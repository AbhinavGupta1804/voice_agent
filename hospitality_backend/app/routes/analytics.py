"""Routes for analytics and reporting."""
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from db.postgres import get_db_pool

logger = logging.getLogger(__name__)


def register_analytics_routes(app):
    """Register analytics routes."""
    router = APIRouter(tags=["Analytics"], prefix="/api/analytics")
    
    @router.get("/orders/summary")
    async def get_orders_summary(
        days: int = Query(7, ge=1, le=365)
    ):
        """Get order summary statistics for the last N days."""
        try:
            pool = await get_db_pool()
            async with pool.acquire() as conn:
                start_date = datetime.now(timezone.utc) - timedelta(days=days)
                
                # Total orders
                total_orders = await conn.fetchval("""
                    SELECT COUNT(*) FROM "Hospitality".orders 
                    WHERE order_timestamp >= $1
                """, start_date)
                
                # Orders by status
                orders_by_status = await conn.fetch("""
                    SELECT status, COUNT(*) as count
                    FROM "Hospitality".orders
                    WHERE order_timestamp >= $1
                    GROUP BY status
                """, start_date)
                
                status_counts = {row['status']: row['count'] for row in orders_by_status}
                
                # Total revenue
                total_revenue = await conn.fetchval("""
                    SELECT COALESCE(SUM(total_amount), 0) FROM "Hospitality".orders 
                    WHERE order_timestamp >= $1 AND total_amount IS NOT NULL
                """, start_date)
                
                # Average order value
                avg_order_value = await conn.fetchval("""
                    SELECT COALESCE(AVG(total_amount), 0) FROM "Hospitality".orders 
                    WHERE order_timestamp >= $1 AND total_amount IS NOT NULL
                """, start_date)
                
                # Orders per day
                orders_per_day = await conn.fetch("""
                    SELECT DATE(order_timestamp) as date, COUNT(*) as count
                    FROM "Hospitality".orders
                    WHERE order_timestamp >= $1
                    GROUP BY DATE(order_timestamp)
                    ORDER BY date ASC
                """, start_date)
                
                return {
                    "period_days": days,
                    "total_orders": total_orders or 0,
                    "orders_by_status": status_counts,
                    "total_revenue": float(total_revenue) if total_revenue else 0.0,
                    "average_order_value": float(avg_order_value) if avg_order_value else 0.0,
                    "orders_per_day": [
                        {"date": row['date'].isoformat(), "count": row['count']}
                        for row in orders_per_day
                    ]
                }
        except Exception as e:
            logger.error(f"[Analytics] Failed to get orders summary: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))
    
    @router.get("/calls/summary")
    async def get_calls_summary(
        days: int = Query(7, ge=1, le=365)
    ):
        """Get call summary statistics for the last N days."""
        try:
            pool = await get_db_pool()
            async with pool.acquire() as conn:
                start_date = datetime.now(timezone.utc) - timedelta(days=days)
                
                # Total calls
                total_calls = await conn.fetchval("""
                    SELECT COUNT(*) FROM "Hospitality".calls 
                    WHERE call_timestamp >= $1
                """, start_date)
                
                # Calls with orders
                calls_with_orders = await conn.fetchval("""
                    SELECT COUNT(DISTINCT call_id) FROM "Hospitality".calls 
                    WHERE call_timestamp >= $1 AND order_id IS NOT NULL
                """, start_date)
                
                # Average call duration
                avg_duration = await conn.fetchval("""
                    SELECT COALESCE(AVG(duration_sec), 0) FROM "Hospitality".calls 
                    WHERE call_timestamp >= $1
                """, start_date)
                
                # Calls per day
                calls_per_day = await conn.fetch("""
                    SELECT DATE(call_timestamp) as date, COUNT(*) as count
                    FROM "Hospitality".calls
                    WHERE call_timestamp >= $1
                    GROUP BY DATE(call_timestamp)
                    ORDER BY date ASC
                """, start_date)
                
                # Conversion rate (calls that resulted in orders)
                conversion_rate = (calls_with_orders / total_calls * 100) if total_calls > 0 else 0
                
                return {
                    "period_days": days,
                    "total_calls": total_calls or 0,
                    "calls_with_orders": calls_with_orders or 0,
                    "conversion_rate": round(conversion_rate, 2),
                    "average_duration_sec": round(float(avg_duration) if avg_duration else 0.0, 2),
                    "calls_per_day": [
                        {"date": row['date'].isoformat(), "count": row['count']}
                        for row in calls_per_day
                    ]
                }
        except Exception as e:
            logger.error(f"[Analytics] Failed to get calls summary: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))
    
    @router.get("/revenue/daily")
    async def get_daily_revenue(
        days: int = Query(30, ge=1, le=365)
    ):
        """Get daily revenue breakdown for the last N days."""
        try:
            pool = await get_db_pool()
            async with pool.acquire() as conn:
                start_date = datetime.now(timezone.utc) - timedelta(days=days)
                
                daily_revenue = await conn.fetch("""
                    SELECT 
                        DATE(order_timestamp) as date,
                        COUNT(*) as order_count,
                        COALESCE(SUM(total_amount), 0) as revenue
                    FROM "Hospitality".orders
                    WHERE order_timestamp >= $1 AND total_amount IS NOT NULL
                    GROUP BY DATE(order_timestamp)
                    ORDER BY date ASC
                """, start_date)
                
                return {
                    "period_days": days,
                    "daily_revenue": [
                        {
                            "date": row['date'].isoformat(),
                            "order_count": row['order_count'],
                            "revenue": float(row['revenue'])
                        }
                        for row in daily_revenue
                    ]
                }
        except Exception as e:
            logger.error(f"[Analytics] Failed to get daily revenue: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))
    
    @router.get("/popular-items")
    async def get_popular_items(
        days: int = Query(30, ge=1, le=365),
        limit: int = Query(10, ge=1, le=50)
    ):
        """Get most popular items ordered in the last N days."""
        try:
            pool = await get_db_pool()
            async with pool.acquire() as conn:
                start_date = datetime.now(timezone.utc) - timedelta(days=days)
                
                # This requires JSONB querying - simplified version
                # In production, you might want to denormalize item names into a separate table
                orders = await conn.fetch("""
                    SELECT items FROM "Hospitality".orders
                    WHERE order_timestamp >= $1
                """, start_date)
                
                # Aggregate items manually
                item_counts = {}
                for order in orders:
                    items = order['items'] if isinstance(order['items'], list) else []
                    for item in items:
                        item_name = item.get('name', 'Unknown')
                        quantity = item.get('quantity', 1)
                        item_counts[item_name] = item_counts.get(item_name, 0) + quantity
                
                # Sort and limit
                popular_items = sorted(
                    item_counts.items(),
                    key=lambda x: x[1],
                    reverse=True
                )[:limit]
                
                return {
                    "period_days": days,
                    "popular_items": [
                        {"name": name, "total_quantity": count}
                        for name, count in popular_items
                    ]
                }
        except Exception as e:
            logger.error(f"[Analytics] Failed to get popular items: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))
    
    app.include_router(router)

