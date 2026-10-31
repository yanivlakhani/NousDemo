from __future__ import annotations

from datetime import UTC, datetime

import httpx
from sqlalchemy import select

from app.database import session_scope
from app.models import Action, Communication, Event
from app.records import elevenlabs_call_payload, language_code
from app.settings import settings
from app.simulated_voice import complete_simulated_action


def dispatch_queued_calls(limit: int = 20) -> dict:
    if not settings.use_fake_voice and (not all((settings.elevenlabs_api_key, settings.elevenlabs_agent_id, settings.elevenlabs_phone_number_id)) or str(settings.elevenlabs_agent_id).startswith("PLACEHOLDER")):
        return {"configured": False, "dispatched": 0}
    dispatched = []
    with session_scope() as session:
        actions = session.scalars(select(Action).where(Action.action_type.in_(["CALL_PATIENT", "EARLIER_SLOT_OFFER"]), Action.status == "QUEUED").order_by(Action.created_at).with_for_update(skip_locked=True).limit(limit)).all()
        for action in actions:
            # Browser-receiver calls are claimed by the intended patient's open
            # demo phone. The telephone simulator must never consume them first.
            if (action.payload or {}).get("transport") == "demo_browser_receiver":
                continue
            action.status = "EXECUTING"
            payload = action.payload
            try:
                if settings.use_fake_voice:
                    complete_simulated_action(session, action)
                    dispatched.append(str(action.id))
                    continue
                purpose = payload.get("purpose") or ("EARLIER_SLOT_OFFER" if action.action_type == "EARLIER_SLOT_OFFER" else "FOLLOW_UP")
                call_payload = elevenlabs_call_payload(agent_id=settings.elevenlabs_agent_id, phone_number_id=settings.elevenlabs_phone_number_id, to_number=payload["phone_number"], patient_first_name=payload["patient_first_name"], goal_id=action.goal_id, reason=payload["reason"], purpose=purpose, preferred_language=payload.get("preferred_language", "English"), proposed_slot_id=payload.get("proposed_slot_id"))
                response = httpx.post("https://api.elevenlabs.io/v1/convai/twilio/outbound-call", headers={"xi-api-key": settings.elevenlabs_api_key}, json=call_payload, timeout=20)
                response.raise_for_status(); result = response.json(); external_id = result.get("conversation_id") or f"pending-{action.id}"
                action.status, action.result, action.completed_at = "COMPLETED", result, datetime.now(UTC)
                code = language_code(payload.get("preferred_language"))
                session.add_all([Communication(goal_id=action.goal_id, channel="VOICE", direction="OUTBOUND", external_id=external_id, purpose=purpose, outcome="QUEUED", language=code, summary=payload["reason"]), Event(goal_id=action.goal_id, event_type="VOICE_CALL_REQUESTED", source="call_dispatcher", payload={"conversation_id": external_id, "purpose": purpose, "outcome": "QUEUED", "language": code}, idempotency_key=f"dispatch:{action.id}")])
                dispatched.append(str(action.id))
            except Exception as exc:
                action.status = "FAILED"; action.result = {"error": str(exc)[:500]}; action.completed_at = datetime.now(UTC)
                session.add(Communication(goal_id=action.goal_id, channel="VOICE", direction="OUTBOUND", external_id=f"failed-{action.id}", purpose=payload.get("purpose", "FOLLOW_UP"), outcome="FAILED", language=language_code(payload.get("preferred_language")), summary=str(exc)[:500]))
    return {"configured": True, "provider": "simulated" if settings.use_fake_voice else "elevenlabs", "dispatched": len(dispatched), "action_ids": dispatched}
