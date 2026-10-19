from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import require_admin
from ..models import OutboxMessage, OutboxStatus, User

router = APIRouter(prefix="/admin/outbox", tags=["admin"])


@router.get("")
async def list_outbox(status: OutboxStatus = OutboxStatus.failed, limit: int = Query(50, ge=1, le=200),
                      admin: User = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(OutboxMessage).where(OutboxMessage.status == status)
                                  .order_by(OutboxMessage.id.desc()).limit(limit))).scalars()
    return [{"id": m.id, "kind": m.kind, "chat_id": m.chat_id, "attempts": m.attempts, "error": m.last_error,
             "created_at": m.created_at, "sent_at": m.sent_at, "preview": m.text[:120]} for m in rows]


@router.post("/{msg_id}/retry", status_code=204)
async def retry(msg_id: int, admin: User = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    m = await session.get(OutboxMessage, msg_id)
    if not m:
        raise HTTPException(404, "Сообщение не найдено")
    m.status, m.attempts, m.next_attempt_at = OutboxStatus.pending, 0, datetime.now(timezone.utc)
    await session.commit()
