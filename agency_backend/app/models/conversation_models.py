"""Pydantic models for conversation threads and messages."""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class ConversationThreadResponse(BaseModel):
    """Single thread for API response."""

    id: int
    phone_number: Optional[str] = None
    channel: str  # whatsapp | sms | email
    display_name: Optional[str] = None
    email_address: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(extra="ignore")


class ConversationMessageResponse(BaseModel):
    """Single message for API response."""

    id: int
    thread_id: int
    body: str
    direction: str  # inbound | outbound
    sender_type: str  # bot | client | user
    twilio_message_sid: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(extra="ignore")


class SendMessageRequest(BaseModel):
    """Request body for client sending a message."""

    body: str = Field(..., min_length=1, max_length=1600)


class PaginatedThreadsResponse(BaseModel):
    """Paginated list of threads."""

    page: int
    page_size: int
    total: int
    items: List[ConversationThreadResponse]

    model_config = ConfigDict(extra="ignore")
