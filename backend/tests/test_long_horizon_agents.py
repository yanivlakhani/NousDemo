from __future__ import annotations

from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app import agents
from app.models import Action, AgentStep, AgentToolCall, Appointment, CaseNote, Event, Slot


@pytest.fixture(autouse=True)
def active_version(monkeypatch):
    version = SimpleNamespace(
        id=uuid4(), version=1, name="Nous Caseworker", role="CASEWORKER",
        model="test-model", status="PUBLISHED", tool_policy={"allowed": [tool["name"] for tool in agents.TOOLS]},
        definition=SimpleNamespace(key="caseworker"),
    )
    monkeypatch.setattr(agents, "active_agent_spec", lambda _session: version)


def tool_response(*calls: tuple[str, dict]) -> dict:
    return {
        "content": [
            {"type": "tool_use", "id": f"tool-{index}", "name": name, "input": inputs}
            for index, (name, inputs) in enumerate(calls, 1)
        ],
        "stop_reason": "tool_use",
        "usage": {"input_tokens": 11, "output_tokens": 7},
    }


class RecordingSession:
    """Small unit-test session that records durable rows without a database."""

    def __init__(self, scalar_values: list[object] | None = None, scalars_values: list[list[object]] | None = None):
        self.added: list[object] = []
        self.scalar_values = list(scalar_values or [])
        self.scalars_values = list(scalars_values or [])

    def begin_nested(self):
        return nullcontext()

    def add(self, value):
        self.added.append(value)

    def add_all(self, values):
        self.added.extend(values)

    def flush(self):
        return None

    def scalar(self, _query):
        return self.scalar_values.pop(0) if self.scalar_values else None

    def scalars(self, _query):
        values = self.scalars_values.pop(0) if self.scalars_values else []
        return SimpleNamespace(all=lambda: values)


def goal_stub(*, version: int = 1):
    return SimpleNamespace(
        id=uuid4(),
        version=version,
        status="ACTIVE",
        next_wake_at=None,
        current_summary=None,
        current_blocker=None,
    )


def test_repeated_wake_cycles_preserve_prior_context_and_append_traces(monkeypatch):
    """A resumed goal gets a fresh step while retaining the earlier observation."""
    session, goal = RecordingSession(), goal_stub()
    durable_notes: list[str] = []
    observed_messages: list[list[dict]] = []

    def snapshot(_session, _goal):
        return {"goal": "Arrange MRI", "notes": list(durable_notes), "summary": _goal.current_summary}

    responses = iter(
        [
            tool_response(
                ("wait_until", {"wake_at": "2027-01-01T09:00:00+00:00", "reason": "Await reply"}),
                ("end_step", {"decision": "Waiting for patient reply"}),
            ),
            tool_response(
                ("write_case_note", {"category": "CONTACT", "text": "Patient replied by phone"}),
                ("wait_until", {"wake_at": "2027-01-02T09:00:00+00:00", "reason": "Await confirmation"}),
                ("end_step", {"decision": "Reply recorded; awaiting confirmation"}),
            ),
        ]
    )

    def fake_model(messages, _agent_spec):
        observed_messages.append(messages)
        return next(responses)

    def fake_dispatch(_session, _goal, name, inputs):
        if name == "write_case_note":
            durable_notes.append(inputs["text"])
            return "Case note recorded.", "OK", False, None
        if name == "wait_until":
            _goal.status = "WAITING"
            _goal.next_wake_at = datetime.fromisoformat(inputs["wake_at"])
            return "Wake scheduled.", "OK", False, None
        if name == "end_step":
            return "Step ended.", "OK", True, inputs["decision"]
        raise AssertionError(name)

    monkeypatch.setattr(agents, "context", snapshot)
    monkeypatch.setattr(agents, "model", fake_model)
    monkeypatch.setattr(agents, "dispatch", fake_dispatch)

    first = agents.run_goal(session, goal)
    goal.next_wake_at = datetime.now(UTC) - timedelta(seconds=1)
    second = agents.run_goal(session, goal)

    steps = [row for row in session.added if isinstance(row, AgentStep)]
    calls = [row for row in session.added if isinstance(row, AgentToolCall)]
    assert first["summary"] == "Waiting for patient reply"
    assert second["summary"] == "Reply recorded; awaiting confirmation"
    assert goal.version == 3
    assert len(steps) == 2 and len(calls) == 5
    assert steps[0].context["notes"] == []
    assert steps[1].context["notes"] == []  # note is written during, not before, the second observation
    assert "Waiting for patient reply" in observed_messages[1][0]["content"]
    assert durable_notes == ["Patient replied by phone"]


def test_next_cycle_reads_note_written_by_previous_cycle(monkeypatch):
    session, goal = RecordingSession(), goal_stub()
    durable_notes: list[str] = []
    first_messages: list[str] = []

    monkeypatch.setattr(
        agents,
        "context",
        lambda _session, _goal: {"goal": "Arrange MRI", "notes": list(durable_notes)},
    )

    responses = iter(
        [
            tool_response(
                ("write_case_note", {"category": "PREFERENCE", "text": "Saturday mornings only"}),
                ("wait_until", {"wake_at": "2027-01-01T09:00:00+00:00", "reason": "Await capacity"}),
                ("end_step", {"decision": "Preference recorded"}),
            ),
            tool_response(
                ("wait_until", {"wake_at": "2027-01-02T09:00:00+00:00", "reason": "Await capacity"}),
                ("end_step", {"decision": "Still waiting for Saturday capacity"}),
            ),
        ]
    )

    def fake_model(messages, _agent_spec):
        first_messages.append(messages[0]["content"])
        return next(responses)

    def fake_dispatch(_session, _goal, name, inputs):
        if name == "write_case_note":
            durable_notes.append(inputs["text"])
            return "recorded", "OK", False, None
        if name == "wait_until":
            _goal.status, _goal.next_wake_at = "WAITING", datetime.fromisoformat(inputs["wake_at"])
            return "waiting", "OK", False, None
        return "ended", "OK", True, inputs["decision"]

    monkeypatch.setattr(agents, "model", fake_model)
    monkeypatch.setattr(agents, "dispatch", fake_dispatch)
    agents.run_goal(session, goal)
    agents.run_goal(session, goal)

    assert "Saturday mornings only" not in first_messages[0]
    assert "Saturday mornings only" in first_messages[1]


def test_tool_budget_failure_schedules_retry_and_does_not_advance_version(monkeypatch):
    session, goal = RecordingSession(), goal_stub(version=8)
    calls = [("read_case_notes", {}) for _ in range(agents.MAX_CALLS + 1)]
    monkeypatch.setattr(agents, "context", lambda *_: {"goal": "Arrange MRI", "notes": []})
    monkeypatch.setattr(agents, "model", lambda _messages, _agent_spec: tool_response(*calls))
    monkeypatch.setattr(agents, "dispatch", lambda *_: ("notes", "OK", False, None))

    result = agents.run_goal(session, goal)
    failure = next(row for row in session.added if isinstance(row, AgentStep))

    assert result["fallback"] is True
    assert goal.status == "WAITING" and goal.next_wake_at > datetime.now(UTC)
    assert goal.version == 8
    assert failure.fallback is True
    assert "Tool budget exceeded" in failure.error


def test_human_escalation_is_terminal_until_operator_review():
    patient = SimpleNamespace(id=uuid4())
    referral = SimpleNamespace(id=uuid4(), patient=patient)
    goal = goal_stub()
    goal.referral = referral
    session = RecordingSession()

    result, status, ended, _ = agents.dispatch(
        session, goal, "request_human", {"reason": "Patient asked a clinical safety question"}
    )

    assert (result, status, ended) == ("Escalated.", "OK", False)
    assert goal.status == "HUMAN_REVIEW_REQUIRED"
    assert goal.next_wake_at is None
    assert goal.current_blocker == "Patient asked a clinical safety question"
    assert any(isinstance(row, Event) and row.event_type == "HUMAN_REVIEW_REQUESTED" for row in session.added)


def test_queue_call_uses_stable_idempotency_key_for_same_goal_version():
    patient = SimpleNamespace(id=uuid4(), first_name="Amira", phone="+447700900142")
    referral = SimpleNamespace(id=uuid4(), patient=patient)
    goal = goal_stub(version=4)
    goal.referral = referral
    session = RecordingSession()

    agents.dispatch(session, goal, "queue_patient_call", {"reason": "Confirm availability"})
    agents.dispatch(session, goal, "queue_patient_call", {"reason": "Confirm availability"})

    actions = [row for row in session.added if isinstance(row, Action)]
    assert len(actions) == 2
    assert {row.idempotency_key for row in actions} == {f"call-queue:{goal.id}:4"}


def test_slot_offer_never_cancels_existing_booking(monkeypatch):
    patient = SimpleNamespace(id=uuid4())
    referral = SimpleNamespace(id=uuid4(), patient=patient)
    goal = goal_stub()
    goal.referral = referral
    existing = Appointment(referral_id=referral.id, slot_id=uuid4(), status="BOOKED")
    candidate = Slot(
        id=uuid4(),
        provider_org="Provider",
        site="North",
        procedure="MRI",
        starts_at=datetime.now(UTC) + timedelta(days=5),
        duration_minutes=30,
        status="AVAILABLE",
    )
    session = RecordingSession(scalar_values=[None])
    monkeypatch.setattr(agents, "eligible_slots", lambda *_: [candidate])

    text, status, _, _ = agents.dispatch(
        session, goal, "offer_slot", {"slot_id": str(candidate.id), "reason": "Earlier suitable slot"}
    )

    offers = [row for row in session.added if isinstance(row, Appointment)]
    assert status == "OK" and "existing booking unchanged" in text
    assert existing.status == "BOOKED"
    assert candidate.status == "HELD"
    assert len(offers) == 1 and offers[0].status == "OFFERED"


def test_duplicate_pending_offers_self_heal_without_human_escalation():
    now = datetime.now(UTC)
    referral_id = uuid4()
    older_slot = Slot(id=uuid4(), provider_org="Provider", site="North", procedure="MRI", starts_at=now + timedelta(days=4), duration_minutes=30, status="HELD", held_until=now + timedelta(hours=5))
    newest_slot = Slot(id=uuid4(), provider_org="Provider", site="North", procedure="MRI", starts_at=now + timedelta(days=3), duration_minutes=30, status="HELD", held_until=now + timedelta(hours=10))
    older = Appointment(id=uuid4(), referral_id=referral_id, slot=older_slot, status="OFFERED", created_at=now - timedelta(minutes=5))
    newest = Appointment(id=uuid4(), referral_id=referral_id, slot=newest_slot, status="OFFERED", created_at=now)
    goal = goal_stub(); goal.referral_id = referral_id; goal.status = "HUMAN_REVIEW_REQUIRED"; goal.current_blocker = "An offer is already open"
    session = RecordingSession(scalars_values=[[newest, older]])

    retained = agents.reconcile_pending_offers(session, goal, now)

    assert retained is newest
    assert newest.status == "OFFERED" and newest_slot.status == "HELD"
    assert older.status == "EXPIRED" and older_slot.status == "AVAILABLE"
    assert goal.status == "WAITING" and goal.current_blocker is None
    assert any(isinstance(row, Event) and row.event_type == "REDUNDANT_OFFER_RECONCILED" for row in session.added)


def test_transcript_derived_case_note_is_visible_in_next_agent_context():
    """A persisted ElevenLabs summary must be part of the following observation."""
    patient = SimpleNamespace(id=uuid4(), first_name="Jo", preferred_contact_method="VOICE", preferred_language="Welsh", constraints={})
    referral = SimpleNamespace(
        id=uuid4(), patient=patient, pathway_type="RTT", procedure="MRI"
    )
    goal = goal_stub()
    goal.description = "Arrange MRI"
    goal.referral = referral
    note = CaseNote(
        patient_id=patient.id,
        referral_id=referral.id,
        goal_id=goal.id,
        category="CONTACT",
        text="Call transcript summary: patient confirmed Saturday mornings only.",
        language="Welsh",
        source="ELEVENLABS",
    )
    session = RecordingSession(scalars_values=[[note], []])

    snapshot = agents.context(session, goal)

    assert snapshot["notes"] == [
        {
            "category": "CONTACT",
            "text": "Call transcript summary: patient confirmed Saturday mornings only.",
            "language": "Welsh",
            "source": "ELEVENLABS",
        }
    ]


def test_agent_note_tool_reads_and_writes_patient_language():
    patient = SimpleNamespace(id=uuid4(), preferred_language="Polish")
    referral = SimpleNamespace(id=uuid4(), patient=patient)
    goal = goal_stub()
    goal.referral = referral
    prior = CaseNote(patient_id=patient.id, referral_id=referral.id, goal_id=goal.id, category="CONTACT", text="Interpreter requested.", language="Polish", source="OPERATOR")
    session = RecordingSession(scalars_values=[[prior]])

    text, status, _, _ = agents.dispatch(session, goal, "read_case_notes", {})
    assert status == "OK"
    assert text == "CONTACT [Polish]: Interpreter requested."

    agents.dispatch(session, goal, "write_case_note", {"category": "FOLLOW_UP", "text": "Interpreter booked."})
    written = next(row for row in session.added if isinstance(row, CaseNote))
    assert written.language == "Polish"


def test_wait_until_rejects_past_wake_without_changing_goal():
    patient = SimpleNamespace(id=uuid4())
    goal = goal_stub()
    goal.referral = SimpleNamespace(id=uuid4(), patient=patient)
    session = RecordingSession()
    original = (goal.status, goal.next_wake_at, goal.current_summary)

    _, status, _, _ = agents.dispatch(
        session,
        goal,
        "wait_until",
        {"wake_at": "2020-01-01T09:00:00+00:00", "reason": "Invalid stale wake"},
    )

    assert status == "REJECTED"
    assert (goal.status, goal.next_wake_at, goal.current_summary) == original
