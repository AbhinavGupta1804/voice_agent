"""Routes for dashboard and websocket connections."""
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

# Simple in-memory dashboard manager (can be enhanced with Redis for production)
class DashboardManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"[Dashboard] Client connected. Total connections: {len(self.active_connections)}")
    
    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info(f"[Dashboard] Client disconnected. Total connections: {len(self.active_connections)}")
    
    async def broadcast(self, message: dict):
        """Broadcast message to all connected clients."""
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except:
                disconnected.append(connection)
        
        # Remove disconnected clients
        for conn in disconnected:
            self.disconnect(conn)

dashboard_manager = DashboardManager()


def register_dashboard_routes(app):
    """Register dashboard routes."""
    router = APIRouter(tags=["Dashboard"], prefix="/api/dashboard")
    
    @router.websocket("/ws")
    async def dashboard_websocket(websocket: WebSocket):
        """WebSocket endpoint for dashboard updates."""
        await dashboard_manager.connect(websocket)
        try:
            while True:
                # Keep connection alive and handle incoming messages
                data = await websocket.receive_text()
                # Echo back or process message
                await websocket.send_json({"type": "pong", "message": "Connected"})
        except WebSocketDisconnect:
            dashboard_manager.disconnect(websocket)
        except Exception as e:
            logger.error(f"[Dashboard] WebSocket error: {e}")
            dashboard_manager.disconnect(websocket)
    
    app.include_router(router)

