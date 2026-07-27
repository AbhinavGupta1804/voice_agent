"""Webhook handlers for voice agent call completion."""
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Form
from fastapi.responses import JSONResponse, Response

from ..config import Config
from ..handlers.dashboard_ws import dashboard_manager
from .groq_proxy import generate_groq_response, ChatMessage
from ..models import (
    CallCompletePayload,
    CallRecordResponse,
    InsightModel,
    NotificationPreferences,
)
from ..services.call_record_service import CallRecordService
from ..services.follow_up_service import ScheduledFollowUpService
from ..services.conversation_service import ConversationService
from ..services.email_service import EmailService
from ..services.whatsapp_service import WhatsAppService
from ..services.whatsapp_booking_service import WhatsAppBookingService
from ..services.twilio_service import TwilioService
from ..services.ticket_service import TicketService
from ..utils.webhook_security import verify_retell_signature
from ..utils.phone_utils import normalize_phone_number

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


async def _process_retell_call_analyzed(call: dict) -> dict:
    """Transform Retell call_analyzed payload — same fields as legacy ElevenLabs webhook."""
    from ..services.post_call_processor import (
        apply_openai_analysis,
        build_transcript_from_retell,
        finalize_call_record,
        resolve_call_identity,
        retell_call_timestamp,
    )

    call_id = call.get("call_id")
    if not call_id:
        raise HTTPException(status_code=400, detail="Missing call_id")

    if await CallRecordService.is_call_analyzed_processed(call_id):
        logger.info("[Retell Webhook] Skipping duplicate call_analyzed for call_id=%s", call_id)
        return {"status": "already_processed", "call_id": call_id}

    transcript_text = build_transcript_from_retell(call)
    call_type, client_name, phone_number = await resolve_call_identity(
        call_id, call, transcript_text=transcript_text
    )

    call_analysis = call.get("call_analysis") or {}
    topics = []
    summary = call_analysis.get("call_summary")
    if summary:
        # Topic column is VARCHAR(255) — store a short label, full text goes in summary
        topics = [str(summary).strip()[:255]]

    custom_data = call_analysis.get("custom_analysis_data") or {}
    if isinstance(custom_data, dict):
        title = custom_data.get("call_summary_title") or custom_data.get("title")
        if title:
            topics = [str(title)]

    call_successful = call_analysis.get("call_successful")
    if isinstance(call_successful, bool):
        conversion_status = call_successful
    elif isinstance(call_successful, str):
        conversion_status = call_successful.lower() == "success"
    else:
        conversion_status = False

    duration_sec = int((call.get("duration_ms") or 0) / 1000)
    recording_url = call.get("recording_url") or call.get("scrubbed_recording_url")
    sentiment = call_analysis.get("user_sentiment")
    if isinstance(sentiment, str):
        sentiment = sentiment.lower()

    logger.info(
        "[Retell Webhook] call_id=%s type=%s client=%s phone=%s duration=%ss recording=%s",
        call_id,
        call_type,
        client_name,
        phone_number or "(none)",
        duration_sec,
        bool(recording_url),
    )

    payload = CallCompletePayload(
        call_id=call_id,
        client_name=client_name,
        transcript=transcript_text.strip(),
        insights=InsightModel(topics=topics, duration_sec=duration_sec),
        conversion_status=conversion_status,
        sentiment=sentiment,
        timestamp=retell_call_timestamp(call),
        recording_url=recording_url,
        call_type=call_type,
        phone_number=phone_number,
        summary=summary,
    )

    client_name = await apply_openai_analysis(
        payload,
        transcript_text=transcript_text,
        phone_number=phone_number,
        client_name=client_name,
        call_type=call_type,
    )
    payload.client_name = client_name

    return await finalize_call_record(payload, send_notifications=_send_post_call_notifications)


async def _handle_retell_call_started(call: dict) -> None:
    """Persist inbound caller metadata early so post-call processing has phone/name."""
    call_id = call.get("call_id")
    if not call_id:
        return

    metadata = call.get("metadata") or {}
    merged = {**metadata}
    for key in ("retell_llm_dynamic_variables", "collected_dynamic_variables"):
        block = call.get(key)
        if isinstance(block, dict):
            merged.update(block)

    from_number = (call.get("from_number") or merged.get("phone_number") or "").strip()
    client_name = (
        merged.get("client_name")
        or merged.get("customer_name")
        or "Unknown"
    )
    call_type = merged.get("call_type") or (
        "inbound" if (call.get("direction") or "").lower() == "inbound" else "outbound"
    )

    if from_number and _is_valid_phone_number(from_number):
        await CallRecordService.store_call_metadata(
            call_sid=call_id,
            client_name=client_name,
            phone_number=from_number,
            call_type=call_type,
        )
        await CallRecordService.link_conversation_to_call(call_id, call_id)
        logger.info(
            "[Retell Webhook] call_started stored metadata call_id=%s phone=%s",
            call_id,
            from_number,
        )


async def _handle_retell_call_ended(call: dict) -> None:
    """Handle call_ended — log disconnect reason; schedule follow-up on no-answer outbound."""
    call_id = call.get("call_id")
    disconnection_reason = (call.get("disconnection_reason") or "unknown").lower()
    duration_ms = call.get("duration_ms") or 0
    logger.info(
        "[Retell Webhook] call_ended call_id=%s reason=%s duration_ms=%s",
        call_id,
        disconnection_reason,
        duration_ms,
    )

    no_answer_reasons = {
        "dial_no_answer",
        "dial_busy",
        "dial_failed",
        "dial_rejected",
        "registered_call_timeout",
        "telephony_provider_permission_denied",
    }

    if disconnection_reason not in no_answer_reasons:
        return

    metadata = call.get("metadata") or {}
    phone_number = (
        await CallRecordService.get_phone_number_from_conversation(call_id)
        or metadata.get("phone_number")
        or call.get("to_number")
        or ""
    )
    client_name = (
        await CallRecordService.get_client_name_from_conversation(call_id)
        or metadata.get("client_name")
        or metadata.get("customer_name")
        or "Unknown"
    )

    if not call_id or not phone_number or not _is_valid_phone_number(phone_number):
        logger.warning("[Retell Webhook] call_ended no-answer but missing phone for call_id=%s", call_id)
        return

    delay_minutes = getattr(Config, "FOLLOW_UP_NO_ANSWER_DELAY_MINUTES", 15)
    scheduled_at = datetime.now(timezone.utc) + timedelta(minutes=delay_minutes)
    try:
        follow_up_id = await ScheduledFollowUpService.create_follow_up(
            call_id=call_id,
            phone_number=phone_number,
            client_name=client_name,
            scheduled_at=scheduled_at,
            context={
                "reason": "no_answer",
                "disconnection_reason": disconnection_reason,
                "original_attempt": "retell_call_ended",
                "summary": f"Follow-up: user did not pick up ({disconnection_reason})",
            },
        )
        if follow_up_id:
            logger.info("[Retell Webhook] Scheduled no-answer follow-up id=%s for %s", follow_up_id, call_id)
    except Exception as exc:
        logger.error("[Retell Webhook] Failed to schedule no-answer follow-up: %s", exc, exc_info=True)

    await dashboard_manager.broadcast(
        "call_failed",
        {
            "conversation_id": call_id,
            "failure_reason": disconnection_reason,
            "metadata": metadata,
        },
    )


def register_webhook_routes(app):
    """Register webhook routes."""
    router = APIRouter(tags=["Webhooks"])

    @router.post("/webhook/retell")
    @router.get("/webhook/retell")
    async def retell_webhook(request: Request):
        """
        Retell post-call webhook.

        Configure in Retell Dashboard → Agent → Webhook URL:
          POST {NGROK_URL}/webhook/retell

        Events:
          - call_started   → store caller metadata
          - call_ended     → no-answer follow-up scheduling
          - call_analyzed  → save call, notify, dashboard update
        """
        if request.method == "GET":
            return {"status": "ok", "service": "retell-webhook"}
        try:
            raw_body = await request.body()
            raw_text = raw_body.decode("utf-8")
            signature = request.headers.get("X-Retell-Signature") or request.headers.get("x-retell-signature")

            if Config.RETELL_WEBHOOK_VERIFY and Config.RETELL_API_KEY:
                if not signature:
                    raise HTTPException(
                        status_code=401,
                        detail="Missing X-Retell-Signature header",
                    )
                if not verify_retell_signature(raw_text, signature, Config.RETELL_API_KEY):
                    raise HTTPException(
                        status_code=401,
                        detail=(
                            "Invalid Retell webhook signature. "
                            "Use the API key that has the webhook badge in Retell Dashboard → API Keys, "
                            "and set it as RETELL_API_KEY in .env."
                        ),
                    )
            elif not Config.RETELL_WEBHOOK_VERIFY:
                logger.warning("[Retell Webhook] Signature verification disabled (RETELL_WEBHOOK_VERIFY=false)")

            data = json.loads(raw_text)
            event = data.get("event", "")
            call = data.get("call") or {}
            call_id = call.get("call_id")

            logger.info("[Retell Webhook] event=%s call_id=%s", event, call_id)

            if event == "call_started":
                await _handle_retell_call_started(call)
                return {"status": "acknowledged"}

            if event == "call_ended":
                await _handle_retell_call_ended(call)
                return {"status": "acknowledged"}

            if event == "call_analyzed":
                return await _process_retell_call_analyzed(call)

            return {"status": "ignored", "event": event}
        except HTTPException:
            raise
        except Exception as exc:
            logger.error("[Retell Webhook] error: %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail="Failed to process Retell webhook")

    @router.post("/webhook/whatsapp_response")
    async def whatsapp_response_webhook(
        request: Request,
        Body: str = Form(default=""),
        From: str = Form(default=""),
        To: str = Form(default=""),
        MessageSid: str = Form(default=None)  # Add MessageSid parameter
    ):
        """
        Single Twilio inbound WhatsApp webhook for the whole product.

        Configure Twilio "When a message comes in" to:
          POST https://<your-host>/webhook/whatsapp_response

        Order of handling:
          1. Active booking-email session (voice appointment → WhatsApp email) — PostgreSQL
          2. Otherwise: conversation thread + CONFIRM/RESCHEDULE keywords or Groq chat bot
        """
        try:
            raw_body = (Body or "").strip()
            # Normalize the phone number using our utility
            from_number = normalize_phone_number((From or "").replace("whatsapp:", "").strip())
            
            logger.info(
                "[WhatsApp Inbound] /webhook/whatsapp_response from=%s body_len=%d",
                from_number,
                len(raw_body),
            )

            if not from_number:
                logger.error("[DEBUG] Missing from_number")
                return Response(content="", media_type="application/xml")

            # 1) Booking email (appointment flow) — before general chat
            try:
                booking_result = await WhatsAppBookingService.handle_inbound_email_reply(
                    from_phone=from_number,
                    message_body=raw_body,
                )
                if booking_result.get("handled"):
                    reply = booking_result.get("reply_message", "")
                    if reply:
                        await WhatsAppService.send_simple_message(from_number, reply)
                    logger.info(
                        "[WhatsApp] booking email handled call_id=%s success=%s",
                        booking_result.get("call_id"),
                        booking_result.get("success"),
                    )
                    return Response(content="", media_type="application/xml")
            except Exception as booking_exc:
                logger.error(
                    "[WhatsApp] booking email handler error: %s",
                    booking_exc,
                    exc_info=True,
                )

            # 2) General WhatsApp chat (dashboard thread + Groq)
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
                        twilio_message_sid=MessageSid,  # Pass the captured MessageSid
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
                    
                    # Fetch last call summary for context (Using ConversationService)
                    last_call_context = ""
                    try:
                        last_call = await ConversationService.get_latest_call_context(from_number)
                        if last_call:
                            last_call_context = (
                                f"\n\nRecent Interaction Context:\n"
                                f"- Client Name: {last_call.get('client_name')}\n"
                                f"- Last Call Summary: {last_call.get('summary')}\n"
                                f"Use this context if relevant, but don't force it."
                            )
                            logger.info(f"[WhatsApp] Found last call context for {from_number}")
                    except Exception as e:
                        logger.warning(f"[WhatsApp] Failed to get call context: {e}")

                    # Add Text-Channel Specific System Prompt with Context
                    history.append(ChatMessage(role="system", content=f"""
                    You are Neha, a helpful customer support agent for Naturals Ice Cream.
                    Reply to the customer's text message in a friendly, concise, and professional manner.
                    Do not mention being an AI or voice agent. Keep answers under 3 sentences.
                    If you don't know something, offer to have a human agent call them back.
                    {last_call_context}
                    """))
                    
                    if thread_id:
                        # Get last 15 messages (Chronological: Oldest -> Newest) using get_recent_messages
                        # This ensures we see the ACTUAL latest conversation, not just the first 10 ever.
                        raw_msgs = await ConversationService.get_recent_messages(thread_id, limit=15)
                        for m in raw_msgs:
                            role = "assistant" if m["sender_type"] in ("bot", "agent") else "user"
                            history.append(ChatMessage(role=role, content=m["body"]))
                    
                    # 2. Add current message
                    history.append(ChatMessage(role="user", content=raw_body))
                    
                    # 3. Generate Response
                    ai_result = await generate_groq_response(
                        messages=history,
                        temperature=0.7,
                        max_tokens=200
                    )
                    
                    # Extract content from the message object
                    if isinstance(ai_result, dict):
                        response_message = ai_result.get("content") or ""
                    else:
                        response_message = str(ai_result)

                    # Fallback if empty
                    if not (response_message and response_message.strip()):
                         response_message = "I received your message but couldn't generate a response. Please try again."

                except Exception as e:
                    logger.error(f"[AI] Failed to generate response: {e}")
                    response_message = "Thanks for your message. We'll get back to you shortly."

            logger.info(f"[DEBUG] Sending Reply: {response_message}")
            result = await WhatsAppService.send_simple_message(from_number, response_message)
            message_sid = result.get("message_sid") if isinstance(result, dict) else None

            # Always store bot reply in conversation so it shows on website (even if Twilio didn't return sid)
            if thread_id:
                await ConversationService.add_message(
                    thread_id=thread_id,
                    body=response_message,
                    direction="outbound",
                    sender_type="bot",
                    twilio_message_sid=message_sid,
                )
                logger.info(f"[DEBUG] Outbound Reply Saved: sid={message_sid}")

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
        To: str = Form(default=""),
        MessageSid: str = Form(default=None)  # Add MessageSid parameter
    ):
        """
        Handle incoming SMS: store in conversation thread, then send bot ack via SMS.
        Configure this URL in Twilio Console for your phone number's "A MESSAGE COMES IN" webhook.
        """
        try:
            raw_body = (Body or "").strip()
            from_number = normalize_phone_number((From or "").strip())
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
                    twilio_message_sid=MessageSid,  # Pass the captured MessageSid
                )
                await dashboard_manager.broadcast("conversation_message", {"thread_id": thread_id, "channel": "sms"})

            # Generate AI Response using Groq (same logic as WhatsApp)
            response_message = "Thanks for your message. We'll get back to you shortly."
            try:
                # 1. Fetch recent history for context
                history = []
                
                # Fetch last call summary for context (SMS channel)
                last_call_context = ""
                try:
                    last_call = await ConversationService.get_latest_call_context(from_number)
                    if last_call:
                        last_call_context = (
                            f"\n\nRecent Interaction Context:\n"
                            f"- Client Name: {last_call.get('client_name')}\n"
                            f"- Last Call Summary: {last_call.get('summary')}\n"
                        )
                except Exception:
                    pass

                # Add Text-Channel Specific System Prompt
                history.append(ChatMessage(role="system", content=f"""
                You are Neha, a helpful customer support agent for Naturals Ice Cream.
                Reply to the customer's SMS in a friendly, concise, and professional manner.
                Keep answers very short (under 160 chars if possible).
                {last_call_context}
                """))
                
                if thread_id:
                    # Get last 15 messages (Chronological)
                    raw_msgs = await ConversationService.get_recent_messages(thread_id, limit=15)
                    for m in raw_msgs:
                        role = "assistant" if m["sender_type"] in ("bot", "agent") else "user"
                        history.append(ChatMessage(role=role, content=m["body"]))
                
                # 2. Add current message
                history.append(ChatMessage(role="user", content=raw_body))
                
                # 3. Generate Response
                ai_result = await generate_groq_response(
                    messages=history,
                    temperature=0.7,
                    max_tokens=150  # Keep SMS shorter
                )
                
                # Extract content from the message object
                ai_response_text = ""
                if isinstance(ai_result, dict):
                    ai_response_text = ai_result.get("content") or ""
                else:
                    ai_response_text = str(ai_result)
                
                if ai_response_text and ai_response_text.strip():
                     response_message = ai_response_text.strip()

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


def _build_post_call_summary_body(client_name: str, summary: str, follow_up_date: Optional[str] = None) -> str:
    """Short post-call summary for WhatsApp, SMS, and conversation thread."""
    name = (client_name or "there").strip()
    text = (summary or "No summary available.").strip()
    body = (
        f"Hello {name}! Thank you for your recent call. Here's a summary of our conversation:\n"
        f"{text}"
    )
    if follow_up_date:
        body += f"\n\nScheduled follow-up: {follow_up_date}"
    return body


async def _send_post_call_notifications(payload: CallCompletePayload, record: dict) -> None:
    """
    Send brochure + summary after every call via WhatsApp and/or email when contact info is available,
    and record each sent message in the conversation thread for the Chats page.
    """
    if not await CallRecordService.try_acquire_post_call_notification_lock(payload.call_id):
        logger.info(
            "[PostCallNotifications] Skipping duplicate dispatch for call_id=%s",
            payload.call_id,
        )
        return

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

    # Use summary from payload; fallback to record (DB) so SMS and conversation always show the same text
    summary_text = (payload.summary or (record.get("summary") if record else None) or "").strip() or "No summary available."
    summary_body_for_conversation = _build_post_call_summary_body(
        payload.client_name, summary_text, payload.follow_up_date
    )

    # ----- WhatsApp: send brochure + summary after every call when we have a number -----
    whatsapp_number = await _get_phone_number_fallback()
    if whatsapp_number:
        try:
            # Check for recent support ticket (created in last 10 mins)
            latest_ticket_id = None
            latest_issue = None
            
            try:
                tickets = await TicketService.get_ticket_status(whatsapp_number)
                if tickets:
                    latest = tickets[0]
                    # Check if created recently (e.g. within last 10 mins)
                    # Ensure timezone awareness (created_at from DB is usually naive or UTC)
                    now_utc = datetime.now(timezone.utc)
                    
                    # Convert ticket time to aware UTC if it's naive
                    ticket_time = latest.created_at
                    if ticket_time.tzinfo is None:
                        ticket_time = ticket_time.replace(tzinfo=timezone.utc)
                        
                    time_diff = now_utc - ticket_time
                    if time_diff.total_seconds() < 600:  # 10 minutes
                        latest_ticket_id = latest.ticket_id
                        latest_issue = latest.issue_description
                        logger.info(f"[PostCallNotifications] Found recent ticket #{latest.ticket_id}")
            except Exception as e:
                logger.warning(f"[PostCallNotifications] Failed to check tickets: {e}")

            whatsapp_result = await WhatsAppService.send_call_summary_whatsapp(
                to_number=whatsapp_number,
                client_name=payload.client_name,
                summary=summary_text,
                follow_up_date=payload.follow_up_date,
                call_id=payload.call_id,
                ticket_id=latest_ticket_id,
                issue=latest_issue,
                summary_body_for_conversation=summary_body_for_conversation,
            )
            if whatsapp_result is None:
                whatsapp_result = {"success": False, "error": "No response from WhatsApp service"}
            if whatsapp_result.get("success"):
                # Only record if a message was actually sent (not skipped)
                sent_body = whatsapp_result.get("message_body")
                
                if sent_body:
                    logger.info(f"[PostCallNotifications] WhatsApp sent to {whatsapp_number}")
                    prefs.whatsapp_sent = True
                    if whatsapp_number != (prefs.whatsapp_number or ""):
                        prefs.whatsapp_number = whatsapp_number
                        
                    # Record in conversation so it shows on Chats page
                    try:
                        thread = await ConversationService.get_or_create_thread(whatsapp_number, "whatsapp")
                        if thread.get("id"):
                            await ConversationService.add_message(
                                thread_id=thread["id"],
                                body=sent_body,  # Use the actual message body returned by the service
                                direction="outbound",
                                sender_type="bot",
                                twilio_message_sid=whatsapp_result.get("message_sid"),
                            )
                            await dashboard_manager.broadcast("conversation_message", {"thread_id": thread["id"], "channel": "whatsapp"})
                    except Exception as rec:
                        logger.warning(f"[PostCallNotifications] Failed to record WhatsApp in conversation: {rec}")
                else:
                    logger.info(f"[PostCallNotifications] WhatsApp skipped (no message body), not recording in DB.")
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
            sms_body = _build_post_call_summary_body(
                payload.client_name, summary_text, payload.follow_up_date
            )
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
    else:
        await CallRecordService.release_post_call_notification_lock(payload.call_id)
