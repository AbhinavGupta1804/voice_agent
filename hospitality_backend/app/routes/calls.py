"""Routes for call history."""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from models.call_models import CallRecordResponse, PaginatedCallsResponse
from services.call_service import CallService

logger = logging.getLogger(__name__)


def register_call_routes(app):
    """Register call history routes."""
    router = APIRouter(tags=["Calls"], prefix="/api/calls")
    
    @router.get("", response_model=PaginatedCallsResponse)
    async def list_calls(
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100)
    ):
        """List call records with pagination."""
        try:
            calls, total = await CallService.list_calls(page=page, page_size=page_size)
            return PaginatedCallsResponse(
                page=page,
                page_size=page_size,
                total=total,
                items=[CallRecordResponse(**call) for call in calls]
            )
        except Exception as e:
            logger.error(f"[Calls] Failed to list calls: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))
    
    @router.get("/{call_id}", response_model=CallRecordResponse)
    async def get_call(call_id: str):
        """Get a single call record by call_id."""
        try:
            call = await CallService.get_call(call_id)
            if not call:
                raise HTTPException(status_code=404, detail=f"Call {call_id} not found")
            return CallRecordResponse(**call)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"[Calls] Failed to get call: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))
    
    app.include_router(router)
