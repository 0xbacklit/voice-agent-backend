from __future__ import annotations

import uuid
from datetime import datetime

from ..schemas import Appointment, ToolCallEvent
from .slots import format_slot, list_available_slots


def build_tool_event(name: str, detail: str, status: str = "completed") -> ToolCallEvent:
    return ToolCallEvent(
        id=uuid.uuid4().hex,
        name=name,
        status=status,
        detail=detail,
        timestamp=datetime.utcnow(),
    )


def tool_invalid_datetime(tool_name: str) -> tuple[ToolCallEvent, dict]:
    detail = "Could not understand the date/time. Ask for a natural phrasing like 'Tue Feb 12 at 2 PM'."
    return build_tool_event(tool_name, detail, status="failed"), {"error": detail}


def tool_identify_user(contact_number: str | None) -> tuple[ToolCallEvent, dict]:
    detail = "Asked for phone number" if not contact_number else f"Received {contact_number}"
    return build_tool_event("identify_user", detail), {"contact_number": contact_number}


def tool_fetch_slots() -> tuple[ToolCallEvent, dict]:
    slots = list_available_slots()
    detail = f"Returned {len(slots)} slots"
    return build_tool_event("fetch_slots", detail), {
        "slots": [slot.__dict__ for slot in slots],
        "slots_human": [format_slot(slot) for slot in slots],
    }


def tool_book_appointment(appointment: Appointment) -> tuple[ToolCallEvent, dict]:
    detail = f"Booked {appointment.date} {appointment.time} for {appointment.name}"
    return build_tool_event("book_appointment", detail), {"appointment": appointment.model_dump()}


def _mask_contact(contact_number: str) -> str:
    digits = "".join(ch for ch in contact_number if ch.isdigit())
    if len(digits) < 4:
        return contact_number
    return f"***{digits[-4:]}"


def tool_retrieve_appointments(contact_number: str, count: int) -> tuple[ToolCallEvent, dict]:
    if not contact_number:
        detail = "No confirmed phone number yet."
        return build_tool_event("retrieve_appointments", detail, status="failed"), {"count": 0}
    detail = f"Found {count} appointments for {_mask_contact(contact_number)}"
    return build_tool_event("retrieve_appointments", detail), {"count": count}


def tool_cancel_appointment(date: str, time: str, name: str | None) -> tuple[ToolCallEvent, dict]:
    name_label = f" for {name}" if name else ""
    detail = f"Cancelled appointment{name_label} on {date} at {time}"
    return build_tool_event("cancel_appointment", detail), {"date": date, "time": time, "name": name}


def tool_modify_appointment(appointment: Appointment) -> tuple[ToolCallEvent, dict]:
    detail = f"Modified appointment for {appointment.name} to {appointment.date} {appointment.time}"
    return build_tool_event("modify_appointment", detail), {"appointment": appointment.model_dump()}


def tool_end_conversation() -> tuple[ToolCallEvent, dict]:
    return build_tool_event("end_conversation", "Conversation ended"), {}
