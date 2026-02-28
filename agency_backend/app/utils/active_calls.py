"""
Active Calls Store — In-memory mapping of phone numbers to call SIDs.
=====================================================================
Used by end_call tool to find the Twilio CallSid for the current call.
"""
import logging
from typing import Optional, Dict

logger = logging.getLogger(__name__)

# phone_number → call_sid mapping for active calls
_active_calls: Dict[str, str] = {}


def register_call(phone_number: str, call_sid: str) -> None:
    """Register an active call. Called when Twilio call starts."""
    if phone_number and call_sid:
        _active_calls[phone_number] = call_sid
        logger.info(f"[ActiveCalls] Registered: {phone_number} → {call_sid}")


def get_call_sid(phone_number: str) -> Optional[str]:
    """Get the call_sid for a phone number."""
    return _active_calls.get(phone_number)


def unregister_call(phone_number: str) -> None:
    """Remove a call from the active store. Called on cleanup."""
    if phone_number and phone_number in _active_calls:
        removed = _active_calls.pop(phone_number)
        logger.info(f"[ActiveCalls] Unregistered: {phone_number} (was {removed})")


def get_latest_call_sid() -> Optional[str]:
    """Get the most recently registered call_sid (fallback)."""
    if _active_calls:
        # Return last inserted (Python 3.7+ dicts are ordered)
        return list(_active_calls.values())[-1]
    return None
