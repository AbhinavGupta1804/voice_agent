"""Service layer for scheduled follow-up operations."""
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import asyncpg

from ..db.postgres import acquire_connection
from ..config import Config

logger = logging.getLogger(__name__)


class ScheduledFollowUpService:
    """PostgreSQL-backed operations for scheduled follow-ups."""

    @staticmethod
    async def create_follow_up(
        call_id: str,
        phone_number: str,
        client_name: str,
        scheduled_at: datetime,
        context: dict = None,
        follow_up_first_message: Optional[str] = None,
    ) -> Optional[int]:
        """
        Create a new scheduled follow-up.
        
        Args:
            call_id: Original call ID
            phone_number: Phone number to call
            client_name: Client name
            scheduled_at: When to execute the follow-up
            context: Additional context (summary, notes, etc.)
            follow_up_first_message: Optional first message for the agent on the follow-up call (LLM-generated for continuity).
            
        Returns:
            follow_up_id if successful, None otherwise
        """
        if not Config.FOLLOW_UP_CALLS_ENABLED:
            logger.info("[FollowUp] Skipping create (FOLLOW_UP_CALLS_ENABLED=false) call_id=%s", call_id)
            return None
        try:
            async with acquire_connection() as conn:
                import json
                follow_up_id = await conn.fetchval("""
                    INSERT INTO scheduled_follow_ups 
                    (call_id, phone_number, client_name, scheduled_at, context, status, follow_up_first_message)
                    VALUES ($1, $2, $3, $4, $5, 'pending', $6)
                    ON CONFLICT (call_id) WHERE status IN ('pending', 'processing')
                    DO UPDATE SET 
                        scheduled_at = EXCLUDED.scheduled_at,
                        context = EXCLUDED.context,
                        follow_up_first_message = COALESCE(EXCLUDED.follow_up_first_message, scheduled_follow_ups.follow_up_first_message)
                    RETURNING id
                """, call_id, phone_number, client_name, scheduled_at,
                    json.dumps(context) if context else None,
                    follow_up_first_message)
                
                logger.info(f"[FollowUp] Created/updated follow-up id={follow_up_id} for call_id={call_id} at {scheduled_at}")
                return follow_up_id
                
        except asyncpg.PostgresError as exc:
            logger.error(f"[FollowUp] Failed to create follow-up for call_id={call_id}: {exc}")
            return None

    @staticmethod
    async def get_due_follow_ups(limit: int = 100) -> List[Dict]:
        """
        Get all pending follow-ups that are due for execution.
        
        Args:
            limit: Maximum number of follow-ups to fetch
            
        Returns:
            List of follow-up records
        """
        try:
            async with acquire_connection() as conn:
                rows = await conn.fetch("""
                    SELECT id, call_id, phone_number, client_name, scheduled_at, context, retry_count, follow_up_first_message
                    FROM scheduled_follow_ups
                    WHERE status = 'pending'
                    AND scheduled_at <= NOW()
                    ORDER BY scheduled_at
                    LIMIT $1
                """, limit)
                
                return [dict(row) for row in rows]
                
        except asyncpg.PostgresError as exc:
            logger.error(f"[FollowUp] Failed to fetch due follow-ups: {exc}")
            return []

    @staticmethod
    async def list_follow_ups(
        limit: int = 50,
        offset: int = 0,
        status: Optional[str] = None,
    ) -> tuple[List[Dict], int]:
        """
        List scheduled follow-ups with optional status filter and pagination.

        Args:
            limit: Maximum number of records to return
            offset: Number of records to skip
            status: Optional status filter (pending, processing, completed, failed, cancelled)

        Returns:
            Tuple of (list of follow-up dicts, total count)
        """
        try:
            async with acquire_connection() as conn:
                if status:
                    total = await conn.fetchval(
                        "SELECT COUNT(*) FROM scheduled_follow_ups WHERE status = $1",
                        status,
                    )
                    rows = await conn.fetch(
                        """
                        SELECT id, call_id, phone_number, client_name, scheduled_at, status,
                               retry_count, max_retries, last_error, context, created_at, executed_at
                        FROM scheduled_follow_ups
                        WHERE status = $1
                        ORDER BY scheduled_at DESC
                        LIMIT $2 OFFSET $3
                        """,
                        status,
                        limit,
                        offset,
                    )
                else:
                    total = await conn.fetchval("SELECT COUNT(*) FROM scheduled_follow_ups")
                    rows = await conn.fetch(
                        """
                        SELECT id, call_id, phone_number, client_name, scheduled_at, status,
                               retry_count, max_retries, last_error, context, created_at, executed_at
                        FROM scheduled_follow_ups
                        ORDER BY scheduled_at DESC
                        LIMIT $1 OFFSET $2
                        """,
                        limit,
                        offset,
                    )

                def _parse_context(raw: Any) -> Optional[Dict[str, Any]]:
                    if raw is None:
                        return None
                    if isinstance(raw, dict):
                        return raw
                    if isinstance(raw, str):
                        try:
                            return json.loads(raw)
                        except (json.JSONDecodeError, TypeError):
                            return None
                    return None

                def row_to_dict(row) -> dict:
                    return {
                        "id": row["id"],
                        "call_id": row["call_id"] or "",
                        "phone_number": row["phone_number"],
                        "client_name": row["client_name"],
                        "scheduled_at": row["scheduled_at"],
                        "status": row["status"],
                        "retry_count": row["retry_count"],
                        "max_retries": row.get("max_retries", 3),
                        "last_error": row["last_error"],
                        "context": _parse_context(row["context"]),
                        "created_at": row["created_at"],
                        "executed_at": row["executed_at"],
                    }

                return [row_to_dict(r) for r in rows], total or 0

        except asyncpg.PostgresError as exc:
            logger.error(f"[FollowUp] Failed to list follow-ups: {exc}")
            return [], 0

    @staticmethod
    async def update_status(follow_up_id: int, status: str, error: str = None) -> bool:
        """
        Update follow-up status.
        
        Args:
            follow_up_id: Follow-up ID
            status: New status ('processing', 'completed', 'failed')
            error: Error message if status is 'failed'
            
        Returns:
            True if successful, False otherwise
        """
        try:
            async with acquire_connection() as conn:
                if status == 'completed':
                    await conn.execute("""
                        UPDATE scheduled_follow_ups 
                        SET status = $1, executed_at = NOW()
                        WHERE id = $2
                    """, status, follow_up_id)
                elif status == 'failed':
                    await conn.execute("""
                        UPDATE scheduled_follow_ups 
                        SET status = $1, last_error = $2, retry_count = retry_count + 1
                        WHERE id = $3
                    """, status, error, follow_up_id)
                elif status == 'not_picked':
                    await conn.execute("""
                        UPDATE scheduled_follow_ups 
                        SET status = $1, executed_at = NOW()
                        WHERE id = $2
                    """, status, follow_up_id)
                else:
                    await conn.execute("""
                        UPDATE scheduled_follow_ups 
                        SET status = $1
                        WHERE id = $2
                    """, status, follow_up_id)
                
                logger.info(f"[FollowUp] Updated follow-up id={follow_up_id} to status={status}")
                return True
                
        except asyncpg.PostgresError as exc:
            logger.error(f"[FollowUp] Failed to update status for id={follow_up_id}: {exc}")
            return False

    @staticmethod
    async def retry_failed_follow_up(follow_up_id: int, retry_delay_minutes: int = 15) -> bool:
        """
        Reset a failed follow-up for retry.
        
        Args:
            follow_up_id: Follow-up ID
            retry_delay_minutes: Minutes to wait before retry
            
        Returns:
            True if rescheduled, False otherwise
        """
        try:
            async with acquire_connection() as conn:
                result = await conn.execute("""
                    UPDATE scheduled_follow_ups 
                    SET status = 'pending', 
                        scheduled_at = NOW() + INTERVAL '%s minutes'
                    WHERE id = $1 AND retry_count < max_retries
                """ % retry_delay_minutes, follow_up_id)
                
                return result.split()[-1] != '0'
                
        except asyncpg.PostgresError as exc:
            logger.error(f"[FollowUp] Failed to retry follow-up id={follow_up_id}: {exc}")
            return False

    @staticmethod
    async def mark_not_picked_if_max_retries(follow_up_id: int) -> bool:
        """
        If follow-up has retry_count >= max_retries, set status to 'not_picked'.
        Call this after update_status(follow_up_id, 'failed', error).
        """
        try:
            async with acquire_connection() as conn:
                result = await conn.execute("""
                    UPDATE scheduled_follow_ups
                    SET status = 'not_picked', executed_at = NOW()
                    WHERE id = $1 AND retry_count >= max_retries
                """, follow_up_id)
                return result.split()[-1] != '0'
        except asyncpg.PostgresError as exc:
            logger.error(f"[FollowUp] Failed to mark not_picked for id={follow_up_id}: {exc}")
            return False

    @staticmethod
    async def cancel_all_active(reason: str = "disabled by admin") -> int:
        """Cancel all pending/processing follow-ups. Returns number of rows updated."""
        try:
            async with acquire_connection() as conn:
                result = await conn.execute(
                    """
                    UPDATE scheduled_follow_ups
                    SET status = 'cancelled',
                        last_error = $1,
                        executed_at = NOW()
                    WHERE status IN ('pending', 'processing')
                    """,
                    reason,
                )
                count = int(result.split()[-1]) if result else 0
                logger.info("[FollowUp] Cancelled %s active follow-up(s)", count)
                return count
        except asyncpg.PostgresError as exc:
            logger.error("[FollowUp] Failed to cancel active follow-ups: %s", exc)
            return 0
