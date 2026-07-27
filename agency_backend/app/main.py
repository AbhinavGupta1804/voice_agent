"""
FastAPI implementation of Twilio-ElevenLabs voice calling assistant.

"""
import logging
import uvicorn
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse

from .config import Config
from .db import init_postgres, close_postgres
from .services.scheduler_service import start_scheduler, stop_scheduler
from .services.follow_up_service import ScheduledFollowUpService
from .routes import (
    register_outbound_routes,
    register_webhook_routes,
    register_dashboard_routes,
    register_analytics_routes,
    register_inbound_routes,
    register_groq_proxy_routes,
)
from .routes.elevenlabs_tools import register_elevenlabs_tools_routes
from .routes.booking_email import register_booking_email_routes
from .routes.tickets import router as tickets_router

# ... (existing code) ...




# Configure logging
logging.basicConfig(
    level=logging.INFO,  # INFO level for cleaner logs
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
logging.getLogger("handlers.websocket_handler").setLevel(logging.INFO)
logging.getLogger("groq").setLevel(logging.WARNING)  # Silence Groq SDK debug logs
logging.getLogger("groq._base_client").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize application on startup and cleanup on shutdown."""
    logger.info("[Server] Starting up - initializing database connection pool...")
    
    try:
        await init_postgres()
        logger.info("[Server] Database connection pool initialized successfully")
    except Exception as e:
        logger.error(f"[Server] PostgreSQL initialization failed: {e}", exc_info=True)
        # Don't raise - let the server start even if DB fails initially
        # The pool will try to reconnect on first query

    # Start the follow-up scheduler (or cancel queue when disabled)
    try:
        if not Config.FOLLOW_UP_CALLS_ENABLED:
            cancelled = await ScheduledFollowUpService.cancel_all_active(
                reason="FOLLOW_UP_CALLS_ENABLED=false"
            )
            logger.info(
                "[Server] Follow-up calls disabled; cancelled %s queued follow-up(s)",
                cancelled,
            )
        await start_scheduler()
        if Config.FOLLOW_UP_CALLS_ENABLED:
            logger.info("[Server] Follow-up scheduler started successfully")
    except Exception as e:
        logger.error(f"[Server] Scheduler initialization failed: {e}", exc_info=True)
    
    # Validate Retell config on startup
    try:
        Config.validate_retell_config()
        logger.info("[Server] Retell configuration validated")
    except Exception as e:
        logger.warning(f"[Server] Retell config missing (calls will fail until set): {e}")
    
    try:
        yield
    finally:
        logger.info("[Server] Shutting down...")
        await stop_scheduler()
        await close_postgres()
        logger.info("[Server] Cleanup complete")


# Initialize FastAPI application
app = FastAPI(
    title="Twilio-Retell Voice Assistant",
    description="Connect Twilio phone calls to Retell Conversational AI",
    version="3.0.0",
    lifespan=lifespan
)

# Enable CORS for the dashboard frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Audio files are now served directly from Cloudflare R2, not through this server


@app.get("/")
async def root():
    """Health check endpoint."""
    return JSONResponse(content={
        "message": "Server is running",
        "version": "2.0.0",
        "service": "Naturals Retell-Twilio Integration"
    })

# @app.post("/retell-dynamic-variables")
# @app.get("/retell-dynamic-variables")
# async def retell_dynamic_variables(request: Request):
#     """
#     Optional inbound webhook for Retell dynamic variables.
#     Retell can also receive variables via retell_llm_dynamic_variables at call creation.
#     """
#     data = {}
#     if request.method == "POST":
#         try:
#             data = await request.json()
#         except Exception:
#             data = {}
#     else:
#         data = dict(request.query_params())

#     phone_number = (
#         data.get("phone_number")
#         or data.get("from_number")
#         or data.get("from")
#         or data.get("caller_id")
#         or ""
#     )
#     customer_name = data.get("customer_name") or data.get("client_name") or ""

#     return {
#         "retell_llm_dynamic_variables": {
#             "phone_number": str(phone_number or ""),
#             "customer_name": str(customer_name or ""),
#             "client_name": str(customer_name or ""),
#         }
#     }


# @app.post("/elevenlabs-init")
# @app.get("/elevenlabs-init")
# async def elevenlabs_init(request: Request):
#     """Legacy alias — redirects to Retell dynamic variables shape."""
#     return await retell_dynamic_variables(request)
    
@app.get("/static/brochure.pdf")
async def get_brochure():
    """Serve the brochure PDF file for WhatsApp media messages."""
    # Resolve the brochure path relative to the app directory
    app_dir = Path(__file__).parent
    brochure_path = app_dir.parent / Config.BROCHURE_FILE_PATH
    
    if not brochure_path.exists():
        logger.error(f"[Static] Brochure file not found at: {brochure_path}")
        return JSONResponse(
            status_code=404,
            content={"error": "Brochure file not found"}
        )
    
    return FileResponse(
        path=str(brochure_path),
        media_type="application/pdf",
        filename="DevFuzzion_Brochure.pdf"
    )


@app.get("/debug/config")
async def debug_config():
    """Debug endpoint to check configuration (REMOVE IN PRODUCTION)."""
    return JSONResponse(content={
        "retell_configured": bool(Config.RETELL_API_KEY and Config.RETELL_AGENT_ID),
        "retell_integration_mode": Config.RETELL_INTEGRATION_MODE,
        "twilio_configured": bool(Config.TWILIO_PHONE_NUMBER),
        "ngrok_url": Config.NGROK_URL or "Not set",
        "db_url_configured": bool(Config.DB_URL),
        "db_url_preview": Config.DB_URL.split("@")[-1] if Config.DB_URL else "Not set",
    })


@app.get("/health")
async def health_check():
    """Health check endpoint with database status."""
    from .db.postgres import check_pool_health
    
    db_health = await check_pool_health()

    return JSONResponse(content={
        "status": "healthy" if db_health["healthy"] else "degraded",
        "database": db_health,
        "version": "2.0.0"
    })


@app.post("/debug/test-db")
async def test_db_write():
    """Test endpoint to verify database writes work (REMOVE IN PRODUCTION)."""
    from .db.postgres import get_db_pool
    from datetime import datetime, timezone
    
    try:
        pool = await get_db_pool()
        test_call_id = f"test_{int(datetime.now(timezone.utc).timestamp())}"
        
        logger.info(f"[Debug] Testing database write with call_id={test_call_id}")
        
        async with pool.acquire() as conn:
            async with conn.transaction():
                result = await conn.execute("""
                    INSERT INTO calls (
                        call_id, client_name, phone_number, transcript,
                        conversion_status, duration_sec, call_timestamp
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7)
                    ON CONFLICT (call_id) DO UPDATE SET updated_at = NOW()
                """,
                    test_call_id,
                    "Test Client",
                    "+1234567890",
                    "Test transcript for database verification",
                    False,
                    0,
                    datetime.now(timezone.utc)
                )
                
                logger.info(f"[Debug] Insert result: {result}")
                
                # Verify it was inserted
                count = await conn.fetchval("SELECT COUNT(*) FROM calls WHERE call_id = $1", test_call_id)
                logger.info(f"[Debug] Verification count: {count}")
        
        # Fetch outside transaction to verify commit
        async with pool.acquire() as conn:
            final_count = await conn.fetchval("SELECT COUNT(*) FROM calls WHERE call_id = $1", test_call_id)
            total_records = await conn.fetchval("SELECT COUNT(*) FROM calls")
        
        logger.info(f"[Debug] Final count after transaction: {final_count}, Total records: {total_records}")
        
        return JSONResponse(content={
            "success": True,
            "message": "Database write test successful",
            "test_call_id": test_call_id,
            "insert_result": result,
            "verification_count_in_transaction": count,
            "verification_count_after_commit": final_count,
            "total_records_in_table": total_records
        })
    except Exception as e:
        logger.error(f"[Debug] Database test failed: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__
            }
        )


# Register route handlers
register_outbound_routes(app)
register_inbound_routes(app)
register_dashboard_routes(app)
register_webhook_routes(app)
register_analytics_routes(app)
register_groq_proxy_routes(app)
register_elevenlabs_tools_routes(app, prefix="/api/retell")
register_elevenlabs_tools_routes(app, prefix="/api/elevenlabs")
register_booking_email_routes(app)
app.include_router(tickets_router)


if __name__ == "__main__":
    logger.info(f"[Server] Starting on port {Config.PORT}")
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=Config.PORT,
        reload=False,
        log_level="info"
    )
