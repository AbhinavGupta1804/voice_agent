"""Service for ElevenLabs API interactions."""
import asyncio
import logging
import time
import httpx
from ..config import Config

logger = logging.getLogger(__name__)


class ElevenLabsService:
    """Service for ElevenLabs API operations.
    
    Includes signed-URL pre-fetching so subsequent calls skip the
    ~1-2 s HTTP round-trip to ElevenLabs.
    """
    
    # ── Pre-fetch state ──
    _prefetched_url: str | None = None
    _prefetch_time: float = 0
    _PREFETCH_TTL: float = 45  # seconds — URLs are valid for several minutes
    
    @classmethod
    async def _fetch_signed_url(cls) -> str:
        """Low-level HTTP call to get a fresh signed URL."""
        Config.validate_elevenlabs_config()
        
        url = f"https://api.elevenlabs.io/v1/convai/conversation/get_signed_url?agent_id={Config.ELEVENLABS_AGENT_ID}"
        headers = {"xi-api-key": Config.ELEVENLABS_API_KEY}
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, headers=headers)
            
            if response.status_code != 200:
                logger.error(f"[ElevenLabs] Failed to get signed URL: {response.status_code}")
                raise Exception(f"Failed to get signed URL: {response.status_code} - {response.text}")
            
            data = response.json()
            return data["signed_url"]
    
    @classmethod
    async def _prefetch_url(cls):
        """Pre-fetch the next signed URL in the background."""
        try:
            cls._prefetched_url = await cls._fetch_signed_url()
            cls._prefetch_time = time.time()
            logger.info("[ElevenLabs] Pre-fetched signed URL for next call")
        except Exception as e:
            logger.warning(f"[ElevenLabs] Failed to pre-fetch signed URL: {e}")
    
    @classmethod
    async def warmup(cls):
        """Pre-fetch the first signed URL at server startup."""
        await cls._prefetch_url()
    
    @classmethod
    async def get_signed_url(cls) -> str:
        """
        Get a signed WebSocket URL for authenticated ElevenLabs conversations.
        
        Uses a pre-fetched URL when available (near-instant), otherwise
        falls back to a fresh HTTP fetch. Always kicks off a background
        pre-fetch for the *next* call.
        """
        # Use pre-fetched URL if still fresh
        if cls._prefetched_url and (time.time() - cls._prefetch_time) < cls._PREFETCH_TTL:
            url = cls._prefetched_url
            cls._prefetched_url = None
            logger.info("[ElevenLabs] Using pre-fetched signed URL (near-instant)")
            # Immediately pre-fetch next URL in background
            asyncio.create_task(cls._prefetch_url())
            return url
        
        # No cached URL — fetch synchronously
        logger.info("[ElevenLabs] No pre-fetched URL, fetching fresh...")
        url = await cls._fetch_signed_url()
        # Pre-fetch next URL in background
        asyncio.create_task(cls._prefetch_url())
        return url
