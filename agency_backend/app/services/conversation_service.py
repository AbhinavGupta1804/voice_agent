"""Service for conversation threads and messages (WhatsApp/SMS)."""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import asyncpg

from ..db.postgres import get_db_pool

logger = logging.getLogger(__name__)

CHANNEL_WHATSAPP = "whatsapp"
CHANNEL_SMS = "sms"
CHANNEL_EMAIL = "email"
SENDER_BOT = "bot"
SENDER_CLIENT = "client"
SENDER_USER = "user"
DIRECTION_INBOUND = "inbound"
DIRECTION_OUTBOUND = "outbound"


class ConversationService:
    """CRUD for conversation_threads and conversation_messages."""

    @staticmethod
    async def get_or_create_thread(
        phone_number: Optional[str] = None,
        channel: str = "whatsapp",
        display_name: Optional[str] = None,
        email_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get existing thread by (phone_number, channel) or (email_address, channel) or create one."""
        pool = await get_db_pool()
        if channel not in (CHANNEL_WHATSAPP, CHANNEL_SMS, CHANNEL_EMAIL):
            raise ValueError("channel must be 'whatsapp', 'sms', or 'email'")
        if channel == CHANNEL_EMAIL:
            if not email_address or not email_address.strip():
                raise ValueError("email_address required for channel 'email'")
            email_address = email_address.strip().lower()
            phone_number = None
        else:
            if not phone_number or not str(phone_number).strip():
                raise ValueError("phone_number required for whatsapp/sms")
            phone_number = str(phone_number).strip()
            email_address = None
        try:
            async with pool.acquire() as conn:
                if channel == CHANNEL_EMAIL:
                    row = await conn.fetchrow(
                        """
                        INSERT INTO conversation_threads (phone_number, channel, display_name, email_address, created_at, updated_at)
                        VALUES (NULL, 'email', $1, $2, NOW(), NOW())
                        ON CONFLICT (email_address, channel) DO UPDATE SET updated_at = NOW()
                        RETURNING id, phone_number, channel, display_name, email_address, created_at, updated_at
                        """,
                        display_name or None,
                        email_address.strip().lower(),
                    )
                else:
                    row = await conn.fetchrow(
                        """
                        INSERT INTO conversation_threads (phone_number, channel, display_name, created_at, updated_at)
                        VALUES ($1, $2, $3, NOW(), NOW())
                        ON CONFLICT (phone_number, channel) DO UPDATE SET updated_at = NOW()
                        RETURNING id, phone_number, channel, display_name, email_address, created_at, updated_at
                        """,
                        phone_number,
                        channel,
                        display_name or None,
                    )
                return dict(row) if row else {}
        except asyncpg.PostgresError as exc:
            logger.error(f"[Conversation] get_or_create_thread failed: {exc}")
            raise

    @staticmethod
    async def get_thread(thread_id: int) -> Optional[Dict[str, Any]]:
        """Get a single thread by id."""
        pool = await get_db_pool()
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT id, phone_number, channel, display_name, email_address, created_at, updated_at FROM conversation_threads WHERE id = $1",
                    thread_id,
                )
                return dict(row) if row else None
        except asyncpg.PostgresError as exc:
            logger.error(f"[Conversation] get_thread failed: {exc}")
            return None

    @staticmethod
    async def list_threads(
        channel: str,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """List threads for a channel, ordered by updated_at desc."""
        pool = await get_db_pool()
        if channel not in (CHANNEL_WHATSAPP, CHANNEL_SMS, CHANNEL_EMAIL):
            raise ValueError("channel must be 'whatsapp', 'sms', or 'email'")
        try:
            async with pool.acquire() as conn:
                total = await conn.fetchval(
                    "SELECT COUNT(*) FROM conversation_threads WHERE channel = $1",
                    channel,
                )
                rows = await conn.fetch(
                    """
                    SELECT id, phone_number, channel, display_name, email_address, created_at, updated_at
                    FROM conversation_threads
                    WHERE channel = $1
                    ORDER BY updated_at DESC
                    LIMIT $2 OFFSET $3
                    """,
                    channel,
                    limit,
                    offset,
                )
                return [dict(r) for r in rows], total or 0
        except asyncpg.PostgresError as exc:
            logger.error(f"[Conversation] list_threads failed: {exc}")
            return [], 0

    @staticmethod
    async def list_messages(
        thread_id: int,
        limit: int = 100,
        before_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """List messages in a thread, oldest first (for chat UI)."""
        pool = await get_db_pool()
        try:
            async with pool.acquire() as conn:
                if before_id is not None:
                    rows = await conn.fetch(
                        """
                        SELECT id, thread_id, body, direction, sender_type, twilio_message_sid, created_at
                        FROM conversation_messages
                        WHERE thread_id = $1 AND id < $2
                        ORDER BY id DESC
                        LIMIT $3
                        """,
                        thread_id,
                        before_id,
                        limit,
                    )
                else:
                    rows = await conn.fetch(
                        """
                        SELECT id, thread_id, body, direction, sender_type, twilio_message_sid, created_at
                        FROM conversation_messages
                        WHERE thread_id = $1
                        ORDER BY id ASC
                        LIMIT $2
                        """,
                        thread_id,
                        limit,
                    )
                out = [dict(r) for r in rows]
                if before_id is not None:
                    out.reverse()
                return out
        except asyncpg.PostgresError as exc:
            logger.error(f"[Conversation] list_messages failed: {exc}")
            return []

    @staticmethod
    async def add_message(
        thread_id: int,
        body: str,
        direction: str,
        sender_type: str,
        twilio_message_sid: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Insert a message and refresh thread updated_at."""
        pool = await get_db_pool()
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO conversation_messages (thread_id, body, direction, sender_type, twilio_message_sid, created_at)
                    VALUES ($1, $2, $3, $4, $5, NOW())
                    RETURNING id, thread_id, body, direction, sender_type, twilio_message_sid, created_at
                    """,
                    thread_id,
                    body.strip(),
                    direction,
                    sender_type,
                    twilio_message_sid,
                )
                if row:
                    await conn.execute(
                        "UPDATE conversation_threads SET updated_at = NOW() WHERE id = $1",
                        thread_id,
                    )
                return dict(row) if row else None
        except asyncpg.PostgresError as exc:
            logger.error(f"[Conversation] add_message failed: {exc}")
            return None

    @staticmethod
    async def get_latest_call_context(phone_number: str) -> Optional[Dict[str, Any]]:
        """Get latest call record for a phone number (for bot context)."""
        pool = await get_db_pool()
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT call_id, client_name, summary, transcript
                    FROM calls
                    WHERE phone_number = $1 OR phone_number = $2
                    ORDER BY call_timestamp DESC
                    LIMIT 1
                    """,
                    phone_number,
                    phone_number.replace("+", "").strip(),
                )
                return dict(row) if row else None
        except asyncpg.PostgresError as exc:
            logger.error(f"[Conversation] get_latest_call_context failed: {exc}")
            return None
