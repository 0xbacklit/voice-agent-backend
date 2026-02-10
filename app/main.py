from __future__ import annotations

from datetime import datetime
from typing import Dict, List

from dotenv import load_dotenv

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from .config import settings
from .livekit_tokens import create_token
from .schemas import Appointment, ConversationSummary, SessionStartResponse, ToolCallEvent
from .store import store
from .db.repository import build_repositories
from .tools.handlers import (
    tool_book_appointment,
    tool_cancel_appointment,
    tool_end_conversation,
    tool_fetch_slots,
    tool_identify_user,
    tool_missing_info,
    tool_invalid_datetime,
    tool_modify_appointment,
    tool_retrieve_appointments,
)
from dateutil import parser as date_parser

app = FastAPI(title="Voice Agent API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, session_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.setdefault(session_id, []).append(websocket)

    def disconnect(self, session_id: str, websocket: WebSocket) -> None:
        self.active_connections[session_id].remove(websocket)

    async def broadcast(self, session_id: str, payload: dict) -> None:
        for websocket in list(self.active_connections.get(session_id, [])):
            await websocket.send_json(payload)


manager = ConnectionManager()
appointment_repo, summary_repo = build_repositories(
    settings.supabase_url,
    settings.supabase_key,
)


async def _record_tool_event(session_id: str, event: ToolCallEvent) -> None:
    if event.status != "completed":
        return
    store.add_tool_call(session_id, event)
    await manager.broadcast(session_id, {"type": "tool_call", "payload": event.model_dump(mode="json")})


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/session/start", response_model=SessionStartResponse)
async def start_session() -> SessionStartResponse:
    session = store.create_session()
    return SessionStartResponse(
        session_id=session.session_id,
        ws_url=f"{settings.ws_base_url}/session/{session.session_id}/events",
    )


@app.post("/livekit/token")
async def livekit_token(payload: dict) -> dict:
    if not settings.livekit_url or not settings.livekit_api_key or not settings.livekit_api_secret:
        return {"error": "LiveKit credentials missing"}
    session_id = payload.get("session_id") or store.create_session().session_id
    identity = payload.get("identity", f"caller-{session_id[:6]}")
    token = create_token(
        livekit_url=settings.livekit_url,
        livekit_api_key=settings.livekit_api_key,
        livekit_api_secret=settings.livekit_api_secret,
        room=session_id,
        identity=identity,
        agent_name=settings.livekit_agent_name,
    )
    return token.__dict__


@app.get("/session/{session_id}/tools", response_model=list[ToolCallEvent])
async def get_tool_calls(session_id: str) -> list[ToolCallEvent]:
    return store.list_tool_calls(session_id)


@app.post("/session/{session_id}/tools", response_model=ToolCallEvent)
async def push_tool_call(session_id: str, event: ToolCallEvent) -> ToolCallEvent:
    await _record_tool_event(session_id, event)
    return event


@app.get("/appointments/{contact_number}", response_model=list[Appointment])
async def list_appointments(contact_number: str) -> list[Appointment]:
    return appointment_repo.list_by_contact(contact_number)


@app.post("/appointments", response_model=Appointment)
async def create_appointment(appointment: Appointment) -> Appointment:
    appointments = appointment_repo.list_by_contact(appointment.contact_number)
    for existing in appointments:
        if existing.status != "booked":
            continue
        if existing.date != appointment.date:
            continue
        if _within_buffer(existing.time, appointment.time):
            appointment.status = "conflict"
            return appointment
    try:
        created = appointment_repo.create(appointment)
        return created
    except Exception:
        appointment.status = "conflict"
        return appointment


@app.post("/session/{session_id}/summary", response_model=ConversationSummary)
async def create_summary(session_id: str, summary: ConversationSummary) -> ConversationSummary:
    if summary.contact_number:
        appointments = appointment_repo.list_by_contact(summary.contact_number)
        summary.booked_appointments = [
            appt for appt in appointments if appt.status == "booked"
        ]
    summary_repo.create(summary)
    await manager.broadcast(session_id, {"type": "summary", "payload": summary.model_dump(mode="json")})
    return summary


@app.post("/tools/identify_user")
async def identify_user(payload: dict) -> dict:
    contact_number = payload.get("contact_number")
    event, result = tool_identify_user(contact_number)
    session_id = payload.get("session_id") or store.create_session().session_id
    if contact_number:
        store.set_contact_number(session_id, contact_number)
    await _record_tool_event(session_id, event)
    return {"event": event.model_dump(), "result": result}


@app.post("/tools/fetch_slots")
async def fetch_slots(payload: dict) -> dict:
    event, result = tool_fetch_slots()
    session_id = payload.get("session_id") or store.create_session().session_id
    await _record_tool_event(session_id, event)
    return {"event": event.model_dump(), "result": result}


@app.post("/tools/book_appointment")
async def book_appointment(payload: dict) -> dict:
    appointment = Appointment(**payload["appointment"])
    session_id = payload.get("session_id") or store.create_session().session_id
    if appointment.contact_number:
        store.set_contact_number(session_id, appointment.contact_number)
    stored_contact = store.get_contact_number(session_id)
    if not stored_contact:
        event, result = tool_missing_info(
            "book_appointment",
            "Phone number not confirmed. Ask the user for their phone number first.",
        )
        await _record_tool_event(session_id, event)
        return {"event": event.model_dump(), "result": result}
    if not appointment.contact_number:
        appointment.contact_number = stored_contact
    if not appointment.name.strip():
        event, result = tool_missing_info(
            "book_appointment",
            "Name missing. Ask the user for their name before booking.",
        )
        await _record_tool_event(session_id, event)
        return {"event": event.model_dump(), "result": result}
    try:
        appointment.date, appointment.time = _normalize_date_time(
            appointment.date, appointment.time
        )
    except ValueError:
        event, result = tool_invalid_datetime("book_appointment")
        await _record_tool_event(session_id, event)
        return {"event": event.model_dump(), "result": result}
    created = await create_appointment(appointment)
    event, result = tool_book_appointment(created)
    await _record_tool_event(session_id, event)
    return {"event": event.model_dump(), "result": result}


@app.post("/tools/retrieve_appointments")
async def retrieve_appointments(payload: dict) -> dict:
    contact_number = payload.get("contact_number")
    session_id = payload.get("session_id") or store.create_session().session_id
    if not contact_number:
        event, result = tool_missing_info(
            "retrieve_appointments",
            "Phone number missing. Ask the user for their phone number first.",
        )
        await _record_tool_event(session_id, event)
        return {"event": event.model_dump(), "result": result}
    store.set_contact_number(session_id, contact_number)
    appointments = appointment_repo.list_by_contact(contact_number)
    event, result = tool_retrieve_appointments(contact_number, len(appointments))
    await _record_tool_event(session_id, event)
    result["appointments"] = [appt.model_dump() for appt in appointments]
    return {"event": event.model_dump(), "result": result}


@app.post("/tools/cancel_appointment")
async def cancel_appointment(payload: dict) -> dict:
    contact_number = payload.get("contact_number")
    session_id = payload.get("session_id") or store.create_session().session_id
    if contact_number:
        store.set_contact_number(session_id, contact_number)
    stored_contact = store.get_contact_number(session_id)
    if not stored_contact:
        event, result = tool_missing_info(
            "cancel_appointment",
            "Phone number not confirmed. Ask the user for their phone number first.",
        )
        await _record_tool_event(session_id, event)
        return {"event": event.model_dump(), "result": result}
    date_input = payload.get("date")
    time_input = payload.get("time")
    if not date_input or not time_input:
        event, result = tool_missing_info(
            "cancel_appointment",
            "Date/time missing. Ask the user which appointment to cancel.",
        )
        await _record_tool_event(session_id, event)
        return {"event": event.model_dump(), "result": result}
    try:
        date, time = _normalize_date_time(date_input, time_input)
    except ValueError:
        event, result = tool_invalid_datetime("cancel_appointment")
        await _record_tool_event(session_id, event)
        return {"event": event.model_dump(), "result": result}
    name = payload.get("name")
    appointments = appointment_repo.list_by_contact(stored_contact)
    target = next(
        (
            appt
            for appt in appointments
            if appt.date == date and appt.time == time and (name is None or appt.name == name)
        ),
        None,
    )
    if not target:
        event, result = tool_missing_info(
            "cancel_appointment",
            "No matching appointment found for that date/time.",
        )
        await _record_tool_event(session_id, event)
        return {"event": event.model_dump(), "result": result}
    target.status = "cancelled"
    appointment_repo.update(target)
    event, result = tool_cancel_appointment(date, time, name)
    await _record_tool_event(session_id, event)
    return {"event": event.model_dump(), "result": result}


@app.post("/tools/modify_appointment")
async def modify_appointment(payload: dict) -> dict:
    contact_number = payload.get("contact_number")
    session_id = payload.get("session_id") or store.create_session().session_id
    if contact_number:
        store.set_contact_number(session_id, contact_number)
    stored_contact = store.get_contact_number(session_id)
    if not stored_contact:
        event, result = tool_missing_info(
            "modify_appointment",
            "Phone number not confirmed. Ask the user for their phone number first.",
        )
        await _record_tool_event(session_id, event)
        return {"event": event.model_dump(), "result": result}
    date_input = payload.get("date")
    time_input = payload.get("time")
    new_date_input = payload.get("new_date")
    new_time_input = payload.get("new_time")
    if not date_input or not time_input or not new_date_input or not new_time_input:
        event, result = tool_missing_info(
            "modify_appointment",
            "Missing original or new date/time. Ask the user for both.",
        )
        await _record_tool_event(session_id, event)
        return {"event": event.model_dump(), "result": result}
    try:
        date, time = _normalize_date_time(date_input, time_input)
        new_date, new_time = _normalize_date_time(new_date_input, new_time_input)
    except ValueError:
        event, result = tool_invalid_datetime("modify_appointment")
        await _record_tool_event(session_id, event)
        return {"event": event.model_dump(), "result": result}
    name = payload.get("name")

    appointments = appointment_repo.list_by_contact(stored_contact)
    target = next(
        (
            appt
            for appt in appointments
            if appt.date == date and appt.time == time and (name is None or appt.name == name)
        ),
        None,
    )
    if target:
        # Prevent overlapping within 30 minutes on the same date for the same contact.
        for existing in appointments:
            if existing.id == target.id or existing.status != "booked":
                continue
            if existing.date != new_date:
                continue
            if _within_buffer(existing.time, new_time):
                target.status = "conflict"
                event, result = tool_modify_appointment(target)
                session_id = payload.get("session_id") or store.create_session().session_id
                await _record_tool_event(session_id, event)
                return {"event": event.model_dump(), "result": result}

        target.date = new_date
        target.time = new_time
        appointment_repo.update(target)
        event, result = tool_modify_appointment(target)
    else:
        placeholder = Appointment(
            id="",
            contact_number=stored_contact,
            name=name or "Appointment",
            date=new_date,
            time=new_time,
            status="not_found",
        )
        event, result = tool_missing_info(
            "modify_appointment",
            "No matching appointment found for that date/time.",
        )

    session_id = payload.get("session_id") or store.create_session().session_id
    await _record_tool_event(session_id, event)
    return {"event": event.model_dump(), "result": result}


def _within_buffer(existing_time: str, new_time: str, buffer_minutes: int = 30) -> bool:
    existing_dt = date_parser.parse(existing_time, fuzzy=True)
    new_dt = date_parser.parse(new_time, fuzzy=True)
    delta = abs((existing_dt - new_dt).total_seconds())
    return delta < buffer_minutes * 60


def _normalize_date_time(date_str: str, time_str: str) -> tuple[str, str]:
    # Parse flexible inputs and normalize to ISO date + 24h time for storage.
    try:
        parsed_date = date_parser.parse(date_str, fuzzy=True).date()
        parsed_time = date_parser.parse(time_str, fuzzy=True).time()
    except Exception as exc:
        raise ValueError("invalid datetime") from exc
    return parsed_date.isoformat(), parsed_time.strftime("%H:%M")


@app.post("/tools/end_conversation")
async def end_conversation(payload: dict) -> dict:
    event, result = tool_end_conversation()
    session_id = payload.get("session_id") or store.create_session().session_id
    await _record_tool_event(session_id, event)
    await manager.broadcast(
        session_id, {"type": "session_closed", "payload": {"session_id": session_id}}
    )
    return {"event": event.model_dump(), "result": result}


@app.websocket("/session/{session_id}/events")
async def session_events(session_id: str, websocket: WebSocket) -> None:
    await manager.connect(session_id, websocket)
    await manager.broadcast(
        session_id,
        {
            "type": "status",
            "payload": {"session_id": session_id, "state": "connected"},
        },
    )
    try:
        while True:
            message = await websocket.receive_json()
            if message.get("type") == "ping":
                await websocket.send_json({"type": "pong", "payload": {"at": datetime.utcnow().isoformat()}})
    except WebSocketDisconnect:
        manager.disconnect(session_id, websocket)
