"""Patch aditya .json: remove cal/date tools, ngrok URLs, concise calm global prompt."""
import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
BASE = (os.getenv("NGROK_URL") or "http://localhost:8000").rstrip("/")
API_ELEVEN = f"{BASE}/api/elevenlabs"
WEBHOOK = f"{BASE}/webhook/retell"

path = Path(__file__).resolve().parents[1] / "aditya .json"
raw = path.read_text(encoding="utf-8")
raw = re.sub(r"https?://[a-z0-9-]+\.ngrok-free\.dev", BASE, raw)
data = json.loads(raw)
cf = data["conversationFlow"]

GLOBAL_PROMPT = (
    "You are Neha, Naturals Ice Cream phone support (India). English only.\n\n"
    "Tone: calm, friendly, and steady — talk like a normal support agent on a phone call. "
    "Do not sound overly excited, dramatic, or salesy. Keep the same pace and warmth from start to finish. "
    "Short replies; at most one light filler (e.g. okay, sure) when it fits naturally.\n\n"
    "Variables: {{customer_name}} for tickets and booking. {{email}} only from WhatsApp — never ask for email on the call.\n\n"
    "Never read JSON, tool output, or ISO timestamps aloud. Say times naturally (e.g. 3 PM).\n\n"
    "Products: call product_lookup first; speak only what it returns.\n\n"
    "Complaints: use {{customer_name}} if set, else ask name once → create_ticket → say ticket number.\n\n"
    "Booking (IST from system context — no date tool):\n"
    "1. Ask preferred date.\n"
    "2. Convert to start/end YYYY-MM-DD (end = start + 1 day).\n"
    "3. get_available_slots → list only returned times.\n"
    "4. User picks time → send_whatsapp_email_request → poll get_booking_email_status until {{email}} ready.\n"
    "5. Confirm → book_slot only after user confirms and {{email}} is set.\n\n"
    "After every tool: respond briefly and continue. On failure, apologize and retry or re-ask.\n\n"
    "If user asks how to reach you or for a callback: they can call this same number anytime — not an appointment.\n\n"
    "Misconduct: warn once, then end call. After each task, ask if anything else."
)

CONVERT_DATE = """Convert the user's requested date to JSON only (do not speak it).

Use system current date/time (Asia/Calcutta / IST) as today — no date tool.
- "today" → that date; "tomorrow" → +1 day; weekdays → next upcoming from today.
- end = start + 1 day. Never use a past year.

Return ONLY:
{"start":"YYYY-MM-DD","end":"YYYY-MM-DD"}"""

FUNCTION_FILLERS = {
    "node-1774698840567": "One moment, let me check that for you.",
    "node-1774698989384": "I'm raising your ticket now.",
    "node-1774699163166": "Let me check what times we have that day.",
    "node-1774699299561": "Booking that for you now.",
    "node-booking-email-poll-2026": "Checking WhatsApp for your email, one moment.",
}

data["webhook_url"] = WEBHOOK
data["timezone"] = "Asia/Calcutta"
cf["global_prompt"] = GLOBAL_PROMPT

# Calmer defaults — less forced filler personality
if "handbook_config" in data:
    data["handbook_config"]["natural_filler_words"] = False
    data["handbook_config"]["default_personality"] = False

for node in cf["nodes"]:
    nid = node.get("id")
    if nid == "node-1774699912789":
        for edge in node.get("edges", []):
            if edge.get("destination_node_id") == "node-1776900000000":
                edge["destination_node_id"] = "node-1775319880576"
        node["instruction"] = {
            "type": "prompt",
            "text": (
                "Ask preferred date in a calm, natural way — e.g. 'Sure, what date works for you?' "
                "Vary wording; keep tone steady, not overly enthusiastic."
            ),
        }
    if nid == "node-1775319880576":
        node["instruction"] = {"type": "prompt", "text": CONVERT_DATE}
    if nid in FUNCTION_FILLERS:
        node["instruction"] = {"type": "static_text", "text": FUNCTION_FILLERS[nid]}
        node["speak_during_execution"] = True
    if nid == "start-node-1774692276701":
        inst = node.get("instruction") or {}
        if inst.get("type") == "static_text":
            inst["text"] = "Hello, this is Neha from Naturals Ice Cream. How may I help you today?"
    if nid == "node-1774935034342":
        node["instruction"] = {
            "type": "prompt",
            "text": (
                "Confirm before booking: time {{selected_time}}, name {{customer_name}}, email {{email}} (WhatsApp). "
                "Read email once naturally, then ask if you should book. "
                "Never book without {{email}}. Stay calm and clear — no extra excitement."
            ),
        }

before = len(cf["nodes"])
cf["nodes"] = [n for n in cf["nodes"] if n.get("id") != "node-1776900000000"]
print(f"Removed {before - len(cf['nodes'])} get_current_date node(s)")

TOOL_TIMEOUTS = {
    "product_lookup": 20000,
    "create_ticket": 20000,
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

    # get_available_slots / book_slot stay on Cal.com — do not reroute to backend
    if name == "get_available_slots":
        desc = t.get("description") or ""
        desc = desc.replace("Always call get_current_date first for each new availability check request.\n", "")
        desc = desc.replace("Call get_current_date first when date is relative. ", "")
        if "system current date" not in desc and "no date tool" not in desc:
            desc = (
                "Use system current date (Asia/Calcutta / IST) for today/tomorrow/weekdays — no date tool.\n"
                + desc
            )
        t["description"] = desc
    elif name == "product_lookup":
        t["description"] = (
            "Ice cream flavors, ingredients, nutrition, pricing. Pass the customer's full question as query."
        )
        t["speak_during_execution"] = True
    elif name == "create_ticket":
        t["speak_during_execution"] = True
    elif name == "get_booking_email_status":
        t["speak_during_execution"] = True

path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"Patched {path.name}")
print(f"  webhook: {WEBHOOK}")
print(f"  tools: {len(cf['tools'])} remaining")
