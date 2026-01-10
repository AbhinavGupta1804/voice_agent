"""Service layer for order operations."""
import logging
import asyncio
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Tuple, Optional
import asyncpg
import json

from db.postgres import get_db_pool, reset_pool
from models.order_models import OrderCreate, OrderUpdate

logger = logging.getLogger(__name__)


def _serialize_order(row: asyncpg.Record) -> Dict:
    """Convert PostgreSQL row to dictionary format."""
    if not row:
        return {}
    
    record = dict(row)
    # Parse JSONB items
    if record.get("items"):
        if isinstance(record["items"], str):
            record["items"] = json.loads(record["items"])
        elif not isinstance(record["items"], list):
            record["items"] = []
    else:
        record["items"] = []
    
    # Convert timestamp
    if record.get("order_timestamp"):
        ts = record["order_timestamp"]
        if isinstance(ts, datetime):
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            else:
                ts = ts.astimezone(timezone.utc)
            record["order_timestamp"] = ts.isoformat()
    
    if record.get("completed_at"):
        ts = record["completed_at"]
        if isinstance(ts, datetime):
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            else:
                ts = ts.astimezone(timezone.utc)
            record["completed_at"] = ts.isoformat()
    
    record.pop("id", None)
    record.pop("created_at", None)
    record.pop("updated_at", None)
    
    return record


class OrderService:
    """PostgreSQL-backed operations for orders."""
    
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
                        f"[OrderService] Connection error (attempt {attempt + 1}/{max_retries + 1}): {e}. "
                        f"Retrying in {delay}s..."
                    )
                    await asyncio.sleep(delay)
                    # Reset pool to get fresh connections
                    try:
                        await reset_pool()
                    except Exception as reset_error:
                        logger.error(f"[OrderService] Failed to reset pool: {reset_error}")
                else:
                    logger.error(f"[OrderService] All retry attempts failed: {e}")
            except Exception as e:
                # Non-connection errors should not be retried
                logger.error(f"[OrderService] Non-retryable error: {e}", exc_info=True)
                raise
        
        # If we exhausted retries, raise the last exception
        raise last_exception
    
    @staticmethod
    async def create_order(order_data: OrderCreate) -> Dict:
        """Create a new order."""
        order_id = f"ORD-{uuid.uuid4().hex[:8].upper()}"
        
        async def _create():
            pool = await get_db_pool()
            async with pool.acquire() as conn:
                async with conn.transaction():
                    items_json = json.dumps([
                        item.model_dump() if hasattr(item, 'model_dump') else item 
                        for item in order_data.items
                    ])
                    
                    await conn.execute("""
                        INSERT INTO "Hospitality".orders (
                            order_id, caller_name, caller_phone, items, status,
                            estimated_time_minutes, order_timestamp, call_id, notes, total_amount
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                    """,
                        order_id,
                        order_data.caller_name,
                        order_data.caller_phone,
                        items_json,
                        "pending",
                        order_data.estimated_time_minutes,
                        datetime.now(timezone.utc),
                        order_data.call_id,
                        order_data.notes,
                        order_data.total_amount
                    )
                    
                    # Fetch the created order
                    row = await conn.fetchrow('SELECT * FROM "Hospitality".orders WHERE order_id = $1', order_id)
                    return _serialize_order(row)
        
        return await OrderService._execute_with_retry(_create)
    
    @staticmethod
    async def update_order(order_id: str, order_update: OrderUpdate) -> Dict:
        """Update an existing order."""
        async def _update():
            pool = await get_db_pool()
            async with pool.acquire() as conn:
                async with conn.transaction():
                    updates = []
                    values = []
                    param_num = 1
                    
                    if order_update.status:
                        updates.append(f"status = ${param_num}")
                        values.append(order_update.status)
                        param_num += 1
                        
                        # If status is completed, set completed_at
                        if order_update.status == "completed":
                            updates.append(f"completed_at = ${param_num}")
                            values.append(datetime.now(timezone.utc))
                            param_num += 1
                    
                    if order_update.estimated_time_minutes is not None:
                        updates.append(f"estimated_time_minutes = ${param_num}")
                        values.append(order_update.estimated_time_minutes)
                        param_num += 1
                    
                    if order_update.notes is not None:
                        updates.append(f"notes = ${param_num}")
                        values.append(order_update.notes)
                        param_num += 1
                    
                    if order_update.total_amount is not None:
                        updates.append(f"total_amount = ${param_num}")
                        values.append(order_update.total_amount)
                        param_num += 1
                    
                    if not updates:
                        # No updates to make, just fetch and return
                        row = await conn.fetchrow('SELECT * FROM "Hospitality".orders WHERE order_id = $1', order_id)
                        if not row:
                            raise ValueError(f"Order {order_id} not found")
                        return _serialize_order(row)
                    
                    updates.append(f"updated_at = NOW()")
                    values.append(order_id)
                    
                    query = f"""
                        UPDATE "Hospitality".orders 
                        SET {', '.join(updates)}
                        WHERE order_id = ${param_num}
                    """
                    
                    await conn.execute(query, *values)
                    
                    # Fetch updated order
                    row = await conn.fetchrow('SELECT * FROM "Hospitality".orders WHERE order_id = $1', order_id)
                    if not row:
                        raise ValueError(f"Order {order_id} not found")
                    
                    return _serialize_order(row)
        
        return await OrderService._execute_with_retry(_update)
    
    @staticmethod
    async def get_order(order_id: str) -> Optional[Dict]:
        """Get a single order by order_id."""
        async def _get():
            pool = await get_db_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow('SELECT * FROM "Hospitality".orders WHERE order_id = $1', order_id)
                if not row:
                    return None
                return _serialize_order(row)
        
        return await OrderService._execute_with_retry(_get)
    
    @staticmethod
    async def list_orders(
        page: int = 1,
        page_size: int = 20,
        status: Optional[str] = None
    ) -> Tuple[List[Dict], int]:
        """List orders with pagination and optional status filter."""
        offset = max(page - 1, 0) * page_size
        
        async def _list():
            pool = await get_db_pool()
            async with pool.acquire() as conn:
                # Build query with optional status filter
                if status:
                    total = await conn.fetchval(
                        'SELECT COUNT(*) FROM "Hospitality".orders WHERE status = $1',
                        status
                    )
                    rows = await conn.fetch("""
                        SELECT * FROM "Hospitality".orders 
                        WHERE status = $1
                        ORDER BY order_timestamp DESC
                        LIMIT $2 OFFSET $3
                    """, status, page_size, offset)
                else:
                    total = await conn.fetchval('SELECT COUNT(*) FROM "Hospitality".orders')
                    rows = await conn.fetch("""
                        SELECT * FROM "Hospitality".orders 
                        ORDER BY order_timestamp DESC
                        LIMIT $1 OFFSET $2
                    """, page_size, offset)
                
                orders = [_serialize_order(row) for row in rows]
                return orders, total
        
        return await OrderService._execute_with_retry(_list)
    
    @staticmethod
    async def get_pending_orders() -> List[Dict]:
        """Get all pending orders."""
        orders, _ = await OrderService.list_orders(page=1, page_size=1000, status="pending")
        return orders
    
    @staticmethod
    async def get_today_completed_count() -> int:
        """Get count of completed orders for today."""
        async def _get_count():
            pool = await get_db_pool()
            async with pool.acquire() as conn:
                count = await conn.fetchval("""
                    SELECT COUNT(*) FROM "Hospitality".orders 
                    WHERE status = 'completed' 
                    AND DATE(completed_at) = CURRENT_DATE
                """)
                return count or 0
        
        try:
            return await OrderService._execute_with_retry(_get_count)
        except Exception as e:
            logger.error(f"[OrderService] Failed to get today completed count: {e}", exc_info=True)
            return 0

