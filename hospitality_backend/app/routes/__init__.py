"""API routes."""
from .inbound_calls import register_inbound_routes
from .orders import register_order_routes
from .calls import register_call_routes
from .webhooks import register_webhook_routes
from .analytics import register_analytics_routes
from .dashboard import register_dashboard_routes

__all__ = [
    "register_inbound_routes",
    "register_order_routes",
    "register_call_routes",
    "register_webhook_routes",
    "register_analytics_routes",
    "register_dashboard_routes",
]

