"""Route modules."""
from .outbound_calls import register_outbound_routes
from .webhooks import register_webhook_routes
from .dashboard import register_dashboard_routes
from .analytics import register_analytics_routes

__all__ = [
	"register_outbound_routes",
	"register_webhook_routes",
	"register_dashboard_routes",
	"register_analytics_routes",
]
