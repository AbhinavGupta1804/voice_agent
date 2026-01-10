"""Webhook handlers for call completion and order processing."""
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Header, Form
from fastapi.responses import Response

from config import Config
from services.call_service import CallService
from services.order_service import OrderService
from services.openai_service import OpenAIService
from services.whatsapp_service import WhatsAppService
from utils.webhook_security import verify_hmac_signature

logger = logging.getLogger(__name__)


def _is_valid_phone_number(phone: str) -> bool:
    """Validate if a phone number is actually a phone number and not text."""
    if not phone or not isinstance(phone, str):
        return False
    
    cleaned = phone.replace("whatsapp:", "").replace("+", "").strip()
    
    if not cleaned:
        return False
    
    if not cleaned.isdigit():
        return False
    
    invalid_patterns = [
        "exactly", "this", "number", "same", "called", "call", 
        "current", "present", "that", "which", "you"
    ]
    phone_lower = phone.lower()
    for pattern in invalid_patterns:
        if pattern in phone_lower:
            return False
    
    if len(cleaned) < 10:
        return False
    
    return True


def register_webhook_routes(app):
    """Register webhook routes."""
    router = APIRouter(tags=["Webhooks"])
    
    @router.get("/webhook/call_complete")
    async def webhook_test():
        """Test endpoint to verify webhook route is accessible."""
        return {"status": "ok", "message": "Webhook endpoint is accessible", "method": "GET"}
    
    @router.post("/webhook/call_complete")
    async def call_complete_webhook(
        request: Request,
        elevenlabs_signature: str = Header(None, alias="ElevenLabs-Signature")
    ):
        """
        Handle ElevenLabs post-call webhooks.
        Extracts order details, creates order record, and sends WhatsApp notification.
        """
        logger.info("[Webhook] ========== WEBHOOK RECEIVED ==========")
        logger.info(f"[Webhook] Request method: {request.method}")
        logger.info(f"[Webhook] Request URL: {request.url}")
        logger.info(f"[Webhook] Headers: {dict(request.headers)}")
        
        try:
            # Handle chunked transfer encoding
            if request.headers.get("transfer-encoding", "").lower() == "chunked":
                logger.info("[Webhook] Reading chunked body...")
                chunks = []
                async for chunk in request.stream():
                    chunks.append(chunk)
                raw_body = b''.join(chunks)
                logger.info(f"[Webhook] Chunked body size: {len(raw_body)} bytes")
            else:
                raw_body = await request.body()
                logger.info(f"[Webhook] Body size: {len(raw_body)} bytes")
            
            logger.info(f"[Webhook] ElevenLabs-Signature header: {elevenlabs_signature}")
            logger.info(f"[Webhook] ELEVENLABS_WEBHOOK_SECRET configured: {bool(Config.ELEVENLABS_WEBHOOK_SECRET)}")
            
            # Verify HMAC signature if webhook secret is configured
            if Config.ELEVENLABS_WEBHOOK_SECRET:
                logger.info("[Webhook] Webhook secret is configured, verifying signature...")
                if not elevenlabs_signature:
                    logger.error("[Webhook] Missing ElevenLabs-Signature header")
                    raise HTTPException(
                        status_code=401,
                        detail="Missing ElevenLabs-Signature header"
                    )
                
                signature_valid = verify_hmac_signature(
                    raw_body,
                    elevenlabs_signature,
                    Config.ELEVENLABS_WEBHOOK_SECRET
                )
                
                if not signature_valid:
                    logger.error("[Webhook] HMAC signature verification FAILED")
                    logger.error(f"[Webhook] Received signature: {elevenlabs_signature}")
                    raise HTTPException(
                        status_code=401,
                        detail="Invalid webhook signature"
                    )
                else:
                    logger.info("[Webhook] HMAC signature verification PASSED")
            else:
                logger.info("[Webhook] No webhook secret configured, skipping signature verification")
            
            # Parse payload
            try:
                raw_body_str = raw_body.decode('utf-8') if isinstance(raw_body, bytes) else raw_body
                logger.info(f"[Webhook] Raw body (first 500 chars): {raw_body_str[:500]}")
                
                raw_data = json.loads(raw_body)
                webhook_type = raw_data.get("type", "")
                
                logger.info(f"[Webhook] Received webhook type: {webhook_type}")
                logger.info(f"[Webhook] Full webhook data keys: {list(raw_data.keys())}")
                
                # Process all webhook types, but only create orders from post_call_transcription
                if webhook_type == "post_call_transcription":
                    logger.info("[Webhook] Processing post_call_transcription webhook")
                elif webhook_type == "post_call_audio":
                    logger.info("[Webhook] Received post_call_audio webhook")
                    return await _handle_audio_webhook(raw_data)
                elif webhook_type == "call_initiation_failure":
                    logger.warning("[Webhook] Received call_initiation_failure webhook")
                    return {"status": "ok", "message": "Call initiation failure logged"}
                else:
                    logger.info(f"[Webhook] Unknown webhook type: {webhook_type}, returning success")
                    return {"status": "ok", "message": f"Webhook type {webhook_type} received but not processed"}
                
                # Only process post_call_transcription webhooks for order creation
                if webhook_type != "post_call_transcription":
                    logger.info(f"[Webhook] Skipping order processing for webhook type: {webhook_type}")
                    return {"status": "ok", "message": "Webhook received but not processed"}
                
                # Extract transcript
                transcript_text = ""
                for turn in raw_data.get('data', {}).get('transcript', []):
                    if turn.get('message'):
                        role_label = turn['role'].capitalize()
                        transcript_text += f"{role_label}: {turn['message']}\n"
                
                conversation_id = raw_data.get('data', {}).get('conversation_id')
                metadata = raw_data.get('data', {}).get('metadata', {})
                
                logger.info(f"[Webhook] Conversation ID: {conversation_id}")
                logger.info(f"[Webhook] Metadata keys: {list(metadata.keys()) if metadata else 'No metadata'}")
                
                # Get caller phone number from multiple sources with fallbacks
                # For inbound calls, ElevenLabs provides phone number in dynamic_variables.system__caller_id
                caller_phone = ""
                
                # Try 1: From ElevenLabs dynamic variables (PRIMARY for inbound calls)
                # This is where ElevenLabs stores the caller phone number for inbound calls
                if 'conversation_initiation_client_data' in raw_data.get('data', {}):
                    try:
                        init_data = raw_data['data']['conversation_initiation_client_data']
                        if isinstance(init_data, dict):
                            dynamic_vars = init_data.get('dynamic_variables', {})
                            if isinstance(dynamic_vars, dict):
                                # ElevenLabs stores caller phone in system__caller_id for inbound calls
                                system_caller_id = dynamic_vars.get('system__caller_id')
                                if system_caller_id:
                                    caller_phone = system_caller_id
                                    logger.info(f"[Webhook] Retrieved phone from ElevenLabs system__caller_id: {caller_phone}")
                                # Also check for phone_number in dynamic vars (fallback)
                                elif dynamic_vars.get('phone_number'):
                                    caller_phone = dynamic_vars.get('phone_number')
                                    logger.info(f"[Webhook] Retrieved phone from dynamic variables phone_number: {caller_phone}")
                    except Exception as e:
                        logger.warning(f"[Webhook] Failed to get phone from dynamic variables: {e}")
                
                # Try 2: From webhook metadata
                if not caller_phone:
                    caller_phone = (
                        metadata.get("caller_phone") or 
                        metadata.get("phone_number") or 
                        ""
                    )
                    if caller_phone:
                        logger.info(f"[Webhook] Retrieved phone from webhook metadata: {caller_phone}")
                
                # Try 3: From stored call metadata using conversation_id (fallback from Twilio start event)
                if not caller_phone and conversation_id:
                    try:
                        from services.call_record_service import CallRecordService
                        stored_phone = await CallRecordService.get_phone_number_from_conversation(conversation_id)
                        if stored_phone:
                            caller_phone = stored_phone
                            logger.info(f"[Webhook] Retrieved phone from stored call metadata (Twilio start event): {caller_phone}")
                    except Exception as e:
                        logger.warning(f"[Webhook] Failed to get phone from metadata: {e}")
                
                # Try 4: From phone_call metadata (ElevenLabs also provides this)
                if not caller_phone and 'phone_call' in raw_data.get('data', {}):
                    try:
                        phone_call_data = raw_data['data']['phone_call']
                        if isinstance(phone_call_data, dict):
                            external_number = phone_call_data.get('external_number')
                            if external_number:
                                caller_phone = external_number
                                logger.info(f"[Webhook] Retrieved phone from phone_call.external_number: {caller_phone}")
                    except Exception as e:
                        logger.warning(f"[Webhook] Failed to get phone from phone_call metadata: {e}")
                
                # Get caller name from metadata
                caller_name = metadata.get("caller_name") or ""
                
                # Try to get caller name from stored metadata
                if not caller_name and conversation_id:
                    try:
                        from services.call_record_service import CallRecordService
                        stored_name = await CallRecordService.get_caller_name_from_conversation(conversation_id)
                        if stored_name:
                            caller_name = stored_name
                            logger.info(f"[Webhook] Retrieved caller name from metadata: {caller_name}")
                    except ImportError:
                        pass
                    except Exception as e:
                        logger.warning(f"[Webhook] Failed to get caller name from metadata: {e}")
                
                if caller_phone:
                    logger.info(f"[Webhook] Final caller phone: {caller_phone}, caller name: {caller_name}")
                else:
                    logger.warning(f"[Webhook] No phone number found from any source for conversation_id={conversation_id}")
                
                # Extract summary
                analysis = raw_data.get('data', {}).get('analysis', {})
                summary = analysis.get('transcript_summary') or analysis.get('call_summary_title')
                
                # Extract caller name and sentiment from transcript using OpenAI
                sentiment = None
                extracted_caller_name = None
                if transcript_text.strip():
                    try:
                        ai_analysis = await OpenAIService.analyze_call_sentiment_and_name(transcript_text.strip())
                        extracted_caller_name = ai_analysis.get("caller_name")
                        sentiment = ai_analysis.get("sentiment", "neutral")
                        logger.info(f"[Webhook] Extracted caller_name: {extracted_caller_name}, sentiment: {sentiment}")
                    except Exception as e:
                        logger.warning(f"[Webhook] Failed to extract sentiment/name from transcript: {e}")
                
                # Use extracted caller name if available, otherwise use existing
                final_caller_name = extracted_caller_name or caller_name or metadata.get("caller_name") or "Customer"
                
                # Save call record
                call_record = {
                    "call_id": conversation_id,
                    "caller_name": final_caller_name,
                    "caller_phone": caller_phone,
                    "transcript": transcript_text.strip(),
                    "summary": summary,
                    "order_id": None,
                    "duration_sec": metadata.get('call_duration_secs', 0),
                    "call_timestamp": datetime.fromtimestamp(
                        raw_data.get('event_timestamp', datetime.now(timezone.utc).timestamp()),
                        tz=timezone.utc
                    ),
                    "recording_url": None,  # Will be updated by audio webhook
                    "sentiment": sentiment
                }
                
                saved_call = await CallService.create_call_record(call_record)
                logger.info(f"[Webhook] Call record saved: {conversation_id}")
                
                # Extract order details from transcript using OpenAI
                order_details = await OpenAIService.extract_order_details(
                    transcript_text,
                    caller_phone
                )
                
                # Create order if items were found
                order_id = None
                if order_details.get("items") and len(order_details.get("items", [])) > 0:
                    from models.order_models import OrderCreate, OrderItem as OrderItemModel
                    
                    items = [
                        OrderItemModel(
                            name=item.get("name", ""),
                            quantity=item.get("quantity", 1),
                            price=item.get("price"),
                            notes=item.get("notes")
                        )
                        for item in order_details.get("items", [])
                    ]
                    
                    # Get caller phone with fallback
                    final_caller_phone = (
                        caller_phone or 
                        order_details.get("caller_phone") or 
                        "UNKNOWN"
                    )
                    
                    order_create = OrderCreate(
                        caller_name=order_details.get("caller_name") or metadata.get("caller_name") or "Customer",
                        caller_phone=final_caller_phone,
                        items=items,
                        estimated_time_minutes=order_details.get("estimated_time_minutes"),
                        notes=order_details.get("notes"),
                        total_amount=order_details.get("total_amount"),
                        call_id=conversation_id
                    )
                    
                    created_order = await OrderService.create_order(order_create)
                    order_id = created_order.get("order_id")
                    
                    logger.info(f"[Webhook] Order created: {order_id}")
                    
                    # Update call record with order_id
                    call_record["order_id"] = order_id
                    await CallService.create_call_record(call_record)
                    
                    # Send WhatsApp notification with order details
                    whatsapp_number = final_caller_phone
                    if whatsapp_number and _is_valid_phone_number(whatsapp_number):
                        try:
                            whatsapp_result = await WhatsAppService.send_order_confirmation(
                                to_number=whatsapp_number,
                                caller_name=order_create.caller_name,
                                order_id=order_id,
                                items=[item.model_dump() if hasattr(item, 'model_dump') else item for item in items],
                                estimated_time_minutes=order_details.get("estimated_time_minutes")
                            )
                            
                            if whatsapp_result.get("success"):
                                logger.info(f"[Webhook] WhatsApp notification sent to {whatsapp_number}")
                            else:
                                logger.warning(f"[Webhook] WhatsApp notification failed: {whatsapp_result.get('error')}")
                        except Exception as e:
                            logger.error(f"[Webhook] Error sending WhatsApp notification: {e}")
                    else:
                        logger.warning(f"[Webhook] Invalid phone number for WhatsApp: {whatsapp_number}")
                else:
                    logger.info("[Webhook] No order items found in transcript, skipping order creation")
                
                return {
                    "status": "success",
                    "call_id": conversation_id,
                    "order_id": order_id
                }
            
            except json.JSONDecodeError as e:
                logger.error(f"[Webhook] Failed to parse JSON: {e}")
                logger.error(f"[Webhook] Raw body that failed to parse: {raw_body[:1000] if isinstance(raw_body, bytes) else raw_body}")
                raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}")
            except Exception as e:
                logger.error(f"[Webhook] Error processing webhook: {e}", exc_info=True)
                import traceback
                logger.error(f"[Webhook] Traceback: {traceback.format_exc()}")
                raise HTTPException(status_code=500, detail=str(e))
        
        except HTTPException as e:
            logger.error(f"[Webhook] HTTPException: {e.status_code} - {e.detail}")
            raise
        except Exception as e:
            logger.error(f"[Webhook] Unexpected error: {e}", exc_info=True)
            import traceback
            logger.error(f"[Webhook] Traceback: {traceback.format_exc()}")
            raise HTTPException(status_code=500, detail="Internal server error")
    
    @router.post("/webhook/whatsapp_response")
    async def whatsapp_response_webhook(
        request: Request,
        Body: str = Form(default=""),
        From: str = Form(default=""),
        To: str = Form(default="")
    ):
        """
        Handle incoming WhatsApp message responses from customers.
        
        This endpoint receives webhooks from Twilio when users reply to WhatsApp messages.
        """
        try:
            # Parse the incoming message
            message_body = Body.strip().upper() if Body else ""
            from_number = From.replace("whatsapp:", "") if From else ""
            
            logger.info(f"[WhatsApp Webhook] Received response from {from_number}: {message_body}")
            
            # Handle user responses (can be extended for order-related responses)
            if message_body in ["CONFIRM", "OK", "YES"]:
                response_message = "✅ Thank you for confirming! We'll keep you updated on your order status."
                await WhatsAppService.send_simple_message(from_number, response_message)
                logger.info(f"[WhatsApp Webhook] Confirmation received from {from_number}")
            
            elif message_body in ["CANCEL", "NO"]:
                response_message = "We're sorry to hear that. If you need to cancel your order, please call us directly. Thank you!"
                await WhatsAppService.send_simple_message(from_number, response_message)
                logger.info(f"[WhatsApp Webhook] Cancellation request from {from_number}")
            
            else:
                # Generic response for other messages
                response_message = "Thank you for your message! For order inquiries, please call us directly. We'll notify you via WhatsApp when your order is ready."
                await WhatsAppService.send_simple_message(from_number, response_message)
            
            # Return empty TwiML response
            return Response(content="", media_type="application/xml")
            
        except Exception as exc:
            logger.error(f"[WhatsApp Webhook] Error processing response: {exc}", exc_info=True)
            return Response(content="", media_type="application/xml")
    
    app.include_router(router)


async def _handle_audio_webhook(raw_data: dict) -> dict:
    """
    Handle post_call_audio webhook from ElevenLabs.
    
    Audio webhooks contain base64-encoded audio data that we save to R2
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
        
        # Save the audio file to R2 and get the URL
        from services.call_record_service import CallRecordService
        recording_url = await CallRecordService.save_audio_recording(conversation_id, full_audio)
        
        if recording_url:
            # Update the call record with the recording URL
            updated = await CallRecordService.update_recording_url(conversation_id, recording_url)
            
            if updated:
                logger.info(f"[Webhook] Successfully processed audio for {conversation_id}: {recording_url}")
                return {"status": "success", "call_id": conversation_id, "recording_url": recording_url}
            else:
                logger.warning(f"[Webhook] Audio saved but failed to update call record for {conversation_id}")
                return {"status": "partial", "message": "Audio saved but call record update failed"}
        else:
            logger.error(f"[Webhook] Failed to save audio for {conversation_id}")
            return {"status": "error", "message": "Failed to save audio"}
            
    except Exception as e:
        logger.error(f"[Webhook] Error processing audio webhook: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}

