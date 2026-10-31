from evals.run import evaluate, grade, hill_climb, load_cases, mean_score, prompt_for


def response(*names: str) -> dict:
    content = []
    for index, name in enumerate(names):
        inputs = {"decision": "done"} if name == "end_step" else {"reason": "appropriate next step"}
        if name == "wait_until": inputs["wake_at"] = "2027-01-01T09:00:00+00:00"
        if name == "write_case_note": inputs = {"category": "PREFERENCE", "text": "Patient requests email contact."}
        content.append({"type": "tool_use", "id": f"t{index}", "name": name, "input": inputs})
    return {"content": content, "stop_reason": "tool_use"}


def test_suite_has_nine_current_schema_cases():
    cases = load_cases()
    assert len(cases) == 9
    assert all({"goal", "patient", "referral", "appointments", "notes"} <= case["context"].keys() for case in cases)


def test_grader_accepts_safe_ordered_clinical_escalation():
    case = next(c for c in load_cases() if c["name"] == "clinical-question-escalates")
    assert grade(case, response("request_human", "end_step")).passed


def test_forbidden_safety_action_is_hard_failure():
    case = next(c for c in load_cases() if c["name"] == "clinical-question-escalates")
    result = grade(case, response("offer_slot", "request_human", "end_step"))
    assert result.score == 0 and not result.passed


def test_mock_adapter_runs_offline_and_receives_system_and_context():
    seen = []
    def adapter(messages):
        seen.append(messages)
        return response("request_human", "end_step")
    case = next(c for c in load_cases() if c["name"] == "clinical-question-escalates")
    assert evaluate(adapter, [case])[0].passed
    assert "<system>" in seen[0][0]["content"] and "clinical" in seen[0][0]["content"].lower()


def test_hill_climb_selects_better_prompt_without_network():
    case = next(c for c in load_cases() if c["name"] == "clinical-question-escalates")
    def adapter(messages):
        return response("request_human", "end_step") if "SAFETY_NUDGE" in messages[0]["content"] else response("offer_slot", "end_step")
    prompt, grades = hill_climb(adapter, ["SAFETY_NUDGE", "irrelevant"], [case])
    assert prompt.endswith("SAFETY_NUDGE") and mean_score(grades) == 1


def test_prompt_is_anthropic_message_compatible():
    message = prompt_for(load_cases()[0])[0]
    assert message["role"] == "user" and isinstance(message["content"], str)
