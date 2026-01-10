"""Data models for the hospitality application."""
from .order_models import Order, OrderCreate, OrderUpdate, OrderResponse, PaginatedOrdersResponse
from .call_models import CallRecord, CallRecordResponse, PaginatedCallsResponse

__all__ = [
    "Order",
    "OrderCreate",
    "OrderUpdate",
    "OrderResponse",
    "PaginatedOrdersResponse",
    "CallRecord",
    "CallRecordResponse",
    "PaginatedCallsResponse",
]
