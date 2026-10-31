"""Add an idempotent, non-destructive released-slot demo cohort.

Run with DATABASE_URL set. Existing operational records are never changed or
deleted. The four DEMO-OVERSEER-* patients are created only when absent.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.database import session_scope
from app.models import Appointment, AppointmentType, Goal, Patient, Referral, Slot


PREFIX = "DEMO-OVERSEER-"


def weekday_at(days: int, hour: int = 13) -> datetime:
    value = datetime.now(UTC).replace(hour=hour, minute=0, second=0, microsecond=0) + timedelta(days=days)
    while value.weekday() >= 5:
        value += timedelta(days=1)
    return value


def seed() -> dict:
    with session_scope() as session:
        existing = session.scalars(select(Patient).where(Patient.external_ref.like(f"{PREFIX}%"))).all()
        if existing:
            return {"created": False, "patients": [patient.external_ref for patient in existing]}
        appointment_type = session.scalar(select(AppointmentType).where(AppointmentType.code == "MRI"))
        if not appointment_type:
            appointment_type = session.scalar(select(AppointmentType).where(AppointmentType.name.ilike("%MRI%")))
        if not appointment_type:
            raise RuntimeError("Create the MRI appointment type before seeding the overseer demo")

        records = [
            ("SOURCE", "Sam", "Reed", "ROUTINE", 3),
            ("PRIYA", "Priya", "Shah", "URGENT", 18),
            ("BOB", "Bob", "Martin", "SOON", 30),
            ("ELENA", "Elena", "Kovac", "ROUTINE", 45),
        ]
        created: dict[str, dict] = {}
        for suffix, first, last, urgency, booked_days in records:
            patient = Patient(
                external_ref=f"{PREFIX}{suffix}", first_name=first, last_name=last,
                date_of_birth=datetime(1975, 4, 17, tzinfo=UTC), phone=None,
                preferred_contact_method="VOICE", preferred_language="English", constraints={},
            )
            referral = Referral(
                patient=patient, appointment_type_id=appointment_type.id,
                pathway_type="Appointment scheduling", procedure=appointment_type.name,
                provider_org="nous scheduling", status="ACTIVE",
            )
            goal = Goal(
                referral=referral, description=f"Complete {appointment_type.name} appointment",
                success_criteria={"clinician_urgency": urgency}, status="WAITING", version=1,
            )
            slot = Slot(
                external_ref=f"demo-overseer-booked-{suffix.lower()}", appointment_type_id=appointment_type.id,
                provider_org="nous scheduling", site="Main site", procedure=appointment_type.name,
                starts_at=weekday_at(booked_days), duration_minutes=120,
                properties={"source": "overseer_golden_path"}, status="BOOKED",
            )
            session.add_all([patient, referral, goal, slot]); session.flush()
            session.add(Appointment(referral_id=referral.id, slot_id=slot.id, status="BOOKED"))
            created[suffix] = {"patient": patient, "goal": goal, "slot": slot}

        replacement = Slot(
            external_ref="demo-overseer-source-replacement", appointment_type_id=appointment_type.id,
            provider_org="nous scheduling", site="Main site", procedure=appointment_type.name,
            starts_at=weekday_at(40, 15), duration_minutes=120,
            properties={"source": "overseer_golden_path"}, status="AVAILABLE",
        )
        session.add(replacement); session.flush()
        return {
            "created": True,
            "source_goal_id": str(created["SOURCE"]["goal"].id),
            "replacement_slot_id": str(replacement.id),
            "expected_first_choice": created["PRIYA"]["patient"].external_ref,
            "phone_url_after_selection": f"/phone?claim={created['PRIYA']['patient'].external_ref}",
        }


if __name__ == "__main__":
    print(seed())
