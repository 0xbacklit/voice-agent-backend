from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List

from .schemas import Appointment, ConversationSummary, ToolCallEvent


@dataclass
class SessionState:
    session_id: str
    started_at: datetime = field(default_factory=datetime.utcnow)
    tool_calls: List[ToolCallEvent] = field(default_factory=list)
    summary: ConversationSummary | None = None
    contact_number: str | None = None


class InMemoryStore:
    def __init__(self) -> None:
        self.sessions: Dict[str, SessionState] = {}
        self.appointments: Dict[str, Appointment] = {}

    def create_session(self) -> SessionState:
        session_id = uuid.uuid4().hex
        session = SessionState(session_id=session_id)
        self.sessions[session_id] = session
        return session

    def get_or_create_session(self, session_id: str) -> SessionState:
        if session_id in self.sessions:
            return self.sessions[session_id]
        session = SessionState(session_id=session_id)
        self.sessions[session_id] = session
        return session

    def add_tool_call(self, session_id: str, event: ToolCallEvent) -> None:
        session = self.get_or_create_session(session_id)
        session.tool_calls.append(event)

    def list_tool_calls(self, session_id: str) -> List[ToolCallEvent]:
        return self.sessions[session_id].tool_calls

    def set_contact_number(self, session_id: str, contact_number: str) -> None:
        session = self.get_or_create_session(session_id)
        session.contact_number = contact_number

    def get_contact_number(self, session_id: str) -> str | None:
        session = self.get_or_create_session(session_id)
        return session.contact_number

    def add_appointment(self, appointment: Appointment) -> None:
        self.appointments[appointment.id] = appointment

    def list_appointments(self, contact_number: str) -> List[Appointment]:
        return [
            appointment
            for appointment in self.appointments.values()
            if appointment.contact_number == contact_number
        ]

    def update_summary(self, summary: ConversationSummary) -> None:
        session = self.sessions[summary.session_id]
        session.summary = summary


store = InMemoryStore()
