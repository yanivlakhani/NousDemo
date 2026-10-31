from evals.simulate_pathway import run_all, run_scenario


def test_phone_less_acceptance_path_runs_to_completion_without_network():
    report = run_scenario("accept")

    assert report["passed"] is True
    assert report["label"] == "SYNTHETIC / NO NETWORK / NO PRODUCTION DB"
    assert report["goal"]["status"] == "COMPLETED"
    assert report["checks"]["patient_has_no_phone"] is True
    assert report["checks"]["network_calls"] == 0
    assert report["checks"]["transcript_stored_once"] is True
    assert report["checks"]["transcript_note_stored_once"] is True
    assert report["checks"]["case_document_versioned"] is True
    assert len(report["agent_steps"]) == 4


def test_phone_less_decline_path_remains_durably_waiting():
    report = run_scenario("decline")

    assert report["passed"] is True
    assert report["goal"]["status"] == "WAITING"
    assert any(row["type"] == "SLOT_REJECTED" for row in report["timeline"])


def test_phone_less_clinical_question_escalates_to_human():
    report = run_scenario("escalate")

    assert report["passed"] is True
    assert report["goal"]["status"] == "HUMAN_REVIEW_REQUIRED"
    assert any(row["type"] == "HUMAN_REVIEW_REQUESTED" for row in report["timeline"])


def test_all_replay_report_is_machine_readable_and_green():
    report = run_all()

    assert report["passed"] is True
    assert [item["scenario"] for item in report["reports"]] == ["accept", "decline", "escalate"]
