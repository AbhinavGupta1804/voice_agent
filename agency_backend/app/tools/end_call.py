"""
end_call tool — Standalone tool for Custom LLM voice calls.
============================================================
Ends the active phone call via Twilio REST API.
Used when the customer says goodbye, thank you, or wants to end the call.

Interface:
    TOOL_DEFINITION  — dict describing the tool (name, description, params)
    validate(args)   — validates & cleans arguments, returns clean dict
    execute(args)    — terminates call via Twilio API, returns result dict
"""
import logging
from typing import Dict, Any

from twilio.rest import Client as TwilioClient

from ..config import Config

logger = logging.getLogger(__name__)


# =====================================================================
# TOOL DEFINITION (used by dispatcher to build system prompt)
# =====================================================================

TOOL_DEFINITION = {
    "name": "end_call",
    "description": (
        "End/hang up the current phone call. Use when the customer says goodbye, "
        "thank you, or clearly indicates they want to end the conversation. "
        "Common triggers: 'bye', 'thank you', 'that's all', 'nothing else', "
        "'okay bye', 'thanks bye', 'goodbye', 'have a nice day', 'bas itna hi tha', "
        "'theek hai', 'dhanyavaad', 'shukriya'. "
        "IMPORTANT: Always say a warm goodbye message FIRST using final_answer, "
        "then call end_call on the NEXT turn."
    ),
    "parameters": {
        "reason": {
            "type": "string",
            "required": False,
            "description": "Reason for ending call (e.g., 'customer_goodbye', 'resolved', 'misconduct'). Default: 'customer_goodbye'",
        },
    },
}


# =====================================================================
# VALIDATE
# =====================================================================

def validate(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate & clean tool arguments.
    Returns clean dict with reason.
    """
    reason = (args.get("reason") or "customer_goodbye").strip()
    return {"reason": reason}


# =====================================================================
# EXECUTE
# =====================================================================

async def execute(args: Dict[str, Any], call_sid: str = None) -> Dict[str, Any]:
    """
    Execute end_call: terminates the active phone call via Twilio API.

    Args:
        args: Tool arguments (reason)
        call_sid: The Twilio CallSid to terminate

    Returns:
        {
            "success": True/False,
            "message": "confirmation or error message"
        }
    """
    try:
        clean_args = validate(args)
    except ValueError as e:
        return {"success": False, "message": str(e)}

    reason = clean_args["reason"]

    if not call_sid:
        logger.warning("[end_call] No call_sid provided, cannot end call via API")
        return {
            "success": True,
            "message": "Call khatam ho rahi hai. Thank you for calling Naturals Ice Cream!",
        }

    logger.info(f"[end_call] Ending call {call_sid} (reason: {reason})")

    try:
        import asyncio

        def _hangup():
            client = TwilioClient(Config.TWILIO_ACCOUNT_SID, Config.TWILIO_AUTH_TOKEN)
            call = client.calls(call_sid).update(status="completed")
            return call.status

        status = await asyncio.to_thread(_hangup)
        logger.info(f"[end_call] Call {call_sid} terminated successfully (status: {status})")

        return {
            "success": True,
            "message": "Call successfully ended. Thank you for calling Naturals Ice Cream!",
        }

    except Exception as e:
        logger.error(f"[end_call] Failed to end call {call_sid}: {e}", exc_info=True)
        return {
            "success": True,  # Still return success so the agent says goodbye
            "message": "Call khatam ho rahi hai. Thank you for calling Naturals Ice Cream!",
        }
