"""WhatsApp operations for booking email collection."""
import logging
from typing import Any, Dict, Optional

from ..config import Config
from .booking_email_session_service import BookingEmailSessionService
from .whatsapp_service import WhatsAppService

logger = logging.getLogger(__name__)


class WhatsAppBookingService:
    """High-level API: send booking email request + handle inbound replies."""

    @classmethod
    def resolve_target_phone(cls, explicit_phone: Optional[str] = None) -> str:
        """
        Phone to send WhatsApp to.

        Phase 1: fixed test number from env.
        Later: pass caller phone from Retell {{user_number}}.
        """
        return explicit_phone or Config.BOOKING_EMAIL_WHATSAPP

    @classmethod
    async def send_email_request(
        cls,
        call_id: str,
        customer_name: str,
        selected_time: Optional[str] = None,
        phone: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create Redis session and send WhatsApp asking for email."""
        target_phone = cls.resolve_target_phone(phone)
        session = await BookingEmailSessionService.create_session(
            call_id=call_id,
            phone=target_phone,
            customer_name=customer_name,
            selected_time=selected_time,
        )

        time_line = f" for *{selected_time}*" if selected_time else ""
        message_body = (
            f"Hi {customer_name or 'there'},\n\n"
            f"You are booking a Naturals Ice Cream appointment{time_line}.\n\n"
            f"Please reply to this message with your *email address* "
            f"(for example: name@gmail.com).\n\n"
        )

        send_result = await WhatsAppService.send_simple_message(
            to_number=target_phone,
            message_body=message_body,
        )

        if not send_result.get("success"):
            logger.error(
                "[WhatsAppBooking] send failed call_id=%s error=%s",
                call_id,
                send_result.get("error"),
            )
            return {
                "success": False,
                "status": "failed",
                "call_id": call_id,
                "message": "Could not send WhatsApp message. Please try again.",
                "whatsapp_error": send_result.get("error"),
            }

        logger.info(
            "[WhatsAppBooking] request sent call_id=%s to=%s sid=%s",
            call_id,
            target_phone,
            send_result.get("message_sid"),
        )
        return {
            "success": True,
            "status": "pending",
            "call_id": call_id,
            "phone": target_phone,
            "session": session,
        }

    @classmethod
    async def collect_email_via_whatsapp(
        cls,
        call_id: str,
        customer_name: str,
        selected_time: Optional[str] = None,
        phone: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Option 2: Send WhatsApp, then wait on Redis until user replies (long-poll).

        Retell tool holds this HTTP request open until email arrives or timeout.
        """
        send_result = await cls.send_email_request(
            call_id=call_id,
            customer_name=customer_name,
            selected_time=selected_time,
            phone=phone,
        )
        if not send_result.get("success"):
            return {
                "success": False,
                "status": send_result.get("status", "failed"),
                "call_id": call_id,
                "email": "",
                "ready": False,
                "message": send_result.get("message", "Failed to send WhatsApp."),
            }

        wait_result = await BookingEmailSessionService.wait_for_email(call_id)
        email = wait_result.get("email") or ""
        ready = bool(wait_result.get("ready"))

        if ready and email:
            return {
                "success": True,
                "status": "email_received",
                "call_id": call_id,
                "email": email,
                "ready": True,
                "message": f"Email received via WhatsApp: {email}",
            }

        return {
            "success": False,
            "status": wait_result.get("status", "timeout"),
            "call_id": call_id,
            "email": "",
            "ready": False,
            "message": (
                "Did not receive email on WhatsApp in time. "
                "Ask the customer to check WhatsApp and try again."
            ),
        }

    @classmethod
    async def handle_inbound_email_reply(
        cls,
        from_phone: str,
        message_body: str,
    ) -> Dict[str, Any]:
        """
        Process inbound WhatsApp text as booking email reply.

        Returns:
            handled: bool
            reply_message: str to send back on WhatsApp
        """
        session = await BookingEmailSessionService.get_active_session_by_phone(from_phone)
        if not session:
            return {"handled": False, "reply_message": ""}

        from ..utils.email_validation import extract_email_from_text, validate_email

        raw = (message_body or "").strip()
        extracted = extract_email_from_text(raw)
        if not extracted:
            return {
                "handled": True,
                "call_id": session["call_id"],
                "success": False,
                "reply_message": (
                    "I couldn't read a valid email address. "
                    "Please send your email like: name@gmail.com"
                ),
            }

        valid, normalized = validate_email(extracted)
        if not valid or not normalized:
            return {
                "handled": True,
                "call_id": session["call_id"],
                "success": False,
                "reply_message": (
                    "That doesn't look like a valid email. "
                    "Please try again (example: name@gmail.com)."
                ),
            }

        updated = await BookingEmailSessionService.set_email_received(
            session["call_id"],
            normalized,
        )
        if not updated:
            return {
                "handled": True,
                "call_id": session["call_id"],
                "success": False,
                "reply_message": "Session expired. Please ask the agent to resend the request.",
            }

        return {
            "handled": True,
            "call_id": session["call_id"],
            "success": True,
            "email": normalized,
            "reply_message": (
                f"Thanks! We received your email ({normalized}). "
                "Please stay on the call — the agent will confirm shortly."
            ),
        }
