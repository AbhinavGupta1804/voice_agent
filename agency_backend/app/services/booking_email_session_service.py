"""PostgreSQL-backed sessions for WhatsApp email collection during voice booking."""
import logging
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, Optional

from ..config import Config
from ..db.postgres import get_db_pool
from ..utils.phone_utils import normalize_phone_number

logger = logging.getLogger(__name__)


class SessionStatus(str, Enum):
    PENDING = "pending"
    EMAIL_RECEIVED = "email_received"
    EXPIRED = "expired"
    FAILED = "failed"


def _row_to_session(row) -> Dict[str, Any]:
    """Map asyncpg row to session dict (matches former Redis JSON shape)."""
    email = row["email"] or ""
    status = row["status"]
    return {
        "call_id": row["call_id"],
        "phone": row["phone"],
        "customer_name": row["customer_name"] or "",
        "selected_time": row["selected_time"] or "",
        "status": status,
        "email": email,
        "ready": status == SessionStatus.EMAIL_RECEIVED.value and bool(email),
        "created_at": row["created_at"].isoformat() if row["created_at"] else "",
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else "",
        "expires_at": row["expires_at"].isoformat() if row["expires_at"] else "",
    }


class BookingEmailSessionService:
    """Store and retrieve booking email collection state in PostgreSQL."""

    @classmethod
    async def create_session(
        cls,
        call_id: str,
        phone: str,
        customer_name: str,
        selected_time: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create or replace a pending session for this call."""
        if not call_id:
            raise ValueError("call_id is required")

        normalized_phone = normalize_phone_number(phone)
        ttl_seconds = Config.BOOKING_EMAIL_SESSION_TTL_SECONDS
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=ttl_seconds)

        pool = await get_db_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    UPDATE booking_email_sessions
                    SET status = $1, updated_at = NOW()
                    WHERE phone = $2 AND status = $3 AND expires_at > NOW()
                    """,
                    SessionStatus.EXPIRED.value,
                    normalized_phone,
                    SessionStatus.PENDING.value,
                )
                row = await conn.fetchrow(
                    """
                    INSERT INTO booking_email_sessions (
                        call_id, phone, customer_name, selected_time,
                        status, email, created_at, updated_at, expires_at
                    ) VALUES ($1, $2, $3, $4, $5, '', $6, $6, $7)
                    ON CONFLICT (call_id) DO UPDATE SET
                        phone = EXCLUDED.phone,
                        customer_name = EXCLUDED.customer_name,
                        selected_time = EXCLUDED.selected_time,
                        status = EXCLUDED.status,
                        email = '',
                        updated_at = EXCLUDED.updated_at,
                        expires_at = EXCLUDED.expires_at
                    RETURNING *
                    """,
                    call_id,
                    normalized_phone,
                    customer_name or "",
                    selected_time or "",
                    SessionStatus.PENDING.value,
                    now,
                    expires_at,
                )

        session = _row_to_session(row)
        logger.info(
            "[BookingEmailSession] created call_id=%s phone=%s name=%s",
            call_id,
            normalized_phone,
            customer_name,
        )
        return session

    @classmethod
    async def get_session(cls, call_id: str) -> Optional[Dict[str, Any]]:
        """Load active (non-expired) session by call_id."""
        if not call_id:
            return None
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM booking_email_sessions
                WHERE call_id = $1 AND expires_at > NOW()
                """,
                call_id,
            )
        if not row:
            return None
        return _row_to_session(row)

    @classmethod
    async def get_active_session_by_phone(cls, phone: str) -> Optional[Dict[str, Any]]:
        """Resolve the newest pending session for an inbound WhatsApp number."""
        normalized = normalize_phone_number(phone)
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM booking_email_sessions
                WHERE phone = $1
                  AND status = $2
                  AND expires_at > NOW()
                ORDER BY created_at DESC
                LIMIT 1
                """,
                normalized,
                SessionStatus.PENDING.value,
            )
        if not row:
            return None
        return _row_to_session(row)

    @classmethod
    async def set_email_received(cls, call_id: str, email: str) -> Optional[Dict[str, Any]]:
        """Mark session as having received a valid email."""
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE booking_email_sessions
                SET email = $2,
                    status = $3,
                    updated_at = NOW()
                WHERE call_id = $1 AND expires_at > NOW()
                RETURNING *
                """,
                call_id,
                email,
                SessionStatus.EMAIL_RECEIVED.value,
            )
        if not row:
            logger.warning("[BookingEmailSession] set_email: no session call_id=%s", call_id)
            return None

        session = _row_to_session(row)
        logger.info("[BookingEmailSession] email_received call_id=%s email=%s", call_id, email)
        return session

    @classmethod
    async def to_status_response(cls, call_id: str) -> Dict[str, Any]:
        """
        Public status payload for Retell polling (non-blocking GET).

        Retell maps `email` -> dynamic variable via response_variables.
        """
        session = await cls.get_session(call_id)
        if not session:
            return {
                "call_id": call_id,
                "status": SessionStatus.EXPIRED.value,
                "email": "",
                "ready": False,
                "message": "No active session found for this call.",
            }

        status = session.get("status", SessionStatus.PENDING.value)
        email = session.get("email") or ""
        ready = status == SessionStatus.EMAIL_RECEIVED.value and bool(email)

        return {
            "call_id": call_id,
            "status": status,
            "email": email,
            "ready": ready,
            "customer_name": session.get("customer_name", ""),
            "selected_time": session.get("selected_time", ""),
            "message": (
                "Email received."
                if ready
                else "Waiting for WhatsApp reply with email address."
            ),
        }
