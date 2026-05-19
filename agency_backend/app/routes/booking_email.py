"""Booking email session polling (inbound WhatsApp is handled in webhooks.py)."""
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from ..services.booking_email_session_service import BookingEmailSessionService

logger = logging.getLogger(__name__)


def register_booking_email_routes(app) -> None:
    """
    Register booking-email poll route.

    Twilio inbound WhatsApp must use a single URL:
      POST /webhook/whatsapp_response  (see app/routes/webhooks.py)
    That handler runs booking-email collection first, then general WhatsApp chat.
    """
    router = APIRouter(tags=["Booking Email"])

    @router.get("/session-status/{call_id}")
    async def get_session_status(call_id: str):
        """
        Non-blocking poll for Retell: check if WhatsApp email was received.

        Retell custom tool should call this every few seconds until ready=true.
        Map response `email` to dynamic variable {{email}} for book_slot.
        """
        if not call_id or not call_id.strip():
            raise HTTPException(status_code=400, detail="call_id is required")

        payload = await BookingEmailSessionService.to_status_response(call_id.strip())
        logger.debug(
            "[SessionStatus] call_id=%s status=%s ready=%s",
            call_id,
            payload.get("status"),
            payload.get("ready"),
        )
        return JSONResponse(content=payload)

    app.include_router(router)
