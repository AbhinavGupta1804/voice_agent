"""Patch Agent 13: backend Cal tools, fix booking misroute, no get_current_date."""
import json
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
base = (os.getenv("NGROK_URL") or "http://localhost:8000").rstrip("/")
api = f"{base}/api/retell"

path = Path(__file__).resolve().parents[1] / "docs" / "New Claude Agent (13).json"
data = json.loads(path.read_text(encoding="utf-8"))
cf = data["conversationFlow"]

CALLBACK_RULE = (
    "If user asks 'can I call you', how to reach you, or callback: say they can call this same "
    "number anytime. That is NOT an appointment — do not start booking."
)
gp = cf["global_prompt"]
if "can I call you" not in gp:
    cf["global_prompt"] = gp.rstrip() + "\n\n" + CALLBACK_RULE

for node in cf["nodes"]:
    if node.get("id") == "node-1775429325981":
        for edge in node.get("edges", []):
            if edge.get("destination_node_id") == "node-1774699912789":
                edge["transition_condition"]["prompt"] = (
                    "User wants manager visit OR schedule appointment with date/time"
                )

for t in cf["tools"]:
    name = t.get("name")
    if name == "get_available_slots":
        t.clear()
        t.update({
            "headers": {},
            "parameter_type": "json",
            "method": "POST",
            "query_params": {},
            "description": "Check open times for date (YYYY-MM-DD in {{start}}). Uses server Cal.com config.",
            "type": "custom",
            "url": f"{api}/get_available_slots",
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
        })
    elif name == "book_slot":
        t.clear()
        t.update({
            "headers": {},
            "parameter_type": "json",
            "method": "POST",
            "query_params": {},
            "description": "Book after {{email}} ready and user confirmed. Pass start ISO time and attendee name/email.",
            "type": "custom",
            "url": f"{api}/book_slot",
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
                    "start": {"type": "string", "description": "Exact ISO slot from availability."},
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
        })

path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"Patched tools -> {api}/get_available_slots and /book_slot")
