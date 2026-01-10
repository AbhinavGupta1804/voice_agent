"""WebSocket handler for inbound calls."""
import asyncio
import json
import logging
from typing import Optional
from fastapi import WebSocket, WebSocketDisconnect
import websockets

from services.elevenlabs_service import ElevenLabsService
from services.call_service import CallService
from services.call_record_service import CallRecordService

logger = logging.getLogger(__name__)


class InboundWebSocketHandler:
    """Handles WebSocket communication for inbound calls."""
    
    def __init__(self, websocket: WebSocket):
        """
        Initialize the handler.
        
        Args:
            websocket: WebSocket connection from Twilio
        """
        self.websocket = websocket
        self.stream_sid: Optional[str] = None
        self.call_sid: Optional[str] = None
        self.conversation_id: Optional[str] = None
        self.elevenlabs_ws: Optional[websockets.WebSocketClientProtocol] = None
        self.caller_phone: Optional[str] = None
        self.elevenlabs_closed: bool = False
    
    async def handle(self):
        """Handle the WebSocket connection."""
        await self.websocket.accept()
        logger.info("[Handler] Twilio connected to inbound media stream")
        
        try:
            # Connect to ElevenLabs immediately
            await self._setup_elevenlabs()
            
            # Handle the connection with concurrent tasks
            await self._handle_connection()
        
        except Exception as e:
            logger.error(f"[Handler] Error in inbound media stream: {e}")
        
        finally:
            await self._cleanup()
    
    async def _setup_elevenlabs(self):
        """Set up ElevenLabs connection using authenticated signed URL."""
        try:
            signed_url = await ElevenLabsService.get_signed_url()
            
            self.elevenlabs_ws = await asyncio.wait_for(
                websockets.connect(
                    signed_url,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=10
                ),
                timeout=10.0
            )
            
        except asyncio.TimeoutError:
            logger.error("[ElevenLabs] Connection timeout")
            raise
        except Exception as e:
            logger.error(f"[ElevenLabs] Connection failed: {e}")
            raise
    
    async def _initialize_conversation_context(self):
        """Send conversation initiation payload."""
        if not self.elevenlabs_ws:
            return
        
        try:
            init_payload = {
                "type": "conversation_initiation_settings",
                "conversation_config_override": {
                    "agent": {
                        "prompt": {
                            "prompt": """
You are a friendly and professional AI assistant for a restaurant/hotel/bar. 
You handle inbound calls from customers who want to place orders.

Your responsibilities:
1. Greet the caller warmly
2. Take their order details (items, quantities, special instructions)
3. Ask for their name and phone number if not provided
4. Confirm the order details
5. Provide estimated preparation/delivery time if available
6. Be courteous, efficient, and helpful

Keep responses concise and natural. Focus on accuracy of order details.
                            """.strip()
                        }
                    }
                }
            }
            
            await self.elevenlabs_ws.send(json.dumps(init_payload))
            logger.info("[ElevenLabs] Conversation context initialized")
            
        except Exception as e:
            logger.error(f"[ElevenLabs] Failed to initialize conversation: {e}")
    
    async def _handle_connection(self):
        """Handle bidirectional communication between Twilio and ElevenLabs."""
        # Wait for Twilio start event to get call metadata
        start_event_received = False
        
        async def handle_twilio_messages():
            nonlocal start_event_received
            try:
                async for message in self.websocket.iter_text():
                    if not message:
                        continue
                    
                    data = json.loads(message)
                    event_type = data.get("event")
                    
                    if event_type == "start":
                        start_event_received = True
                        start_data = data.get("start", {})
                        self.stream_sid = start_data.get("streamSid")
                        self.call_sid = start_data.get("callSid")
                        
                        # Extract phone number from multiple possible fields (same as old backend)
                        # Twilio provides caller phone in different fields depending on call type
                        self.caller_phone = (
                            start_data.get("callerPhoneNumber") or 
                            start_data.get("from") or 
                            start_data.get("caller") or
                            ""
                        )
                        
                        # Also check custom parameters if available (for outbound calls)
                        custom_params = start_data.get("customParameters", {})
                        if not self.caller_phone and custom_params:
                            self.caller_phone = custom_params.get("phone_number", "")
                        
                        # Store call metadata for webhook lookup (CRITICAL - this is how we get phone number later)
                        if self.call_sid and self.caller_phone:
                            await CallRecordService.store_call_metadata(
                                call_sid=self.call_sid,
                                caller_name="Customer",  # Will be updated from transcript if available
                                phone_number=self.caller_phone
                            )
                            logger.info(f"[Handler] Stored call metadata - SID: {self.call_sid}, Phone: {self.caller_phone}")
                        elif self.call_sid:
                            logger.warning(f"[Handler] Call SID available but no phone number found in start event. Fields: {list(start_data.keys())}")
                        
                        logger.info(f"[Handler] Call started - SID: {self.call_sid}, Caller: {self.caller_phone}")
                        
                        # Initialize conversation context after start event
                        await self._initialize_conversation_context()
                        
                    elif event_type == "media":
                        # Forward audio to ElevenLabs
                        if self.elevenlabs_ws and not self.elevenlabs_closed:
                            media_payload = data.get("media", {})
                            chunk = media_payload.get("payload")
                            
                            if chunk:
                                # Send audio chunk directly to ElevenLabs
                                audio_message = {
                                    "user_audio_chunk": chunk
                                }
                                try:
                                    await self.elevenlabs_ws.send(json.dumps(audio_message))
                                except Exception as e:
                                    logger.error(f"[Handler] Failed to send audio to ElevenLabs: {e}")
                    
                    elif event_type == "stop":
                        logger.info("[Handler] Twilio stream stopped")
                        break
            
            except WebSocketDisconnect:
                logger.info("[Handler] Twilio disconnected")
            except Exception as e:
                logger.error(f"[Handler] Error handling Twilio messages: {e}")
        
        async def handle_elevenlabs_messages():
            try:
                if not self.elevenlabs_ws:
                    return
                
                async for message in self.elevenlabs_ws:
                    if self.elevenlabs_closed:
                        break
                    
                    data = json.loads(message)
                    msg_type = data.get("type")
                    
                    if msg_type == "conversation_initiation_metadata":
                        # Extract conversation_id from different possible formats
                        if isinstance(data, dict):
                            if "conversation_id" in data:
                                self.conversation_id = data.get("conversation_id")
                            elif "conversation_initiation_metadata_event" in data:
                                metadata_event = data.get("conversation_initiation_metadata_event", {})
                                self.conversation_id = metadata_event.get("conversation_id")
                        
                        if self.conversation_id:
                            logger.info(f"[ElevenLabs] Conversation ID: {self.conversation_id}")
                            
                            # Link conversation_id to call_sid for webhook lookup
                            if self.call_sid:
                                await CallRecordService.link_conversation_to_call(
                                    conversation_id=self.conversation_id,
                                    call_sid=self.call_sid
                                )
                                logger.info(f"[Handler] Linked conversation_id={self.conversation_id} to call_sid={self.call_sid}")
                        else:
                            logger.warning("[ElevenLabs] No conversation_id found in metadata event")
                    
                    elif msg_type == "audio":
                        # Forward audio from ElevenLabs to Twilio
                        audio_base64 = None
                        if data.get("audio", {}).get("chunk"):
                            audio_base64 = data["audio"]["chunk"]
                        elif data.get("audio_event", {}).get("audio_base_64"):
                            audio_base64 = data["audio_event"]["audio_base_64"]
                        elif isinstance(data.get("audio"), str):
                            audio_base64 = data["audio"]
                        
                        if audio_base64 and self.stream_sid:
                            media_message = {
                                "event": "media",
                                "streamSid": self.stream_sid,
                                "media": {
                                    "payload": audio_base64
                                }
                            }
                            try:
                                await self.websocket.send_json(media_message)
                            except Exception as e:
                                logger.error(f"[Handler] Failed to send audio to Twilio: {e}")
            
            except Exception as e:
                logger.error(f"[Handler] Error handling ElevenLabs messages: {e}")
            finally:
                self.elevenlabs_closed = True
        
        # Wait for start event before starting ElevenLabs handler
        timeout = 5.0
        start_time = asyncio.get_event_loop().time()
        
        while not start_event_received and (asyncio.get_event_loop().time() - start_time) < timeout:
            await asyncio.sleep(0.1)
        
        if not start_event_received:
            logger.warning("[Handler] Start event not received, proceeding anyway")
        
        # Run both handlers concurrently
        await asyncio.gather(
            handle_twilio_messages(),
            handle_elevenlabs_messages(),
            return_exceptions=True
        )
    
    async def _cleanup(self):
        """Cleanup resources."""
        try:
            if self.elevenlabs_ws and not self.elevenlabs_closed:
                await self.elevenlabs_ws.close()
                self.elevenlabs_closed = True
            
            if self.websocket:
                try:
                    await self.websocket.close()
                except:
                    pass
        except Exception as e:
            logger.error(f"[Handler] Error during cleanup: {e}")

