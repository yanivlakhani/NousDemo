from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import Action, Appointment, AppointmentType, Event, Goal, GoalDecision, Referral, Slot

HOLD_FOR = timedelta(hours=24)
OVERSEER_HORIZON = timedelta(days=7)
MAX_BATCH = 20
CAPACITY_HORIZON_DAYS = 28
CAPACITY_DAY_START_HOUR = 9
CAPACITY_DAY_END_HOUR = 17
DEFAULT_PROVIDER_ORG = "Nous demo provider"
DEFAULT_SITE = "Main site"


def _weekday_starts(now: datetime, duration_minutes: int, horizon_days: int) -> list[datetime]:
    """Return future UTC slot starts for weekday clinic hours in the horizon."""
    if duration_minutes <= 0:
        return []
    starts: list[datetime] = []
    for offset in range(horizon_days):
        day = now.date() + timedelta(days=offset)
        if day.weekday() >= 5:
            continue
        cursor = datetime(day.year, day.month, day.day, CAPACITY_DAY_START_HOUR, tzinfo=UTC)
        closes_at = cursor.replace(hour=CAPACITY_DAY_END_HOUR)
        while cursor + timedelta(minutes=duration_minutes) <= closes_at:
            if cursor >= now:
                starts.append(cursor)
            cursor += timedelta(minutes=duration_minutes)
    return starts


def _automatic_slot_ref(appointment_type: AppointmentType, starts_at: datetime) -> str:
    return f"auto:{appointment_type.id}:{starts_at.strftime('%Y%m%dT%H%MZ')}"


def ensure_weekday_capacity(
    session: Session,
    *,
    now: datetime | None = None,
    horizon_days: int = CAPACITY_HORIZON_DAYS,
    duration_override_minutes: int | None = None,
    provider_org: str = DEFAULT_PROVIDER_ORG,
    site: str = DEFAULT_SITE,
) -> dict:
    """Idempotently fill weekdays 09:00-17:00 with each active type's duration.

    Existing rows are identified by a deterministic external reference and are
    never updated, so held and booked slots remain untouched.
    """
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    if horizon_days < 1:
        raise ValueError("horizon_days must be positive")
    if duration_override_minutes is not None and duration_override_minutes <= 0:
        raise ValueError("duration_override_minutes must be positive")

    # Locking the type rows serializes concurrent overseer runs before either
    # computes missing refs; the unique external_ref remains a second guard.
    appointment_types = session.scalars(
        select(AppointmentType)
        .where(AppointmentType.is_active.is_(True))
        .order_by(AppointmentType.code)
        .with_for_update()
    ).all()
    desired: list[tuple[AppointmentType, datetime, str]] = []
    for appointment_type in appointment_types:
        duration_minutes = duration_override_minutes or appointment_type.default_duration_minutes
        for starts_at in _weekday_starts(now, duration_minutes, horizon_days):
            desired.append((appointment_type, starts_at, _automatic_slot_ref(appointment_type, starts_at)))

    refs = [item[2] for item in desired]
    existing = set(session.scalars(select(Slot.external_ref).where(Slot.external_ref.in_(refs))).all()) if refs else set()
    slots = [
        Slot(
            external_ref=external_ref,
            appointment_type_id=appointment_type.id,
            provider_org=provider_org,
            site=site,
            procedure=appointment_type.name,
            starts_at=starts_at,
            duration_minutes=duration_override_minutes or appointment_type.default_duration_minutes,
            properties={
                "source": "automatic_weekday_capacity",
                "capacity_profile": "demo_scarce" if duration_override_minutes else "configured_type",
            },
            status="AVAILABLE",
        )
        for appointment_type, starts_at, external_ref in desired
        if external_ref not in existing
    ]
    session.add_all(slots)
    return {
        "created": len(slots),
        "already_present": len(desired) - len(slots),
        "appointment_types": len(appointment_types),
        "horizon_days": horizon_days,
        "duration_override_minutes": duration_override_minutes,
    }


def release_expired_holds(session: Session, now: datetime) -> int:
    slots = session.scalars(select(Slot).where(Slot.status == "HELD", Slot.held_until <= now).with_for_update(skip_locked=True)).all()
    for slot in slots:
        slot.status, slot.held_until = "AVAILABLE", None
        offers = session.scalars(select(Appointment).where(Appointment.slot_id == slot.id, Appointment.status == "OFFERED")).all()
        for offer in offers:
            offer.status = "EXPIRED"
    return len(slots)


URGENCY_SCORES = {"IMMEDIATE": 4, "URGENT": 3, "SOON": 2, "ROUTINE": 1}


def _delegation_key(goal_id: object, slot_id: object) -> str:
    """Stable queue identity; the database unique constraint rejects retries."""
    return f"earlier-slot-offer:{goal_id}:{slot_id}"


def _clinician_urgency(goal: Goal) -> tuple[int, str]:
    """Read, but never infer, clinician-assigned urgency from durable goal policy."""
    raw = goal.success_criteria.get("clinician_urgency") or goal.success_criteria.get("urgency")
    label = str(raw).strip().upper() if raw else "UNSPECIFIED"
    return URGENCY_SCORES.get(label, 0), label


def _rank(session: Session, slot: Slot, now: datetime) -> list[tuple[float, Goal, list[str]]]:
    # Claim eligible patients independently of the slot claim. Concurrent
    # overseer runs skip patients already being delegated, preventing two
    # released slots from producing competing offers for the same person.
    goals = session.scalars(select(Goal).where(Goal.status.in_(["ACTIVE", "WAITING"]), Goal.referral.has(Referral.procedure == slot.procedure)).order_by(Goal.created_at).with_for_update(skip_locked=True)).all()
    ranked = []
    for goal in goals:
        patient, referral = goal.referral.patient, goal.referral
        if str((slot.properties or {}).get("released_by_goal_id", "")) == str(goal.id):
            continue
        if patient.constraints.get("WEEKEND_ONLY") and slot.starts_at.weekday() < 5: continue
        if patient.constraints.get("Saturdays only") and slot.starts_at.weekday() != 5: continue
        if session.scalar(select(Appointment.id).where(Appointment.referral_id == referral.id, Appointment.slot_id == slot.id)): continue
        if session.scalar(select(Appointment.id).where(Appointment.referral_id == referral.id, Appointment.status == "OFFERED")): continue
        site_preference = patient.constraints.get("preferred_site") or patient.constraints.get("site")
        if isinstance(site_preference, str) and site_preference.strip() and site_preference.strip().lower() != slot.site.lower(): continue
        prior_calls = [action for action in getattr(goal, "actions", []) if action.action_type == "EARLIER_SLOT_OFFER"]
        if any(str((action.payload or {}).get("proposed_slot_id", "")) == str(slot.id) and action.status not in {"CANCELLED", "EXPIRED"} for action in prior_calls): continue
        current = session.scalar(select(Appointment).where(Appointment.referral_id == referral.id, Appointment.status == "BOOKED"))
        # Released-slot cascades are only for patients who already have a later
        # appointment. Ordinary newly-added capacity retains the original
        # no-booking pathway. Neither path infers need from clinical data.
        released_gap = bool((slot.properties or {}).get("released_gap"))
        if current is None and released_gap:
            continue
        urgency_score, urgency = _clinician_urgency(goal)
        if current is None:
            improvement_days = 0
            reasons = [f"clinician-assigned urgency: {urgency}", "administrative fit: no appointment currently booked"]
        elif slot.starts_at < current.slot.starts_at:
            improvement_days = max(0, (current.slot.starts_at - slot.starts_at).days)
            reasons = [f"clinician-assigned urgency: {urgency}", f"administrative fit: {improvement_days} days earlier"]
        else:
            continue
        score = urgency_score * 10_000 + improvement_days
        if referral.deadline_at:
            # deadline_at is clinician/referrer supplied; it is not derived from
            # symptoms, notes, diagnosis, or any model judgement.
            days = max(0, (referral.deadline_at - now).days)
            score += max(0, 365 - days)
            reasons.append(f"clinician-assigned deadline in {days} days")
        ranked.append((score, goal, reasons))
    return sorted(ranked, key=lambda item: (-item[0], item[1].created_at))


def match_available_slots(session: Session, limit: int = MAX_BATCH, *, released_only: bool = False, pass_id: str | None = None) -> dict:
    now = datetime.now(UTC); expired = release_expired_holds(session, now); matches = []
    query = select(Slot).where(Slot.status == "AVAILABLE", Slot.starts_at >= now, Slot.starts_at < now + OVERSEER_HORIZON)
    if released_only:
        query = query.where(Slot.properties["released_gap"].as_boolean().is_(True))
    else:
        # The demo exposes a deep synthetic calendar for patient-led
        # rescheduling. It must not cause unsolicited caseworker calls merely
        # because that background capacity exists.
        query = query.where(or_(
            Slot.properties["reschedule_only"].as_boolean().is_(None),
            Slot.properties["reschedule_only"].as_boolean().is_(False),
        ))
    slots = session.scalars(query.order_by(Slot.starts_at).with_for_update(skip_locked=True).limit(limit)).all()
    for slot in slots:
        ranked = _rank(session, slot, now)
        if not ranked: continue
        score, goal, reasons = ranked[0]
        slot.status, slot.held_until = "HELD", now + HOLD_FOR
        offer = Appointment(referral_id=goal.referral_id, slot_id=slot.id, status="OFFERED"); session.add(offer); session.flush()
        goal.status, goal.next_wake_at = "WAITING", now
        ranked_choices = [{"rank": index, "goal_id": str(candidate.id), "score": candidate_score, "reasons": candidate_reasons} for index, (candidate_score, candidate, candidate_reasons) in enumerate(ranked, 1)]
        goal.version += 1
        patient = goal.referral.patient
        patient_name = " ".join(part for part in (getattr(patient, "first_name", None), getattr(patient, "last_name", None)) if part)
        slot_context = {
            "slot_id": str(slot.id),
            "appointment_type": slot.procedure,
            "starts_at": slot.starts_at.isoformat(),
            "site": getattr(slot, "site", None),
        }
        selected_patient = {
            "goal_id": str(goal.id),
            "external_ref": getattr(patient, "external_ref", None),
            "name": patient_name or "Patient record",
        }
        delegation = {
            "action": "DELEGATE_EARLIER_SLOT_OFFER",
            "delegated_goal": "Contact the patient to offer the held earlier appointment; do not cancel their current booking.",
            "purpose": "EARLIER_SLOT_OFFER",
            **slot_context,
            "selected_patient": selected_patient,
            "appointment_id": str(offer.id), "reasons": reasons,
        }
        next_scan_at = now + timedelta(minutes=1)
        decision = GoalDecision(goal_id=goal.id, goal_version=goal.version, observation={"overseer_run": "released_slot_ranking", "iteration_status": "CLOSED", "closed_at": now.isoformat(), "next_wake_at": next_scan_at.isoformat(), "slot_id": str(slot.id), "ranked_choices": ranked_choices, "ranking_policy": "clinician_assigned_urgency_then_administrative_fit"}, reasoning_summary="Selected the highest ranked eligible later-booked patient using recorded clinician urgency and administrative fit only.", proposed_action=delegation)
        session.add(decision)
        session.flush()
        call_key = _delegation_key(goal.id, slot.id)
        trace = {"overseer_decision_id": str(decision.id), "delegation_key": call_key}
        session.add(Event(goal_id=goal.id, event_type="OVERSEER_DELEGATED", source="capacity_overseer", payload={**delegation, **trace, "ranked_choices": ranked_choices, "action_type": "WAKE_CASEWORKER"}, idempotency_key=f"{call_key}:delegate"))
        # The handoff is complete here. The patient-specific caseworker owns the
        # browser call action and all subsequent voice/tools/notes/outcomes.
        session.add(Action(goal_id=goal.id, action_type="CALL_PATIENT", status="QUEUED", payload={"reason": "Offer a nearer appointment released by a cancellation or reschedule.", "purpose": "EARLIER_SLOT_OFFER", "patient_first_name": patient.first_name, "phone_number": patient.phone, "proposed_slot_id": str(slot.id), **slot_context, **trace, "selected_patient": selected_patient, "delegated_by": "capacity_overseer", "owner": "caseworker", "reasons": reasons, "receiver_token": uuid4().hex, "receiver_ready": True, "transport": "demo_browser_receiver"}, idempotency_key=call_key, requires_human_approval=False))
        session.add(Event(goal_id=goal.id, event_type="BROWSER_CALL_QUEUED", source="caseworker", payload={"slot_id": str(slot.id), "purpose": "EARLIER_SLOT_OFFER", "delegated_by": "capacity_overseer"}, idempotency_key=f"{call_key}:caseworker"))
        matches.append({"goal_id": str(goal.id), "slot_id": str(slot.id), "score": score, "reasons": reasons, "ranked_choices": ranked_choices, "delegated_action": "EARLIER_SLOT_OFFER", **trace})
    next_scan_at = now + timedelta(minutes=1)
    summary = f"Delegated {len(matches)} caseworker{'s' if len(matches) != 1 else ''}" if matches else "No actionable release this pass"
    pass_id = pass_id or uuid4().hex
    session.add(Event(goal_id=None, event_type="OVERSEER_PASS_COMPLETED", source="capacity_overseer", payload={"pass_id": pass_id, "iteration_status": "CLOSED", "matched": len(matches), "summary": summary, "next_wake_at": next_scan_at.isoformat()}, idempotency_key=f"overseer-pass:{pass_id}"))
    return {"matched": len(matches), "expired_holds": expired, "offers": matches, "pass_id": pass_id, "iteration_status": "CLOSED", "last_iteration_summary": summary, "next_wake_at": next_scan_at.isoformat()}
