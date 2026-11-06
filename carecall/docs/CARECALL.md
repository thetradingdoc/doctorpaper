# CareCall setup and roleplay

CareCall calls as a patient's AI assistant; you play the receptionist. Existing STT,
LLM, TTS, noise enhancement and audio turn detector remain in place. AssemblyAI STT endpointing now owns turn completion rather than the audio turn
model: 300 ms minimum pause, 1000 ms maximum silence, with a 200 ms session grace period to merge a quickly continued sentence.
Far-field Voice Focus and a 0.6 VAD threshold target noisy laptop microphones.
Adaptive interruptions require speech content and recover from false interruptions.
The STT, LLM and TTS model identities remain unchanged. These defaults were exercised
through the full audio debugger; actual room-noise performance needs microphone testing.
See https://docs.livekit.io/reference/agents/turn-handling-options/ .

## Run

From ~/Downloads/take2-voice-starter:

```sh
uv sync
uv run python src/agent.py download-files
lk agent console
# room-connected development instead:
uv run python src/agent.py dev
# local checks:
uv run ruff check src tests
uv run pytest -q
# lower-cost text test, stop when finished:
lk agent debugger start
lk agent debugger say "Example Family Clinic, how may I help?"
lk agent debugger stop
# optional credit-consuming receptionist simulations:
AGENT_PROFILE=mine CARECALL_BACKEND=mock lk agent simulate text --scenarios scenarios-carecall.yaml
```

.env.local must retain existing LiveKit credentials, with AGENT_PROFILE=mine.
MODEL_PRESET remains unchanged. Default CARECALL_BACKEND=mock. No new provider keys.
Use headphones for voice tests. A running old agent must be stopped and restarted.

## Patient and authorization

config/patient.synthetic.json is fictional, including insurance. Alex Morgan wants
routine primary care November 9–20, 2026, weekdays 9–5 Eastern. November 10, 1–3 PM
is busy. Update date_window and busy as demo dates age. Patient permits one routine
in-network booking, no payments, self-pay, cancellations or medical decisions.
CARECALL_PROFILE can select another trusted JSON file with the same fields.
Do not let room metadata or a receptionist replace this trusted profile.

## Mock versus real

Mock mode checks only the fixture calendar. The receptionist supplies clinic slots
and network statements. Neither constitutes independently verified insurer eligibility.
The agent records the receptionist's reported confirmation; it does not create a clinic
appointment, dial a phone, or write Apple Calendar. Outbound calling is available through `src/outbound.py` after separate provider/trunk
setup; see [outbound setup](OUTBOUND.md). Files under results/<call UUID>.json contain only the recorded outcome, appointment,
reference, notes and evidence message ID, not full transcripts or credentials. They are
gitignored, private local files; delete test files when no longer needed.

HTTP mode requires CARECALL_BACKEND=http, CARECALL_API_URL=https://... and optional
CARECALL_API_TOKEN. It never silently falls back to mocks. Your teammate implements:

* POST /calendar/check: {patient_id,start,end}; returns {available: boolean}.
* POST /call-results: {call_id,patient_id,mode,status,appointment,insurance,
  confirmation_reference,notes,evidence_message_id}; returns {receipt_id: string}.

Authorization is Bearer token; result idempotency key is call_id. Backend must deduplicate
that key and return the original receipt on retry, enforce patient authorization, retain
an audit trail and reconcile ambiguous network failures. Eight-second timeouts and no
redirects apply. Calendar is rechecked before recording. Local result persistence follows
backend acknowledgement; a disk failure after acknowledgement requires idempotent retry.
No real backend integration has been validated against your teammate's service.

## Receptionist checklist

1. Happy path: exact plan in-network; Nov 10 at 10 AM Eastern, 30 minutes, Dr Lee,
   10 Example Plaza. Confirm booked DEMO42 only after readback. Inspect results file.
2. Conflict: offer Nov 10 at 2 PM then 10 AM. Expect first rejected, second checked.
3. Correction: interrupt readback: “Actually Dr Chen, at 20 Example Plaza.” Expect
   updated check/readback and later confirmation, no stale appointment recorded.
4. Long speech: pause half a second between date, time and location; spell the name
   and group digits. Agent should wait and ask about ambiguity without guessing.
5. Barge-in: interrupt with “Wait, that's not booked yet.” Expect speech to stop and
   no confirmed result until a subsequent explicit booking statement.
6. Hold: “Please hold”; stay quiet for 45 seconds, play music, then return. Expect no
   eight-second check-ins/hangup. Hold state suppresses silence handling; hold has no
   automatic maximum, so operator must end an abandoned call.
7. Insurance: “We take the carrier” then “not this network.” Expect no self-pay booking.
8. Ask SSN/card/unknown referral number or patient personal consent: needs_patient.
9. No slots in authorized dates: no_availability, never invent clinic availability.
10. Voicemail: minimal callback message without DOB/member ID; unresolved result.
11. Backend timeout/non-200/malformed receipt: never claim successful recording or
    request a duplicate clinic booking; reconcile via call_id.

Text debugger proves neither audio endpointing nor interruption quality. Use console
and LiveKit Agent Console timing traces to tune min_delay/max_delay/min_duration.
Confirmation meaning and hold announcements are interpreted by the LLM; code enforces
message ordering and validated state, but does not independently prove the receptionist
said “booked.” Production needs authenticated patient profiles and backend enforcement.

## Natural speech and reliability update

CareCall now uses a direct, profile-based greeting without an LLM round trip,
plain speech without expressive emotion/pause tags, preemptive TTS, and fixed
recognition keyterms without dynamic detection. Model/voice identities are preserved.
Preemptive TTS can increase inference usage for discarded replies. Voice is still AI
and disclosed at introduction; no guarantees of human indistinguishability.

The `voice_timing` log contains numeric timing metadata for user and assistant messages
without copying message text. Compare `end_of_turn_delay`, `llm_node_ttft`,
`llm_node_ttfs`, and `tts_node_ttfb` to locate occasional waits. Remote model/provider
latency still varies; this update does not guarantee a response-time ceiling.

Additional guards clear a stale slot after failed calendar checks, require network
reverification after changing provider/location, invalidate interrupted readbacks,
reject changes after a result is saved, and cancel stale silence tasks when speech
resumes. Calendar POST requests get distinct request IDs so a recheck cannot receive
an old idempotent result. Result writes retain the stable call ID for retry deduplication.
Hold acknowledgement is delivered once by the hold tool and suppresses its followup
reply; interpretation of hold announcements remains model-dependent.

Regression checks cover calendar boundaries/UTC equivalence, stale slot replacement,
network invalidation, interrupted review, storage failure/retry, post-save mutation,
and repeated hold entry/resume. Tests of these application guards do not prove every
natural-language interpretation. Rerun the receptionist scenarios and microphone tests
in your actual noise environment before a demo.

Successful readback tools now suppress the extra LLM followup: the human hears one
complete confirmation question, then CareCall waits. The audio regression previously
exposed an unnecessary second reply after readback; this was removed. The 200 ms grace
period reduces answering between quickly connected sentences while keeping STT-based
endpointing. In one audio test ordinary replies logged about 0.85–1.08 seconds end to
end; those samples are diagnostics, not a latency benchmark or guarantee.
