"""Routes for handling inbound calls and unified voice webhook."""

import logging
from fastapi import Request, WebSocket
from fastapi.responses import Response

from ..config import Config
from ..handlers.inbound_websocket_handler import InboundWebSocketHandler

logger = logging.getLogger(__name__)


def register_inbound_routes(app):
    """Register inbound call routes."""
    
    @app.post("/voice-webhook")
    @app.get("/voice-webhook")
    async def unified_voice_webhook(request: Request):
        """
        Unified webhook endpoint for Twilio voice calls.
        
        This endpoint detects if a call is inbound or outbound and routes accordingly:
        - Inbound calls: Proxies to ElevenLabs' inbound webhook
        - Outbound calls: Should not reach here (they use /outbound-call-twiml)
        
        Set this URL as the "A CALL COMES IN" webhook in Twilio Voice Configuration:
        https://08ffb542bc52.ngrok-free.app/voice-webhook
        """
        try:
            # Get all form data from Twilio
            form_data = await request.form()
            form_dict = dict(form_data)
            
            # Log incoming webhook details
            logger.info(f"[VoiceWebhook] Received Twilio webhook")
            logger.info(f"[VoiceWebhook] CallSid: {form_dict.get('CallSid', 'N/A')}")
            logger.info(f"[VoiceWebhook] From: {form_dict.get('From', 'N/A')}")
            logger.info(f"[VoiceWebhook] To: {form_dict.get('To', 'N/A')}")
            logger.info(f"[VoiceWebhook] CallStatus: {form_dict.get('CallStatus', 'N/A')}")
            logger.info(f"[VoiceWebhook] Direction: {form_dict.get('Direction', 'N/A')}")
            
            # Detect if this is an inbound call
            # Inbound calls have Direction='inbound' or the To number is your Twilio number
            direction = form_dict.get('Direction', '').lower()
            to_number = form_dict.get('To', '')
            call_status = form_dict.get('CallStatus', '').lower()
            
            is_inbound = (
                direction == 'inbound' or 
                (not direction and to_number == Config.TWILIO_PHONE_NUMBER) or
                call_status == 'ringing'  # Initial webhook for incoming calls
            )
            
            if is_inbound:
                logger.info("[VoiceWebhook] Detected INBOUND call - returning TwiML with WebSocket")
                
                # Return TwiML that connects to our WebSocket handler
                # This allows us to customize the first message for inbound calls
                base_url = Config.NGROK_URL or f"https://{request.headers.get('host', 'localhost')}"
                ws_url = base_url.replace("https://", "").replace("http://", "")
                ws_stream_url = f"wss://{ws_url}/inbound-media-stream"
                
                logger.info(f"[VoiceWebhook] Generated WebSocket URL: {ws_stream_url}")
                
                # Extract caller info to pass to the stream
                from_number = form_dict.get('From', '')
                caller_name = form_dict.get('CallerName', '')

                twiml_response = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="{ws_stream_url}">
            <Parameter name="from" value="{from_number}" />
            <Parameter name="callerName" value="{caller_name}" />
        </Stream>
    </Connect>
</Response>"""
                
                return Response(content=twiml_response, media_type="text/xml")
            
            else:
                # This shouldn't normally happen for outbound calls since they use /outbound-call-twiml
                # But handle it gracefully just in case
                logger.warning(f"[VoiceWebhook] Unexpected call direction or type: Direction={direction}, Status={call_status}")
                
                # For safety, you could route to outbound handler or return a default response
                default_twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say>Please hold while we connect your call.</Say>
    <Pause length="1"/>
</Response>"""
                return Response(content=default_twiml, media_type="application/xml")
                
        except Exception as e:
            logger.error(f"[VoiceWebhook] Unexpected error: {e}", exc_info=True)
            # Return a basic error TwiML
            error_twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say>An error occurred processing your call. Please try again later.</Say>
    <Hangup/>
</Response>"""
            return Response(content=error_twiml, media_type="application/xml")
    
    @app.websocket("/inbound-media-stream")
    async def inbound_media_stream_handler(websocket: WebSocket):
        """
        WebSocket handler for inbound call media streams.
        Connects Twilio audio to ElevenLabs with custom inbound greeting.
        
        Args:
            websocket: WebSocket connection from Twilio
        """
        handler = InboundWebSocketHandler(websocket)
        await handler.handle()