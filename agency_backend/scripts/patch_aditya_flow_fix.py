"""Fix aditya .json flow: manager routing, date-extract loop, booking order."""
import json
from pathlib import Path

path = Path(__file__).resolve().parents[1] / "aditya .json"
data = json.loads(path.read_text(encoding="utf-8"))
cf = data["conversationFlow"]

MANAGER_NODE = {
    "instruction": {
        "type": "prompt",
        "text": (
            "User wants a manager or supervisor. Stay calm. Ask what they need help with in one short question. "
            "Say you can note it for the team to follow up, or raise a support ticket now. "
            "Do NOT ask for an appointment date unless they clearly want to schedule a meeting or visit."
        ),
    },
    "name": "Manager / Escalation",
    "edges": [
        {
            "destination_node_id": "node-1774699770683",
            "id": "edge-manager-to-complaint",
            "transition_condition": {
                "type": "prompt",
                "prompt": "User describes a problem OR wants a ticket OR complaint",
            },
        },
        {
            "destination_node_id": "node-1774699912789",
            "id": "edge-manager-to-booking",
            "transition_condition": {
                "type": "prompt",
                "prompt": "User explicitly wants to schedule a meeting OR appointment with a date",
            },
        },
        {
            "destination_node_id": "node-1775429325981",
            "id": "edge-manager-to-anything-else",
            "transition_condition": {
                "type": "prompt",
                "prompt": "User is satisfied OR only wanted general callback info",
            },
        },
    ],
    "id": "node-manager-escalation-2026",
    "type": "conversation",
    "display_position": {"x": -330, "y": 990},
}

DATE_EXTRACT_DESC = (
    "YYYY-MM-DD start date for the appointment day. "
    "Use system current date (Asia/Calcutta / IST) as today — no date tool. "
    "today → that date; tomorrow → +1 day; weekdays → next upcoming. Never use a past year."
)
DATE_END_DESC = "YYYY-MM-DD end date = start + 1 day."

cf["global_prompt"] = (
    "You are Neha, Naturals Ice Cream phone support (India). English only.\n\n"
    "Tone: calm, friendly, steady — normal phone support. Not overly excited or dramatic. "
    "Same pace throughout. Short replies; at most one light filler when natural.\n\n"
    "Variables: {{customer_name}} for tickets and booking. {{email}} only from WhatsApp — never ask for email on the call.\n\n"
    "Manager request: NOT the same as booking. If user wants a manager, ask what they need — do not jump to appointment dates.\n\n"
    "Never read JSON, tool output, or ISO timestamps aloud. Say times naturally (e.g. 3 PM).\n\n"
    "Products: product_lookup first; speak only what it returns.\n\n"
    "Complaints: {{customer_name}} if set, else ask name once → create_ticket → say ticket number.\n\n"
    "Booking (IST system date — no date tool):\n"
    "1. Ask preferred date.\n"
    "2. Extract start/end YYYY-MM-DD (end = start + 1 day).\n"
    "3. get_available_slots → list returned times only.\n"
    "4. User picks time → ask name if needed → send_whatsapp_email_request → poll get_booking_email_status until {{email}} set.\n"
    "5. Confirm details → book_slot ONLY after user confirms AND {{email}} is ready.\n\n"
    "Never ask 'should I book' before WhatsApp email is collected.\n\n"
    "After tools: brief response and continue. On failure, apologize and retry.\n\n"
    "Callback on this number is not an appointment.\n\n"
    "Misconduct: warn once, end call. After each task, ask if anything else."
)

# Insert manager node if missing
if not any(n.get("id") == "node-manager-escalation-2026" for n in cf["nodes"]):
    cf["nodes"].append(MANAGER_NODE)

# Remove redundant convert-date conversation node (causes extract loop)
cf["nodes"] = [n for n in cf["nodes"] if n.get("id") != "node-1775319880576"]

for node in cf["nodes"]:
    nid = node.get("id")

    if nid == "start-node-1774692276701":
        for edge in node.get("edges", []):
            prompt = edge.get("transition_condition", {}).get("prompt", "")
            if "manager" in prompt.lower() and "appointment" in prompt.lower():
                edge["transition_condition"]["prompt"] = (
                    "User asks for manager OR supervisor OR speak to someone senior"
                )
                edge["destination_node_id"] = "node-manager-escalation-2026"
        node["edges"].append(
            {
                "destination_node_id": "node-early-customer-name-2026",
                "id": "edge-welcome-appointment-only",
                "transition_condition": {
                    "type": "prompt",
                    "prompt": "User wants appointment OR schedule meeting OR book visit (not manager)",
                },
            }
        )

    if nid == "node-early-customer-name-2026":
        for edge in node.get("edges", []):
            if edge.get("id") == "edge-early-to-appointment":
                edge["destination_node_id"] = "node-manager-escalation-2026"
                edge["transition_condition"]["prompt"] = (
                    "User asks for manager OR supervisor OR speak to someone senior"
                )
        node["edges"].append(
            {
                "destination_node_id": "node-1774699912789",
                "id": "edge-early-to-appointment-only",
                "transition_condition": {
                    "type": "prompt",
                    "prompt": "User wants appointment OR schedule meeting OR book visit (not manager)",
                },
            }
        )

    if nid == "node-1774699912789":
        node["instruction"] = {
            "type": "prompt",
            "text": (
                "User wants to book an appointment. Ask preferred date calmly — "
                "e.g. 'Sure, what date works for you?' One question only. Not for manager-only requests."
            ),
        }
        for edge in node.get("edges", []):
            if edge.get("destination_node_id") == "node-1775319880576":
                edge["destination_node_id"] = "node-1774699962185"

    if nid == "node-1774699962185":
        for var in node.get("variables", []):
            if var.get("name") == "start":
                var["description"] = DATE_EXTRACT_DESC
            if var.get("name") == "end":
                var["description"] = DATE_END_DESC
        node["else_edge"] = {
            "destination_node_id": "node-1774699912789",
            "id": "node-1774699962185-else-edge",
            "transition_condition": {"type": "prompt", "prompt": "Date could not be parsed — ask again"},
        }
        for edge in node.get("edges", []):
            if edge.get("id") == "edge-1774699962185-wu2hchhx9":
                edge["transition_condition"]["prompt"] = (
                    "start and end dates extracted successfully — proceed to check availability"
                )

    if nid == "node-1774934968660":
        node["instruction"] = {
            "type": "prompt",
            "text": (
                "If {{customer_name}} is already set: do not ask again — go to WhatsApp email step. "
                "If empty: ask full name once, calmly — e.g. 'May I have your full name please?' "
                "Never ask for email on the call. Do not repeat the name question."
            ),
        }

    if nid == "node-1775362969761":
        node["instruction"] = {
            "type": "prompt",
            "text": (
                "List available times from get_available_slots only. Ask which time they prefer. "
                "Do NOT ask to confirm or book yet — email comes via WhatsApp first."
            ),
        }

    if nid == "node-1775429325981":
        for edge in node.get("edges", []):
            if edge.get("id") == "edge-1775441784382-qclenjxrv":
                edge["destination_node_id"] = "node-manager-escalation-2026"
                edge["transition_condition"]["prompt"] = (
                    "User asks for manager OR supervisor"
                )
        node["edges"].append(
            {
                "destination_node_id": "node-1774699912789",
                "id": "edge-anyelse-appointment-only",
                "transition_condition": {
                    "type": "prompt",
                    "prompt": "User wants appointment OR schedule meeting OR book visit",
                },
            }
        )

path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"Fixed flow in {path.name}")
