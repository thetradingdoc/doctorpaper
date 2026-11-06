"""One-shot outbound demo dispatch. No automatic redials or provider purchases."""

import argparse
import asyncio
import json
import os
import re
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from livekit import api


class OutboundConfigError(ValueError):
    pass


def validate_destination(number: str) -> str:
    if not re.fullmatch(r"\+[1-9][0-9]{7,14}", number):
        raise OutboundConfigError(
            "Use a full international number, for example +12025550142"
        )
    allowed = {
        n.strip()
        for n in os.getenv("CARECALL_ALLOWED_DESTINATIONS", "").split(",")
        if n.strip()
    }
    if number not in allowed:
        raise OutboundConfigError(
            "Destination must be in CARECALL_ALLOWED_DESTINATIONS"
        )
    return number


def settings(number: str) -> tuple[str, str]:
    validate_destination(number)
    if os.getenv("CARECALL_OUTBOUND_ENABLED", "false").lower() != "true":
        raise OutboundConfigError(
            "Outbound disabled. Configure a provider trunk, then set CARECALL_OUTBOUND_ENABLED=true"
        )
    trunk = os.getenv("SIP_OUTBOUND_TRUNK_ID", "")
    if not trunk.startswith("ST_"):
        raise OutboundConfigError(
            "Set SIP_OUTBOUND_TRUNK_ID to a configured LiveKit outbound trunk"
        )
    return trunk, os.getenv("SIP_FROM_NUMBER", "")


async def prepare_outbound(ctx) -> str | None:
    """Dial only for explicitly marked dispatches, before AgentSession starts speaking."""
    try:
        metadata = json.loads(ctx.job.metadata or "{}")
    except (TypeError, ValueError) as exc:
        raise OutboundConfigError("Invalid job metadata") from exc
    if not isinstance(metadata, dict):
        raise OutboundConfigError("Job metadata must be an object")
    if metadata.get("carecall_mode") != "outbound":
        return None
    number = metadata.get("phone_number")
    if not isinstance(number, str):
        raise OutboundConfigError("Outbound dispatch needs phone_number")
    trunk, caller = settings(number)
    identity = "carecall-callee"
    request = api.CreateSIPParticipantRequest(
        sip_trunk_id=trunk,
        sip_call_to=number,
        sip_number=caller,
        room_name=ctx.room.name,
        participant_identity=identity,
        participant_name="CareCall demo recipient",
        wait_until_answered=True,
        hide_phone_number=True,
    )
    request.ringing_timeout.FromSeconds(30)
    request.max_call_duration.FromSeconds(600)
    await ctx.connect()
    # Exactly one dial attempt. Carrier rejection, busy, timeout and no-answer
    # propagate to the entrypoint, which deletes the room and releases the job.
    await asyncio.wait_for(ctx.api.sip.create_sip_participant(request), timeout=45)
    await asyncio.wait_for(ctx.wait_for_participant(identity=identity), timeout=10)
    return identity


async def launch(number: str) -> str:
    trunk, _ = settings(number)
    for key in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"):
        if not os.getenv(key):
            raise OutboundConfigError(
                f"Missing {key}; select your local credentials with --env-file"
            )
    async with api.LiveKitAPI() as client:
        trunks = await client.sip.list_sip_outbound_trunk(
            api.ListSIPOutboundTrunkRequest()
        )
        if trunk not in {t.sip_trunk_id for t in trunks.items}:
            raise OutboundConfigError(
                "Configured outbound trunk does not exist in this LiveKit project"
            )
        room = f"carecall-outbound-{uuid4().hex[:16]}"
        await client.agent_dispatch.create_dispatch(
            api.CreateAgentDispatchRequest(
                agent_name=os.getenv("AGENT_NAME", "take2-agent"),
                room=room,
                metadata=json.dumps(
                    {"carecall_mode": "outbound", "phone_number": number}
                ),
            )
        )
        return room


def main():
    parser = argparse.ArgumentParser(
        description="Dispatch one authorized CareCall outbound call. Provider charges may apply."
    )
    parser.add_argument(
        "--to", required=True, help="Recipient in international +country format"
    )
    parser.add_argument(
        "--env-file", default=str(Path(__file__).resolve().parent.parent / ".env.local")
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate local settings only; no network calls or dialing",
    )
    args = parser.parse_args()
    load_dotenv(args.env_file)
    try:
        settings(args.to)
        if args.check:
            print(
                "Local outbound settings valid. No call placed; provider/worker connectivity not checked."
            )
            return
        room = asyncio.run(launch(args.to))
        print(
            f"Dispatch queued: {room}. This does not mean answered. Watch the running agent for call_connected or call_failed."
        )
    except (OutboundConfigError, ValueError) as exc:
        parser.exit(1, f"{exc}\n")
    except Exception:
        parser.exit(
            1,
            "Dispatch failed. Check project connectivity and credentials; no automatic retry was attempted.\n",
        )


if __name__ == "__main__":
    main()
