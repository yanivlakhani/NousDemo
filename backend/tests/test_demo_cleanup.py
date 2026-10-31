from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

from app.demo_cleanup import _payload_mentions, choose_canonical_appointment, cleanup_demo_state
from app.models import Appointment, Patient, Slot


NOW = datetime(2026, 10, 15, 12, tzinfo=UTC)


def appointment(status: str, starts_at: datetime, suffix: int) -> Appointment:
    slot = Slot(
        id=UUID(f"20000000-0000-0000-0000-{suffix:012d}"),
        external_ref=f"demo-slot-{suffix}",
        provider_org="nous",
        site="Main site",
        procedure="MRI",
        starts_at=starts_at,
        duration_minutes=120,
        properties={"source": "test"},
        status="BOOKED" if status == "BOOKED" else "HELD",
    )
    return Appointment(
        id=UUID(f"30000000-0000-0000-0000-{suffix:012d}"),
        referral_id=UUID("40000000-0000-0000-0000-000000000001"),
        slot_id=slot.id,
        slot=slot,
        status=status,
        created_at=NOW + timedelta(minutes=suffix),
    )


def test_canonical_appointment_keeps_existing_booking_over_offer():
    booked = appointment("BOOKED", NOW + timedelta(days=30), 1)
    offered = appointment("OFFERED", NOW + timedelta(days=1), 2)

    assert choose_canonical_appointment([offered, booked], NOW) is booked


def test_canonical_appointment_restores_earliest_future_offer_when_booking_missing():
    old_decline = appointment("DECLINED", NOW - timedelta(days=1), 1)
    later_offer = appointment("OFFERED", NOW + timedelta(days=2), 2)
    earlier_offer = appointment("OFFERED", NOW + timedelta(days=1), 3)

    assert choose_canonical_appointment([old_decline, later_offer, earlier_offer], NOW) is earlier_offer


def test_canonical_appointment_does_not_invent_booking_from_history():
    declined = appointment("DECLINED", NOW - timedelta(days=1), 1)
    rescheduled = appointment("RESCHEDULED", NOW - timedelta(days=2), 2)

    assert choose_canonical_appointment([declined, rescheduled], NOW) is None


def test_payload_reference_detection_is_recursive_and_exact():
    target = "30000000-0000-0000-0000-000000000001"

    assert _payload_mentions({"nested": [{"appointment_id": target}]}, {target})
    assert not _payload_mentions({"appointment_id": f"prefix-{target}"}, {target})


class Rows:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class SequenceSession:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.deleted = []

    def scalars(self, _statement):
        return Rows(next(self.responses))

    def delete(self, row):
        self.deleted.append(row)


def test_cleanup_is_a_noop_for_a_coherent_demo_case():
    patient = Patient(
        id=UUID("10000000-0000-0000-0000-000000000001"),
        external_ref="DEMO-CANONICAL-1",
        first_name="Demo",
        last_name="Patient",
        date_of_birth=datetime(1980, 1, 1, tzinfo=UTC),
        phone="+447700900001",
        preferred_language="English",
        constraints={},
    )
    referral = SimpleNamespace(id=UUID("40000000-0000-0000-0000-000000000001"), patient_id=patient.id)
    goal = SimpleNamespace(
        id=UUID("50000000-0000-0000-0000-000000000001"), referral_id=referral.id,
        status="WAITING", current_blocker=None, next_wake_at=None,
    )
    booked = appointment("BOOKED", NOW + timedelta(days=10), 1)
    responses = [
        [patient], [referral], [goal], [patient.phone], [booked],
        [], [], [], [], [], [],
    ]
    session = SequenceSession(responses)

    result = cleanup_demo_state(session)

    assert result["patients_retained"] == 1
    assert sum(value for key, value in result.items() if key != "patients_retained") == 0
    assert session.deleted == []
