"""Patch New Claude Agent (13).json: remove get_current_date, anti-stuck tool settings."""
import json
from pathlib import Path

path = Path(__file__).resolve().parents[1] / "docs" / "New Claude Agent (13).json"
data = json.loads(path.read_text(encoding="utf-8"))
cf = data["conversationFlow"]

OLD_DATE_BLOCK = (
    "IMPORTANT — The get_current_date tool will always be called first to get the real current date.\n"
    "Use the date from that tool's response as 'today'. Never use training data for dates.\n\n"
    "Rules:\n"
    '- "today" → exact date returned by get_current_date tool\n'
    '- "tomorrow" → get_current_date result + 1 day\n'
    '- "Friday" → next upcoming Friday from get_current_date result\n'
    "- NEVER assume or guess the year. Always use what get_current_date returns."
)
NEW_DATE_BLOCK = (
    "IMPORTANT — Retell injects the real current date and time automatically (timezone Asia/Calcutta / IST). "
    "Use that as today. Never use training data for dates.\n\n"
    "Rules:\n"
    '- "today" → current date from system context (IST)\n'
    '- "tomorrow" → today + 1 day\n'
    '- "Friday" / weekday names → next upcoming that day from today\n'
    "- NEVER assume or guess the year. Always derive from system current date."
)
if OLD_DATE_BLOCK in cf["global_prompt"]:
    cf["global_prompt"] = cf["global_prompt"].replace(OLD_DATE_BLOCK, NEW_DATE_BLOCK)
else:
    print("WARN: global_prompt date block not found — may already be patched")

CONVERT_DATE_TEXT = """You must convert the user's requested date into YYYY-MM-DD format.

Use Retell's built-in current date and time (Asia/Calcutta / IST) as today.
Do NOT use your training knowledge. Do NOT guess. Do NOT use 2024.

Understanding relative dates:
- "today" → current date from system context (IST)
- "tomorrow" → that date + 1 day
- "next Friday" / "Monday" → calculate forward from that date

Rules:
1. Derive year, month, day from system current date.
2. Never use a past year.
3. end = start + 1 day.

Return ONLY JSON:

{
 "start": "YYYY-MM-DD",
 "end": "YYYY-MM-DD"
}

This is internal. Do not speak the JSON or dates to the user.
"""

for node in cf["nodes"]:
    nid = node.get("id")
    if nid == "node-1774699912789":
        for edge in node.get("edges", []):
            if edge.get("destination_node_id") == "node-1776900000000":
                edge["destination_node_id"] = "node-1775319880576"
    if nid == "node-1775319880576":
        node["instruction"] = {"type": "prompt", "text": CONVERT_DATE_TEXT}
    if nid == "node-1774698840567":
        node["instruction"] = {
            "type": "static_text",
            "text": "Hmm, one second, let me check that for you.",
        }
    if nid == "node-1774698989384":
        node["instruction"] = {
            "type": "static_text",
            "text": "Alright, I am just getting that ticket raised for you now.",
        }
    if nid == "node-1774699163166":
        node["instruction"] = {
            "type": "static_text",
            "text": "Okay, let me check what times we have open for that day.",
        }
        node.setdefault("else_edge", {})["destination_node_id"] = "node-1774699912789"
    if nid == "node-1774699299561":
        node["instruction"] = {
            "type": "static_text",
            "text": "Perfect, I am booking that appointment for you now.",
        }
    if nid == "node-booking-email-poll-2026":
        node["speak_during_execution"] = True
        node["instruction"] = {
            "type": "static_text",
            "text": "Just checking WhatsApp for your email, one moment.",
        }

before = len(cf["nodes"])
cf["nodes"] = [n for n in cf["nodes"] if n.get("id") != "node-1776900000000"]
print(f"Removed {before - len(cf['nodes'])} node(s)")

tool_updates = {
    "product_lookup": {
        "timeout_ms": 20000,
        "speak_after_execution": True,
        "speak_during_execution": True,
    },
    "create_ticket": {
        "timeout_ms": 20000,
        "speak_after_execution": True,
        "speak_during_execution": True,
    },
    "get_available_slots": {
        "timeout_ms": 15000,
        "speak_after_execution": True,
        "speak_during_execution": True,
    },
    "book_slot": {
        "timeout_ms": 20000,
        "speak_after_execution": True,
        "speak_during_execution": True,
    },
    "send_whatsapp_email_request": {
        "timeout_ms": 15000,
        "speak_after_execution": True,
        "speak_during_execution": True,
    },
    "get_booking_email_status": {
        "timeout_ms": 8000,
        "speak_after_execution": True,
        "speak_during_execution": True,
    },
}

cf["tools"] = [t for t in cf["tools"] if t.get("name") != "get_current_date"]
for t in cf["tools"]:
    name = t.get("name")
    if name in tool_updates:
        t.update(tool_updates[name])
    if name == "get_available_slots":
        t["description"] = (
            "Call when the user asks for available appointment times.\n\n"
            "Use system current date (IST) for today/tomorrow/relative dates — no separate date tool needed.\n"
            "Derive start and end for the requested day before calling. Do not reuse stale start/end from earlier turns.\n\n"
            "Query params use {{start}} and {{end}} as YYYY-MM-DD (start = requested day, end = next day).\n"
            "If this tool fails or times out, apologize briefly and ask the user to repeat the date."
        )

data["end_call_after_silence_ms"] = 600000
path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"Patched {path.name}")
