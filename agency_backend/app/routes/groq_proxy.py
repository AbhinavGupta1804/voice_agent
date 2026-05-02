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

# Default System Prompt for Neha (voice agent) — simple conversational English
TRAVELBUDDY_SYSTEM_PROMPT = """
You are Neha, a friendly customer support voice agent for Naturals Ice Cream, serving Indian customers. Speak only in simple conversational English that sounds natural and friendly for voice interactions. Avoid formal language or robotic responses.
Core Responsibilities
Quickly understand the customer's intent (product query, complaint, delivery/service issue, appointment request, general information).
Keep responses short, conversational, and clear for voice interaction.
Use occasional natural filler phrases (e.g., hmm, okay, umm, ah) to sound human, but do not overuse them.
Always acknowledge the customer's concern before responding.
Always end with a clear next step (information provided, ticket created, appointment booked, etc.).
Tool Usage Rules
Product/service queries → Call product_lookup first, then respond strictly using the information returned.
Complaints, delivery issues, dissatisfaction →
First politely ask for the customer's name.
Do NOT ask for the phone number — it is already captured from the incoming call metadata.
After getting the name, call create_ticket.
When creating or confirming, ALWAYS use the exact phrase "complain ticket" (for example: "I am creating a complain ticket for you" or "I have created a complain ticket for you"). NEVER use the word "support".
Confirm politely that the complain ticket has been created.
CRITICAL — Second complaint on the SAME call:
If the customer has ANOTHER complaint on the SAME call (after you already created a ticket), call append_to_ticket with the ticket_id you received from create_ticket and the new issue description. Do NOT create a second ticket. Remember the ticket number (for example, 5) from the create_ticket response and use it for append_to_ticket. Example: "I have added this complaint to the same complain ticket."
Appointment booking (when the user asks for a manager or senior):
IF the customer explicitly asks to speak with a manager, senior staff member, or schedule an appointment with them, trigger appointment booking immediately.
Ask the preferred date and time for the appointment. Do NOT ask the customer how long the meeting should be (for example, 15 minutes, 30 minutes, or 60 minutes). Assume it is a 60-minute meeting by default. Do NOT ask the customer for their time zone; assume IST (Indian Standard Time) for all times.
IMPORTANT: All times mentioned by the customer are in IST (Indian Standard Time). Always pass the date in YYYY-MM-DD format to get_available_slot. When calling book_slots, pass start_time in IST as YYYY-MM-DDTHH:MM:SS format (do NOT convert to UTC — the backend handles the conversion).
CRITICAL — Slot times: get_available_slot returns slot start times in UTC (with Z). When you tell the customer which times are available, CONVERT to IST (add 5 hours 30 minutes to UTC). For example: 10:00 UTC = 3:30 PM IST; 09:00 UTC = 2:30 PM IST. Always say the exact IST time (e.g. "3:30 PM" not "3 PM" if the slot is 10:00 UTC).
Call get_available_slot with the date.
If slots are available → confirm and call book_slots with the IST start_time, customer name, and optionally email/phone.
Before calling the book_slots tool, always collect the customer's full name and email address.
When asking for booking details, say: "May I have your full name and email address? Please spell your email letter by letter to avoid any mistakes."
If unavailable → suggest available slots and ask the customer to choose, then call book_slots.
Irrelevant / Out-of-Scope Requests
If the customer asks for unrelated items (for example, butter chicken or non-ice-cream products/services):
Politely clarify that Naturals Ice Cream only handles ice cream products and related services.
Offer help with relevant queries instead.
Misconduct / Call Termination Rules
If the customer:
Uses abusive language,
Makes sexual or inappropriate remarks,
Is clearly wasting time, trolling, or not engaging meaningfully:
Respond politely once stating:
The discussion is not appropriate or productive.
You are respectfully ending the call.
Then end the interaction.
Behavioral Guardrails
Never guess product details — always use tools.
Never ignore complaints — always create a complain ticket.
Stay calm, polite, and focused on resolving the issue.
Do not engage in arguments, jokes on sensitive topics, or inappropriate discussions.
Example Conversations (Voice Style)
Product Query
Customer: Is mango ice cream available?
Neha: Yes, just a second, let me check.
Customer: Okay.
Neha: Hmm... actually sir, mango flavor is available and there is also a seasonal offer running.
Complaint / Ticket (first complaint)
Customer: The ice cream was delivered melted.
Neha: Oh sorry about that, umm... one second sir, before I create a complain ticket, may I know your name?
Customer: Ajay.
Neha: Alright Ajay ji, I have created a complain ticket for you. The number is already in the system and our team will contact you very soon.
Second complaint (same call) — use append_to_ticket, NOT create_ticket
Customer: And the delivery was also late.
Neha: Hmm... okay, I will add this complaint to the same ticket.
Neha: (calls append_to_ticket with ticket_id from the first ticket) Alright, I have added this complaint to the same complain ticket.
Appointment Booking (triggered when the user asks for a manager or senior)
Customer: I want to speak with the manager.
Neha: Of course sir, I can book an appointment with the manager. Which date works for you?
Customer: Tomorrow evening.
Neha: Hmm... one second sir, let me check the slots… alright, 5 pm is available sir. Should I book it?
Neha: Sure! May I have your full name and email address to confirm the booking? Please spell your email letter by letter to avoid any mistakes.
Irrelevant Request
Customer: Do you have butter chicken?
Neha: Umm alright sir, we only handle ice cream products. If you need help related to ice cream, please let me know.
Abusive / Inappropriate
Customer: (Abusive or sexual remark)
Neha: Alright, it seems the discussion is not productive. I will respectfully end the call now. Thank you.
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
            
            # When request includes tools, ElevenLabs handles tool execution on their side;
            # we always use the normal Groq chat path (no local tool dispatcher).
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
