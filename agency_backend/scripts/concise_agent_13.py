"""Drastically reduce token usage in New Claude Agent (13).json."""
import json
from pathlib import Path

path = Path(__file__).resolve().parents[1] / "docs" / "New Claude Agent (13).json"
data = json.loads(path.read_text(encoding="utf-8"))
cf = data["conversationFlow"]

CONCISE_GLOBAL = """You are Neha, Naturals Ice Cream phone support (India). English only. Warm, short, natural — not robotic.

Variables: {{customer_name}} for tickets and booking. {{email}} only from WhatsApp for booking. Never ask for email on the call.

Never read JSON, tool output, or ISO timestamps aloud. Say times naturally (e.g. 3 PM).

Products: call product_lookup first; speak only what it returns. If flavor not found, say you do not have that info.

Complaints: if {{customer_name}} is set, use it; else ask name once. Then create_ticket. Always say the ticket number returned.

Booking (IST dates from system context — no date tool):
1. Ask preferred date.
2. Convert to start/end YYYY-MM-DD (end = start + 1 day).
3. get_available_slots → list only returned times.
4. User picks time → send_whatsapp_email_request → poll get_booking_email_status until {{email}} ready.
5. Confirm details → book_slot only after user confirms and {{email}} is set.

After every tool: speak immediately and continue. If a tool fails, apologize briefly and retry or re-ask.

Misconduct: warn once, then end call. After each task, ask if anything else."""

# Short node instructions by node id
NODE_TEXT = {
    "start-node-1774692276701": "Hello, this is Neha from Naturals Ice Cream. How may I help you today?",
    "node-1774698840567": "Hmm, one second, let me check that.",
    "node-1774698989384": "Alright, raising your ticket now.",
    "node-1774699163166": "Let me check open times for that day.",
    "node-1774699299561": "Booking that for you now.",
    "node-1774879382888": None,  # End Call - static
    "node-1774699770684": "Sorry to hear that. Ask name only if {{customer_name}} empty; else capture issue in one sentence. Empathize briefly first.",
    "node-1774699912789": "Ask preferred date casually. One short question.",
    "node-1774700607617": "Confirm ticket created; include ticket number from tool. Brief and warm.",
    "node-1774702302668": "Apologize — ticket system issue. Team will follow up.",
    "node-1774934991043": None,  # extract - no instruction
    "node-extract-ticket-2026": None,
    "node-1774935034342": "Read {{selected_time}}, {{customer_name}}, {{email}} once. Ask to confirm booking.",
    "node-1775319880576": """Convert user's date to JSON only (do not speak it):
{"start":"YYYY-MM-DD","end":"YYYY-MM-DD"}
Use IST system date for today/tomorrow/weekdays. end = start + 1 day.""",
    "node-1775362969761": "List slots from tool only. If user already picked a valid time, confirm briefly instead of full list.",
    "node-1775363147348": None,
    "node-1775363555011": "Confirm booking success briefly.",
    "node-1775363612729": "Slot failed — offer to check other times.",
    "node-1775429325981": "Ask what else they need.",
    "node-1775486466596": None,
    "node-booking-email-send-2026": "Tell them you sent WhatsApp — reply there with email.",
    "node-booking-email-wait-2026": "Wait for them to say they sent the email on WhatsApp.",
    "node-booking-email-poll-2026": "Checking WhatsApp for your email.",
    "node-early-customer-name-2026": "If they give their name, capture it. Do not ask if {{customer_name}} already set.",
    "node-1774934991043": None,
    "node-1775363555011": "Booking confirmed. Mention confirmation shortly.",
    "node-1775363612729": "That slot is taken. Offer other times from last availability check.",
    "node-1774704438124": None,
    "node-1775363147348": None,
    "node-1774699962185": None,
    "node-1774699962185": None,
}

# Map by name for nodes without stable ids in map
NODE_TEXT_BY_NAME = {
    "Welcome Node": "Hello, this is Neha from Naturals Ice Cream. How may I help you today?",
    "End Call": "End the call politely.",
    "Ask Name": "Empathize briefly. Ask name only if {{customer_name}} empty; else get issue in one sentence.",
    "Ask Date & Time": "Ask preferred date in one short question.",
    "Ask Booking Name": "Ask full name only if {{customer_name}} empty.",
    "Show Available slots": "List only tool-returned times, or confirm if user already chose a valid one.",
    "Confirm Booking": "Read time, name, email once. Ask to confirm before booking.",
    "Anything Else": "Ask if they need anything else.",
    "Map time to slot": "Map {{selected_time}} to exact ISO from slots. Internal only.",
    "Confirmation ": "Confirm ticket with number from create_ticket response.",
    "Early Capture Customer Name": "Capture name if user volunteers it early in call.",
    "Extract Variables": None,
    "Extract Ticket Info": None,
    "Extract Booking Name": None,
    "Conversation": None,  # handled per-id below
}

CONVERSATION_BY_ID = {
    "node-1774700607617": "Confirm ticket with ticket number from tool.",
    "node-1774879761276": "Answer using product_lookup result only. If flavor not found, say you do not have that info.",
    "node-1774935034342": "Confirm time, name, email. Ask permission to book.",
    "node-1775319880576": NODE_TEXT["node-1775319880576"],
    "node-1775362969761": NODE_TEXT["node-1775362969761"],
    "node-1775429325981": "Anything else I can help with?",
    "node-1775363555011": "Appointment booked. They will get confirmation soon.",
    "node-1775363612729": "Slot unavailable. Suggest picking another time from available slots.",
    "node-1774702302668": "Sorry, ticket could not be created right now. Team will contact them.",
    "node-1774879382888": "Goodbye, thank you for calling Naturals.",
}

FUNCTION_STATIC = {
    "node-1774698840567": "One moment, checking that.",
    "node-1774698989384": "Raising your ticket now.",
    "node-1774699163166": "Checking available times.",
    "node-1774699299561": "Booking now.",
    "node-booking-email-poll-2026": "Checking WhatsApp for your email.",
}

cf["global_prompt"] = CONCISE_GLOBAL

for node in cf["nodes"]:
    # Biggest win: drop finetune examples
    node.pop("finetune_transition_examples", None)

    nid = node.get("id")
    name = node.get("name")
    ntype = node.get("type")

    if ntype == "function" and nid in FUNCTION_STATIC:
        node["instruction"] = {"type": "static_text", "text": FUNCTION_STATIC[nid]}
        continue

    text = CONVERSATION_BY_ID.get(nid) or NODE_TEXT.get(nid) or NODE_TEXT_BY_NAME.get(name)
    if text is None:
        continue

    inst = node.get("instruction") or {}
    if inst.get("type") == "static_text" and name == "Welcome Node":
        inst["text"] = text
    elif inst.get("type") in ("prompt", "static_text"):
        node["instruction"] = {"type": "prompt", "text": text}
    elif name == "Welcome Node":
        node["instruction"] = {"type": "static_text", "text": text}

# Trim transition prompts on edges
EDGE_SHORT = {
    "User provides date": "user gave date",
    "Convert date": "dates converted",
    "Ticket created": "ticket created",
    "Give user list of time slots avaialble": "show slot list",
    "After get_available_slots: the user already stated a specific clock time earlier in this call (e.g. 4 PM) AND that time appears among the returned available slots—skip listing all slots aloud; go extract selected_time then map to slot.": "preselected time matches slots",
    "Go to book_slot ONLY if user confirms booking AND {{email}} was received via WhatsApp (ready=true). If email missing, go back to WhatsApp flow.": "confirmed and email ready",
    "Go to book_slot ONLY if user confirms booking AND {{email}} was received": "confirmed and email ready",
    "get_booking_email_status returned ready=true or status email_received with a non-empty email": "email received",
    "Email not received yet — tell user to check WhatsApp and try again": "email not ready",
    "After send_whatsapp_email_request succeeds": "whatsapp sent",
    "User says they sent the email, or is ready, or asks to check": "user ready to check email",
    "customer_name is already set — go to Send WhatsApp Email Request": "name already set",
    "customer_name captured — go to Send WhatsApp Email Request": "name captured",
    "After sharing the product info, proceed to ask if they need anything else": "done sharing product info",
    "After informing the user, proceed to ask if they need anything else": "done informing user",
    "User wants a different date OR none of these work": "different date needed",
    "User clearly wants to do something else entirely": "different intent",
    "Give users time he can choose from on that date": "user picks time",
    "If Appointment booked give confirmation.": "booked",
    "User gave their full name": "name given",
    "User says email is wrong — resend WhatsApp email request": "wrong email",
    "User says cancel OR wants to do something else": "cancel or other",
    "Date fetched — proceed to convert user requested date": "date ready",
}
for node in cf["nodes"]:
    for edge in node.get("edges") or []:
        tc = edge.get("transition_condition") or {}
        if tc.get("type") == "prompt":
            p = tc.get("prompt", "")
            tc["prompt"] = EDGE_SHORT.get(p, p if len(p) <= 48 else p[:48])
    else_e = node.get("else_edge")
    if else_e:
        tc = else_e.get("transition_condition") or {}
        if tc.get("type") == "prompt" and tc.get("prompt") not in ("Else",):
            # Retell requires else_edge prompt to be exactly "Else" — do not lowercase
            if (tc.get("prompt") or "").lower() == "else":
                tc["prompt"] = "Else"

# Remove unused built-in Cal tools (flow uses custom get_available_slots / book_slot)
cf["tools"] = [
    t
    for t in cf["tools"]
    if t.get("name") not in ("check_availability_cal", "book_appointment_cal")
]

TOOL_DESC = {
    "product_lookup": "Ice cream flavors, ingredients, nutrition, pricing. Pass full customer question as query.",
    "create_ticket": "Create complaint ticket. customer_name, issue_description, priority High/Medium/Low.",
    "get_available_slots": "Check slots for {{start}}–{{end}} (YYYY-MM-DD, end = next day). Use IST system date for relative dates.",
    "book_slot": "Book after {{email}} ready and user confirmed. attendee.name={{customer_name}}, attendee.email={{email}}.",
    "send_whatsapp_email_request": "Send WhatsApp to collect email. Needs customer_name, optional selected_time.",
    "get_booking_email_status": "Poll email session by call_id. Proceed when ready=true and email set.",
}
for t in cf["tools"]:
    name = t.get("name")
    if name in TOOL_DESC:
        t["description"] = TOOL_DESC[name]

# Reduce handbook injection
data["handbook_config"] = {
    "conversational_personality": False,
    "echo_verification": False,
    "speech_normalization": False,
    "default_personality": False,
    "scope_boundaries": False,
    "natural_filler_words": False,
    "nato_phonetic_alphabet": False,
    "high_empathy": False,
    "ai_disclosure": True,
    "smart_matching": False,
}

# Shorten extract-variable descriptions (included in node context)
VAR_DESC = {
    "customer_name": "Caller full name if given; reuse session value.",
    "issue_description": "One-sentence complaint summary.",
    "start": "Appointment day YYYY-MM-DD.",
    "end": "Day after start YYYY-MM-DD.",
    "selected_time": "Customer's chosen time (e.g. 4 PM).",
}
for node in cf["nodes"]:
    for v in node.get("variables") or []:
        n = v.get("name")
        if n in VAR_DESC:
            v["description"] = VAR_DESC[n]

# Shorten tool parameter descriptions
PARAM_DESC = {
    "query": "Customer's full product question.",
    "priority": "High, Medium, or Low.",
    "issue_description": "Complaint summary.",
    "customer_name": "From {{customer_name}}.",
    "start": "ISO slot time from availability.",
    "eventTypeId": "Cal.com event type ID.",
    "notes": "Notes or N/A.",
    "selected_time": "From {{selected_time}}.",
    "email": "From {{email}}.",
}
for t in cf["tools"]:
    params = (t.get("parameters") or {}).get("properties") or {}
    for pname, pdef in params.items():
        if pname in PARAM_DESC:
            pdef["description"] = PARAM_DESC[pname]
    attendee = params.get("attendee", {}).get("properties", {})
    for pname, pdef in attendee.items():
        if pname == "name":
            pdef["description"] = "{{customer_name}}"

path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

# Report
d = json.loads(path.read_text(encoding="utf-8"))
cf = d["conversationFlow"]
gp = cf["global_prompt"]
node_chars = sum(len((n.get("instruction") or {}).get("text") or "") for n in cf["nodes"])
finetune = sum(
    len(tr.get("content") or "")
    for n in cf["nodes"]
    for ex in n.get("finetune_transition_examples") or []
    for tr in ex.get("transcript") or []
)
tool_chars = sum(len(t.get("description") or "") for t in cf["tools"])
est = (len(gp) + node_chars + finetune + tool_chars) // 4
print(f"global_prompt: {len(gp)} chars")
print(f"node instructions: {node_chars} chars")
print(f"finetune: {finetune} chars")
print(f"tool descs: {tool_chars} chars")
print(f"rough static estimate: ~{est} tokens (excl. history/handbook)")
