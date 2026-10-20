"""Догоняет схему БД до моделей: новые таблицы, недостающие nullable-колонки и индексы.

Нужно, пока в проекте нет миграций Alembic: обновление кода не должно требовать пересоздания базы.
Только добавляет, ничего не удаляет и не меняет типы существующих колонок.
"""
import logging

from sqlalchemy import inspect
from sqlalchemy.schema import CreateIndex

from .db import Base

log = logging.getLogger("schema")


def _default_sql(col, dialect) -> str:
    """SQL значения по умолчанию: text("false") -> false, func.now() -> now(), строка -> 'строка'."""
    arg = col.server_default.arg
    if isinstance(arg, str):
        return "'" + arg.replace("'", "''") + "'"
    if hasattr(arg, "text"):
        return arg.text
    return str(arg.compile(dialect=dialect))


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
            if col.server_default is not None:
                # значение по умолчанию: PostgreSQL сразу проставит его в уже существующих строках
                ddl += f" DEFAULT {_default_sql(col, conn.dialect)}"
                if not col.nullable:
                    ddl += " NOT NULL"
            conn.exec_driver_sql(ddl)
            changes.append(ddl)
        # ремонт: колонка уже есть, но добавлена без значения по умолчанию (старая версия этого кода)
        cols = {c["name"]: c for c in insp.get_columns(table.name)}
        for col in table.columns:
            info = cols.get(col.name)
            if info is None or col.server_default is None or col.name in [c.name for c in table.primary_key]:
                continue
            default = _default_sql(col, conn.dialect)
            if info.get("default") is None:
                conn.exec_driver_sql(f"ALTER TABLE {q(table.name)} ALTER COLUMN {q(col.name)} SET DEFAULT {default}")
                changes.append(f"{table.name}.{col.name}: DEFAULT {default}")
            if not col.nullable and info.get("nullable"):
                filled = conn.exec_driver_sql(
                    f"UPDATE {q(table.name)} SET {q(col.name)} = {default} WHERE {q(col.name)} IS NULL").rowcount
                conn.exec_driver_sql(f"ALTER TABLE {q(table.name)} ALTER COLUMN {q(col.name)} SET NOT NULL")
                changes.append(f"{table.name}.{col.name}: заполнено {filled} пустых, NOT NULL")
        for idx in table.indexes:
            conn.execute(CreateIndex(idx, if_not_exists=True))
    changes += _fill_player_numbers(conn)
    for ch in changes:
        log.info("schema: %s", ch)
    return changes


def _fill_player_numbers(conn) -> list[str]:
    """Аккаунтам, созданным до появления номеров, выдаём номера по порядку регистрации. Гостям номер не нужен."""
    if conn.dialect.name != "postgresql":
        return []
    filled = conn.exec_driver_sql(
        "UPDATE users u SET player_no = s.n FROM ("
        "  SELECT id, nextval('player_no_seq') AS n FROM ("
        "    SELECT id FROM users WHERE player_no IS NULL AND NOT is_guest ORDER BY id) q) s "
        "WHERE u.id = s.id").rowcount
    return [f"users.player_no: выдано номеров {filled}"] if filled else []
