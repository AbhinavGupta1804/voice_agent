"""WebSocket handler for inbound calls."""

import asyncio
import json
import logging
from typing import Optional
from fastapi import WebSocket, WebSocketDisconnect
import websockets

from ..services.elevenlabs_service import ElevenLabsService
from ..services.call_record_service import CallRecordService

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
        logger.info("[InboundHandler] Twilio connected to inbound media stream")
        
        try:
            # Connect to ElevenLabs immediately using signed URL
            await self._setup_elevenlabs()
            
            # Handle the connection with concurrent tasks
            await self._handle_connection()
        
        except Exception as e:
            logger.error(f"[InboundHandler] Error in inbound media stream: {e}")
        
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
        """Send conversation initiation payload with first message override for inbound calls."""
        if not self.elevenlabs_ws:
            return

        init_payload = {
            "type": "conversation_initiation_client_data",
            "custom_llm_extra_body": {},
        }

        conversation_override = {}
        first_message = self._build_first_message()
        if first_message:
            conversation_override["agent"] = {"first_message": first_message}

        if conversation_override:
            init_payload["conversation_config_override"] = conversation_override
        else:
            init_payload["conversation_config_override"] = {}

        dynamic_variables = self._build_dynamic_variables()
        if dynamic_variables:
            init_payload["dynamic_variables"] = dynamic_variables

        try:
            await self.elevenlabs_ws.send(json.dumps(init_payload))
            logger.info("[ElevenLabs] Sent inbound first message override")
        except Exception as exc:
            logger.error("[ElevenLabs] Failed to send conversation initiation payload: %s", exc)

    def _build_first_message(self) -> str:
        """Create the agent's first message for inbound calls."""
        return "Hey, मैं Priya बोल रही हूँ Naturals Ice Cream से. How can I help you today with our delicious handcrafted ice creams?"

    def _build_dynamic_variables(self) -> dict:
        """Assemble dynamic variables for the ElevenLabs conversation context."""
        dynamic_vars = {}
        if self.caller_phone:
            dynamic_vars["phone_number"] = self.caller_phone
        return dynamic_vars
    
    async def _handle_connection(self):
        """Handle the WebSocket connection lifecycle."""
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
                        
                        # Extract phone number from multiple possible fields
                        # Extract phone number from multiple possible fields
                        custom_params = start_data.get("customParameters", {})
                        self.caller_phone = (
                            custom_params.get("from") or
                            start_data.get("callerPhoneNumber") or 
                            start_data.get("from") or 
                            start_data.get("caller") or
                            ""
                        )
                        
                        # Extract caller name if available
                        client_name = custom_params.get("callerName") or "Customer"
                        
                        logger.info(f"[InboundHandler] Call started - SID: {self.call_sid}, Caller: {self.caller_phone}, Name: {client_name}")
                        
                        # Store call metadata for webhook lookup
                        if self.call_sid and self.caller_phone:
                            await CallRecordService.store_call_metadata(
                                call_sid=self.call_sid,
                                client_name=client_name,
                                phone_number=self.caller_phone,
                                call_type="inbound"
                            )
                        
                        # Initialize conversation context after start event
                        await self._initialize_conversation_context()
                    
                    elif event_type == "media":
                        # Forward audio to ElevenLabs
                        if self.elevenlabs_ws and not self.elevenlabs_closed:
                            media_payload = data.get("media", {})
                            chunk = media_payload.get("payload")
                            
                            if chunk:
                                audio_message = {
                                    "user_audio_chunk": chunk
                                }
                                try:
                                    await self.elevenlabs_ws.send(json.dumps(audio_message))
                                except websockets.exceptions.ConnectionClosed:
                                    logger.info("[InboundHandler] ElevenLabs connection closed while sending audio")
                                    return
                                except Exception as e:
                                    logger.error(f"[InboundHandler] Failed to send audio to ElevenLabs: {e}")
                    
                    elif event_type == "stop":
                        logger.info("[InboundHandler] Twilio stream stopped")
                        break
            
            except WebSocketDisconnect:
                logger.info("[InboundHandler] Twilio disconnected")
            except Exception as e:
                logger.error(f"[InboundHandler] Error handling Twilio messages: {e}")
        
        async def handle_elevenlabs_messages():
            try:
                if not self.elevenlabs_ws:
                    return
                
                async for message in self.elevenlabs_ws:
                    if self.elevenlabs_closed:
                        break
                    
                    data = json.loads(message)
                    msg_type = data.get("type")
                    
                    # Handle ping/pong
                    if msg_type == "ping":
                        event_id = data.get("ping_event", {}).get("event_id")
                        if event_id:
                            pong_response = {
                                "type": "pong",
                                "event_id": event_id
                            }
                            await self.elevenlabs_ws.send(json.dumps(pong_response))
                            continue
                    
                    if msg_type == "conversation_initiation_metadata":
                        # Extract conversation_id
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
                            except (RuntimeError, WebSocketDisconnect):
                                # "Cannot call 'send' once a close message has been sent."
                                logger.info("[InboundHandler] Twilio connection closed while sending audio")
                                return
                            except Exception as e:
                                logger.error(f"[InboundHandler] Failed to send audio to Twilio: {e}")
                    
                    elif msg_type == "interruption":
                        if self.stream_sid:
                            clear_message = {
                                "event": "clear",
                                "streamSid": self.stream_sid
                            }
                            await self.websocket.send_text(json.dumps(clear_message))
            
            except websockets.exceptions.ConnectionClosed:
                self.elevenlabs_closed = True
            except Exception as e:
                logger.error(f"[InboundHandler] Error handling ElevenLabs messages: {e}")
                self.elevenlabs_closed = True
        
        # Wait for start event before starting ElevenLabs handler
        timeout = 5.0
        start_time = asyncio.get_event_loop().time()
        
        while not start_event_received and (asyncio.get_event_loop().time() - start_time) < timeout:
            await asyncio.sleep(0.1)
        
        if not start_event_received:
            logger.warning("[InboundHandler] Start event not received, proceeding anyway")
        
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
            logger.error(f"[InboundHandler] Error during cleanup: {e}")
