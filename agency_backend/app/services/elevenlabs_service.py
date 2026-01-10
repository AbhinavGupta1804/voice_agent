"""Service for ElevenLabs API interactions."""
import logging
import httpx
from ..config import Config

logger = logging.getLogger(__name__)


class ElevenLabsService:
    """Service for ElevenLabs API operations."""
    
    @staticmethod
    async def get_signed_url() -> str:
        """
        Get a signed WebSocket URL for authenticated ElevenLabs conversations.
        
        Returns:
            str: The signed WebSocket URL
            
        Raises:
            Exception: If the API request fails
        """
        Config.validate_elevenlabs_config()
        
        url = f"https://api.elevenlabs.io/v1/convai/conversation/get_signed_url?agent_id={Config.ELEVENLABS_AGENT_ID}"
        headers = {
            "xi-api-key": Config.ELEVENLABS_API_KEY
        }
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=headers)
            
            if response.status_code != 200:
                logger.error(f"[ElevenLabs] Failed to get signed URL: {response.status_code}")
                raise Exception(f"Failed to get signed URL: {response.status_code} - {response.text}")
            
            data = response.json()
            return data["signed_url"]
