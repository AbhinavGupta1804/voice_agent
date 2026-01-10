"""Service layer for Google Gemini AI integration."""
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# Lazy import for google.genai to avoid breaking app startup if package is not installed
_genai_module = None
_types_module = None

def _import_genai():
    """Lazy import of google.genai module."""
    global _genai_module, _types_module
    if _genai_module is None:
        try:
            import google.genai as genai
            from google.genai import types
            _genai_module = genai
            _types_module = types
        except ImportError:
            # Fallback for different package versions
            try:
                from google import genai
                from google.genai import types
                _genai_module = genai
                _types_module = types
            except ImportError:
                raise ImportError(
                    "google-genai package is not installed. "
                    "Install it with: pip install google-genai"
                )
    return _genai_module, _types_module

from ..config import Config


@dataclass
class TranscriptAnalysisResult:
    """Result of transcript analysis including summary, follow-up, and notification preferences."""
    summary: str
    follow_up_date: Optional[str]
    notify_email: bool
    notify_whatsapp: bool
    email_address: Optional[str]
    whatsapp_number: Optional[str]


class GeminiService:
    """Service for generating call summaries and extracting follow-up dates using Gemini."""
    
    _client: Optional[any] = None
    
    @classmethod
    def _get_client(cls):
        """Get or create the Gemini client."""
        genai, _ = _import_genai()
        if cls._client is None:
            api_key = Config.GEMINI_API_KEY
            if not api_key:
                raise ValueError("GEMINI_API_KEY is not configured")
            cls._client = genai.Client(api_key=api_key)
        return cls._client
    
    @staticmethod
    async def analyze_transcript(transcript: str, default_phone_number: Optional[str] = None) -> TranscriptAnalysisResult:
        """
        Analyze a call transcript to generate summary, extract follow-up date, and notification preferences.
        
        Args:
            transcript: The full call transcript text.
            default_phone_number: The phone number used for the call (used as default for WhatsApp).
            
        Returns:
            TranscriptAnalysisResult with all extracted information.
        """
        if not transcript or not transcript.strip():
            logger.warning("[Gemini] Empty transcript provided")
            return TranscriptAnalysisResult(
                summary="No transcript available for analysis.",
                follow_up_date=None,
                notify_email=False,
                notify_whatsapp=False,
                email_address=None,
                whatsapp_number=None
            )
        
        try:
            client = GeminiService._get_client()
            
            prompt = f"""
                        Analyze the following call transcript and extract the following information:

                        1. A concise summary (2-3 sentences max) of the key points discussed and outcome.

                        2. Extract any follow-up date mentioned in the conversation. If a specific date is mentioned, return it. If a relative date like "next week", "tomorrow", "in 3 days" etc. is mentioned, calculate the actual date based on today being {datetime.now().strftime('%Y-%m-%d')}.

                        3. Determine if the user requested to receive call details (summary and follow-up information) via email. Look for phrases like "send me an email", "email me the details", "forward to my email", etc.

                        4. Determine if the user requested to receive call details via WhatsApp. Look for phrases like "send me a WhatsApp", "message me on WhatsApp", "text me", "send to my WhatsApp", etc.

                        5. If email notification is requested, extract the email address mentioned in the conversation.

                        6. If WhatsApp notification is requested, extract the phone number mentioned for WhatsApp (if different from the call number).

                        Respond in the following exact format:
                        SUMMARY: <your summary here>
                        FOLLOW_UP_DATE: <YYYY-MM-DD or NONE if no follow-up date mentioned>
                        NOTIFY_EMAIL: <YES or NO>
                        NOTIFY_WHATSAPP: <YES or NO>
                        EMAIL_ADDRESS: <extracted email address or NONE>
                        WHATSAPP_NUMBER: <extracted phone number in E.164 format like +1234567890 or NONE if they want to use the call number>

                        Transcript:
                        {transcript}
                    """

            _, types = _import_genai()
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.3,
                    max_output_tokens=5000,
                )
            )
            
            response_text = response.text.strip()
            logger.info(f"[Gemini] Raw response length: {len(response_text)} chars")
            logger.debug(f"[Gemini] Full response:\n{response_text}")
            
            # Check if response seems complete (should have all expected fields)
            if "WHATSAPP_NUMBER:" not in response_text:
                logger.warning(f"[Gemini] Response may be truncated - missing expected fields. Full response: {response_text}")
            
            # Parse the response
            summary = ""
            follow_up_date = None
            notify_email = False
            notify_whatsapp = False
            email_address = None
            whatsapp_number = None
            
            # Extract summary
            summary_match = re.search(r'SUMMARY:\s*(.+?)(?=FOLLOW_UP_DATE:|$)', response_text, re.DOTALL)
            if summary_match:
                summary = summary_match.group(1).strip()
            else:
                summary = response_text[:500] if len(response_text) > 500 else response_text
            
            # Extract follow-up date
            date_match = re.search(r'FOLLOW_UP_DATE:\s*(\d{4}-\d{2}-\d{2}|NONE)', response_text, re.IGNORECASE)
            if date_match:
                date_str = date_match.group(1).upper()
                if date_str != "NONE":
                    try:
                        datetime.strptime(date_str, '%Y-%m-%d')
                        follow_up_date = date_str
                    except ValueError:
                        logger.warning(f"[Gemini] Invalid date format: {date_str}")
            
            # Extract notification preferences
            email_match = re.search(r'NOTIFY_EMAIL:\s*(YES|NO)', response_text, re.IGNORECASE)
            if email_match:
                notify_email = email_match.group(1).upper() == "YES"
            
            whatsapp_match = re.search(r'NOTIFY_WHATSAPP:\s*(YES|NO)', response_text, re.IGNORECASE)
            if whatsapp_match:
                notify_whatsapp = whatsapp_match.group(1).upper() == "YES"
            
            # Extract email address
            email_addr_match = re.search(r'EMAIL_ADDRESS:\s*([^\n]+)', response_text, re.IGNORECASE)
            if email_addr_match:
                addr = email_addr_match.group(1).strip()
                if addr.upper() != "NONE" and "@" in addr:
                    # Clean up the email address (remove any trailing punctuation)
                    email_address = re.sub(r'[.,;:]+$', '', addr)
                    logger.info(f"[Gemini] Extracted email: {email_address}")
            
            # Extract WhatsApp number
            wa_number_match = re.search(r'WHATSAPP_NUMBER:\s*([^\n]+)', response_text, re.IGNORECASE)
            if wa_number_match:
                num = wa_number_match.group(1).strip()
                if num.upper() != "NONE":
                    # Clean up the number - extract digits and + sign
                    cleaned_num = re.sub(r'[^\d+]', '', num)
                    if cleaned_num and (cleaned_num.startswith('+') or cleaned_num.isdigit()):
                        # Add + if missing and number is long enough (international format)
                        if not cleaned_num.startswith('+') and len(cleaned_num) >= 10:
                            cleaned_num = '+' + cleaned_num
                        whatsapp_number = cleaned_num
                        logger.info(f"[Gemini] Extracted WhatsApp number: {whatsapp_number}")
            
            # Use default phone number for WhatsApp if user wants WhatsApp but didn't provide a different number
            if notify_whatsapp and not whatsapp_number and default_phone_number:
                whatsapp_number = default_phone_number
                logger.info(f"[Gemini] Using default phone number for WhatsApp: {whatsapp_number}")
            
            logger.info(f"[Gemini] Parsed - summary: {summary[:50]}..., follow_up: {follow_up_date}, "
                       f"notify_email: {notify_email}, notify_whatsapp: {notify_whatsapp}, "
                       f"email: {email_address}, whatsapp: {whatsapp_number}")
            
            return TranscriptAnalysisResult(
                summary=summary,
                follow_up_date=follow_up_date,
                notify_email=notify_email,
                notify_whatsapp=notify_whatsapp,
                email_address=email_address,
                whatsapp_number=whatsapp_number
            )
            
        except Exception as exc:
            logger.error(f"[Gemini] Analysis failed: {exc}")
            return TranscriptAnalysisResult(
                summary="Unable to generate summary due to an error.",
                follow_up_date=None,
                notify_email=False,
                notify_whatsapp=False,
                email_address=None,
                whatsapp_number=None
            )
