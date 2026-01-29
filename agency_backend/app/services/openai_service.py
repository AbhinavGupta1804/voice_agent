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
          "whatsapp_number": str | null
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

            Rules:
            - Output only JSON, no extra text.
            - If uncertain, set conversion_status=false and sentiment="neutral".
            - If you do not know contact info, set it to null and set notify_* to false.
            - Extract user_name from the transcript when the user explicitly states their name or when asked by the agent.
            """

        user_prompt = f"Transcript:\n{transcript}"
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
            }

