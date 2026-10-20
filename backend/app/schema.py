"""Догоняет схему БД до моделей: новые таблицы, недостающие nullable-колонки и индексы.

Нужно, пока в проекте нет миграций Alembic: обновление кода не должно требовать пересоздания базы.
Только добавляет, ничего не удаляет и не меняет типы существующих колонок.
"""
import logging

from sqlalchemy import inspect
from sqlalchemy.schema import CreateIndex

from .db import Base

log = logging.getLogger("schema")


def sync_schema(conn) -> list[str]:
    """Вызывать через conn.run_sync(sync_schema). Возвращает список выполненных изменений."""
    import app.models  # noqa: F401  регистрирует все таблицы

    Base.metadata.create_all(conn)
    insp = inspect(conn)
    q = conn.dialect.identifier_preparer.quote
    changes = []
    for table in Base.metadata.sorted_tables:
        existing = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name in existing:
                continue
            if not col.nullable and col.server_default is None:
                log.warning("колонку %s.%s нужно добавить миграцией (NOT NULL без значения по умолчанию)",
                            table.name, col.name)
                continue
            ddl = (f"ALTER TABLE {q(table.name)} ADD COLUMN IF NOT EXISTS {q(col.name)} "
                   f"{col.type.compile(dialect=conn.dialect)}")
            conn.exec_driver_sql(ddl)
            changes.append(ddl)
        for idx in table.indexes:
            conn.execute(CreateIndex(idx, if_not_exists=True))
    for ch in changes:
        log.info("schema: %s", ch)
    return changes
