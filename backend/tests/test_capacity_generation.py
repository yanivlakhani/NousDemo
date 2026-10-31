from datetime import UTC, datetime
from uuid import UUID

import pytest

from app.capacity import _automatic_slot_ref, _weekday_starts, ensure_weekday_capacity
from app.models import AppointmentType


class ScalarRows:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class CapacitySession:
    def __init__(self, appointment_types, existing_refs=()):
        self.appointment_types = appointment_types
        self.existing_refs = list(existing_refs)
        self.added = []
        self.scalar_calls = 0

    def scalars(self, _statement):
        self.scalar_calls += 1
        rows = self.appointment_types if self.scalar_calls == 1 else self.existing_refs
        return ScalarRows(rows)

    def add_all(self, rows):
        self.added.extend(rows)


def appointment_type(code="MRI", duration=30, active=True):
    return AppointmentType(
        id=UUID("20000000-0000-0000-0000-000000000001"),
        code=code,
        name=code,
        default_duration_minutes=duration,
        is_active=active,
    )


def test_weekday_starts_fill_clinic_hours_and_skip_weekends():
    starts = _weekday_starts(datetime(2026, 10, 16, 8, tzinfo=UTC), 60, 4)  # Friday through Monday

    assert len(starts) == 16
    assert {value.weekday() for value in starts} == {0, 4}
    assert {value.hour for value in starts} == set(range(9, 17))


def test_ensure_capacity_uses_type_duration_and_deterministic_refs():
    session = CapacitySession([appointment_type(duration=120)])
    now = datetime(2026, 10, 15, 8, tzinfo=UTC)

    result = ensure_weekday_capacity(session, now=now, horizon_days=1)

    assert result == {"created": 4, "already_present": 0, "appointment_types": 1, "horizon_days": 1, "duration_override_minutes": None}
    assert [slot.starts_at.hour for slot in session.added] == [9, 11, 13, 15]
    assert all(slot.duration_minutes == 120 for slot in session.added)
    assert all(slot.appointment_type_id == session.appointment_types[0].id for slot in session.added)
    assert session.added[0].external_ref == _automatic_slot_ref(session.appointment_types[0], session.added[0].starts_at)


def test_existing_automatic_slots_are_not_modified_or_recreated():
    kind = appointment_type(duration=240)
    now = datetime(2026, 10, 15, 8, tzinfo=UTC)
    starts = _weekday_starts(now, 240, 1)
    existing_refs = [_automatic_slot_ref(kind, value) for value in starts]
    session = CapacitySession([kind], existing_refs)

    result = ensure_weekday_capacity(session, now=now, horizon_days=1)

    assert result["created"] == 0
    assert result["already_present"] == 2
    assert session.added == []


def test_demo_override_creates_scarce_capacity_without_changing_type_configuration():
    kind = appointment_type(duration=30)
    session = CapacitySession([kind])

    result = ensure_weekday_capacity(
        session,
        now=datetime(2026, 10, 15, 8, tzinfo=UTC),
        horizon_days=1,
        duration_override_minutes=120,
    )

    assert result["created"] == 4
    assert result["duration_override_minutes"] == 120
    assert kind.default_duration_minutes == 30
    assert [slot.duration_minutes for slot in session.added] == [120] * 4
    assert {slot.properties["capacity_profile"] for slot in session.added} == {"demo_scarce"}


def test_capacity_rejects_naive_clock():
    with pytest.raises(ValueError, match="timezone-aware"):
        ensure_weekday_capacity(CapacitySession([]), now=datetime(2026, 10, 15), horizon_days=1)


def test_capacity_rejects_non_positive_demo_duration():
    with pytest.raises(ValueError, match="duration_override_minutes must be positive"):
        ensure_weekday_capacity(
            CapacitySession([]),
            now=datetime(2026, 10, 15, 8, tzinfo=UTC),
            duration_override_minutes=0,
        )
