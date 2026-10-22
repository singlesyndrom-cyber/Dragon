import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.exc import InterfaceError, OperationalError

from .config import settings
from .db import engine
from .schema import sync_schema
from .routers import auctions, auth, cards, clubs, creators, decks, edh, leagues, meta, news, outbox, players, tables, tournaments

log = logging.getLogger("startup")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.auto_create_tables:  # только для разработки; в проде схему ведёт Alembic
        for attempt in range(30):            # база могла ещё не подняться после перезапуска контейнеров
            try:
                async with engine.begin() as conn:
                    await conn.run_sync(sync_schema)   # новые таблицы и колонки без пересоздания базы
                break
            except (OSError, InterfaceError, OperationalError) as e:
                if attempt == 29:
                    raise
                log.warning("база недоступна (%s), повтор через 2 с", e)
                await asyncio.sleep(2)
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
app.include_router(players.router)
app.include_router(creators.router)
app.include_router(tables.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
