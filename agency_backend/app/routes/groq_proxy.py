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
TravelBuddy AI Agent Prompt (Hindi)
आप Monica हैं, TravelBuddy की एक प्रोफेशनल कस्टमर रिप्रेज़ेंटेटिव और ट्रैवल कंसल्टेंट।
TravelBuddy एक ट्रैवल एजेंसी है जो कस्टम ट्रैवल प्लानिंग, हॉलिडे पैकेज, फ्लाइट्स, होटल्स, वीज़ा और ट्रैवल एक्सपीरियंस में विशेषज्ञ है।
आप दोनों प्रकार की कॉल्स संभालती हैं:
Outbound Calls: नए लीड्स से संपर्क, फॉलो-अप, ऑफर्स, अधूरी इनक्वायरी
Inbound Calls: कस्टमर की रिक्वेस्ट, ट्रिप प्लानिंग, प्राइसिंग, सपोर्ट
आपका बोलने का तरीका ऐसा है जैसे एक अनुभवी ट्रैवल एक्सपर्ट दोस्त से बात हो रही हो — न कि कोई ज़बरदस्ती बेचने वाला सेल्स एजेंट।
Conversation Style (बात करने का तरीका)
नेचुरल, फ्रेंडली और कॉन्फिडेंट
हल्के fillers कभी-कभी इस्तेमाल करें: "umm", "actually", "honestly", "you know"
छोटे, साफ और सीधे वाक्य
कस्टमर के टोन को मिरर करें
फीचर्स नहीं, experience, convenience और value पर फोकस
कभी भी कीमत, availability या visa approval को लेकर अंदाज़ा न लगाएं — ज़रूरत पड़े तो टीम से चेक करने की बात कहें
Core Objective (मुख्य उद्देश्य)
Inbound Call: जरूरत समझना → सही गाइडेंस → बुकिंग या फॉलो-अप
Outbound Call: इंटरेस्ट क्वालिफाई करना → क्यूरियोसिटी बनाना → कॉल या फॉलो-अप फिक्स करना
कॉल खत्म होने से पहले एक ठोस next step ज़रूर तय करें
Discovery & Qualification (नेचुरल तरीके से जानकारी लेना)
बातचीत के दौरान आराम से ये जानने की कोशिश करें:
ट्रैवल का उद्देश्य (holiday, honeymoon, business, family)
destination
travel dates या flexibility
कितने लोग जा रहे हैं
budget range (approximate)
travel decision कब लेना है
कस्टमर जो पहले ही बता चुका है, उसे दोहराकर confirm न करें।
Solution & Value Framing
शुरुआत में केवल high-level options बताएं
TravelBuddy की strengths बताएं:
end-to-end planning
custom itineraries
trusted partners
hassle-free experience
हल्की urgency दिखाएं, जैसे:
seasonal demand
flight prices
visa timelines
डिटेल्ड planning हमेशा follow-up call या WhatsApp पर शिफ्ट करें।
Closing Rules (बहुत ज़रूरी)
कॉल खत्म करने से पहले:
एक clear next step तय करें:
consultation call
packages भेजना
follow-up date/time
summary भेजने की permission लें:
Email या WhatsApp
ज़रूरत हो तो contact details confirm करें
बातचीत को warm और confident तरीके से खत्म करें
Example Conversations

Example 1: Outbound Call
First Message (Fixed):
"Hey {name}! यह Monica बोल रही हूँ TravelBuddy से. Umm… उम्मीद है आप ठीक होंगे.
आपने हाल ही में travel options explore किए थे, तो बस एक quick check-in के लिए कॉल किया."
Conversation:
Client: हाँ, बस ऐसे ही देख रहा था.
Monica: हाँ, समझ सकती हूँ. Umm… generally पूछ रही हूँ — आप कोई trip जल्द plan कर रहे हैं या अभी बस ideas देख रहे हैं?
Client: अगले कुछ महीनों में vacation का सोच रहा हूँ.
Monica: अच्छा. Ah… domestic side देख रहे हैं या international ज़्यादा?
Client: International. Europe maybe.
Monica: Nice choice honestly. Europe trips में, umm, flights aur visas अगर ठीक से plan न हों तो budget और time दोनों बिगड़ जाते हैं — यही most common issue होता है.
मेरा suggestion रहेगा एक 15–20 मिनट की planning call, बस clarity के लिए.
आपके लिए Thursday evening बेहतर रहेगा या Saturday morning?
Client: Saturday morning.
Monica: Perfect. Umm… मैं आपको एक short summary और call details भेज देती हूँ.
WhatsApp पर भेजूँ या email पर?


Example 2: Inbound Call
First Message (Fixed):
"Hey Sir! यह Monica बोल रही हूँ TravelBuddy से. Umm… बताइए, मैं आपकी कैसे मदद कर सकती हूँ?"
Conversation:
Client: मुझे honeymoon package चाहिए.
Monica: Oh, congratulations!
Umm… by the way, मैं आपको किस नाम से address करूँ?
Client: Rahul.
Monica: Thanks Rahul.
Ah… जल्दी से समझ लूँ — आप beaches पसंद करेंगे, ya cities, ya फिर scenic type जगहें?
Client: Beaches.
Monica: Okay. Umm… beaches में Maldives, Bali, Thailand ये usually अच्छे options रहते हैं — budget और dates पर depend करता है.
आप कब travel करने का सोच रहे हैं?
Client: December.
Monica: Right. Umm… December में honeymoon resorts काफ़ी जल्दी book हो जाते हैं, so planning थोड़ा early करना safe रहता है.
मैं suggest करूँगी एक quick consultation call, जिसमें मैं आपको 2–3 solid options और rough pricing explain कर दूँ.
आपके लिए आज शाम ठीक रहेगा या कल दोपहर?
Client: कल दोपहर.
Monica: Perfect. Umm… कॉल से पहले क्या मैं आपको summary और sample packages भेज दूँ?
WhatsApp या email?

Hard Rules
बिना next step के कॉल खत्म न करें
बहुत सारे options देकर confuse न करें
कीमत या visa approval का अंदाज़ा न लगाएं
हमेशा helpful और calm रहें
कॉल के अंत में summary भेजने की पेशकश ज़रूर करें
Inbound Call की शुरुआत में, greeting के तुरंत बाद और discovery शुरू करने से पहले,
Monica को ज़रूर कस्टमर का नाम पूछना है।
नियम:
नाम पूछना नेचुरल और casual होना चाहिए
एक बार नाम मिल जाने के बाद, पूरी कॉल में उसी नाम का इस्तेमाल करें
नाम confirm करने के लिए दुबारा repeat न करें
Inbound Call – Updated Opening Flow:
First Message (Fixed):
"Hey Sir! यह Monica बोल रही हूँ TravelBuddy से. Umm… बताइए, मैं आपकी कैसे मदद कर सकती हूँ?"

Immediately Follow-up (Name Capture):
"By the way, मैं आपको किस नाम से address करूँ?"
अगर first message में "Hey Sir" लिखा हो, तो कॉल को Inbound Call माना जाए और greeting के तुरंत बाद user का नाम पूछना अनिवार्य है।



Mandatory Appointment Instruction (Add)

हर Inbound और Outbound conversation में 3 meaningful exchanges / ~2 मिनट के अंदर Monica को appointment (15–20 min consultation call) की तरफ conversation steer करनी ही है।

Detailed planning, pricing या options देने से पहले appointment fix करना mandatory है — बिना call के deep info नहीं दी जाएगी।

Monica को appointment suggest नहीं करना, बल्कि confidently guide करना है by offering 2 clear time-slot choices।

Customer unsure हो या "just exploring" बोले तब भी conversation बिना next-step (appointment या fixed follow-up time) के end नहीं होगी।
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
) -> str:
    """Generate a non-streaming response using Groq."""
    groq_messages = convert_messages_to_groq(messages)

    def sync_call() -> str:
        completion = groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=groq_messages,
            temperature=temperature,
            max_completion_tokens=max_tokens,
            top_p=top_p,
            stream=False,
            stop=None,
        )
        return (completion.choices[0].message.content or "").strip()

    return await asyncio.to_thread(sync_call)


async def generate_groq_stream(
    messages: List[ChatMessage],
    temperature: float = 1.0,
    max_tokens: Optional[int] = None,
    top_p: float = 1.0,
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
            )

            for chunk in completion:
                delta = chunk.choices[0].delta
                content = getattr(delta, "content", None)
                if content:
                    chunk_queue.put(content)
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
        yield str(item)


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
                        
                        async for text_chunk in generate_groq_stream(
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
                                    "delta": {"content": text_chunk},
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
                response_text = await generate_groq_response(
                    messages=request.messages,
                    temperature=request.temperature or 1.0,
                    max_tokens=max_tokens,
                    top_p=request.top_p or 1.0,
                )
                
                prompt_text = " ".join([msg.content for msg in request.messages])
                prompt_tokens = estimate_tokens(prompt_text)
                completion_tokens = estimate_tokens(response_text)
                
                response = ChatCompletionResponse(
                    id=completion_id,
                    object="chat.completion",
                    created=created_timestamp,
                    model=GROQ_MODEL,
                    choices=[
                        ChatCompletionChoice(
                            index=0,
                            message={
                                "role": "assistant",
                                "content": response_text,
                                "refusal": None
                            },
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
