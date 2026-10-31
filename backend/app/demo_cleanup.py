from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
import re

from sqlalchemy import or_, select

from app.models import (
    Action,
    AgentStep,
    AgentToolCall,
    Appointment,
    CaseDocument,
    CaseDocumentVersion,
    CaseNote,
    CaseNoteVersion,
    Communication,
    Event,
    Goal,
    GoalDecision,
    Patient,
    Referral,
    Slot,
)


DEMO_PREFIX = "DEMO-"
E164_RE = re.compile(r"^\+[1-9]\d{7,14}$")


def _demo_patients(session) -> list[Patient]:
    return list(
        session.scalars(
            select(Patient)
            .where(Patient.external_ref.like(f"{DEMO_PREFIX}%"))
            .order_by(Patient.external_ref)
        ).all()
    )


def audit_demo_state(session) -> dict:
    """Return a read-only, JSON-safe inventory and invariant report for DEMO-* cases.

    Every scoped row is reached from a patient whose external reference starts
    with ``DEMO-``. Slots are reported separately because they are capacity
    records and may be shared; merely being linked to a demo appointment never
    makes a slot safe to delete.
    """
    patients = _demo_patients(session)
    patient_ids = [row.id for row in patients]
    referrals = list(session.scalars(select(Referral).where(Referral.patient_id.in_(patient_ids))).all()) if patient_ids else []
    referral_ids = [row.id for row in referrals]
    goals = list(session.scalars(select(Goal).where(Goal.referral_id.in_(referral_ids))).all()) if referral_ids else []
    goal_ids = [row.id for row in goals]
    appointments = list(session.scalars(select(Appointment).where(Appointment.referral_id.in_(referral_ids))).all()) if referral_ids else []
    slot_ids = list({row.slot_id for row in appointments})
    slots = list(session.scalars(select(Slot).where(Slot.id.in_(slot_ids))).all()) if slot_ids else []
    actions = list(session.scalars(select(Action).where(Action.goal_id.in_(goal_ids))).all()) if goal_ids else []
    decisions = list(session.scalars(select(GoalDecision).where(GoalDecision.goal_id.in_(goal_ids))).all()) if goal_ids else []
    events = list(session.scalars(select(Event).where(Event.goal_id.in_(goal_ids))).all()) if goal_ids else []
    calls = list(session.scalars(select(Communication).where(Communication.goal_id.in_(goal_ids))).all()) if goal_ids else []
    notes = list(session.scalars(select(CaseNote).where(CaseNote.patient_id.in_(patient_ids))).all()) if patient_ids else []
    note_ids = [row.id for row in notes]
    note_versions = list(session.scalars(select(CaseNoteVersion).where(CaseNoteVersion.note_id.in_(note_ids))).all()) if note_ids else []
    documents = list(session.scalars(select(CaseDocument).where(CaseDocument.goal_id.in_(goal_ids))).all()) if goal_ids else []
    document_ids = [row.id for row in documents]
    document_versions = list(session.scalars(select(CaseDocumentVersion).where(CaseDocumentVersion.document_id.in_(document_ids))).all()) if document_ids else []
    steps = list(session.scalars(select(AgentStep).where(AgentStep.goal_id.in_(goal_ids))).all()) if goal_ids else []
    step_ids = [row.id for row in steps]
    tool_calls = list(session.scalars(select(AgentToolCall).where(AgentToolCall.step_id.in_(step_ids))).all()) if step_ids else []
    now = datetime.now(UTC)
    capacity_slots = list(session.scalars(
        select(Slot).where(
            Slot.external_ref.like("auto:%"), Slot.starts_at >= now,
            Slot.starts_at < now + timedelta(days=2),
        )
    ).all())

    violations: list[dict[str, str]] = []

    def add(code: str, ref: str, detail: str) -> None:
        violations.append({"code": code, "ref": ref, "detail": detail})

    phone_counts = Counter(row.phone for row in session.scalars(select(Patient).where(Patient.phone.is_not(None))).all())
    referrals_by_patient = Counter(row.patient_id for row in referrals)
    goals_by_referral = Counter(row.referral_id for row in goals)
    appointments_by_referral: dict = {}
    for row in appointments:
        appointments_by_referral.setdefault(row.referral_id, []).append(row)
    patient_ref = {row.id: row.external_ref for row in patients}
    referral_ref = {row.id: patient_ref[row.patient_id] for row in referrals}
    goal_ref = {row.id: referral_ref[row.referral_id] for row in goals}
    slot_by_id = {row.id: row for row in slots}

    for patient in patients:
        ref = patient.external_ref
        if not patient.date_of_birth:
            add("MISSING_DOB", ref, "date_of_birth is required")
        if not patient.phone or not E164_RE.fullmatch(patient.phone):
            add("INVALID_PHONE", ref, "phone must be unique E.164")
        elif phone_counts[patient.phone] != 1:
            add("DUPLICATE_PHONE", ref, "phone is not unique")
        if not (patient.preferred_language or "").strip():
            add("MISSING_LANGUAGE", ref, "preferred_language is required")
        if referrals_by_patient[patient.id] != 1:
            add("REFERRAL_CARDINALITY", ref, f"expected 1 referral, found {referrals_by_patient[patient.id]}")

    for referral in referrals:
        ref = referral_ref[referral.id]
        if goals_by_referral[referral.id] != 1:
            add("GOAL_CARDINALITY", ref, f"expected 1 goal, found {goals_by_referral[referral.id]}")
        related = appointments_by_referral.get(referral.id, [])
        booked = [row for row in related if row.status == "BOOKED"]
        open_offers = [row for row in related if row.status == "OFFERED"]
        if len(related) != 1:
            add("APPOINTMENT_CARDINALITY", ref, f"expected 1 coherent appointment, found {len(related)}")
        if len(booked) != 1:
            add("BOOKED_APPOINTMENT_CARDINALITY", ref, f"expected 1 booked appointment, found {len(booked)}")
        if open_offers:
            goal = next((row for row in goals if row.referral_id == referral.id), None)
            communicated = bool(goal and any(call.goal_id == goal.id and call.purpose == "EARLIER_SLOT_OFFER" and call.outcome in {"ANSWERED", "DECLINED", "NO_ANSWER"} for call in calls))
            if not communicated:
                add("UNCOMMUNICATED_OPEN_OFFER", ref, f"{len(open_offers)} open offer(s) without a completed call")

    delegation_types = {"CALL_PATIENT", "EARLIER_SLOT_OFFER"}
    active_statuses = {"PROPOSED", "QUEUED", "RUNNING", "IN_PROGRESS"}
    for action in actions:
        if action.action_type in delegation_types and action.status in active_statuses:
            matching_event = any(
                event.goal_id == action.goal_id
                and event.event_type in {"OVERSEER_DELEGATED", "BROWSER_CALL_QUEUED"}
                and str((event.payload or {}).get("action_id", "")) in {"", str(action.id)}
                for event in events
            )
            if not matching_event:
                add("ACTIVE_DELEGATION_WITHOUT_EVENT", goal_ref[action.goal_id], f"action {action.id} is {action.status}")

    for goal in goals:
        ref = goal_ref[goal.id]
        if goal.status == "HUMAN_REVIEW_REQUIRED":
            add("STALE_HUMAN_REVIEW", ref, "demo goal is still in human review")
        if goal.status == "WAITING" and goal.current_blocker:
            add("STALE_WAITING_BLOCKER", ref, "waiting demo goal still has a blocker")
        if goal.status == "WAITING" and goal.next_wake_at and goal.next_wake_at <= now:
            add("STALE_WAITING_WAKE", ref, "waiting demo goal has an overdue wake")

    declined_goal_ids = {call.goal_id for call in calls if call.outcome == "DECLINED"}
    for appointment in appointments:
        goal = next((row for row in goals if row.referral_id == appointment.referral_id), None)
        slot = slot_by_id.get(appointment.slot_id)
        if goal and goal.id in declined_goal_ids and slot and (slot.properties or {}).get("released_gap"):
            add("DECLINE_RELEASED_SLOT", goal_ref[goal.id], f"slot {slot.id} is marked released after a declined call")

    for call in calls:
        text = f"{call.summary or ''} {call.transcript or ''}".lower()
        if call.outcome == "FAILED" or "404" in text:
            add("FAILED_CALL_NOISE", goal_ref[call.goal_id], f"communication {call.id}")
    for step in steps:
        if step.outcome != "COMPLETED" or "404" in (step.error or "").lower() or "phone number" in (step.error or "").lower():
            add("FAILED_RUN_NOISE", goal_ref[step.goal_id], f"agent step {step.id}")

    for note in notes:
        versions = [row for row in note_versions if row.note_id == note.id]
        if not versions or not note.current_version_id or note.current_version_id not in {row.id for row in versions}:
            add("BROKEN_NOTE_VERSION", patient_ref[note.patient_id], f"case note {note.id} has invalid current version")
        if note.referral_id not in referral_ref or (note.goal_id is not None and note.goal_id not in goal_ref):
            add("CROSS_CASE_NOTE", patient_ref[note.patient_id], f"case note {note.id} crosses the demo case boundary")
    for document in documents:
        versions = [row for row in document_versions if row.document_id == document.id]
        if not versions or not document.current_version_id or document.current_version_id not in {row.id for row in versions}:
            add("BROKEN_DOCUMENT_VERSION", goal_ref[document.goal_id], f"case document {document.id} has invalid current version")

    capacity_by_type = Counter(str(row.appointment_type_id) for row in capacity_slots)
    for appointment_type_id, count in capacity_by_type.items():
        if count > 8:
            add("CAPACITY_NOT_SCARCE", appointment_type_id, f"found {count} automatic slots in the two-day demo horizon")

    return {
        "scope": f"{DEMO_PREFIX}*",
        "patients": [
            {
                "external_ref": row.external_ref,
                "phone": row.phone,
                "language": row.preferred_language,
                "referrals": referrals_by_patient[row.id],
            }
            for row in patients
        ],
        "counts": {
            "patients": len(patients), "referrals": len(referrals), "goals": len(goals),
            "appointments": len(appointments), "linked_slots": len(slots), "open_offers": sum(row.status == "OFFERED" for row in appointments),
            "actions": len(actions), "decisions": len(decisions), "events": len(events), "calls": len(calls),
            "case_notes": len(notes), "case_note_versions": len(note_versions),
            "case_documents": len(documents), "case_document_versions": len(document_versions),
            "agent_steps": len(steps), "agent_tool_calls": len(tool_calls),
        },
        "status_counts": {
            "goals": dict(Counter(row.status for row in goals)),
            "appointments": dict(Counter(row.status for row in appointments)),
            "slots": dict(Counter(row.status for row in slots)),
            "actions": dict(Counter(row.status for row in actions)),
            "calls": dict(Counter(row.outcome for row in calls)),
            "agent_steps": dict(Counter(row.outcome for row in steps)),
            "demo_capacity": dict(Counter(row.status for row in capacity_slots)),
        },
        "records": {
            "appointments": [
                {
                    "id": str(row.id), "patient": referral_ref[row.referral_id], "status": row.status,
                    "slot_id": str(row.slot_id), "slot_external_ref": slot_by_id[row.slot_id].external_ref,
                    "slot_status": slot_by_id[row.slot_id].status,
                    "slot_properties": slot_by_id[row.slot_id].properties or {},
                    "created_at": row.created_at.isoformat(),
                }
                for row in sorted(appointments, key=lambda item: item.created_at)
            ],
            "actions": [
                {
                    "id": str(row.id), "patient": goal_ref[row.goal_id], "type": row.action_type,
                    "status": row.status, "payload": row.payload or {}, "result": row.result,
                    "created_at": row.created_at.isoformat(),
                }
                for row in sorted(actions, key=lambda item: item.created_at)
            ],
            "calls": [
                {
                    "id": str(row.id), "patient": goal_ref[row.goal_id], "purpose": row.purpose,
                    "outcome": row.outcome, "summary": row.summary, "created_at": row.created_at.isoformat(),
                }
                for row in sorted(calls, key=lambda item: item.created_at)
            ],
            "events": [
                {
                    "id": str(row.id), "patient": goal_ref[row.goal_id], "type": row.event_type,
                    "source": row.source, "payload": row.payload or {}, "created_at": row.created_at.isoformat(),
                }
                for row in sorted(events, key=lambda item: item.created_at)
            ],
            "agent_steps": [
                {
                    "id": str(row.id), "patient": goal_ref[row.goal_id], "outcome": row.outcome,
                    "error": row.error, "wake_reason": row.wake_reason, "created_at": row.created_at.isoformat(),
                }
                for row in sorted(steps, key=lambda item: item.created_at)
            ],
        },
        "violations": violations,
        "valid": not violations,
    }


def choose_canonical_appointment(appointments: list[Appointment], now: datetime) -> Appointment | None:
    """Choose one defensible booking without inventing a new slot."""
    booked = [row for row in appointments if row.status == "BOOKED"]
    if booked:
        return max(booked, key=lambda row: (row.slot.starts_at, row.created_at))
    future_offers = [row for row in appointments if row.status == "OFFERED" and row.slot.starts_at > now]
    if future_offers:
        return min(future_offers, key=lambda row: (row.slot.starts_at, row.created_at))
    return None


def _payload_mentions(payload: object, identifiers: set[str]) -> bool:
    if isinstance(payload, dict):
        return any(_payload_mentions(value, identifiers) for value in payload.values())
    if isinstance(payload, list):
        return any(_payload_mentions(value, identifiers) for value in payload)
    return str(payload) in identifiers


def cleanup_demo_state(session) -> dict:
    """Idempotently restore only DEMO-* cases to a quiescent coherent state."""
    patients = _demo_patients(session)
    patients_by_id = {row.id: row for row in patients}
    patient_ids = [row.id for row in patients]
    referrals = list(session.scalars(select(Referral).where(Referral.patient_id.in_(patient_ids))).all()) if patient_ids else []
    referral_ids = [row.id for row in referrals]
    goals = list(session.scalars(select(Goal).where(Goal.referral_id.in_(referral_ids))).all()) if referral_ids else []
    goal_ids = [goal.id for goal in goals]
    counts = {
        "patients_retained": len(patients), "phones_added": 0, "dobs_added": 0,
        "languages_added": 0, "blockers_cleared": 0, "wakes_cleared": 0,
        "appointments_removed": 0, "appointments_restored": 0, "slots_released": 0,
        "release_markers_cleared": 0, "actions_removed": 0, "decisions_removed": 0,
        "events_removed": 0, "failed_calls_removed": 0, "bad_runs_removed": 0,
    }
    existing_phones = set(session.scalars(select(Patient.phone).where(Patient.phone.is_not(None))).all())
    for index, patient in enumerate(patients):
        if not patient.phone:
            candidate_index = index
            while f"+44770091{candidate_index:04d}" in existing_phones:
                candidate_index += len(patients) or 1
            patient.phone = f"+44770091{candidate_index:04d}"
            existing_phones.add(patient.phone)
            counts["phones_added"] += 1
        if not patient.date_of_birth:
            patient.date_of_birth = datetime(1975, 4, 17, tzinfo=UTC)
            counts["dobs_added"] += 1
        if not patient.preferred_language:
            patient.preferred_language = "English"
            counts["languages_added"] += 1

    now = datetime.now(UTC)
    removed_appointment_ids: set[str] = set()
    canonical_slot_ids: set = set()
    touched_slots: set[Slot] = set()
    for referral in referrals:
        related = list(session.scalars(select(Appointment).where(Appointment.referral_id == referral.id)).all())
        external_ref = patients_by_id[referral.patient_id].external_ref
        expected_slot_ref = None
        if external_ref == "DEMO-ASHA-01":
            expected_slot_ref = "auto:20000000-0000-0000-0000-000000000001:20261016T1100Z"
        elif external_ref.startswith("DEMO-OVERSEER-"):
            expected_slot_ref = f"demo-overseer-booked-{external_ref.removeprefix('DEMO-OVERSEER-').lower()}"
        expected_slot = session.scalar(select(Slot).where(Slot.external_ref == expected_slot_ref)) if expected_slot_ref else None
        canonical = next((row for row in related if expected_slot and row.slot_id == expected_slot.id), None)
        if expected_slot and canonical is None:
            canonical = Appointment(referral_id=referral.id, slot_id=expected_slot.id, slot=expected_slot, status="BOOKED")
            session.add(canonical)
            related.append(canonical)
            counts["appointments_restored"] += 1
        if canonical is None:
            canonical = choose_canonical_appointment(related, now)
        if canonical:
            canonical_slot_ids.add(canonical.slot_id)
            if canonical.status != "BOOKED" or canonical.slot.status != "BOOKED":
                canonical.status = "BOOKED"
                canonical.slot.status = "BOOKED"
                canonical.slot.held_until = None
                counts["appointments_restored"] += 1
        for appointment in related:
            properties = appointment.slot.properties or {}
            if properties.get("released_gap"):
                appointment.slot.properties = {
                    **properties, "released_gap": False, "release_reason": None,
                    "released_by_goal_id": None,
                }
                counts["release_markers_cleared"] += 1
            if appointment is canonical:
                continue
            touched_slots.add(appointment.slot)
            removed_appointment_ids.add(str(appointment.id))
            session.delete(appointment)
            counts["appointments_removed"] += 1

    # A slot is safe to release only when every appointment currently pointing
    # at it belongs to this exact DEMO-* referral set. Never mutate a slot that
    # is also referenced by a non-demo case.
    for slot in touched_slots:
        if slot.id in canonical_slot_ids:
            continue
        linked_referral_ids = set(session.scalars(select(Appointment.referral_id).where(Appointment.slot_id == slot.id)).all())
        if linked_referral_ids.issubset(set(referral_ids)) and slot.status in {"HELD", "BOOKED"}:
            slot.status, slot.held_until = "AVAILABLE", None
            counts["slots_released"] += 1

    # Released slots no longer have an Appointment row, so they are not reached
    # through ``touched_slots`` above. Remove every release marker created by a
    # DEMO-* goal or an old reset can steal the next overseer handoff.
    demo_goal_ids = {str(goal_id) for goal_id in goal_ids}
    released_demo_slots = session.scalars(
        select(Slot).where(
            Slot.properties["released_by_goal_id"].as_string().in_(demo_goal_ids)
        )
    ).all()
    for slot in released_demo_slots:
        properties = slot.properties or {}
        if properties.get("released_gap"):
            slot.properties = {
                **properties,
                "released_gap": False,
                "release_reason": None,
                "released_by_goal_id": None,
            }
            counts["release_markers_cleared"] += 1

    for goal in goals:
        if goal.current_blocker or goal.status == "HUMAN_REVIEW_REQUIRED":
            goal.current_blocker = None
            goal.status = "WAITING"
            counts["blockers_cleared"] += 1
        # A demo reset must be completely quiescent. Clear every scheduled wake,
        # including future wakes left by reminder/capacity runs, so a reset
        # cannot immediately race a background worker and recreate stale state.
        if goal.next_wake_at:
            goal.next_wake_at = None
            counts["wakes_cleared"] += 1
    if not goal_ids:
        return counts
    removed_action_ids: set[str] = set()
    for row in session.scalars(select(Action).where(Action.goal_id.in_(goal_ids))).all():
        removed_action_ids.add(str(row.id)); session.delete(row); counts["actions_removed"] += 1
    for row in session.scalars(select(GoalDecision).where(GoalDecision.goal_id.in_(goal_ids))).all():
        session.delete(row); counts["decisions_removed"] += 1
    derived_types = {
        "CAPACITY_CHANGED", "HUMAN_REVIEW_REQUESTED", "OVERSEER_DELEGATED",
        "BROWSER_CALL_QUEUED", "VOICE_CALL_DECLINED",
    }
    removed_ids = removed_appointment_ids | removed_action_ids
    for row in session.scalars(select(Event).where(Event.goal_id.in_(goal_ids))).all():
        if row.event_type in derived_types or _payload_mentions(row.payload or {}, removed_ids):
            session.delete(row); counts["events_removed"] += 1
    # Use the exact same predicate as the audit. Keeping this in Python also
    # handles NULL summary/transcript values consistently across Postgres and
    # the lightweight fake sessions used by the reset regression tests.
    for row in session.scalars(select(Communication).where(Communication.goal_id.in_(goal_ids))).all():
        call_text = f"{row.summary or ''} {row.transcript or ''}".lower()
        if row.outcome == "FAILED" or "404" in call_text:
            session.delete(row); counts["failed_calls_removed"] += 1
    for row in session.scalars(select(AgentStep).where(AgentStep.goal_id.in_(goal_ids))).all():
        error = (row.error or "").lower()
        if row.outcome not in {"COMPLETED"} or "404" in error or "phone number" in error:
            session.delete(row); counts["bad_runs_removed"] += 1
    return counts
