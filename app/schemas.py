from datetime import datetime
from pydantic import BaseModel, Field


class SessionStartResponse(BaseModel):
    session_id: str
    ws_url: str


class ToolCallEvent(BaseModel):
    id: str
    name: str
    status: str
    detail: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class Appointment(BaseModel):
    id: str
    contact_number: str
    name: str
    date: str
    time: str
    status: str = "booked"
    confirmed_by_user: bool = False


class ConversationSummary(BaseModel):
    session_id: str
    contact_number: str | None = None
    summary: str
    booked_appointments: list[Appointment]
    preferences: list[str]
    created_at: datetime = Field(default_factory=datetime.utcnow)
