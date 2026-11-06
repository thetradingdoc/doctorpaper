"""CareCall domain state and explicit mock/HTTP backend contract."""

import asyncio
import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import aiohttp


@dataclass
class CallState:
    profile: dict
    call_id: str = field(default_factory=lambda: str(uuid4()))
    on_hold: bool = False
    insurance: str = "unknown"
    candidate: dict | None = None
    insurance_target: tuple[str, str] | None = None
    reviewed_message: str | None = None
    latest_message: str | None = None
    result: dict | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


def load_profile() -> dict:
    return json.loads(
        Path(
            os.getenv(
                "CARECALL_PROFILE",
                str(
                    Path(__file__).resolve().parent.parent
                    / "config/patient.synthetic.json"
                ),
            )
        ).read_text()
    )


class Backend:
    def __init__(self):
        self.mode = os.getenv("CARECALL_BACKEND", "mock")
        if self.mode not in {"mock", "http"}:
            raise ValueError("CARECALL_BACKEND must be mock or http")
        self.url = os.getenv("CARECALL_API_URL", "").rstrip("/")
        if self.mode == "http" and not self.url.startswith("https://"):
            raise ValueError("HTTP backend requires an HTTPS CARECALL_API_URL")

    async def request(self, path: str, payload: dict, key: str) -> dict:
        headers = {"Idempotency-Key": key}
        token = os.getenv("CARECALL_API_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        async with (
            aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as client,
            client.post(
                self.url + path, json=payload, headers=headers, allow_redirects=False
            ) as response,
        ):
            if response.status != 200:
                raise ValueError(
                    "Backend unavailable; outcome unknown, do not claim success"
                )
            return await response.json()

    async def available(self, state: CallState, start: str, end: str) -> dict:
        a, b = datetime.fromisoformat(start), datetime.fromisoformat(end)
        if a.tzinfo is None or b.tzinfo is None or b <= a:
            raise ValueError("Use ordered ISO datetimes including UTC offsets")
        p = state.profile
        local = a.astimezone(ZoneInfo(p["timezone"]))
        finish = b.astimezone(ZoneInfo(p["timezone"]))
        if not p["date_window"][0] <= local.date().isoformat() <= p["date_window"][1]:
            return {"available": False, "reason": "outside authorized date window"}
        if (
            local.weekday() >= 5
            or local.hour < 9
            or (finish.hour * 60 + finish.minute) > 17 * 60
            or finish.date() != local.date()
        ):
            return {
                "available": False,
                "reason": "outside weekday nine-to-five preference",
            }
        if self.mode == "http":
            result = await self.request(
                "/calendar/check",
                {"patient_id": p["id"], "start": start, "end": end},
                f"{state.call_id}:calendar:{uuid4()}",
            )
            if (
                not isinstance(result, dict)
                or type(result.get("available")) is not bool
            ):
                raise ValueError("Invalid calendar response")
            return result
        for busy in p["busy"]:
            if a < datetime.fromisoformat(busy[1]) and b > datetime.fromisoformat(
                busy[0]
            ):
                return {"available": False, "reason": "mock calendar conflict"}
        return {"available": True, "source": "mock", "start": start, "end": end}

    async def record(self, state: CallState, result: dict) -> dict:
        payload = {
            "call_id": state.call_id,
            "patient_id": state.profile["id"],
            "mode": self.mode,
            **result,
        }
        if self.mode == "http":
            receipt = await self.request("/call-results", payload, state.call_id)
            if (
                not isinstance(receipt, dict)
                or not isinstance(receipt.get("receipt_id"), str)
                or not receipt["receipt_id"]
            ):
                raise ValueError("Backend did not acknowledge recording")
            payload["receipt_id"] = receipt["receipt_id"]
        folder = Path(os.getenv("CARECALL_RESULTS_DIR", "results"))
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        target = folder / f"{state.call_id}.json"
        temp = target.with_suffix(".tmp")
        temp.write_text(json.dumps(payload, indent=2))
        temp.chmod(0o600)
        temp.replace(target)
        return payload
