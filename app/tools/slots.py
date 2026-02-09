from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Slot:
    date: str
    time: str


AVAILABLE_SLOTS = [
    Slot(date="2026-02-10", time="09:00"),
    Slot(date="2026-02-10", time="11:30"),
    Slot(date="2026-02-11", time="14:00"),
    Slot(date="2026-02-12", time="10:15"),
    Slot(date="2026-02-12", time="15:30"),
]


def list_available_slots() -> list[Slot]:
    return list(AVAILABLE_SLOTS)


def format_slot(slot: Slot) -> str:
    dt = datetime.strptime(f"{slot.date} {slot.time}", "%Y-%m-%d %H:%M")
    return dt.strftime("%a %b %d at %-I:%M %p")
