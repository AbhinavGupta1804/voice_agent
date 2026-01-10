"""Refactored outbound call handlers for Twilio-ElevenLabs integration."""

import logging
from urllib.parse import urlencode
from fastapi import WebSocket, Request
from fastapi.responses import Response, JSONResponse

from ..config import Config
from ..models.call_models import OutboundCallRequest
from ..services.twilio_service import TwilioService
from ..handlers.websocket_handler import OutboundWebSocketHandler

logger = logging.getLogger(__name__)


def register_outbound_routes(app):
    """Register outbound call routes."""
    Config.validate_twilio_config()
    Config.validate_elevenlabs_config()
    
    # Initialize services
    twilio_service = TwilioService()
    
    @app.post("/outbound-call")
    async def initiate_outbound_call(request_data: OutboundCallRequest, request: Request):
        """
        Initiate an outbound call using Twilio with personalized greeting.
        
        Args:
            request_data: Call parameters including phone number and client name
            request: FastAPI request object
            
        Returns:
            JSON response with call status
        """
        if not request_data.number:
            return JSONResponse(
                status_code=400,
                content={"error": "Phone number is required"}
            )
        
        if not request_data.client_name:
            return JSONResponse(
                status_code=400,
                content={"error": "Client name is required"}
            )
        
        try:
            # Build TwiML URL with client name parameter
            base_url = Config.NGROK_URL or f"https://{request.headers.get('host', 'localhost')}"
            twiml_url = f"{base_url}/outbound-call-twiml"
            
            # Add client name as query parameter
            params = {
                "client_name": request_data.client_name,
                "phone_number": request_data.number
            }
            twiml_url_with_params = f"{twiml_url}?{urlencode(params)}"
            
            # Initiate the call with Twilio
            call_info = await twilio_service.initiate_call(
                to_number=request_data.number,
                twiml_url=twiml_url_with_params
            )
            
            return JSONResponse(content={
                "success": True,
                "message": "Call initiated",
                "callSid": call_info["call_sid"],
                "clientName": request_data.client_name,
                "phoneNumber": request_data.number
            })
        
        except Exception as e:
            logger.error(f"[Outbound] Error initiating call: {e}")
            return JSONResponse(
                status_code=500,
                content={
                    "success": False,
                    "error": str(e)
                }
            )
    
    @app.post("/outbound-call-twiml", operation_id="outbound_call_twiml_post")
    @app.get("/outbound-call-twiml", operation_id="outbound_call_twiml_get")
    async def outbound_call_twiml(request: Request):
        """
        Return TwiML for outbound calls with client name parameter.
        
        Args:
            request: FastAPI request object with query parameters
            
        Returns:
            TwiML XML response
        """
        # Get query parameters
        query_params = dict(request.query_params)
        client_name = query_params.get("client_name", "")
        phone_number = query_params.get("phone_number", "")
        
        logger.info(f"[TwiML] Received query params: client_name={client_name}, phone_number={phone_number}")
        
        # Build base URL
        base_url = Config.NGROK_URL or f"https://{request.headers.get('host', 'localhost')}"
        ws_url = base_url.replace("https://", "").replace("http://", "")
        ws_stream_url = f"wss://{ws_url}/outbound-media-stream"
        
        logger.info(f"[TwiML] Generated WebSocket URL: {ws_stream_url}")
        
        # Use Twilio Stream Parameters to pass metadata
        # These will be available in the 'start' event's customParameters
        twiml_response = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="{ws_stream_url}">
            <Parameter name="client_name" value="{client_name}" />
            <Parameter name="phone_number" value="{phone_number}" />
        </Stream>
    </Connect>
</Response>"""
        
        return Response(content=twiml_response, media_type="text/xml")
    
    @app.websocket("/outbound-media-stream")
    async def outbound_media_stream_handler(websocket: WebSocket):
        """
        WebSocket handler for outbound call media streams.
        Connects Twilio audio to ElevenLabs with personalized greeting.
        
        Args:
            websocket: WebSocket connection from Twilio
        """
        # Parameters will be extracted from Twilio's 'start' event
        # Pass empty strings initially, handler will extract them from the start event
        handler = OutboundWebSocketHandler(websocket, "", "")
        await handler.handle()
