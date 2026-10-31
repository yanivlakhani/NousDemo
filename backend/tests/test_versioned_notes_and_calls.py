from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.main import CallRequest, case_note_json
from app.models import CaseNoteVersion, Communication
from app.records import REMINDER_LEAD_HOURS, elevenlabs_call_payload, language_code, reminder_wake_at


def test_call_contract_rejects_unknown_purpose():
    with pytest.raises(ValidationError):
        CallRequest(goal_id=uuid4(), patient_first_name="Jo", phone_number="+44123", reason="Test", purpose="SALES")


def test_typed_call_columns_and_reminder_policy_are_explicit():
    assert {"purpose", "outcome", "summary", "language"} <= set(Communication.__table__.c.keys())
    assert REMINDER_LEAD_HOURS == 48


def test_elevenlabs_payload_sets_language_and_typed_dynamic_variables():
    payload = elevenlabs_call_payload(agent_id="agent", phone_number_id="phone", to_number="+44123", patient_first_name="Jo", goal_id=uuid4(), reason="Earlier slot", purpose="EARLIER_SLOT_OFFER", preferred_language="Polish")
    variables = payload["conversation_initiation_client_data"]["dynamic_variables"]
    assert payload["conversation_config_override"]["agent"]["language"] == "pl"
    assert variables["preferred_language"] == "pl"
    assert variables["purpose"] == "EARLIER_SLOT_OFFER"
    assert language_code("Not configured") == "en"
    assert language_code("Hindi") == "hi"


def test_case_note_serialization_exposes_immutable_version_and_provenance():
    now, note_id, revision_id = datetime.now(UTC), uuid4(), uuid4()
    note = SimpleNamespace(id=note_id, category="ADMIN", text="Current", language="English", source="OPERATOR", current_version_id=revision_id, created_at=now)
    revision = SimpleNamespace(id=revision_id, note_id=note_id, version=2, category="ADMIN", text="Current", language="English", source="OPERATOR", supersedes_id=uuid4(), created_at=now)
    result = case_note_json(note, [revision])
    assert result["current_version"] == 2
    assert result["provenance"] == "OPERATOR"
    assert result["versions"][0]["current"] is True
    assert "supersedes_id" in result["versions"][0]


def test_case_note_revision_schema_has_stable_identity_and_unique_version():
    assert {"note_id", "version", "supersedes_id", "source"} <= set(CaseNoteVersion.__table__.c.keys())


def test_reminder_wake_is_48_hours_before_appointment():
    now = datetime(2026, 10, 15, 9, tzinfo=UTC)
    appointment = datetime(2026, 10, 20, 14, tzinfo=UTC)
    assert reminder_wake_at(appointment, now=now) == datetime(2026, 10, 18, 14, tzinfo=UTC)


def test_reminder_is_due_now_when_booking_inside_window():
    now = datetime(2026, 10, 15, 12, tzinfo=UTC)
    appointment = datetime(2026, 10, 16, 14, tzinfo=UTC)
    assert reminder_wake_at(appointment, now=now) == now


def test_reminder_wake_handles_non_utc_aware_datetimes_by_instant():
    london_winter = timezone(timedelta(hours=0))
    now = datetime(2026, 10, 15, 9, tzinfo=UTC)
    appointment = datetime(2026, 10, 20, 14, tzinfo=london_winter)
    assert reminder_wake_at(appointment, now=now) == datetime(2026, 10, 18, 14, tzinfo=london_winter)


@pytest.mark.parametrize(
    ("appointment", "now"),
    [
        (datetime(2026, 10, 20, 14), datetime(2026, 10, 15, 9, tzinfo=UTC)),
        (datetime(2026, 10, 20, 14, tzinfo=UTC), datetime(2026, 10, 15, 9)),
    ],
)
def test_reminder_wake_rejects_naive_datetimes(appointment, now):
    with pytest.raises(ValueError, match="timezone-aware"):
        reminder_wake_at(appointment, now=now)
