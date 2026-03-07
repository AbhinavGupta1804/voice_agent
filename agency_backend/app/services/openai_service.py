"""OpenAI helper service for sentiment and conversion analysis."""
import logging
from typing import Optional

from openai import AsyncOpenAI

from ..config import Config

logger = logging.getLogger(__name__)


class OpenAIService:
    """Wrapper around OpenAI chat completions to classify calls."""

    _client: Optional[AsyncOpenAI] = None

    @classmethod
    def _get_client(cls) -> AsyncOpenAI:
        if cls._client is None:
            if not Config.OPENAI_API_KEY:
                raise RuntimeError("OPENAI_API_KEY is not configured")
            cls._client = AsyncOpenAI(api_key=Config.OPENAI_API_KEY)
        return cls._client

    @classmethod
    def detect_call_type_from_transcript(cls, transcript: str) -> Optional[str]:
        """
        Detect if a call is inbound or outbound based on the agent's first message in the transcript.
        
        Logic:
        - Inbound calls: Agent greets with "Hey Sir" (doesn't know user's name)
        - Outbound calls: Agent greets with "Hey {name}" (knows user's name)
        
        Args:
            transcript: The call transcript text
            
        Returns:
            "inbound", "outbound", or None if cannot determine
        """
        if not transcript:
            return None
        
        # Look for the first agent message in the transcript
        # Transcript format is typically: "Agent: Hey {name}!..." or "Agent: Hey Sir!..."
        lines = transcript.split('\n')
        for line in lines:
            line_lower = line.lower().strip()
            # Check for agent messages (could be "Agent:", "agent:", etc.)
            if line_lower.startswith('agent:'):
                message = line[len('agent:'):].strip()
                message_lower = message.lower()
                
                # Check for inbound pattern: "Hey Sir" or variations
                if message_lower.startswith('hey sir') or message_lower.startswith('hey, sir'):
                    logger.info("[OpenAI] Detected call_type='inbound' from transcript (agent said 'Hey Sir')")
                    return "inbound"
                
                # Check for outbound pattern: "Hey {name}" where name is not "Sir"
                if message_lower.startswith('hey '):
                    # Extract the word after "Hey"
                    words = message_lower.split()
                    if len(words) > 1:
                        second_word = words[1].strip(',!?')
                        if second_word and second_word != 'sir' and second_word != 'there':
                            logger.info(f"[OpenAI] Detected call_type='outbound' from transcript (agent said 'Hey {second_word}')")
                            return "outbound"
        
        logger.warning("[OpenAI] Could not detect call_type from transcript")
        return None
    
    @classmethod
    async def analyze_call_structured(
        cls,
        transcript: str,
        default_phone_number: Optional[str] = None,
    ) -> dict:
        """
        Analyze a call transcript and return structured fields:
        {
          "summary": str | null,
          "conversion_status": bool,
          "sentiment": "positive" | "neutral" | "negative",
          "notify_email": bool,
          "notify_whatsapp": bool,
          "email_address": str | null,
          "whatsapp_number": str | null,
          "user_name": str | null,
          "follow_up_required": bool,
          "follow_up_datetime": str | null
        }
        """
        client = cls._get_client()

        system_prompt = """
            You are a strict JSON generator for call analytics. Given the call transcript, return ONLY a JSON object with:
            - summary: concise 1-3 sentence summary (string or null)
            - conversion_status: boolean (true if the user accepted / booked / agreed; else false)
            - sentiment: one of ["positive","neutral","negative"] reflecting user's attitude
            - notify_email: boolean (should we send a follow-up email?)
            - notify_whatsapp: boolean (should we send a follow-up WhatsApp?)
            - email_address: string or null (only if notify_email is true; otherwise null)
            - whatsapp_number: string or null (only if notify_whatsapp is true; otherwise null)
            - user_name: string or null (extract the user's actual name from the transcript. Look for when the user introduces themselves or when the agent asks for their name. Return null if name cannot be determined)
            - follow_up_required: boolean (true ONLY if customer explicitly asks to be called back later, says they are busy, asks to reschedule, or similar scenarios. false otherwise)
            - follow_up_datetime: string or null (ISO 8601 format like "2025-02-03T15:00:00+05:30" - only if follow_up_required is true. Calculate based on current datetime and what customer said like "call me in 2 days", "call me tomorrow at 3 PM", "call after 2 hours")
            - follow_up_first_message: string or null (ONLY if follow_up_required is true. The exact first message the agent should say when making the follow-up call, so the conversation continues from the previous call. MUST be in Hinglish (Hindi + English mix, e.g. "Hey [name], Neha bol rahi hoon Naturals Ice Cream se. Aapne kaha tha ki aaj call back karein – jo baat discuss ki thi uske baare mein follow-up kar rahi hoon."). Include the client's name naturally. Keep it concise, 1-3 sentences.

            Rules:
            - Output only JSON, no extra text.
            - If uncertain, set conversion_status=false and sentiment="neutral".
            - If you do not know contact info, set it to null and set notify_* to false.
            - Extract user_name from the transcript when the user explicitly states their name or when asked by the agent.
            - Set follow_up_required=true ONLY when customer explicitly requests a callback (e.g., "call me later", "I'm busy right now", "call me tomorrow"). Do NOT set it true for general follow-ups.
            - For follow_up_datetime, use the current datetime provided and calculate the exact datetime based on customer's request.
            - When follow_up_required is true, always provide follow_up_first_message in Hinglish (Hindi words in Devanagari + English mix), a natural opening line for the agent that references the prior conversation and the callback, so the follow-up call has continuity.
            """

        from datetime import datetime, timezone
        current_dt = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        
        user_prompt = f"Transcript:\n{transcript}\n\nCurrent datetime (UTC): {current_dt}"
        if default_phone_number:
            user_prompt += f"\nDefault phone number (if needed): {default_phone_number}"

        try:
            response = await client.chat.completions.create(
                model=Config.OPENAI_MODEL or "gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
                max_tokens=200,
                response_format={"type": "json_object"},
            )

            import json

            content = response.choices[0].message.content
            data = json.loads(content or "{}")

            # Normalize fields with defaults
            result = {
                "summary": data.get("summary"),
                "conversion_status": bool(data.get("conversion_status", False)),
                "sentiment": str(data.get("sentiment", "neutral")).lower(),
                "notify_email": bool(data.get("notify_email", False)),
                "notify_whatsapp": bool(data.get("notify_whatsapp", False)),
                "email_address": data.get("email_address"),
                "whatsapp_number": data.get("whatsapp_number"),
                "user_name": data.get("user_name"),  # Extracted user name from transcript
                "follow_up_required": bool(data.get("follow_up_required", False)),
                "follow_up_datetime": data.get("follow_up_datetime"),
                "follow_up_first_message": data.get("follow_up_first_message"),
            }

            if result["sentiment"] not in {"positive", "neutral", "negative"}:
                result["sentiment"] = "neutral"

            logger.info(
                "[OpenAI] Structured analysis -> conversion=%s, sentiment=%s, notify_email=%s, notify_whatsapp=%s",
                result["conversion_status"],
                result["sentiment"],
                result["notify_email"],
                result["notify_whatsapp"],
            )
            logger.info(f"[OpenAI DEBUG] follow_up_required={result['follow_up_required']}, follow_up_datetime={result['follow_up_datetime']}")
            return result

        except Exception as exc:  # pragma: no cover
            logger.error(f"[OpenAI] Structured analysis failed: {exc}", exc_info=True)
            return {
                "summary": None,
                "conversion_status": False,
                "sentiment": "neutral",
                "notify_email": False,
                "notify_whatsapp": False,
                "email_address": None,
                "whatsapp_number": None,
                "user_name": None,
                "follow_up_required": False,
                "follow_up_datetime": None,
                "follow_up_first_message": None,
            }

