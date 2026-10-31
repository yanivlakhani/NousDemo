import asyncio
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from app import main
from app.main import BrowserConversationRequest, ConstraintRequest, DemoPhoneAnswerRequest, DemoPhoneDeclineRequest, GoalRequest, IdentityVerificationRequest, ReferralCreate, SlotRequest, app


client = TestClient(app)
GOAL_ID = "00000000-0000-0000-0000-000000000042"
SLOT_ID = "00000000-0000-0000-0000-000000000018"


def test_health_uses_fake_provider_locally():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True, "database": False, "voice_provider": "fake", "agent_provider": "not_configured"}


def test_local_call_completes_without_telephony():
    response = client.post(
        "/api/voice/call",
        json={
            "goal_id": GOAL_ID,
            "patient_first_name": "Amira",
            "phone_number": "+447700900142",
            "reason": "Confirm an offered Saturday appointment",
            "proposed_slot_id": SLOT_ID,
        },
    )
    assert response.status_code == 200
    assert response.json()["provider"] == "simulated"
    assert response.json()["simulated"] is True
    assert response.json()["transport"] == "none"
    assert response.json()["outcome"] == "ANSWERED"


def test_browser_session_keeps_api_key_server_side_and_returns_case_context(monkeypatch):
    patient = SimpleNamespace(first_name="Amira", preferred_language="Hindi")
    offered = SimpleNamespace(slot_id=SLOT_ID, status="OFFERED", created_at=datetime(2026, 10, 15, tzinfo=UTC))
    goal = SimpleNamespace(id=GOAL_ID, referral=SimpleNamespace(patient=patient, appointments=[offered]))
    captured = {}
    receiver_action = SimpleNamespace(id=SLOT_ID, goal_id=GOAL_ID, status="RINGING_BROWSER", payload={"receiver_token": "receiver-token-123456"})

    class FakeSession:
        def get(self, _model, _id): return receiver_action

    @contextmanager
    def fake_scope():
        yield FakeSession()

    class FakeResponse:
        status_code = 200
        def json(self):
            return {"signed_url": "wss://example.invalid/signed?token=short-lived"}

    class FakeClient:
        def __init__(self, **_kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_args): pass
        async def get(self, url, **kwargs):
            captured.update({"url": url, **kwargs})
            return FakeResponse()

    monkeypatch.setattr(main, "require_database", lambda: None)
    monkeypatch.setattr(main, "session_scope", fake_scope)
    monkeypatch.setattr(main, "load_goal", lambda _session, _goal_id: goal)
    monkeypatch.setattr(main, "match_available_slots", lambda *_args, **_kwargs: {"matched": 0, "offers": []})
    monkeypatch.setattr(main.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(main.settings, "elevenlabs_api_key", "server-secret")
    monkeypatch.setattr(main.settings, "elevenlabs_agent_id", "agent_demo")

    result = asyncio.run(main.browser_voice_session(BrowserConversationRequest(goal_id=GOAL_ID, action_id=SLOT_ID, receiver_token="receiver-token-123456")))

    assert result["transport"] == "browser_websocket"
    assert result["dynamic_variables"] == {"goal_id": GOAL_ID, "patient_first_name": "Amira", "preferred_language": "hi", "proposed_slot_id": SLOT_ID, "purpose": "FOLLOW_UP", "reason": "Progress appointment scheduling"}
    assert result["language_code"] == "hi"
    assert "api_key" not in result and "server-secret" not in str(result)
    assert captured["headers"] == {"xi-api-key": "server-secret"}
    assert captured["params"] == {"agent_id": "agent_demo"}


def test_browser_session_explicit_slot_overrides_current_offer(monkeypatch):
    current_slot_id = "00000000-0000-0000-0000-000000000019"
    patient = SimpleNamespace(first_name="Amira", preferred_language="Hindi")
    offered = SimpleNamespace(slot_id=current_slot_id, status="OFFERED", created_at=datetime(2026, 10, 15, tzinfo=UTC))
    goal = SimpleNamespace(id=GOAL_ID, referral=SimpleNamespace(patient=patient, appointments=[offered]))
    receiver_action = SimpleNamespace(id=SLOT_ID, goal_id=GOAL_ID, status="RINGING_BROWSER", payload={"receiver_token": "receiver-token-123456"})

    class FakeSession:
        def get(self, _model, _id): return receiver_action

    @contextmanager
    def fake_scope():
        yield FakeSession()

    class FakeResponse:
        status_code = 200
        def json(self):
            return {"signed_url": "wss://example.invalid/signed?token=short-lived"}

    class FakeClient:
        def __init__(self, **_kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_args): pass
        async def get(self, _url, **_kwargs): return FakeResponse()

    monkeypatch.setattr(main, "require_database", lambda: None)
    monkeypatch.setattr(main, "session_scope", fake_scope)
    monkeypatch.setattr(main, "load_goal", lambda _session, _goal_id: goal)
    monkeypatch.setattr(main.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(main.settings, "elevenlabs_api_key", "server-secret")
    monkeypatch.setattr(main.settings, "elevenlabs_agent_id", "agent_demo")

    result = asyncio.run(main.browser_voice_session(BrowserConversationRequest(goal_id=GOAL_ID, proposed_slot_id=SLOT_ID, action_id=SLOT_ID, receiver_token="receiver-token-123456")))

    assert result["dynamic_variables"]["proposed_slot_id"] == SLOT_ID


def test_another_patients_phone_cannot_answer_the_call(monkeypatch):
    patient = SimpleNamespace(first_name="Amira", preferred_language="English")
    goal = SimpleNamespace(id=GOAL_ID, referral_id=SLOT_ID, status="WAITING", current_blocker=None, next_wake_at=None, referral=SimpleNamespace(patient=patient, appointments=[]))
    other_goal_id = "00000000-0000-0000-0000-000000000099"
    receiver_action = SimpleNamespace(id=SLOT_ID, goal_id=other_goal_id, status="RINGING_BROWSER", payload={"receiver_token": "receiver-token-123456"})

    class FakeSession:
        def get(self, _model, _id): return receiver_action

    @contextmanager
    def fake_scope():
        yield FakeSession()

    monkeypatch.setattr(main, "require_database", lambda: None)
    monkeypatch.setattr(main, "session_scope", fake_scope)
    monkeypatch.setattr(main, "load_goal", lambda _session, _goal_id: goal)
    monkeypatch.setattr(main.settings, "elevenlabs_api_key", "server-secret")
    monkeypatch.setattr(main.settings, "elevenlabs_agent_id", "agent_demo")

    with pytest.raises(main.HTTPException) as error:
        asyncio.run(main.browser_voice_session(BrowserConversationRequest(goal_id=GOAL_ID, action_id=SLOT_ID, receiver_token="receiver-token-123456")))
    assert error.value.status_code == 403


def test_demo_phone_returns_only_minimal_incoming_call_context(monkeypatch):
    patient = SimpleNamespace(first_name="Amira", preferred_language="Hindi")
    goal = SimpleNamespace(id=GOAL_ID, referral=SimpleNamespace(patient=patient, procedure="MRI"))
    action = SimpleNamespace(
        id=SLOT_ID,
        action_type="CALL_PATIENT",
        status="QUEUED",
        payload={"purpose": "REMINDER", "reason": "Confirm tomorrow's appointment", "receiver_token": "receiver-token-123456", "receiver_ready": True},
        created_at=datetime.now(UTC),
    )

    class FakeSession:
        def __init__(self): self.calls = 0
        def scalar(self, _query):
            self.calls += 1
            return goal if self.calls == 1 else action

    fake_session = FakeSession()

    @contextmanager
    def fake_scope():
        yield fake_session

    monkeypatch.setattr(main, "require_database", lambda: None)
    monkeypatch.setattr(main, "session_scope", fake_scope)

    result = asyncio.run(main.demo_phone_incoming("DEMO-AMIRA"))

    assert result == {
        "waiting": False,
        "goal_id": GOAL_ID,
        "action_id": SLOT_ID,
        "receiver_token": "receiver-token-123456",
        "patient_first_name": "Amira",
        "procedure": "MRI",
        "purpose": "REMINDER",
        "reason": "Confirm tomorrow's appointment",
        "preferred_language": "Hindi",
    }
    assert "date_of_birth" not in result
    assert "phone" not in result
    assert "notes" not in result


def test_demo_reset_request_rejects_any_scope_other_than_demo_prefix():
    with pytest.raises(ValidationError):
        main.DemoResetRequest(
            operation_id="presenter-reset-0001",
            scope="*",
            confirmation="RESET DEMO-* RECORDS",
        )


def test_demo_reset_requires_presenter_header(monkeypatch):
    monkeypatch.setattr(main, "require_database", lambda: None)
    request = main.DemoResetRequest(
        operation_id="presenter-reset-0002",
        scope="DEMO-*",
        confirmation="RESET DEMO-* RECORDS",
    )

    with pytest.raises(main.HTTPException) as error:
        asyncio.run(main.reset_demo_data(request, None))

    assert error.value.status_code == 404


def test_demo_reset_is_transactional_validated_rate_guarded_and_idempotent(monkeypatch):
    class FakeSession:
        def flush(self): pass

    scope_calls = 0

    @contextmanager
    def fake_scope():
        nonlocal scope_calls
        scope_calls += 1
        yield FakeSession()

    reports = iter([
        {"counts": {"appointments": 15}, "patients": [], "status_counts": {}, "valid": False, "violations": [{"code": "STALE"}]},
        {"counts": {"appointments": 5, "open_offers": 0}, "patients": [{"external_ref": "DEMO-ASHA-01"}], "status_counts": {"appointments": {"BOOKED": 5}}, "valid": True, "violations": []},
    ])
    monkeypatch.setattr(main, "session_scope", fake_scope)
    monkeypatch.setattr(main, "require_database", lambda: None)
    monkeypatch.setattr(main, "audit_demo_state", lambda _session: next(reports))
    monkeypatch.setattr(main, "cleanup_demo_state", lambda _session: {"appointments_removed": 10})
    monkeypatch.setattr(main, "_demo_reset_last_at", 0.0)
    main._demo_reset_results.clear()
    request = main.DemoResetRequest(
        operation_id="presenter-reset-0003",
        scope="DEMO-*",
        confirmation="RESET DEMO-* RECORDS",
    )

    first = asyncio.run(main.reset_demo_data(request, "1"))
    second = asyncio.run(main.reset_demo_data(request, "1"))

    assert first == second
    assert scope_calls == 1
    assert first["scope"] == "DEMO-*"
    assert first["changes"] == {"appointments_removed": 10}
    assert first["validation"] == {"valid": True, "violations": []}
    assert first["after_counts"] == {"appointments": 5, "open_offers": 0}

    another = main.DemoResetRequest(
        operation_id="presenter-reset-0004",
        scope="DEMO-*",
        confirmation="RESET DEMO-* RECORDS",
    )
    with pytest.raises(main.HTTPException) as error:
        asyncio.run(main.reset_demo_data(another, "1"))
    assert error.value.status_code == 429


def test_always_ready_phone_reuses_delegated_action_and_completion_is_idempotent(monkeypatch):
    patient = SimpleNamespace(first_name="Amira", preferred_language="Hindi")
    goal = SimpleNamespace(id=GOAL_ID, referral_id=SLOT_ID, status="WAITING", current_blocker=None, next_wake_at=None, referral=SimpleNamespace(patient=patient, appointments=[]))
    action = SimpleNamespace(
        id=SLOT_ID, goal_id=GOAL_ID, action_type="EARLIER_SLOT_OFFER", status="QUEUED",
        payload={"purpose": "EARLIER_SLOT_OFFER", "receiver_token": "receiver-token-123456", "receiver_ready": True},
        created_at=datetime.now(UTC), completed_at=None, result=None,
    )
    added = []

    class FakeSession:
        def get(self, _model, _id): return action
        def scalars(self, _query): return SimpleNamespace(all=lambda: [])
        def add(self, value): added.append(value)
        def flush(self): pass

    @contextmanager
    def fake_scope():
        yield FakeSession()

    monkeypatch.setattr(main, "require_database", lambda: None)
    monkeypatch.setattr(main, "session_scope", fake_scope)
    monkeypatch.setattr(main, "_demo_phone_goal", lambda _session, _claim: goal)
    monkeypatch.setattr(main, "load_goal", lambda _session, _goal_id: goal)
    monkeypatch.setattr(main, "match_available_slots", lambda *_args, **_kwargs: {"matched": 0, "offers": []})

    answered = asyncio.run(main.demo_phone_answer(DemoPhoneAnswerRequest(claim_code="DEMO-AMIRA", action_id=SLOT_ID)))
    assert answered == {"goal_id": GOAL_ID, "action_id": SLOT_ID, "receiver_token": "receiver-token-123456"}
    assert action.status == "RINGING_BROWSER"

    request = BrowserConversationRequest(goal_id=GOAL_ID, action_id=SLOT_ID, receiver_token="receiver-token-123456")
    first = asyncio.run(main.demo_phone_complete(request))
    second = asyncio.run(main.demo_phone_complete(request))
    assert first["status"] == second["status"] == "COMPLETED"
    assert len([value for value in added if isinstance(value, main.Communication)]) == 1
    assert len([value for value in added if isinstance(value, main.Event)]) == 2


def test_declined_browser_call_stays_with_caseworker_and_never_releases_capacity(monkeypatch):
    patient = SimpleNamespace(first_name="Amira", preferred_language="Hindi")
    goal = SimpleNamespace(id=GOAL_ID, referral_id=SLOT_ID, status="WAITING", current_blocker=None, next_wake_at=None, referral=SimpleNamespace(patient=patient, appointments=[]))
    action = SimpleNamespace(
        id=SLOT_ID, goal_id=GOAL_ID, action_type="CALL_PATIENT", status="QUEUED",
        payload={"purpose": "REMINDER", "receiver_token": "receiver-token-123456", "receiver_ready": True},
        completed_at=None, result=None,
    )
    added = []

    class FakeSession:
        def get(self, _model, _id): return action
        def scalars(self, _query): return SimpleNamespace(all=lambda: [])
        def add(self, value): added.append(value)

    @contextmanager
    def fake_scope():
        yield FakeSession()

    monkeypatch.setattr(main, "require_database", lambda: None)
    monkeypatch.setattr(main, "session_scope", fake_scope)
    monkeypatch.setattr(main, "_demo_phone_goal", lambda _session, _claim: goal)

    result = asyncio.run(main.demo_phone_decline(DemoPhoneDeclineRequest(claim_code="DEMO-AMIRA", action_id=SLOT_ID)))

    assert result == {"ok": True, "outcome": "DECLINED"}
    assert action.status == "DECLINED"
    assert action.result == {"outcome": "DECLINED", "transport": "demo_browser_receiver"}
    event_types = [value.event_type for value in added if isinstance(value, main.Event)]
    assert event_types == ["OFFER_RELEASED_ON_CALL_END", "VOICE_CALL_DECLINED"]
    assert "SLOT_RELEASED" not in event_types
    assert "OVERSEER_DELEGATED" not in event_types


@pytest.mark.parametrize(
    ("outcome", "expected_status", "communication_outcome"),
    [("COMPLETED", "COMPLETED", "ANSWERED"), ("FAILED", "FAILED", "FAILED"), ("TIMED_OUT", "TIMED_OUT", "NO_ANSWER")],
)
def test_browser_call_endings_terminalize_action_and_remove_live_projection(monkeypatch, outcome, expected_status, communication_outcome):
    patient = SimpleNamespace(first_name="Amira", preferred_language="English")
    goal = SimpleNamespace(id=GOAL_ID, referral_id=SLOT_ID, status="WAITING", current_blocker=None, next_wake_at=None, referral=SimpleNamespace(patient=patient, appointments=[]))
    action = SimpleNamespace(
        id=SLOT_ID, goal_id=GOAL_ID, action_type="CALL_PATIENT", status="IN_PROGRESS",
        payload={"purpose": "FOLLOW_UP", "receiver_token": "receiver-token-123456", "receiver_ready": True},
        created_at=datetime.now(UTC), completed_at=None, result=None,
    )
    added = []

    class FakeSession:
        def get(self, _model, _id): return action
        def scalars(self, _query): return SimpleNamespace(all=lambda: [])
        def add(self, value): added.append(value)
        def flush(self): pass

    @contextmanager
    def fake_scope():
        yield FakeSession()

    monkeypatch.setattr(main, "require_database", lambda: None)
    monkeypatch.setattr(main, "session_scope", fake_scope)
    monkeypatch.setattr(main, "load_goal", lambda _session, _goal_id: goal)
    matcher_calls = []
    monkeypatch.setattr(main, "match_available_slots", lambda *_args, **kwargs: matcher_calls.append(kwargs) or {"matched": 0})

    request = main.DemoPhoneEndRequest(goal_id=GOAL_ID, action_id=SLOT_ID, receiver_token="receiver-token-123456", outcome=outcome)
    result = asyncio.run(main.demo_phone_complete(request))

    assert result == {"ok": True, "status": expected_status, "outcome": expected_status}
    assert action.completed_at is not None
    assert action.status not in main.LIVE_BROWSER_CALL_STATUSES
    assert [item.outcome for item in added if isinstance(item, main.Communication)] == [communication_outcome]
    assert matcher_calls == ([{"limit": 1}] if outcome == "COMPLETED" else [])


def test_cancel_and_timeout_are_idempotent_terminal_states():
    for initial, outcome in (("RINGING_BROWSER", "CANCELLED"), ("QUEUED", "TIMED_OUT")):
        action = SimpleNamespace(status=initial, completed_at=None, result=None)
        assert main._terminalize_browser_action(action, outcome) is True
        ended_at = action.completed_at
        assert main._terminalize_browser_action(action, "FAILED") is False
        assert action.status == outcome
        assert action.completed_at == ended_at
        assert action.result["outcome"] == outcome


def test_call_end_releases_open_offer_but_preserves_explicit_booking():
    slot = SimpleNamespace(id=SLOT_ID, status="HELD", held_until=datetime.now(UTC), properties={})
    offer = SimpleNamespace(id=SLOT_ID, slot_id=SLOT_ID, status="OFFERED")
    action = SimpleNamespace(id=SLOT_ID)
    goal = SimpleNamespace(id=GOAL_ID, referral_id=SLOT_ID, status="HUMAN_REVIEW_REQUIRED", current_blocker="offer is already open", next_wake_at=None)
    added = []

    class FakeSession:
        def scalars(self, _query): return SimpleNamespace(all=lambda: [offer] if offer.status == "OFFERED" else [])
        def get(self, model, _id): return slot if model is main.Slot else None
        def add(self, value): added.append(value)

    released = main._release_unaccepted_offers_on_call_end(FakeSession(), goal, action, "FAILED")
    assert released == [SLOT_ID]
    assert offer.status == "EXPIRED"
    assert slot.status == "AVAILABLE" and slot.held_until is None
    assert goal.status == "WAITING" and goal.current_blocker is None
    assert [event.event_type for event in added] == ["OFFER_RELEASED_ON_CALL_END"]

    offer.status = "BOOKED"
    slot.status = "BOOKED"
    added.clear()
    assert main._release_unaccepted_offers_on_call_end(FakeSession(), goal, action, "COMPLETED") == []
    assert offer.status == "BOOKED" and slot.status == "BOOKED"


def test_expired_call_is_no_longer_reported_as_incoming(monkeypatch):
    patient = SimpleNamespace(first_name="Amira", preferred_language="Hindi")
    goal = SimpleNamespace(id=GOAL_ID, referral_id=SLOT_ID, status="WAITING", current_blocker=None, next_wake_at=None, referral=SimpleNamespace(patient=patient, procedure="MRI"))
    action = SimpleNamespace(
        id=SLOT_ID, action_type="CALL_PATIENT", status="RINGING_BROWSER",
        payload={"receiver_token": "receiver-token-123456", "receiver_ready": True},
        created_at=datetime.now(UTC) - timedelta(minutes=16), completed_at=None, result=None,
    )

    class FakeSession:
        def __init__(self): self.calls = 0
        def scalar(self, _query):
            self.calls += 1
            return goal if self.calls == 1 else action
        def scalars(self, _query): return SimpleNamespace(all=lambda: [])
        def add(self, _value): pass

    @contextmanager
    def fake_scope():
        yield FakeSession()

    monkeypatch.setattr(main, "require_database", lambda: None)
    monkeypatch.setattr(main, "session_scope", fake_scope)
    result = asyncio.run(main.demo_phone_incoming("DEMO-AMIRA"))

    assert result["waiting"] is True
    assert result["action_id"] is None
    assert action.status == "TIMED_OUT"
    assert action.completed_at is not None


def test_patient_projection_only_exposes_genuinely_live_call_banner():
    patient = SimpleNamespace(id=GOAL_ID, external_ref="DEMO-AMIRA", first_name="Amira", last_name="Shah", phone=None, email=None, preferred_language="English", preferred_contact_method="VOICE", administrative_notes=None, constraints={})
    referral = SimpleNamespace(id=SLOT_ID, patient=patient, pathway_type="RTT", procedure="MRI", appointments=[])
    live = SimpleNamespace(id=SLOT_ID, action_type="CALL_PATIENT", status="RINGING_BROWSER", created_at=datetime.now(UTC))
    goal = SimpleNamespace(id=GOAL_ID, referral=referral, status="WAITING", current_blocker=None, next_wake_at=None, actions=[live])

    projected = main.case_json(goal)
    assert projected["active_call_action_id"] == SLOT_ID
    assert projected["active_call_status"] == "RINGING_BROWSER"

    live.status = "COMPLETED"
    projected = main.case_json(goal)
    assert projected["active_call_action_id"] is None
    assert projected["active_call_status"] is None


def test_elevenlabs_metadata_fetches_live_agent_when_phone_calls_are_simulated(monkeypatch):
    fetched = {}

    async def fake_metadata(api_key, agent_id, phone_number_id, *, refresh=False):
        fetched.update({
            "api_key": api_key,
            "agent_id": agent_id,
            "phone_number_id": phone_number_id,
            "refresh": refresh,
        })
        return {
            "configured": True,
            "available": True,
            "agent_id": agent_id,
            "agent_name": "Nous Scheduling Caseworker",
            "agent_version": "version_7",
            "attached_tools": [{"id": f"tool_{index}", "name": f"Tool {index}"} for index in range(7)],
            "webhook_status": "Active",
        }

    monkeypatch.setattr(main.settings, "use_fake_voice", True)
    monkeypatch.setattr(main.settings, "elevenlabs_api_key", "server-secret")
    monkeypatch.setattr(main.settings, "elevenlabs_agent_id", "agent_demo")
    monkeypatch.setattr(main.settings, "elevenlabs_phone_number_id", None)
    monkeypatch.setattr(main, "fetch_elevenlabs_metadata", fake_metadata)

    result = asyncio.run(main.elevenlabs_integration_metadata(refresh=True))

    assert fetched == {"api_key": "server-secret", "agent_id": "agent_demo", "phone_number_id": None, "refresh": True}
    assert result["agent_version"] == "version_7"
    assert len(result["attached_tools"]) == 7
    assert result["webhook_status"] == "Active"
    assert result["browser_available"] is True
    assert result["browser_authentication"] == "signed_url"
    assert result["browser_session_endpoint"] == "/api/voice/browser-session"
    assert result["telephone_transport"] == "simulated"
    assert result["simulated_outcomes"] is True
    assert "server-secret" not in str(result)


def test_voice_tools_require_database():
    paths = (
        "/elevenlabs/tools/get-case",
        "/elevenlabs/tools/verify-identity",
        "/elevenlabs/tools/list-offered-slots",
        "/elevenlabs/tools/list-reschedule-slots",
        "/elevenlabs/tools/accept-slot",
        "/elevenlabs/tools/reject-slot",
        "/elevenlabs/tools/patient-constraint",
        "/elevenlabs/tools/request-human",
    )
    for path in paths:
        body = {"goal_id": GOAL_ID}
        if path.endswith(("accept-slot", "reject-slot")):
            body["slot_id"] = SLOT_ID
        if path.endswith(("patient-constraint", "request-human")):
            body["constraint"] = "Needs an interpreter"
        if path.endswith("verify-identity"):
            body["date_of_birth"] = "1980-01-02"
        response = client.post(path, json=body)
        assert response.status_code == 503, path


def test_elevenlabs_tool_request_contracts_are_strictly_typed():
    assert GoalRequest(goal_id=GOAL_ID).goal_id
    assert SlotRequest(goal_id=GOAL_ID, slot_id=SLOT_ID, reason="Not available").reason == "Not available"
    assert ConstraintRequest(goal_id=GOAL_ID, constraint="Tuesday mornings").constraint == "Tuesday mornings"
    assert IdentityVerificationRequest(goal_id=GOAL_ID, date_of_birth="1980-01-02").date_of_birth.isoformat() == "1980-01-02"
    referral = ReferralCreate(external_ref="R1", first_name="A", last_name="B", date_of_birth="1980-01-02", phone="+447700900001", pathway_type="RTT", procedure="MRI", provider_org="Provider")
    assert referral.date_of_birth.isoformat() == "1980-01-02"
    with pytest.raises(ValidationError):
        SlotRequest(goal_id=GOAL_ID)
    with pytest.raises(ValidationError):
        ConstraintRequest(goal_id=GOAL_ID)


def test_new_referral_requires_a_real_past_date_of_birth():
    valid = {
        "external_ref": "R1",
        "first_name": "A",
        "last_name": "B",
        "pathway_type": "RTT",
        "provider_org": "Provider",
        "phone": "+447700900001",
    }
    with pytest.raises(ValidationError):
        ReferralCreate(**valid)
    with pytest.raises(ValidationError, match="must be in the past"):
        ReferralCreate(**valid, date_of_birth=date.today())
    with pytest.raises(ValidationError, match="must be in the past"):
        ReferralCreate(**valid, date_of_birth=date.today() + timedelta(days=1))
    with pytest.raises(ValidationError):
        ReferralCreate(**valid, date_of_birth="2025-02-29")
    with pytest.raises(ValidationError, match="international format"):
        ReferralCreate(**{**valid, "phone": "07700"}, date_of_birth="1980-01-02")
    assert ReferralCreate(**valid, date_of_birth="1980-01-02").date_of_birth.isoformat() == "1980-01-02"


def test_openapi_exposes_exact_elevenlabs_post_contracts():
    schema = client.get("/openapi.json").json()
    expected = {
        "/elevenlabs/tools/get-case": "GoalRequest",
        "/elevenlabs/tools/verify-identity": "IdentityVerificationRequest",
        "/elevenlabs/tools/list-offered-slots": "GoalRequest",
        "/elevenlabs/tools/list-reschedule-slots": "GoalRequest",
        "/elevenlabs/tools/accept-slot": "SlotRequest",
        "/elevenlabs/tools/reject-slot": "SlotRequest",
        "/elevenlabs/tools/patient-constraint": "ConstraintRequest",
        "/elevenlabs/tools/request-human": "ConstraintRequest",
    }
    for path, model in expected.items():
        operation = schema["paths"][path]
        assert set(operation) == {"post"}
        request_schema = operation["post"]["requestBody"]["content"]["application/json"]["schema"]
        assert request_schema["$ref"].endswith(f"/{model}")

    webhook = schema["paths"]["/webhooks/elevenlabs"]["post"]
    signature = next(parameter for parameter in webhook["parameters"] if parameter["name"] == "elevenlabs-signature")
    assert signature["in"] == "header"


def test_identity_verification_returns_only_boolean_and_get_case_does_not_leak_dob(monkeypatch):
    patient = SimpleNamespace(first_name="Amira", date_of_birth=datetime(1980, 1, 2, tzinfo=UTC))
    goal = SimpleNamespace(id=GOAL_ID, referral_id=SLOT_ID, description="Arrange MRI", status="ACTIVE", current_blocker=None, referral=SimpleNamespace(patient=patient))

    class FakeSession:
        def scalar(self, _query): return None

    @contextmanager
    def fake_scope():
        yield FakeSession()

    monkeypatch.setattr(main, "require_database", lambda: None)
    monkeypatch.setattr(main, "session_scope", fake_scope)
    monkeypatch.setattr(main, "load_goal", lambda _session, _goal_id: goal)

    verified = asyncio.run(main.verify_identity(IdentityVerificationRequest(goal_id=GOAL_ID, date_of_birth="1980-01-02")))
    rejected = asyncio.run(main.verify_identity(IdentityVerificationRequest(goal_id=GOAL_ID, date_of_birth="1980-01-03")))
    voice_case = asyncio.run(main.get_case(GoalRequest(goal_id=GOAL_ID)))

    assert verified == {"verified": True}
    assert rejected == {"verified": False}
    assert "date_of_birth" not in voice_case
    assert "1980-01-02" not in str(voice_case)


def test_webhook_requires_signature():
    response = client.post("/webhooks/elevenlabs", json={"type": "post_call_transcription"})
    assert response.status_code == 401
