# DoctorPaper — your care, in order

A responsive medical paperwork and appointment-tracking **hackathon prototype**, inspired by the supplied DoctorPaper camera UI and problem slide. The frontend is vanilla HTML/CSS/JS (no build dependencies); the optional local Python server provides document OCR, SQLite state, and a simple integration contract for the LiveKit voice agent.

> **Important:** This is NOT a HIPAA-compliant or production patient portal. Do not process real PHI in a publicly accessible deployment. Use synthetic demo records. There is no EHR sync, real phone call, insurance eligibility lookup, or appointment booking built into this UI.

## Quick start

```bash
python3 server.py
```

Open **http://127.0.0.1:8787** in your browser. The dashboard initially shows explicitly synthetic records and an illustrative voice-agent timeline. For a real local workspace, click the upper-right **DP** icon and enter the API token printed by the Python process. Set `DOCTORPAPER_API_TOKEN` to a strong random token to persist your local credentials across restarts; otherwise each server launch generates a new token. Files and records stay in `.local-data/` (gitignored). Bind to loopback by default.

Optional local OCR tools: install `tesseract` for PNG/JPG/WebP and `pdftotext` for PDFs. Without those binaries, the user can manually review the extracted fields. PDF and image **original files stay in the browser** and are not saved by the server; only OCR text and reviewed fields are stored in local SQLite. OCR is heuristic and can miss names, amounts or insurance. Never let OCR auto-trigger a call or a booking.

## What the UI includes

- **Overview**: polished responsive dashboard with documents, reviewed records, and request counts.
- **Document vault**: select category (Bill, Record, EOB, Receipt, Skin photo, Rx), upload supported files up to 10 MB, conservative local OCR, edit all fields, explicitly approve review, filter and browse.
- **Appointments**: choose reviewed records, create a request, see stage-by-stage live status fed by the voice-agent API. Client polls every 3 seconds in local workspace mode. Sample mode has a **clearly simulated** stage advance action.
- **Connections**: directions for Siri/Swift handoff. Navigation-only App Intents do not currently read records.
- **Privacy**: tokens, explicit review gate, localhost binding, content-size limits, no browser token persistence, and CSP headers. These are dev defaults, not production controls.

## Team contract: LiveKit agent (person 1)

All API requests require `Authorization: Bearer <DOCTORPAPER_API_TOKEN>`. API responses use JSON.

1. The UI creates a booking request using `POST /api/appointments` with `{ "document_ids": ["..."] }`. All IDs must refer to **reviewed** records.
2. Agent worker polls `GET /api/appointments` to discover new `status: "pending"` requests, then calls `GET /api/agent/context` to obtain **reviewed fields only**. Match selected `document_ids` from the request against the context list. The API deliberately does not grant unrestricted access to the original binary or unreviewed OCR text.
3. The agent calls `POST /api/appointments/<id>/events` for each meaningful change:

```json
{"stage":"context_ready","detail":"Verified reviewed context and started scheduling"}
```

Supported stages, in order: `request_received` → `context_ready` → `calling_provider` → `checking_availability` → `confirming_details` → `booked`. Or end with `failed` / `cancelled`. A successful **booked** event requires verified `provider`, `date`, and `time` (not guessed or simulated):

```json
{"stage":"booked","detail":"Provider confirmed the slot","provider":"Actual clinic","date":"2026-11-12","time":"10:30 AM","notes":"Confirmation reference from provider"}
```

**Never report `booked` based only on a voice model's intent.** The agent must receive a real booking confirmation from a provider or integration. The API is a hackathon event contract, not a secure job queue; it lacks worker claiming, agent-specific scoped tokens, patient authentication, and provider verification.

## Team contract: Siri (person 2)

The supplied `doctorlittle_Siri_Component(1).zip` contains two native Swift App Intents: open care timeline and open record connections. They currently only route the foreground native iOS app and require local-device unlocking plus app sign-in; they do NOT ingest medical records, read them aloud, or call this HTTP API. Because this repository provides a web frontend, the iOS teammate must implement an authenticated native host app (or a secure, explicit navigation bridge) and navigate to the corresponding screens; **do not** put a bearer token or PHI into AppIntent shortcut parameters.

For a future signed-in backend, `GET /api/agent/context` illustrates the minimal reviewed-data contract. Replace this local shared token with proper user identity, authorization, scoped service access, consent and audit before any real data integration.

## API reference

| Endpoint | Purpose |
| --- | --- |
| `GET /api/health` | Local availability check |
| `GET /api/documents` | Document metadata + reviewed state |
| `POST /api/documents` | Upload `filename`, `media_type`, `kind`, `content_base64` |
| `POST /api/documents/<id>/review` | Explicitly approve edited `fields` |
| `GET /api/agent/context` | Reviewed structured data only |
| `GET /api/appointments` | Request and event timeline list |
| `POST /api/appointments` | Create request from approved document IDs |
| `GET /api/appointments/<id>` | Get one request |
| `POST /api/appointments/<id>/events` | Update status from agent worker |

## Tests

```bash
python3 -m unittest discover -s tests -v
```

The tests exercise extracted field parsing, the reviewed-data gate and booking event state transition using only synthetic data.

## Roadmap before any real clinical deployment

Patient sign-in; per-user access control; HTTPS; encryption at rest; secure secrets; EHR OAuth consent; audit logging; retention/deletion policies; malware scanning and document lifecycle; regulated-data processing agreements; real provider scheduling confirmation; patient verification and safety escalation; accessibility and device QA.

## CareCall LiveKit voice agent

The patient-side voice agent lives in [`carecall/`](carecall/README.md). It preserves
the existing speech models and includes noisy-room STT endpointing, interruption/hold
handling, a synthetic patient profile, calendar checks, guarded booking result recording,
and receptionist roleplay scenarios. See [setup and backend contract](carecall/docs/CARECALL.md).

```sh
cd carecall
uv sync
cp .env.example .env.local
# Fill in your LiveKit credentials locally; AGENT_PROFILE is already mine.
lk agent console --input-device "MacBook Pro Microphone" --output-device "MacBook Pro Speakers"
```

No credentials, generated call results, or local environments are included. CareCall
defaults to a mock calendar and local result files; it does not dial phone numbers.
Its optional HTTP contract (`/calendar/check`, `/call-results`) is **not yet connected**
to DoctorPaper's `/api/appointments/.../events` contract. A backend adapter is still
required; copying the agent here does not automatically dispatch dashboard requests
or update their timeline. Use synthetic data for the demo.
