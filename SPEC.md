# nous — hackathon build specification

## One-line product

nous gives each referral a persistent administrative AI caseworker whose job is to move the patient from referral to completed care, while a global scheduling agent reuses cancelled capacity.

This is not a reminder bot. A case stays open until care completes, the patient genuinely opts out, or a person must take over.

## Scope for the hackathon

Build one convincing MRI pathway. Show:

1. a patient misses an appointment;
2. their caseworker calls, learns an administrative constraint such as “Saturdays only”, and records it;
3. an eligible slot is offered and accepted;
4. a cancellation creates a free slot;
5. the capacity agent ranks eligible patients and offers it safely;
6. acceptance releases the patient's old booking, producing another capacity event;
7. any clinical question goes to `HUMAN_REVIEW_REQUIRED`.

Do not build real NHS/PAS connectivity, medical decision-making, identity verification, payments, or a general workflow builder.

## Technical shape

- Python 3.12+ and FastAPI own all domain logic and HTTP endpoints.
- PostgreSQL is the durable source of truth.
- SQLAlchemy 2, Alembic, Pydantic v2, httpx and pytest.
- The supplied React UI is the operations console. It can call FastAPI when persistence is added.
- ElevenLabs is a voice transport, not a workflow engine or database.
- n8n is unnecessary for core behaviour. If included, use one disposable provider-webhook adapter only.
- One worker invocation takes one meaningful action and stops. Timers and incoming events wake cases again.

## Core records

- `Patient`: identity, phone/email, preferred channel and language.
- `Referral`: pathway, procedure, provider, status and administrative eligibility.
- `Goal`: success criteria, status, summary, blocker, version and `next_wake_at`.
- `Event`: immutable observation with source, payload and unique idempotency key.
- `Action`: proposed side effect, approval/status, payload/result and idempotency key.
- `Appointment` and `Slot`: offer/hold/book/cancel/complete states and hold expiry.
- `Communication`: channel, provider ID, outcome, safe summary and optional transcript.
- `GoalDecision`: observation, concise audit-facing rationale and proposed action. Never store hidden chain of thought.

## Workflow placement

Keep workflows as ordinary Python application services:

```text
app/
  domain/          # entities, enums, transition rules
  services/        # run_goal, wake_goal, match_slot, accept_offer
  adapters/        # ElevenLabs, fake voice, provider/PAS, model clients
  api/             # FastAPI routers and webhook verification
  workers/         # wake_due_goals and expired-hold recovery
  prompts/         # versioned structured-decision prompts
```

`run_goal(goal_id)` loads the compact case context, checks deterministic terminal conditions, requests one structured decision, validates it with policy code, stores the decision/action, executes one permitted effect, turns the result into an event, updates the goal and exits.

## Safety and correctness rules

- Minimise stored personal data and keep clinical decisions outside the system.
- The model proposes; Python validates and mutates.
- No medical advice, triage, urgency changes or treatment changes.
- Never cancel an existing appointment before the patient accepts the replacement.
- Validate procedure, site and constraints before offering a slot.
- Use unique idempotency keys for events and actions.
- Never offer the same slot to the same case twice without an explicit reset.
- Cap cascade depth, expire holds, and use row locks for concurrent booking.
- Expose only small, case-scoped voice tools.
- Store concise audit explanations rather than private reasoning.

## ElevenLabs contract

Create one administrative scheduling agent. Start outbound calls with dynamic variables: first name, goal ID, pathway, call reason, current appointment and proposed appointment. The agent must identify the administrative reason for the call and must not invent clinical information.

Server tools:

- `get_case(goal_id)` returns a policy-filtered conversation view;
- `list_offered_slots(goal_id)` returns only offers created for that case;
- `accept_slot(goal_id, slot_id)` validates the offer and performs the guarded transition;
- `reject_slot(goal_id, slot_id, reason)` records the outcome;
- `patient_constraint(goal_id, constraint)` records an administrative preference;
- `request_human(goal_id, reason)` enters human review.

Verify post-call webhook signatures over the raw request body. Persist provider conversation ID, transcript, outcome and safe summary as a communication/event, then wake the goal. Use the local voice provider only for development without telephony.

## Capacity ranking

Start deterministically: reject ineligible procedure/site combinations, then score no current appointment, improvement in appointment date, deadline proximity, stated time/site preferences and recent rejected offers. Use an LLM only for a readable rationale if desired. A match creates an offer or temporary hold—not a booking.

## Definition of done

- Dashboard, cases, case detail and capacity views are navigable and database-backed.
- The exact three-minute scenario works with fake voice.
- API decisions and side effects are typed, validated, idempotent and auditable.
- Real ElevenLabs is enabled entirely through configuration.
- Database migrations are repeatable and auditable.
- Unit tests cover eligibility, transitions, duplicate webhooks, hold expiry and cascade limits.
