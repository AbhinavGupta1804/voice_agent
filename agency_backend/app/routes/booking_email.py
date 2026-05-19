"""Booking email collection: WhatsApp webhook + session status polling."""
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from ..services.booking_email_session_service import BookingEmailSessionService
from ..services.whatsapp_booking_service import WhatsAppBookingService
from ..services.whatsapp_service import WhatsAppService
from ..utils.phone_utils import normalize_phone_number

logger = logging.getLogger(__name__)


class WhatsAppWebhookResponse(BaseModel):
    """Ack for Twilio WhatsApp webhook."""
    status: str = "ok"
    handled: bool = False
    call_id: Optional[str] = None


def register_booking_email_routes(app) -> None:
    """Register scalable booking-email routes (Redis-backed)."""
    router = APIRouter(tags=["Booking Email"])

    @router.post("/webhooks/whatsapp", response_model=WhatsAppWebhookResponse)
    async def whatsapp_booking_webhook(
        request: Request,
        Body: str = Form(default=""),
        From: str = Form(default=""),
        To: str = Form(default=""),
        MessageSid: str = Form(default=None),
    ):
        """
        Twilio inbound WhatsApp for booking email collection.

        Configure Twilio 'A MESSAGE COMES IN' to this URL for production scale.
        Updates Redis session; does not block voice calls.
        """
        raw_body = (Body or "").strip()
        from_number = normalize_phone_number((From or "").replace("whatsapp:", "").strip())

        logger.info(
            "[WhatsAppBooking Webhook] from=%s body_len=%d sid=%s",
            from_number,
            len(raw_body),
            MessageSid,
        )

        if not from_number:
            return WhatsAppWebhookResponse(status="ignored", handled=False)

        result = await WhatsAppBookingService.handle_inbound_email_reply(
            from_phone=from_number,
            message_body=raw_body,
        )

        if not result.get("handled"):
            logger.warning(
                "[WhatsAppBooking Webhook] No pending booking session for from=%s "
                "(Twilio reached backend OK — check BOOKING_EMAIL_WHATSAPP matches sender, "
                "or start a new call to create a session). body_preview=%r",
                from_number,
                raw_body[:80],
            )

        if result.get("handled"):
            reply = result.get("reply_message", "")
            if reply:
                await WhatsAppService.send_simple_message(from_number, reply)
            logger.info(
                "[WhatsAppBooking Webhook] handled call_id=%s success=%s",
                result.get("call_id"),
                result.get("success"),
            )
            return WhatsAppWebhookResponse(
                status="ok",
                handled=True,
                call_id=result.get("call_id"),
            )

        # Not a booking session — return 200 so Twilio does not retry;
        # legacy handler may still process via /webhook/whatsapp_response if configured.
        return WhatsAppWebhookResponse(status="ok", handled=False)

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
