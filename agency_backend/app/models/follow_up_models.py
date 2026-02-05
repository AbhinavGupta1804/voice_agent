"""Pydantic models for scheduled follow-up responses."""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class ScheduledFollowUpResponse(BaseModel):
    """Single scheduled follow-up record for API response."""

    id: int = Field(..., description="Follow-up ID")
    call_id: str = Field(..., description="Original call/conversation ID")
    phone_number: str = Field(..., description="Phone number to call")
    client_name: Optional[str] = Field(default=None, description="Client name")
    scheduled_at: datetime = Field(..., description="When the follow-up is scheduled")
    status: str = Field(..., description="pending | processing | completed | failed | cancelled | not_picked")
    retry_count: int = Field(default=0, description="Number of retry attempts")
    max_retries: int = Field(default=3, description="Maximum retries allowed")
    last_error: Optional[str] = Field(default=None, description="Last error message if failed")
    context: Optional[Dict[str, Any]] = Field(default=None, description="Context (reason, summary, etc.)")
    created_at: Optional[datetime] = Field(default=None, description="When the follow-up was created")
    executed_at: Optional[datetime] = Field(default=None, description="When the follow-up was executed")

    model_config = ConfigDict(extra="ignore")


class PaginatedFollowUpsResponse(BaseModel):
    """Paginated list of scheduled follow-ups."""

    page: int = Field(..., ge=1)
    page_size: int = Field(..., ge=1, le=100)
    total: int = Field(..., ge=0)
    items: List[ScheduledFollowUpResponse] = Field(default_factory=list)

    model_config = ConfigDict(extra="ignore")
