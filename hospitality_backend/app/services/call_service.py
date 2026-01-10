"""Service layer for call record operations."""
import logging
import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Tuple, Optional
import asyncpg

from db.postgres import get_db_pool, reset_pool

logger = logging.getLogger(__name__)


def _serialize_call_record(row: asyncpg.Record) -> Dict:
    """Convert PostgreSQL row to dictionary format."""
    if not row:
        return {}
    
    record = dict(row)
    
    # Convert timestamp
    if record.get("call_timestamp"):
        ts = record["call_timestamp"]
        if isinstance(ts, datetime):
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            else:
                ts = ts.astimezone(timezone.utc)
            record["call_timestamp"] = ts.isoformat()
    
    record.pop("id", None)
    record.pop("created_at", None)
    record.pop("updated_at", None)
    
    return record


class CallService:
    """PostgreSQL-backed operations for call records."""
    
    @staticmethod
    async def _execute_with_retry(operation, max_retries=2, initial_delay=0.1):
        """Execute a database operation with retry logic for connection failures."""
        last_exception = None
        
        for attempt in range(max_retries + 1):
            try:
                return await operation()
            except (asyncpg.exceptions.ConnectionDoesNotExistError, 
                    ConnectionResetError,
                    OSError) as e:
                last_exception = e
                if attempt < max_retries:
                    delay = initial_delay * (2 ** attempt)
                    logger.warning(
                        f"[CallService] Connection error (attempt {attempt + 1}/{max_retries + 1}): {e}. "
                        f"Retrying in {delay}s..."
                    )
                    await asyncio.sleep(delay)
                    # Reset pool to get fresh connections
                    try:
                        await reset_pool()
                    except Exception as reset_error:
                        logger.error(f"[CallService] Failed to reset pool: {reset_error}")
                else:
                    logger.error(f"[CallService] All retry attempts failed: {e}")
            except Exception as e:
                # Non-connection errors should not be retried
                logger.error(f"[CallService] Non-retryable error: {e}", exc_info=True)
                raise
        
        # If we exhausted retries, raise the last exception
        raise last_exception
    
    @staticmethod
    async def create_call_record(call_data: Dict) -> Dict:
        """Create a new call record."""
        async def _create():
            pool = await get_db_pool()
            async with pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute("""
                        INSERT INTO "Hospitality".calls (
                            call_id, caller_name, caller_phone, transcript, summary,
                            order_id, duration_sec, call_timestamp, recording_url, sentiment
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                        ON CONFLICT (call_id) DO UPDATE SET
                            caller_name = EXCLUDED.caller_name,
                            caller_phone = EXCLUDED.caller_phone,
                            transcript = EXCLUDED.transcript,
                            summary = EXCLUDED.summary,
                            order_id = EXCLUDED.order_id,
                            duration_sec = EXCLUDED.duration_sec,
                            call_timestamp = EXCLUDED.call_timestamp,
                            recording_url = COALESCE(EXCLUDED.recording_url, "Hospitality".calls.recording_url),
                            sentiment = EXCLUDED.sentiment,
                            updated_at = NOW()
                    """,
                        call_data.get("call_id"),
                        call_data.get("caller_name"),
                        call_data.get("caller_phone"),
                        call_data.get("transcript"),
                        call_data.get("summary"),
                        call_data.get("order_id"),
                        call_data.get("duration_sec", 0),
                        call_data.get("call_timestamp", datetime.now(timezone.utc)),
                        call_data.get("recording_url"),
                        call_data.get("sentiment")
                    )
                    
                    row = await conn.fetchrow('SELECT * FROM "Hospitality".calls WHERE call_id = $1', call_data.get("call_id"))
                    return _serialize_call_record(row)
        
        return await CallService._execute_with_retry(_create)
    
    @staticmethod
    async def get_call(call_id: str) -> Optional[Dict]:
        """Get a single call record by call_id."""
        async def _get():
            pool = await get_db_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow('SELECT * FROM "Hospitality".calls WHERE call_id = $1', call_id)
                if not row:
                    return None
                return _serialize_call_record(row)
        
        return await CallService._execute_with_retry(_get)
    
    @staticmethod
    async def list_calls(page: int = 1, page_size: int = 20) -> Tuple[List[Dict], int]:
        """List call records with pagination."""
        offset = max(page - 1, 0) * page_size
        
        async def _list():
            pool = await get_db_pool()
            async with pool.acquire() as conn:
                total = await conn.fetchval('SELECT COUNT(*) FROM "Hospitality".calls')
                
                rows = await conn.fetch("""
                    SELECT * FROM "Hospitality".calls 
                    ORDER BY call_timestamp DESC
                    LIMIT $1 OFFSET $2
                """, page_size, offset)
                
                calls = [_serialize_call_record(row) for row in rows]
                return calls, total
        
        return await CallService._execute_with_retry(_list)

