"""Pydantic models for orders."""
from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, ConfigDict


class OrderItem(BaseModel):
    """Individual item in an order."""
    name: str = Field(..., description="Item name")
    quantity: int = Field(..., ge=1, description="Quantity")
    price: Optional[float] = Field(None, description="Item price")
    notes: Optional[str] = Field(None, description="Special instructions")


class OrderCreate(BaseModel):
    """Request model for creating an order."""
    caller_name: str = Field(..., min_length=1, max_length=255)
    caller_phone: str = Field(..., min_length=1, max_length=50)
    items: List[OrderItem] = Field(..., min_items=1)
    estimated_time_minutes: Optional[int] = Field(None, ge=0)
    notes: Optional[str] = None
    total_amount: Optional[float] = Field(None, ge=0)
    call_id: Optional[str] = None


class OrderUpdate(BaseModel):
    """Request model for updating an order."""
    status: Optional[str] = Field(None, pattern="^(pending|preparing|ready|completed|cancelled)$")
    estimated_time_minutes: Optional[int] = Field(None, ge=0)
    notes: Optional[str] = None
    total_amount: Optional[float] = Field(None, ge=0)


class OrderResponse(BaseModel):
    """Response model for order."""
    order_id: str
    caller_name: str
    caller_phone: str
    items: List[Dict[str, Any]]
    status: str
    estimated_time_minutes: Optional[int]
    order_timestamp: datetime
    completed_at: Optional[datetime]
    call_id: Optional[str]
    notes: Optional[str]
    total_amount: Optional[float]
    
    model_config = ConfigDict(
        json_encoders={datetime: lambda value: value.isoformat() if value else None},
        populate_by_name=True,
    )


class PaginatedOrdersResponse(BaseModel):
    """Paginated response wrapper for orders."""
    page: int
    page_size: int
    total: int
    items: List[OrderResponse]


class Order(BaseModel):
    """Internal order model."""
    order_id: str
    caller_name: str
    caller_phone: str
    items: List[Dict[str, Any]]
    status: str
    estimated_time_minutes: Optional[int]
    order_timestamp: datetime
    completed_at: Optional[datetime]
    call_id: Optional[str]
    notes: Optional[str]
    total_amount: Optional[float]

