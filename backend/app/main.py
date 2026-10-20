import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import settings
from .db import engine
from .schema import sync_schema
from .routers import auctions, auth, cards, clubs, decks, edh, leagues, meta, news, outbox, tournaments


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.auto_create_tables:  # только для разработки; в проде схему ведёт Alembic
        async with engine.begin() as conn:
            await conn.run_sync(sync_schema)   # новые таблицы и колонки без пересоздания базы
    expirer = asyncio.create_task(edh.expire_overdue_loop())  # авто-закрытие столов по таймеру 70 минут
    yield
    expirer.cancel()


app = FastAPI(title="KKI Platform", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(clubs.router)
app.include_router(tournaments.router)
app.include_router(edh.router)
app.include_router(cards.router)
app.include_router(decks.router)
app.include_router(meta.router)
app.include_router(news.router)
app.include_router(outbox.router)
app.include_router(auctions.router)
app.include_router(leagues.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
