"""Async Redis connection pool for booking email sessions."""
import logging
from typing import Optional

import redis.asyncio as redis

from ..config import Config

logger = logging.getLogger(__name__)

_redis: Optional[redis.Redis] = None


async def init_redis() -> None:
    """Initialize the shared Redis client."""
    global _redis
    if _redis is not None:
        return
    _redis = redis.from_url(
        Config.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
        max_connections=Config.REDIS_MAX_CONNECTIONS,
    )
    await _redis.ping()
    logger.info("[Redis] Connected to %s", Config.REDIS_URL.split("@")[-1])


async def close_redis() -> None:
    """Close Redis connection."""
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None
        logger.info("[Redis] Connection closed")


async def get_redis() -> redis.Redis:
    """Return the shared Redis client, initializing if needed."""
    global _redis
    if _redis is None:
        await init_redis()
    return _redis


async def check_redis_health() -> dict:
    """Health check for Redis."""
    try:
        client = await get_redis()
        await client.ping()
        return {"healthy": True, "message": "ok"}
    except Exception as exc:
        logger.warning("[Redis] Health check failed: %s", exc)
        return {"healthy": False, "message": str(exc)}
