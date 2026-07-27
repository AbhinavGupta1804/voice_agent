"""
Transform "New Claude Agent (14).json" -> "New Claude Agent (15).json".

Goals (from user):
- Remove the RAG / product_lookup ("ice cream flavour") tool, its nodes and all
  product/flavour routing edges.
- Stop the agent from ever speaking raw tool output / JSON / ISO timestamps:
  convert the "Map time to slot" conversation node into a silent
  extract_dynamic_variables node, and drop the redundant "Convert date" node.
- Cut token bloat (huge finetune example lists + global prompt) so tool calling
  and answers are fast and don't hit the 4500ms first-token timeout.
"""

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.normpath(os.path.join(HERE, "..", "docs", "New Claude Agent (14).json"))
DST = os.path.normpath(os.path.join(HERE, "..", "docs", "New Claude Agent (15).json"))

with open(SRC, "r", encoding="utf-8") as f:
    data = json.load(f)

cf = data["conversationFlow"]
nodes = cf["nodes"]
tools = cf["tools"]

# ---------------------------------------------------------------------------
# IDs we are removing / changing
# ---------------------------------------------------------------------------
PRODUCT_TOOL_ID = "tool-1774698838217"          # product_lookup (RAG)
PRODUCT_NODES = {
    "node-1774698840567",   # Product Lookup (function)
    "node-1774879761276",   # Conversation: speak product info
    "node-1774879382888",   # Conversation: flavour not found
}
REDUNDANT_NODES = {
    "node-1775319880576",   # Conversation: convert date to JSON (redundant, was spoken)
}
DELETED_NODES = PRODUCT_NODES | REDUNDANT_NODES

MAP_TIME_NODE = "node-1775363299525"            # Map time to slot (-> becomes extract)
ASK_DATE_NODE = "node-1774699912789"            # Ask Date & Time
EXTRACT_START_END_NODE = "node-1774699962185"   # Extract start/end (date)

# ---------------------------------------------------------------------------
# 1. Remove the product_lookup tool
# ---------------------------------------------------------------------------
cf["tools"] = [t for t in tools if t.get("tool_id") != PRODUCT_TOOL_ID]

# ---------------------------------------------------------------------------
# 2. Remove deleted nodes
# ---------------------------------------------------------------------------
nodes = [n for n in nodes if n.get("id") not in DELETED_NODES]

# ---------------------------------------------------------------------------
# 3. Reroute edges that pointed into deleted nodes
#    - Ask Date -> (was Convert date) -> now straight to Extract start/end
#    - Any other edge into a deleted node is simply dropped
# ---------------------------------------------------------------------------
ROUTE_PRODUCT_WORDS = ("product", "flavor", "flavour", "menu", " price")


def is_product_route(edge):
    p = edge.get("transition_condition", {}).get("prompt", "").lower()
    return any(w in p for w in ROUTE_PRODUCT_WORDS)


def fix_edges(node):
    new_edges = []
    for e in node.get("edges", []):
        dest = e.get("destination_node_id")
        if dest in REDUNDANT_NODES:
            # convert-date was always followed by extract start/end
            e["destination_node_id"] = EXTRACT_START_END_NODE
            new_edges.append(e)
        elif dest in PRODUCT_NODES:
            # drop product/flavour edges entirely
            continue
        elif is_product_route(e):
            # drop leftover product-intent routing edges (e.g. welcome node)
            continue
        else:
            new_edges.append(e)
    node["edges"] = new_edges

    # else_edge handling
    ee = node.get("else_edge")
    if ee:
        dest = ee.get("destination_node_id")
        if dest in REDUNDANT_NODES:
            ee["destination_node_id"] = EXTRACT_START_END_NODE
        elif dest in PRODUCT_NODES:
            # point a now-dangling else to "Anything Else" as a safe fallback
            ee["destination_node_id"] = "node-1775429325981"

for n in nodes:
    fix_edges(n)

# ---------------------------------------------------------------------------
# 4. Convert "Map time to slot" conversation node -> silent extract node
#    so it never speaks the JSON timestamp out loud.
# ---------------------------------------------------------------------------
for n in nodes:
    if n.get("id") == MAP_TIME_NODE:
        n.pop("instruction", None)
        n["type"] = "extract_dynamic_variables"
        n["name"] = "Map Time To Slot"
        n["variables"] = [
            {
                "name": "selected_start",
                "type": "string",
                "description": (
                    "The exact ISO 8601 timestamp from the get_available_slots list "
                    "that matches the customer's chosen time ({{selected_time}}). "
                    "Copy the timestamp string EXACTLY as returned by the tool "
                    "(e.g. 2026-07-02T10:00:00.000+05:30). Do not invent, round, or "
                    "reformat it. Never say this value out loud."
                ),
            }
        ]
        # keep the two outgoing edges (name set -> send WA, name not set -> ask name)
        n["else_edge"] = {
            "id": "node-1775363299525-else-edge",
            "transition_condition": {"type": "prompt", "prompt": "Else"},
            "destination_node_id": "node-1775362969761",  # back to show slots
        }
        n["finetune_transition_examples"] = [
            {
                "id": "fe-mapslot-10am",
                "transcript": [
                    {"content": "the ten AM one", "role": "user"},
                    {
                        "content": "{ \"selected_start\": \"2026-07-02T10:00:00.000+05:30\" }",
                        "role": "agent",
                    },
                ],
            }
        ]
        break

# ---------------------------------------------------------------------------
# 5. Trim finetune examples (huge token bloat) and drop product/flavour ones.
# ---------------------------------------------------------------------------
PRODUCT_WORDS = (
    "flavor", "flavour", "ice cream", "icecream", "pista", "mango", "chocolate",
    "vanilla", "coconut", "strawberry", "kulfi", "tub", "rupees", "discount",
    "price", "product", "menu", "black currant", "almond", "sitaphal",
    "tender coconut",
)
MAX_EXAMPLES = 2  # per node


def is_product_example(ex):
    for turn in ex.get("transcript", []):
        c = turn.get("content", "").lower()
        if any(w in c for w in PRODUCT_WORDS):
            return True
    return False


for n in nodes:
    exs = n.get("finetune_transition_examples")
    if not exs:
        continue
    kept = [e for e in exs if not is_product_example(e)]
    n["finetune_transition_examples"] = kept[:MAX_EXAMPLES]

# ---------------------------------------------------------------------------
# 6. New, lean global prompt (no product flow; hard rule against speaking JSON)
# ---------------------------------------------------------------------------
cf["global_prompt"] = (
    "You are Neha, phone support for Naturals Ice Cream (India). English only.\n\n"
    "Tone: calm, friendly and steady, like a real human support agent on a call. "
    "Not over-excited or salesy. Keep replies short. At most one light filler "
    "(okay, sure, alright) when it feels natural.\n\n"
    "HARD RULE: Never say JSON, tool names, variable names, raw tool output, or "
    "ISO timestamps out loud. Always speak times naturally (e.g. 3 PM, 10 in the "
    "morning). If you receive raw data, just summarise it in plain words.\n\n"
    "Variables: {{customer_name}} is used for tickets and bookings. {{email}} only "
    "ever comes from WhatsApp, never ask for email on the call.\n\n"
    "You help with two things: (1) complaints -> create a ticket, and (2) "
    "appointments / manager meetings -> booking. You do NOT answer product, "
    "flavour, price or menu questions; if asked, politely say you can only help "
    "with complaints and appointments.\n\n"
    "Complaints: if {{customer_name}} is set, reuse it; otherwise ask the name "
    "once. Then create_ticket and tell them the ticket number naturally.\n\n"
    "Booking (today's date/time is in the system context, IST, no date tool):\n"
    "1. Ask the preferred date.\n"
    "2. Call get_available_slots, then offer only the times it returns.\n"
    "3. Caller picks a time.\n"
    "4. Call send_whatsapp_email_request, ask them to reply on WhatsApp with their "
    "email, then check get_booking_email_status until {{email}} is ready.\n"
    "5. Confirm the details, then book_slot, only after they confirm and {{email}} "
    "is set.\n\n"
    "After any tool: reply briefly in plain language and keep moving. On failure, "
    "apologise once and retry or re-ask. Do not repeat yourself.\n\n"
    "If asked how to reach us or for a callback: they can call this same number "
    "anytime.\n\n"
    "Misconduct: warn once, then end the call. After each task, ask if there is "
    "anything else."
)

# ---------------------------------------------------------------------------
# 7. Sanity: ensure no remaining references to deleted nodes
# ---------------------------------------------------------------------------
node_ids = {n["id"] for n in nodes}
dangling = []
for n in nodes:
    for e in n.get("edges", []):
        d = e.get("destination_node_id")
        if d and d not in node_ids:
            dangling.append((n["id"], d))
    ee = n.get("else_edge")
    if ee:
        d = ee.get("destination_node_id")
        if d and d not in node_ids:
            dangling.append((n["id"], "else->" + d))

cf["nodes"] = nodes

with open(DST, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print("Wrote:", DST)
print("Nodes:", len(nodes), "| Tools:", [t["name"] for t in cf["tools"]])
if dangling:
    print("WARNING dangling edges:", dangling)
else:
    print("No dangling edges. OK")
