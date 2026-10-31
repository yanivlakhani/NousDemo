# nous: AI caseworkers for missed NHS appointments

Built in a weekend at the **UCL AI Society x Accel hackathon** (October 2026).

Missed appointments ("did not attends", or DNAs) waste scarce diagnostic capacity such as MRI slots and push patients further down waiting lists. Reminder texts help, but they stop at a reminder. When a patient misses an appointment or can't make the time they've been given, someone still has to phone them, find out what works, rebook them, and refill the slot they've just freed.

nous gives every referral a persistent **administrative AI caseworker** whose job is to get that patient from referral to completed care. A separate **capacity agent** watches for cancellations and offers freed slots to the patients who can actually use them.

## What the prototype does

The demo follows one MRI pathway end to end:

1. A patient misses their appointment.
2. Their caseworker calls them with a voice agent, learns an administrative constraint (for example "Saturdays only"), and records it in the case notes.
3. A suitable slot is offered and accepted.
4. Another patient cancels, freeing a slot.
5. The capacity agent ranks eligible patients and offers the slot safely.
6. Acceptance releases that patient's old booking, which creates a new capacity event and the cascade continues.
7. Any clinical question is routed to `HUMAN_REVIEW_REQUIRED`. The system never makes clinical decisions.

An operations console shows every case, the agents' decisions, and a live view of the overseer loop as it runs.

## How it works

The core design rule is that **the model proposes and Python validates**. Each time a case wakes up (a timer fires, a call ends, a slot frees up), the caseworker loads a compact view of the case, asks Claude for one structured decision, checks it against policy code, executes at most one permitted action, records the result as an event, and goes back to sleep.

Safety rules are enforced in code rather than left to the prompt: no clinical advice or triage, an existing booking is never cancelled before the replacement is accepted, procedure and site eligibility are checked before any offer, slot holds expire, concurrent bookings use row locks, and every event and action carries an idempotency key so duplicate webhooks can't double book. Decisions are stored as short audit-facing rationales.

The voice agent (ElevenLabs) only gets a handful of narrow, case-scoped tools: look up the case, list offered slots, accept or reject a slot, record a patient constraint, and hand off to a human.

## Tech stack

**Backend:** Python, FastAPI, SQLAlchemy 2, Alembic, Pydantic v2, PostgreSQL (Supabase)
**AI:** Claude (Anthropic API) for structured caseworker decisions, ElevenLabs conversational agent for voice
**Frontend:** React, TypeScript, Vite, React Flow
**Infrastructure:** Modal for deployment, GitHub Actions for CI/CD
**Testing:** ~100 pytest tests plus a nine-case evaluation suite for the agent's decisions

## Running it locally

The demo runs with a simulated voice provider by default, so no phone calls are made and no API keys are needed to explore the interface.

```bash
# Frontend
npm install
npm run dev

# Backend
cd backend
cp .env.example .env        # leave USE_FAKE_VOICE=true for local use
python -m venv .venv
source .venv/bin/activate
pip install -e .
uvicorn app.main:app --reload --port 8000
```

See `DEPLOYMENT.md` for deployment and `ELEVENLABS.md` for connecting a real voice agent.

## Team and my role

Built by a team of two medical students and an engineer. I built the voice calling agents and the mock patient data used to drive the demo, wrote the pitch deck and script, and designed the video demo and live pitch. Most of the backend and frontend commits in this repository were made by my teammate [@htsaustin](https://github.com/htsaustin).

All patient data in this repository is synthetic. No real patients were contacted.
