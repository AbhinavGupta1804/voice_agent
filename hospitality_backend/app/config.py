"""Configuration management for the hospitality application."""
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


class Config:
    """Application configuration."""
    
    # ElevenLabs Configuration
    ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
    ELEVENLABS_AGENT_ID = os.getenv("ELEVENLABS_AGENT_ID")
    ELEVENLABS_WEBHOOK_SECRET = os.getenv("ELEVENLABS_WEBHOOK_SECRET", "")
    
    # OpenAI Configuration
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    
    # Twilio Configuration
    TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
    TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
    TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")
    TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER", os.getenv("TWILIO_PHONE_NUMBER"))
    
    # Data Stores
    DB_URL = os.getenv("DB_URL", "postgresql://postgres:postgres@localhost:5432/hospitality_agent")
    ENV = os.getenv("ENV", "dev")
    
    # Server Configuration
    PORT = int(os.getenv("PORT", "8000"))
    NGROK_URL = os.getenv("NGROK_URL", "")
    
    # Cloudflare R2 Storage
    R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID")
    R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
    R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
    R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME", "call-recordings")
    # R2_ENDPOINT_URL: Format: https://{account_id}.r2.cloudflarestorage.com
    R2_ENDPOINT_URL = os.getenv("R2_ENDPOINT_URL") or (f"https://{os.getenv('R2_ACCOUNT_ID')}.r2.cloudflarestorage.com" if os.getenv("R2_ACCOUNT_ID") else None)
    # R2_PUBLIC_BASE_URL: Public URL base (without trailing slash)
    # Format: https://pub-{hash}.r2.dev (from R2 public bucket URL)
    # Example: https://pub-0d05beffe4df48109a9b7182cfc00427.r2.dev
    R2_PUBLIC_BASE_URL = os.getenv("R2_PUBLIC_BASE_URL")
    
    # CORS Configuration
    _cors_origins = os.getenv("CORS_ALLOW_ORIGINS", "")
    if _cors_origins.strip():
        CORS_ALLOW_ORIGINS = [origin.strip() for origin in _cors_origins.split(",") if origin.strip()]
    else:
        # Default to allow common development ports
        CORS_ALLOW_ORIGINS = [
            "http://localhost:8081",
            "http://localhost:5173",
            "http://localhost:3000",
            "http://127.0.0.1:8081",
            "http://127.0.0.1:5173",
        ]
    
    @classmethod
    def validate_elevenlabs_config(cls):
        """Validate ElevenLabs configuration."""
        if not cls.ELEVENLABS_API_KEY or not cls.ELEVENLABS_AGENT_ID:
            raise ValueError("Missing ELEVENLABS_API_KEY or ELEVENLABS_AGENT_ID")
    
    @classmethod
    def validate_twilio_config(cls):
        """Validate Twilio configuration."""
        if not all([cls.TWILIO_ACCOUNT_SID, cls.TWILIO_AUTH_TOKEN, cls.TWILIO_PHONE_NUMBER]):
            raise ValueError("Missing Twilio configuration variables")
    
    @classmethod
    def validate_db_config(cls):
        """Validate PostgreSQL database configuration."""
        if not cls.DB_URL:
            raise ValueError("Missing DB_URL")
    
    @classmethod
    def validate_whatsapp_config(cls):
        """Validate WhatsApp configuration."""
        cls.validate_twilio_config()
        if not cls.TWILIO_WHATSAPP_NUMBER:
            raise ValueError("Missing TWILIO_WHATSAPP_NUMBER")

