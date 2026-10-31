import json

from app.agents import DECISION_OUTPUT_CONTRACT, TOOLS, decision_json


def test_end_step_declares_structured_operator_output():
    end_step = next(tool for tool in TOOLS if tool["name"] == "end_step")
    schema = end_step["input_schema"]
    assert schema["required"] == [
        "title", "trigger", "reason", "candidate_slots", "actions_taken",
        "booking_released", "outcome", "next_action",
    ]
    assert "Do not include Markdown" in DECISION_OUTPUT_CONTRACT


def test_structured_decision_is_compact_json():
    encoded = decision_json({
        "title": "Appointment offer needs review",
        "trigger": "A slot became available",
        "reason": "An appointment offer is already open.",
        "candidate_slots": [{"starts_at": "2026-10-16T13:00:00Z", "site": "Main site"}],
        "actions_taken": ["Appointment note recorded", "Human review requested"],
        "booking_released": False,
        "outcome": "No new offer created",
        "next_action": "Review the existing offer.",
    })
    value = json.loads(encoded)
    assert value["title"] == "Appointment offer needs review"
    assert value["booking_released"] is False
    assert value["candidate_slots"][0]["site"] == "Main site"
    assert len(encoded) <= 500


def test_legacy_decision_string_remains_supported():
    assert decision_json({"decision": "Waiting for patient reply"}) == "Waiting for patient reply"
