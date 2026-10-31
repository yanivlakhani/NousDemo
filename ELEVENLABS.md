# ElevenLabs agent configuration

## Current workspace state

- Agent: `nous Scheduling Caseworker`
- Agent ID: `agent_4301m4zja6btfrd8jyrh48eqy6zh`
- Attached workspace tools: `nous_get_case`, `nous_verify_identity`, `nous_list_offered_slots`,
  `nous_accept_slot`, `nous_reject_slot`, `nous_patient_constraint`, and
  `nous_request_human`
- Outstanding account setup: import or purchase an outbound phone number, assign it
  to the agent, configure the signed post-call webhook, and put the resulting phone
  number ID, agent ID, and webhook signing secret in the Modal
  `pathway-elevenlabs` secret.

## System prompt

You are nous, an administrative scheduling caseworker supporting patient pathways.

Your goal is to help the named patient progress from referral to a completed appointment. Clearly identify that you are calling about an appointment. Be calm, concise and respectful. You may discuss appointment dates, times, locations, attendance, contact preferences and administrative constraints only.

Never give medical advice, interpret symptoms, change clinical priority, discuss medication, or invent patient or clinical information. If the caller raises anything requiring clinical judgement, call `nous_request_human`, explain that a member of the care team must help, and do not continue the clinical topic.

Before discussing case-specific information, ask the patient to state their date of birth and call `nous_verify_identity`. Never disclose the date held on file. Continue only after a match; after two failures call `nous_request_human`. Then ask about language, hearing, communication, and accessibility preferences and record them with `nous_patient_constraint`.

Use `nous_get_case` after identity verification. Use `nous_list_offered_slots` before offering an appointment. Never claim a slot is booked until `nous_accept_slot` succeeds. If the patient declines, call `nous_reject_slot` and capture a short administrative reason. Confirm the agreed date, time and site once. End the call when the administrative task is complete.

Do not read internal IDs aloud.

## First message

Hello {{patient_first_name}}, this is nous calling about your appointment. Is now an okay time to speak?

## Dynamic variables expected

- `patient_first_name`
- `goal_id`
- `reason`
- `purpose`
- `preferred_language`
- `proposed_slot_id`

`goal_id` and `proposed_slot_id` are UUID strings supplied by nous; they must never be
inferred from speech. The first
message uses `patient_first_name`. Do not assign fallback values in ElevenLabs that
could silently route a call to a different case.

## Webhook tools

Create seven POST webhook tools using the deployed Modal base URL:

| Tool | Path | Required JSON body |
|---|---|---|
| `nous_get_case` | `/elevenlabs/tools/get-case` | `goal_id` string |
| `nous_verify_identity` | `/elevenlabs/tools/verify-identity` | `goal_id` string, `date_of_birth` YYYY-MM-DD |
| `nous_list_offered_slots` | `/elevenlabs/tools/list-offered-slots` | `goal_id` string |
| `nous_accept_slot` | `/elevenlabs/tools/accept-slot` | `goal_id`, `slot_id` strings |
| `nous_reject_slot` | `/elevenlabs/tools/reject-slot` | `goal_id`, `slot_id` strings; optional `reason` |
| `nous_patient_constraint` | `/elevenlabs/tools/patient-constraint` | `goal_id`, `constraint` strings |
| `nous_request_human` | `/elevenlabs/tools/request-human` | `goal_id`, `constraint` strings |

In each tool, set `goal_id` from the `goal_id` dynamic variable rather than asking the caller. Use a 10-second response timeout. All tools use authenticated, database-backed transitions.

Configure every tool as JSON `POST`, with `Content-Type: application/json`. Mark each
field listed above as required (except `reject_slot.reason`). Do not enable speech-to-
parameter extraction for `goal_id` or `slot_id`: map those from dynamic variables.
Treat any non-2xx response as a tool failure and hand off rather than claiming success.

## Repeatable configuration

The checked-in configuration is the source of truth. It contains no credentials and
reads the API key and agent ID only inside a Modal function from the existing secret:

```bash
modal run scripts/configure_elevenlabs.py
```

The command creates or updates the seven clearly named `nous_*` webhook tools,
attaches them, enables the language override permission used by outbound calls,
adds language presets for every language supported by `backend/app/records.py`, and
enables language detection. Its output is limited to agent/tool/version metadata;
it never prints API keys, phone numbers, stored dates of birth, or patient records.

## Post-call webhook

Subscribe to `post_call_transcription` and `call_initiation_failure` at:

```text
https://YOUR-MODAL-URL.modal.run/webhooks/elevenlabs
```

The backend validates `ElevenLabs-Signature` using the SDK and the Modal secret.

## Production readiness check

Four real values must exist in the Modal secret `pathway-elevenlabs`:
`ELEVENLABS_API_KEY`, `ELEVENLABS_AGENT_ID`, `ELEVENLABS_PHONE_NUMBER_ID`, and
`ELEVENLABS_WEBHOOK_SECRET`. Placeholder values are not usable. Do not paste any of
them into logs, screenshots, issue comments, or source control.

GitHub Actions does not duplicate these credentials. Modal remains the single runtime
source for these values; the deployment workflow verifies the resulting provider and
database readiness without reading or printing the secrets.

Before the first call:

1. Assign the imported phone number to the **nous Scheduling Caseworker** agent.
2. Publish the agent after adding the prompt, first message, variables, and seven tools.
3. Enable the two webhook events above and copy the generated signing secret into the
   Modal secret.
4. Redeploy, then require `/health` to return `database: true` and
   `voice_provider: "elevenlabs"`.
5. From the ElevenLabs dashboard, confirm the agent and phone number IDs shown there
   match the secret metadata. Do not reveal their values while doing this.

### One controlled end-to-end test call

Use a synthetic database case and a phone number whose owner explicitly approved the
test. This endpoint places a real call and may incur charges:

```bash
printf 'Deployed base URL: '; read -r NOUS_BASE_URL
printf 'Synthetic goal UUID: '; read -r NOUS_TEST_GOAL_ID
printf 'Approved E.164 phone number: '; read -r NOUS_TEST_PHONE
curl --fail-with-body --silent --show-error \
  --request POST "$NOUS_BASE_URL/api/voice/call" \
  --header 'Content-Type: application/json' \
  --data "{\"goal_id\":\"$NOUS_TEST_GOAL_ID\",\"patient_first_name\":\"Test\",\"phone_number\":\"$NOUS_TEST_PHONE\",\"reason\":\"End-to-end administrative scheduling test\"}"
```

Success requires all of the following, not merely HTTP 200: the approved handset
rings; the first message renders the name; `get_case` succeeds; a harmless constraint
or human-handoff tool call appears in ElevenLabs; and the signed post-call webhook
creates one call record without duplication. Delete or anonymise synthetic transcript
data according to the project's retention policy.
