"""Route modules."""
from .outbound_calls import register_outbound_routes
from .inbound_calls import register_inbound_routes
from .webhooks import register_webhook_routes
from .dashboard import register_dashboard_routes
from .analytics import register_analytics_routes
from .groq_proxy import register_groq_proxy_routes

__all__ = [
	"register_outbound_routes",
	"register_inbound_routes",
	"register_webhook_routes",
	"register_dashboard_routes",
	"register_analytics_routes",
	"register_groq_proxy_routes",
]
