# nous: remaining work

Audit date: 2026-10-15. This distinguishes the live Modal build in this directory from the richer implementation committed on branch `pathway-anthropic-agents` in PR #1. No secret values are recorded here.

## Current position

The public Modal URL is live: `/` returns HTTP 200 and `/health` reports a connected database plus configured ElevenLabs and Anthropic providers. The local React production build succeeds and the current API contract suite passes (4 tests).

PR #1 is committed but is not part of that deployment. Its full local suite passes with 85 tests and 7 environment-dependent integration tests skipped. It contains the more complete Pathway domain model, deterministic safety rules, Anthropic tool loop with fallback, case notes, agent traces, staff rescheduling, server-rendered operations pages, and an eval/hill-climb framework.

The main remaining job is therefore integration, not invention: make PR #1's tested domain engine the backend source of truth for the deployed React/Modal product, then rehearse one reliable end-to-end scenario.

## Implemented and deployed

- React operations console served with FastAPI from one Modal ASGI app.
- Supabase/Postgres connection and an applied Alembic schema for patients, referrals, goals, slots, appointments, events, actions, decisions, and communications.
- Read APIs for dashboard, patients/cases, case timeline, slots, calls, and agent activity.
- Write APIs for referrals, slots, manual rescheduling, due-agent execution, and capacity matching.
- Anthropic-backed bounded caseworker decision call and five-minute scheduled caseworker wake.
- Five-minute scheduled capacity matcher.
- ElevenLabs outbound-call adapter, six narrow case-scoped tools, and signed post-call webhook parsing/deduplication.
- Durable decision/action/event and call-summary records.
- Production build and minimal local API checks.

Important qualification: provider configuration reported by `/health` proves environment variables are present, not that a real call, verified webhook round trip, or successful live Anthropic decision has completed.

## Implemented only in Haiku PR #1

- Full referral-recovery domain engine: event ingestion, wake queue, one-decision steps, holds, offers, acceptance, decline, expiry, and bounded cascades.
- Atomic replacement-booking behavior: keep the old appointment until the replacement is accepted, then release the old slot into the cascade.
- Deterministic eligibility and capacity ranking, including pathway matching, weekend constraints, previous offers, appointment improvement, and cascade depth.
- Duplicate-event handling, row locking, due-time checks, retry rules, and human escalation for clinical questions.
- Anthropic tool-use caseworker with policy-enforced tools, structured step/tool-call traces, token counts, rollback on provider failure, and deterministic fallback.
- Case notes, call notes, staff notes, reschedule-request capture, and guarded staff rescheduling UI.
- Dashboard, goals, case detail, capacity, timeline, trace, demo clock, reset, and simulation flows in Jinja templates.
- Seeded synthetic demo cohort and scripted voice outcomes.
- Scenario eval runner, graders, prompt variants, CLI reporting, and hill-climb scaffolding.
- Broad automated coverage: 85 passing tests locally; 7 integration tests are skipped unless the external/local integration stack is enabled.

## Missing integration work

1. Choose one canonical backend. The recommended path is to port PR #1's `pathway/` domain engine into the deployed FastAPI/SQLAlchemy service, preserving the existing React API surface where useful.
2. Reconcile the two schemas. PR #1 uses `offers`, `patient_constraints`, `case_notes`, `agent_steps`, and `agent_tool_calls`; the deployed schema represents offers as appointments and has different field/status names. Add an Alembic migration and a deliberate data-mapping plan rather than using `create_all` in production.
3. Replace the deployed capacity matcher. It currently selects the first matching goal and does not apply PR #1's ranking, previous-offer, weekend, improvement, expiry, or cascade rules.
4. Replace or wrap the deployed caseworker. Its current four-action JSON decision (`CALL_PATIENT`, `WAIT`, `REQUEST_HUMAN`, `COMPLETE`) records a queued call but does not execute PR #1's policy-scoped tool loop or deterministic fallback.
5. Route every mutation through the domain services. In particular, deployed `accept-slot` can book an available/held slot without verifying a case-owned offer or releasing the previous booking atomically; constraint input is not allowlisted; reject/human event keys use random values and are not replay-idempotent.
6. Connect queued `CALL_PATIENT` actions to the ElevenLabs adapter and persist success/failure back onto the action. At present the scheduled caseworker can queue a call, while the outbound-call endpoint is a separate manual path.
7. Translate ElevenLabs webhook results into the same event/constraint/offer state transitions used by fake voice and the UI. Do not maintain a second behavior path for voice.
8. Decide which UI survives. Keep the React console as the product UI, but port the PR-only case notes, trace display, reschedule controls, offer state, candidate rationale, demo clock, and scenario controls into it.
9. Add an explicit seed/reset mechanism for the deployed database using synthetic data only. Make reset unavailable or strongly protected outside the demo environment.
10. Update Modal jobs to invoke the integrated worker/capacity services, with bounded batches and concurrency-safe claims.

## Missing credentials and configuration

- Rotate the Anthropic key that was shared in chat, then update the `nous-anthropic` Modal secret. Treat the shared value as exposed even if it has not been committed.
- Confirm the Anthropic model identifier is available to the account. PR #1 currently defaults to a model name that should be validated against the actual API account before deployment.
- Replace any ElevenLabs placeholder values with a restricted API key, real conversational-agent ID, real imported phone-number ID, and webhook signing secret.
- Configure the ElevenLabs agent prompt, first message, dynamic variables, and six server tools against the final public URL.
- Register the production post-call webhook and verify its signature header/body contract with a real signed delivery.
- Confirm the Supabase pooler connection is the intended production database and that migrations run before every deploy.
- Add protected internal/API authentication for scheduled workers and provider events. The current deployed mutation and voice-tool routes do not enforce an internal token.
- Keep phone numbers, API keys, database URLs, webhook secrets, and service-role credentials only in Modal/GitHub/Supabase secret stores.

## Test and eval gaps

- Run the 7 skipped PR integration tests against their Postgres/PostgREST stack and record the result.
- Add migration tests from the currently deployed schema to the integrated schema, including existing rows.
- Add deployed HTTP tests for create referral, capacity ranking, offer ownership, accept/decline/expiry, replacement booking, cascade, duplicate events, case notes, traces, webhook replay, and agent failure fallback.
- Add concurrency tests for two workers claiming the same goal and two patients accepting the same slot.
- Test webhook signature verification using an ElevenLabs fixture or sandbox event, not only the missing-signature case.
- Run one live Anthropic step with a synthetic patient and assert the resulting trace, action, and event are stored.
- Run one approved end-to-end ElevenLabs call: outbound request, tool call, patient response, signed webhook, persisted summary, and goal wake.
- Turn the PR eval scenarios into a release gate. Establish a baseline score, required safety pass rate, token/cost ceiling, and regression threshold.
- Add browser-level smoke coverage for the exact three-minute demo path.

## UX gaps

- The React console needs visible loading, empty, stale, and error states; action buttons should show progress and success/failure without relying on a full manual refresh.
- Show open offer versus booked appointment explicitly. Operators must be able to see that the old appointment remains intact until acceptance.
- Surface eligibility/ranking rationale, hold expiry, cascade depth, next wake reason, and deterministic-versus-Anthropic/fallback mode.
- Add case notes and a legible audit trace without exposing hidden chain-of-thought; show concise decisions, tool inputs/results, timestamps, and provider IDs.
- Add confirmation and recovery flows for real outbound calls, rescheduling, reset, and other consequential actions.
- Make clinical escalation prominent and ensure the UI never presents an AI action as clinical advice.
- Add a guided demo mode or reset button that always restores the same synthetic scenario and indicates that all data is synthetic.
- Check small-screen layout, keyboard navigation, focus states, contrast, and accessible status announcements.

## Production hardening

- Add authentication, authorization, tenant/organisation scoping, and least-privilege service access before using non-synthetic patient data.
- Protect all mutation, worker, and ElevenLabs tool endpoints with scoped credentials; add rate limits and request-size limits.
- Validate provider/patient identity and enforce strict schemas/allowlists for constraints, event types, tool inputs, phone numbers, and URLs.
- Minimise stored personal data; define retention/deletion rules for transcripts, notes, events, and logs. Encrypt and redact sensitive fields in observability tooling.
- Use transactional outbox/idempotency patterns for external calls so crashes cannot duplicate calls or lose action results.
- Add retries with backoff, dead-letter handling, stale-action recovery, hold cleanup, and operational alerts.
- Add structured logs and metrics for wake lag, failed actions, call failures, webhook rejection/replay, hold expiry, token/cost usage, and escalation volume.
- Pin dependencies, scan them, add CI lint/type/test/migration/eval gates, and use staged/rollback-capable deployments.
- Back up Postgres, test restore, document incident response, and set spend/rate budgets for Modal, Anthropic, ElevenLabs, and Supabase.
- Complete a privacy/security review before any NHS or real-patient pilot; the hackathon build should remain synthetic and administrative-only.

## Ordered hackathon-ready checklist

- [ ] Rotate the exposed Anthropic credential and set the validated model in Modal.
- [ ] Configure real ElevenLabs agent/number/webhook credentials, or explicitly choose fake voice for the judged demo.
- [ ] Merge/port PR #1's domain engine and schema into the deployed service.
- [ ] Apply the new migration to a disposable database, then production; verify row counts and constraints.
- [ ] Wire React actions, scheduled wakes, capacity matching, fake voice, and ElevenLabs through that one domain engine.
- [ ] Seed/reset the 12-patient synthetic scenario and confirm the UI labels it synthetic.
- [ ] Run all local suites, the 7 integration tests, migration tests, and the scenario eval release gate.
- [ ] Rehearse the core path: DNA -> administrative constraint -> eligible offer -> acceptance -> cancellation -> ranked reuse -> old-slot cascade -> clinical question escalation.
- [ ] If real voice is in the demo, complete one approved live call and signed webhook round trip; otherwise use fake voice and keep the live-call control disabled.
- [ ] Lock down public mutation/tool endpoints and remove or protect reset/debug controls.
- [ ] Deploy with migrations first, then smoke-test `/health`, dashboard data, one agent step, one capacity match, and one full browser scenario.
- [ ] Capture a fallback demo recording and a one-page operator script with the reset procedure and known limitations.

## Suggested cut line

For a reliable hackathon demo, ship the integrated PR domain engine, synthetic seed/reset, React case/capacity/audit views, Anthropic decision trace with deterministic fallback, and fake voice. Treat a real ElevenLabs call as a bonus only after the signed end-to-end rehearsal succeeds. Authentication, real provider connectivity, and use of real patient data remain post-hackathon work.
