import json
from types import SimpleNamespace

import pytest

from outbound import OutboundConfigError, prepare_outbound, settings


def configure(monkeypatch):
    monkeypatch.setenv("CARECALL_OUTBOUND_ENABLED", "true")
    monkeypatch.setenv("SIP_OUTBOUND_TRUNK_ID", "ST_test")
    monkeypatch.setenv("CARECALL_ALLOWED_DESTINATIONS", "+12025550142")


def test_destinations_and_missing_trunk(monkeypatch):
    configure(monkeypatch)
    with pytest.raises(OutboundConfigError):
        settings("+12025550143")
    with pytest.raises(OutboundConfigError):
        settings("2025550142")
    monkeypatch.setenv("SIP_OUTBOUND_TRUNK_ID", "")
    with pytest.raises(OutboundConfigError):
        settings("+12025550142")


def test_disabled_by_default(monkeypatch):
    configure(monkeypatch)
    monkeypatch.delenv("CARECALL_OUTBOUND_ENABLED")
    with pytest.raises(OutboundConfigError):
        settings("+12025550142")


@pytest.mark.asyncio
async def test_console_and_inbound_never_dial():
    assert (
        await prepare_outbound(SimpleNamespace(job=SimpleNamespace(metadata="")))
        is None
    )
    assert (
        await prepare_outbound(
            SimpleNamespace(job=SimpleNamespace(metadata='{"user_id":"demo"}'))
        )
        is None
    )


@pytest.mark.asyncio
async def test_invalid_metadata_rejected():
    for value in ("{broken", "[]", '{"carecall_mode":"outbound"}'):
        with pytest.raises(OutboundConfigError):
            await prepare_outbound(SimpleNamespace(job=SimpleNamespace(metadata=value)))


@pytest.mark.asyncio
async def test_answer_before_session_can_greet(monkeypatch):
    configure(monkeypatch)
    events = []

    async def connect():
        events.append("connect")

    async def dial(request):
        assert request.sip_call_to == "+12025550142"
        assert request.wait_until_answered
        assert request.max_call_duration.seconds == 600
        assert request.ringing_timeout.seconds == 30
        events.append("dial_answered")

    async def participant(*, identity):
        assert identity == "carecall-callee"
        events.append("participant_joined")

    ctx = SimpleNamespace(
        job=SimpleNamespace(
            metadata=json.dumps(
                {"carecall_mode": "outbound", "phone_number": "+12025550142"}
            )
        ),
        room=SimpleNamespace(name="test-room"),
        connect=connect,
        api=SimpleNamespace(sip=SimpleNamespace(create_sip_participant=dial)),
        wait_for_participant=participant,
    )
    assert await prepare_outbound(ctx) == "carecall-callee"
    assert events == ["connect", "dial_answered", "participant_joined"]


@pytest.mark.asyncio
async def test_rejection_is_not_redialed(monkeypatch):
    configure(monkeypatch)
    calls = []

    async def connect():
        pass

    async def dial(request):
        calls.append(request)
        raise RuntimeError("provider refused")

    ctx = SimpleNamespace(
        job=SimpleNamespace(
            metadata=json.dumps(
                {"carecall_mode": "outbound", "phone_number": "+12025550142"}
            )
        ),
        room=SimpleNamespace(name="test-room"),
        connect=connect,
        api=SimpleNamespace(sip=SimpleNamespace(create_sip_participant=dial)),
    )
    with pytest.raises(RuntimeError):
        await prepare_outbound(ctx)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_missing_cloud_trunk_never_dispatches(monkeypatch):
    import outbound

    configure(monkeypatch)
    for key in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"):
        monkeypatch.setenv(key, "test-only")

    async def list_trunks(request):
        return SimpleNamespace(items=[])

    class Client:
        sip = SimpleNamespace(list_sip_outbound_trunk=list_trunks)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    monkeypatch.setattr(outbound.api, "LiveKitAPI", Client)
    with pytest.raises(OutboundConfigError, match="does not exist"):
        await outbound.launch("+12025550142")
