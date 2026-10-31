# Deploy nous to Modal

> Demo configuration: `modal_app.py` deliberately sets `USE_FAKE_VOICE=true` on the call dispatcher, so queued outcome simulation needs only the database and makes no ElevenLabs/Twilio request. The web service still receives the ElevenLabs API key and agent ID so it can mint a short-lived signed browser-agent URL; no phone-number ID is required for that path. Real outbound telephony remains documented below for a later approved deployment.

## What is already prepared

- The production frontend is compiled to `dist/`.
- `modal_app.py` packages that frontend and the FastAPI backend into one Modal ASGI web function.
- The first deployment enables real ElevenLabs voice and requires the `pathway-elevenlabs` Modal secret.
- The Modal app name is `nous`.
- Containers scale to zero after two idle minutes; one container can serve concurrent static/API requests.

## One-time account setup

1. Sign into the Modal account/workspace that holds the credits.
2. In this project directory, run:

   ```bash
   modal token new
   ```

   This opens Modal's authentication flow and stores a local token. Do not paste that token into source files or chat.

3. Confirm the intended Modal profile/workspace:

   ```bash
   modal profile current
   modal app list
   ```

## ElevenLabs setup required before first deployment

In ElevenLabs:

1. Create an ElevenAgents agent named **nous Scheduling Caseworker**.
2. Give it the administrative-only system prompt in `ELEVENLABS.md`.
3. Import or connect a Twilio phone number in ElevenLabs and assign it to this agent.
4. Copy the agent ID and ElevenLabs phone-number ID.
5. Create an API key restricted to the agent/conversation capabilities needed for outbound calling.
6. Create a post-call transcription webhook. Keep its generated signing secret.

After authenticating Modal, create the required secret without committing any values:

```bash
modal secret create pathway-elevenlabs \
  ELEVENLABS_API_KEY='...' \
  ELEVENLABS_AGENT_ID='...' \
  ELEVENLABS_PHONE_NUMBER_ID='...' \
  ELEVENLABS_WEBHOOK_SECRET='...'
```

## Anthropic caseworker setup

```bash
modal secret create nous-anthropic \
  ANTHROPIC_API_KEY=... \
  ANTHROPIC_MODEL=claude-haiku-5-5
```

The deployed Modal app schedules `wake_caseworkers` and `run_capacity_overseer` every five minutes. Caseworker wakes remain safely inactive while the API key is a placeholder.

## First deployment

From the project root:

```bash
npm install
npm run build
modal deploy modal_app.py
```

Modal prints the public `modal.run` URL. Verify:

```bash
curl https://YOUR-URL.modal.run/health
```

Expected response:

```json
{"ok":true,"voice_provider":"elevenlabs"}
```

Then open the root URL and exercise Overview, Patient cases, Capacity, the case drawer and the fake call buttons.

## Development loop

Use a temporary live endpoint with file watching:

```bash
modal serve modal_app.py
```

For production updates:

```bash
npm run build
modal deploy modal_app.py --strategy recreate
```

The frontend must be rebuilt before deployment whenever `src/` changes.

## ElevenLabs configuration

The deployment requires one Modal secret named `pathway-elevenlabs` with:

```text
ELEVENLABS_API_KEY=...
ELEVENLABS_AGENT_ID=...
ELEVENLABS_PHONE_NUMBER_ID=...
ELEVENLABS_WEBHOOK_SECRET=...
```

The secret is already attached in `modal_app.py`. Redeploy and check `/health` reports `elevenlabs`. Configure the ElevenLabs post-call webhook as:

```text
https://YOUR-URL.modal.run/webhooks/elevenlabs
```

Before making calls, verify the configured recipients and restrict voice tools to authenticated ElevenLabs callers.

## Persistence decision

Modal containers are ephemeral, so durable state lives in Supabase Postgres through `DATABASE_URL`. Modal remains responsible for compute, web endpoints and scheduled wake workers.

## Scheduled case wake-up

Only add a scheduled worker after durable goal storage exists. The intended Modal function is:

```python
@app.function(image=image, schedule=modal.Period(minutes=1))
def wake_due_goals():
    # Query due goals using row locks, run one step per goal, then exit.
    ...
```

Do not schedule the current fixture-only UI: there is no durable state to wake yet.

## Operational checklist

- Use only an explicitly approved test number for the first real call.
- Do not put credentials in `.env.example`, Git or frontend code.
- Treat the generated URL as public unless proxy authentication is explicitly enabled.
- Minimise stored patient data and use explicit test recipients during development.
- Review Modal logs after each deploy.
- Set a spend notification/budget in the Modal workspace dashboard.
- Redeploy only after `npm run build` succeeds.
