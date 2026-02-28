"""
get_available_slots tool — Standalone tool for Custom LLM voice calls.
======================================================================
Calls the Cal.com API to retrieve available appointment slots for a
given date. Used when a customer wants to book an appointment with a
manager or support representative.

Interface:
    TOOL_DEFINITION  — dict describing the tool (name, description, params)
    validate(args)   — validates & cleans arguments, returns clean dict
    execute(args)    — fetches slots from Cal.com API, returns result dict
"""
import logging
import os
from datetime import datetime, timedelta
from typing import Dict, Any

import httpx

from ..config import Config

logger = logging.getLogger(__name__)

# =====================================================================
# Cal.com Configuration - use Config class for lazy loading
# =====================================================================


# =====================================================================
# TOOL DEFINITION (used by dispatcher to build system prompt)
# =====================================================================

TOOL_DEFINITION = {
    "name": "get_available_slots",
    "description": (
        "Get available appointment slots for booking. Use when customer wants to "
        "book an appointment or meeting with a manager or support representative. "
        "Returns available time slots for the requested date."
    ),
    "parameters": {
        "start": {
            "type": "string",
            "required": True,
            "description": (
                "The date on which user wants to book an appointment, "
                "in 'YYYY-MM-DD' format (e.g. '2026-03-01')."
            ),
        },
        "end": {
            "type": "string",
            "required": False,
            "description": (
                "The next day after the appointment date, in 'YYYY-MM-DD' format. "
                "If not provided, it will be auto-calculated as start + 1 day."
            ),
        },
    },
}


# =====================================================================
# VALIDATE
# =====================================================================

def validate(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate & clean tool arguments.
    Returns clean dict with start and end dates.
    Raises ValueError if required fields are missing or invalid.
    """
    start = (args.get("start") or "").strip()
    if not start:
        raise ValueError("start date is required. Ask the customer which date they want the appointment.")

    # Validate date format
    try:
        start_date = datetime.strptime(start, "%Y-%m-%d")
    except ValueError:
        raise ValueError(f"Invalid start date format '{start}'. Must be YYYY-MM-DD.")

    # Auto-calculate end if not provided
    end = (args.get("end") or "").strip()
    if not end:
        end_date = start_date + timedelta(days=1)
        end = end_date.strftime("%Y-%m-%d")
    else:
        try:
            datetime.strptime(end, "%Y-%m-%d")
        except ValueError:
            raise ValueError(f"Invalid end date format '{end}'. Must be YYYY-MM-DD.")

    return {"start": start, "end": end}


# =====================================================================
# EXECUTE
# =====================================================================

async def execute(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute get_available_slots: validates args, calls Cal.com API.

    Returns:
        {
            "success": True/False,
            "message": "slot info or error",
            "slots": ["10:00", "11:00", ...]  (if success)
        }
    """
    import time as _time
    t_start = _time.time()
    
    logger.info(f"[get_available_slots] ========================================")
    logger.info(f"[get_available_slots] === EXECUTE START ===")
    logger.info(f"[get_available_slots] Raw args: {args}")
    logger.info(f"[get_available_slots] Config: API_VERSION={Config.CAL_API_VERSION}, EVENT_TYPE_ID={Config.CAL_EVENT_TYPE_ID}")
    logger.info(f"[get_available_slots] API Key configured: {bool(Config.CAL_API_KEY)}")

    # Step 1: Validate
    logger.info(f"[get_available_slots] [Step 1/3] Validating arguments...")
    try:
        clean_args = validate(args)
        logger.info(f"[get_available_slots] [Step 1/3] PASS: start={clean_args['start']}, end={clean_args['end']}")
    except ValueError as e:
        logger.warning(f"[get_available_slots] [Step 1/3] FAIL: {e}")
        return {"success": False, "message": str(e)}

    # Step 2: Check API key
    logger.info(f"[get_available_slots] [Step 2/3] Checking API configuration...")
    if not Config.CAL_API_KEY:
        logger.error("[get_available_slots] [Step 2/3] FAIL: CAL_API_KEY not configured")
        return {
            "success": False,
            "message": "Appointment system abhi configured nahi hai. Please baad mein try karein.",
        }
    logger.info(f"[get_available_slots] [Step 2/3] PASS: API key present")

    # Step 3: Call Cal.com API
    logger.info(f"[get_available_slots] [Step 3/3] Calling Cal.com API...")
    try:
        url = "https://api.cal.com/v2/slots"
        params = {
            "eventTypeId": Config.CAL_EVENT_TYPE_ID,
            "start": clean_args["start"],
            "end": clean_args["end"],
        }
        headers = {
            "Authorization": f"Bearer {Config.CAL_API_KEY}",
            "cal-api-version": Config.CAL_API_VERSION,
        }

        logger.info(f"[get_available_slots] Request URL: GET {url}")
        logger.info(f"[get_available_slots] Request params: {params}")
        logger.info(f"[get_available_slots] Request headers: cal-api-version={Config.CAL_API_VERSION}")

        t_api = _time.time()
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(url, params=params, headers=headers)
        api_time = (_time.time() - t_api) * 1000

        logger.info(f"[get_available_slots] Response status: {response.status_code} ({api_time:.0f}ms)")
        logger.info(f"[get_available_slots] Response body: {response.text[:800]}")

        if response.status_code != 200:
            logger.error(f"[get_available_slots] [Step 3/3] FAIL: API returned {response.status_code}")
            logger.error(f"[get_available_slots] Error response: {response.text[:500]}")
            return {
                "success": False,
                "message": "Slots check karne mein problem ho gayi. Please thodi der baad try karein.",
            }

        data = response.json()
        logger.info(f"[get_available_slots] [Step 3/3] PASS: API call successful")

        # Parse slots from response
        slots_data = data.get("data", {})
        logger.info(f"[get_available_slots] Parsing slots from data keys: {list(slots_data.keys())}")

        all_slots = []
        for date_key, slot_list in slots_data.items():
            logger.info(f"[get_available_slots] Date {date_key}: {len(slot_list)} raw slots")
            for i, slot in enumerate(slot_list):
                slot_time = slot.get("start") or slot.get("time", "")
                logger.debug(f"[get_available_slots] Slot[{i}]: raw={slot}, extracted_time={slot_time}")
                if slot_time:
                    try:
                        dt = datetime.fromisoformat(slot_time.replace("Z", "+00:00"))
                        readable = dt.strftime("%I:%M %p")
                        all_slots.append({
                            "readable": readable,
                            "iso": slot_time,
                        })
                    except (ValueError, TypeError) as e:
                        logger.warning(f"[get_available_slots] Failed to parse slot time '{slot_time}': {e}")
                        all_slots.append({
                            "readable": slot_time,
                            "iso": slot_time,
                        })

        total_time = (_time.time() - t_start) * 1000
        
        if not all_slots:
            logger.info(f"[get_available_slots] Result: No slots available")
            logger.info(f"[get_available_slots] === EXECUTE END ({total_time:.0f}ms) ===")
            return {
                "success": True,
                "message": f"{clean_args['start']} ko koi slot available nahi hai. Koi aur date try karein.",
                "slots": [],
            }

        # Build response
        slots_text_parts = [f"{s['readable']} (ISO: {s['iso']})" for s in all_slots]
        slots_text = ", ".join(slots_text_parts)
        readable_only = ", ".join([s["readable"] for s in all_slots])
        
        logger.info(f"[get_available_slots] Result: {len(all_slots)} slots found")
        logger.info(f"[get_available_slots] Slots readable: {readable_only}")
        logger.info(f"[get_available_slots] === EXECUTE END ({total_time:.0f}ms) SUCCESS ===")

        return {
            "success": True,
            "message": f"{clean_args['start']} ke liye available slots: {slots_text}. Jab book_slot call karein, ISO timestamp use karein.",
            "slots": all_slots,
            "slots_readable": readable_only,
        }

    except httpx.TimeoutException:
        total_time = (_time.time() - t_start) * 1000
        logger.error(f"[get_available_slots] API request timed out after {total_time:.0f}ms")
        return {
            "success": False,
            "message": "Appointment system se response nahi aaya. Please dobara try karein.",
        }
    except Exception as e:
        total_time = (_time.time() - t_start) * 1000
        logger.error(f"[get_available_slots] Execution ERROR after {total_time:.0f}ms: {type(e).__name__}: {e}", exc_info=True)
        return {
            "success": False,
            "message": "Slots check karne mein kuch problem ho gayi. Please baad mein try karein.",
        }
