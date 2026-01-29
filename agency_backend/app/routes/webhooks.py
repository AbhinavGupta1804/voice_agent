"""Webhook handlers for voice agent call completion."""
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Header, Form
from fastapi.responses import JSONResponse, Response

from ..config import Config
from ..handlers.dashboard_ws import dashboard_manager
from ..models import (
    CallCompletePayload, 
    CallRecordResponse, 
    ElevenLabsWebhookPayload,
    InsightModel,
    NotificationPreferences
)
from ..services.call_record_service import CallRecordService
from ..services.openai_service import OpenAIService
from ..services.email_service import EmailService
from ..services.whatsapp_service import WhatsAppService
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
        Handle incoming WhatsApp message responses (confirm/reschedule).
        
        This endpoint receives webhooks from Twilio when users reply to WhatsApp messages.
        """
        try:
            # Parse the incoming message
            message_body = Body.strip().upper()
            from_number = From.replace("whatsapp:", "")
            
            logger.info(f"[WhatsApp Webhook] Received response from {from_number}: {message_body}")
            
            # Handle user responses
            if message_body == "CONFIRM":
                # User confirmed the appointment
                response_message = "✅ Great! Your appointment has been confirmed. We look forward to speaking with you!"
                await WhatsAppService.send_simple_message(from_number, response_message)
                
                # TODO: Update the call record with confirmation status
                logger.info(f"[WhatsApp Webhook] Appointment confirmed by {from_number}")
                
            elif message_body == "RESCHEDULE":
                # User wants to reschedule
                response_message = "📅 No problem! Please call us back at your convenience to reschedule your appointment, or reply with your preferred date and time."
                await WhatsAppService.send_simple_message(from_number, response_message)
                
                logger.info(f"[WhatsApp Webhook] Reschedule requested by {from_number}")
            
            else:
                # Generic response for other messages
                response_message = "Thank you for your message. If you'd like to confirm your appointment, reply CONFIRM. To reschedule, reply RESCHEDULE."
                await WhatsAppService.send_simple_message(from_number, response_message)
            
            # Return empty TwiML response
            return Response(content="", media_type="application/xml")
            
        except Exception as exc:
            logger.error(f"[WhatsApp Webhook] Error processing response: {exc}")
            return Response(content="", media_type="application/xml")

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
    
    Logs the failure for monitoring and notifies the dashboard.
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


async def _send_post_call_notifications(payload: CallCompletePayload, record: dict) -> None:
    """
    Send post-call notifications via email and/or WhatsApp based on user preferences.
    
    Args:
        payload: The call completion payload with notification preferences.
        record: The saved call record.
    """
    if not payload.notification_preferences:
        logger.info("[PostCallNotifications] No notification preferences set, skipping")
        return
    
    prefs = payload.notification_preferences
    
    # Helper function to get phone number from multiple sources
    async def _get_phone_number_fallback() -> Optional[str]:
        """Get phone number from multiple sources with fallbacks."""
        # Try 1: From notification preferences (extracted by AI)
        if prefs.whatsapp_number and _is_valid_phone_number(prefs.whatsapp_number):
            logger.info(f"[PostCallNotifications] Using WhatsApp number from preferences: {prefs.whatsapp_number}")
            return prefs.whatsapp_number
        
        # Try 2: From payload phone_number
        if payload.phone_number and _is_valid_phone_number(payload.phone_number):
            logger.info(f"[PostCallNotifications] Using phone number from payload: {payload.phone_number}")
            return payload.phone_number
        
        # Try 3: From database record
        if record.get("phone_number") and _is_valid_phone_number(record.get("phone_number")):
            logger.info(f"[PostCallNotifications] Using phone number from database record: {record.get('phone_number')}")
            return record.get("phone_number")
        
        # Try 4: From call metadata using conversation_id
        if payload.call_id:
            metadata_phone = await CallRecordService.get_phone_number_from_conversation(payload.call_id)
            if metadata_phone and _is_valid_phone_number(metadata_phone):
                logger.info(f"[PostCallNotifications] Using phone number from call metadata: {metadata_phone}")
                return metadata_phone
        
        logger.warning("[PostCallNotifications] No valid phone number found from any source")
        return None
    
    # Send email notification if requested
    if prefs.notify_email and prefs.email_address:
        try:
            email_result = await EmailService.send_call_summary_email(
                to_email=prefs.email_address,
                client_name=payload.client_name,
                summary=payload.summary or "No summary available.",
                follow_up_date=payload.follow_up_date
            )
            
            if email_result.get("success"):
                logger.info(f"[PostCallNotifications] Email sent to {prefs.email_address}")
                # Update the record to mark email as sent
                prefs.email_sent = True
            else:
                logger.warning(f"[PostCallNotifications] Email failed: {email_result.get('error')}")
        except Exception as e:
            logger.error(f"[PostCallNotifications] Email error: {e}")
    
    # Send WhatsApp notification if requested
    if prefs.notify_whatsapp:
        # Get phone number from multiple sources with fallbacks
        whatsapp_number = await _get_phone_number_fallback()
        
        if whatsapp_number:
            try:
                whatsapp_result = await WhatsAppService.send_call_summary_whatsapp(
                    to_number=whatsapp_number,
                    client_name=payload.client_name,
                    summary=payload.summary or "No summary available.",
                    follow_up_date=payload.follow_up_date,
                    call_id=payload.call_id
                )
            
                if whatsapp_result.get("success"):
                    logger.info(f"[PostCallNotifications] WhatsApp sent to {whatsapp_number}")
                    # Update the record to mark WhatsApp as sent
                    prefs.whatsapp_sent = True
                    # Update the stored number in preferences if we used a different source
                    if whatsapp_number != prefs.whatsapp_number:
                        prefs.whatsapp_number = whatsapp_number
                        logger.info(f"[PostCallNotifications] Updated preferences with phone number: {whatsapp_number}")
                else:
                    logger.warning(f"[PostCallNotifications] WhatsApp failed: {whatsapp_result.get('error')}")
            except Exception as e:
                logger.error(f"[PostCallNotifications] WhatsApp error: {e}")
        else:
            logger.warning(
                "[PostCallNotifications] No valid WhatsApp number available for notification. "
                "Tried: preferences, payload, database record, and call metadata."
            )
    
    # Update record with notification status if any were sent
    if prefs.email_sent or prefs.whatsapp_sent:
        try:
            updated_payload = CallCompletePayload(**record)
            updated_payload.notification_preferences = prefs
            await CallRecordService.upsert_call_record(updated_payload)
            logger.info("[PostCallNotifications] Updated record with notification status")
        except Exception as e:
            logger.warning(f"[PostCallNotifications] Failed to update notification status: {e}")
