"""Patch New Claude Agent (9) (2).json: remove date tool, ngrok URLs, light speed/tone tweaks."""
import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
BASE = (os.getenv("NGROK_URL") or "http://localhost:8000").rstrip("/")
API_RETELL = f"{BASE}/api/retell"
API_ELEVEN = f"{BASE}/api/elevenlabs"
WEBHOOK = f"{BASE}/webhook/retell"

path = Path(__file__).resolve().parents[1] / "New Claude Agent (9) (2).json"
raw = path.read_text(encoding="utf-8")
raw = raw.replace("Sophia", "Neha")
# Normalize any old ngrok host in URLs (including stray leading spaces)
raw = re.sub(
    r"https?://[a-z0-9-]+\.ngrok-free\.dev",
    BASE,
    raw,
)
data = json.loads(raw)
cf = data["conversationFlow"]

# --- Agent-level settings ---
data["webhook_url"] = WEBHOOK
data["timezone"] = "Asia/Calcutta"
data["end_call_after_silence_ms"] = 600000
data["reminder_trigger_ms"] = data.get("reminder_trigger_ms", 15000)
data["reminder_max_count"] = data.get("reminder_max_count", 2)
if data.get("voice_id") in ("retell-Cimo", "11labs-Cimo", None):
    data["voice_id"] = "fish_audio-Cimo"

# --- Global prompt: swap date tool → built-in IST (keep tone section intact) ---
gp = cf["global_prompt"]
DATE_OLD = (
    "IMPORTANT — The get_current_date tool will always be called first to get the real current date.\n"
    "Use the date from that tool's response as 'today'. Never use training data for dates.\n\n"
    "Rules:\n"
    '- "today" → exact date returned by get_current_date tool\n'
    '- "tomorrow" → get_current_date result + 1 day\n'
    '- "Friday" → next upcoming Friday from get_current_date result\n'
    "- NEVER assume or guess the year. Always use what get_current_date returns."
)
DATE_NEW = (
    "IMPORTANT — You have the real current date and time (Asia/Calcutta / IST) from the system. "
    "Use that as today. Never use training data for dates.\n\n"
    "Rules:\n"
    '- "today" → current date from system context (IST)\n'
    '- "tomorrow" → today + 1 day\n'
    '- "Friday" / weekdays → next upcoming that day from today\n'
    "- NEVER assume or guess the year."
)
if DATE_OLD in gp:
    gp = gp.replace(DATE_OLD, DATE_NEW)
else:
    gp = re.sub(r"get_current_date[^\n]*\n?", "", gp)
gp = gp.replace("- Call get_available_slot.", "- Call get_available_slots after date is clear.")
gp = gp.replace("get_current_date first", "system current date (IST)")
CALLBACK = (
    "If user asks how to call you or for a callback: they can call this same number anytime. "
    "That is not an appointment — do not start booking."
)
if "can I call you" not in gp and "call this same number" not in gp:
    gp = gp.rstrip() + "\n\n" + CALLBACK
cf["global_prompt"] = gp

CONVERT_DATE = """Convert the user's requested date to JSON only (do not speak it).

Use system current date/time (Asia/Calcutta / IST) as today — no date tool.
- "today" → that date; "tomorrow" → +1 day; weekdays → next upcoming from today.
- end = start + 1 day. Never use a past year.

Return ONLY:
{"start":"YYYY-MM-DD","end":"YYYY-MM-DD"}"""

FUNCTION_FILLERS = {
    "node-1774698840567": "Hmm, one second, let me check that for you.",
    "node-1774698989384": "Alright, I'm raising your ticket now.",
    "node-1774699163166": "Okay, let me see what times we have open that day.",
    "node-1774699299561": "Perfect, booking that for you now.",
    "node-booking-email-poll-2026": "Just checking WhatsApp for your email, one moment.",
}

# Reroute Ask Date → convert date (skip get_current_date node)
for node in cf["nodes"]:
    nid = node.get("id")
    if nid == "node-1774699912789":
        for edge in node.get("edges", []):
            if edge.get("destination_node_id") == "node-1776900000000":
                edge["destination_node_id"] = "node-1775319880576"
    if nid == "node-1775319880576":
        node["instruction"] = {"type": "prompt", "text": CONVERT_DATE}
    if nid in FUNCTION_FILLERS:
        node["instruction"] = {"type": "static_text", "text": FUNCTION_FILLERS[nid]}
        node["speak_during_execution"] = True
    if nid == "start-node-1774692276701":
        inst = node.get("instruction") or {}
        if inst.get("type") == "static_text":
            inst["text"] = "Hello, this is Neha from Naturals Ice Cream. Umm... how may I help you today?"
    # Light trim on a few verbose node prompts (keep human tone)
    if nid == "node-1774699912789":
        node["instruction"] = {
            "type": "prompt",
            "text": (
                "Ask preferred date warmly and casually — e.g. 'Yeah sure, umm... what date works for you?' "
                "Vary wording; at most one filler per reply."
            ),
        }
    if nid == "node-1774935034342":
        node["instruction"] = {
            "type": "prompt",
            "text": (
                "Confirm before booking: time {{selected_time}}, name {{customer_name}}, email {{email}} (WhatsApp). "
                "Read email once naturally, then ask if you should book. "
                "Never book without {{email}}. One filler max at the start, not in ticket/email details."
            ),
        }

before = len(cf["nodes"])
cf["nodes"] = [n for n in cf["nodes"] if n.get("id") != "node-1776900000000"]
print(f"Removed {before - len(cf['nodes'])} date-tool node(s)")

# --- Tools ---
TOOL_TIMEOUTS = {
    "product_lookup": 20000,
    "create_ticket": 20000,
    "get_available_slots": 10000,
    "book_slot": 10000,
    "send_whatsapp_email_request": 15000,
    "get_booking_email_status": 8000,
}

URL_MAP = {
    "product_lookup": f"{API_ELEVEN}/product-lookup",
    "create_ticket": f"{API_ELEVEN}/create_ticket",
    "send_whatsapp_email_request": f"{API_ELEVEN}/send_whatsapp_email_request",
    "get_booking_email_status": f"{API_ELEVEN}/get_booking_email_status",
}

cf["tools"] = [
    t
    for t in cf["tools"]
    if t.get("name")
    not in ("get_current_date", "check_availability_cal", "book_appointment_cal")
]

for t in cf["tools"]:
    name = t.get("name")
    if name in URL_MAP:
        t["url"] = URL_MAP[name].strip()
    if name in TOOL_TIMEOUTS:
        t["timeout_ms"] = TOOL_TIMEOUTS[name]
    t["speak_after_execution"] = True
    if name in ("product_lookup", "create_ticket", "get_available_slots", "book_slot"):
        t["speak_during_execution"] = True

    if name == "get_available_slots":
        t.clear()
        t.update(
            {
                "headers": {},
                "parameter_type": "json",
                "method": "POST",
                "query_params": {},
                "description": (
                    "Open times for the requested day. Pass date as YYYY-MM-DD from {{start}}. "
                    "Use IST system date for today/tomorrow/weekdays — no date tool. "
                    "Refresh date each new availability check."
                ),
                "type": "custom",
                "url": f"{API_RETELL}/get_available_slots",
                "tool_id": "tool-1774971619011",
                "args_at_root": True,
                "timeout_ms": 10000,
                "speak_after_execution": True,
                "speak_during_execution": True,
                "name": "get_available_slots",
                "response_variables": {},
                "parameters": {
                    "type": "object",
                    "properties": {
                        "date": {
                            "type": "string",
                            "description": "Appointment day from {{start}} as YYYY-MM-DD.",
                        }
                    },
                    "required": ["date"],
                },
            }
        )
    elif name == "book_slot":
        t.clear()
        t.update(
            {
                "headers": {},
                "parameter_type": "json",
                "method": "POST",
                "query_params": {},
                "description": (
                    "Book after user confirms and {{email}} is ready. "
                    "attendee.name={{customer_name}}, attendee.email={{email}}."
                ),
                "type": "custom",
                "url": f"{API_RETELL}/book_slot",
                "tool_id": "tool-1774973702770",
                "args_at_root": True,
                "timeout_ms": 10000,
                "speak_after_execution": True,
                "speak_during_execution": True,
                "name": "book_slot",
                "response_variables": {},
                "parameters": {
                    "type": "object",
                    "required": ["start", "attendee"],
                    "properties": {
                        "start": {
                            "type": "string",
                            "description": "Exact ISO slot from availability.",
                        },
                        "attendee": {
                            "type": "object",
                            "required": ["name", "email", "timeZone"],
                            "properties": {
                                "name": {"type": "string"},
                                "email": {"type": "string"},
                                "timeZone": {"type": "string"},
                            },
                        },
                    },
                },
            }
        )
    elif name == "product_lookup":
        t["description"] = (
            "Ice cream flavors, ingredients, nutrition, pricing. Pass the customer's full question as query."
        )
    elif name == "get_booking_email_status":
        t["speak_during_execution"] = True

path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"Patched {path.name}")
print(f"  webhook: {WEBHOOK}")
print(f"  tools -> {BASE}/api/...")
