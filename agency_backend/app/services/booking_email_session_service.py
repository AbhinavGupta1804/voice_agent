"""Redis-backed sessions for WhatsApp email collection during voice booking."""
import asyncio
import json
import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional

from ..config import Config
from ..db.redis_client import get_redis
from ..utils.phone_utils import normalize_phone_number

logger = logging.getLogger(__name__)


class SessionStatus(str, Enum):
    PENDING = "pending"
    EMAIL_RECEIVED = "email_received"
    EXPIRED = "expired"
    FAILED = "failed"


def _session_key(call_id: str) -> str:
    return f"booking_email:session:{call_id}"


def _phone_index_key(phone: str) -> str:
    digits = normalize_phone_number(phone).lstrip("+")
    return f"booking_email:phone:{digits}"


class BookingEmailSessionService:
    """Store and retrieve booking email collection state in Redis."""

    @classmethod
    async def create_session(
        cls,
        call_id: str,
        phone: str,
        customer_name: str,
        selected_time: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new pending session (replaces any prior session for this call)."""
        if not call_id:
            raise ValueError("call_id is required")

        normalized_phone = normalize_phone_number(phone)
        now = datetime.now(timezone.utc).isoformat()
        session: Dict[str, Any] = {
            "call_id": call_id,
            "phone": normalized_phone,
            "customer_name": customer_name or "",
            "selected_time": selected_time or "",
            "status": SessionStatus.PENDING.value,
            "email": "",
            "ready": False,
            "created_at": now,
            "updated_at": now,
        }

        redis = await get_redis()
        ttl = Config.BOOKING_EMAIL_SESSION_TTL_SECONDS
        pipe = redis.pipeline()
        pipe.set(_session_key(call_id), json.dumps(session), ex=ttl)
        pipe.set(_phone_index_key(normalized_phone), call_id, ex=ttl)
        await pipe.execute()

        logger.info(
            "[BookingEmailSession] created call_id=%s phone=%s name=%s",
            call_id,
            normalized_phone,
            customer_name,
        )
        return session

    @classmethod
    async def get_session(cls, call_id: str) -> Optional[Dict[str, Any]]:
        """Load session by call_id."""
        if not call_id:
            return None
        redis = await get_redis()
        raw = await redis.get(_session_key(call_id))
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.error("[BookingEmailSession] corrupt session call_id=%s", call_id)
            return None

    @classmethod
    async def get_active_session_by_phone(cls, phone: str) -> Optional[Dict[str, Any]]:
        """Resolve the active session for an inbound WhatsApp number."""
        normalized = normalize_phone_number(phone)
        redis = await get_redis()
        call_id = await redis.get(_phone_index_key(normalized))
        if not call_id:
            return None
        session = await cls.get_session(call_id)
        if not session:
            return None
        if session.get("status") == SessionStatus.PENDING.value:
            return session
        return None

    @classmethod
    async def set_email_received(cls, call_id: str, email: str) -> Optional[Dict[str, Any]]:
        """Mark session as having received a valid email."""
        session = await cls.get_session(call_id)
        if not session:
            logger.warning("[BookingEmailSession] set_email: no session call_id=%s", call_id)
            return None

        session["email"] = email
        session["status"] = SessionStatus.EMAIL_RECEIVED.value
        session["ready"] = True
        session["updated_at"] = datetime.now(timezone.utc).isoformat()

        redis = await get_redis()
        ttl = Config.BOOKING_EMAIL_SESSION_TTL_SECONDS
        await redis.set(_session_key(call_id), json.dumps(session), ex=ttl)

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

    @classmethod
    async def wait_for_email(
        cls,
        call_id: str,
        timeout_seconds: Optional[int] = None,
        poll_interval_seconds: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Block until email is received in Redis or timeout (Option 2 long-poll).

        Used by collect_email_via_whatsapp while the voice call holds on the tool.
        """
        timeout = timeout_seconds or Config.BOOKING_EMAIL_WAIT_TIMEOUT_SECONDS
        interval = poll_interval_seconds or Config.BOOKING_EMAIL_POLL_INTERVAL_SECONDS
        elapsed = 0.0

        while elapsed < timeout:
            session = await cls.get_session(call_id)
            if session and session.get("status") == SessionStatus.EMAIL_RECEIVED.value:
                email = session.get("email") or ""
                if email:
                    logger.info(
                        "[BookingEmailSession] wait_for_email done call_id=%s elapsed=%.1fs",
                        call_id,
                        elapsed,
                    )
                    return {
                        "status": SessionStatus.EMAIL_RECEIVED.value,
                        "email": email,
                        "ready": True,
                        "call_id": call_id,
                    }

            await asyncio.sleep(interval)
            elapsed += interval

        logger.warning(
            "[BookingEmailSession] wait_for_email timeout call_id=%s after %ss",
            call_id,
            timeout,
        )
        return {
            "status": "timeout",
            "email": "",
            "ready": False,
            "call_id": call_id,
            "message": "Timed out waiting for WhatsApp email reply.",
        }
