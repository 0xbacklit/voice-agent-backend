from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx
from livekit.agents import Agent, RunContext, function_tool


@dataclass
class AgentState:
    contact_number: str | None = None
    booked: list[dict] = field(default_factory=list)
    preferences: list[str] = field(default_factory=list)
    actions: list[dict] = field(default_factory=list)
    tool_calls: int = 0
    info_notes: list[str] = field(default_factory=list)

    def add_action(self, action: str, detail: str) -> None:
        self.actions.append(
            {
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "action": action,
                "detail": detail,
            }
        )

    def record_tool(self, name: str) -> None:
        self.tool_calls += 1
        if name == "fetch_slots":
            self.info_notes.append("Reviewed available time slots.")
        elif name == "retrieve_appointments":
            self.info_notes.append("Checked existing appointments.")


class VoiceBookingAgent(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions=(
                "You are a calm, friendly scheduling assistant. "
                "You can identify callers, fetch available slots, book, modify, cancel, "
                "or retrieve appointments, and end the conversation with a summary. "
                "Available slots are suggestions only; you can book any future date/time the user requests. "
                "Do not force the user to pick only from available slots. "
                "Only call fetch_slots if the user explicitly asks for available times. "
                "Always confirm date, time, and contact number before booking. "
                "Never call the user by the assistant's name. If the user name is unknown, avoid using a name. "
                "Never assume or invent a phone number, name, date, or time. "
                "If the user has not provided a phone number, ask for it before retrieving or booking. "
                "Once the phone number is confirmed, do not ask again unless the user changes it. "
                "Ask only for the next required detail. "
                "Before booking, ask: 'Do you have any preferences?' If the user says none, proceed without preferences. "
                "Only record preferences explicitly stated by the user (e.g., morning slot, quiet office). "
                "Know the tool requirements and collect missing fields before calling: "
                "identify_user requires phone; book_appointment requires name, phone, date, time; "
                "retrieve_appointments requires phone; cancel_appointment requires phone, date, time; "
                "modify_appointment requires phone, name, original date/time, new date/time. "
                "Only call book_appointment after the user has explicitly confirmed the date and time. "
                "When calling tools, always use date in YYYY-MM-DD format and time in HH:MM (24-hour). "
                "Never ask the user to speak in those formats; interpret natural language and convert internally. "
                "When speaking any date or time (slots, booked, modified, cancelled, or retrieved), "
                "always use a natural human format like 'Tuesday, February 10 at 9:00 AM'. "
                "Never read digits one by one and never say date formats like '2026-02-10'."
            )
        )
        self.backend_base_url = os.getenv("BACKEND_BASE_URL", "http://localhost:8000")
        self.state = AgentState()

    def _humanize_timestamp(self, iso_ts: str) -> str:
        try:
            ts = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
            return ts.strftime("%b %d, %Y %I:%M %p UTC")
        except Exception:
            return iso_ts

    def _humanize_date_time(self, date: str, time: str) -> str:
        try:
            date_part = datetime.strptime(date, "%Y-%m-%d").strftime("%a %b %d, %Y")
        except Exception:
            date_part = date
        try:
            time_part = datetime.strptime(time, "%H:%M").strftime("%I:%M %p").lstrip("0")
        except Exception:
            time_part = time
        return f"{date_part} at {time_part}"

    def _remove_booked_match(
        self, contact_number: str | None, date: str, time: str, name: str | None
    ) -> list[dict[str, Any]]:
        removed: list[dict[str, Any]] = []
        remaining: list[dict[str, Any]] = []
        for appt in self.state.booked:
            if contact_number and appt.get("contact_number") != contact_number:
                remaining.append(appt)
                continue
            if name and appt.get("name") != name:
                remaining.append(appt)
                continue
            if appt.get("date") == date and appt.get("time") == time:
                removed.append(appt)
            else:
                remaining.append(appt)
        self.state.booked = remaining
        return removed

    def _session_id(self, context: RunContext) -> str:
        try:
            return context.session.userdata.get("session_id", "unknown")  # type: ignore[union-attr]
        except Exception:
            return "unknown"

    async def _post(self, path: str, payload: dict) -> dict:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(f"{self.backend_base_url}{path}", json=payload)
            response.raise_for_status()
            return response.json()

    @function_tool()
    async def identify_user(self, context: RunContext, contact_number: str) -> dict:
        """Identify the user by phone number."""
        self.state.record_tool("identify_user")
        self.state.contact_number = contact_number
        return await self._post(
            "/tools/identify_user",
            {"session_id": self._session_id(context), "contact_number": contact_number},
        )

    @function_tool()
    async def fetch_slots(self, context: RunContext) -> dict:
        """Fetch available appointment slots."""
        self.state.record_tool("fetch_slots")
        return await self._post(
            "/tools/fetch_slots",
            {"session_id": self._session_id(context)},
        )

    @function_tool()
    async def book_appointment(
        self,
        context: RunContext,
        name: str,
        contact_number: str,
        date: str,
        time: str,
        preferences: list[str] | None = None,
    ) -> dict:
        """Book an appointment for a user."""
        self.state.record_tool("book_appointment")
        appointment = {
            "id": uuid.uuid4().hex,
            "contact_number": contact_number,
            "name": name,
            "date": date,
            "time": time,
            "confirmed_by_user": True,
            "status": "booked",
        }
        self.state.booked.append(appointment)
        if preferences:
            for pref in preferences:
                cleaned = pref.strip()
                if cleaned and cleaned not in self.state.preferences:
                    self.state.preferences.append(cleaned)
        self.state.add_action(
            "created",
            f"Booked {self._humanize_date_time(date, time)} for {name}.",
        )
        return await self._post(
            "/tools/book_appointment",
            {"session_id": self._session_id(context), "appointment": appointment},
        )

    @function_tool()
    async def retrieve_appointments(self, context: RunContext, contact_number: str) -> dict:
        """Retrieve existing appointments for a contact number."""
        self.state.record_tool("retrieve_appointments")
        return await self._post(
            "/tools/retrieve_appointments",
            {"session_id": self._session_id(context), "contact_number": contact_number},
        )

    @function_tool()
    async def cancel_appointment(
        self,
        context: RunContext,
        contact_number: str,
        date: str,
        time: str,
        name: str | None = None,
    ) -> dict:
        """Cancel an existing appointment."""
        self.state.record_tool("cancel_appointment")
        self._remove_booked_match(contact_number, date, time, name)
        self.state.add_action(
            "cancelled",
            f"Cancelled {self._humanize_date_time(date, time)}"
            f"{f' for {name}' if name else ''}.",
        )
        return await self._post(
            "/tools/cancel_appointment",
            {
                "session_id": self._session_id(context),
                "contact_number": contact_number,
                "date": date,
                "time": time,
                "name": name,
            },
        )

    @function_tool()
    async def modify_appointment(
        self,
        context: RunContext,
        contact_number: str,
        date: str,
        time: str,
        name: str,
        new_date: str,
        new_time: str,
    ) -> dict:
        """Modify an appointment date or time."""
        self.state.record_tool("modify_appointment")
        removed = self._remove_booked_match(contact_number, date, time, name)
        if removed:
            updated = removed[0]
            updated["date"] = new_date
            updated["time"] = new_time
            self.state.booked.append(updated)
        self.state.add_action(
            "modified",
            f"Rescheduled {name} from {self._humanize_date_time(date, time)} "
            f"to {self._humanize_date_time(new_date, new_time)}.",
        )
        return await self._post(
            "/tools/modify_appointment",
            {
                "session_id": self._session_id(context),
                "contact_number": contact_number,
                "name": name,
                "date": date,
                "time": time,
                "new_date": new_date,
                "new_time": new_time,
            },
        )

    @function_tool()
    async def end_conversation(
        self, context: RunContext, preferences: list[str] | None = None
    ) -> dict:
        """End the conversation and generate a summary."""
        if hasattr(context, "session") and context.session is not None:
            if self.state.tool_calls == 0 and not self.state.preferences:
                await context.session.say(
                    "Understood. Ending the call now.",
                    allow_interruptions=False,
                )
                return await self._post(
                    "/tools/end_conversation",
                    {"session_id": self._session_id(context)},
                )
            await context.session.say(
                "Let me create a summary of this conversation for you.",
                allow_interruptions=False,
            )
        # Do not record preferences at end; only capture during booking when user states them.
        created = [a for a in self.state.actions if a["action"] == "created"]
        cancelled = [a for a in self.state.actions if a["action"] == "cancelled"]
        modified = [a for a in self.state.actions if a["action"] == "modified"]

        summary_parts: list[str] = ["Here’s a quick recap of what we covered."]

        if created:
            created_lines = [item["detail"] for item in created]
            summary_parts.append("Booked: " + "; ".join(created_lines))
        if modified:
            modified_lines = [item["detail"] for item in modified]
            summary_parts.append("Updated: " + "; ".join(modified_lines))
        if cancelled:
            cancelled_lines = [item["detail"] for item in cancelled]
            summary_parts.append("Cancelled: " + "; ".join(cancelled_lines))

        if not (created or modified or cancelled):
            summary_parts.append("No appointments were booked, changed, or cancelled.")
            if self.state.info_notes:
                summary_parts.append("We also " + " ".join(self.state.info_notes))

        if self.state.preferences:
            summary_parts.append("Preferences noted: " + ", ".join(self.state.preferences) + ".")
        else:
            summary_parts.append("Preferences noted: none.")

        summary_parts.append(
            f"Call ended at {datetime.utcnow().strftime('%b %d, %Y %I:%M %p UTC')}."
        )

        summary_text = " ".join(summary_parts)
        summary_payload = {
            "session_id": self._session_id(context),
            "contact_number": self.state.contact_number,
            "summary": summary_text,
            "booked_appointments": self.state.booked,
            "preferences": self.state.preferences,
        }
        await self._post(
            f"/session/{self._session_id(context)}/summary",
            summary_payload,
        )
        if hasattr(context, "session") and context.session is not None:
            await context.session.say(
                "Your summary is ready. You can view it in the Summary panel on the right. "
                "Ending this call now.",
                allow_interruptions=False,
            )
        return await self._post(
            "/tools/end_conversation",
            {"session_id": self._session_id(context)},
        )
