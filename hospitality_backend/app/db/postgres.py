"""Async PostgreSQL client setup and helpers."""
import asyncio
import logging
from typing import Optional
import asyncpg
from asyncpg import Pool

from config import Config

logger = logging.getLogger(__name__)

_pool: Optional[Pool] = None
_init_lock = asyncio.Lock()
_initialized = False


async def init_postgres(timeout: float = 10.0):
    """Initialize PostgreSQL connection pool at server startup.
    
    Args:
        timeout: Maximum time in seconds to wait for connection (default: 10s)
    """
    global _pool, _initialized
    
    Config.validate_db_config()
    
    async with _init_lock:
        if _initialized and _pool is not None:
            logger.info("[PostgreSQL] Pool already initialized, reusing existing pool")
            return _pool

        try:
            logger.info(f"[PostgreSQL] Initializing connection pool...")
            logger.info(f"[PostgreSQL] Connecting to: {Config.DB_URL.split('@')[-1] if Config.DB_URL else 'Not configured'}")
            
            # Wrap pool creation with timeout to prevent hanging on DNS resolution
            try:
                _pool = await asyncio.wait_for(
                    asyncpg.create_pool(
                        Config.DB_URL,
                        min_size=2,
                        max_size=10,
                        max_inactive_connection_lifetime=300,  # Close idle connections after 5 minutes
                        command_timeout=60,
                        statement_cache_size=100,
                        setup=_setup_connection,
                    ),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                logger.error(f"[PostgreSQL] Connection timeout after {timeout}s - database may be unreachable")
                raise ConnectionError(f"Database connection timeout after {timeout} seconds. Check network connectivity and database hostname.")
            
            # Verify connection works with timeout
            try:
                await asyncio.wait_for(
                    _verify_pool_connection(_pool),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                logger.error(f"[PostgreSQL] Connection verification timeout after {timeout}s")
                if _pool:
                    await _pool.close()
                    _pool = None
                raise ConnectionError(f"Database connection verification timeout after {timeout} seconds.")
            
            _initialized = True
            logger.info("[PostgreSQL] Connection pool created and verified successfully")
            
        except asyncpg.InvalidPasswordError as exc:
            logger.error(f"[PostgreSQL] Authentication failed - check username/password: {exc}")
            raise
        except asyncpg.InvalidCatalogNameError as exc:
            logger.error(f"[PostgreSQL] Database not found - check database name: {exc}")
            raise
        except (ConnectionError, OSError, asyncio.TimeoutError) as exc:
            logger.error(f"[PostgreSQL] Connection failed: {exc}")
            logger.warning("[PostgreSQL] Application will start but database operations will fail until connection is established")
            _pool = None
            _initialized = False
            raise
        except Exception as exc:
            logger.error(f"[PostgreSQL] Initialization failed: {exc}", exc_info=True)
            _pool = None
            _initialized = False
            raise
    
    return _pool


async def _verify_pool_connection(pool: Pool):
    """Verify the pool connection works."""
    async with pool.acquire() as conn:
        result = await conn.fetchval("SELECT 1")
        logger.info(f"[PostgreSQL] Connection test successful: {result}")
        
        # Create tables if they don't exist
        await _create_tables(conn)


async def _setup_connection(conn):
    """Setup function called for each new connection."""
    try:
        await conn.execute("SET idle_in_transaction_session_timeout = '5min'")
        await conn.execute("SET statement_timeout = '60s'")
        # Set search path to use Hospitality schema
        await conn.execute('SET search_path TO "Hospitality", public')
    except Exception as e:
        logger.warning(f"[PostgreSQL] Connection setup failed (connection may be stale): {e}")
        # Re-raise to let asyncpg handle the connection invalidation
        raise




async def _create_tables(conn):
    """Create database tables if they don't exist."""
    # Create schema if it doesn't exist
    await conn.execute('CREATE SCHEMA IF NOT EXISTS "Hospitality"')
    
    # Set search path to use Hospitality schema
    await conn.execute('SET search_path TO "Hospitality", public')
    
    # Calls table
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS "Hospitality".calls (
            id SERIAL PRIMARY KEY,
            call_id VARCHAR(255) UNIQUE NOT NULL,
            caller_name VARCHAR(255),
            caller_phone VARCHAR(50),
            transcript TEXT,
            summary TEXT,
            order_id VARCHAR(255),
            duration_sec INTEGER DEFAULT 0,
            call_timestamp TIMESTAMPTZ DEFAULT NOW(),
            recording_url TEXT,
            sentiment VARCHAR(20),
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    
    # Orders table
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS "Hospitality".orders (
            id SERIAL PRIMARY KEY,
            order_id VARCHAR(255) UNIQUE NOT NULL,
            caller_name VARCHAR(255) NOT NULL,
            caller_phone VARCHAR(50) NOT NULL,
            items JSONB NOT NULL,
            status VARCHAR(50) DEFAULT 'pending',
            estimated_time_minutes INTEGER,
            order_timestamp TIMESTAMPTZ DEFAULT NOW(),
            completed_at TIMESTAMPTZ,
            call_id VARCHAR(255),
            notes TEXT,
            total_amount DECIMAL(10, 2),
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    
    # Create indexes
    await conn.execute('CREATE INDEX IF NOT EXISTS idx_calls_call_id ON "Hospitality".calls(call_id)')
    await conn.execute('CREATE INDEX IF NOT EXISTS idx_calls_call_timestamp ON "Hospitality".calls(call_timestamp)')
    await conn.execute('CREATE INDEX IF NOT EXISTS idx_orders_order_id ON "Hospitality".orders(order_id)')
    await conn.execute('CREATE INDEX IF NOT EXISTS idx_orders_status ON "Hospitality".orders(status)')
    await conn.execute('CREATE INDEX IF NOT EXISTS idx_orders_order_timestamp ON "Hospitality".orders(order_timestamp)')
    await conn.execute('CREATE INDEX IF NOT EXISTS idx_orders_call_id ON "Hospitality".orders(call_id)')
    
    logger.info("[PostgreSQL] Tables and indexes created/verified")


async def reset_pool():
    """Reset the connection pool by closing and reinitializing it."""
    global _pool, _initialized
    
    async with _init_lock:
        logger.warning("[PostgreSQL] Resetting connection pool due to connection failures...")
        
        if _pool is not None:
            try:
                await _pool.close()
            except Exception as e:
                logger.warning(f"[PostgreSQL] Error closing old pool: {e}")
        
        _pool = None
        _initialized = False
        
        # Reinitialize
        try:
            await init_postgres()
        except Exception as e:
            logger.error(f"[PostgreSQL] Failed to reinitialize pool after reset: {e}", exc_info=True)
            raise


async def get_db_pool() -> Pool:
    """Return the database pool, initializing if required."""
    global _pool, _initialized
    
    if _pool is None or not _initialized:
        logger.warning("[PostgreSQL] Pool not initialized, initializing now...")
        try:
            await init_postgres(timeout=10.0)
        except (ConnectionError, OSError, asyncio.TimeoutError) as e:
            logger.error(f"[PostgreSQL] Failed to initialize pool: {e}")
            raise RuntimeError(f"Database connection unavailable: {e}")
        except Exception as e:
            logger.error(f"[PostgreSQL] Failed to initialize pool: {e}", exc_info=True)
            raise RuntimeError(f"Database initialization failed: {e}")
    
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

