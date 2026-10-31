"""Declarative, secret-free configuration for the nous ElevenLabs agent."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


API_URL = "https://api.elevenlabs.io/v1"
DEFAULT_BASE_URL = "https://htsaustin--nous-web.us-east.modal.run"
VOICE_SPEED = 1.2


@dataclass(frozen=True)
class ToolSpec:
    name: str
    path: str
    description: str
    properties: dict[str, str]
    required: tuple[str, ...]
    dynamic_fields: dict[str, str]


TOOLS = (
    ToolSpec("nous_get_case", "/elevenlabs/tools/get-case", "Read the current administrative case after identity has been verified.", {"goal_id": "The current case identifier."}, ("goal_id",), {"goal_id": "goal_id"}),
    ToolSpec("nous_verify_identity", "/elevenlabs/tools/verify-identity", "Verify the caller's stated date of birth. The response reveals only whether it matches.", {"goal_id": "The current case identifier.", "date_of_birth": "The date of birth stated by the caller, formatted YYYY-MM-DD."}, ("goal_id", "date_of_birth"), {"goal_id": "goal_id"}),
    ToolSpec("nous_list_offered_slots", "/elevenlabs/tools/list-offered-slots", "Read only this patient's currently offered appointment and current booking. Never use it to search general capacity.", {"goal_id": "The current case identifier."}, ("goal_id",), {"goal_id": "goal_id"}),
    ToolSpec("nous_list_reschedule_slots", "/elevenlabs/tools/list-reschedule-slots", "Find compatible available replacement appointments when the patient explicitly asks to change their current booking.", {"goal_id": "The current case identifier."}, ("goal_id",), {"goal_id": "goal_id"}),
    ToolSpec("nous_accept_slot", "/elevenlabs/tools/accept-slot", "Accept and book the exact offered or replacement slot only after the patient clearly agrees.", {"goal_id": "The current case identifier.", "slot_id": "The slot_id returned by the offered-slot or reschedule-slot tool for the appointment the patient accepted."}, ("goal_id", "slot_id"), {"goal_id": "goal_id"}),
    ToolSpec("nous_reject_slot", "/elevenlabs/tools/reject-slot", "Record that the patient declined an offered slot.", {"goal_id": "The current case identifier.", "slot_id": "The declined offered slot identifier.", "reason": "A brief administrative reason, if given."}, ("goal_id", "slot_id"), {"goal_id": "goal_id", "slot_id": "proposed_slot_id"}),
    ToolSpec("nous_patient_constraint", "/elevenlabs/tools/patient-constraint", "Record an availability, site, language, contact, communication, or accessibility preference.", {"goal_id": "The current case identifier.", "constraint": "The patient's administrative constraint or preference."}, ("goal_id", "constraint"), {"goal_id": "goal_id"}),
    ToolSpec("nous_request_human", "/elevenlabs/tools/request-human", "Escalate clinical questions, failed identity checks, safeguarding concerns, or requests outside scheduling.", {"goal_id": "The current case identifier.", "constraint": "A concise reason a human must take over."}, ("goal_id", "constraint"), {"goal_id": "goal_id"}),
)

FIRST_MESSAGES = {
    "en": "Hello {{patient_first_name}}, this is nous calling about an appointment. Is now an okay time to speak?",
    "es": "Hola {{patient_first_name}}, soy nous y llamo por una cita. ¿Es un buen momento para hablar?",
    "pl": "Dzień dobry {{patient_first_name}}, tu nous w sprawie wizyty. Czy możemy teraz porozmawiać?",
    "tr": "Merhaba {{patient_first_name}}, ben nous. Bir randevu hakkında arıyorum. Konuşmak için uygun musunuz?",
    "ar": "مرحبًا {{patient_first_name}}، معك nous بخصوص موعد. هل الوقت مناسب للتحدث؟",
    "ro": "Bună {{patient_first_name}}, sunt nous și vă sun în legătură cu o programare. Este un moment potrivit să vorbim?",
    "zh": "您好 {{patient_first_name}}，我是 nous，来电是关于一个预约。现在方便说话吗？",
    "ur": "السلام علیکم {{patient_first_name}}، میں nous سے ایک اپائنٹمنٹ کے بارے میں بات کر رہا ہوں۔ کیا ابھی بات کرنا مناسب ہے؟",
    "uk": "Вітаю, {{patient_first_name}}, це nous щодо запису на прийом. Вам зараз зручно говорити?",
    "pt": "Olá {{patient_first_name}}, sou da nous e estou ligando sobre uma consulta. É um bom momento para falar?",
    "gu": "નમસ્તે {{patient_first_name}}, હું nous તરફથી એપોઇન્ટમેન્ટ વિશે ફોન કરું છું. શું અત્યારે વાત કરવાનો યોગ્ય સમય છે?",
    "cs": "Dobrý den, {{patient_first_name}}, volám z nous ohledně termínu. Hodí se vám teď mluvit?",
    "hi": "नमस्ते {{patient_first_name}}, मैं nous से अपॉइंटमेंट के बारे में बात कर रहा हूँ। क्या अभी बात करने का सही समय है?",
}

SYSTEM_PROMPT = """You are nous, an administrative scheduling caseworker supporting patient pathways.

Your goal is to help the named patient progress from referral to a completed appointment. Clearly identify that you are calling about an appointment. Be calm, concise and respectful. You may discuss appointment dates, times, locations, attendance, contact preferences and administrative constraints only.

Before disclosing case-specific information, ask the caller to state their date of birth and call `nous_verify_identity`. Never say or hint at the date of birth held on file. Continue only when the tool returns `verified: true`. If it returns false, allow one careful retry; after a second failure call `nous_request_human` and do not disclose case details.

Once identity is verified, ask whether the patient has a preferred language or any hearing, communication, or accessibility needs. Use `nous_patient_constraint` to record every preference. If they ask for another supported language, use the language detection tool. For hearing difficulty, speak slowly, use short sentences, confirm understanding, and offer repetition. If communication or consent is unsafe or uncertain, call `nous_request_human`.

Never give medical advice, interpret symptoms, change clinical priority, discuss medication, or invent patient or clinical information. If the caller raises anything requiring clinical judgement, call `nous_request_human`, explain that a member of the care team must help, and do not continue the clinical topic.

Use `nous_get_case` only after successful identity verification. Use `nous_list_offered_slots` before offering an appointment. Never claim a slot is booked until `nous_accept_slot` succeeds. If the patient declines, call `nous_reject_slot` and capture a short administrative reason. Confirm the agreed date, time and site once. End the call when the administrative task is complete.

The purpose of this call is {{purpose}}. Your exact administrative assignment is: {{reason}}

Follow the purpose strictly:
- For REMINDER, confirm only that the patient's existing booked appointment remains suitable. After identity verification, read the current booking with `nous_get_case`, state its date, time and site, and ask whether they still expect to attend. If they explicitly ask to change it, call `nous_list_reschedule_slots`, offer only a returned compatible replacement, and call `nous_accept_slot` exactly once after clear agreement.
- For EARLIER_SLOT_OFFER, discuss only the proposed offered slot. Call `nous_list_offered_slots`, describe the offered date, time and site, and call `nous_accept_slot` exactly once only after clear acceptance. A successful response means it is booked; do not call the list or accept tools again.
- For RESCHEDULE, call `nous_list_reschedule_slots`, offer a compatible returned replacement, and keep the current booking until `nous_accept_slot` succeeds.
- For FOLLOW_UP, perform only the stated assignment.

The current case identifier is {{goal_id}} and the proposed slot identifier is {{proposed_slot_id}}. Use them only through tool calls. Never read, ask for, repeat, or expose internal identifiers."""


def tool_config(spec: ToolSpec, base_url: str) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    for key, description in spec.properties.items():
        item: dict[str, Any] = {"type": "string"}
        if key in spec.dynamic_fields:
            item["dynamic_variable"] = spec.dynamic_fields[key]
        else:
            item["description"] = description
        properties[key] = item
    return {
        "type": "webhook",
        "name": spec.name,
        "description": spec.description,
        "response_timeout_secs": 10,
        "api_schema": {
            "url": base_url.rstrip("/") + spec.path,
            "method": "POST",
            "path_params_schema": {},
            "query_params_schema": None,
            "request_body_schema": {"type": "object", "description": spec.description, "required": list(spec.required), "properties": properties},
            "request_headers": {},
        },
        "dynamic_variables": {"dynamic_variable_placeholders": {name: "" for name in set(spec.dynamic_fields.values())}},
    }


def configure(client: httpx.Client, *, agent_id: str, base_url: str = DEFAULT_BASE_URL) -> dict[str, Any]:
    tools_response = client.get(f"{API_URL}/convai/tools", params={"page_size": 100})
    _raise_api_error(tools_response, "list tools")
    existing = {(item.get("tool_config") or {}).get("name"): item for item in tools_response.json().get("tools", [])}
    tool_ids: list[str] = []
    created: list[str] = []
    updated: list[str] = []
    for spec in TOOLS:
        payload = {"tool_config": tool_config(spec, base_url)}
        current = existing.get(spec.name)
        if current:
            response = client.patch(f"{API_URL}/convai/tools/{current['id']}", json=payload)
            updated.append(spec.name)
        else:
            response = client.post(f"{API_URL}/convai/tools", json=payload)
            created.append(spec.name)
        _raise_api_error(response, f"configure {spec.name}")
        tool_ids.append(response.json()["id"])

    detail = client.get(f"{API_URL}/convai/agents/{agent_id}")
    _raise_api_error(detail, "get agent")
    agent = detail.json()
    prompt_config = agent["conversation_config"]["agent"].get("prompt") or {}
    prompt_config = {key: value for key, value in prompt_config.items() if key not in {"tools", "tool_ids"}}
    built_in_tools = dict(prompt_config.get("built_in_tools") or {})
    built_in_tools["language_detection"] = {
        "type": "system",
        "name": "language_detection",
        "description": "Switch to a supported language when the patient requests it or clearly speaks another supported language.",
        "params": {"system_tool_type": "language_detection"},
    }
    overrides = ((agent.get("platform_settings") or {}).get("overrides") or {}).get("conversation_config_override") or {}
    auth = dict((agent.get("platform_settings") or {}).get("auth") or {})
    auth["enable_auth"] = True
    override_agent = dict(overrides.get("agent") or {})
    override_agent["language"] = True
    overrides = {**overrides, "agent": override_agent}
    language_presets = {code: {"overrides": {"agent": {"first_message": message}}} for code, message in FIRST_MESSAGES.items() if code != "en"}
    update = {
        "conversation_config": {
            "tts": {**(agent.get("conversation_config", {}).get("tts") or {}), "speed": VOICE_SPEED},
            "language_presets": language_presets,
            "agent": {
                "first_message": FIRST_MESSAGES["en"],
                "dynamic_variables": {"dynamic_variable_placeholders": {"patient_first_name": "", "goal_id": "", "reason": "", "purpose": "", "preferred_language": "en", "proposed_slot_id": ""}},
                "prompt": {**prompt_config, "prompt": SYSTEM_PROMPT, "tool_ids": tool_ids, "built_in_tools": built_in_tools},
            },
        },
        "platform_settings": {
            "auth": auth,
            "overrides": {"conversation_config_override": overrides},
        },
        "version_description": "Purpose-specific calls, idempotent acceptance and brisker voice",
    }
    patched = client.patch(f"{API_URL}/convai/agents/{agent_id}", json=update)
    _raise_api_error(patched, "update agent")
    result = patched.json()
    return {"agent_id": agent_id, "agent_name": result.get("name"), "version_id": result.get("version_id"), "created_tools": created, "updated_tools": updated, "attached_tools": [spec.name for spec in TOOLS], "browser_authentication_enabled": True, "language_override_enabled": True, "language_presets": sorted(language_presets), "voice_speed": VOICE_SPEED}


def verify(client: httpx.Client, *, agent_id: str) -> dict[str, Any]:
    response = client.get(f"{API_URL}/convai/agents/{agent_id}")
    _raise_api_error(response, "verify agent")
    agent = response.json()
    conversation = agent.get("conversation_config") or {}
    prompt = (conversation.get("agent") or {}).get("prompt") or {}
    overrides = (((agent.get("platform_settings") or {}).get("overrides") or {}).get("conversation_config_override") or {}).get("agent") or {}
    tools_response = client.get(f"{API_URL}/convai/tools", params={"used_by_agent_id": agent_id, "page_size": 100})
    _raise_api_error(tools_response, "verify attached tools")
    attached = sorted((item.get("tool_config") or {}).get("name") for item in tools_response.json().get("tools", []) if (item.get("tool_config") or {}).get("name", "").startswith("nous_"))
    return {"agent_id": agent.get("agent_id"), "agent_name": agent.get("name"), "version_id": agent.get("version_id"), "attached_tools": attached, "browser_authentication_enabled": ((agent.get("platform_settings") or {}).get("auth") or {}).get("enable_auth") is True, "identity_prompt_enabled": "nous_verify_identity" in prompt.get("prompt", ""), "accessibility_prompt_enabled": "accessibility" in prompt.get("prompt", "").lower(), "language_detection_enabled": bool((prompt.get("built_in_tools") or {}).get("language_detection")), "language_override_enabled": overrides.get("language") is True, "language_presets": sorted((conversation.get("language_presets") or {}).keys()), "voice_speed": (conversation.get("tts") or {}).get("speed")}
def _raise_api_error(response: httpx.Response, operation: str) -> None:
    if not response.is_success:
        raise RuntimeError(f"{operation} failed with HTTP {response.status_code}: {response.text[:2000]}")
