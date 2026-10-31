from types import SimpleNamespace
from uuid import uuid4

from app.models import Communication, Event
from app.simulated_voice import complete_simulated_action


class RecordingSession:
    def __init__(self):
        self.added = []

    def add_all(self, values):
        self.added.extend(values)


def test_simulated_action_completes_with_typed_honest_records():
    action = SimpleNamespace(
        id=uuid4(), goal_id=uuid4(), action_type="CALL_PATIENT", status="QUEUED",
        payload={"purpose": "REMINDER", "reason": "Confirm attendance", "preferred_language": "Hindi", "simulated_outcome": "NO_ANSWER"},
        result=None, completed_at=None,
    )
    session = RecordingSession()

    result = complete_simulated_action(session, action)

    communication = next(item for item in session.added if isinstance(item, Communication))
    event = next(item for item in session.added if isinstance(item, Event))
    assert action.status == "COMPLETED"
    assert action.result == result
    assert result == {"provider": "simulated", "transport": "none", "simulated": True, "status": "completed", "outcome": "NO_ANSWER", "conversation_id": f"simulated-{action.id}"}
    assert communication.channel == "SIMULATED_VOICE"
    assert communication.outcome == "NO_ANSWER"
    assert communication.summary.startswith("[SIMULATED — no telephone call placed]")
    assert event.event_type == "VOICE_CALL_SIMULATED"
    assert event.payload["simulated"] is True
    assert event.payload["transport"] == "none"
