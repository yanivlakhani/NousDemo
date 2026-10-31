from __future__ import annotations

from datetime import UTC, datetime

from app.models import Communication, Event
from app.records import CALL_OUTCOMES, language_code


DEFAULT_SIMULATED_OUTCOME = "ANSWERED"


def simulated_result(*, action_id, outcome: str | None = None) -> dict:
    """Return honest, deterministic demo transport metadata; no call is placed."""
    selected = (outcome or DEFAULT_SIMULATED_OUTCOME).upper()
    if selected not in CALL_OUTCOMES or selected == "QUEUED":
        selected = DEFAULT_SIMULATED_OUTCOME
    return {
        "provider": "simulated",
        "transport": "none",
        "simulated": True,
        "status": "completed",
        "outcome": selected,
        "conversation_id": f"simulated-{action_id}",
    }


def complete_simulated_action(session, action) -> dict:
    payload = action.payload or {}
    purpose = payload.get("purpose") or (
        "EARLIER_SLOT_OFFER" if action.action_type == "EARLIER_SLOT_OFFER" else "FOLLOW_UP"
    )
    result = simulated_result(action_id=action.id, outcome=payload.get("simulated_outcome"))
    code = language_code(payload.get("preferred_language"))
    summary = payload.get("simulated_summary") or payload.get("reason") or "Simulated caseworker call completed"
    metadata = {
        "simulated": True,
        "provider": "simulated",
        "transport": "none",
        "conversation_id": result["conversation_id"],
        "purpose": purpose,
        "outcome": result["outcome"],
        "language": code,
    }
    action.status = "COMPLETED"
    action.result = result
    action.completed_at = datetime.now(UTC)
    session.add_all(
        [
            Communication(
                goal_id=action.goal_id,
                channel="SIMULATED_VOICE",
                direction="OUTBOUND",
                external_id=result["conversation_id"],
                purpose=purpose,
                outcome=result["outcome"],
                language=code,
                summary=f"[SIMULATED — no telephone call placed] {summary}",
                transcript=payload.get("simulated_transcript"),
            ),
            Event(
                goal_id=action.goal_id,
                event_type="VOICE_CALL_SIMULATED",
                source="simulated_voice",
                payload=metadata,
                idempotency_key=f"simulated-call:{action.id}",
            ),
        ]
    )
    return result
