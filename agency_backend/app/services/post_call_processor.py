"""Shared post-call processing for Retell and legacy ElevenLabs webhooks."""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional, Tuple

from ..handlers.dashboard_ws import dashboard_manager
from ..models import CallCompletePayload, CallRecordResponse, NotificationPreferences
from ..services.call_record_service import CallRecordService
from ..services.follow_up_service import ScheduledFollowUpService
from ..services.openai_service import OpenAIService

logger = logging.getLogger(__name__)


def is_valid_phone_number(phone: str) -> bool:
    """Validate E.164-ish phone numbers and reject transcript garbage."""
    if not phone or not isinstance(phone, str):
        return False
    cleaned = phone.replace("whatsapp:", "").replace("+", "").strip()
    if not cleaned or not cleaned.isdigit() or len(cleaned) < 10:
        return False
    invalid_patterns = [
        "exactly", "this", "number", "same", "called", "call",
        "current", "present", "that", "which", "you",
    ]
    phone_lower = phone.lower()
    return not any(pattern in phone_lower for pattern in invalid_patterns)


def build_transcript_from_retell(call: dict) -> str:
    """Build transcript text from Retell call object (string or utterance list)."""
    transcript = (call.get("transcript") or "").strip()
    if transcript:
        return transcript

    lines = []
    for turn in call.get("transcript_object") or []:
        if not isinstance(turn, dict):
            continue
        role = (turn.get("role") or "unknown").capitalize()
        content = (turn.get("content") or turn.get("message") or "").strip()
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)


def merge_retell_variables(call: dict) -> dict:
    """Merge metadata + dynamic variables from a Retell call object."""
    merged = {}
    for key in ("metadata", "retell_llm_dynamic_variables", "collected_dynamic_variables"):
        block = call.get(key)
        if isinstance(block, dict):
            merged.update(block)
    return merged


def retell_call_timestamp(call: dict) -> datetime:
    """Use Retell start_timestamp when available."""
    start_ms = call.get("start_timestamp")
    if start_ms:
        try:
            return datetime.fromtimestamp(int(start_ms) / 1000, tz=timezone.utc)
        except (TypeError, ValueError, OSError):
            pass
    end_ms = call.get("end_timestamp")
    if end_ms:
        try:
            return datetime.fromtimestamp(int(end_ms) / 1000, tz=timezone.utc)
        except (TypeError, ValueError, OSError):
            pass
    return datetime.now(timezone.utc)


async def resolve_call_identity(
    call_id: str,
    call: dict,
    *,
    direction: str = "",
    transcript_text: str = "",
) -> Tuple[str, str, str]:
    """
    Resolve call_type, client_name, phone_number using the same fallback chain
    as the legacy ElevenLabs webhook.
    """
    merged = merge_retell_variables(call)
    direction = (direction or call.get("direction") or "").lower()

    call_type = await CallRecordService.get_call_type_from_conversation(call_id)
    client_name = await CallRecordService.get_client_name_from_conversation(call_id) or "Unknown"
    phone_number = await CallRecordService.get_phone_number_from_conversation(call_id) or ""

    if not call_type:
        call_type = merged.get("call_type") or ("inbound" if direction == "inbound" else "outbound")

    if client_name == "Unknown":
        client_name = (
            merged.get("client_name")
            or merged.get("customer_name")
            or "Unknown"
        )

    if not phone_number:
        phone_number = merged.get("phone_number") or ""
    if not phone_number:
        phone_number = call.get("from_number") if call_type == "inbound" else call.get("to_number")
    phone_number = phone_number or ""

    if not call_type:
        if client_name == "Customer":
            call_type = "inbound"
        elif client_name != "Unknown":
            call_type = "outbound"

    if not call_type and transcript_text.strip():
        detected = OpenAIService.detect_call_type_from_transcript(transcript_text.strip())
        if detected:
            call_type = detected
            logger.info("[PostCall] Detected call_type=%s from transcript", detected)

    return call_type or "outbound", client_name, phone_number


async def apply_openai_analysis(
    payload: CallCompletePayload,
    *,
    transcript_text: str,
    phone_number: str,
    client_name: str,
    call_type: str,
) -> str:
    """Run OpenAI structured analysis and mutate payload (same as ElevenLabs path)."""
    if not transcript_text.strip():
        return client_name

    if not call_type and transcript_text.strip():
        detected = OpenAIService.detect_call_type_from_transcript(transcript_text.strip())
        if detected:
            call_type = detected
            payload.call_type = detected

    try:
        ai_result = await OpenAIService.analyze_call_structured(
            transcript_text.strip(),
            phone_number or None,
        )

        payload.summary = ai_result.get("summary") or payload.summary
        payload.conversion_status = ai_result.get("conversion_status", payload.conversion_status)
        payload.sentiment = ai_result.get("sentiment", payload.sentiment or "neutral")
        payload.phone_number = phone_number

        extracted_user_name = ai_result.get("user_name")
        if extracted_user_name and call_type == "inbound" and client_name in ["Customer", "Unknown"]:
            client_name = extracted_user_name
            payload.client_name = extracted_user_name
            logger.info("[PostCall] Extracted inbound user name: %s", extracted_user_name)

        extracted_whatsapp = ai_result.get("whatsapp_number")
        if extracted_whatsapp and not is_valid_phone_number(extracted_whatsapp):
            logger.warning(
                "[PostCall] Invalid WhatsApp number '%s', using call phone %s",
                extracted_whatsapp,
                phone_number,
            )
            extracted_whatsapp = phone_number

        payload.notification_preferences = NotificationPreferences(
            notify_email=ai_result.get("notify_email", False),
            notify_whatsapp=ai_result.get("notify_whatsapp", False),
            email_address=ai_result.get("email_address"),
            whatsapp_number=extracted_whatsapp,
        )

        if ai_result.get("follow_up_datetime"):
            try:
                follow_up_dt = datetime.fromisoformat(
                    ai_result["follow_up_datetime"].replace("Z", "+00:00")
                )
                payload.follow_up_date = follow_up_dt.date().isoformat()
            except Exception:
                payload.follow_up_date = None

        if ai_result.get("follow_up_required") and ai_result.get("follow_up_datetime"):
            try:
                follow_up_dt = datetime.fromisoformat(
                    ai_result["follow_up_datetime"].replace("Z", "+00:00")
                )
                await ScheduledFollowUpService.create_follow_up(
                    call_id=payload.call_id,
                    phone_number=phone_number,
                    client_name=client_name,
                    scheduled_at=follow_up_dt,
                    context={
                        "summary": payload.summary,
                        "original_call_date": datetime.now(timezone.utc).isoformat(),
                        "call_type": call_type,
                    },
                    follow_up_first_message=ai_result.get("follow_up_first_message"),
                )
                logger.info("[PostCall] Scheduled follow-up at %s", follow_up_dt)
            except Exception as exc:
                logger.error("[PostCall] Failed to schedule follow-up: %s", exc)

        logger.info(
            "[PostCall] OpenAI analysis conversion=%s sentiment=%s notify_email=%s notify_whatsapp=%s",
            payload.conversion_status,
            payload.sentiment,
            payload.notification_preferences.notify_email,
            payload.notification_preferences.notify_whatsapp,
        )
    except Exception as exc:
        logger.warning("[PostCall] OpenAI analysis failed: %s", exc)

    return client_name


async def finalize_call_record(
    payload: CallCompletePayload,
    *,
    send_notifications,
) -> dict:
    """Upsert DB, broadcast dashboard, dispatch notifications in background."""
    logger.info("[PostCall] Upserting call_id=%s", payload.call_id)
    record = await CallRecordService.upsert_call_record(payload)
    response_model = CallRecordResponse(**record)

    # Respond to Retell quickly — slow Twilio sends run in background
    async def _dispatch_notifications():
        try:
            await send_notifications(payload, record)
        except Exception as exc:
            logger.error(
                "[PostCall] Background notifications failed for call_id=%s: %s",
                payload.call_id,
                exc,
                exc_info=True,
            )

    asyncio.create_task(_dispatch_notifications())

    await CallRecordService.cleanup_call_metadata(payload.call_id)
    await dashboard_manager.broadcast("call_completed", response_model.model_dump(mode="json"))
    return {"status": "success", "call_id": response_model.call_id}
