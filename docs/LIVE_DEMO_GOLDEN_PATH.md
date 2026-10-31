# nous live-demo golden path

> **Fictional demonstration data only.** The people, identifiers, dates and notes below are invented. Keep `USE_FAKE_VOICE=true` unless an approved test telephone number is configured. Never place a call to a real patient during this demo.

## What this red thread proves

A reminder call safely verifies identity, reads durable preferences, records updated constraints, and moves an appointment without dropping the existing booking. The released slot then wakes the capacity overseer, which ranks eligible patients using **only explicit clinician-assigned urgency and administrative fit**, delegates the selected patient to a caseworker, and queues an earlier-slot call.

The demonstrator should say: “The model does bounded administrative work. It does not infer clinical need, alter clinical priority, or cancel a booking before a replacement is accepted.”

## Prerequisites and safety gate

- Open the deployed nous URL in a clean browser tab. Confirm **Overview**, **Appointments**, **Capacity**, **Calls**, **Agents**, and **Agent activity** load without a database warning.
- On **Agents**, confirm the Caseworker and Overseer definitions are active and the voice card reports the intended configuration. Use **Run once** only as manual recovery.
- Confirm the reminder policy is **48 hours before the appointment** (`REMINDER`, `lead_hours: 48`). For a live run, choose an appointment whose reminder is actually due; for the five-minute demo, use the prepared due-reminder fixture.
- Keep fake voice enabled. Only disable it when the configured ElevenLabs number is an approved test destination and the operator has explicitly agreed to place the call.
- Confirm the fixture contains two appointment slots of the same type: a replacement slot suitable for the first person and a later booked slot for the second person. Slot matching is appointment-type-specific.
- Confirm there are no stale open offers for either fixture person. Refresh before starting.
- The deployed demo uses `DEMO_CAPACITY_SLOT_MINUTES=120` and `DEMO_CAPACITY_HORIZON_DAYS=2`. This yields four weekday slots per appointment type per day across a deliberately short horizon, rather than hundreds of free appointments. The appointment type remains normally configurable outside demo mode.
- The capacity generator never rewrites existing held or booked slots. Apply the profile immediately after resetting the fictional fixture; if ordinary automatic slots were already generated, reset the fixture before rehearsing rather than mixing the two profiles.

## Fictional fixture

Use obvious demo identifiers so no record can be mistaken for a real patient.

| Record | Fictional values | Required starting state |
|---|---|---|
| Person A | Asha Demo, `DEMO-ASHA-001`, DOB `1985-04-12`, preferred language Hindi, approved test number | Booked morning appointment; reminder due; a later afternoon replacement is available |
| Person B | Ravi Demo, `DEMO-RAVI-002`, DOB `1972-09-03`, preferred language Hindi, approved test number | Booked later appointment of the same type; explicit clinician urgency `URGENT` |
| Comparison candidate | Mina Demo, `DEMO-MINA-003` | Booked later appointment of the same type; explicit clinician urgency `ROUTINE` or `UNSPECIFIED` |

### Set up what the UI supports

1. From **Overview** or **Appointments**, select **New referral**.
2. Create each fictional person with the exact demo reference, DOB, approved test phone number, language, and the same appointment type. The UI should show **Referral created**.
3. Open each row from **Appointments**. Under **Appointment notes**, add only factual administrative notes. For Asha add:
   - **Preference** — `Prefers Hindi for telephone calls.`
   - **Constraint** — `Has difficulty hearing; speak slowly, confirm understanding, and use an approved accessibility route if needed.`
   - **Constraint** — `Cannot attend morning appointments; afternoon slots only.`
4. Confirm each note appears with source/provenance and a version badge/history disclosure.
5. Open **Capacity**, filter to the chosen appointment type, and confirm the required available and booked slots are present.

The current UI creates referrals and notes but does not expose controls for creating slots, assigning initial bookings, setting clinician urgency, editing a note into v2, or forcing the reminder clock. Those values must be present in the prepared demo fixture before the session. Do not improvise with production data. Treat a missing fixture field as a failed prerequisite, not permission to invent it during the demo.

## Golden path: full operator sequence

### 1. Establish the durable case

Navigate to **Appointments → Asha Demo**. Show **Contact & preferences** and read back the recorded language and DOB presence without speaking the DOB aloud. Under **Appointment notes**, show the Hindi, hearing, and afternoon-only facts. Open each version-history disclosure to establish that changes are additive and attributable.

Expected evidence:

- The record is clearly `DEMO-ASHA-001`.
- Language is `Hindi`; accessibility and time constraints are factual notes, not clinical interpretations.
- Version history retains the superseded value when the prepared v2 note is shown; it does not silently overwrite v1.

### 2. Run the reminder call

Use the prepared due-reminder execution. If manual recovery is needed, go to **Agents → Caseworker → Run once**, then refresh. Do not use **Call patient** for the final live story unless its request has been set to purpose `REMINDER`; the generic drawer action is a recovery control, not proof of the timing policy.

In the simulated conversation, the agent must:

1. Explain that this is an administrative appointment reminder.
2. Ask Asha to state her DOB; never disclose the stored DOB.
3. Call `verify-identity`. Continue only when the result is `{"verified": true}`. A mismatch ends disclosure and goes to human review.
4. Read the durable Hindi, hearing, and afternoon-only constraints.
5. Confirm the new afternoon slot before changing anything.
6. Record only the confirmed changes as a new note/document version.
7. Accept the replacement only after explicit confirmation.

Expected ElevenLabs tool evidence (names as configured in ElevenLabs):

| Tool | Expected input/result |
|---|---|
| `get-case` | Demo goal ID; result allows appointment/site/availability topics only |
| `verify-identity` | Stated DOB; `verified: true` without returning the stored DOB |
| `patient-constraint` | Confirmed constraint such as `AFTERNOON_ONLY`; `recorded: true` |
| `list-offered-slots` | Same appointment type; afternoon option returned |
| `accept-slot` | Confirmed slot ID; `accepted: true`, new slot booked, prior slot released |

Expected caseworker trace evidence (for the durable run around the call): `read_case_notes` → optional `read_case_documents` → `write_case_note` and/or `write_case_document` → `queue_patient_call` with `purpose: REMINDER` → `end_step`. Each persisted tool span should be `OK`; the decision must show a real model/runtime or an explicitly labelled deterministic fallback.

### 3. Prove safe rescheduling and versioned updates

Return to **Appointments → Asha Demo** and refresh.

- The accepted afternoon appointment is booked.
- The previous morning booking is `RESCHEDULED`; its slot becomes `AVAILABLE` only after acceptance.
- The history contains `SLOT_ACCEPTED` with `released_slot_ids`, plus the call/note events.
- The updated note or appointment document has a new immutable version with provenance (for example, `ELEVENLABS` or `CASEWORKER`) and the earlier version remains visible.
- **Calls** shows purpose `REMINDER`, a typed outcome (`QUEUED`, then `ANSWERED` after a valid callback), language, and summary. A queued fake call is acceptable for the safe demo; do not claim it was answered.

### 4. Follow the released slot through the overseer

Open **Capacity**, filter to the appointment type, and show Asha’s former morning slot as the released gap. Then open **Agent activity** and select the newest relevant run.

The capacity decision must contain:

- `ranking_policy: clinician_assigned_urgency_then_administrative_fit`
- `ranked_choices` with Ravi and the comparison candidate
- reasons containing only explicit clinician-assigned urgency, days earlier/other administrative fit, and (if present) a clinician-assigned deadline
- `DELEGATE_EARLIER_SLOT_OFFER`, with the existing booking explicitly retained

Never describe the ranking as a diagnosis or model-inferred clinical priority. `UNSPECIFIED` must remain unspecified.

Expected persisted outcome:

- The selected released slot becomes `HELD` for 24 hours.
- An `OFFERED` appointment is created for Ravi while Ravi’s later booking remains `BOOKED`.
- `OVERSEER_DELEGATED` and a queued `EARLIER_SLOT_OFFER` action are recorded.
- The delegated caseworker is woken immediately.

### 5. Show the delegated earlier-slot offer

Navigate to **Appointments → Ravi Demo → Long-horizon execution**. Open the newest run and its tool disclosure. Then open **Calls**.

Expected evidence:

- The wake/delegation identifies the released slot and preserves the current booking.
- The caseworker reads notes before contact and queues the call with purpose `EARLIER_SLOT_OFFER`.
- The call uses Ravi’s configured preferred language.
- The call says an earlier slot is available; it does not say the later appointment has already been cancelled.
- Only a later `accept-slot` result may release Ravi’s old slot. A decline or no-answer keeps the existing booking and releases the temporary hold safely.

## Agent activity evidence checklist

On **Agent activity**, select each relevant recorded run in the left-hand **Runs** list. Expand every tool span and point out input, persisted result, status, sequence, runtime/model, tokens where available, and stop reason. For this story, capture or show:

- Reminder preparation: `read_case_notes`, `queue_patient_call`, `end_step`.
- Durable update: `write_case_note` or `write_case_document` returning a recorded/new version.
- Safe slot work: `search_slots` / `offer_slot`, or the voice `list-offered-slots` / `accept-slot` evidence in the appointment execution history.
- Capacity delegation: persisted decision/action/event showing ranked choices and `OVERSEER_DELEGATED`.
- Earlier offer: `read_case_notes`, `queue_patient_call` with `EARLIER_SLOT_OFFER`, `end_step`.

Do not narrate an execution that is absent. The page explicitly promises “No inferred executions.”

## Five-minute compressed script

**0:00–0:35 — Frame.** “These are fictional demo records. Calls are simulated unless the approved test number is configured. nous is administrative: it never invents clinical urgency.” Open **Appointments → Asha Demo**.

**0:35–1:15 — Context.** Show Hindi, hearing difficulty, afternoon-only constraint, DOB present, and note version history. Say: “The caseworker reads durable, attributable context rather than relying on transient call memory.”

**1:15–2:10 — Reminder.** Show the due `REMINDER` call/run. Expand identity verification and note/tool evidence. Say: “Asha states DOB; the tool returns only true or false. On mismatch, nothing sensitive is disclosed.”

**2:10–2:55 — Safe move.** Show the accepted afternoon appointment and `SLOT_ACCEPTED`. Say: “The morning booking was retained until acceptance; only then was the old slot released.” Show the new note/document version beside its predecessor.

**2:55–4:05 — Overseer.** Go to **Capacity**, then **Agent activity**. Show the released morning gap, ranking policy, candidates, and reasons. Say: “The overseer uses recorded clinician urgency and administrative fit only. It delegates; it does not call patients itself or infer priority.”

**4:05–4:45 — Cascade.** Open **Appointments → Ravi Demo → Long-horizon execution**, then **Calls**. Show `EARLIER_SLOT_OFFER`, preferred language, and that Ravi’s existing booking remains intact while the offer is held.

**4:45–5:00 — Close.** “One confirmed change safely freed capacity, produced an auditable ranking, and delegated the next bounded action—with every model and tool step persisted.”

## Failure and recovery

| Failure | Safe response | Recovery evidence |
|---|---|---|
| DOB mismatch or unavailable DOB | Stop disclosure; call `request-human`; do not list or accept slots | `verified: false` and `HUMAN_REVIEW_REQUIRED` |
| Patient raises a clinical question | Explain an appropriate person must respond; escalate | `request_human` / `request-human`, no priority change |
| Hearing/accessibility need prevents safe consent | Slow down and confirm; if still unsafe, stop and request human/accessibility support | Constraint note plus escalation; no reschedule |
| No suitable afternoon slot | Keep current booking; record constraint and arrange a later wake | `search_slots` empty, then `wait_until` or human review |
| Slot becomes unavailable | Do not cancel current booking; refresh/search again | `accept-slot` conflict or rejected tool span, current booking unchanged |
| Voice provider unavailable | Keep fake voice on or show queued/failed state honestly; do not use a real number as a workaround | Typed `FAILED`/`QUEUED` outcome and manual follow-up |
| Agent run fails | Open **Agents**, inspect **Recent executions**, then use **Run once** once after correcting the prerequisite | New persisted run linked by sequence/wake reason; failure remains visible |
| Activity table is empty | Stop the demo claim, refresh once, confirm database/migrations and a persisted run; fall back to the prepared screenshot only if clearly labelled | At least one real `AGENT_STEP` with tool spans before resuming |
| Overseer ranks on inferred medical content | Stop; do not place the offer; escalate as a product defect | No outbound action; evidence retained for review |

## End-state acceptance

The demo passes only if Asha’s replacement is booked, her old slot was released after acceptance, the versioned update and call purpose/outcome are visible, the overseer decision exposes its allowed ranking basis, Ravi’s caseworker receives a delegated earlier-slot action, and Ravi’s existing booking remains protected until he accepts.
