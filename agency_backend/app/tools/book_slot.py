"""
book_slot tool — Standalone tool for Custom LLM voice calls.
=============================================================
Calls the Cal.com API to book an appointment slot for a customer.
Used after customer has selected an available slot from get_available_slots.

Interface:
    TOOL_DEFINITION  — dict describing the tool (name, description, params)
    validate(args)   — validates & cleans arguments, returns clean dict
    execute(args)    — books slot via Cal.com API, returns result dict
"""
import logging
import os
from datetime import datetime
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
    "name": "book_slot",
    "description": (
        "Book an appointment slot for the customer. Use ONLY after customer has "
        "selected an exact available time from get_available_slots results. "
        "Before calling: confirm customer's name, email, and selected time. "
        "After success: share the meeting URL with the customer."
    ),
    "parameters": {
        "start": {
            "type": "string",
            "required": True,
            "description": (
                "The exact slot start time selected by user in ISO 8601 UTC format. "
                "Must match a slot from get_available_slots. Example: '2026-03-01T10:00:00.000Z'"
            ),
        },
        "name": {
            "type": "string",
            "required": True,
            "description": "Full name of the person booking the meeting (MUST ask if not provided).",
        },
        "email": {
            "type": "string",
            "required": True,
            "description": "Email address for booking confirmation (MUST ask if not provided).",
        },
        "timeZone": {
            "type": "string",
            "required": False,
            "description": "User's timezone. Default: 'Asia/Kolkata'.",
        },
    },
}


# =====================================================================
# VALIDATE
# =====================================================================

def validate(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate & clean tool arguments.
    Returns clean dict ready for Cal.com API.
    Raises ValueError if required fields are missing or invalid.
    """
    logger.info(f"[book_slot] Validating args: {args}")

    # Start time (required)
    start = (args.get("start") or "").strip()
    if not start:
        raise ValueError("start time is required. Ask which slot the customer wants to book.")

    # Validate ISO format
    try:
        # Handle various ISO formats
        if start.endswith("Z"):
            datetime.fromisoformat(start.replace("Z", "+00:00"))
        else:
            datetime.fromisoformat(start)
        logger.info(f"[book_slot] Start time validated: {start}")
    except ValueError as e:
        logger.warning(f"[book_slot] Invalid start time format: {start} - {e}")
        raise ValueError(f"Invalid start time format '{start}'. Must be ISO 8601 format like '2026-03-01T10:00:00.000Z'.")

    # Name (required)
    name = (args.get("name") or "").strip()
    if not name:
        raise ValueError("name is required. Ask customer for their name before booking.")
    logger.info(f"[book_slot] Name validated: {name}")

    # Email (required)
    email = (args.get("email") or "").strip()
    if not email:
        raise ValueError("email is required. Ask customer for their email address before booking.")
    if "@" not in email or "." not in email:
        raise ValueError(f"Invalid email format '{email}'. Please provide a valid email address.")
    logger.info(f"[book_slot] Email validated: {email}")

    # Timezone (optional, default to Asia/Kolkata for India)
    timeZone = (args.get("timeZone") or "").strip()
    if not timeZone:
        timeZone = "Asia/Kolkata"
    logger.info(f"[book_slot] Timezone: {timeZone}")

    return {
        "start": start,
        "name": name,
        "email": email,
        "timeZone": timeZone,
    }


# =====================================================================
# EXECUTE
# =====================================================================

async def execute(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute book_slot: validates args, calls Cal.com booking API.

    Returns:
        {
            "success": True/False,
            "message": "confirmation or error",
            "booking_url": "https://..." (if success)
        }
    """
    import time as _time
    t_start = _time.time()
    
    logger.info(f"[book_slot] ========================================")
    logger.info(f"[book_slot] === EXECUTE START ===")
    logger.info(f"[book_slot] Raw args: {args}")
    logger.info(f"[book_slot] Config: API_VERSION={Config.CAL_BOOK_API_VERSION}, EVENT_TYPE_ID={Config.CAL_EVENT_TYPE_ID}")
    logger.info(f"[book_slot] API Key configured: {bool(Config.CAL_API_KEY)}")

    # Step 1: Validate
    logger.info(f"[book_slot] [Step 1/4] Validating arguments...")
    try:
        clean_args = validate(args)
        logger.info(f"[book_slot] [Step 1/4] PASS: start={clean_args['start']}, name={clean_args['name']}, email={clean_args['email']}, tz={clean_args['timeZone']}")
    except ValueError as e:
        logger.warning(f"[book_slot] [Step 1/4] FAIL: {e}")
        return {"success": False, "message": str(e)}

    # Step 2: Check API key
    logger.info(f"[book_slot] [Step 2/4] Checking API configuration...")
    if not Config.CAL_API_KEY:
        logger.error("[book_slot] [Step 2/4] FAIL: CAL_API_KEY not configured")
        return {
            "success": False,
            "message": "Appointment system abhi configured nahi hai. Please baad mein try karein.",
        }
    logger.info(f"[book_slot] [Step 2/4] PASS: API key present")

    # Step 3: Build request body
    logger.info(f"[book_slot] [Step 3/4] Building request body...")
    request_body = {
        "eventTypeId": int(Config.CAL_EVENT_TYPE_ID),
        "start": clean_args["start"],
        "attendee": {
            "name": clean_args["name"],
            "email": clean_args["email"],
            "timeZone": clean_args["timeZone"],
        },
    }
    logger.info(f"[book_slot] [Step 3/4] PASS: Request body built")
    logger.info(f"[book_slot] Request body: {request_body}")

    # Step 4: Call Cal.com API
    logger.info(f"[book_slot] [Step 4/4] Calling Cal.com API...")
    try:
        url = "https://api.cal.com/v2/bookings"
        headers = {
            "Authorization": f"Bearer {Config.CAL_API_KEY}",
            "cal-api-version": Config.CAL_BOOK_API_VERSION,
            "Content-Type": "application/json",
        }

        logger.info(f"[book_slot] Request URL: POST {url}")
        logger.info(f"[book_slot] Request headers: cal-api-version={Config.CAL_BOOK_API_VERSION}, Content-Type=application/json")

        t_api = _time.time()
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(url, json=request_body, headers=headers)
        api_time = (_time.time() - t_api) * 1000

        logger.info(f"[book_slot] Response status: {response.status_code} ({api_time:.0f}ms)")
        logger.info(f"[book_slot] Response body: {response.text[:1500]}")

        if response.status_code not in (200, 201):
            logger.error(f"[book_slot] [Step 4/4] FAIL: API returned {response.status_code}")
            
            # Try to extract error message from response
            try:
                error_data = response.json()
                logger.error(f"[book_slot] Error data: {error_data}")
                error_msg = error_data.get("message") or error_data.get("error") or str(error_data)
                # Convert dict to string if needed
                if isinstance(error_msg, dict):
                    error_msg = error_msg.get("message", str(error_msg))
                error_msg = str(error_msg)[:100]
                logger.error(f"[book_slot] Extracted error: {error_msg}")
            except Exception as parse_err:
                logger.error(f"[book_slot] Failed to parse error response: {parse_err}")
                error_msg = response.text[:200]
            
            total_time = (_time.time() - t_start) * 1000
            logger.info(f"[book_slot] === EXECUTE END ({total_time:.0f}ms) FAILED ===")
            return {
                "success": False,
                "message": f"Booking nahi ho payi. Error: {error_msg}",
            }

        logger.info(f"[book_slot] [Step 4/4] PASS: API call successful")
        data = response.json()
        logger.info(f"[book_slot] Response parsed successfully")

        # Extract booking info from response
        booking_data = data.get("data", {})
        logger.info(f"[book_slot] Booking data keys: {list(booking_data.keys()) if isinstance(booking_data, dict) else 'not a dict'}")
        
        booking_id = booking_data.get("id") or booking_data.get("uid") or booking_data.get("bookingId")
        meeting_url = booking_data.get("meetingUrl") or booking_data.get("meeting_url") or booking_data.get("url")
        
        logger.info(f"[book_slot] Extracted booking_id: {booking_id}")
        logger.info(f"[book_slot] Extracted meeting_url: {meeting_url}")
        
        # Try to find meeting URL in nested structures
        if not meeting_url:
            logger.info(f"[book_slot] Meeting URL not found in root, checking nested structures...")
            
            # Check in references
            refs = booking_data.get("references", [])
            logger.info(f"[book_slot] References: {refs}")
            for ref in refs:
                if ref.get("meetingUrl"):
                    meeting_url = ref.get("meetingUrl")
                    logger.info(f"[book_slot] Found meeting URL in references: {meeting_url}")
                    break
            
            # Check in metadata
            metadata = booking_data.get("metadata", {})
            logger.info(f"[book_slot] Metadata: {metadata}")
            if metadata.get("videoCallUrl"):
                meeting_url = metadata.get("videoCallUrl")
                logger.info(f"[book_slot] Found meeting URL in metadata: {meeting_url}")

        # Format start time for user-friendly message
        try:
            dt = datetime.fromisoformat(clean_args["start"].replace("Z", "+00:00"))
            readable_time = dt.strftime("%d %B %Y at %I:%M %p")
        except Exception as dt_err:
            logger.warning(f"[book_slot] Failed to format datetime: {dt_err}")
            readable_time = clean_args["start"]

        success_message = f"Appointment booked ho gayi hai {clean_args['name']} ji ke liye {readable_time} ko."
        if meeting_url:
            success_message += f" Meeting link: {meeting_url}"
        else:
            success_message += " Confirmation email bhej diya jayega."

        total_time = (_time.time() - t_start) * 1000
        logger.info(f"[book_slot] Final booking_id: {booking_id}")
        logger.info(f"[book_slot] Final meeting_url: {meeting_url}")
        logger.info(f"[book_slot] Success message: {success_message}")
        logger.info(f"[book_slot] === EXECUTE END ({total_time:.0f}ms) SUCCESS ===")
        
        return {
            "success": True,
            "message": success_message,
            "booking_id": booking_id,
            "meeting_url": meeting_url,
        }

    except httpx.TimeoutException:
        total_time = (_time.time() - t_start) * 1000
        logger.error(f"[book_slot] API request timed out after {total_time:.0f}ms")
        return {
            "success": False,
            "message": "Appointment system se response nahi aaya. Please dobara try karein.",
        }
    except Exception as e:
        total_time = (_time.time() - t_start) * 1000
        logger.error(f"[book_slot] Execution ERROR after {total_time:.0f}ms: {type(e).__name__}: {e}", exc_info=True)
        return {
            "success": False,
            "message": "Booking karne mein kuch problem ho gayi. Please baad mein try karein.",
        }
