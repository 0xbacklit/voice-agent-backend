from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol

from ..schemas import Appointment, ConversationSummary


class AppointmentRepository(Protocol):
    def create(self, appointment: Appointment) -> Appointment:
        ...

    def list_by_contact(self, contact_number: str) -> list[Appointment]:
        ...

    def update(self, appointment: Appointment) -> Appointment:
        ...


class SummaryRepository(Protocol):
    def create(self, summary: ConversationSummary) -> ConversationSummary:
        ...


@dataclass
class InMemoryAppointmentRepository:
    store: dict[str, Appointment]

    def create(self, appointment: Appointment) -> Appointment:
        self.store[appointment.id] = appointment
        return appointment

    def list_by_contact(self, contact_number: str) -> list[Appointment]:
        return [
            appointment
            for appointment in self.store.values()
            if appointment.contact_number == contact_number
        ]

    def update(self, appointment: Appointment) -> Appointment:
        self.store[appointment.id] = appointment
        return appointment


@dataclass
class InMemorySummaryRepository:
    store: dict[str, ConversationSummary]

    def create(self, summary: ConversationSummary) -> ConversationSummary:
        self.store[summary.session_id] = summary
        return summary


class SupabaseAppointmentRepository:
    def __init__(self, client) -> None:
        self.client = client

    def create(self, appointment: Appointment) -> Appointment:
        payload = appointment.model_dump()
        self.client.table("appointments").insert(payload).execute()
        return appointment

    def list_by_contact(self, contact_number: str) -> list[Appointment]:
        response = (
            self.client.table("appointments")
            .select("*")
            .eq("contact_number", contact_number)
            .execute()
        )
        return [Appointment(**row) for row in response.data or []]

    def update(self, appointment: Appointment) -> Appointment:
        payload = appointment.model_dump()
        self.client.table("appointments").update(payload).eq("id", appointment.id).execute()
        return appointment


class SupabaseSummaryRepository:
    def __init__(self, client) -> None:
        self.client = client

    def create(self, summary: ConversationSummary) -> ConversationSummary:
        payload = summary.model_dump(mode="json")
        self.client.table("summaries").insert(payload).execute()
        return summary


def build_repositories(supabase_url: str | None, supabase_key: str | None):
    if not supabase_url or not supabase_key:
        raise ValueError("Missing Supabase configuration (SUPABASE_URL/SUPABASE_KEY).")

    from supabase import create_client

    client = create_client(supabase_url, supabase_key)
    appointment_repo = SupabaseAppointmentRepository(client)
    summary_repo = SupabaseSummaryRepository(client)
    return appointment_repo, summary_repo
