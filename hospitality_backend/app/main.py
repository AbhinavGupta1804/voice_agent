"""
FastAPI implementation of hospitality inbound call handling system.
Handles inbound calls, order management, and WhatsApp notifications.
"""
import asyncio
import logging
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import Config
from db import init_postgres, close_postgres
from routes import (
    register_inbound_routes,
    register_order_routes,
    register_call_routes,
    register_webhook_routes,
    register_analytics_routes,
    register_dashboard_routes
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s - %(name)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Silence noisy third-party loggers
logging.getLogger("asyncpg").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("websockets").setLevel(logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize application on startup and cleanup on shutdown."""
    logger.info("[Server] Starting up - initializing database connection pool...")
    
    try:
        await init_postgres(timeout=10.0)
        logger.info("[Server] Database connection pool initialized successfully")
    except (ConnectionError, OSError, asyncio.TimeoutError) as e:
        logger.error(f"[Server] PostgreSQL connection failed: {e}")
        logger.warning("[Server] Application will start but database-dependent endpoints may fail")
        logger.warning("[Server] Database will be initialized on first use or can be retried via /health endpoint")
    except Exception as e:
        logger.error(f"[Server] PostgreSQL initialization failed: {e}", exc_info=True)
        logger.warning("[Server] Application will start but database-dependent endpoints may fail")
    
    yield
    
    logger.info("[Server] Shutting down - closing database connection pool...")
    await close_postgres()
    logger.info("[Server] Shutdown complete")


# Create FastAPI application
app = FastAPI(
    title="Hospitality AI Caller",
    description="Inbound call handling system for restaurants, hotels, and bars",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware
# Allow all origins if CORS_ALLOW_ORIGINS is ["*"], otherwise use configured origins
cors_origins = Config.CORS_ALLOW_ORIGINS
if cors_origins == ["*"]:
    cors_origins = ["*"]
else:
    # Add common development ports
    cors_origins = list(set(cors_origins + [
        "http://localhost:8081",
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:8081",
        "http://127.0.0.1:5173",
    ]))

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routes
register_inbound_routes(app)
register_order_routes(app)
register_call_routes(app)
register_webhook_routes(app)
register_analytics_routes(app)
register_dashboard_routes(app)


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": "Hospitality AI Caller",
        "version": "1.0.0",
        "status": "running"
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    from db import check_pool_health
    db_health = await check_pool_health()
    
    return {
        "status": "healthy" if db_health.get("healthy") else "degraded",
        "database": db_health
    }


@app.get("/webhook/test")
async def webhook_test_endpoint():
    """Test endpoint to verify webhook route is accessible via ngrok."""
    return {
        "status": "ok",
        "message": "Webhook endpoint is accessible",
        "webhook_url": f"{Config.NGROK_URL or 'http://localhost:8000'}/webhook/call_complete",
        "webhook_secret_configured": bool(Config.ELEVENLABS_WEBHOOK_SECRET)
    }


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=Config.PORT,
        reload=Config.ENV == "dev",
        log_level="info"
    )

