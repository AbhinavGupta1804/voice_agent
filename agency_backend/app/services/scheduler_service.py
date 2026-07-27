"""APScheduler service for executing scheduled follow-up calls."""
import logging
from datetime import datetime, timezone
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from .follow_up_service import ScheduledFollowUpService
from .retell_service import RetellService
from .call_record_service import CallRecordService
from ..config import Config

logger = logging.getLogger(__name__)

_scheduler: Optional[AsyncIOScheduler] = None


async def execute_follow_up(follow_up: dict) -> bool:
    """Execute a single follow-up call via Retell."""
    follow_up_id = follow_up["id"]
    phone_number = follow_up["phone_number"]
    client_name = follow_up["client_name"]

    import json
    context_raw = follow_up.get("context")
    if isinstance(context_raw, str):
        try:
            context = json.loads(context_raw)
        except json.JSONDecodeError:
            context = {}
    elif isinstance(context_raw, dict):
        context = context_raw
    else:
        context = {}

    logger.info("[Scheduler] Executing follow-up id=%s for %s at %s", follow_up_id, client_name, phone_number)
    await ScheduledFollowUpService.update_status(follow_up_id, "processing")

    try:
        first_message = follow_up.get("follow_up_first_message") or ""
        status_callback_url = None
        if Config.NGROK_URL:
            status_callback_url = f"{Config.NGROK_URL}/webhook/twilio-call-status?follow_up_id={follow_up_id}"

        call_info = await RetellService.initiate_outbound_call(
            to_number=phone_number,
            client_name=client_name,
            follow_up_first_message=first_message,
            status_callback_url=status_callback_url,
        )

        call_id = call_info.get("call_id")
        if call_id:
            await CallRecordService.store_call_metadata(
                call_sid=call_id,
                client_name=client_name,
                phone_number=phone_number,
                call_type="outbound",
            )
            await CallRecordService.link_conversation_to_call(call_id, call_id)

        logger.info(
            "[Scheduler] Follow-up call initiated call_id=%s; status via Twilio callback when SIP mode",
            call_id,
        )
        return True

    except Exception as e:
        error_msg = str(e)
        logger.error("[Scheduler] Follow-up call failed id=%s: %s", follow_up_id, error_msg)

        retry_count = follow_up.get("retry_count", 0)
        if retry_count < 3:
            await ScheduledFollowUpService.update_status(follow_up_id, "failed", error_msg)
            await ScheduledFollowUpService.retry_failed_follow_up(follow_up_id, retry_delay_minutes=15)
            logger.info("[Scheduler] Scheduled retry for follow-up id=%s", follow_up_id)
        else:
            await ScheduledFollowUpService.update_status(
                follow_up_id,
                "failed",
                f"Max retries reached. Last error: {error_msg}",
            )
            logger.error("[Scheduler] Max retries reached for follow-up id=%s", follow_up_id)

        return False


async def check_and_execute_due_follow_ups():
    """Check for due follow-ups and execute them."""
    if not Config.FOLLOW_UP_CALLS_ENABLED:
        logger.debug("[Scheduler] Follow-up calls disabled (FOLLOW_UP_CALLS_ENABLED=false)")
        return
    logger.debug("[Scheduler] Checking for due follow-ups...")
    try:
        due_follow_ups = await ScheduledFollowUpService.get_due_follow_ups(limit=10)
        if not due_follow_ups:
            logger.debug("[Scheduler] No due follow-ups found")
            return
        logger.info("[Scheduler] Found %s due follow-ups", len(due_follow_ups))
        for follow_up in due_follow_ups:
            await execute_follow_up(follow_up)
    except Exception as e:
        logger.error("[Scheduler] Error checking due follow-ups: %s", e, exc_info=True)


def get_scheduler() -> Optional[AsyncIOScheduler]:
    return _scheduler


async def start_scheduler():
    global _scheduler
    if _scheduler is not None:
        logger.warning("[Scheduler] Scheduler already running")
        return
    if not Config.FOLLOW_UP_CALLS_ENABLED:
        logger.info("[Scheduler] Follow-up job not started (FOLLOW_UP_CALLS_ENABLED=false)")
        return
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        check_and_execute_due_follow_ups,
        trigger=IntervalTrigger(minutes=20),
        id="check_follow_ups",
        name="Check and execute due follow-up calls",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info("[Scheduler] APScheduler started")


async def stop_scheduler():
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("[Scheduler] APScheduler stopped")
