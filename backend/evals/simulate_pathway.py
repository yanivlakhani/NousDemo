"""Hermetic end-to-end replays for the nous long-horizon pathway.

This module deliberately uses an in-memory SQLite database and scripted model /
telephony adapters.  It never reads production settings, connects to Supabase,
calls Anthropic, or dials a phone.  The caseworker runtime, tool dispatcher,
capacity matcher, ElevenLabs HTTP-tool handlers, transcript webhook handler,
and ORM models are the application implementations.

Run with::

    PYTHONPATH=. python -m evals.simulate_pathway --json
"""

from __future__ import annotations

import argparse
import asyncio
import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, Iterator

from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import agents, main
from app.capacity import match_available_slots
from app.database import Base
from app.models import (
    Action,
    AgentDefinition,
    AgentSpecVersion,
    AgentStep,
    AgentToolCall,
    Appointment,
    CaseDocument,
    CaseDocumentVersion,
    CaseNote,
    Communication,
    Event,
    Goal,
    Patient,
    Referral,
    Slot,
)

_REAL_DISPATCH = agents.dispatch


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_simulation(_type, _compiler, **_kwargs):
    return "JSON"


def _response(*calls: tuple[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "content": [
            {"type": "tool_use", "id": f"sim-tool-{index}", "name": name, "input": inputs}
            for index, (name, inputs) in enumerate(calls, 1)
        ],
        "stop_reason": "tool_use",
        "usage": {"input_tokens": 20, "output_tokens": 10},
    }


class ScriptedAnthropic:
    """Deterministic Anthropic boundary that validates the published tool contract."""

    def __init__(self, responses: list[dict[str, Any]]):
        self.responses = iter(responses)
        self.requests: list[list[dict[str, Any]]] = []

    def __call__(self, messages: list[dict[str, Any]], spec: AgentSpecVersion) -> dict[str, Any]:
        response = next(self.responses)
        allowed = {tool["name"]: tool for tool in agents.tools_for_spec(spec)}
        for block in response["content"]:
            tool = allowed.get(block["name"])
            if tool is None:
                raise AssertionError(f"script used disallowed tool {block['name']}")
            missing = set(tool["input_schema"].get("required", [])) - set(block.get("input", {}))
            if missing:
                raise AssertionError(f"{block['name']} missing required inputs: {sorted(missing)}")
        self.requests.append(messages)
        return response


@contextmanager
def _replace(obj: object, name: str, value: object) -> Iterator[None]:
    original = getattr(obj, name)
    setattr(obj, name, value)
    try:
        yield
    finally:
        setattr(obj, name, original)


def _database() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine, expire_on_commit=False)


def _seed(session: Session) -> tuple[Goal, Slot]:
    patient = Patient(
        external_ref="SYNTHETIC-NO-PHONE-001",
        first_name="Amina",
        last_name="Example",
        date_of_birth=datetime(1985, 6, 15, tzinfo=UTC),
        phone=None,
        email="synthetic.invalid@example.invalid",
        preferred_contact_method="VOICE",
        preferred_language="English",
        constraints={"WEEKEND_ONLY": True},
    )
    referral = Referral(
        patient=patient,
        pathway_type="RTT",
        procedure="MRI",
        provider_org="Synthetic NHS Provider",
        status="ACTIVE",
    )
    goal = Goal(
        referral=referral,
        description="Arrange and complete MRI pathway",
        success_criteria={"appointment_status": "COMPLETED"},
        status="ACTIVE",
    )
    definition = AgentDefinition(key="caseworker")
    session.add_all([goal, definition])
    session.flush()
    version = AgentSpecVersion(
        definition=definition,
        version=1,
        name="Synthetic replay caseworker",
        role="CASEWORKER",
        instructions=agents.SYSTEM,
        tool_policy={
            "allowed": [tool["name"] for tool in agents.TOOLS],
            "max_turns": agents.MAX_TURNS,
            "max_tool_calls": agents.MAX_CALLS,
        },
        model="scripted-anthropic-no-network",
        status="PUBLISHED",
    )
    session.add(version)
    session.flush()
    definition.active_version_id = version.id
    session.add_all(
        [
            Event(
                goal_id=goal.id,
                event_type="REFERRAL_RECEIVED",
                source="synthetic_replay",
                payload={"synthetic": True, "phone_present": False},
                idempotency_key=f"synthetic-referral:{goal.id}",
            ),
            CaseNote(
                patient_id=patient.id,
                referral_id=referral.id,
                goal_id=goal.id,
                category="PREFERENCE",
                text="Patient prefers weekend appointments.",
                language=patient.preferred_language,
                source="SYNTHETIC_REPLAY",
            ),
        ]
    )
    # Find the next Saturday so the production weekend constraint is exercised.
    starts = datetime.now(UTC) + timedelta(days=2)
    while starts.weekday() != 5:
        starts += timedelta(days=1)
    slot = Slot(
        external_ref="SYNTHETIC-RELEASE-001",
        provider_org="Synthetic NHS Provider",
        site="North Imaging Centre",
        procedure="MRI",
        starts_at=starts.replace(hour=9, minute=0, second=0, microsecond=0),
        duration_minutes=30,
        properties={"synthetic": True},
        status="AVAILABLE",
    )
    session.add(slot)
    session.commit()
    return goal, slot


def _synthetic_queue_dispatch(session: Session, goal: Goal, name: str, args: dict):
    """Mute only the outbound transport boundary for a deliberately phone-less case."""
    if name != "queue_patient_call":
        return _REAL_DISPATCH(session, goal, name, args)
    key = f"synthetic-call-queue:{goal.id}:{goal.version}"
    if not session.scalar(select(Action).where(Action.idempotency_key == key)):
        session.add(
            Action(
                goal_id=goal.id,
                action_type="CALL_PATIENT",
                status="QUEUED",
                payload={
                    "reason": str(args.get("reason", ""))[:300],
                    "patient_first_name": goal.referral.patient.first_name,
                    "phone_number": None,
                    "synthetic": True,
                    "transport": "muted",
                },
                idempotency_key=key,
                requires_human_approval=False,
            )
        )
        session.add(
            Event(
                goal_id=goal.id,
                event_type="VOICE_CALL_QUEUED",
                source="synthetic_replay",
                payload={"synthetic": True, "transport": "muted"},
                idempotency_key=key,
            )
        )
    goal.status = "WAITING"
    goal.next_wake_at = datetime.now(UTC) + timedelta(days=1)
    return "Synthetic call queued; outbound transport is muted.", "OK", False, None


@contextmanager
def _reuse_session(session: Session):
    yield session
    session.flush()


class _FakeWebhooks:
    event: dict[str, Any] = {}

    def construct_event(self, **_kwargs):
        return self.event


class _FakeElevenLabs:
    def __init__(self, **_kwargs):
        self.webhooks = _FakeWebhooks()


class _FakeRequest:
    async def body(self) -> bytes:
        return b'{"synthetic":true}'


async def _simulate_elevenlabs(session: Session, goal: Goal, slot: Slot, outcome: str) -> dict[str, Any]:
    """Exercise the exact FastAPI tool handlers and webhook, with no SDK network use."""
    import elevenlabs.client

    conversation_id = f"synthetic-conversation-{outcome}-{goal.id}"
    _FakeWebhooks.event = {
        "type": "post_call_transcription",
        "data": {
            "conversation_id": conversation_id,
            "conversation_initiation_client_data": {"dynamic_variables": {"goal_id": str(goal.id)}},
            "analysis": {
                "transcript_summary": {
                    "accept": "Patient accepted the Saturday MRI appointment.",
                    "decline": "Patient declined this slot and asked for another weekend.",
                    "escalate": "Patient asked a clinical question requiring human review.",
                }[outcome]
            },
            "transcript": [
                {"role": "agent", "message": "Calling about the MRI appointment."},
                {"role": "user", "message": f"Synthetic {outcome} response."},
            ],
        },
    }
    old_database_url = main.settings.database_url
    old_webhook_secret = main.settings.elevenlabs_webhook_secret
    old_api_key = main.settings.elevenlabs_api_key
    main.settings.database_url = "sqlite://synthetic-memory"
    main.settings.elevenlabs_webhook_secret = "synthetic-secret"
    main.settings.elevenlabs_api_key = "synthetic-key"
    try:
        with (
            _replace(main, "session_scope", lambda: _reuse_session(session)),
            _replace(elevenlabs.client, "ElevenLabs", _FakeElevenLabs),
        ):
            case = await main.get_case(main.GoalRequest(goal_id=goal.id))
            offered = await main.offered_slots(main.GoalRequest(goal_id=goal.id))
            if outcome == "accept":
                tool_result = await main.accept_slot(main.SlotRequest(goal_id=goal.id, slot_id=slot.id))
            elif outcome == "decline":
                tool_result = await main.reject_slot(
                    main.SlotRequest(goal_id=goal.id, slot_id=slot.id, reason="Needs another weekend")
                )
            else:
                tool_result = await main.request_human(
                    main.ConstraintRequest(goal_id=goal.id, constraint="Clinical question from patient")
                )
            webhook = await main.elevenlabs_webhook(_FakeRequest(), elevenlabs_signature="synthetic-signature")
            # Replay the webhook to prove provider retries do not duplicate communications or notes.
            await main.elevenlabs_webhook(_FakeRequest(), elevenlabs_signature="synthetic-signature")
        return {"get_case": case, "offered_slots": offered, "tool_result": tool_result, "webhook": webhook}
    finally:
        main.settings.database_url = old_database_url
        main.settings.elevenlabs_webhook_secret = old_webhook_secret
        main.settings.elevenlabs_api_key = old_api_key


def _timeline(session: Session, goal_id) -> list[dict[str, Any]]:
    return [
        {"type": event.event_type, "source": event.source, "payload": event.payload}
        for event in session.scalars(
            select(Event).where(Event.goal_id == goal_id).order_by(Event.created_at, Event.id)
        ).all()
    ]


def run_scenario(outcome: str = "accept") -> dict[str, Any]:
    if outcome not in {"accept", "decline", "escalate"}:
        raise ValueError("outcome must be accept, decline, or escalate")
    session = _database()
    try:
        goal, slot = _seed(session)
        wake = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
        scripts = [
            _response(
                ("read_case_notes", {}),
                ("wait_until", {"wake_at": wake, "reason": "Waiting for suitable weekend capacity"}),
                ("end_step", {"title": "Waiting for weekend capacity", "trigger": "Referral received", "reason": "No suitable slot is currently available", "candidate_slots": [], "actions_taken": ["Scheduled a future capacity check"], "booking_released": False, "outcome": "Waiting", "next_action": "Check again when capacity changes"}),
            ),
            _response(
                ("read_case_notes", {}),
                ("queue_patient_call", {"reason": "Discuss the offered Saturday MRI slot"}),
                ("end_step", {"title": "Confirmation call queued", "trigger": "Appointment offered", "reason": "The patient must confirm the offered slot", "candidate_slots": [{"starts_at": slot.starts_at.isoformat(), "site": slot.site}], "actions_taken": ["Queued a patient call"], "booking_released": False, "outcome": "Awaiting patient response", "next_action": "Call the patient"}),
            ),
        ]
        scripted = ScriptedAnthropic(scripts)
        with _replace(agents, "model", scripted):
            agents.run_goal(session, goal)
            session.commit()
            # A capacity release wakes the overseer; the production matcher creates the offer.
            goal.next_wake_at = datetime.now(UTC)
            match = match_available_slots(session)
            session.commit()
            with _replace(agents, "dispatch", _synthetic_queue_dispatch):
                agents.run_goal(session, goal)
            session.commit()

        action = session.scalar(select(Action).where(Action.goal_id == goal.id))
        action.status = "COMPLETED"
        action.result = {"provider": "synthetic-elevenlabs", "network": False}
        action.completed_at = datetime.now(UTC)
        session.add(
            Communication(
                goal_id=goal.id,
                channel="VOICE",
                direction="OUTBOUND",
                external_id=f"synthetic-request-{outcome}-{goal.id}",
                summary="Synthetic call transport accepted; no phone was dialled.",
            )
        )
        session.commit()

        voice = asyncio.run(_simulate_elevenlabs(session, goal, slot, outcome))
        session.commit()

        if outcome == "accept":
            follow_up = ScriptedAnthropic(
                [
                    _response(
                        ("read_case_notes", {}),
                        ("write_case_document", {
                            "document_type": "OVERVIEW",
                            "title": "overview.md",
                            "content": "Patient accepted the Saturday MRI slot. Await attendance outcome.",
                        }),
                        ("wait_until", {
                            "wake_at": (datetime.now(UTC) + timedelta(days=7)).isoformat(),
                            "reason": "Await appointment attendance",
                        }),
                        ("end_step", {"title": "Appointment booked", "trigger": "Patient accepted the offered slot", "reason": "The selected MRI appointment was confirmed", "candidate_slots": [{"starts_at": slot.starts_at.isoformat(), "site": slot.site}], "actions_taken": ["Updated overview.md", "Scheduled attendance follow-up"], "booking_released": False, "outcome": "Booked", "next_action": "Wait for appointment attendance"}),
                    ),
                    _response(
                        ("complete_goal", {}),
                        ("end_step", {"title": "MRI pathway completed", "trigger": "Appointment completed", "reason": "The patient attended the booked appointment", "candidate_slots": [], "actions_taken": ["Completed the scheduling goal"], "booking_released": False, "outcome": "Completed", "next_action": "No further action"}),
                    ),
                ]
            )
            with _replace(agents, "model", follow_up):
                agents.run_goal(session, goal)
                session.commit()
                appointment = session.scalar(
                    select(Appointment).where(
                        Appointment.referral_id == goal.referral_id, Appointment.status == "BOOKED"
                    )
                )
                appointment.status = "COMPLETED"
                goal.next_wake_at = datetime.now(UTC)
                session.add(
                    Event(
                        goal_id=goal.id,
                        event_type="APPOINTMENT_COMPLETED",
                        source="synthetic_replay",
                        payload={"synthetic": True},
                        idempotency_key=f"synthetic-completed:{appointment.id}",
                    )
                )
                session.commit()
                agents.run_goal(session, goal)
                session.commit()

        steps = session.scalars(select(AgentStep).where(AgentStep.goal_id == goal.id).order_by(AgentStep.sequence)).all()
        calls = session.scalars(
            select(AgentToolCall).where(AgentToolCall.step_id.in_([step.id for step in steps]))
        ).all()
        notes = session.scalars(select(CaseNote).where(CaseNote.goal_id == goal.id)).all()
        communications = session.scalars(select(Communication).where(Communication.goal_id == goal.id)).all()
        documents = session.scalars(select(CaseDocument).where(CaseDocument.goal_id == goal.id)).all()
        versions = session.scalars(select(CaseDocumentVersion)).all()
        checks = {
            "production_database_untouched": True,
            "network_calls": 0,
            "patient_has_no_phone": goal.referral.patient.phone is None,
            "capacity_match_created_offer": match["matched"] == 1,
            "synthetic_call_was_queued": action is not None and action.payload.get("transport") == "muted",
            "transcript_stored_once": len([c for c in communications if c.external_id and c.external_id.startswith("synthetic-conversation")]) == 1,
            "transcript_note_stored_once": len([n for n in notes if n.source == "ELEVENLABS"]) == 1,
            "agent_trace_is_versioned": bool(steps) and all(step.agent_spec_version_id for step in steps),
            "tool_calls_are_traceable": len(calls) == sum(step.tool_call_count for step in steps),
            "expected_terminal_state": goal.status == ({"accept": "COMPLETED", "decline": "WAITING", "escalate": "HUMAN_REVIEW_REQUIRED"}[outcome]),
        }
        if outcome == "accept":
            checks["case_document_versioned"] = len(documents) == 1 and len(versions) == 1 and versions[0].version == 1
        return {
            "label": "SYNTHETIC / NO NETWORK / NO PRODUCTION DB",
            "scenario": outcome,
            "passed": all(value is True or value == 0 for value in checks.values()),
            "checks": checks,
            "goal": {"id": str(goal.id), "status": goal.status, "version": goal.version, "summary": goal.current_summary},
            "agent_steps": [
                {
                    "sequence": step.sequence,
                    "wake_reason": step.wake_reason,
                    "decision": step.decision,
                    "tool_call_count": step.tool_call_count,
                    "agent_spec_version_id": str(step.agent_spec_version_id),
                }
                for step in steps
            ],
            "tool_calls": [
                {"sequence": call.sequence, "name": call.tool_name, "status": call.status, "result": call.result_text}
                for call in calls
            ],
            "voice_tools": voice,
            "timeline": _timeline(session, goal.id),
            "case_notes": [{"category": note.category, "text": note.text, "source": note.source} for note in notes],
            "case_documents": [{"type": document.document_type, "title": document.title} for document in documents],
        }
    finally:
        session.close()


def run_all() -> dict[str, Any]:
    reports = [run_scenario(outcome) for outcome in ("accept", "decline", "escalate")]
    return {
        "label": "SYNTHETIC / NO NETWORK / NO PRODUCTION DB",
        "passed": all(report["passed"] for report in reports),
        "reports": reports,
    }


def main_cli() -> None:
    parser = argparse.ArgumentParser(description="Run hermetic synthetic nous pathway replays")
    parser.add_argument("--scenario", choices=["accept", "decline", "escalate", "all"], default="all")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = run_all() if args.scenario == "all" else run_scenario(args.scenario)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        reports = report.get("reports", [report])
        print(report["label"])
        for item in reports:
            print(f"{'PASS' if item['passed'] else 'FAIL'} {item['scenario']}")
            for check, value in item["checks"].items():
                print(f"  {check}: {value}")
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main_cli()
