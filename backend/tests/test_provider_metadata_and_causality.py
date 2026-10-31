import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import httpx
from fastapi.testclient import TestClient

from app.elevenlabs_metadata import _cache, fetch_elevenlabs_metadata
from app.main import ReferralCreate, SlotCreate, agent_step_json, app, case_note_json, overseer_decision_json, tool_call_json
from app.models import AgentStep, AppointmentType, CaseNote, Referral, Slot


client = TestClient(app)


def test_elevenlabs_metadata_is_sanitized_and_reports_runtime_assignments():
    _cache.clear()

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "/convai/agents/" in path:
            return httpx.Response(200, json={"agent_id": "agent_1", "name": "Nous", "version_id": "v3", "branch_id": "main", "conversation_config": {"agent": {"prompt": {"prompt": "PRIVATE PROMPT", "tool_ids": ["tool_a"], "tools": [{"tool_id": "tool_b", "name": "accept_slot", "type": "webhook"}]}}}})
        if path.endswith("/convai/settings"):
            return httpx.Response(200, json={"webhooks": {"post_call_webhook_id": "webhook_1", "events": ["transcript"]}})
        if path.endswith("/workspace/webhooks"):
            return httpx.Response(200, json={"webhooks": [{"webhook_id": "webhook_1", "auth_type": "hmac", "is_disabled": False, "is_auto_disabled": False, "retry_enabled": True}]})
        if path.endswith("/convai/tools/tool_a"):
            return httpx.Response(200, json={"tool_id": "tool_a", "tool_config": {"type": "webhook", "name": "get_case"}})
        return httpx.Response(200, json={"phone_number_id": "phone_1", "phone_number": "+447700900123", "label": "Nous", "provider": "twilio", "assigned_agent": {"agent_id": "agent_1", "branch_id": "main"}})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await fetch_elevenlabs_metadata("super-secret-key", "agent_1", "phone_1", client=http)

    result = asyncio.run(run())
    serialized = json.dumps(result)
    assert "super-secret-key" not in serialized
    assert "PRIVATE PROMPT" not in serialized
    assert result["agent"]["version_id"] == "v3"
    assert {tool["id"] for tool in result["agent"]["attached_tools"]} == {"tool_a", "tool_b"}
    assert {tool["name"] for tool in result["agent"]["attached_tools"]} == {"get_case", "accept_slot"}
    assert result["phone_assignment"]["assigned"] is True
    assert result["phone_assignment"]["phones"][0]["number"] == "••••0123"
    assert result["webhook"]["active"] is True


def test_trace_json_exposes_long_horizon_causality():
    now, parent_id, spec_id = datetime.now(UTC), uuid4(), uuid4()
    step = SimpleNamespace(id=uuid4(), goal_id=uuid4(), agent_spec_version_id=spec_id, parent_step_id=parent_id, sequence=4, retry_attempt=1, wake_reason="VOICE_CALL_COMPLETED", scheduled_next_wake=now, outcome="COMPLETED", tool_call_count=2, decision="Follow up", error=None, stop_reason="tool_use", mode="ANTHROPIC", model="claude-haiku-5-5", fallback=False, context={"agent_spec": {"version": 2}}, input_tokens=10, output_tokens=5, created_at=now)
    row = agent_step_json(step, [{"tool_name": "read_case_notes"}])
    assert row["parent_step_id"] == str(parent_id)
    assert row["agent_spec_version_id"] == str(spec_id)
    assert row["agent_version"] == 2
    assert row["model"] == "claude-haiku-5-5"
    assert (row["sequence"], row["retry_attempt"], row["tool_call_count"]) == (4, 1, 2)
    assert row["scheduled_next_wake"] == now.isoformat()


def test_trace_json_exposes_recorded_run_and_tool_timings():
    started, completed = datetime.now(UTC), datetime.now(UTC)
    step = SimpleNamespace(id=uuid4(), goal_id=uuid4(), agent_spec_version_id=None, parent_step_id=None, sequence=1, retry_attempt=0, wake_reason="INITIAL_GOAL", scheduled_next_wake=None, outcome="COMPLETED", tool_call_count=1, decision="Done", error=None, stop_reason="end_turn", mode="ANTHROPIC", model="model", fallback=False, context={}, input_tokens=1, output_tokens=1, created_at=started, completed_at=completed, duration_ms=17)
    call = SimpleNamespace(id=uuid4(), sequence=1, tool_name="read_case", tool_input={}, result_text="ok", status="OK", started_at=started, completed_at=completed, duration_ms=4)

    row = agent_step_json(step, [tool_call_json(call)])

    assert row["completed_at"] == completed.isoformat()
    assert row["duration_ms"] == 17
    assert row["tool_calls"][0]["started_at"] == started.isoformat()
    assert row["tool_calls"][0]["completed_at"] == completed.isoformat()
    assert row["tool_calls"][0]["duration_ms"] == 4


def test_overseer_decision_uses_common_run_contract_without_inventing_timings():
    now = datetime.now(UTC)
    decision = SimpleNamespace(id=uuid4(), goal_id=uuid4(), proposed_action={"action": "OFFER_SLOT", "slot_id": "slot-1"}, reasoning_summary="Offer the released slot to the highest-ranked eligible patient.", observation={"ranked_choices": ["patient-1"]}, created_at=now)

    row = overseer_decision_json(decision)

    assert row["kind"] == "AGENT_STEP"
    assert row["agent_role"] == "OVERSEER"
    assert row["mode"] == "DETERMINISTIC_POLICY"
    assert row["context"]["agent_spec"] == {"role": "OVERSEER", "version": 1}
    assert row["completed_at"] is None and row["duration_ms"] is None
    assert row["tool_calls"][0]["tool_name"] == "rank_released_slot"
    assert row["tool_calls"][0]["started_at"] is None


def test_history_and_provider_endpoints_are_explicit_in_openapi():
    paths = client.get("/openapi.json").json()["paths"]
    assert "get" in paths["/api/integrations/elevenlabs"]
    assert "get" in paths["/api/goals/{goal_id}/agent-history"]
    assert "get" in paths["/api/patients/{goal_id}/agent-history"]
    assert "get" in paths["/api/appointment-types"]


def test_appointment_type_contract_is_backward_compatible():
    assert ReferralCreate(external_ref="R1", first_name="A", last_name="B", date_of_birth="1980-01-02", phone="+447700900001", pathway_type="MRI", procedure="MRI", provider_org="Provider").procedure == "MRI"
    assert SlotCreate(provider_org="Provider", site="North", procedure="MRI", starts_at=datetime.now(UTC)).duration_minutes is None
    assert "appointment_type_id" in Referral.__table__.c
    assert "appointment_type_id" in Slot.__table__.c
    assert {"code", "name", "default_duration_minutes", "preparation_note", "is_active"} <= set(AppointmentType.__table__.c.keys())


def test_case_note_schema_requires_language():
    assert "language" in CaseNote.__table__.c
    assert CaseNote.__table__.c.language.nullable is False


def test_case_note_api_contract_includes_language():
    now = datetime.now(UTC)
    note = SimpleNamespace(id=uuid4(), category="PREFERENCE", text="Interpreter requested.", language="Polish", source="OPERATOR", created_at=now)
    assert case_note_json(note)["language"] == "Polish"


def test_agent_step_schema_contains_causal_columns():
    expected = {"parent_step_id", "sequence", "retry_attempt", "wake_reason", "scheduled_next_wake", "outcome", "tool_call_count"}
    assert expected <= set(AgentStep.__table__.c.keys())
