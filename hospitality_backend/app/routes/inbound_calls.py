"""Routes for handling inbound calls."""
import logging
from fastapi import APIRouter, WebSocket, Request
from fastapi.responses import Response

from config import Config
from handlers.inbound_websocket_handler import InboundWebSocketHandler

logger = logging.getLogger(__name__)


def register_inbound_routes(app):
    """Register inbound call routes."""
    router = APIRouter(tags=["Inbound Calls"])
    
    @router.get("/inbound/twiml")
    async def get_twiml():
        """
        Return TwiML instructions for inbound calls.
        This endpoint is called by Twilio when a call comes in.
        """
        base_url = Config.NGROK_URL or f"http://localhost:{Config.PORT}"
        websocket_url = f"{base_url}/inbound/media"
        
        # TwiML to start media stream
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Start>
        <Stream url="wss://{websocket_url.replace('http://', '').replace('https://', '')}" />
    </Start>
    <Say>Thank you for calling. Please hold while we connect you.</Say>
    <Pause length="30" />
</Response>"""
        
        return Response(content=twiml, media_type="application/xml")
    
    @router.websocket("/inbound/media")
    async def inbound_media_stream(websocket: WebSocket):
        """
        WebSocket endpoint for bidirectional media streaming with Twilio.
        Handles audio from Twilio and forwards to ElevenLabs, and vice versa.
        """
        handler = InboundWebSocketHandler(websocket)
        await handler.handle()
    
    app.include_router(router)

