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
"""You are a professional appointment assistant. Keep replies short and focused.
Tone: warm, confident, concise. No long explanations or examples.

Rules:
- Slots are suggestions only; you can book any future date/time the user requests.
- Before any appointment action (book/retrieve/cancel/modify), call identify_user.
- Booking requires name, phone number, date & time, preference (optional) . Ask only what's missing.
- Ask for preferences only once before booking; record only what the user explicitly states.
- Never invent or assume name/phone/date/time. Don't call the user by the assistant's name.
- Speak in natural sentences. Never list field labels.
- Never mention internal IDs or database identifiers in user‑facing speech or summaries.
Formatting:
- Tool inputs: date = YYYY-MM-DD, time = HH:MM (24h).
- Never ask users to speak in those formats; interpret natural language.
- Speak dates/times naturally (e.g., “Tuesday at 9 AM”), never digit-by-digit.
"""
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
        response = await self._post(
            "/tools/book_appointment",
            {"session_id": self._session_id(context), "appointment": appointment},
        )
        event = response.get("event", {})
        result = response.get("result", {})
        if event.get("status") == "completed":
            booked_appt = result.get("appointment", appointment)
            self.state.booked.append(booked_appt)
            if preferences:
                for pref in preferences:
                    cleaned = pref.strip()
                    if cleaned and cleaned not in self.state.preferences:
                        self.state.preferences.append(cleaned)
            self.state.add_action(
                "created",
                f"Booked {self._humanize_date_time(date, time)} for {name}.",
            )
        return response

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
        response = await self._post(
            "/tools/cancel_appointment",
            {
                "session_id": self._session_id(context),
                "contact_number": contact_number,
                "date": date,
                "time": time,
                "name": name,
            },
        )
        event = response.get("event", {})
        if event.get("status") == "completed":
            self._remove_booked_match(contact_number, date, time, name)
            self.state.add_action(
                "cancelled",
                f"Cancelled {self._humanize_date_time(date, time)}"
                f"{f' for {name}' if name else ''}.",
            )
        return response

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
        response = await self._post(
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
        event = response.get("event", {})
        if event.get("status") == "completed":
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
        return response

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
