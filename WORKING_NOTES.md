# Working notes

- 2026-10-15: Created and versioned the real ElevenLabs `nous Scheduling Caseworker`
  agent and attached all six database-backed scheduling webhook tools. The ElevenLabs
  workspace still has no phone numbers; phone assignment and signed post-call webhook
  setup remain before an end-to-end outbound call.

## Voice integration

- 2026-10-15: Reworked the prototype into one Modal ASGI deployment serving the compiled React UI and FastAPI routes.
- 2026-10-15: Product name confirmed as `nous`; next Modal deployment uses app name `nous`.
- 2026-10-15: ElevenLabs moved into the required first release; `modal_app.py` requires the `pathway-elevenlabs` secret and sets `USE_FAKE_VOICE=false`.
- 2026-10-15: Added outbound ElevenLabs/Twilio calling with per-call dynamic variables.
- 2026-10-15: Added six narrow case-scoped webhook tools.
- 2026-10-15: Added ElevenLabs SDK HMAC verification over raw webhook bodies.
- 2026-10-15: Added `ELEVENLABS.md` with the prompt, first message, variables and exact tool contracts.
- 2026-10-15: Local shell had no ElevenLabs variables. Never record secret values in this file.
- 2026-10-15: Fixed a FastAPI response-annotation incompatibility found during integration validation.
- 2026-10-15: Added API contract tests for health, fake adapter, tool routes and unsigned webhook rejection; 4 tests pass.
- Remaining user-owned setup: obtain ElevenLabs API key, agent ID, imported phone-number ID and webhook signing secret; create the Modal secret without sharing values in source control.
- 2026-10-15: Production readiness now includes exact agent/tool/webhook setup, an explicit approved-number end-to-end test, complete OpenAPI contract coverage for all six tools, and retrying post-deploy readiness checks. ElevenLabs credentials remain solely in the Modal secret.

## Parallel Lovable workspace

- 2026-10-15: A collaborator is experimenting in Lovable project `4d7f7dab-e92f-4a66-9fed-31264e92e22f`.
- Reference URL: `https://lovable.dev/projects/4d7f7dab-e92f-4a66-9fed-31264e92e22f`.
- Treat this as a UI/reference workspace until its source is connected to GitHub or an explicit merge direction is agreed. Modal/FastAPI/Supabase remain the owners of runtime behaviour and durable state.

## Modal deployment

- 2026-10-15: Confirmed Modal CLI authentication on profile `htsaustin`.
- 2026-10-15: Confirmed the Modal workspace initially contains no secrets.
- 2026-10-15: Built the production Vite bundle successfully.
- 2026-10-15: Real voice is required for the first release; deployment must remain blocked until the required Modal secret exists rather than silently falling back to fake voice.
- 2026-10-15: User explicitly requested immediate deployment using placeholder ElevenLabs values. The deployed endpoints are structurally enabled for ElevenLabs, but outbound calls cannot succeed until the placeholder secret is replaced with real credentials.
- 2026-10-15: Created the `pathway-elevenlabs` Modal secret with explicit placeholder values, rebuilt the frontend, and deployed successfully.
- 2026-10-15: Verified the public root returns HTTP 200, the case tool returns valid structured JSON, and `/health` reports `voice_provider: elevenlabs` after the rolling deployment completed.
- 2026-10-15: Previous deployment URL: `https://htsaustin--pathway-hackathon-web.us-east.modal.run`; the renamed `nous` release will use `https://htsaustin--nous-web.us-east.modal.run`.
- 2026-10-15: Added pull-request CI for the frontend build and backend tests, plus a serialized `main` deployment workflow with a production health check.
- 2026-10-15: Added `pathway-database` Modal secret using the Supabase transaction-pooler URI. Secret values are not stored in Git or these notes.
- 2026-10-15: Added Alembic migrations as a required pre-deploy Modal job; production health now requires a working database connection.
- 2026-10-15: The previous release was verified (`/` and `/health` both HTTP 200). Source configuration now requires ElevenLabs for the next release.
- 2026-10-15: The production Vite bundle and Python application source compile cleanly. The `pathway-elevenlabs` Modal secret is configured; agent, phone-number and webhook identifiers still need real values.
- 2026-10-15: Supabase authentication succeeded after the database credential was updated. The project already contained five tables from an earlier prototype; the initial migration preserves them as `legacy_*` tables before creating the empty nous schema.
- 2026-10-15: Added the Anthropic-backed long-horizon caseworker runtime, five-minute Modal caseworker and capacity-overseer wakes, durable decisions/actions/events, manual referral and slot creation, guarded operator rescheduling, Calls and Agent activity views, and a replayable eval starter set. The `nous-anthropic` secret currently contains an explicit placeholder; real decisions remain disabled until a valid key replaces it.
- 2026-10-15: Applied the OKF runtime principles: deterministic scheduling and validation, one bounded action per wake, durable audit artifacts, a shared production/eval decision path, and no external side effects in eval cases.
