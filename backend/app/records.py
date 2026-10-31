from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import func, select

from app.models import CaseNote, CaseNoteVersion


CALL_PURPOSES = {"REMINDER", "RESCHEDULE", "EARLIER_SLOT_OFFER", "FOLLOW_UP"}
CALL_OUTCOMES = {"QUEUED", "ANSWERED", "DECLINED", "NO_ANSWER", "FAILED", "ESCALATED"}
REMINDER_LEAD_HOURS = 48
LANGUAGE_CODES = {
    "english": "en", "spanish": "es", "polish": "pl", "turkish": "tr",
    "arabic": "ar", "romanian": "ro", "mandarin": "zh", "urdu": "ur",
    "ukrainian": "uk", "portuguese": "pt", "gujarati": "gu", "czech": "cs",
    "hindi": "hi",
}


def language_code(name: str | None) -> str:
    return LANGUAGE_CODES.get((name or "English").strip().lower(), "en")


def reminder_wake_at(appointment_at: datetime, *, now: datetime | None = None) -> datetime:
    """Return the durable wake for the 48-hour reminder, due now if already inside the window."""
    clock = now or datetime.now(UTC)
    if appointment_at.tzinfo is None or clock.tzinfo is None:
        raise ValueError("appointment_at and now must be timezone-aware")
    return max(clock, appointment_at - timedelta(hours=REMINDER_LEAD_HOURS))


def elevenlabs_call_payload(*, agent_id: str, phone_number_id: str, to_number: str, patient_first_name: str, goal_id, reason: str, purpose: str, preferred_language: str, proposed_slot_id=None) -> dict:
    code = language_code(preferred_language)
    return {"agent_id": agent_id, "agent_phone_number_id": phone_number_id, "to_number": to_number,
            "conversation_config_override": {"agent": {"language": code}},
            "conversation_initiation_client_data": {"dynamic_variables": {
                "patient_first_name": patient_first_name, "goal_id": str(goal_id), "reason": reason,
                "purpose": purpose, "preferred_language": code, "proposed_slot_id": str(proposed_slot_id or ""),
            }}}


def create_note(session, *, patient_id, referral_id, goal_id, category: str, text: str, language: str, source: str) -> CaseNote:
    note = CaseNote(id=uuid4(), patient_id=patient_id, referral_id=referral_id, goal_id=goal_id, category=category, text=text, language=language, source=source)
    revision = CaseNoteVersion(id=uuid4(), note_id=note.id, version=1, category=category, text=text, language=language, source=source)
    session.add_all([note, revision]); session.flush(); note.current_version_id = revision.id
    return note


def revise_note(session, note: CaseNote, *, category: str, text: str, language: str, source: str) -> CaseNoteVersion:
    latest = session.scalar(select(func.max(CaseNoteVersion.version)).where(CaseNoteVersion.note_id == note.id)) or 0
    revision = CaseNoteVersion(note_id=note.id, version=latest + 1, category=category, text=text, language=language, source=source, supersedes_id=note.current_version_id)
    session.add(revision); session.flush()
    note.category, note.text, note.language, note.source, note.current_version_id = category, text, language, source, revision.id
    return revision
