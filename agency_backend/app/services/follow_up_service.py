"""Service layer for scheduled follow-up operations."""
import logging
from datetime import datetime
from typing import Dict, List, Optional

import asyncpg

from ..db.postgres import get_db_pool

logger = logging.getLogger(__name__)


class ScheduledFollowUpService:
    """PostgreSQL-backed operations for scheduled follow-ups."""

    @staticmethod
    async def create_follow_up(
        call_id: str,
        phone_number: str,
        client_name: str,
        scheduled_at: datetime,
        context: dict = None
    ) -> Optional[int]:
        """
        Create a new scheduled follow-up.
        
        Args:
            call_id: Original call ID
            phone_number: Phone number to call
            client_name: Client name
            scheduled_at: When to execute the follow-up
            context: Additional context (summary, notes, etc.)
            
        Returns:
            follow_up_id if successful, None otherwise
        """
        pool = await get_db_pool()
        
        try:
            async with pool.acquire() as conn:
                import json
                follow_up_id = await conn.fetchval("""
                    INSERT INTO scheduled_follow_ups 
                    (call_id, phone_number, client_name, scheduled_at, context, status)
                    VALUES ($1, $2, $3, $4, $5, 'pending')
                    ON CONFLICT (call_id) WHERE status IN ('pending', 'processing')
                    DO UPDATE SET 
                        scheduled_at = EXCLUDED.scheduled_at,
                        context = EXCLUDED.context
                    RETURNING id
                """, call_id, phone_number, client_name, scheduled_at, 
                    json.dumps(context) if context else None)
                
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
        pool = await get_db_pool()
        
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT id, call_id, phone_number, client_name, scheduled_at, context, retry_count
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
        pool = await get_db_pool()
        
        try:
            async with pool.acquire() as conn:
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
        pool = await get_db_pool()
        
        try:
            async with pool.acquire() as conn:
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
