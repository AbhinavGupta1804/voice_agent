"""Webhook handlers for voice agent call completion."""
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Header, Form
from fastapi.responses import JSONResponse, Response

from ..config import Config
from ..handlers.dashboard_ws import dashboard_manager
from .groq_proxy import generate_groq_response, ChatMessage
from ..models import (
    CallCompletePayload, 
    CallRecordResponse, 
    ElevenLabsWebhookPayload,
    InsightModel,
    NotificationPreferences
)
from ..services.call_record_service import CallRecordService
from ..services.follow_up_service import ScheduledFollowUpService
from ..services.conversation_service import ConversationService
from ..services.openai_service import OpenAIService
from ..services.email_service import EmailService
from ..services.whatsapp_service import WhatsAppService
from ..services.twilio_service import TwilioService
from ..utils.webhook_security import verify_hmac_signature

logger = logging.getLogger(__name__)


def _is_valid_phone_number(phone: str) -> bool:
    """
    Validate if a phone number is actually a phone number and not text.
    
    Args:
        phone: Phone number string to validate
        
    Returns:
        bool: True if it's a valid phone number format, False otherwise
    """
    if not phone or not isinstance(phone, str):
        return False
    
    # Remove common prefixes and whitespace
    cleaned = phone.replace("whatsapp:", "").replace("+", "").strip()
    
    # Check if it contains only digits (and possibly + at start)
    # Valid phone numbers should be mostly numeric
    if not cleaned:
        return False
    
    # Check if it's all digits (after removing + and whatsapp:)
    if not cleaned.isdigit():
        return False
    
    # Check for common invalid patterns (text that might be extracted)
    invalid_patterns = [
        "exactly", "this", "number", "same", "called", "call", 
        "current", "present", "that", "which", "you"
    ]
    phone_lower = phone.lower()
    for pattern in invalid_patterns:
        if pattern in phone_lower:
            return False
    
    # Check minimum length (phone numbers should be at least 10 digits)
    if len(cleaned) < 10:
        return False
    
    return True


def register_webhook_routes(app):
    """Register webhook routes."""
    router = APIRouter(tags=["Webhooks"])

    @router.post("/webhook/call_complete")
    async def call_complete_webhook(
        request: Request,
        elevenlabs_signature: str = Header(None, alias="ElevenLabs-Signature")
    ):
        """
        Handle ElevenLabs post-call webhooks.
        
        Handles both types:
        - post_call_transcription: Contains transcript, analysis, metadata
        - post_call_audio: Contains base64-encoded audio data
        
        This endpoint verifies the HMAC signature from ElevenLabs before processing.
        """
        try:
            # Handle chunked transfer encoding for audio webhooks
            if request.headers.get("transfer-encoding", "").lower() == "chunked":
                chunks = []
                async for chunk in request.stream():
                    chunks.append(chunk)
                raw_body = b''.join(chunks)
            else:
                raw_body = await request.body()
            
            # Verify HMAC signature if webhook secret is configured
            if Config.ELEVENLABS_WEBHOOK_SECRET:
                if not elevenlabs_signature:
                    raise HTTPException(
                        status_code=401,
                        detail="Missing ElevenLabs-Signature header"
                    )
                
                if not verify_hmac_signature(
                    raw_body,
                    elevenlabs_signature,
                    Config.ELEVENLABS_WEBHOOK_SECRET
                ):
                    raise HTTPException(
                        status_code=401,
                        detail="Invalid webhook signature"
                    )
            
            # Parse and validate payload
            try:
                raw_data = json.loads(raw_body)
                webhook_type = raw_data.get("type", "")
                
                logger.info(f"[Webhook] Received webhook type: {webhook_type}")
                
                # Handle audio webhook separately
                if webhook_type == "post_call_audio":
                    return await _handle_audio_webhook(raw_data)
                
                # Handle call initiation failure webhook
                if webhook_type == "call_initiation_failure":
                    return await _handle_call_failure_webhook(raw_data)
                
                # Parse as ElevenLabs transcription webhook format
                # elevenlabs_payload = ElevenLabsWebhookPayload.model_validate(raw_data)
                
                # Transform ElevenLabs payload to our internal format
                # Build transcript text from conversation turns
                transcript_text = ""
                for turn in raw_data['data']['transcript']:
                    if turn['message']:
                        role_label = turn['role'].capitalize()
                        transcript_text += f"{role_label}: {turn['message']}\n"
                
                # Extract client name from stored metadata (set during call initiation)
                conversation_id = raw_data['data']['conversation_id']
                metadata = raw_data['data']['metadata']
                
                # Get call_type, client_name, and phone_number from stored call metadata FIRST
                call_type = await CallRecordService.get_call_type_from_conversation(conversation_id)
                client_name = await CallRecordService.get_client_name_from_conversation(conversation_id) or "Unknown"
                phone_number = await CallRecordService.get_phone_number_from_conversation(conversation_id) or ""
                
                # If call_type is still None, try to infer it from client_name
                if not call_type:
                    if client_name == "Customer":
                        call_type = "inbound"
                        logger.info(f"[Webhook] Inferred call_type='inbound' from client_name='Customer'")
                    elif client_name != "Unknown":
                        # If we have a real client name but no call_type, it's likely outbound
                        call_type = "outbound"
                        logger.info(f"[Webhook] Inferred call_type='outbound' from client_name='{client_name}'")
                
                # Final fallback: Detect call_type from transcript (agent's first message pattern)
                # Inbound: "Hey Sir" | Outbound: "Hey {name}"
                if not call_type and transcript_text.strip():
                    detected_call_type = OpenAIService.detect_call_type_from_transcript(transcript_text.strip())
                    if detected_call_type:
                        call_type = detected_call_type
                        logger.info(f"[Webhook] Detected call_type='{call_type}' from transcript analysis")
                
                logger.info(f"[Webhook] Retrieved metadata - call_type={call_type}, client_name={client_name}, phone_number={phone_number}")
                
                # Fallback: Try to get client_name from webhook payload metadata
                if client_name == "Unknown":
                    client_name = metadata.get("client_name", "Unknown")
                
                # Fallback: Try to get from webhook payload dynamic variables (legacy support)
                if client_name == "Unknown" and 'conversation_initiation_client_data' in raw_data.get('data', {}):
                    init_data = raw_data['data']['conversation_initiation_client_data']
                    if isinstance(init_data, dict):
                        dynamic_vars = init_data.get('dynamic_variables', {})
                        if isinstance(dynamic_vars, dict):
                            client_name = dynamic_vars.get('client_name', 'Unknown')
                            logger.info(f"[Webhook] Fallback: Extracted client name from payload: {client_name}")
                
                if client_name != "Unknown":
                    logger.info(f"[Webhook] Using client name: {client_name}")
                else:
                    logger.warning(f"[Webhook] No client name found for conversation_id={conversation_id}")
                
                # Extract topics from summary if available
                topics = []
                if raw_data['data']['analysis'] and raw_data['data']['analysis']['call_summary_title']:
                    topics = [raw_data['data']['analysis']['call_summary_title']]
                
                # Determine conversion status (you may want to adjust this logic)
                conversion_status = (
                    raw_data['data']['analysis']['call_successful'] == "success"
                    if raw_data['data']['analysis'] else False
                )
                
                # Extract recording URL from metadata or data
                recording_url = None
                
                if recording_url:
                    logger.info(f"[Webhook] Found recording URL: {recording_url[:50]}...")
                else:
                    logger.info("[Webhook] No recording URL found in payload")
                
                # Create our internal payload format
                payload = CallCompletePayload(
                    call_id=raw_data['data']['conversation_id'],
                    client_name=client_name,
                    transcript=transcript_text.strip(),
                    insights=InsightModel(
                        topics=topics,
                        duration_sec=raw_data['data']['metadata']['call_duration_secs']
                    ),
                    conversion_status=conversion_status,
                    sentiment=None,
                    timestamp=datetime.fromtimestamp(raw_data['event_timestamp'], tz=timezone.utc),
                    recording_url=recording_url,
                    call_type=call_type
                )
                
                # Fallback 2: Try to get phone_number from webhook payload dynamic variables if not already retrieved
                if not phone_number:
                    phone_number = metadata.get("phone_number", "")
                
                # Fallback 3: Try to get from webhook payload dynamic variables
                if not phone_number and 'conversation_initiation_client_data' in raw_data.get('data', {}):
                    init_data = raw_data['data']['conversation_initiation_client_data']
                    if isinstance(init_data, dict):
                        dynamic_vars = init_data.get('dynamic_variables', {})
                        if isinstance(dynamic_vars, dict):
                            phone_number = dynamic_vars.get('phone_number', phone_number)
                
                if phone_number:
                    logger.info(f"[Webhook] Phone number retrieved: {phone_number}")
                else:
                    logger.warning(f"[Webhook] No phone number found in metadata for conversation_id={conversation_id}")
                
                # Single analysis using OpenAI (summary, conversion, sentiment, notifications)
                try:
                    ai_result = await OpenAIService.analyze_call_structured(
                        transcript_text.strip(),
                        phone_number or None,
                    )

                    payload.summary = ai_result.get("summary")
                    payload.conversion_status = ai_result.get("conversion_status", False)
                    payload.sentiment = ai_result.get("sentiment", "neutral")
                    payload.phone_number = phone_number
                    
                    # For inbound calls, extract user name from transcript if client_name is still "Customer" or "Unknown"
                    extracted_user_name = ai_result.get("user_name")
                    if extracted_user_name and call_type == "inbound":
                        # Only update if we still have placeholder names
                        if client_name in ["Customer", "Unknown"]:
                            client_name = extracted_user_name
                            payload.client_name = extracted_user_name
                            logger.info(f"[Webhook] Extracted user name from transcript for inbound call: {extracted_user_name}")

                    # Extract WhatsApp number and validate it
                    extracted_whatsapp_number = ai_result.get("whatsapp_number")
                    
                    # If extracted number is invalid (contains text like "exactly_this_number"),
                    # fall back to the actual phone number used for the call
                    if extracted_whatsapp_number and not _is_valid_phone_number(extracted_whatsapp_number):
                        logger.warning(
                            f"[Webhook] Invalid WhatsApp number extracted: '{extracted_whatsapp_number}'. "
                            f"Using call phone number as fallback: {phone_number}"
                        )
                        extracted_whatsapp_number = phone_number
                    
                    # Notification preferences
                    payload.notification_preferences = NotificationPreferences(
                        notify_email=ai_result.get("notify_email", False),
                        notify_whatsapp=ai_result.get("notify_whatsapp", False),
                        email_address=ai_result.get("email_address"),
                        whatsapp_number=extracted_whatsapp_number,
                    )

                    logger.info(
                        "[Webhook] OpenAI structured analysis -> conversion=%s, sentiment=%s, notify_email=%s, notify_whatsapp=%s",
                        payload.conversion_status,
                        payload.sentiment,
                        payload.notification_preferences.notify_email,
                        payload.notification_preferences.notify_whatsapp,
                    )
                    
                    # Store follow_up_datetime in payload (for calls table backward compatibility)
                    if ai_result.get("follow_up_datetime"):
                        try:
                            follow_up_dt = datetime.fromisoformat(ai_result["follow_up_datetime"].replace('Z', '+00:00'))
                            payload.follow_up_date = follow_up_dt.date().isoformat()
                        except Exception:
                            payload.follow_up_date = None
                    
                    # Debug log for follow-up check
                    logger.info(f"[Webhook DEBUG] ai_result follow_up check: required={ai_result.get('follow_up_required')}, datetime={ai_result.get('follow_up_datetime')}")
                    
                    # Schedule follow-up call if customer requested callback
                    if ai_result.get("follow_up_required") and ai_result.get("follow_up_datetime"):
                        try:
                            follow_up_dt = datetime.fromisoformat(ai_result["follow_up_datetime"].replace('Z', '+00:00'))
                            logger.info(f"[Webhook DEBUG] Attempting to create follow-up: call_id={payload.call_id}, phone={phone_number}, scheduled_at={follow_up_dt}")
                            await ScheduledFollowUpService.create_follow_up(
                                call_id=payload.call_id,
                                phone_number=phone_number,
                                client_name=client_name,
                                scheduled_at=follow_up_dt,
                                context={
                                    "summary": payload.summary,
                                    "original_call_date": datetime.now(timezone.utc).isoformat(),
                                    "call_type": call_type
                                },
                                follow_up_first_message=ai_result.get("follow_up_first_message"),
                            )
                            logger.info(f"[Webhook] Scheduled follow-up call for {follow_up_dt}")
                        except Exception as follow_up_error:
                            logger.error(f"[Webhook] Failed to schedule follow-up: {follow_up_error}")
                except Exception as ai_error:
                    logger.warning(f"[Webhook] OpenAI structured analysis failed, using defaults: {ai_error}")
                
            except Exception as e:
                logger.error(f"[Webhook] Failed to parse payload: {e}")
                raise HTTPException(status_code=400, detail=f"Invalid payload structure: {e}")
            
            # Process the webhook
            logger.info(f"[Webhook] About to upsert call record for call_id={payload.call_id}")
            try:
                record = await CallRecordService.upsert_call_record(payload)
                logger.info(f"[Webhook] Successfully upserted call record, got {len(record)} fields back")
                response_model = CallRecordResponse(**record)
            except Exception as upsert_error:
                logger.error(f"[Webhook] Failed to upsert call record: {upsert_error}", exc_info=True)
                raise
            
            # Send post-call notifications
            await _send_post_call_notifications(payload, record)
            
            # Clean up stored metadata
            await CallRecordService.cleanup_call_metadata(conversation_id)
            
            # Broadcast full record so the dashboard stays in sync
            await dashboard_manager.broadcast(
                "call_completed",
                response_model.model_dump(mode="json"),
            )
            
            return {"status": "success", "call_id": response_model.call_id}
            
        except HTTPException:
            raise
        except Exception as exc:  # pragma: no cover - network/db errors
            logger.error("[Webhook] call_complete error: %s", exc)
            raise HTTPException(status_code=500, detail="Failed to process webhook")

    @router.post("/webhook/whatsapp_response")
    async def whatsapp_response_webhook(
        request: Request,
        Body: str = Form(default=""),
        From: str = Form(default=""),
        To: str = Form(default="")
    ):
        """
        Handle incoming WhatsApp messages: store in conversation thread, then reply (confirm/reschedule or generic bot).
        """
        try:
            raw_body = (Body or "").strip()
            from_number = (From or "").replace("whatsapp:", "").strip()
            
            logger.info(f"[DEBUG] Webhook triggered. From: {from_number}, Body: {raw_body}")

            if not from_number:
                logger.error("[DEBUG] Missing from_number")
                return Response(content="", media_type="application/xml")

            # Get or create thread
            try:
                thread = await ConversationService.get_or_create_thread(from_number, "whatsapp")
                thread_id = thread.get("id")
                logger.info(f"[DEBUG] Thread Found/Created: ID={thread_id}")
            except Exception as e:
                logger.error(f"[DEBUG] Failed to get thread: {e}")
                thread_id = None

            if thread_id:
                try:
                    msg = await ConversationService.add_message(
                        thread_id=thread_id,
                        body=raw_body,
                        direction="inbound",
                        sender_type="client",  # CHANGED from 'user' to 'client' to match DB constraint
                        twilio_message_sid=None,
                    )
                    logger.info(f"[DEBUG] Inbound Message Saved: {msg}")
                    await dashboard_manager.broadcast("conversation_message", {"thread_id": thread_id, "channel": "whatsapp"})
                except Exception as e:
                     logger.error(f"[DEBUG] Failed to save inbound msg: {e}")

            # --- AI RESPONSE LOGIC ---
            message_body_upper = raw_body.upper()
            
            # Special Keywords Override AI
            if message_body_upper == "CONFIRM":
                response_message = "✅ Great! Your appointment has been confirmed. We look forward to speaking with you!"
            elif message_body_upper == "RESCHEDULE":
                response_message = "📅 No problem! Please call us back at your convenience to reschedule your appointment, or reply with your preferred date and time."
            else:
                # Generate AI Response using Groq
                try:
                    # 1. Fetch recent history for context
                    history = []
                    if thread_id:
                        # Get last 15 messages (Chronological: Oldest -> Newest) using get_recent_messages
                        # This ensures we see the ACTUAL latest conversation, not just the first 10 ever.
                        raw_msgs = await ConversationService.get_recent_messages(thread_id, limit=15)
                        for m in raw_msgs:
                            role = "assistant" if m["sender_type"] in ("bot", "client") else "user"
                            history.append(ChatMessage(role=role, content=m["body"]))
                    
                    # 2. Add current message
                    history.append(ChatMessage(role="user", content=raw_body))
                    
                    # 3. Generate Response
                    response_message = await generate_groq_response(
                        messages=history,
                        temperature=0.7,
                        max_tokens=200
                    )
                    
                    # Fallback if empty
                    if not (response_message and response_message.strip()):
                         response_message = "I received your message but couldn't generate a response. Please try again."

                except Exception as e:
                    logger.error(f"[AI] Failed to generate response: {e}")
                    response_message = "Thanks for your message. We'll get back to you shortly."

            logger.info(f"[DEBUG] Sending Reply: {response_message}")
            result = await WhatsAppService.send_simple_message(from_number, response_message)
            message_sid = result.get("message_sid") if isinstance(result, dict) else None
            
            if thread_id and message_sid:
                await ConversationService.add_message(
                    thread_id=thread_id,
                    body=response_message,
                    direction="outbound",
                    sender_type="bot",
                    twilio_message_sid=message_sid,
                )
                logger.info(f"[DEBUG] Outbound Reply Saved: {message_sid}")

            return Response(content="", media_type="application/xml")
        except Exception as exc:
            logger.error(f"[WhatsApp Webhook] Error: {exc}", exc_info=True)
            return Response(content="", media_type="application/xml")

    @router.post("/webhook/inbound-email")
    async def inbound_email_webhook(request: Request):
        """
        Handle inbound email from a provider (SendGrid, Mailgun, etc.).
        Expects JSON: { "from_email": "...", "to_email": "...", "subject": "...", "body": "..." }.
        Stores message in conversation thread and optionally sends bot auto-reply.
        Configure your email provider to POST to this URL when an email is received.
        """
        try:
            body = await request.json()
            from_email = (body.get("from_email") or body.get("from") or "").strip().lower()
            to_email = (body.get("to_email") or body.get("to") or "").strip().lower()
            subject = (body.get("subject") or "").strip()
            text = (body.get("body") or body.get("text") or body.get("text_plain") or "").strip()
            if not from_email or "@" not in from_email:
                return JSONResponse(content={"status": "ignored", "reason": "missing from_email"}, status_code=200)
            if not text:
                text = subject or "(No content)"

            thread = await ConversationService.get_or_create_thread(channel="email", email_address=from_email)
            thread_id = thread.get("id")
            if thread_id:
                await ConversationService.add_message(
                    thread_id=thread_id,
                    body=subject and f"Subject: {subject}\n\n{text}" or text,
                    direction="inbound",
                    sender_type="user",
                )
                await dashboard_manager.broadcast("conversation_message", {"thread_id": thread_id, "channel": "email"})

            reply_text = "Thanks for your email. We'll get back to you shortly."
            email_result = await EmailService.send_simple_email(to_email=from_email, body=reply_text)
            if email_result.get("success") and thread_id:
                await ConversationService.add_message(
                    thread_id=thread_id,
                    body=reply_text,
                    direction="outbound",
                    sender_type="bot",
                )
                await dashboard_manager.broadcast("conversation_message", {"thread_id": thread_id, "channel": "email"})

            return JSONResponse(content={"status": "ok", "thread_id": thread_id})
        except Exception as exc:
            logger.error(f"[Inbound Email Webhook] Error: {exc}", exc_info=True)
            return JSONResponse(content={"status": "error", "message": str(exc)}, status_code=500)

    @router.post("/webhook/incoming-sms")
    async def incoming_sms_webhook(
        request: Request,
        Body: str = Form(default=""),
        From: str = Form(default=""),
        To: str = Form(default="")
    ):
        """
        Handle incoming SMS: store in conversation thread, then send bot ack via SMS.
        Configure this URL in Twilio Console for your phone number's "A MESSAGE COMES IN" webhook.
        """
        try:
            raw_body = (Body or "").strip()
            from_number = (From or "").strip()
            if not from_number:
                return Response(content="<Response></Response>", media_type="application/xml")

            thread = await ConversationService.get_or_create_thread(from_number, "sms")
            thread_id = thread.get("id")
            if thread_id:
                await ConversationService.add_message(
                    thread_id=thread_id,
                    body=raw_body,
                    direction="inbound",
                    sender_type="client",  # Fixed: Match DB constraint
                    twilio_message_sid=None,
                )
                await dashboard_manager.broadcast("conversation_message", {"thread_id": thread_id, "channel": "sms"})

            # Generate AI Response using Groq (same logic as WhatsApp)
            response_message = "Thanks for your message. We'll get back to you shortly."
            try:
                # 1. Fetch recent history for context
                history = []
                if thread_id:
                    # Get last 15 messages (Chronological)
                    raw_msgs = await ConversationService.get_recent_messages(thread_id, limit=15)
                    for m in raw_msgs:
                        role = "assistant" if m["sender_type"] in ("bot", "agent") else "user"
                        history.append(ChatMessage(role=role, content=m["body"]))
                
                # 2. Add current message
                history.append(ChatMessage(role="user", content=raw_body))
                
                # 3. Generate Response
                ai_response = await generate_groq_response(
                    messages=history,
                    temperature=0.7,
                    max_tokens=150  # Keep SMS shorter
                )
                
                if ai_response and ai_response.strip():
                     response_message = ai_response.strip()

            except Exception as e:
                logger.error(f"[SMS AI] Failed to generate response: {e}")
                # Fallback to default message

            twilio_service = TwilioService()
            result = await twilio_service.send_sms(from_number, response_message)
            message_sid = result.get("message_sid") if result.get("success") else None
            if thread_id and message_sid:
                await ConversationService.add_message(
                    thread_id=thread_id,
                    body=response_message,
                    direction="outbound",
                    sender_type="bot",
                    twilio_message_sid=message_sid,
                )

            return Response(content="<Response></Response>", media_type="application/xml")
        except Exception as exc:
            logger.error(f"[SMS Webhook] Error: {exc}", exc_info=True)
            return Response(content="<Response></Response>", media_type="application/xml")

    @router.post("/webhook/twilio-call-status")
    async def twilio_call_status_webhook(
        request: Request,
        CallSid: str = Form(default=""),
        CallStatus: str = Form(default=""),
    ):
        """
        Twilio StatusCallback for outbound follow-up calls.
        Called when the call ends (completed, no-answer, busy, canceled, failed).
        Use ?follow_up_id=<id> in the StatusCallback URL when initiating the call.
        """
        try:
            follow_up_id_param = request.query_params.get("follow_up_id")
            if not follow_up_id_param or not follow_up_id_param.isdigit():
                logger.warning("[Webhook] Twilio call status missing or invalid follow_up_id")
                return Response(content="", status_code=200)
            follow_up_id = int(follow_up_id_param)
            logger.info(f"[Webhook] Twilio call status: CallSid={CallSid}, CallStatus={CallStatus}, follow_up_id={follow_up_id}")
            if CallStatus == "completed":
                await ScheduledFollowUpService.update_status(follow_up_id, "completed")
                logger.info(f"[Webhook] Follow-up id={follow_up_id} marked completed (call answered and ended)")
            elif CallStatus in ("no-answer", "busy", "canceled", "failed"):
                reason = CallStatus.replace("-", " ")
                await ScheduledFollowUpService.update_status(follow_up_id, "failed", reason)
                updated = await ScheduledFollowUpService.mark_not_picked_if_max_retries(follow_up_id)
                if updated:
                    logger.info(f"[Webhook] Follow-up id={follow_up_id} marked not_picked (max retries reached)")
                else:
                    await ScheduledFollowUpService.retry_failed_follow_up(follow_up_id, retry_delay_minutes=15)
                    logger.info(f"[Webhook] Follow-up id={follow_up_id} scheduled for retry")
            else:
                logger.debug(f"[Webhook] Ignoring CallStatus={CallStatus} for follow_up_id={follow_up_id}")
            return Response(content="", status_code=200)
        except Exception as exc:
            logger.error(f"[Webhook] Twilio call status error: {exc}", exc_info=True)
            return Response(content="", status_code=200)

    app.include_router(router)


async def _handle_audio_webhook(raw_data: dict) -> dict:
    """
    Handle post_call_audio webhook from ElevenLabs.
    
    Audio webhooks contain base64-encoded audio data that we save to disk
    and then update the corresponding call record with the audio URL.
    """
    try:
        data = raw_data.get("data", {})
        conversation_id = data.get("conversation_id")
        full_audio = data.get("full_audio")
        
        if not conversation_id:
            logger.error("[Webhook] Audio webhook missing conversation_id")
            return {"status": "error", "message": "Missing conversation_id"}
        
        if not full_audio:
            logger.error(f"[Webhook] Audio webhook for {conversation_id} missing full_audio")
            return {"status": "error", "message": "Missing full_audio"}
        
        logger.info(f"[Webhook] Processing audio webhook for conversation_id={conversation_id}")
        logger.info(f"[Webhook] Audio data size: {len(full_audio)} chars (base64)")
        
        # Save the audio file and get the URL
        recording_url = await CallRecordService.save_audio_recording(conversation_id, full_audio)
        
        if recording_url:
            # Update the call record with the recording URL
            updated = await CallRecordService.update_recording_url(conversation_id, recording_url)
            
            if updated:
                logger.info(f"[Webhook] Successfully processed audio for {conversation_id}: {recording_url}")
                
                # Broadcast update to dashboard
                await dashboard_manager.broadcast(
                    "call_audio_ready",
                    {"call_id": conversation_id, "recording_url": recording_url}
                )
                
                return {"status": "success", "call_id": conversation_id, "recording_url": recording_url}
            else:
                logger.warning(f"[Webhook] Audio saved but no call record found for {conversation_id}")
                return {"status": "partial", "message": "Audio saved but call record not found"}
        else:
            logger.error(f"[Webhook] Failed to save audio for {conversation_id}")
            return {"status": "error", "message": "Failed to save audio"}
            
    except Exception as e:
        logger.error(f"[Webhook] Error processing audio webhook: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


async def _handle_call_failure_webhook(raw_data: dict) -> dict:
    """
    Handle call_initiation_failure webhook from ElevenLabs.

    Logs the failure for monitoring, notifies the dashboard, and schedules
    a follow-up call when the user didn't pick up (no answer / busy / etc.).
    """
    try:
        data = raw_data.get("data", {})
        agent_id = data.get("agent_id")
        conversation_id = data.get("conversation_id")
        failure_reason = data.get("failure_reason")
        metadata = data.get("metadata", {})

        logger.warning(f"[Webhook] Call initiation failed - agent={agent_id}, conversation={conversation_id}")
        logger.warning(f"[Webhook] Failure reason: {failure_reason}")
        logger.warning(f"[Webhook] Metadata: {metadata}")

        if not conversation_id:
            await dashboard_manager.broadcast(
                "call_failed",
                {"agent_id": agent_id, "conversation_id": None, "failure_reason": failure_reason, "metadata": metadata}
            )
            return {"status": "acknowledged", "failure_reason": failure_reason}

        # Resolve phone_number and client_name for follow-up (no-answer scenario)
        phone_number = await CallRecordService.get_phone_number_from_conversation(conversation_id)
        if not phone_number and metadata:
            phone_number = metadata.get("phone_number") or metadata.get("to") or ""
        if isinstance(phone_number, str):
            phone_number = phone_number.strip() or None

        client_name = await CallRecordService.get_client_name_from_conversation(conversation_id)
        if not client_name and metadata:
            client_name = metadata.get("client_name") or ""
        client_name = (client_name or metadata.get("client_name") or "Unknown").strip() or "Unknown"

        # Schedule follow-up when we have a valid phone number (mark as follow-up: user didn't pick up)
        if conversation_id and phone_number and _is_valid_phone_number(phone_number):
            delay_minutes = getattr(Config, "FOLLOW_UP_NO_ANSWER_DELAY_MINUTES", 15)
            scheduled_at = datetime.now(timezone.utc) + timedelta(minutes=delay_minutes)
            try:
                follow_up_id = await ScheduledFollowUpService.create_follow_up(
                    call_id=conversation_id,
                    phone_number=phone_number,
                    client_name=client_name,
                    scheduled_at=scheduled_at,
                    context={
                        "reason": "no_answer",
                        "failure_reason": failure_reason,
                        "original_attempt": "call_initiation_failure",
                        "summary": f"Follow-up: user did not pick up ({failure_reason or 'unknown'})",
                    },
                )
                if follow_up_id:
                    logger.info(
                        f"[Webhook] Scheduled no-answer follow-up id={follow_up_id} for {conversation_id} "
                        f"at {phone_number}, scheduled_at={scheduled_at.isoformat()}"
                    )
                else:
                    logger.warning(f"[Webhook] Failed to create no-answer follow-up for {conversation_id}")
            except Exception as follow_up_err:
                logger.error(f"[Webhook] Error scheduling no-answer follow-up: {follow_up_err}", exc_info=True)
        else:
            if not phone_number or not _is_valid_phone_number(phone_number):
                logger.warning(
                    f"[Webhook] No valid phone number for no-answer follow-up (conversation_id={conversation_id}). "
                    "Skipping scheduled follow-up."
                )

        # Broadcast to dashboard
        await dashboard_manager.broadcast(
            "call_failed",
            {
                "agent_id": agent_id,
                "conversation_id": conversation_id,
                "failure_reason": failure_reason,
                "metadata": metadata
            }
        )

        return {"status": "acknowledged", "failure_reason": failure_reason}

    except Exception as e:
        logger.error(f"[Webhook] Error processing call failure webhook: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


def _build_post_call_summary_body(client_name: str, summary: str, follow_up_date: Optional[str] = None) -> str:
    """Build the summary + brochure message body for recording in conversation."""
    follow_up_line = f"\n\n📅 Scheduled Follow-up: {follow_up_date}" if follow_up_date else ""
    return (
        f"📞 Call Summary for {client_name}\n\n"
        f"Hello {client_name}! Thank you for your recent call. Here's a summary of our conversation:\n\n"
        f"📝 Summary:\n{summary}{follow_up_line}\n\n"
        f"📎 Attached: Our brochure with more information about our services.\n\n"
        "---\n_This is an automated message from DevFuzzion Voice Assistant._"
    )


async def _send_post_call_notifications(payload: CallCompletePayload, record: dict) -> None:
    """
    Send brochure + summary after every call via WhatsApp and/or email when contact info is available,
    and record each sent message in the conversation thread for the Chats page.
    """
    prefs = payload.notification_preferences or NotificationPreferences(
        notify_email=False, notify_whatsapp=False, email_address=None, whatsapp_number=None,
        email_sent=False, whatsapp_sent=False,
    )

    # Helper: get phone number from multiple sources
    async def _get_phone_number_fallback() -> Optional[str]:
        if prefs.whatsapp_number and _is_valid_phone_number(prefs.whatsapp_number):
            return prefs.whatsapp_number
        if payload.phone_number and _is_valid_phone_number(payload.phone_number):
            return payload.phone_number
        if record.get("phone_number") and _is_valid_phone_number(record.get("phone_number")):
            return record.get("phone_number")
        if payload.call_id:
            metadata_phone = await CallRecordService.get_phone_number_from_conversation(payload.call_id)
            if metadata_phone and _is_valid_phone_number(metadata_phone):
                return metadata_phone
        return None

    # Helper: get email from multiple sources
    def _get_email_fallback() -> Optional[str]:
        email = (prefs.email_address or "").strip() or None
        if email and "@" in email:
            return email
        # Could extend to payload/record if we add email_address there later
        return None

    summary_text = payload.summary or "No summary available."
    summary_body_for_conversation = _build_post_call_summary_body(
        payload.client_name, summary_text, payload.follow_up_date
    )

    # ----- WhatsApp: send brochure + summary after every call when we have a number -----
    whatsapp_number = await _get_phone_number_fallback()
    if whatsapp_number:
        try:
            whatsapp_result = await WhatsAppService.send_call_summary_whatsapp(
                to_number=whatsapp_number,
                client_name=payload.client_name,
                summary=summary_text,
                follow_up_date=payload.follow_up_date,
                call_id=payload.call_id,
            )
            if whatsapp_result is None:
                whatsapp_result = {"success": False, "error": "No response from WhatsApp service"}
            if whatsapp_result.get("success"):
                logger.info(f"[PostCallNotifications] WhatsApp (brochure + summary) sent to {whatsapp_number}")
                prefs.whatsapp_sent = True
                if whatsapp_number != (prefs.whatsapp_number or ""):
                    prefs.whatsapp_number = whatsapp_number
                # Record in conversation so it shows on Chats page
                try:
                    thread = await ConversationService.get_or_create_thread(whatsapp_number, "whatsapp")
                    if thread.get("id"):
                        await ConversationService.add_message(
                            thread_id=thread["id"],
                            body=summary_body_for_conversation,
                            direction="outbound",
                            sender_type="bot",
                            twilio_message_sid=whatsapp_result.get("message_sid"),
                        )
                        await dashboard_manager.broadcast("conversation_message", {"thread_id": thread["id"], "channel": "whatsapp"})
                except Exception as rec:
                    logger.warning(f"[PostCallNotifications] Failed to record WhatsApp in conversation: {rec}")
            else:
                logger.warning(f"[PostCallNotifications] WhatsApp failed: {whatsapp_result.get('error')}")
        except Exception as e:
            logger.error(f"[PostCallNotifications] WhatsApp error: {e}")
    else:
        logger.debug("[PostCallNotifications] No valid phone number for WhatsApp")

    # ----- SMS: send short summary after every call when we have a number -----
    sms_number = await _get_phone_number_fallback()
    if sms_number:
        try:
            sms_body = f"Call Summary for {payload.client_name}:\n{summary_text}"
            twilio_service = TwilioService()
            sms_result = await twilio_service.send_sms(sms_number, sms_body)
            
            if sms_result.get("success"):
                logger.info(f"[PostCallNotifications] SMS summary sent to {sms_number}")
                # Record in conversation
                try:
                    thread = await ConversationService.get_or_create_thread(sms_number, "sms")
                    if thread.get("id"):
                        await ConversationService.add_message(
                            thread_id=thread["id"],
                            body=sms_body,
                            direction="outbound",
                            sender_type="bot",
                            twilio_message_sid=sms_result.get("message_sid"),
                        )
                        await dashboard_manager.broadcast("conversation_message", {"thread_id": thread["id"], "channel": "sms"})
                except Exception as rec:
                    logger.warning(f"[PostCallNotifications] Failed to record SMS in conversation: {rec}")
            else:
                logger.warning(f"[PostCallNotifications] SMS failed: {sms_result.get('error')}")
        except Exception as e:
            logger.error(f"[PostCallNotifications] SMS error: {e}")
    else:
        logger.debug("[PostCallNotifications] No valid phone number for SMS")

    # ----- Email: send brochure + summary after every call when we have an email -----
    email_address = _get_email_fallback()
    if email_address:
        try:
            email_result = await EmailService.send_call_summary_email(
                to_email=email_address,
                client_name=payload.client_name,
                summary=summary_text,
                follow_up_date=payload.follow_up_date,
            )
            if email_result is None:
                email_result = {"success": False, "error": "No response from email service"}
            if email_result.get("success"):
                logger.info(f"[PostCallNotifications] Email (brochure + summary) sent to {email_address}")
                prefs.email_sent = True
                if email_address != (prefs.email_address or ""):
                    prefs.email_address = email_address
                # Record in conversation so it shows on Chats page
                try:
                    thread = await ConversationService.get_or_create_thread(channel="email", email_address=email_address)
                    if thread.get("id"):
                        await ConversationService.add_message(
                            thread_id=thread["id"],
                            body=summary_body_for_conversation,
                            direction="outbound",
                            sender_type="bot",
                        )
                        await dashboard_manager.broadcast("conversation_message", {"thread_id": thread["id"], "channel": "email"})
                except Exception as rec:
                    logger.warning(f"[PostCallNotifications] Failed to record email in conversation: {rec}")
            else:
                logger.warning(f"[PostCallNotifications] Email failed: {email_result.get('error')}")
        except Exception as e:
            logger.error(f"[PostCallNotifications] Email error: {e}")
    else:
        logger.debug("[PostCallNotifications] No valid email address for email")

    if prefs.email_sent or prefs.whatsapp_sent:
        try:
            updated_payload = CallCompletePayload.model_validate(record)
            updated_payload.notification_preferences = prefs
            await CallRecordService.upsert_call_record(updated_payload)
            logger.info("[PostCallNotifications] Updated record with notification status")
        except Exception as e:
            logger.warning(f"[PostCallNotifications] Failed to update notification status: {e}")
