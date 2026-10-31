from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from app import agents
from app.main import app
from app.models import Action, AgentDefinition, AgentSpecVersion, AgentStep, CaseDocument, CaseDocumentVersion, Event


client = TestClient(app)


def test_versioned_agent_and_case_document_routes_are_exposed():
    paths = client.get("/openapi.json").json()["paths"]
    assert "get" in paths["/api/agent-definitions"]
    assert "post" in paths["/api/agent-definitions/{key}/versions"]
    assert "post" in paths["/api/agent-definitions/{key}/versions/{version_number}/activate"]
    assert set(paths["/api/goals/{goal_id}/documents"]) == {"get", "post"}


def test_agent_steps_have_exact_spec_version_foreign_key():
    column = AgentStep.__table__.c.agent_spec_version_id
    target = next(iter(column.foreign_keys)).target_fullname
    assert target == "agent_spec_versions.id"


def test_documents_separate_stable_identity_from_immutable_versions():
    assert {"goal_id", "document_type", "title", "current_version_id"} <= set(CaseDocument.__table__.c.keys())
    assert {"document_id", "content", "version", "supersedes_id", "metadata", "created_by"} <= set(CaseDocumentVersion.__table__.c.keys())
    assert any(constraint.name == "uq_case_document_version" for constraint in CaseDocumentVersion.__table__.constraints)


def test_agent_tool_policy_limits_model_tool_surface():
    version = SimpleNamespace(tool_policy={"allowed": ["read_case_notes", "end_step"]})
    assert [tool["name"] for tool in agents.tools_for_spec(version)] == ["read_case_notes", "end_step"]


def test_caseworker_and_operator_share_three_named_markdown_files():
    assert agents.CASE_FILES == {
        "OVERVIEW": "overview.md",
        "PREFERENCES": "preferences.md",
        "CALL_NOTES": "call-notes.md",
    }
    writer = next(tool for tool in agents.TOOLS if tool["name"] == "write_case_document")
    assert writer["input_schema"]["properties"]["title"]["enum"] == list(agents.CASE_FILES.values())


def test_agent_definitions_have_stable_active_version_pointer():
    assert AgentDefinition.__table__.c.active_version_id.nullable
    assert any(constraint.name == "uq_agent_spec_definition_version" for constraint in AgentSpecVersion.__table__.constraints)


def test_call_queue_replay_does_not_create_duplicate_rows():
    existing_action = SimpleNamespace(idempotency_key="existing")
    existing_event = SimpleNamespace(idempotency_key="existing")

    class Session:
        def __init__(self):
            self.values = iter([existing_action, existing_event])
            self.added = []

        def scalar(self, _query):
            return next(self.values)

        def add(self, value):
            self.added.append(value)

    patient = SimpleNamespace(id=uuid4(), first_name="Amira", phone="+447700900142")
    referral = SimpleNamespace(id=uuid4(), patient=patient)
    goal = SimpleNamespace(id=uuid4(), version=4, referral=referral, status="ACTIVE", next_wake_at=None)
    session = Session()

    result, status, _, _ = agents.dispatch(session, goal, "queue_patient_call", {"reason": "Confirm availability"})

    assert (result, status) == ("Patient call queued.", "OK")
    assert not any(isinstance(row, (Action, Event)) for row in session.added)
