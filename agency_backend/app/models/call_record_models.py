"""Pydantic models for call record payloads and responses."""
from datetime import datetime, date
from typing import List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


class InsightModel(BaseModel):
    """Structured insights extracted from a call."""

    topics: List[str] = Field(default_factory=list)
    duration_sec: int = Field(..., ge=0)

    model_config = ConfigDict(extra="ignore")


class NotificationPreferences(BaseModel):
    """User notification preferences extracted from transcript."""
    
    notify_email: bool = Field(default=False, description="Whether user wants email notification")
    notify_whatsapp: bool = Field(default=False, description="Whether user wants WhatsApp notification")
    email_address: Optional[str] = Field(default=None, description="Email address for notification")
    whatsapp_number: Optional[str] = Field(default=None, description="WhatsApp number for notification")
    email_sent: bool = Field(default=False, description="Whether email was successfully sent")
    whatsapp_sent: bool = Field(default=False, description="Whether WhatsApp message was successfully sent")
    
    model_config = ConfigDict(extra="ignore")


# ElevenLabs webhook models
class ElevenLabsTranscriptTurn(BaseModel):
    """A single turn in the conversation transcript."""
    role: str
    message: Optional[str] = None
    time_in_call_secs: int = 0
    
    model_config = ConfigDict(extra="ignore")


class ElevenLabsAnalysis(BaseModel):
    """Analysis data from ElevenLabs."""
    call_successful: Optional[str] = None
    transcript_summary: Optional[str] = None
    call_summary_title: Optional[str] = None
    
    model_config = ConfigDict(extra="ignore")


class ElevenLabsMetadata(BaseModel):
    """Metadata about the call."""
    call_duration_secs: int = 0
    cost: Optional[int] = None
    termination_reason: Optional[str] = None
    recording_url: Optional[str] = Field(default=None, description="URL to the call recording audio")
    
    model_config = ConfigDict(extra="ignore")


class ElevenLabsConversationData(BaseModel):
    """The main data payload from ElevenLabs post_call_transcription webhook."""
    agent_id: str
    conversation_id: str
    status: str
    transcript: List[ElevenLabsTranscriptTurn]
    metadata: ElevenLabsMetadata
    analysis: Optional[ElevenLabsAnalysis] = None
    recording_url: Optional[str] = Field(default=None, description="URL to the call recording audio")
    
    model_config = ConfigDict(extra="allow")


class ElevenLabsWebhookPayload(BaseModel):
    """Complete ElevenLabs webhook payload structure."""
    type: str
    event_timestamp: int
    data: ElevenLabsConversationData
    
    model_config = ConfigDict(extra="ignore")


class CallCompletePayload(BaseModel):
    """Payload schema for call completion webhook."""

    call_id: str = Field(..., min_length=1, max_length=128)
    client_name: str = Field(..., min_length=1, max_length=255)
    transcript: str = Field(default="", min_length=0)
    insights: InsightModel
    conversion_status: bool
    sentiment: Optional[str] = Field(default=None, description="Call sentiment: positive | neutral | negative")
    timestamp: datetime
    summary: Optional[str] = Field(default=None, description="AI-generated call summary")
    follow_up_date: Optional[Union[str, date]] = Field(default=None, description="Extracted follow-up date in YYYY-MM-DD format")
    notification_preferences: Optional[NotificationPreferences] = Field(default=None, description="User notification preferences")
    phone_number: Optional[str] = Field(default=None, description="Phone number used for the call")
    recording_url: Optional[str] = Field(default=None, description="URL to the call recording audio")
    call_type: Optional[str] = Field(default=None, description="Type of call: 'inbound' or 'outbound'")

    model_config = ConfigDict(extra="ignore")


class CallRecordResponse(CallCompletePayload):
    """Response schema for call records."""

    model_config = ConfigDict(
        json_encoders={datetime: lambda value: value.strftime('%Y-%m-%dT%H:%M:%SZ') if value.tzinfo else value.isoformat()},
        populate_by_name=True,
    )


class PaginatedCallsResponse(BaseModel):
    """Paginated response wrapper for call records."""

    page: int
    page_size: int
    total: int
    items: List[CallRecordResponse]


class CallSummaryResponse(BaseModel):
    """Summary metrics for dashboard analytics."""

    total_calls: int
    conversions: int
    conversion_rate: float
