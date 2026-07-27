"""Routes for handling inbound calls via Retell AI."""

import logging

from fastapi import Request
from fastapi.responses import Response

from ..config import Config
from ..services.retell_service import RetellService
from ..services.call_record_service import CallRecordService

logger = logging.getLogger(__name__)


def register_inbound_routes(app):
    """Register inbound call routes."""

    @app.post("/voice-webhook")
    @app.get("/voice-webhook")
    async def unified_voice_webhook(request: Request):
        """
        Twilio voice webhook for inbound calls (SIP mode).

        In direct mode with a Retell-imported number, Retell handles inbound calls
        in the Retell dashboard — this endpoint is only needed for SIP mode.
        """
        if Config.RETELL_INTEGRATION_MODE == "direct":
            logger.info("[VoiceWebhook] Direct mode — inbound handled by Retell; returning hold message")
            return Response(
                content='<?xml version="1.0" encoding="UTF-8"?><Response><Say>Please configure inbound routing in Retell for direct mode.</Say><Hangup/></Response>',
                media_type="text/xml",
            )

        try:
            form_data = await request.form()
            form_dict = dict(form_data)

            from_number = form_dict.get("From", "")
            to_number = form_dict.get("To", "")
            call_sid = form_dict.get("CallSid", "")
            caller_name = form_dict.get("CallerName", "") or "Customer"

            logger.info(
                "[VoiceWebhook] Inbound SIP bridge CallSid=%s From=%s To=%s",
                call_sid,
                from_number,
                to_number,
            )

            registration = await RetellService.register_phone_call(
                direction="inbound",
                from_number=from_number,
                to_number=to_number or Config.TWILIO_PHONE_NUMBER,
                client_name=caller_name,
                phone_number=from_number,
                call_type="inbound",
                twilio_call_sid=call_sid,
            )
            retell_call_id = registration["call_id"]

            await CallRecordService.store_call_metadata(
                call_sid=retell_call_id,
                client_name=caller_name,
                phone_number=from_number,
                call_type="inbound",
            )
            await CallRecordService.link_conversation_to_call(retell_call_id, retell_call_id)

            return Response(
                content=RetellService.build_sip_twiml(retell_call_id),
                media_type="text/xml",
            )
        except Exception as exc:
            logger.error("[VoiceWebhook] Error: %s", exc, exc_info=True)
            return Response(
                content='<?xml version="1.0" encoding="UTF-8"?><Response><Say>An error occurred. Please try again later.</Say><Hangup/></Response>',
                media_type="text/xml",
            )
