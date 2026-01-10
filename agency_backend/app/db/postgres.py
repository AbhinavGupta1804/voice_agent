"""Async PostgreSQL client setup and helpers."""
import asyncio
import logging
from typing import Optional
import asyncpg
from asyncpg import Pool

from ..config import Config

logger = logging.getLogger(__name__)

_pool: Optional[Pool] = None
_init_lock = asyncio.Lock()
_initialized = False


async def init_postgres():
    """Initialize PostgreSQL connection pool at server startup."""
    global _pool, _initialized
    
    Config.validate_db_config()
    
    async with _init_lock:
        if _initialized and _pool is not None:
            logger.info("[PostgreSQL] Pool already initialized, reusing existing pool")
            return _pool

        try:
            logger.info(f"[PostgreSQL] Initializing connection pool...")
            logger.info(f"[PostgreSQL] Connecting to: {Config.DB_URL.split('@')[-1] if Config.DB_URL else 'Not configured'}")
            
            _pool = await asyncpg.create_pool(
                Config.DB_URL,
                min_size=2,
                max_size=10,
                max_inactive_connection_lifetime=0,  # Disable idle connection cleanup
                command_timeout=60,
                statement_cache_size=100,
                # Connection health check settings
                setup=_setup_connection,
            )
            
            # Verify connection works
            async with _pool.acquire() as conn:
                result = await conn.fetchval("SELECT 1")
                logger.info(f"[PostgreSQL] Connection test successful: {result}")
                
                # Verify tables exist
                tables = await conn.fetch("""
                    SELECT table_name FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    AND table_name IN ('calls', 'call_topics', 'notification_preferences')
                """)
                table_names = [t['table_name'] for t in tables]
                logger.info(f"[PostgreSQL] Found tables: {table_names}")
                
                if 'calls' not in table_names:
                    logger.error("[PostgreSQL] WARNING: 'calls' table not found! Data will not be stored.")
            
            _initialized = True
            logger.info("[PostgreSQL] Connection pool created and verified successfully")
            
        except asyncpg.InvalidPasswordError as exc:
            logger.error(f"[PostgreSQL] Authentication failed - check username/password: {exc}")
            raise
        except asyncpg.InvalidCatalogNameError as exc:
            logger.error(f"[PostgreSQL] Database not found - check database name: {exc}")
            raise
        except Exception as exc:
            logger.error(f"[PostgreSQL] Initialization failed: {exc}", exc_info=True)
            raise
    
    return _pool


async def _setup_connection(conn):
    """Setup function called for each new connection."""
    # Set connection parameters for better stability
    await conn.execute("SET idle_in_transaction_session_timeout = '5min'")
    await conn.execute("SET statement_timeout = '60s'")


async def get_db_pool() -> Pool:
    """Return the database pool, initializing if required."""
    global _pool, _initialized
    
    if _pool is None or not _initialized:
        logger.warning("[PostgreSQL] Pool not initialized, initializing now...")
        await init_postgres()
    
    # Check if pool is still valid
    if _pool is None:
        raise RuntimeError("Database pool is not available")
    
    return _pool


async def close_postgres():
    """Close PostgreSQL connection pool - only call on server shutdown."""
    global _pool, _initialized
    
    if _pool is not None:
        logger.info("[PostgreSQL] Closing connection pool...")
        await _pool.close()
        _pool = None
        _initialized = False
        logger.info("[PostgreSQL] Connection pool closed")
    else:
        logger.info("[PostgreSQL] No pool to close")


async def check_pool_health() -> dict:
    """Check the health of the connection pool."""
    global _pool
    
    if _pool is None:
        return {"status": "not_initialized", "healthy": False}
    
    try:
        async with _pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        
        return {
            "status": "healthy",
            "healthy": True,
            "pool_size": _pool.get_size(),
            "pool_free_size": _pool.get_idle_size(),
            "pool_min_size": _pool.get_min_size(),
            "pool_max_size": _pool.get_max_size(),
        }
    except Exception as exc:
        return {
            "status": "unhealthy",
            "healthy": False,
            "error": str(exc)
        }
