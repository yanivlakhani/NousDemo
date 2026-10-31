# v0 remaining checklist

Short go/no-go list for the live nous demonstration.

## Must pass before demo

- [ ] A resettable fictional fixture creates Asha, Ravi, comparison candidate, initial bookings, afternoon replacement, released-gap cascade, explicit clinician urgency, and a due 48-hour reminder.
- [ ] The UI can show a real note/document v1 → v2 with provenance and retained history; operator note editing is either exposed or the prepared fixture supplies the revision.
- [x] Hindi maps to the ElevenLabs language code `hi`; a live Hindi test call still requires an approved test number and language override enabled on the agent.
- [ ] Fake voice is the default; real outbound calling requires an explicitly configured approved test number and a visible preflight check.
- [ ] The reminder path records `purpose: REMINDER`, language, typed outcome, summary, and valid post-call callback evidence.
- [ ] Identity verification returns only `verified: true/false`; mismatch prevents appointment disclosure and acceptance.
- [ ] Rescheduling is atomic: replacement accepted/booked before the prior booking is marked `RESCHEDULED` and its slot released.
- [ ] Released-slot matching persists ranked candidates, scores/reasons, and `clinician_assigned_urgency_then_administrative_fit`; no symptom/note-derived urgency.
- [ ] Overseer delegation queues `EARLIER_SLOT_OFFER`, wakes the selected caseworker, and keeps the candidate’s existing booking until acceptance.
- [ ] **Agent activity** is populated from persisted `AGENT_STEP` and tool-call records, with inputs/results/statuses and no synthetic executions.
- [ ] Appointment **Long-horizon execution** displays call, note/document, slot, wake, and delegation causality without duplicate/noisy capacity rows.

## Demo polish

- [ ] Add a one-click demo reset or documented fixture command, plus a visible “fictional data” banner.
- [ ] Surface the 48-hour reminder policy and call purpose in the UI before the operator triggers/reviews a reminder.
- [ ] Expose call purpose selection on the manual call control or label that control as recovery-only.
- [ ] Make held-slot expiry (24 hours), decline, no-answer, and provider-failure states easy to point out.
- [ ] Rehearse the five-minute script in `docs/LIVE_DEMO_GOLDEN_PATH.md` with fake voice and capture a known-good fallback recording/screenshots.
- [ ] Run backend tests and frontend build immediately before freezing the demo deployment.
