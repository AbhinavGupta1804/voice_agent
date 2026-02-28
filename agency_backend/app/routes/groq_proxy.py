"""Routes for Groq OpenAI-compatible API proxy."""
import logging
import json
import uuid
import time
import asyncio
import queue
import threading
from typing import Optional, List, Dict, Any, Union

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from groq import Groq, AsyncGroq

from ..config import Config
from ..utils.active_calls import get_latest_call_sid

logger = logging.getLogger(__name__)

# ============== Groq Configuration ==============

GROQ_API_KEY = Config.GROQ_API_KEY if hasattr(Config, "GROQ_API_KEY") else None
groq_client: Optional[Groq] = None
groq_client_async: Optional[AsyncGroq] = None
GROQ_MODEL = "moonshotai/kimi-k2-instruct-0905"

if GROQ_API_KEY:
    groq_client = Groq(api_key=GROQ_API_KEY)
    groq_client_async = AsyncGroq(api_key=GROQ_API_KEY)
    logger.info("[Groq] Groq clients (sync & async) initialized for OpenAI proxy")
else:
    logger.warning("[Groq] GROQ_API_KEY not found - OpenAI proxy endpoints will be disabled")

# Default System Prompt for TravelBuddy AI Agent (Hindi)
TRAVELBUDDY_SYSTEM_PROMPT = """
You are Neha, a friendly customer support voice agent for Naturals Ice Cream, serving Indian customers. Speak only in Hinglish (casual Hindi mixed with English) — natural, conversational, polite, and human-like. Avoid formal Hindi or pure English.
Core Responsibilities
Quickly understand customer intent (product query, complaint, delivery/service issue, appointment request, general info).
Keep responses short, conversational, and clear for voice interaction.
Use occasional natural filler phrases (e.g., hmm, acha, okay, umm, ah) to sound human, but don't overuse them.
Always acknowledge the customer's concern before responding.
Always end with a clear next step (info provided, ticket raised, appointment booked, etc.).
Call Ending Rules
When the customer says goodbye, thank you, bye, or indicates they want to end:
1. FIRST respond with a warm goodbye message using final_answer (e.g., "Thank you for calling Naturals Ice Cream! Aapka din shubh ho.").
2. On the VERY NEXT turn (when customer confirms or says bye again), call end_call tool to hang up.
3. If customer says just "bye" or "thank you bye" with nothing else needed, you can call end_call directly.
Tool Usage Rules
Product/service queries → Call product_lookup first, then respond strictly using returned info.
Complaints, delivery issues, dissatisfaction →
First politely ask the customer's name.
Do NOT ask for phone number — it is already captured from incoming call metadata.
After getting the name, call create_ticket.
Confirm politely that the support ticket has been created.
Appointment booking (manager/support):
Ask preferred date/time first.
Call get_available_slots with the date.
The response will include [SLOT_DATA] with ISO timestamps like "09:00 AM=2026-03-02T09:00:00.000Z".
When customer picks a slot, use the exact ISO timestamp from SLOT_DATA for book_slot.
Ask for customer's name and email before calling book_slot.
Call book_slot with: start (ISO timestamp), name, email.
If no slots available → suggest trying another date.
Irrelevant / Out-of-Scope Requests
If the customer asks for unrelated items (e.g., butter chicken or non-ice-cream products/services):
Politely clarify that Naturals Ice Cream only handles ice cream products and related services.
Offer help with relevant queries instead.
Misconduct / Call Termination Rules
If the customer:
Uses abusive language,
Makes sexual/inappropriate remarks,
Is clearly wasting time, trolling, or not engaging meaningfully:
Respond politely once stating:
The discussion is not appropriate or productive.
You are respectfully ending the call.
Then end the interaction.
Behavioral Guardrails
Never guess product details — always use tools.
Never ignore complaints — always create a ticket.
STAY HUMBLE AND CALM. Do not be overly expressive or enthusiastic.
STRICTLY do not guess or hallucinate any names. If the customer hasn't explicitly said their name, you MUST ask using final_answer FIRST before calling create_ticket.
Do not engage in arguments, jokes on sensitive topics, or inappropriate discussions.
Example Conversations (Hinglish Voice Style)
Product Query
Customer: Mango ice cream available hai kya?
Neha: Ji haan, ek sec check karti hoon.
Customer: Okay.
Neha: Hmm... acutally Sir,Mango flavour available hai aur seasonal offer bhi chal raha hai.
Product Query (Calories)
Customer: Watermelon mein kitni calories hain?
Neha: Ek second Sir, check karti hoon... Watermelon ice cream mein 100g mein 110 calories hain.
Product Query (Ingredients)
Customer: Kaju Draksh mein kya kya ingredients hain?
Neha: Hmm, dekhti hoon... Kaju Draksh mein cashew, raisins, milk solids aur sugar hai Sir.
Product Query (Flavours)
Customer: Kya kya flavours hain aapke paas?
Neha: Ek second... Sir humare paas Mango, Tender Coconut, Sitaphal, Chicku, aur bahut saare flavours hain.
Complaint / Ticket
Customer: Ice cream melted deliver hui thi.
Neha: Oh sorry about that, umm... ek second Sir , ticket create karne se pehle aapka naam bata denge?
Customer: Ajay.
Neha: Acha Ajayji, maine aapke liye ticket raise kar diya hai. Number already system mein, team aapse faata faat contact karegi.
Appointment Booking
Customer: Manager se baat karni hai.
Neha: Okay Sir, kis date pe appointment chahiye?
Customer: Kal.
Neha: Hmm... ek second Sir, check karti hoon slots… acha 9 AM, 10 AM, 11 AM available hai. Konsa time theek rahega?
Customer: 10 baje.
Neha: Okay 10 AM. Booking ke liye aapka naam aur email chahiye.
Customer: Rahul, rahul@gmail.com
Neha: Done Sir, appointment book ho gayi. Confirmation email aa jayega.
Irrelevant Request
Customer: Butter chicken milega?
Neha: Umm acha Sir, hum sirf ice cream products handle karte hain. Ice cream related help chahiye ho toh bataiye.
Abusive / Inappropriate
Customer: (Abusive/sexual remark)
Neha: Acha, lagta hai discussion meaningful nahi ho raha. Main respectfully call end kar rahi hoon. Thank you.

## VOICE PACING
- Use SHORT sentences (max 10-15 words each).
- Add natural pauses using commas and periods.
- Do NOT dump long paragraphs — break into small spoken phrases.
- Example: "Haan ji. Ek second. Main check karti hoon." (3 short sentences, NOT one long one)

## RESPONSE FORMAT (CRITICAL — MUST FOLLOW)
Your ENTIRE response must be a SINGLE VALID JSON object.
Do NOT write any text before or after the JSON.
Do NOT describe the tool call in words.
Do NOT say "I will call product_lookup" — just output the JSON.

### When a tool call is needed:
{{"tool_call": {{"name": "TOOL_NAME", "arguments": {{...}}}}}}

Example: {{"tool_call": {{"name": "product_lookup", "arguments": {{"query": "mango ice cream ingredients"}}}}}}

### When NO tool is needed (normal conversation):
{{"final_answer": "your Hinglish response here"}}

Example: {{"final_answer": "Haan ji, bataiye kya help chahiye?"}}

### RULES:
1. Output ONLY valid JSON — no explanation, no markdown, no extra text.
2. NEVER describe the tool call in words. ONLY output JSON.
3. Before calling create_ticket, you MUST have customer_name. NEVER hallucinate a name like Priya or Ajay. If missing, use final_answer to ask.
4. Priority: High = very upset/urgent, Low = minor feedback, default Medium.
5. Never make up product information — always call product_lookup.
6. Always speak in Hinglish. Never switch to pure English.
""".strip()


# ============== Pydantic Models for OpenAI-compatible API ==============

class ChatMessage(BaseModel):
    role: str  # system, user, assistant
    content: str
    name: Optional[str] = None


class ChatCompletionRequest(BaseModel):
    # we ignore user-provided model and force GROQ_MODEL
    model: str = GROQ_MODEL
    messages: List[ChatMessage]
    temperature: Optional[float] = Field(default=1.0, ge=0, le=2)
    top_p: Optional[float] = Field(default=1.0, ge=0, le=1)
    n: Optional[int] = Field(default=1, ge=1, le=10)
    stream: Optional[bool] = False
    stop: Optional[Union[str, List[str]]] = None
    max_tokens: Optional[int] = 300
    max_completion_tokens: Optional[int] = 300
    presence_penalty: Optional[float] = Field(default=0, ge=-2, le=2)
    frequency_penalty: Optional[float] = Field(default=0, ge=-2, le=2)
    user: Optional[str] = None
    tools: Optional[List[Dict[str, Any]]] = None
    tool_choice: Optional[Union[str, Dict[str, Any]]] = None
    
    class Config:
        extra = "allow"  # Accept extra fields from ElevenLabs


class ChatCompletionChoice(BaseModel):
    index: int
    message: Dict[str, Any]
    logprobs: Optional[Any] = None
    finish_reason: str


class ChatCompletionUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[ChatCompletionChoice]
    usage: ChatCompletionUsage
    system_fingerprint: Optional[str] = None
    service_tier: Optional[str] = "default"


# ============== Groq Helper Functions ==============

def generate_completion_id() -> str:
    """Generate a unique completion ID in OpenAI format."""
    return f"chatcmpl-{uuid.uuid4().hex[:29]}"


def convert_messages_to_groq(messages: List[ChatMessage]) -> List[Dict[str, str]]:
    """Convert our Message model into Groq/OpenAI chat message dicts.
    If no system prompt is provided, inject TravelBuddy system prompt.
    """
    out: List[Dict[str, str]] = []
    has_system = any(m.role == "system" for m in messages)
    if not has_system:
        out.append({"role": "system", "content": TRAVELBUDDY_SYSTEM_PROMPT})

    for m in messages:
        # Keep role/content only (Groq supports system/user/assistant)
        out.append({"role": m.role, "content": m.content})

    return out


def _sanitize_tool_choice(tool_choice: Optional[Union[str, Dict[str, Any]]]) -> Optional[str]:
    """
    Convert tool_choice to Groq-compatible format.
    
    ElevenLabs/OpenAI sends: {"type": "function", "function": {"name": "..."}}
    Groq only accepts strings: "none", "auto", "required"
    """
    if tool_choice is None:
        return None
    if isinstance(tool_choice, str):
        # Already a string — "none", "auto", "required" are valid
        if tool_choice in ("none", "auto", "required"):
            return tool_choice
        return "auto"  # fallback for unknown strings
    if isinstance(tool_choice, dict):
        # Object format → convert to "auto" (Groq doesn't support object format)
        logger.info(f"[Groq Proxy] Converting tool_choice object to 'auto': {tool_choice}")
        return "auto"
    return None


def estimate_tokens(text: str) -> int:
    """Rough estimation of tokens (4 chars per token average)."""
    return max(1, len(text) // 4)


def _truncate_messages_for_log(messages: list) -> list:
    """
    Truncate system prompts for logging - show only first and last 2 lines.
    Non-system messages are shown in full (up to 500 chars).
    """
    truncated = []
    for msg in messages:
        if msg.get("role") == "system":
            content = msg.get("content", "")
            lines = content.split("\n")
            if len(lines) > 6:
                first_lines = "\n".join(lines[:2])
                last_lines = "\n".join(lines[-2:])
                truncated_content = f"{first_lines}\n... [{len(lines)-4} lines omitted] ...\n{last_lines}"
            else:
                truncated_content = content[:300]
            truncated.append({"role": "system", "content": truncated_content})
        else:
            content = msg.get("content", "")
            if len(content) > 500:
                content = content[:500] + "..."
            truncated.append({"role": msg.get("role"), "content": content})
    return truncated


# ============== Custom Tool Dispatcher (for Custom LLM voice calls) ==============
import re

# Import tool modules
from ..tools import create_ticket as create_ticket_tool
from ..tools import product_lookup as product_lookup_tool
from ..tools import get_available_slots as get_available_slots_tool
from ..tools import book_slot as book_slot_tool
from ..tools import end_call as end_call_tool

# Registry: tool_name → module (each module has TOOL_DEFINITION, validate, execute)
TOOL_REGISTRY = {
    "create_ticket": create_ticket_tool,
    "product_lookup": product_lookup_tool,
    "get_available_slots": get_available_slots_tool,
    "book_slot": book_slot_tool,
    "end_call": end_call_tool,
}

# Hold messages for each tool (spoken while tool executes)
# Tools not listed here get a generic hold message.
TOOL_HOLD_MESSAGES = {
    "product_lookup": "Main aapke liye jaankari check karti hoon, ek second... ",
    "create_ticket": "Main aapka ticket bana rahi hoon, ek second... ",
    "get_available_slots": "Ek second, available slots check karti hoon... ",
    "book_slot": "Booking kar rahi hoon, ek second... ",
    "end_call": "",  # No hold message — call ends silently
}
DEFAULT_HOLD_MSG = "Ek second, main check karti hoon... "


def _build_unified_prompt() -> str:
    """Append tool definitions to TRAVELBUDDY_SYSTEM_PROMPT."""
    tool_descriptions = []
    for name, module in TOOL_REGISTRY.items():
        defn = module.TOOL_DEFINITION
        params = defn["parameters"]
        param_lines = []
        for pname, pinfo in params.items():
            req = " (REQUIRED)" if pinfo.get("required") else ""
            param_lines.append(f'     "{pname}": "{pinfo["type"]}{req} — {pinfo["description"]}"')
        param_block = ",\n".join(param_lines)
        tool_descriptions.append(
            f'- **{name}**: {defn["description"]}\n'
            f'  Arguments: {{\n{param_block}\n  }}'
        )

    tools_text = "\n\n".join(tool_descriptions)

    return f"""{TRAVELBUDDY_SYSTEM_PROMPT}

## Available Tools:

{tools_text}
""".strip()


UNIFIED_SYSTEM_PROMPT = _build_unified_prompt()

TOOL_RESULT_PROMPT = """
You are Neha, customer support voice agent for Naturals Ice Cream (Hinglish).
A tool was just executed. The result is below.
Generate a short, warm, conversational response for the customer based on the result.
Respond ONLY as JSON: {"final_answer": "your response"}
""".strip()


def _parse_tool_json(text: str) -> Optional[Dict[str, Any]]:
    """Robustly extract JSON from LLM output."""
    text = text.strip()
    
    # Try 1: direct parse
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass
        
    # Try 2: markdown fences
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        try:
            return json.loads(fence.group(1))
        except (json.JSONDecodeError, ValueError):
            pass
            
    # Try 3: first {...} block
    brace = re.search(r"\{.*\}", text, re.DOTALL)
    if brace:
        try:
            return json.loads(brace.group(0))
        except (json.JSONDecodeError, ValueError):
            pass
            
    # Try 4: Handle partial/broken JSON by closing braces (common in streaming or truncation)
    if text.startswith("{") and not text.endswith("}"):
        try:
            return json.loads(text + "}")
        except:
            pass
            
    logger.error(f"[Tool Dispatcher] JSON parse failed: {text[:200]}")
    return None


async def _call_groq_plain(messages: List[Dict[str, str]], temperature: float = 0) -> str:
    """Call Groq with plain messages (no tools), return raw text."""
    def _sync():
        try:
            resp = groq_client.chat.completions.create(
                model=GROQ_MODEL,
                messages=messages,
                temperature=temperature,
                max_completion_tokens=400,
                stream=False,
            )
            return resp.choices[0].message.content or ""
        except Exception as e:
            # Some models (e.g. gpt-oss-20b) trigger native tool calling
            # even without tools passed. Groq returns the generated text
            # in the error's failed_generation field — extract it.
            err_str = str(e)
            if "tool_use_failed" in err_str and "failed_generation" in err_str:
                import re as _re
                match = _re.search(r"'failed_generation':\s*'(.*?)'", err_str)
                if match:
                    logger.info(f"[Groq Plain] Recovered tool call from failed_generation")
                    return match.group(1)
            raise
    return await asyncio.to_thread(_sync)


def _process_analyze_output(raw: str, last_user_msg: str) -> dict:
    """Consolidated logic to turn LLM raw output into a decision dict."""
    # Parse JSON
    parsed = _parse_tool_json(raw)
    if parsed is None or not isinstance(parsed, dict):
        logger.warning(f"[Tool Dispatcher] JSON parse failed or not a dict, checking for plain-text patterns in raw: {raw[:200]}")
        
        # 1. Regex to extract content from labeled plain text (e.g. final_answer: "Hello")
        # Matches "final_answer": "text", 'final_answer': 'text', final_answer: text, final ans: text etc.
        label_match = re.search(r'(?:final_answer|final_ans|final ans|answer)\s*[:=]\s*["\']?(.*?)["\']?$', raw, re.IGNORECASE | re.DOTALL)
        if label_match:
            extracted_text = label_match.group(1).strip()
            # Clean up trailing braces/quotes if any residual JSON artifacts exist
            extracted_text = re.sub(r'["\'\}]+$', '', extracted_text).strip()
            if extracted_text:
                logger.info(f"[Tool Dispatcher] Recovered final_answer via regex: {extracted_text}")
                return {"type": "final_answer", "text": extracted_text}

        # 2. Detect if LLM described a tool call in plain text instead of JSON
        #    Check ALL registered tools generically so no tool leaks as speech.
        raw_lower = raw.lower()
        for tool_name_key in TOOL_REGISTRY:
            # Match both "tool_name" and "tool name" (underscore → space)
            if tool_name_key in raw_lower or tool_name_key.replace("_", " ") in raw_lower:
                logger.info(f"[Tool Dispatcher] Detected plain-text {tool_name_key}, converting to tool_call")
                # For tools that need specific arguments, try to extract from raw text or use user msg
                if tool_name_key == "product_lookup":
                    return {"type": "tool_call", "name": "product_lookup", "args": {"query": last_user_msg}}
                elif tool_name_key == "get_available_slots":
                    # Try to extract date from user message
                    return {"type": "tool_call", "name": "get_available_slots", "args": {"date": last_user_msg}}
                elif tool_name_key == "create_ticket":
                    # Can't create ticket without name — ask first
                    return {"type": "final_answer", "text": "Aap apna naam bata dijiye, phir main aapka ticket bana deti hoon."}
                elif tool_name_key == "end_call":
                    return {"type": "tool_call", "name": "end_call", "args": {}}
                elif tool_name_key == "book_slot":
                    # book_slot needs structured args — ask the LLM to retry
                    return {"type": "final_answer", "text": "Booking ke liye aapka naam, email aur time confirm kar dijiye."}
                else:
                    # Generic fallback for any future tools
                    return {"type": "tool_call", "name": tool_name_key, "args": {}}
        
        # 3. Fallback: return raw text but clean it of common "internal" markers
        #    Also strip any residual tool-call / JSON artifacts so internal
        #    implementation details are NEVER spoken to the customer.
        clean_text = raw.strip()
        # Remove common prefixes like final_answer: or final_ans:
        clean_text = re.sub(r'^(?:final_answer|final_ans|final ans|answer)\s*[:=]\s*', '', clean_text, flags=re.IGNORECASE)
        # Remove surrounding braces and quotes if it's "broken" JSON
        clean_text = clean_text.strip('{}"\' ')
        
        # Safety: strip any residual tool names / JSON keys that should never be spoken
        for tool_name_key in TOOL_REGISTRY:
            clean_text = clean_text.replace(tool_name_key, "").replace(tool_name_key.replace("_", " "), "")
        clean_text = re.sub(r'\b(tool_call|tool call|arguments|final_answer)\b', '', clean_text, flags=re.IGNORECASE)
        clean_text = re.sub(r'[\s,]+', ' ', clean_text).strip(' ,:"\'')
        
        if not clean_text or len(clean_text) < 3:
            clean_text = "Ji, bataiye main kaise help kar sakti hoon?"
        
        return {"type": "final_answer", "text": clean_text}

    # Final answer — normal conversation
    if "final_answer" in parsed:
        return {"type": "final_answer", "text": parsed["final_answer"]}

    # Tool call detected — will be executed in Phase 2
    if "tool_call" in parsed:
        tc = parsed["tool_call"]
        return {"type": "tool_call", "name": tc.get("name", ""), "args": tc.get("arguments", {})}

    # Some models (e.g. gpt-oss-20b) return bare {"name": "...", "arguments": {...}}
    if "name" in parsed and "arguments" in parsed:
        return {"type": "tool_call", "name": parsed["name"], "args": parsed["arguments"]}

    logger.warning(f"[Tool Dispatcher] Unknown response format: {parsed}")
    return {"type": "final_answer", "text": parsed.get("response", parsed.get("message", "Could you repeat that?"))}


async def _analyze_request(request_messages: List[ChatMessage]) -> dict:
    """
    Phase 1: LLM call only → returns decision dict.
    NO RAG here — RAG only runs when product_lookup tool is executed.
    
    Returns:
        {"type": "final_answer", "text": "..."} — normal conversation
        {"type": "tool_call", "name": "create_ticket", "args": {...}} — needs tool execution
        {"type": "error", "text": "..."} — error fallback
    """
    import time as _time
    t_start = _time.time()

    logger.info(f"[Tool Dispatcher] ====== ANALYZE START ======")

    # Get last user message for fallback logic
    last_user_msg = ""
    for m in reversed(request_messages):
        if m.role == "user":
            last_user_msg = m.content
            break
    logger.info(f"[Tool Dispatcher] Last user msg: {last_user_msg[:150]}")

    # Build messages
    messages = [{"role": "system", "content": UNIFIED_SYSTEM_PROMPT}]
    for m in request_messages:
        if m.role == "system":
            continue
        messages.append({"role": m.role, "content": m.content})

    # Single LLM call
    try:
        t1 = _time.time()
        logger.info(f"[Tool Dispatcher] Calling Groq (Non-Streaming)...")
        raw = await _call_groq_plain(messages)
        llm_time = (_time.time() - t1) * 1000
        logger.info(f"[Tool Dispatcher] Groq DONE ({llm_time:.0f}ms)")
        logger.info(f"[Tool Dispatcher] LLM output: {raw[:500]}")
    except Exception as e:
        logger.error(f"[Tool Dispatcher] Groq FAILED: {type(e).__name__}: {e}", exc_info=True)
        return {"type": "error", "text": "Sorry, main abhi respond nahi kar paa rahi."}

    decision = _process_analyze_output(raw, last_user_msg)
    elapsed = (_time.time() - t_start) * 1000
    
    if decision["type"] == "tool_call":
        logger.info(f"[Tool Dispatcher] → TOOL CALL: {decision['name']} [{elapsed:.0f}ms]")
    else:
        logger.info(f"[Tool Dispatcher] → FINAL ANSWER [{elapsed:.0f}ms]")
        
    return decision


async def _execute_tool(tool_name: str, tool_args: dict, call_sid: str = None) -> str:
    """
    Phase 2: Execute a tool and return the result message.
    For product_lookup: gets RAG chunks → summarizes via LLM.
    For create_ticket: returns result message directly.
    For end_call: terminates the call via Twilio API.
    """
    import time as _time

    tool_module = TOOL_REGISTRY.get(tool_name)
    if not tool_module:
        logger.error(f"[Tool Dispatcher] UNKNOWN TOOL: '{tool_name}'")
        return f"Sorry, I don't have a tool called {tool_name}."

    try:
        t_exec = _time.time()
        logger.info(f"[Tool Dispatcher] Executing {tool_name}...")
        # end_call needs call_sid as extra parameter
        if tool_name == "end_call":
            tool_result = await tool_module.execute(tool_args, call_sid=call_sid)
        else:
            tool_result = await tool_module.execute(tool_args)
        exec_time = (_time.time() - t_exec) * 1000
        logger.info(f"[Tool Dispatcher] {tool_name} DONE ({exec_time:.0f}ms)")
        logger.info(f"[Tool Dispatcher] Result: {json.dumps(tool_result, default=str)[:500]}")
    except Exception as e:
        logger.error(f"[Tool Dispatcher] {tool_name} FAILED: {type(e).__name__}: {e}", exc_info=True)
        return "Sorry, kuch problem ho gayi. Please dobara try karein."

    # For book_slot: summarize booking confirmation via quick LLM call
    if tool_name == "book_slot" and tool_result.get("success"):
        try:
            t_sum = _time.time()
            booking_msg = tool_result.get("message", "")
            meeting_url = tool_result.get("meeting_url", "")
            summary_prompt = [
                {"role": "system", "content": (
                    "You are Neha, voice agent for Naturals Ice Cream.\n"
                    "ALWAYS respond in Hindi or Hinglish. NEVER use pure English.\n"
                    "Be calm, professional, warm. The booking was successful.\n"
                    "Confirm the booking in a SHORT, friendly response (1-2 sentences).\n"
                    "If there's a meeting URL, mention it will be sent via email.\n"
                    "Respond as plain text, NOT JSON."
                )},
                {"role": "user", "content": f"Booking result: {booking_msg}"},
            ]
            logger.info(f"[Tool Dispatcher] Summarizing booking via Groq...")
            summary = await _call_groq_plain(summary_prompt)
            sum_time = (_time.time() - t_sum) * 1000
            logger.info(f"[Tool Dispatcher] Booking summary DONE ({sum_time:.0f}ms): {summary[:200]}")
            return summary.strip()
        except Exception as e:
            logger.error(f"[Tool Dispatcher] Booking summary FAILED: {e}", exc_info=True)
            return tool_result["message"]

    # For get_available_slots: generate voice response but keep ISO timestamps for context
    if tool_name == "get_available_slots" and tool_result.get("success") and tool_result.get("slots"):
        try:
            t_sum = _time.time()
            slots = tool_result["slots"]
            # slots is now list of {"readable": "05:00 PM", "iso": "2026-03-02T17:00:00.000Z"}
            if slots and isinstance(slots[0], dict):
                slots_readable = tool_result.get("slots_readable") or ", ".join(s.get("readable", str(s)) for s in slots)
                # Build mapping for LLM to use when booking
                slot_mapping = " | ".join([f"{s['readable']}={s['iso']}" for s in slots[:6]])  # Limit to 6 for brevity
            else:
                slots_readable = ", ".join(str(s) for s in slots)
                slot_mapping = slots_readable
            
            summary_prompt = [
                {"role": "system", "content": (
                    "You are Neha, voice agent for Naturals Ice Cream.\n"
                    "ALWAYS respond in Hindi or Hinglish. NEVER use pure English.\n"
                    "Be calm, professional, to-the-point. No extra enthusiasm.\n"
                    "Tell the customer the available time slots in a SHORT response (1-2 sentences).\n"
                    "Ask which slot they'd like to book.\n"
                    "PRONUNCIATION RULES for Voice:\n"
                    "- Expand numbers to words (e.g., '5' -> 'paanch').\n"
                    "- Use 12-hour format with AM/PM.\n"
                    "Respond as plain text, NOT JSON."
                )},
                {"role": "user", "content": f"Available slots: {slots_readable}"},
            ]
            logger.info(f"[Tool Dispatcher] Summarizing slots via Groq...")
            summary = await _call_groq_plain(summary_prompt)
            sum_time = (_time.time() - t_sum) * 1000
            logger.info(f"[Tool Dispatcher] Slots summary DONE ({sum_time:.0f}ms): {summary[:200]}")
            
            # Return voice summary + ISO mapping for LLM context (hidden from speech)
            # Format: [VOICE]summary[/VOICE][SLOT_DATA]mapping[/SLOT_DATA]
            return f"{summary.strip()}\n\n[SLOT_DATA for book_slot: {slot_mapping}]"
        except Exception as e:
            logger.error(f"[Tool Dispatcher] Slots summary FAILED: {e}", exc_info=True)
            return tool_result.get("slots_readable", tool_result["message"])

    # For product_lookup: summarize RAG chunks via quick LLM call
    if tool_name == "product_lookup" and tool_result.get("success") and tool_result.get("chunks"):
        try:
            t_sum = _time.time()
            rag_data = tool_result["message"]
            summary_prompt = [
                {"role": "system", "content": (
                    "You are Neha, voice agent for Naturals Ice Cream.\n"
                    "ALWAYS respond in Hindi or Hinglish. NEVER use pure English.\n"
                    "Be calm, professional, to-the-point. No extra enthusiasm.\n"
                    "Summarize the product data into a SHORT response (1-2 sentences).\n"
                    "Only mention what the customer asked about.\n"
                    "PRONUNCIATION RULES for Voice:\n"
                    "- Expand numbers to words (e.g., '179' -> 'one hundred seventy nine').\n"
                    "- Expand units to full words (e.g., 'kcal' -> 'calories', 'g' -> 'gram protein').\n"
                    "Respond as plain text, NOT JSON."
                )},
                {"role": "user", "content": f"Customer asked: {tool_args.get('query', '')}\n\nProduct data:\n{rag_data}"},
            ]
            logger.info(f"[Tool Dispatcher] Summarizing product data via Groq...")
            summary = await _call_groq_plain(summary_prompt)
            sum_time = (_time.time() - t_sum) * 1000
            logger.info(f"[Tool Dispatcher] Summary DONE ({sum_time:.0f}ms): {summary[:200]}")
            return summary.strip()
        except Exception as e:
            logger.error(f"[Tool Dispatcher] Summary FAILED: {e}", exc_info=True)
            # Fallback: return first chunk directly
            return tool_result["chunks"][0][:200]

    return tool_result.get("message", "Aapka request process ho gaya hai.")

async def generate_groq_response(
    messages: List[ChatMessage],
    temperature: float = 1.0,
    max_tokens: Optional[int] = None,
    top_p: float = 1.0,
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Generate a non-streaming response using Groq."""
    groq_messages = convert_messages_to_groq(messages)

    def sync_call() -> Dict[str, Any]:
        api_kwargs = {
            "model": GROQ_MODEL,
            "messages": groq_messages,
            "temperature": temperature,
            "max_completion_tokens": max_tokens,
            "top_p": top_p,
            "stream": False,
            "stop": None,
        }
        
        if tools:
            api_kwargs["tools"] = tools
        safe_tool_choice = _sanitize_tool_choice(tool_choice)
        if safe_tool_choice:
            api_kwargs["tool_choice"] = safe_tool_choice
            
        # DEBUG LOGGING
        logger.info(f"[Groq Proxy] Sending request to {GROQ_MODEL}")
        logger.info(f"[Groq Proxy] Tools present: {bool(tools)}")
        import json
        try:
            truncated_msgs = _truncate_messages_for_log(groq_messages)
            logger.info(f"[Groq Proxy] Messages payload: {json.dumps(truncated_msgs, indent=2)}")
        except Exception:
            logger.info(f"[Groq Proxy] Messages count: {len(groq_messages)}")
            
        completion = groq_client.chat.completions.create(**api_kwargs)
        
        # Return the full message object (content + tool_calls)
        msg = completion.choices[0].message
        return {
            "role": msg.role,
            "content": msg.content,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": tc.type,
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments
                    }
                } for tc in msg.tool_calls
            ] if msg.tool_calls else None
        }

    return await asyncio.to_thread(sync_call)


async def generate_groq_stream(
    messages: List[ChatMessage],
    temperature: float = 1.0,
    max_tokens: Optional[int] = None,
    top_p: float = 1.0,
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
):
    """Generate a streaming response using Groq (queue bridge)."""
    groq_messages = convert_messages_to_groq(messages)
    chunk_queue: "queue.Queue[object]" = queue.Queue()

    def stream_to_queue():
        try:
            api_kwargs = {
                "model": GROQ_MODEL,
                "messages": groq_messages,
                "temperature": temperature,
                "max_completion_tokens": max_tokens,
                "top_p": top_p,
                "stream": True,
            }
            # Only add tools/tool_choice if they have values
            if tools:
                api_kwargs["tools"] = tools
            safe_tc = _sanitize_tool_choice(tool_choice)
            if safe_tc:
                api_kwargs["tool_choice"] = safe_tc

            logger.info(f"[Groq Stream] Calling Groq: tools={bool(tools)}, tool_choice={safe_tc}")
            completion = groq_client.chat.completions.create(**api_kwargs)

            for chunk in completion:
                delta = chunk.choices[0].delta
                delta_dict = {}
                if delta.content is not None:
                    delta_dict["content"] = delta.content
                if delta.role is not None:
                    delta_dict["role"] = delta.role
                if delta.tool_calls:
                    delta_dict["tool_calls"] = [
                        {
                            "index": tc.index,
                            "id": tc.id,
                            "type": tc.type,
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments
                            }
                        } for tc in delta.tool_calls
                    ]
                
                if delta_dict:
                    chunk_queue.put(delta_dict)
            chunk_queue.put(None)
        except Exception as e:
            logger.error(f"[Groq Stream] ERROR: {e}", exc_info=True)
            chunk_queue.put(e)

    thread = threading.Thread(target=stream_to_queue, daemon=True)
    thread.start()

    while True:
        item = await asyncio.to_thread(chunk_queue.get)
        if item is None:
            break
        if isinstance(item, Exception):
            raise item
        yield item


# ============== Routes ==============

def register_groq_proxy_routes(app):
    """Register Groq OpenAI-compatible proxy routes."""
    router = APIRouter(tags=["Groq OpenAI Proxy"])

    @router.get("/v1/models")
    async def list_models():
        """List available models (OpenAI compatible)."""
        if not groq_client:
            raise HTTPException(status_code=503, detail="Groq client not configured")
        
        return {
            "object": "list",
            "data": [
                {
                    "id": GROQ_MODEL,
                    "object": "model",
                    "created": int(time.time()),
                    "owned_by": "groq",
                    "permission": [],
                    "root": GROQ_MODEL,
                    "parent": None,
                }
            ]
        }

    @router.post("/v1/chat/completions")
    async def create_chat_completion(request: ChatCompletionRequest):
        """
        Create a chat completion (OpenAI-compatible endpoint).
        Uses Groq Llama 3.3 70B Versatile under the hood.
        """
        if not groq_client:
            raise HTTPException(status_code=503, detail="Groq client not configured")
        
        try:
            completion_id = generate_completion_id()
            created_timestamp = int(time.time())
            max_tokens = request.max_completion_tokens or request.max_tokens
            
            # ── DEBUG LOG: Request Entry ──
            logger.info(f"[Groq Proxy] === INCOMING REQUEST ===")
            logger.info(f"[Groq Proxy] stream={request.stream}, tools={bool(request.tools)}, tool_choice={request.tool_choice}")
            logger.info(f"[Groq Proxy] messages count={len(request.messages)}, max_tokens={max_tokens}")
            active_call_sid = get_latest_call_sid()
            logger.info(f"[Groq Proxy] call_sid={active_call_sid or 'N/A'}")
            for i, m in enumerate(request.messages):
                logger.info(f"[Groq Proxy] msg[{i}] role={m.role} content={m.content[:100]}...")
            
            # ── CUSTOM TOOL CALLING PATH ──
            # When ElevenLabs sends tools, handle them via our dispatcher
            if request.tools:
                logger.info(f"[Groq Proxy] Tools detected → using custom tool dispatcher")

                if request.stream:
                    async def tool_stream():
                        # Phase 1: Streaming Analysis
                        messages = [{"role": "system", "content": UNIFIED_SYSTEM_PROMPT}]
                        last_user_msg = ""
                        for m in request.messages:
                            if m.role == "user":
                                last_user_msg = m.content
                            if m.role == "system":
                                continue
                            messages.append({"role": m.role, "content": m.content})

                        # Role chunk
                        yield f'data: {json.dumps({"id": completion_id, "object": "chat.completion.chunk", "created": created_timestamp, "model": GROQ_MODEL, "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}, "logprobs": None, "finish_reason": None}]})}\n\n'

                        full_raw = ""
                        hold_sent = False
                        is_final_answer = False
                        
                        logger.info(f"[Groq Proxy] Starting Streaming Analysis...")
                        t_start = time.time()

                        try:
                            # Start Phase 1 Stream
                            stream = await groq_client_async.chat.completions.create(
                                model=GROQ_MODEL,
                                messages=messages,
                                temperature=0,
                                max_completion_tokens=400,
                                stream=True,
                            )

                            async for chunk in stream:
                                delta = chunk.choices[0].delta.content or ""
                                full_raw += delta
                                
                                # Fast Detection: detect ANY tool name early to play hold speech.
                                # Uses TOOL_REGISTRY dynamically so new tools are auto-covered.
                                if not hold_sent and not is_final_answer:
                                    if '"final_answer"' in full_raw:
                                        is_final_answer = True
                                    else:
                                        for tname in TOOL_REGISTRY:
                                            # Check for "tool_name" (JSON) or plain text
                                            if f'"{tname}"' in full_raw or tname.replace('_', ' ') in full_raw.lower():
                                                hold_msg = TOOL_HOLD_MESSAGES.get(tname, DEFAULT_HOLD_MSG)
                                                logger.info(f"[Groq Proxy] FAST TOOL DETECT ({(time.time()-t_start)*1000:.0f}ms): {tname}")
                                                if hold_msg:  # Some tools (end_call) have no hold msg
                                                    yield f'data: {json.dumps({"id": completion_id, "object": "chat.completion.chunk", "created": created_timestamp, "model": GROQ_MODEL, "choices": [{"index": 0, "delta": {"content": hold_msg}, "logprobs": None, "finish_reason": None}]})}\n\n'
                                                hold_sent = True
                                                break

                        except Exception as e:
                            logger.error(f"[Groq Proxy] Streaming analysis FAILED: {e}", exc_info=True)
                            yield f'data: {json.dumps({"id": completion_id, "object": "chat.completion.chunk", "created": created_timestamp, "model": GROQ_MODEL, "choices": [{"index": 0, "delta": {"content": "Sorry, kuch technical error ho gaya."}, "logprobs": None, "finish_reason": "stop"}]})}\n\n'
                            return

                        # Phase 1 complete -> Get final decision
                        decision = _process_analyze_output(full_raw, last_user_msg)
                        
                        if decision["type"] == "tool_call":
                            tool_name = decision["name"]
                            # Fallback hold msg if not already sent during streaming
                            if not hold_sent:
                                hold_msg = TOOL_HOLD_MESSAGES.get(tool_name, DEFAULT_HOLD_MSG)
                                if hold_msg:
                                    yield f'data: {json.dumps({"id": completion_id, "object": "chat.completion.chunk", "created": created_timestamp, "model": GROQ_MODEL, "choices": [{"index": 0, "delta": {"content": hold_msg}, "logprobs": None, "finish_reason": None}]})}\n\n'
                            
                            # Phase 2: Execute tool (customer hears hold msg during this)
                            tool_result = await _execute_tool(tool_name, decision["args"], call_sid=active_call_sid)
                            logger.info(f"[Groq Proxy] Tool answer: {tool_result[:150]}")
                            yield f'data: {json.dumps({"id": completion_id, "object": "chat.completion.chunk", "created": created_timestamp, "model": GROQ_MODEL, "choices": [{"index": 0, "delta": {"content": tool_result}, "logprobs": None, "finish_reason": None}]})}\n\n'
                        
                        elif decision["type"] in ("final_answer", "error"):
                            # Send final text directly
                            text = decision["text"]
                            yield f'data: {json.dumps({"id": completion_id, "object": "chat.completion.chunk", "created": created_timestamp, "model": GROQ_MODEL, "choices": [{"index": 0, "delta": {"content": text}, "logprobs": None, "finish_reason": None}]})}\n\n'

                        # Done
                        yield f'data: {json.dumps({"id": completion_id, "object": "chat.completion.chunk", "created": created_timestamp, "model": GROQ_MODEL, "choices": [{"index": 0, "delta": {}, "logprobs": None, "finish_reason": "stop"}]})}\n\n'
                        yield "data: [DONE]\n\n"

                    return StreamingResponse(
                        tool_stream(),
                        media_type="text/event-stream",
                        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}
                    )
                else:
                    decision = await _analyze_request(request.messages)
                    if decision["type"] == "tool_call":
                        final_text = await _execute_tool(decision["name"], decision["args"], call_sid=active_call_sid)
                    else:
                        final_text = decision["text"]
                    prompt_tokens = estimate_tokens(" ".join(m.content for m in request.messages))
                    completion_tokens = estimate_tokens(final_text)
                    return ChatCompletionResponse(
                        id=completion_id, object="chat.completion", created=created_timestamp, model=GROQ_MODEL,
                        choices=[ChatCompletionChoice(index=0, message={"role": "assistant", "content": final_text, "tool_calls": None}, logprobs=None, finish_reason="stop")],
                        usage=ChatCompletionUsage(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens, total_tokens=prompt_tokens + completion_tokens),
                        system_fingerprint="fp_groq", service_tier="default"
                    )

            # ── NORMAL PATH (no tools) ──
            if request.stream:
                logger.info(f"[Groq Proxy] Taking STREAMING path")
                async def stream_generator():
                    try:
                        logger.info(f"[Groq Proxy] stream_generator started")
                        initial_chunk = {
                            "id": completion_id,
                            "object": "chat.completion.chunk",
                            "created": created_timestamp,
                            "model": GROQ_MODEL,
                            "choices": [{
                                "index": 0,
                                "delta": {"role": "assistant", "content": ""},
                                "logprobs": None,
                                "finish_reason": None
                            }]
                        }
                        yield f"data: {json.dumps(initial_chunk)}\n\n"
                        
                        async for delta_dict in generate_groq_stream(
                            messages=request.messages,
                            temperature=request.temperature or 1.0,
                            max_tokens=max_tokens,
                            top_p=request.top_p or 1.0,
                        ):
                            chunk = {
                                "id": completion_id,
                                "object": "chat.completion.chunk",
                                "created": created_timestamp,
                                "model": GROQ_MODEL,
                                "choices": [{
                                    "index": 0,
                                    "delta": delta_dict,
                                    "logprobs": None,
                                    "finish_reason": None
                                }]
                            }
                            yield f"data: {json.dumps(chunk)}\n\n"
                        
                        final_chunk = {
                            "id": completion_id,
                            "object": "chat.completion.chunk",
                            "created": created_timestamp,
                            "model": GROQ_MODEL,
                            "choices": [{
                                "index": 0,
                                "delta": {},
                                "logprobs": None,
                                "finish_reason": "stop"
                            }]
                        }
                        yield f"data: {json.dumps(final_chunk)}\n\n"
                        yield "data: [DONE]\n\n"
                        logger.info(f"[Groq Proxy] Stream completed successfully")
                        
                    except Exception as e:
                        logger.error(f"[Groq Proxy] STREAM ERROR: {type(e).__name__}: {e}", exc_info=True)
                        error_chunk = {
                            "error": {
                                "message": str(e),
                                "type": "server_error",
                                "code": "internal_error"
                            }
                        }
                        yield f"data: {json.dumps(error_chunk)}\n\n"
                
                return StreamingResponse(
                    stream_generator(),
                    media_type="text/event-stream",
                    headers={
                        "Cache-Control": "no-cache",
                        "Connection": "keep-alive",
                        "X-Accel-Buffering": "no"
                    }
                )
            else:
                logger.info(f"[Groq Proxy] Taking NON-STREAMING path")
                response_message = await generate_groq_response(
                    messages=request.messages,
                    temperature=request.temperature or 1.0,
                    max_tokens=max_tokens,
                    top_p=request.top_p or 1.0,
                )
                
                # Calculate tokens (approx)
                prompt_text = " ".join([msg.content for msg in request.messages])
                # Add tool definitions to prompt size estimation if needed, but keeping it simple
                # Add content from response for completion size
                response_content = response_message.get("content") or ""
                
                prompt_tokens = estimate_tokens(prompt_text)
                completion_tokens = estimate_tokens(response_content)
                
                response = ChatCompletionResponse(
                    id=completion_id,
                    object="chat.completion",
                    created=created_timestamp,
                    model=GROQ_MODEL,
                    choices=[
                        ChatCompletionChoice(
                            index=0,
                            message=response_message,
                            refusal=None,
                            logprobs=None,
                            finish_reason="stop"
                        )
                    ],
                    usage=ChatCompletionUsage(
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        total_tokens=prompt_tokens + completion_tokens
                    ),
                    system_fingerprint="fp_groq",
                    service_tier="default"
                )
                
                return response
                
        except Exception as e:
            logger.error(f"[Groq Proxy] TOP-LEVEL ERROR: {type(e).__name__}: {e}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail={
                    "error": {
                        "message": str(e),
                        "type": "server_error",
                        "code": "internal_error"
                    }
                }
            )

    @router.post("/chat/completions")
    async def create_chat_completion_alt(request: ChatCompletionRequest):
        """Alternative endpoint without /v1 prefix."""
        return await create_chat_completion(request)

    app.include_router(router)
