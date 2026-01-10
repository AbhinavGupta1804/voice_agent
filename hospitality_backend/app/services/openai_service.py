"""OpenAI helper service for extracting order details from transcripts."""
import logging
import json
from typing import Optional, Dict, List
from openai import AsyncOpenAI
from config import Config

logger = logging.getLogger(__name__)


class OpenAIService:
    """Wrapper around OpenAI to extract order information from call transcripts."""
    
    _client: Optional[AsyncOpenAI] = None
    
    @classmethod
    def _get_client(cls) -> AsyncOpenAI:
        if cls._client is None:
            if not Config.OPENAI_API_KEY:
                raise RuntimeError("OPENAI_API_KEY is not configured")
            cls._client = AsyncOpenAI(api_key=Config.OPENAI_API_KEY)
        return cls._client
    
    @classmethod
    async def extract_order_details(cls, transcript: str, caller_phone: Optional[str] = None) -> Dict:
        """
        Extract order details from call transcript.
        
        Returns:
            dict with keys:
            - caller_name: str | None
            - items: List[Dict] with name, quantity, price, notes
            - estimated_time_minutes: int | None
            - notes: str | None
            - total_amount: float | None
        """
        client = cls._get_client()
        
        system_prompt = """
            You are an order extraction system for a restaurant. Extract order details from the call transcript.
            Return ONLY a JSON object with:
            - caller_name: string or null (customer's name)
            - items: array of objects with: name (string), quantity (integer), price (float or null), notes (string or null)
            - estimated_time_minutes: integer or null (estimated preparation time)
            - notes: string or null (special instructions)
            - total_amount: float or null (total order amount if mentioned)
            
            Rules:
            - Output only JSON, no extra text
            - If information is not clear, set to null
            - Items array should contain all ordered items
            """
        
        user_prompt = f"Transcript:\n{transcript}"
        if caller_phone:
            user_prompt += f"\nCaller phone number: {caller_phone}"
        
        try:
            response = await client.chat.completions.create(
                model=Config.OPENAI_MODEL or "gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
                max_tokens=1000,
                response_format={"type": "json_object"},
            )
            
            content = response.choices[0].message.content
            data = json.loads(content or "{}")
            
            result = {
                "caller_name": data.get("caller_name"),
                "items": data.get("items", []),
                "estimated_time_minutes": data.get("estimated_time_minutes"),
                "notes": data.get("notes"),
                "total_amount": data.get("total_amount"),
            }
            
            logger.info(f"[OpenAI] Extracted order details: {len(result.get('items', []))} items")
            return result
            
        except Exception as exc:
            logger.error(f"[OpenAI] Order extraction failed: {exc}", exc_info=True)
            return {
                "caller_name": None,
                "items": [],
                "estimated_time_minutes": None,
                "notes": None,
                "total_amount": None,
            }
    
    @classmethod
    async def analyze_call_sentiment_and_name(cls, transcript: str) -> Dict:
        """
        Analyze call transcript to extract caller name and sentiment.
        
        Returns:
            dict with keys:
            - caller_name: str | None
            - sentiment: "positive" | "neutral" | "negative"
        """
        client = cls._get_client()
        
        system_prompt = """
            You are a call analysis system. Analyze the call transcript and extract:
            - caller_name: string or null (customer's name if mentioned)
            - sentiment: one of ["positive", "neutral", "negative"] reflecting customer's overall attitude
            
            Rules:
            - Output only JSON, no extra text
            - If name is not mentioned, set caller_name to null
            - If uncertain about sentiment, default to "neutral"
            """
        
        user_prompt = f"Transcript:\n{transcript}"
        
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
            
            content = response.choices[0].message.content
            data = json.loads(content or "{}")
            
            sentiment = str(data.get("sentiment", "neutral")).lower()
            if sentiment not in {"positive", "neutral", "negative"}:
                sentiment = "neutral"
            
            result = {
                "caller_name": data.get("caller_name"),
                "sentiment": sentiment,
            }
            
            logger.info(f"[OpenAI] Extracted caller_name: {result.get('caller_name')}, sentiment: {sentiment}")
            return result
            
        except Exception as exc:
            logger.error(f"[OpenAI] Sentiment/name extraction failed: {exc}", exc_info=True)
            return {
                "caller_name": None,
                "sentiment": "neutral",
            }

