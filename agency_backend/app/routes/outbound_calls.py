"""Outbound call handlers using Retell AI."""

import logging
from urllib.parse import urlencode

from fastapi import Request
from fastapi.responses import JSONResponse, Response

from ..config import Config
from ..models.call_models import OutboundCallRequest
from ..services.retell_service import RetellService
from ..services.call_record_service import CallRecordService

logger = logging.getLogger(__name__)


def register_outbound_routes(app):
    """Register outbound call routes."""
    Config.validate_retell_config()
    Config.validate_twilio_config()

    @app.post("/outbound-call")
    async def initiate_outbound_call(request_data: OutboundCallRequest, request: Request):
        """Initiate an outbound call via Retell."""
        if not request_data.number:
            return JSONResponse(status_code=400, content={"error": "Phone number is required"})
        if not request_data.client_name:
            return JSONResponse(status_code=400, content={"error": "Client name is required"})

        try:
            call_info = await RetellService.initiate_outbound_call(
                to_number=request_data.number,
                client_name=request_data.client_name,
            )
            call_id = call_info.get("call_id")
            if call_id:
                await CallRecordService.store_call_metadata(
                    call_sid=call_id,
                    client_name=request_data.client_name,
                    phone_number=request_data.number,
                    call_type="outbound",
                )
                await CallRecordService.link_conversation_to_call(call_id, call_id)

            return JSONResponse(
                content={
                    "success": True,
                    "message": "Call initiated",
                    "callSid": call_info.get("call_sid") or call_id,
                    "callId": call_id,
                    "clientName": request_data.client_name,
                    "phoneNumber": request_data.number,
                }
            )
        except Exception as exc:
            logger.error("[Outbound] Error initiating call: %s", exc)
            return JSONResponse(status_code=500, content={"success": False, "error": str(exc)})

    @app.get("/retell-sip-twiml", operation_id="retell_sip_twiml_get")
    @app.post("/retell-sip-twiml", operation_id="retell_sip_twiml_post")
    async def retell_sip_twiml(request: Request):
        """Return TwiML that bridges a Twilio call to Retell via SIP (SIP mode only)."""
        retell_call_id = request.query_params.get("retell_call_id", "").strip()
        if not retell_call_id:
            return Response(
                content='<?xml version="1.0" encoding="UTF-8"?><Response><Say>Call setup failed.</Say><Hangup/></Response>',
                media_type="text/xml",
            )
        return Response(content=RetellService.build_sip_twiml(retell_call_id), media_type="text/xml")
