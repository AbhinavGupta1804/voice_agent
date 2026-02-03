"""APScheduler service for executing scheduled follow-up calls."""
import logging
from datetime import datetime, timezone
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from .follow_up_service import ScheduledFollowUpService
from .twilio_service import TwilioService
from ..config import Config

logger = logging.getLogger(__name__)

# Global scheduler instance
_scheduler: Optional[AsyncIOScheduler] = None


async def execute_follow_up(follow_up: dict) -> bool:
    """
    Execute a single follow-up call.
    
    Args:
        follow_up: Dict with id, call_id, phone_number, client_name, context
        
    Returns:
        True if successful, False otherwise
    """
    follow_up_id = follow_up["id"]
    phone_number = follow_up["phone_number"]
    client_name = follow_up["client_name"]
    
    # Parse context from JSON string to dict
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
    
    logger.info(f"[Scheduler] Executing follow-up id={follow_up_id} for {client_name} at {phone_number}")
    
    # Update status to processing
    await ScheduledFollowUpService.update_status(follow_up_id, "processing")
    
    try:
        # Initialize Twilio service and make the call
        twilio_service = TwilioService()
        
        # Build TwiML URL with follow-up context
        base_url = Config.NGROK_URL
        if not base_url:
            raise ValueError("NGROK_URL not configured")
        
        from urllib.parse import urlencode
        params = {
            "client_name": client_name,
            "phone_number": phone_number,
            "is_follow_up": "true",
            "original_summary": context.get("summary", "")[:200]
        }
        # Pass LLM-generated first message for follow-up so the agent continues from the previous call
        first_message = follow_up.get("follow_up_first_message") or ""
        if first_message:
            params["follow_up_first_message"] = first_message[:500]
        twiml_url = f"{base_url}/outbound-call-twiml?{urlencode(params)}"
        status_callback_url = f"{base_url}/webhook/twilio-call-status?follow_up_id={follow_up_id}"

        # Initiate the follow-up call; completion is set by Twilio StatusCallback when call ends
        call_info = await twilio_service.initiate_call(
            to_number=phone_number,
            twiml_url=twiml_url,
            status_callback=status_callback_url,
        )

        logger.info(f"[Scheduler] Follow-up call initiated, call_sid={call_info['call_sid']}; status will be set when call ends")
        return True
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"[Scheduler] Follow-up call failed for id={follow_up_id}: {error_msg}")
        
        # Check if we should retry
        retry_count = follow_up.get("retry_count", 0)
        if retry_count < 3:
            # Schedule retry in 15 minutes
            await ScheduledFollowUpService.update_status(follow_up_id, "failed", error_msg)
            await ScheduledFollowUpService.retry_failed_follow_up(follow_up_id, retry_delay_minutes=15)
            logger.info(f"[Scheduler] Scheduled retry for follow-up id={follow_up_id}")
        else:
            # Max retries reached
            await ScheduledFollowUpService.update_status(follow_up_id, "failed", f"Max retries reached. Last error: {error_msg}")
            logger.error(f"[Scheduler] Max retries reached for follow-up id={follow_up_id}")
        
        return False


async def check_and_execute_due_follow_ups():
    """
    Check for due follow-ups and execute them.
    This function is called by APScheduler every minute.
    """
    logger.debug("[Scheduler] Checking for due follow-ups...")
    
    try:
        # Get all pending follow-ups that are due
        due_follow_ups = await ScheduledFollowUpService.get_due_follow_ups(limit=10)
        
        if not due_follow_ups:
            logger.debug("[Scheduler] No due follow-ups found")
            return
        
        logger.info(f"[Scheduler] Found {len(due_follow_ups)} due follow-ups")
        
        # Execute each follow-up
        for follow_up in due_follow_ups:
            await execute_follow_up(follow_up)
            
    except Exception as e:
        logger.error(f"[Scheduler] Error checking due follow-ups: {e}", exc_info=True)


def get_scheduler() -> Optional[AsyncIOScheduler]:
    """Get the global scheduler instance."""
    return _scheduler


async def start_scheduler():
    """Initialize and start the APScheduler."""
    global _scheduler
    
    if _scheduler is not None:
        logger.warning("[Scheduler] Scheduler already running")
        return
    
    _scheduler = AsyncIOScheduler()
    
    # Add job to check for due follow-ups every 2 minutes
    _scheduler.add_job(
        check_and_execute_due_follow_ups,
        trigger=IntervalTrigger(minutes=20),
        id="check_follow_ups",
        name="Check and execute due follow-up calls",
        replace_existing=True
    )
    
    _scheduler.start()
    logger.info("[Scheduler] APScheduler started - checking for follow-ups every 2 minutes")


async def stop_scheduler():
    """Stop the APScheduler."""
    global _scheduler
    
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("[Scheduler] APScheduler stopped")
