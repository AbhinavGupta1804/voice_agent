"""Business logic services."""
from .elevenlabs_service import ElevenLabsService
from .twilio_service import TwilioService
from .call_record_service import CallRecordService
from .email_service import EmailService
from .whatsapp_service import WhatsAppService

try:
    from .gemini_service import GeminiService
except ImportError as e:
    GeminiService = None
    import logging
    logger = logging.getLogger(__name__)
    logger.warning(f"Failed to import GeminiService: {e}. Gemini features will not be available.")

__all__ = [
    "ElevenLabsService",
    "TwilioService",
    "CallRecordService",
    "EmailService",
    "WhatsAppService",
]

if GeminiService is not None:
    __all__.append("GeminiService")
