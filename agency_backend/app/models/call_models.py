"""Models for call-related requests and responses."""
from typing import List
from pydantic import BaseModel, Field


class OutboundCallRequest(BaseModel):
    """Request model for initiating outbound calls."""
    number: str = Field(..., description="Phone number to call in E.164 format")
    client_name: str = Field(..., description="Name of the client to personalize the greeting")


class CallRecipient(BaseModel):
    """Individual call recipient information."""
    number: str = Field(..., description="Phone number to call in E.164 format")
    client_name: str = Field(..., description="Name of the client to personalize the greeting")


class BulkOutboundCallRequest(BaseModel):
    """Request model for initiating multiple concurrent outbound calls."""
    recipients: List[CallRecipient] = Field(..., description="List of recipients to call concurrently", min_items=1, max_items=50)


class CallResult(BaseModel):
    """Result of an individual call initiation."""
    success: bool
    call_sid: str | None = None
    client_name: str
    phone_number: str
    error: str | None = None


class BulkOutboundCallResponse(BaseModel):
    """Response model for bulk outbound call requests."""
    total_requested: int
    successful: int
    failed: int
    results: List[CallResult]
