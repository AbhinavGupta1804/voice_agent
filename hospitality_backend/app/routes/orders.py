"""Routes for order management."""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from models.order_models import OrderCreate, OrderUpdate, OrderResponse, PaginatedOrdersResponse
from services.order_service import OrderService
from services.whatsapp_service import WhatsAppService

logger = logging.getLogger(__name__)


def register_order_routes(app):
    """Register order routes."""
    router = APIRouter(tags=["Orders"], prefix="/api/orders")
    
    @router.post("", response_model=OrderResponse)
    async def create_order(order: OrderCreate):
        """Create a new order."""
        try:
            result = await OrderService.create_order(order)
            return OrderResponse(**result)
        except Exception as e:
            logger.error(f"[Orders] Failed to create order: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))
    
    @router.get("", response_model=PaginatedOrdersResponse)
    async def list_orders(
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100),
        status: Optional[str] = Query(None)
    ):
        """List orders with pagination."""
        try:
            orders, total = await OrderService.list_orders(page=page, page_size=page_size, status=status)
            return PaginatedOrdersResponse(
                page=page,
                page_size=page_size,
                total=total,
                items=[OrderResponse(**order) for order in orders]
            )
        except Exception as e:
            logger.error(f"[Orders] Failed to list orders: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))
    
    @router.get("/pending", response_model=PaginatedOrdersResponse)
    async def get_pending_orders():
        """Get all pending orders."""
        try:
            orders = await OrderService.get_pending_orders()
            return PaginatedOrdersResponse(
                page=1,
                page_size=len(orders),
                total=len(orders),
                items=[OrderResponse(**order) for order in orders]
            )
        except Exception as e:
            logger.error(f"[Orders] Failed to get pending orders: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))
    
    @router.get("/{order_id}", response_model=OrderResponse)
    async def get_order(order_id: str):
        """Get a single order by order_id."""
        try:
            order = await OrderService.get_order(order_id)
            if not order:
                raise HTTPException(status_code=404, detail=f"Order {order_id} not found")
            return OrderResponse(**order)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"[Orders] Failed to get order: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))
    
    @router.patch("/{order_id}", response_model=OrderResponse)
    async def update_order(order_id: str, order_update: OrderUpdate):
        """Update an existing order."""
        try:
            # Get current order to check status change
            current_order = await OrderService.get_order(order_id)
            if not current_order:
                raise HTTPException(status_code=404, detail=f"Order {order_id} not found")
            
            old_status = current_order.get("status")
            new_status = order_update.status
            
            # Update the order
            result = await OrderService.update_order(order_id, order_update)
            
            # Send WhatsApp notification if status changed to "preparing"
            if old_status != "preparing" and new_status == "preparing":
                caller_phone = result.get("caller_phone")
                caller_name = result.get("caller_name", "Customer")
                
                if caller_phone:
                    try:
                        await WhatsAppService.send_order_prepared_notification(
                            to_number=caller_phone,
                            caller_name=caller_name,
                            order_id=order_id
                        )
                        logger.info(f"[Orders] Sent 'preparing' notification to {caller_phone} for order {order_id}")
                    except Exception as e:
                        logger.error(f"[Orders] Failed to send WhatsApp notification: {e}")
            
            # Send WhatsApp notification if status changed to "ready"
            if old_status != "ready" and new_status == "ready":
                caller_phone = result.get("caller_phone")
                caller_name = result.get("caller_name", "Customer")
                
                if caller_phone:
                    try:
                        await WhatsAppService.send_order_ready_notification(
                            to_number=caller_phone,
                            caller_name=caller_name,
                            order_id=order_id
                        )
                        logger.info(f"[Orders] Sent 'ready' notification to {caller_phone} for order {order_id}")
                    except Exception as e:
                        logger.error(f"[Orders] Failed to send WhatsApp notification: {e}")
            
            return OrderResponse(**result)
        except HTTPException:
            raise
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except Exception as e:
            logger.error(f"[Orders] Failed to update order: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))
    
    @router.get("/stats/today-completed", response_model=dict)
    async def get_today_completed_count():
        """Get count of completed orders for today."""
        try:
            count = await OrderService.get_today_completed_count()
            return {"count": count}
        except Exception as e:
            logger.error(f"[Orders] Failed to get today completed count: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))
    
    app.include_router(router)

