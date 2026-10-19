from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from .. import notify
from ..db import get_session
from ..deps import current_user, is_club_organizer, optional_user, require_admin
from ..models import (Article, ArticleStatus, ArticleTag, Club, Comment, GlobalRole, NewsCategory, Tag, User)
from ..slug import normalize_tags, slugify

router = APIRouter(prefix="/news", tags=["news"])


class CategoryIn(BaseModel):
    name: str = Field(min_length=2, max_length=64)


class ArticleIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    summary: str = Field(default="", max_length=500)
    body_md: str = Field(min_length=1, max_length=100_000)
    club_id: int | None = None            # None = глобальная статья (только админ)
    category: str | None = None           # slug категории
    tags: list[str] = Field(default_factory=list, max_length=20)
    cover_url: str | None = Field(default=None, max_length=512)
    publish: bool = False


class ArticlePatch(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=200)
    summary: str | None = Field(default=None, max_length=500)
    body_md: str | None = Field(default=None, min_length=1, max_length=100_000)
    category: str | None = None
    tags: list[str] | None = Field(default=None, max_length=20)
    cover_url: str | None = Field(default=None, max_length=512)


class CommentIn(BaseModel):
    body: str = Field(min_length=1, max_length=2000)


# ---------- вспомогательное ----------
async def _can_manage(session: AsyncSession, club_id: int | None, user: User | None) -> bool:
    if user is None:
        return False
    if club_id is None:
        return user.role == GlobalRole.admin
    return await is_club_organizer(session, club_id, user)


async def _by_slug(session: AsyncSession, slug: str) -> Article:
    a = (await session.execute(select(Article).where(Article.slug == slug))).scalar_one_or_none()
    if not a:
        raise HTTPException(404, "Статья не найдена")
    return a


async def _by_id(session: AsyncSession, article_id: int) -> Article:
    a = await session.get(Article, article_id)
    if not a:
        raise HTTPException(404, "Статья не найдена")
    return a


async def _category_id(session: AsyncSession, slug: str | None) -> int | None:
    if slug is None:
        return None
    cid = (await session.execute(select(NewsCategory.id).where(NewsCategory.slug == slug))).scalar_one_or_none()
    if cid is None:
        raise HTTPException(400, "Такой категории нет")
    return cid


async def _unique_slug(session: AsyncSession, title: str) -> str:
    base = slugify(title)
    taken = set((await session.execute(select(Article.slug).where(Article.slug.like(f"{base}%")))).scalars())
    if base not in taken:
        return base
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"


async def _set_tags(session: AsyncSession, article_id: int, tags: list[str]):
    pairs = normalize_tags(tags)
    await session.execute(delete(ArticleTag).where(ArticleTag.article_id == article_id))
    if not pairs:
        return
    await session.execute(pg_insert(Tag).values([{"name": n, "slug": s} for n, s in pairs])
                          .on_conflict_do_nothing(index_elements=[Tag.slug]))
    ids = (await session.execute(select(Tag.id).where(Tag.slug.in_([s for _, s in pairs])))).scalars().all()
    session.add_all([ArticleTag(article_id=article_id, tag_id=i) for i in ids])


async def _cards(session: AsyncSession, arts: list[Article]) -> list[dict]:
    if not arts:
        return []
    ids = [a.id for a in arts]
    tags: dict[int, list[dict]] = {}
    for aid, name, slug in (await session.execute(select(ArticleTag.article_id, Tag.name, Tag.slug)
                            .join(Tag, Tag.id == ArticleTag.tag_id).where(ArticleTag.article_id.in_(ids)))).all():
        tags.setdefault(aid, []).append({"name": name, "slug": slug})
    counts = dict((await session.execute(select(Comment.article_id, func.count()).where(
        Comment.article_id.in_(ids), Comment.is_hidden.is_(False)).group_by(Comment.article_id))).all())
    clubs = dict((await session.execute(select(Club.id, Club.name).where(
        Club.id.in_({a.club_id for a in arts if a.club_id})))).all())
    cats = {c.id: {"name": c.name, "slug": c.slug} for c in (await session.execute(select(NewsCategory))).scalars()}
    authors = dict((await session.execute(select(User.id, User.nickname).where(
        User.id.in_({a.author_id for a in arts})))).all())
    return [{"id": a.id, "slug": a.slug, "title": a.title, "summary": a.summary, "cover_url": a.cover_url,
             "status": a.status, "published_at": a.published_at, "club_id": a.club_id,
             "club": clubs.get(a.club_id), "category": cats.get(a.category_id), "tags": tags.get(a.id, []),
             "author": authors.get(a.author_id), "comments": counts.get(a.id, 0)} for a in arts]


# ---------- категории ----------
@router.get("/categories")
async def categories(session: AsyncSession = Depends(get_session)):
    res = await session.execute(select(NewsCategory).order_by(NewsCategory.name))
    return [{"name": c.name, "slug": c.slug} for c in res.scalars()]


@router.post("/categories", status_code=201)
async def create_category(data: CategoryIn, admin: User = Depends(require_admin),
                          session: AsyncSession = Depends(get_session)):
    slug = slugify(data.name, 64)
    if (await session.execute(select(NewsCategory).where(
            or_(NewsCategory.slug == slug, NewsCategory.name == data.name)))).scalar_one_or_none():
        raise HTTPException(409, "Такая категория уже есть")
    session.add(NewsCategory(name=data.name, slug=slug))
    await session.commit()
    return {"slug": slug}


# ---------- лента ----------
@router.get("")
async def feed(club_id: int | None = None, scope: str = Query("all", pattern="^(all|global)$"),
               category: str | None = None, tag: str | None = None, q: str | None = None,
               limit: int = Query(20, ge=1, le=50), offset: int = Query(0, ge=0),
               session: AsyncSession = Depends(get_session)):
    """Опубликованные статьи. club_id - новости клуба; scope=global - только глобальные."""
    stmt = select(Article).where(Article.status == ArticleStatus.published)
    if club_id:
        stmt = stmt.where(Article.club_id == club_id)
    elif scope == "global":
        stmt = stmt.where(Article.club_id.is_(None))
    if category:
        stmt = stmt.where(Article.category_id.in_(select(NewsCategory.id).where(NewsCategory.slug == category)))
    if tag:
        stmt = stmt.where(Article.id.in_(select(ArticleTag.article_id).join(Tag, Tag.id == ArticleTag.tag_id)
                                         .where(Tag.slug == tag)))
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Article.title.ilike(like), Article.summary.ilike(like)))
    arts = (await session.execute(stmt.order_by(Article.published_at.desc()).limit(limit).offset(offset))).scalars().all()
    return await _cards(session, list(arts))


@router.get("/mine")
async def my_articles(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    """Мои статьи, включая черновики."""
    arts = (await session.execute(select(Article).where(Article.author_id == user.id)
                                  .order_by(Article.created_at.desc()).limit(100))).scalars().all()
    return await _cards(session, list(arts))


@router.get("/{slug}")
async def read_article(slug: str, user: User | None = Depends(optional_user),
                       session: AsyncSession = Depends(get_session)):
    a = await _by_slug(session, slug)
    if a.status != ArticleStatus.published and not (user and (user.id == a.author_id
                                                               or await _can_manage(session, a.club_id, user))):
        raise HTTPException(404, "Статья не найдена")
    card = (await _cards(session, [a]))[0]
    return {**card, "body_md": a.body_md, "updated_at": a.updated_at}


# ---------- управление статьями ----------
@router.post("", status_code=201)
async def create_article(data: ArticleIn, user: User = Depends(current_user),
                         session: AsyncSession = Depends(get_session)):
    if not await _can_manage(session, data.club_id, user):
        raise HTTPException(403, "Глобальные статьи - только админ, новости клуба - организатор клуба")
    if data.club_id is not None and not await session.get(Club, data.club_id):
        raise HTTPException(404, "Клуб не найден")
    a = Article(club_id=data.club_id, author_id=user.id, title=data.title, summary=data.summary,
                body_md=data.body_md, cover_url=data.cover_url, category_id=await _category_id(session, data.category),
                slug=await _unique_slug(session, data.title))
    if data.publish:
        a.status, a.published_at = ArticleStatus.published, datetime.now(timezone.utc)
    session.add(a)
    await session.flush()
    await _set_tags(session, a.id, data.tags)
    if a.status == ArticleStatus.published:
        await notify.on_article_published(session, a)
    await session.commit()
    return {"id": a.id, "slug": a.slug, "status": a.status}


@router.patch("/{article_id}", status_code=204)
async def update_article(article_id: int, data: ArticlePatch, user: User = Depends(current_user),
                         session: AsyncSession = Depends(get_session)):
    a = await _by_id(session, article_id)
    if not await _can_manage(session, a.club_id, user):
        raise HTTPException(403, "Нет прав на редактирование")
    fields = data.model_dump(exclude_unset=True)
    for key in ("title", "summary", "body_md", "cover_url"):
        if key in fields and (fields[key] is not None or key == "cover_url"):
            setattr(a, key, fields[key])
    if "category" in fields:
        a.category_id = await _category_id(session, fields["category"])
    if fields.get("tags") is not None:
        await _set_tags(session, a.id, fields["tags"])
    await session.commit()


@router.post("/{article_id}/publish", status_code=204)
async def publish(article_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    a = await _by_id(session, article_id)
    if not await _can_manage(session, a.club_id, user):
        raise HTTPException(403, "Нет прав")
    a.status = ArticleStatus.published
    a.published_at = a.published_at or datetime.now(timezone.utc)
    await notify.on_article_published(session, a)
    await session.commit()


@router.post("/{article_id}/unpublish", status_code=204)
async def unpublish(article_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    a = await _by_id(session, article_id)
    if not await _can_manage(session, a.club_id, user):
        raise HTTPException(403, "Нет прав")
    a.status = ArticleStatus.draft
    await session.commit()


@router.delete("/{article_id}", status_code=204)
async def delete_article(article_id: int, user: User = Depends(current_user),
                         session: AsyncSession = Depends(get_session)):
    a = await _by_id(session, article_id)
    if not await _can_manage(session, a.club_id, user):
        raise HTTPException(403, "Нет прав")
    await session.delete(a)
    await session.commit()


# ---------- комментарии ----------
@router.get("/{slug}/comments")
async def list_comments(slug: str, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
                        user: User | None = Depends(optional_user), session: AsyncSession = Depends(get_session)):
    a = await _by_slug(session, slug)
    if a.status != ArticleStatus.published:
        raise HTTPException(404, "Статья не найдена")
    moderator = await _can_manage(session, a.club_id, user)
    stmt = (select(Comment, User.nickname).join(User, User.id == Comment.user_id).where(Comment.article_id == a.id))
    if not moderator:
        stmt = stmt.where(Comment.is_hidden.is_(False))
    rows = (await session.execute(stmt.order_by(Comment.created_at).limit(limit).offset(offset))).all()
    return [{"id": c.id, "user_id": c.user_id, "nickname": nick, "body": c.body, "created_at": c.created_at,
             **({"is_hidden": c.is_hidden} if moderator else {})} for c, nick in rows]


@router.post("/{slug}/comments", status_code=201)
async def add_comment(slug: str, data: CommentIn, user: User = Depends(current_user),
                      session: AsyncSession = Depends(get_session)):
    a = await _by_slug(session, slug)
    if a.status != ArticleStatus.published:
        raise HTTPException(404, "Статья не найдена")
    body = data.body.strip()
    if not body:
        raise HTTPException(422, "Пустой комментарий")
    recent = (await session.execute(select(func.count()).select_from(Comment).where(
        Comment.user_id == user.id, Comment.created_at > datetime.now(timezone.utc) - timedelta(minutes=1)))).scalar_one()
    if recent >= 5:
        raise HTTPException(429, "Слишком часто: подождите минуту")
    c = Comment(article_id=a.id, user_id=user.id, body=body)
    session.add(c)
    await session.commit()
    return {"id": c.id}


async def _comment_and_mod(session: AsyncSession, comment_id: int, user: User) -> tuple[Comment, bool]:
    c = await session.get(Comment, comment_id)
    if not c:
        raise HTTPException(404, "Комментарий не найден")
    a = await session.get(Article, c.article_id)
    return c, await _can_manage(session, a.club_id, user)


@router.delete("/comments/{comment_id}", status_code=204)
async def delete_comment(comment_id: int, user: User = Depends(current_user),
                         session: AsyncSession = Depends(get_session)):
    c, mod = await _comment_and_mod(session, comment_id, user)
    if c.user_id != user.id and not mod:
        raise HTTPException(403, "Нет прав")
    await session.delete(c)
    await session.commit()


@router.post("/comments/{comment_id}/hide", status_code=204)
async def hide_comment(comment_id: int, user: User = Depends(current_user),
                       session: AsyncSession = Depends(get_session)):
    c, mod = await _comment_and_mod(session, comment_id, user)
    if not mod:
        raise HTTPException(403, "Нужны права модератора")
    c.is_hidden = True
    await session.commit()


@router.post("/comments/{comment_id}/unhide", status_code=204)
async def unhide_comment(comment_id: int, user: User = Depends(current_user),
                         session: AsyncSession = Depends(get_session)):
    c, mod = await _comment_and_mod(session, comment_id, user)
    if not mod:
        raise HTTPException(403, "Нужны права модератора")
    c.is_hidden = False
    await session.commit()
