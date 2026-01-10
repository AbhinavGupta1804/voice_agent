"""Pydantic models for call records."""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, ConfigDict


class CallRecordResponse(BaseModel):
    """Response schema for call records."""
    call_id: str
    caller_name: Optional[str]
    caller_phone: Optional[str]
    transcript: Optional[str]
    summary: Optional[str]
    order_id: Optional[str]
    duration_sec: int
    call_timestamp: datetime
    recording_url: Optional[str]
    sentiment: Optional[str]
    
    model_config = ConfigDict(
        json_encoders={datetime: lambda value: value.isoformat() if value else None},
        populate_by_name=True,
    )


class PaginatedCallsResponse(BaseModel):
    """Paginated response wrapper for call records."""
    page: int
    page_size: int
    total: int
    items: List[CallRecordResponse]


class CallRecord(BaseModel):
    """Internal call record model."""
    call_id: str
    caller_name: Optional[str]
    caller_phone: Optional[str]
    transcript: Optional[str]
    summary: Optional[str]
    order_id: Optional[str]
    duration_sec: int
    call_timestamp: datetime
    recording_url: Optional[str]
    sentiment: Optional[str]

