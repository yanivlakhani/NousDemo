from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import Any
from uuid import UUID, uuid4

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Action, AgentDefinition, AgentSpecVersion, AgentStep, AgentToolCall, Appointment, CaseDocument, CaseDocumentVersion, CaseNote, Event, Goal, Slot
from app.records import CALL_PURPOSES, REMINDER_LEAD_HOURS, create_note
from app.settings import settings

MAX_TURNS, MAX_CALLS = 6, 8
SYSTEM = """You are nous, a long-horizon NHS administrative caseworker. Use tools to take one bounded administrative step. Read notes before relying on preferences. Never give clinical advice or change priority; escalate clinical questions. Never cancel an existing booking before a replacement is accepted. Finish with end_step."""
CASE_FILES = {"OVERVIEW": "overview.md", "PREFERENCES": "preferences.md", "CALL_NOTES": "call-notes.md"}
DECISION_OUTPUT_CONTRACT = """When calling end_step, report the run as structured fields rather than prose: a short operator-facing title; the event that triggered this run; one concise reason for the decision; candidate_slots as an array of {starts_at: ISO-8601 timestamp, site}; actions_taken as short factual phrases; whether an existing booking was released; the outcome; and one brief actionable next_action. Do not repeat the same explanation across fields. Do not include Markdown."""


def reconcile_pending_offers(session: Session, goal: Goal, now: datetime | None = None) -> Appointment | None:
    """Enforce one valid pending offer without turning routine state into an escalation."""
    now = now or datetime.now(UTC)
    referral_id = getattr(goal, "referral_id", None) or getattr(getattr(goal, "referral", None), "id", None)
    if referral_id is None:
        return None
    offers = session.scalars(
        select(Appointment)
        .where(Appointment.referral_id == referral_id, Appointment.status == "OFFERED")
        .order_by(Appointment.created_at.desc())
        .with_for_update()
    ).all()
    valid = [offer for offer in offers if offer.slot.status == "HELD" and (offer.slot.held_until is None or offer.slot.held_until > now)]
    keep = valid[0] if valid else None
    for offer in offers:
        if offer is keep:
            continue
        offer.status = "EXPIRED"
        if offer.slot.status == "HELD":
            offer.slot.status, offer.slot.held_until = "AVAILABLE", None
        session.add(Event(
            goal_id=goal.id,
            event_type="REDUNDANT_OFFER_RECONCILED",
            source="caseworker",
            payload={"appointment_id": str(offer.id), "slot_id": str(offer.slot_id), "retained_appointment_id": str(keep.id) if keep else None},
            idempotency_key=f"offer-reconciled:{offer.id}",
        ))
    if goal.status == "HUMAN_REVIEW_REQUIRED" and "offer" in (goal.current_blocker or "").lower():
        goal.status, goal.current_blocker, goal.next_wake_at = "WAITING", None, (keep.slot.held_until if keep else now)
    return keep


def spec(name: str, description: str, properties: dict | None = None, required: list[str] | None = None) -> dict:
    return {"name": name, "description": description, "input_schema": {"type": "object", "properties": properties or {}, "required": required or []}}


TOOLS = [
    spec("read_case_notes", "Read durable case notes."),
    spec("read_case_documents", "Read overview.md, preferences.md and call-notes.md, the same case files operators edit."),
    spec("write_case_document", "Save a new immutable Markdown version of one shared case file.", {"document_type": {"type": "string", "enum": list(CASE_FILES)}, "title": {"type": "string", "enum": list(CASE_FILES.values())}, "content": {"type": "string", "maxLength": 8000}}, ["document_type", "title", "content"]),
    spec("write_case_note", "Write a concise factual administrative note.", {"category": {"type": "string", "enum": ["PREFERENCE", "CONTACT", "CLINICAL_CONCERN", "ADMIN", "FOLLOW_UP"]}, "text": {"type": "string", "maxLength": 500}}, ["category", "text"]),
    spec("set_preferred_language", "Update the patient's preferred spoken language after the patient states or corrects it.", {"language": {"type": "string", "minLength": 2, "maxLength": 80}}, ["language"]),
    spec("search_slots", "List eligible future slots."),
    spec("offer_slot", "Hold and offer a slot; keep any existing booking.", {"slot_id": {"type": "string"}, "reason": {"type": "string"}}, ["slot_id", "reason"]),
    spec("queue_patient_call", "Queue an ElevenLabs administrative call.", {"reason": {"type": "string"}, "purpose": {"type": "string", "enum": sorted(CALL_PURPOSES)}}, ["reason", "purpose"]),
    spec("wait_until", "Set the next durable wake.", {"wake_at": {"type": "string"}, "reason": {"type": "string"}}, ["wake_at", "reason"]),
    spec("request_human", "Escalate, always for clinical questions.", {"reason": {"type": "string"}}, ["reason"]),
    spec("complete_goal", "Complete only after a completed appointment."),
    spec("end_step", "End after arranging a wake, offer, call, escalation, or completion. Return a structured operator summary.", {
        "title": {"type": "string", "maxLength": 80},
        "trigger": {"type": "string", "maxLength": 120},
        "reason": {"type": "string", "maxLength": 220},
        "candidate_slots": {"type": "array", "maxItems": 5, "items": {"type": "object", "properties": {"starts_at": {"type": "string"}, "site": {"type": "string"}}, "required": ["starts_at", "site"]}},
        "actions_taken": {"type": "array", "maxItems": 5, "items": {"type": "string"}},
        "booking_released": {"type": "boolean"},
        "outcome": {"type": "string", "maxLength": 120},
        "next_action": {"type": "string", "maxLength": 160},
        "decision": {"type": "string", "description": "Legacy fallback only."},
    }, ["title", "trigger", "reason", "candidate_slots", "actions_taken", "booking_released", "outcome", "next_action"]),
]


def decision_json(args: dict) -> str:
    """Persist a compact, renderable decision while accepting historical callers."""
    fields = ("title", "trigger", "reason", "candidate_slots", "actions_taken", "booking_released", "outcome", "next_action")
    if not any(key in args for key in fields):
        return str(args.get("decision", "Step completed"))[:500]
    payload = {key: args.get(key) for key in fields}
    payload["candidate_slots"] = list(payload.get("candidate_slots") or [])[:3]
    payload["actions_taken"] = [str(value)[:80] for value in list(payload.get("actions_taken") or [])[:4]]
    text = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    if len(text) <= 500:
        return text
    payload["candidate_slots"] = payload["candidate_slots"][:1]
    payload["reason"] = str(payload.get("reason") or "")[:120]
    payload["next_action"] = str(payload.get("next_action") or "")[:100]
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)[:500]


def context(session: Session, goal: Goal) -> dict[str, Any]:
    patient, referral = goal.referral.patient, goal.referral
    notes = session.scalars(select(CaseNote).where(CaseNote.patient_id == patient.id).order_by(CaseNote.created_at.desc()).limit(20)).all()
    appointments = session.scalars(select(Appointment).where(Appointment.referral_id == referral.id).order_by(Appointment.created_at.desc())).all()
    documents = session.scalars(select(CaseDocument).where(CaseDocument.goal_id == goal.id, CaseDocument.title.in_(CASE_FILES.values())).order_by(CaseDocument.created_at)).all()
    current_versions = {document.current_version_id: session.get(CaseDocumentVersion, document.current_version_id) for document in documents if document.current_version_id}
    booked = next((appointment for appointment in appointments if appointment.status == "BOOKED"), None)
    now = datetime.now(UTC)
    reminder_actions = session.scalars(select(Action).where(Action.goal_id == goal.id, Action.action_type == "CALL_PATIENT", Action.status.in_(["QUEUED", "EXECUTING", "COMPLETED"]))).all()
    reminder_already_queued = any((action.payload or {}).get("purpose") == "REMINDER" for action in reminder_actions)
    reminder = {"lead_hours": REMINDER_LEAD_HOURS, "due": bool(booked and booked.slot.starts_at > now and goal.next_wake_at and goal.next_wake_at <= now), "already_queued": reminder_already_queued, "instruction": "When due and not already queued, read the notes then queue one REMINDER call in the patient's preferred language."}
    return {"goal": goal.description, "status": goal.status, "summary": goal.current_summary, "blocker": goal.current_blocker, "patient": {"first_name": patient.first_name, "contact": patient.preferred_contact_method, "preferred_language": patient.preferred_language, "constraints": patient.constraints}, "referral": {"pathway": referral.pathway_type, "procedure": referral.procedure}, "appointments": [{"id": str(a.id), "slot_id": str(a.slot_id), "status": a.status, "when": a.slot.starts_at.isoformat(), "site": a.slot.site} for a in appointments], "reminder": reminder, "notes": [{"category": n.category, "text": n.text, "language": n.language, "source": n.source} for n in reversed(notes)], "documents": [{"id": str(document.id), "type": document.document_type, "title": document.title, "version": current_versions[document.current_version_id].version, "content": current_versions[document.current_version_id].content} for document in documents if current_versions.get(document.current_version_id)]}


def eligible_slots(session: Session, goal: Goal) -> list[Slot]:
    patient = goal.referral.patient
    rows = session.scalars(select(Slot).where(Slot.procedure == goal.referral.procedure, Slot.status == "AVAILABLE", Slot.starts_at > datetime.now(UTC)).order_by(Slot.starts_at).limit(20)).all()
    weekend_only = patient.constraints.get("WEEKEND_ONLY") or patient.constraints.get("Saturdays only")
    return [slot for slot in rows if not weekend_only or slot.starts_at.weekday() >= 5]


def dispatch(session: Session, goal: Goal, name: str, args: dict) -> tuple[str, str, bool, str | None]:
    now, patient, referral = datetime.now(UTC), goal.referral.patient, goal.referral
    try:
        if name == "read_case_notes":
            notes = session.scalars(select(CaseNote).where(CaseNote.patient_id == patient.id).order_by(CaseNote.created_at.desc()).limit(20)).all()
            return ("\n".join(f"{n.category} [{n.language}]: {n.text}" for n in reversed(notes)) or "No case notes.", "OK", False, None)
        if name == "read_case_documents":
            documents = session.scalars(select(CaseDocument).where(CaseDocument.goal_id == goal.id, CaseDocument.title.in_(CASE_FILES.values())).order_by(CaseDocument.created_at)).all()
            rows = []
            for document in documents:
                version = session.get(CaseDocumentVersion, document.current_version_id) if document.current_version_id else None
                if version: rows.append(f"{document.document_type} / {document.title} / v{version.version}:\n{version.content}")
            return ("\n\n".join(rows) or "No case documents.", "OK", False, None)
        if name == "write_case_document":
            document_type, title, content = str(args.get("document_type", "")).strip().upper(), str(args.get("title", "")).strip().lower(), str(args.get("content", "")).strip()
            expected_title = CASE_FILES.get(document_type)
            if not expected_title or title != expected_title or not content or len(content) > 8000: raise ValueError("Case file must be overview.md, preferences.md or call-notes.md")
            document = session.scalar(select(CaseDocument).where(CaseDocument.goal_id == goal.id, CaseDocument.document_type == document_type, CaseDocument.title == title).with_for_update())
            if not document:
                document = CaseDocument(goal_id=goal.id, document_type=document_type, title=title); session.add(document); session.flush()
            current = session.get(CaseDocumentVersion, document.current_version_id) if document.current_version_id else None
            if current and current.content == content: return (f"Case document already current at v{current.version}.", "OK", False, None)
            latest = session.scalar(select(func.max(CaseDocumentVersion.version)).where(CaseDocumentVersion.document_id == document.id)) or 0
            version = CaseDocumentVersion(document_id=document.id, content=content, version=latest + 1, supersedes_id=document.current_version_id, document_metadata={"provenance": "agent_tool"}, created_by="CASEWORKER")
            session.add(version); session.flush(); document.current_version_id = version.id
            session.add(Event(goal_id=goal.id, event_type="CASE_DOCUMENT_VERSION_CREATED", source="anthropic", payload={"document_id": str(document.id), "version_id": str(version.id), "version": version.version}, idempotency_key=f"case-document:{version.id}"))
            return (f"Case document saved as v{version.version}.", "OK", False, None)
        if name == "write_case_note":
            category, text = args.get("category"), str(args.get("text", "")).strip()
            if category not in {"PREFERENCE", "CONTACT", "CLINICAL_CONCERN", "ADMIN", "FOLLOW_UP"} or not text or len(text) > 500: raise ValueError("Invalid note")
            note = create_note(session, patient_id=patient.id, referral_id=referral.id, goal_id=goal.id, category=category, text=text, language=patient.preferred_language, source="CASEWORKER"); session.add(Event(goal_id=goal.id, event_type="CASE_NOTE_VERSION_CREATED", source="anthropic", payload={"category": category, "note_id": str(note.id), "version": 1}, idempotency_key=f"note:{goal.id}:{uuid4()}"))
            document_type = "PREFERENCES" if category in {"PREFERENCE", "CONTACT"} else "CALL_NOTES"
            title = CASE_FILES[document_type]
            document = session.scalar(select(CaseDocument).where(CaseDocument.goal_id == goal.id, CaseDocument.document_type == document_type, CaseDocument.title == title).with_for_update())
            if not document:
                document = CaseDocument(goal_id=goal.id, document_type=document_type, title=title); session.add(document); session.flush()
            current = session.get(CaseDocumentVersion, document.current_version_id) if document.current_version_id else None
            base = current.content if current else f"# {title.removesuffix('.md').replace('-', ' ').title()}\n"
            content = f"{base.rstrip()}\n\n- {now.date().isoformat()} · {category.replace('_', ' ').title()}: {text}\n"
            latest = session.scalar(select(func.max(CaseDocumentVersion.version)).where(CaseDocumentVersion.document_id == document.id)) or 0
            version = CaseDocumentVersion(document_id=document.id, content=content, version=latest + 1, supersedes_id=document.current_version_id, document_metadata={"format": "markdown", "provenance": "agent_tool"}, created_by="CASEWORKER")
            session.add(version); session.flush(); document.current_version_id = version.id
            return ("Case note recorded.", "OK", False, None)
        if name == "set_preferred_language":
            language = str(args.get("language", "")).strip()
            if len(language) < 2 or len(language) > 80: raise ValueError("A valid preferred language is required")
            previous = patient.preferred_language
            patient.preferred_language = language
            session.add(Event(goal_id=goal.id, event_type="PATIENT_LANGUAGE_UPDATED", source="anthropic", payload={"previous_language": previous, "preferred_language": language}, idempotency_key=f"patient-language:{goal.id}:{uuid4()}"))
            return (f"Preferred language updated to {language}.", "OK", False, None)
        if name == "search_slots":
            slots = eligible_slots(session, goal)
            return ("\n".join(f"slot_id={s.id} when={s.starts_at.isoformat()} site={s.site}" for s in slots) or "No eligible slots.", "OK", False, None)
        if name == "offer_slot":
            slot_id = UUID(str(args.get("slot_id"))); slot = next((s for s in eligible_slots(session, goal) if s.id == slot_id), None)
            if not slot: raise ValueError("Slot is not eligible")
            existing_offer = reconcile_pending_offers(session, goal, now)
            if existing_offer:
                if existing_offer.slot_id == slot.id:
                    goal.status, goal.current_blocker, goal.next_wake_at = "WAITING", None, existing_offer.slot.held_until or now + timedelta(hours=24)
                    return ("The selected slot is already held for this patient; continuing with the existing offer.", "OK", False, None)
                # A caseworker may discover a better compatible slot during the
                # live conversation. Replace the stale offer atomically instead
                # of blocking the demo or escalating routine administration.
                existing_offer.status = "EXPIRED"
                if existing_offer.slot.status == "HELD":
                    existing_offer.slot.status, existing_offer.slot.held_until = "AVAILABLE", None
                session.add(Event(
                    goal_id=goal.id,
                    event_type="STALE_OFFER_REPLACED",
                    source="anthropic",
                    payload={"old_slot_id": str(existing_offer.slot_id), "new_slot_id": str(slot.id)},
                    idempotency_key=f"offer-replaced:{existing_offer.id}:{slot.id}",
                ))
            slot.status, slot.held_until = "HELD", now + timedelta(hours=24); session.add(Appointment(referral_id=referral.id, slot_id=slot.id, status="OFFERED")); goal.status, goal.next_wake_at = "WAITING", now + timedelta(hours=24)
            session.add(Event(goal_id=goal.id, event_type="SLOT_OFFERED", source="anthropic", payload={"slot_id": str(slot.id), "reason": str(args.get("reason", ""))[:300]}, idempotency_key=f"offer:{goal.id}:{slot.id}"))
            return ("Slot held and offered; existing booking unchanged.", "OK", False, None)
        if name == "queue_patient_call":
            reason = str(args.get("reason", ""))[:300]
            purpose = str(args.get("purpose", "FOLLOW_UP")).upper()
            if purpose not in CALL_PURPOSES: raise ValueError("Invalid call purpose")
            if not patient.phone: raise ValueError("Patient has no phone number")
            key = f"call-queue:{goal.id}:{goal.version}"
            if not session.scalar(select(Action).where(Action.idempotency_key == key)):
                session.add(Action(goal_id=goal.id, action_type="CALL_PATIENT", status="QUEUED", payload={"reason": reason, "purpose": purpose, "patient_first_name": patient.first_name, "phone_number": patient.phone, "preferred_language": getattr(patient, "preferred_language", "English")}, idempotency_key=key, requires_human_approval=False))
            if not session.scalar(select(Event).where(Event.idempotency_key == key)):
                session.add(Event(goal_id=goal.id, event_type="VOICE_CALL_QUEUED", source="anthropic", payload={"reason": reason, "purpose": purpose, "outcome": "QUEUED"}, idempotency_key=key))
            goal.status, goal.next_wake_at = "WAITING", now + timedelta(days=1)
            return ("Patient call queued.", "OK", False, None)
        if name == "wait_until":
            wake = datetime.fromisoformat(str(args.get("wake_at")))
            if wake.tzinfo is None or wake <= now: raise ValueError("wake_at must be future and timezone-aware")
            goal.status, goal.next_wake_at, goal.current_summary = "WAITING", wake, str(args.get("reason", "Waiting"))[:500]
            return (f"Waiting until {wake.isoformat()}.", "OK", False, None)
        if name == "request_human":
            reason = str(args.get("reason", "Human review"))[:200]; goal.status, goal.current_blocker, goal.next_wake_at = "HUMAN_REVIEW_REQUIRED", reason, None
            session.add(Event(goal_id=goal.id, event_type="HUMAN_REVIEW_REQUESTED", source="anthropic", payload={"reason": reason}, idempotency_key=f"human:{goal.id}:{uuid4()}"))
            return ("Escalated.", "OK", False, None)
        if name == "complete_goal":
            if not session.scalar(select(Appointment.id).where(Appointment.referral_id == referral.id, Appointment.status == "COMPLETED")): raise ValueError("No completed appointment")
            goal.status, goal.next_wake_at, referral.status = "COMPLETED", None, "COMPLETED"
            return ("Goal completed.", "OK", False, None)
        if name == "end_step":
            has_offer = session.scalar(select(Appointment.id).where(Appointment.referral_id == referral.id, Appointment.status == "OFFERED"))
            if goal.status in {"ACTIVE", "WAITING"} and goal.next_wake_at is None and not has_offer: raise ValueError("Set a wake, offer, call, or escalation first")
            return ("Step ended.", "OK", True, decision_json(args))
        raise ValueError("Unknown tool")
    except (ValueError, TypeError) as exc:
        return (str(exc), "REJECTED", False, None)


def active_agent_spec(session: Session, key: str = "caseworker") -> AgentSpecVersion:
    definition = session.scalar(
        select(AgentDefinition).where(AgentDefinition.key == key)
    )
    if not definition or not definition.active_version_id:
        raise RuntimeError(f"No active {key} agent specification")
    version = session.get(AgentSpecVersion, definition.active_version_id)
    if not version or version.status != "PUBLISHED":
        raise RuntimeError(f"Active {key} agent specification is unavailable")
    return version


def tools_for_spec(agent_spec: AgentSpecVersion) -> list[dict]:
    allowed = set(agent_spec.tool_policy.get("allowed", []))
    return [tool for tool in TOOLS if tool["name"] in allowed]


def step_causality(session: Session, goal: Goal) -> tuple[AgentStep | None, int, int, str]:
    previous = session.scalar(select(AgentStep).where(AgentStep.goal_id == goal.id).order_by(AgentStep.created_at.desc()).limit(1))
    wake_event = session.scalar(select(Event).where(Event.goal_id == goal.id).order_by(Event.created_at.desc()).limit(1))
    sequence = (previous.sequence if previous else 0) + 1
    retry_attempt = ((previous.retry_attempt or 0) + 1) if previous and previous.fallback else 0
    if wake_event:
        detail = wake_event.payload.get("reason") or wake_event.payload.get("note") or wake_event.payload.get("constraint")
        wake_reason = f"{wake_event.event_type}: {detail}" if detail else wake_event.event_type
    elif goal.next_wake_at:
        wake_reason = "SCHEDULED_WAKE"
    else:
        wake_reason = "INITIAL_GOAL"
    return previous, sequence, retry_attempt, wake_reason[:300]


def model(messages: list[dict], agent_spec: AgentSpecVersion) -> dict:
    if not settings.anthropic_api_key or settings.anthropic_api_key.startswith("PLACEHOLDER"): raise RuntimeError("ANTHROPIC_API_KEY is not configured")
    response = httpx.post("https://api.anthropic.com/v1/messages", headers={"x-api-key": settings.anthropic_api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"}, json={"model": agent_spec.model, "max_tokens": 1024, "system": f"{agent_spec.instructions}\n\n{DECISION_OUTPUT_CONTRACT}", "tools": tools_for_spec(agent_spec), "messages": messages}, timeout=45)
    response.raise_for_status(); return response.json()


def run_goal(session: Session, goal: Goal) -> dict[str, Any]:
    run_started_at, run_timer = datetime.now(UTC), perf_counter()
    reconcile_pending_offers(session, goal, run_started_at)
    agent_spec = active_agent_spec(session)
    previous_step, step_sequence, retry_attempt, wake_reason = step_causality(session, goal)
    max_turns = max(1, min(int(agent_spec.tool_policy.get("max_turns", MAX_TURNS)), 12))
    max_calls = max(1, min(int(agent_spec.tool_policy.get("max_tool_calls", MAX_CALLS)), 20))
    snapshot = context(session, goal); snapshot["agent_spec"] = {"id": str(agent_spec.id), "key": agent_spec.definition.key, "version": agent_spec.version, "name": agent_spec.name, "role": agent_spec.role}
    messages = [{"role": "user", "content": f"{json.dumps(snapshot)}\n\nTake the next step and finish with end_step."}]; calls = []; in_tokens = out_tokens = 0; stop = decision = None
    try:
        with session.begin_nested():
            for _ in range(max_turns):
                response = model(messages, agent_spec); stop = response.get("stop_reason"); usage = response.get("usage", {}); in_tokens += usage.get("input_tokens", 0); out_tokens += usage.get("output_tokens", 0); content = response.get("content", []); messages.append({"role": "assistant", "content": content}); results = []
                for block in (item for item in content if item.get("type") == "tool_use"):
                    if len(calls) >= max_calls: raise RuntimeError("Tool budget exceeded")
                    call_started_at, call_timer = datetime.now(UTC), perf_counter()
                    text, status, ended, final = dispatch(session, goal, block["name"], block.get("input", {}))
                    call_completed_at = datetime.now(UTC)
                    calls.append((block["name"], block.get("input", {}), text, status, call_started_at, call_completed_at, max(0, int((perf_counter() - call_timer) * 1000))))
                    results.append({"type": "tool_result", "tool_use_id": block["id"], "content": text, "is_error": status == "REJECTED"})
                    if ended: decision = final; break
                if decision: break
                if not results: raise RuntimeError("Model returned no tool call")
                messages.append({"role": "user", "content": results})
            if not decision: raise RuntimeError("Model did not end the step")
    except Exception as exc:
        goal.status, goal.next_wake_at, goal.current_summary = "WAITING", datetime.now(UTC) + timedelta(hours=1), "Agent failure; retry scheduled"
        completed_at = datetime.now(UTC)
        session.add(AgentStep(goal_id=goal.id, agent_spec_version_id=agent_spec.id, parent_step_id=previous_step.id if previous_step else None, sequence=step_sequence, retry_attempt=retry_attempt, wake_reason=wake_reason, scheduled_next_wake=goal.next_wake_at, outcome="RETRY_SCHEDULED", tool_call_count=len(calls), mode="DETERMINISTIC", model=agent_spec.model, fallback=True, stop_reason=stop, decision="Retry", error=str(exc)[:2000], context=snapshot, input_tokens=in_tokens, output_tokens=out_tokens, created_at=run_started_at, completed_at=completed_at, duration_ms=max(0, int((perf_counter() - run_timer) * 1000))))
        return {"goal_id": str(goal.id), "action": "WAIT", "summary": goal.current_summary, "fallback": True}
    completed_at = datetime.now(UTC)
    step = AgentStep(goal_id=goal.id, agent_spec_version_id=agent_spec.id, parent_step_id=previous_step.id if previous_step else None, sequence=step_sequence, retry_attempt=retry_attempt, wake_reason=wake_reason, scheduled_next_wake=goal.next_wake_at, outcome="COMPLETED", tool_call_count=len(calls), mode="ANTHROPIC", model=agent_spec.model, fallback=False, stop_reason=stop, decision=decision, context=snapshot, input_tokens=in_tokens, output_tokens=out_tokens, created_at=run_started_at, completed_at=completed_at, duration_ms=max(0, int((perf_counter() - run_timer) * 1000))); session.add(step); session.flush()
    for sequence, (name, tool_input, result, status, started_at, call_completed_at, duration_ms) in enumerate(calls, 1): session.add(AgentToolCall(step_id=step.id, sequence=sequence, tool_name=name, tool_input=tool_input, result_text=result, status=status, started_at=started_at, completed_at=call_completed_at, duration_ms=duration_ms))
    goal.current_summary = decision; goal.version += 1; session.add(Event(goal_id=goal.id, event_type="AGENT_STEP_COMPLETED", source="anthropic", payload={"decision": decision, "tool_calls": len(calls), "agent_spec_version_id": str(agent_spec.id), "agent_spec_version": agent_spec.version}, idempotency_key=f"agent-step:{step.id}"))
    return {"goal_id": str(goal.id), "action": calls[-1][0], "summary": decision, "fallback": False}


def due_goals(session: Session, limit: int) -> list[Goal]:
    now = datetime.now(UTC)
    return list(session.scalars(select(Goal).where(Goal.status.in_(["ACTIVE", "WAITING"]), (Goal.next_wake_at.is_(None)) | (Goal.next_wake_at <= now)).order_by(Goal.next_wake_at.asc().nullsfirst()).limit(limit)).all())
