"""Parse Retell AI and ElevenLabs custom tool request payloads."""
from typing import Any, Dict, Optional, Tuple


def parse_tool_request(body: Dict[str, Any]) -> Tuple[Optional[str], Dict[str, Any]]:
    """
    Normalize tool HTTP body from Retell or ElevenLabs.

    Retell sends: { "name", "call": { "call_id", ... }, "args": { ... } }
    ElevenLabs often sends flat JSON fields.

    Returns:
        (call_id, args_dict)
    """
    if not body:
        return None, {}

    call_obj = body.get("call") if isinstance(body.get("call"), dict) else {}
    call_id = (
        call_obj.get("call_id")
        or body.get("call_id")
        or body.get("conversation_id")
    )

    args = body.get("args")
    if isinstance(args, dict) and args:
        return call_id, args

    # args_at_root / ElevenLabs flat body
    reserved = {
        "name",
        "call",
        "args",
        "call_id",
        "conversation_id",
    }
    flat_args = {k: v for k, v in body.items() if k not in reserved}
    if flat_args:
        return call_id, flat_args

    return call_id, {}
