"""WebSocket handler for inbound calls."""

import asyncio
import json
import logging
from typing import Optional
from fastapi import WebSocket, WebSocketDisconnect
import websockets

from ..services.elevenlabs_service import ElevenLabsService
from ..services.call_record_service import CallRecordService
from ..utils.active_calls import register_call, unregister_call

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
            
            # Do NOT send init here — we need caller_phone from Twilio "start" first.
            # Init is sent in handle_twilio_messages() when we get "start", so
            # dynamic_variables.phone_number is set and tools (create_ticket) don't fail.
            # Handle the connection with concurrent tasks
            await self._handle_connection()
        
        except Exception as e:
            logger.error(f"[InboundHandler] Error in inbound media stream: {e}", exc_info=True)

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
        # Always set phone_number so tools (create_ticket) don't get "Missing required dynamic variables"
        if "phone_number" not in dynamic_variables:
            dynamic_variables["phone_number"] = self.caller_phone or ""
        init_payload["dynamic_variables"] = dynamic_variables

        try:
            await self.elevenlabs_ws.send(json.dumps(init_payload))
            logger.info(
                "[ElevenLabs] Sent conversation init with dynamic_variables.phone_number=%s",
                self.caller_phone or "(empty)",
            )
        except Exception as exc:
            logger.error("[ElevenLabs] Failed to send conversation initiation payload: %s", exc)

    def _build_first_message(self) -> str:
        """Create the agent's first message for inbound calls.
        
        Kept short to minimise TTS latency — every word adds ~50-100ms.
        """
        return "Hello! This is Neha calling from Naturals Ice Cream. How may I help you?"

    def _build_dynamic_variables(self) -> dict:
        """Assemble dynamic variables for the ElevenLabs conversation context."""
        dynamic_vars = {}
        if self.caller_phone:
            dynamic_vars["phone_number"] = self.caller_phone
        return dynamic_vars
    
    async def _handle_connection(self):
        """Handle the WebSocket connection lifecycle."""
        
        # Shared event so both handlers know when to stop
        stop_event = asyncio.Event()
        
        async def handle_twilio_messages():
            try:
                async for message in self.websocket.iter_text():
                    if not message:
                        continue
                    
                    data = json.loads(message)
                    event_type = data.get("event")
                    
                    if event_type == "start":
                        start_data = data.get("start", {})
                        self.stream_sid = start_data.get("streamSid")
                        self.call_sid = start_data.get("callSid")
                        
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
                            register_call(self.caller_phone, self.call_sid)
                            await CallRecordService.store_call_metadata(
                                call_sid=self.call_sid,
                                client_name=client_name,
                                phone_number=self.caller_phone,
                                call_type="inbound"
                            )
                        # Send conversation init NOW (first and only time) so dynamic_variables.phone_number is set.
                        # ElevenLabs requires this before tools run; we have caller_phone from "start".
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
                        stop_event.set()  # Signal both handlers to stop
                        return  # Exit handle_twilio_messages
            
            except WebSocketDisconnect as e:
                logger.info(
                    "[InboundHandler] Twilio disconnected (code=%s). Call may have been hung up or network/ngrok dropped.",
                    getattr(e, "code", "?"),
                )
                stop_event.set()
            except Exception as e:
                logger.error(f"[InboundHandler] Error handling Twilio messages: {e}")
                stop_event.set()
        
        async def handle_elevenlabs_messages():
            try:
                if not self.elevenlabs_ws:
                    return
                
                async for message in self.elevenlabs_ws:
                    # Stop reading if Twilio stopped
                    if stop_event.is_set() or self.elevenlabs_closed:
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
                            
                            # Link conversation_id to call_sid for webhook lookup and tool fallback
                            if self.call_sid:
                                await CallRecordService.link_conversation_to_call(
                                    conversation_id=self.conversation_id,
                                    call_sid=self.call_sid
                                )
                            # Push conversation_id so tools (e.g. create_ticket) can send it and we resolve phone
                            if self.elevenlabs_ws and not self.elevenlabs_closed:
                                try:
                                    update = {
                                        "type": "conversation_initiation_client_data",
                                        "dynamic_variables": {"conversation_id": self.conversation_id},
                                    }
                                    await self.elevenlabs_ws.send(json.dumps(update))
                                    logger.info("[InboundHandler] Sent dynamic_variables.conversation_id=%s", self.conversation_id)
                                except Exception as e:
                                    logger.warning("[InboundHandler] Failed to send conversation_id to ElevenLabs: %s", e)
                    
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
            
            except websockets.exceptions.ConnectionClosed as e:
                self.elevenlabs_closed = True
                logger.warning(
                    "[InboundHandler] ElevenLabs WebSocket closed (code=%s, reason=%s). "
                    "If this happens right after conversation_initiation_metadata, check ElevenLabs agent config or signed URL.",
                    getattr(e, "code", "?"),
                    getattr(e, "reason", str(e))[:200],
                )
            except Exception as e:
                logger.error(f"[InboundHandler] Error handling ElevenLabs messages: {e}")
                self.elevenlabs_closed = True
        
        # Run both handlers concurrently — no polling delay!
        # Conversation init was already sent in handle() so ElevenLabs
        # can start generating the greeting while Twilio finishes setup.
        try:
            results = await asyncio.gather(
                handle_twilio_messages(),
                handle_elevenlabs_messages(),
                return_exceptions=True,
            )
            for i, r in enumerate(results):
                if isinstance(r, Exception):
                    logger.warning("[InboundHandler] Handler task %s exited with: %s", i, r)
        finally:
            # CRITICAL: Close ElevenLabs immediately when either handler stops/errors.
            # This prevents the "call continues at ElevenLabs until timeout" issue.
            if self.elevenlabs_ws and not self.elevenlabs_closed:
                try:
                    await asyncio.wait_for(self.elevenlabs_ws.close(), timeout=2.0)
                    logger.info("[InboundHandler] ElevenLabs connection closed")
                except asyncio.TimeoutError:
                    logger.warning("[InboundHandler] ElevenLabs close timed out")
                except Exception as e:
                    logger.warning(f"[InboundHandler] Error closing ElevenLabs: {e}")
                self.elevenlabs_closed = True
    
    async def _cleanup(self):
        """Cleanup resources."""
        try:
            # Unregister from active calls
            if self.caller_phone:
                unregister_call(self.caller_phone)

            if self.elevenlabs_ws and not self.elevenlabs_closed:
                await self.elevenlabs_ws.close()
                self.elevenlabs_closed = True

            if self.websocket:
                try:
                    await self.websocket.close()
                    logger.info("[InboundHandler] Closed Twilio WebSocket (cleanup)")
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"[InboundHandler] Error during cleanup: {e}")
