# Outbound CareCall setup

The calling code is installed, but a LiveKit phone number alone does not provide
outbound service. A Twilio, Telnyx or other outbound SIP provider must first be
connected to your LiveKit project. This is not a free outbound telephone service.
See https://docs.livekit.io/telephony/making-calls/outbound-trunk/ .

## Configure locally

Run from the `carecall` directory. Create `.env.local` from `.env.example` and fill
in your existing LiveKit credentials. Do not commit that file. Retain the credentials
in your old starter; copying them into this local ignored file is optional and manual.

Add the following settings locally (use your actual trunk and authorized destination):

```dotenv
AGENT_PROFILE=mine
AGENT_NAME=take2-agent
CARECALL_BACKEND=mock
CARECALL_OUTBOUND_ENABLED=true
SIP_OUTBOUND_TRUNK_ID=ST_your_outbound_trunk
SIP_FROM_NUMBER=+1YOUR_PROVIDER_NUMBER
CARECALL_ALLOWED_DESTINATIONS=+1YOUR_TEST_PHONE_NUMBER
```

`SIP_FROM_NUMBER` can be blank to use the configured trunk's default. If supplied,
it must be an allowed caller ID from your SIP provider, not an arbitrary LiveKit
inbound number. Keep SIP passwords in LiveKit's trunk configuration; this application
needs only the trunk ID. Allowlist entries are comma separated, exact international
numbers. The receptionist cannot modify this allowlist or request a dial through a tool.

## Start and call

In Terminal 1:

```sh
cd ~/Downloads/doctorpaper/carecall
uv sync
uv run python src/agent.py dev
```

Wait for worker registration. Stop any other worker registered with the same agent name
in this project so a dispatch cannot route to an old version. A cloud-hosted worker can
also handle the job, but must have the same outbound settings and updated code.

In Terminal 2, from the same directory:

```sh
uv run python src/outbound.py --to +1YOUR_TEST_PHONE_NUMBER --check
uv run python src/outbound.py --to +1YOUR_TEST_PHONE_NUMBER
```

`--check` validates local settings only, never places a call, and does not test provider
connectivity. The second command checks the trunk exists and queues one explicit agent
dispatch. A queued dispatch is not evidence of a dial or answered call. Watch Terminal 1
for `call_connected` or `call_failed`. If no worker is registered, queued work may wait;
do not repeatedly submit it. API network failures can have an ambiguous outcome; inspect
LiveKit rooms/call logs before retrying, because a second invocation is a new call.

You can use `--env-file /absolute/path/to/.env.local` for the launcher's local credential
file. The agent worker must load the same project and outbound settings independently.

The agent, after receiving the dispatch, validates the destination again, connects to
the room, makes ONE dial attempt, waits for answer and the SIP participant, and only
then starts the speech session. Ringing is limited to 30 seconds and calls to 10 minutes.
Failures delete the room and release the job. Busy/no-answer is not retried automatically.
Answered voicemail still counts as an answered telephone call; there is no dedicated
answering-machine detection integration. CareCall must not disclose sensitive data on
voicemail. On hangup the existing session deletes the room.

This uses the synthetic patient and mock calendar unless you explicitly configure a real
backend. It does not connect DoctorPaper's appointment queue or replace its separate [language settings](LANGUAGES.md). LiveKit call metadata contains the destination for dialing; do not put
patient records or credentials in dispatch metadata. Application logs omit the number,
but the carrier/LiveKit telephony logs necessarily record call routing information.

## Validation

```sh
uv run pytest -q
uv run ruff check src tests
```

Local tests cover disabled mode, exact destination authorization, bad metadata, inbound
compatibility, answer-before-session ordering, time limits, and no redials on failure.
Actual telephone audio requires a configured provider and an answered live call.
