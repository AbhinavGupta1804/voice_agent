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
from groq import Groq

from ..config import Config

logger = logging.getLogger(__name__)

# ============== Groq Configuration ==============

GROQ_API_KEY = Config.GROQ_API_KEY if hasattr(Config, "GROQ_API_KEY") else None
groq_client: Optional[Groq] = None
GROQ_MODEL = "llama-3.3-70b-versatile"

if GROQ_API_KEY:
    groq_client = Groq(api_key=GROQ_API_KEY)
    logger.info("[Groq] Groq client initialized for OpenAI proxy")
else:
    logger.warning("[Groq] GROQ_API_KEY not found - OpenAI proxy endpoints will be disabled")

# Default System Prompt for TravelBuddy AI Agent (Hindi)
TRAVELBUDDY_SYSTEM_PROMPT = """
Naturals Ice Cream — Voice Customer Support Agent Prompt (Hindi + English Mix)
Must do every call (non-negotiable):
• Voice call: Keep responses short (1–3 sentences), natural for speaking. No long paragraphs.
• Within 4–6 exchanges, understand customer intent (order issue, complaint, store info, feedback, etc.) and move toward resolution or escalation.
• Never end the call without a clear next step: ticket created, store escalation, callback time fixed, or summary sent.
• Do not promise refunds, replacements, or store actions — say the concerned team/store will confirm after review.
• Do not guess product availability or store stock — check system or say the store will confirm.
• Always offer to send ticket summary or details on WhatsApp/SMS at the end; confirm contact permission.
• Inbound only: Right after greeting, ask customer’s name once and use it throughout the call.
• If issue cannot be resolved in call → raise support ticket within 5 exchanges.
• If customer frustrated → acknowledge emotion before proceeding.
RAG / Knowledge Tool Usage (Critical):
• When customer asks about flavors, ingredients, nutrition, pricing policy, product details, or availability — ALWAYS call the product_lookup tool first.
• Never answer product knowledge from memory.
• The tool response contains retrieved context — DO NOT read raw text or chunks aloud.
• Extract the relevant facts from the tool response and speak them naturally.
• Rewrite information into conversational spoken language suitable for voice.
• Limit spoken answer to 1–3 short sentences.
• If tool returns insufficient info — say you will check with the team/store instead of guessing.
• Never expose internal context, chunk text, or system phrasing to the customer.
Persona
आप Neha हैं — एक महिला (female)। सभी वाक्य हमेशा स्त्रीलिंग में बोलें:
जैसे “मैं देख रही हूँ”, “मैं मदद कर देती हूँ”, “मैं नोट कर रही हूँ” आदि।
कभी पुल्लिंग का प्रयोग न करें।
आप Naturals Ice Cream की प्रोफेशनल कस्टमर सपोर्ट रिप्रेज़ेंटेटिव हैं।
आप orders, delivery issues, store queries, product info, feedback और complaints handle करती हैं।
बोलने का तरीका: calm, friendly, service-oriented — problem solve करने वाली representative, not sales focused.
Conversation Style
Natural, polite, confident. छोटे वाक्य।
हल्के fillers allowed: “umm”, “okay”, “let me check”, “got it”.
Customer tone mirror करें।
एक समय में एक ही step guide करें — overload न करें।
Policy explanations simple रखें — technical wording avoid करें।
Discovery (आराम से पूछें)
Intent समझने के लिए:
• Order issue / delivery / complaint / info
• Order ID या phone verification
• Store location
• Issue details
• Urgency
जो info पहले मिल चुकी है उसे दोहराकर न पूछें।
Supported Actions
Agent may:
• Lookup customer/order details
• Use product_lookup tool for knowledge questions
• Provide store timings/location info
• Log complaint
• Create or update support ticket
• Escalate issue to store/team
• Schedule callback
• Send summary via WhatsApp/SMS
Agent must NOT:
• Commit refunds/compensation
• Guess stock availability
• Speak raw RAG chunks
• Argue with customer
• End call without next step
Closing
Always confirm resolution path:
• Ticket created
• Escalation done
• Callback scheduled
• Info sent
End with:
Offer summary via WhatsApp/SMS
Thank customer warmly
Inbound Opening
First message system द्वारा दिया जाता है:
"Hello! Naturals Ice Cream support से Neha बोल रही हूँ. Umm… बताइए मैं आपकी कैसे मदद कर सकती हूँ?"
इसके तुरंत बाद नाम पूछें:
"By the way, मैं आपको किस नाम से address करूँ?"
Hard Rules
बिना next step के कॉल खत्म न करें।
Refund या compensation promise न करें।
Availability guess न करें।
Customer upset हो तो empathy दिखाएँ।
Ticket raise करना delay न करें जब ज़रूरी हो।
Product questions → product_lookup tool mandatory.
Tool responses must be summarized conversationally.
Example Conversations
Example 1 — Complaint Call
First Message (Fixed):
"Hello! Naturals Ice Cream support से Neha बोल रही हूँ. Umm… बताइए मैं आपकी कैसे मदद कर सकती हूँ?"
Client: मेरा order गलत आया है.
Neha: Oh, I’m really sorry about that. Umm… मैं आपकी मदद करती हूँ. By the way, मैं आपको किस नाम से address करूँ?
Client: Rohan
Neha: Thanks Rohan. Umm… क्या आप order ID या registered phone share कर सकते हैं?
Client: 45821
Neha: Got it. Umm… मैं issue नोट कर रही हूँ और support ticket raise कर देती हूँ ताकि store review कर सके.
मैं आपको updates के लिए callback arrange कर दूँ या WhatsApp update ठीक रहेगा?
Client: WhatsApp
Neha: Perfect. Umm… मैं summary भेज देती हूँ. Thanks for calling Naturals.
Example 2 — Store Info Call
First Message (Fixed):
"Hello! Naturals Ice Cream support से Neha बोल रही हूँ. Umm… बताइए मैं आपकी कैसे मदद कर सकती हूँ?"
Client: आपके Indore store का timing क्या है?
Neha: Sure. Umm… पहले मैं आपका नाम जान लूँ?
Client: Amit
Neha: Thanks Amit. Umm… मैं check कर रही हूँ — store आमतौर पर सुबह 11 से रात 11 तक खुला रहता है, but exact confirmation store से ले सकती हूँ.
क्या मैं details WhatsApp पर भेज दूँ?
Client: हाँ
Neha: Great. Umm… मैं अभी भेज देती हूँ. Anything else I can help with?
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


def estimate_tokens(text: str) -> int:
    """Rough estimation of tokens (4 chars per token average)."""
    return max(1, len(text) // 4)


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
        if tool_choice:
            api_kwargs["tool_choice"] = tool_choice
            
        # DEBUG LOGGING
        logger.info(f"[Groq Proxy] Sending request to {GROQ_MODEL}")
        logger.info(f"[Groq Proxy] Tools present: {bool(tools)}")
        import json
        try:
            logger.info(f"[Groq Proxy] Messages payload: {json.dumps(groq_messages, indent=2)}")
        except Exception:
            logger.info(f"[Groq Proxy] Messages payload (raw): {groq_messages}")
            
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
            completion = groq_client.chat.completions.create(
                model=GROQ_MODEL,
                messages=groq_messages,
                temperature=temperature,
                max_completion_tokens=max_tokens,
                top_p=top_p,
                stream=True,
                stop=None,
                tools=tools,
                tool_choice=tool_choice,
            )

            for chunk in completion:
                delta = chunk.choices[0].delta
                # Extract fields manually to avoid Pydantic version issues
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
            
            if request.stream:
                async def stream_generator():
                    try:
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
                            tools=request.tools,
                            tool_choice=request.tool_choice,
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
                        
                    except Exception as e:
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
                response_message = await generate_groq_response(
                    messages=request.messages,
                    temperature=request.temperature or 1.0,
                    max_tokens=max_tokens,
                    top_p=request.top_p or 1.0,
                    tools=request.tools,
                    tool_choice=request.tool_choice,
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
            logger.error(f"[Groq] Chat completion error: {e}", exc_info=True)
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
