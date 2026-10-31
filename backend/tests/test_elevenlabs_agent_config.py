from scripts.elevenlabs_agent_config import FIRST_MESSAGES, SYSTEM_PROMPT, TOOLS, VOICE_SPEED, tool_config


def test_configuration_declares_all_privacy_safe_appointment_tools():
    names = {tool.name for tool in TOOLS}
    assert names == {"nous_get_case", "nous_verify_identity", "nous_list_offered_slots", "nous_list_reschedule_slots", "nous_accept_slot", "nous_reject_slot", "nous_patient_constraint", "nous_request_human"}
    verify = next(tool for tool in TOOLS if tool.name == "nous_verify_identity")
    assert verify.path == "/elevenlabs/tools/verify-identity"
    assert verify.required == ("goal_id", "date_of_birth")


def test_internal_identifiers_are_bound_to_dynamic_variables():
    for spec in TOOLS:
        config = tool_config(spec, "https://demo.example")
        properties = config["api_schema"]["request_body_schema"]["properties"]
        assert properties["goal_id"]["dynamic_variable"] == "goal_id"
        if spec.name == "nous_reject_slot":
            assert properties["slot_id"]["dynamic_variable"] == "proposed_slot_id"
        if spec.name == "nous_accept_slot":
            assert "dynamic_variable" not in properties["slot_id"]
        assert config["api_schema"]["url"].startswith("https://demo.example/elevenlabs/tools/")


def test_prompt_orders_identity_and_accessibility_before_case_details():
    assert SYSTEM_PROMPT.index("nous_verify_identity") < SYSTEM_PROMPT.index("nous_get_case")
    assert "Never say or hint at the date of birth held on file" in SYSTEM_PROMPT
    assert "hearing, communication, or accessibility needs" in SYSTEM_PROMPT
    assert "Never read, ask for, repeat, or expose internal identifiers" in SYSTEM_PROMPT
    assert "The purpose of this call is {{purpose}}" in SYSTEM_PROMPT
    assert "For REMINDER, confirm only" in SYSTEM_PROMPT
    assert "call `nous_accept_slot` exactly once" in SYSTEM_PROMPT


def test_language_presets_cover_runtime_language_codes():
    assert {"en", "es", "pl", "tr", "ar", "ro", "zh", "ur", "uk", "pt", "gu", "cs", "hi"} == set(FIRST_MESSAGES)
    assert VOICE_SPEED == 1.2
