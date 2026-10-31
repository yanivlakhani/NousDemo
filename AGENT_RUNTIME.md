# nous agent runtime

Each referral owns a durable `Goal`; that record, not an in-memory conversation, is the long-horizon caseworker identity. Modal wakes due goals every five minutes. One invocation loads compact state, asks Anthropic for one structured administrative decision, validates the action in Python, stores a `GoalDecision`, `Action`, and `Event`, updates `next_wake_at`, and exits.

The capacity overseer runs separately. Deterministic code filters procedure, availability, current case state, and locks slots before creating offers. Caseworkers are then woken to contact patients. Neither model can directly update the database or book an arbitrary slot.

## Tools and effects

- Read case and event history.
- Read eligible slots and existing bookings.
- Queue a patient call through the ElevenLabs adapter.
- Record an administrative constraint or case note.
- Offer, accept, or reject a guarded slot.
- Request human review.
- Wait until a durable future wake time.

## Evaluation loop

`backend/evals/run.py` calls the same Anthropic decision path used in production. Cases are redacted JSON fixtures with allowed actions. Add regressions from real traces only after redaction. Compare prompt/model variants on action correctness, policy violations, tool validity, schema failures, latency, and cost; never promote a variant solely on average score when it introduces a safety regression.

Run with:

```bash
cd backend
ANTHROPIC_API_KEY=... uv run python -m evals.run
```

The next tracing increment should persist model request metadata, prompt/model version, token usage, latency, tool calls, and dry-run effects so historical decisions can be replayed without repeating external side effects.
