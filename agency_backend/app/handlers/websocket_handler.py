"""WebSocket handler for outbound calls."""
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


class OutboundWebSocketHandler:
    """Handles WebSocket communication for outbound calls."""
    
    def __init__(self, websocket: WebSocket, client_name: str = "", phone_number: str = "", follow_up_first_message: str = ""):
        """
        Initialize the handler.
        
        Args:
            websocket: WebSocket connection from Twilio
            client_name: Client name from query parameters
            phone_number: Phone number from query parameters
            follow_up_first_message: Optional first message for follow-up calls (continuity from previous call).
        """
        self.websocket = websocket
        self.stream_sid: Optional[str] = None
        self.call_sid: Optional[str] = None
        self.conversation_id: Optional[str] = None
        self.elevenlabs_ws: Optional[websockets.WebSocketClientProtocol] = None
        self.client_name: str = client_name
        self.phone_number: str = phone_number
        self.follow_up_first_message: str = follow_up_first_message
        self.elevenlabs_closed: bool = False  # Track if ElevenLabs connection is closed
    
    async def handle(self):
        """Handle the WebSocket connection."""
        await self.websocket.accept()
        logger.info("[Handler] Twilio connected to outbound media stream")
        logger.info(f"[Handler] Client: {self.client_name}, Phone: {self.phone_number}")
        
        try:
            # Connect to ElevenLabs immediately using signed URL
            await self._setup_elevenlabs()
            
            # Handle the connection with concurrent tasks
            await self._handle_connection()
        
        except Exception as e:
            logger.error(f"[Handler] Error in outbound media stream: {e}")
        
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
            # Don't initialize conversation context yet - wait for Twilio start event
            # which contains the custom parameters with client name
            
        except asyncio.TimeoutError:
            logger.error("[ElevenLabs] Connection timeout")
            raise
        except Exception as e:
            logger.error(f"[ElevenLabs] Connection failed: {e}")
            raise
    
    async def _initialize_conversation_context(self):
        """Send conversation initiation payload with first message override."""
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
            logger.info(
                "[ElevenLabs] Sent first message override for %s",
                dynamic_variables.get("client_name", "unknown") if dynamic_variables else "unknown",
            )
        except Exception as exc:
            logger.error("[ElevenLabs] Failed to send conversation initiation payload: %s", exc)

    def _build_first_message(self) -> str:
        """Create the agent's first message. Use LLM-generated follow-up message when present for continuity."""
        if (self.follow_up_first_message or "").strip():
            return self.follow_up_first_message.strip()
        name = (self.client_name or "").strip()
        if not name:
            # Keep short to minimise TTS latency — every word adds ~50-100ms.
            return "Hello! This is Neha calling from Naturals Ice Cream. How may I help you?"
        # Keep short to minimise TTS latency — every word adds ~50-100ms.
        return f"Hello {name}! This is Neha calling from Naturals Ice Cream. How may I help you?"

    def _build_dynamic_variables(self) -> dict:
        """Assemble dynamic variables for the ElevenLabs conversation context."""
        dynamic_vars = {}
        if self.client_name:
            dynamic_vars["client_name"] = self.client_name
        if self.phone_number:
            dynamic_vars["phone_number"] = self.phone_number
        return dynamic_vars

    async def _handle_connection(self):
        """Handle the WebSocket connection lifecycle."""
        # Shared event so both handlers know when to stop
        stop_event = asyncio.Event()
        
        async def handle_elevenlabs_with_stop():
            """Wrapped handler that respects stop event."""
            try:
                async for message in self.elevenlabs_ws:
                    # Exit early if Twilio stopped
                    if stop_event.is_set() or self.elevenlabs_closed:
                        break
                    
                    try:
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
                        
                        await self._process_elevenlabs_message(data)
                    
                    except json.JSONDecodeError as e:
                        logger.error(f"[ElevenLabs] JSON decode error: {e}")
                    except Exception as e:
                        logger.error(f"[ElevenLabs] Error processing message: {e}")
            
            except websockets.exceptions.ConnectionClosed as e:
                self.elevenlabs_closed = True  # Mark ElevenLabs as closed
                stop_event.set()  # Signal Twilio handler to stop
                
                # Give Twilio time to flush audio
                await asyncio.sleep(1)
                try:
                    # Only try to send if websocket is still connected
                    if self.websocket.client_state.name == "CONNECTED":
                        await self.websocket.send_text(json.dumps({"event": "stop"}))
                        await self.websocket.close()
                except Exception:
                    pass
            
            except Exception as e:
                logger.error(f"[ElevenLabs] Error: {e}")
                stop_event.set()
        
        async def handle_twilio_with_stop():
            """Wrapped handler that respects stop event."""
            try:
                while True:
                    # Check if ElevenLabs connection is closed or stop was signaled
                    if self.elevenlabs_closed or stop_event.is_set():
                        break
                    
                    message = await self.websocket.receive_text()
                    data = json.loads(message)
                    
                    event = data.get("event")
                    
                    if event == "start":
                        self.stream_sid = data["start"]["streamSid"]
                        self.call_sid = data["start"]["callSid"]
                        
                        # Register active call for end_call tool
                        if self.call_sid and self.phone_number:
                            register_call(self.phone_number, self.call_sid)
                        
                        # Extract custom parameters from Twilio Stream
                        custom_params = data["start"].get("customParameters", {})
                        if custom_params:
                            self.client_name = custom_params.get("client_name", "")
                            self.phone_number = custom_params.get("phone_number", "")
                            self.follow_up_first_message = custom_params.get("follow_up_first_message", "")
                            logger.info(f"[Handler] Extracted from Stream params - Client: {self.client_name}, Phone: {self.phone_number}, has_follow_up_first_message={bool(self.follow_up_first_message)}")
                            
                            # Now that we have all the info, re-initialize ElevenLabs with correct context
                            if self.elevenlabs_ws:
                                await self._initialize_conversation_context()
                    
                    elif event == "media":
                        # Only forward audio if ElevenLabs is still connected
                        if self.elevenlabs_ws and not self.elevenlabs_closed:
                            try:
                                # Forward audio to ElevenLabs
                                audio_payload = data["media"]["payload"]
                                audio_message = {
                                    "user_audio_chunk": audio_payload
                                }
                                await self.elevenlabs_ws.send(json.dumps(audio_message))
                            except websockets.exceptions.ConnectionClosed:
                                # ElevenLabs closed, mark it and stop forwarding
                                self.elevenlabs_closed = True
                                stop_event.set()
                                break
                            except Exception as e:
                                logger.error(f"[ElevenLabs] Failed to send audio: {e}")
                                # Don't continue if there's a persistent error
                                if "received 1000" in str(e) or "then sent 1000" in str(e):
                                    self.elevenlabs_closed = True
                                    stop_event.set()
                                    break
                    
                    elif event == "stop":
                        logger.info("[Handler] Twilio stream stopped")
                        stop_event.set()  # Signal ElevenLabs handler to stop
                        break
            
            except WebSocketDisconnect:
                logger.info("[Handler] Twilio disconnected")
                stop_event.set()
            except Exception as e:
                logger.error(f"[Twilio] Error: {e}")
                stop_event.set()
        
        # Start bidirectional communication
        try:
            await asyncio.gather(
                handle_elevenlabs_with_stop(),
                handle_twilio_with_stop(),
                return_exceptions=True
            )
        finally:
            # CRITICAL: Close ElevenLabs immediately when either handler stops/errors.
            # This prevents the "call continues at ElevenLabs until timeout" issue.
            if self.elevenlabs_ws and not self.elevenlabs_closed:
                try:
                    await asyncio.wait_for(self.elevenlabs_ws.close(), timeout=2.0)
                    logger.info("[Handler] ElevenLabs connection closed")
                except asyncio.TimeoutError:
                    logger.warning("[Handler] ElevenLabs close timed out")
                except Exception as e:
                    logger.warning(f"[Handler] Error closing ElevenLabs: {e}")
                self.elevenlabs_closed = True
    
    async def _process_elevenlabs_message(self, message: dict):
        """
        Process messages from ElevenLabs.
        
        Args:
            message: Message from ElevenLabs
        """
        msg_type = message.get("type")
        
        if msg_type == "conversation_initiation_metadata":
            metadata = message.get("conversation_initiation_metadata_event", {})
            if metadata.get("conversation_id"):
                self.conversation_id = metadata["conversation_id"]
                logger.info(f"[ElevenLabs] Conversation ID: {self.conversation_id}")
                
                # Link conversation_id to call_sid for webhook lookup
                if self.call_sid:
                    await CallRecordService.link_conversation_to_call(
                        conversation_id=self.conversation_id,
                        call_sid=self.call_sid
                    )
        
        elif msg_type == "audio":
            # Handle audio chunks
            audio_base64 = None
            if message.get("audio", {}).get("chunk"):
                audio_base64 = message["audio"]["chunk"]
            elif message.get("audio_event", {}).get("audio_base_64"):
                audio_base64 = message["audio_event"]["audio_base_64"]
            
            if audio_base64 and self.stream_sid:
                audio_data = {
                    "event": "media",
                    "streamSid": self.stream_sid,
                    "media": {
                        "payload": audio_base64
                    }
                }
                await self.websocket.send_text(json.dumps(audio_data))
        
        elif msg_type == "interruption":
            if self.stream_sid:
                clear_message = {
                    "event": "clear",
                    "streamSid": self.stream_sid
                }
                await self.websocket.send_text(json.dumps(clear_message))
        
        elif msg_type == "user_transcript":
            user_text = message.get("user_transcription_event", {}).get("user_transcript", "")
            if user_text:
                logger.info(f"[User] {user_text}")
        
        elif msg_type == "agent_response":
            agent_text = message.get("agent_response_event", {}).get("agent_response", "")
            if agent_text:
                logger.info(f"[Agent] {agent_text}")
    
    async def _cleanup(self):
        """Cleanup resources."""
        # Unregister from active calls
        if self.phone_number:
            unregister_call(self.phone_number)
        
        if self.elevenlabs_ws and not self.elevenlabs_closed:
            try:
                await self.elevenlabs_ws.close()
                self.elevenlabs_closed = True
            except:
                pass
        try:
            await self.websocket.close()
        except:
            pass
        logger.info("[Handler] Connections closed")
