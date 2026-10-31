from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import asyncio
from time import perf_counter

from app import capacity, main, workers
from app.models import Action, Appointment, Event, GoalDecision


class Rows:
    def __init__(self, values): self.values = values
    def all(self): return self.values


class OverseerSession:
    def __init__(self, *, slot, goals, current_by_goal):
        self.slot, self.goals, self.current_by_goal = slot, goals, current_by_goal
        self.added, self.scalars_calls, self.scalar_calls = [], 0, 0

    def scalars(self, _query):
        self.scalars_calls += 1
        # available slots; eligible goals (expired-hold release is stubbed)
        return Rows([[self.slot], self.goals][self.scalars_calls - 1])

    def scalar(self, _query):
        index = self.scalar_calls
        self.scalar_calls += 1
        # Per goal: duplicate appointment, existing offer, current booking.
        return [None, None, self.current_by_goal[self.goals[0].id], None, None, self.current_by_goal[self.goals[1].id]][index]

    def add(self, row): self.added.append(row)

    def flush(self):
        for row in self.added:
            if getattr(row, "id", None) is None: row.id = uuid4()


def make_goal(*, urgency, current_at, created_at, phone="+447700900111"):
    patient = SimpleNamespace(first_name="Pat", phone=phone, constraints={})
    referral = SimpleNamespace(id=uuid4(), patient=patient, procedure="MRI", deadline_at=None)
    goal = SimpleNamespace(id=uuid4(), referral_id=referral.id, referral=referral, status="WAITING", next_wake_at=None, version=2, success_criteria={"clinician_urgency": urgency}, created_at=created_at)
    current_slot = SimpleNamespace(starts_at=current_at)
    return goal, SimpleNamespace(slot=current_slot)


def test_released_slot_overseer_records_ranking_and_queues_delegated_offer_call(monkeypatch):
    now = datetime.now(UTC)
    slot = SimpleNamespace(id=uuid4(), procedure="MRI", starts_at=now + timedelta(days=2), status="AVAILABLE", held_until=None, properties={"released_gap": True})
    urgent, urgent_current = make_goal(urgency="URGENT", current_at=now + timedelta(days=10), created_at=now)
    routine, routine_current = make_goal(urgency="ROUTINE", current_at=now + timedelta(days=30), created_at=now - timedelta(days=1))
    session = OverseerSession(slot=slot, goals=[routine, urgent], current_by_goal={routine.id: routine_current, urgent.id: urgent_current})
    monkeypatch.setattr(capacity, "release_expired_holds", lambda *_: 0)

    result = capacity.match_available_slots(session, limit=1)

    decision = next(row for row in session.added if isinstance(row, GoalDecision))
    action = next(row for row in session.added if isinstance(row, Action))
    event = next(row for row in session.added if isinstance(row, Event))
    assert result["matched"] == 1 and result["offers"][0]["goal_id"] == str(urgent.id)
    assert decision.observation["ranking_policy"] == "clinician_assigned_urgency_then_administrative_fit"
    assert len(decision.observation["ranked_choices"]) == 2
    assert action.action_type == "CALL_PATIENT" and action.status == "QUEUED"
    assert action.payload["owner"] == "caseworker"
    assert action.payload["delegated_by"] == "capacity_overseer"
    assert action.payload["transport"] == "demo_browser_receiver"
    assert action.payload["receiver_token"]
    assert action.payload["purpose"] == "EARLIER_SLOT_OFFER"
    assert action.payload["slot_id"] == str(slot.id)
    assert action.payload["appointment_type"] == "MRI"
    assert action.payload["starts_at"] == slot.starts_at.isoformat()
    assert action.payload["site"] is None
    assert action.payload["selected_patient"]["goal_id"] == str(urgent.id)
    assert action.payload["delegation_key"] == action.idempotency_key
    assert action.payload["overseer_decision_id"] == str(decision.id)
    assert decision.proposed_action["selected_patient"]["goal_id"] == str(urgent.id)
    assert decision.observation["iteration_status"] == "CLOSED"
    assert decision.observation["next_wake_at"]
    assert event.event_type == "OVERSEER_DELEGATED"
    assert event.payload["overseer_decision_id"] == str(decision.id)
    assert urgent.next_wake_at is not None
    assert result["iteration_status"] == "CLOSED"
    assert result["next_wake_at"]


def test_caseworker_phone_status_tracks_call_lifecycle():
    action = SimpleNamespace(status="QUEUED", result=None)
    assert main._caseworker_phone_status(action) == "Ready to call"
    action.status = "RINGING_BROWSER"
    assert main._caseworker_phone_status(action) == "Calling patient"
    action.status = "IN_PROGRESS"
    assert main._caseworker_phone_status(action) == "On call"
    action.status, action.result = "COMPLETED", {"outcome": "Earlier appointment accepted"}
    assert main._caseworker_phone_status(action) == "Earlier appointment accepted"


def test_overseer_enqueues_multiple_caseworkers_without_running_them(monkeypatch):
    now = datetime.now(UTC)
    slots = [
        SimpleNamespace(id=uuid4(), procedure="MRI", starts_at=now + timedelta(days=offset), status="AVAILABLE", held_until=None, properties={"released_gap": True}, site="North")
        for offset in (2, 3)
    ]
    goals_and_current = [
        make_goal(urgency="URGENT", current_at=now + timedelta(days=10 + index), created_at=now + timedelta(seconds=index))
        for index in range(2)
    ]

    class ParallelQueueSession:
        def __init__(self):
            self.added, self.scalars_calls, self.scalar_values = [], 0, []
            for _, current in goals_and_current:
                self.scalar_values.extend([None, None, current])

        def scalars(self, _query):
            self.scalars_calls += 1
            if self.scalars_calls == 1:
                return Rows(slots)
            return Rows([goals_and_current[self.scalars_calls - 2][0]])

        def scalar(self, _query): return self.scalar_values.pop(0)
        def add(self, row): self.added.append(row)
        def flush(self):
            for row in self.added:
                if getattr(row, "id", None) is None: row.id = uuid4()

    session = ParallelQueueSession()
    monkeypatch.setattr(capacity, "release_expired_holds", lambda *_: 0)
    monkeypatch.setattr(workers, "dispatch_queued_calls", lambda *_: (_ for _ in ()).throw(RuntimeError("slow provider failed")))
    started = perf_counter()
    result = capacity.match_available_slots(session, limit=2)

    actions = [row for row in session.added if isinstance(row, Action)]
    assert perf_counter() - started < 0.25
    assert result["matched"] == 2 and len(actions) == 2
    assert len({action.idempotency_key for action in actions}) == 2
    assert all(action.status == "QUEUED" and action.payload["owner"] == "caseworker" for action in actions)
    completed_pass = next(row for row in session.added if isinstance(row, Event) and row.event_type == "OVERSEER_PASS_COMPLETED")
    assert completed_pass.payload["iteration_status"] == "CLOSED"
    assert completed_pass.payload["matched"] == 2


def test_overseer_persists_no_action_pass_and_schedules_next_wake(monkeypatch):
    class EmptyPassSession:
        def __init__(self): self.added = []
        def scalars(self, _query): return Rows([])
        def add(self, row): self.added.append(row)

    session = EmptyPassSession()
    monkeypatch.setattr(capacity, "release_expired_holds", lambda *_: 0)
    result = capacity.match_available_slots(session)

    completed = next(row for row in session.added if isinstance(row, Event))
    assert result["matched"] == 0
    assert result["last_iteration_summary"] == "No actionable release this pass"
    assert completed.event_type == "OVERSEER_PASS_COMPLETED"
    assert completed.payload["summary"] == "No actionable release this pass"
    assert completed.payload["next_wake_at"] == result["next_wake_at"]


def test_same_patient_slot_pair_has_one_database_enforced_dispatch_identity():
    goal_id, slot_id = uuid4(), uuid4()
    first = capacity._delegation_key(goal_id, slot_id)
    retry = capacity._delegation_key(goal_id, slot_id)

    assert first == retry == f"earlier-slot-offer:{goal_id}:{slot_id}"
    assert Action.__table__.c.idempotency_key.unique is True
    assert Event.__table__.c.idempotency_key.unique is True


def test_overseer_uses_explicit_urgency_and_labels_missing_urgency(monkeypatch):
    now = datetime.now(UTC)
    slot = SimpleNamespace(id=uuid4(), procedure="MRI", starts_at=now + timedelta(days=2), properties={"released_gap": True})
    reachable, reachable_current = make_goal(urgency=None, current_at=now + timedelta(days=8), created_at=now)
    explicit, explicit_current = make_goal(urgency="IMMEDIATE", current_at=now + timedelta(days=20), created_at=now)

    class RankSession:
        def scalars(self, _query): return Rows([explicit, reachable])
        def scalar(self, _query):
            values = getattr(self, "values", [None, None, explicit_current, None, None, reachable_current])
            self.values = values
            return self.values.pop(0)

    ranked = capacity._rank(RankSession(), slot, now)
    assert [goal.id for _, goal, _ in ranked] == [explicit.id, reachable.id]
    assert "UNSPECIFIED" in ranked[1][2][0]


def test_reject_slot_declines_offer_and_releases_hold_immediately(monkeypatch):
    slot_id, goal_id, referral_id = uuid4(), uuid4(), uuid4()
    goal = SimpleNamespace(id=goal_id, referral_id=referral_id, status="WAITING", next_wake_at=None)
    offer = SimpleNamespace(id=uuid4(), status="OFFERED")
    slot = SimpleNamespace(id=slot_id, status="HELD", held_until=datetime.now(UTC) + timedelta(hours=2), properties={})

    class RejectSession:
        def __init__(self): self.values, self.added = [offer, slot], []
        def scalar(self, _query): return self.values.pop(0)
        def add(self, row): self.added.append(row)
        def flush(self): pass

    session = RejectSession()
    @contextmanager
    def scope(): yield session
    monkeypatch.setattr(main, "require_database", lambda: None)
    monkeypatch.setattr(main, "session_scope", scope)
    monkeypatch.setattr(main, "load_goal", lambda *_: goal)
    monkeypatch.setattr(main, "match_available_slots", lambda *_args, **_kwargs: {"matched": 0, "offers": []})

    result = asyncio.run(main.reject_slot(main.SlotRequest(goal_id=goal_id, slot_id=slot_id, reason="Cannot attend")))

    assert result["slot_released"] is True
    assert offer.status == "DECLINED"
    assert slot.status == "AVAILABLE" and slot.held_until is None
    assert {row.event_type for row in session.added} == {"SLOT_REJECTED", "SLOT_RELEASED"}
