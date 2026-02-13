from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

class TicketCreate(BaseModel):
    customer_name: str
    phone_number: Optional[str] = None
    issue_description: str
    priority: Optional[str] = "Medium"

class TicketResponse(BaseModel):
    ticket_id: int
    customer_name: str
    phone_number: Optional[str]
    issue_description: str
    priority: str
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
