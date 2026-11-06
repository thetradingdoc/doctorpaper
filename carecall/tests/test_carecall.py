import json

import pytest

from carecall import Backend, CallState, load_profile


@pytest.mark.asyncio
async def test_calendar_and_record(tmp_path, monkeypatch):
    monkeypatch.setenv("CARECALL_BACKEND", "mock")
    monkeypatch.setenv("CARECALL_RESULTS_DIR", str(tmp_path))
    s = CallState(load_profile())
    b = Backend()
    assert (
        await b.available(s, "2026-11-10T10:00:00-05:00", "2026-11-10T10:30:00-05:00")
    )["available"]
    assert not (
        await b.available(s, "2026-11-10T14:00:00-05:00", "2026-11-10T14:30:00-05:00")
    )["available"]
    result = await b.record(s, {"status": "needs_patient"})
    assert json.loads((tmp_path / f"{s.call_id}.json").read_text()) == result


@pytest.mark.asyncio
async def test_reject_ambiguous_and_outside_window(monkeypatch):
    monkeypatch.setenv("CARECALL_BACKEND", "mock")
    s = CallState(load_profile())
    with pytest.raises(ValueError):
        await Backend().available(s, "2026-11-10T10:00:00", "2026-11-10T10:30:00")
    assert not (
        await Backend().available(
            s, "2027-01-01T10:00:00-05:00", "2027-01-01T10:30:00-05:00"
        )
    )["available"]


def test_http_fails_closed(monkeypatch):
    monkeypatch.setenv("CARECALL_BACKEND", "http")
    monkeypatch.setenv("CARECALL_API_URL", "http://invalid.example")
    with pytest.raises(ValueError):
        Backend()


@pytest.mark.asyncio
async def test_confirmation_guard_and_committed_result(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from livekit.agents import ToolError

    from my_agent import MyAgent

    monkeypatch.setenv("CARECALL_BACKEND", "mock")
    monkeypatch.setenv("CARECALL_RESULTS_DIR", str(tmp_path))
    agent = MyAgent()
    ctx = SimpleNamespace(disallow_interruptions=lambda: None)
    with pytest.raises(ToolError):
        await agent.record_result(ctx, "confirmed", "DEMO42", "")
    await agent.note_insurance("in_network")
    await agent.check_slot(
        "2026-11-10T10:00:00-05:00",
        "2026-11-10T10:30:00-05:00",
        "Dr Lee",
        "10 Example Plaza",
    )
    agent.state.latest_message = "offer"
    agent.state.reviewed_message = "offer"
    with pytest.raises(ToolError):
        await agent.record_result(ctx, "confirmed", "DEMO42", "")
    agent.state.latest_message = "confirmation"
    result = await agent.record_result(ctx, "confirmed", "DEMO42", "arrive early")
    assert result["status"] == "confirmed"
    assert result["appointment"]["start"] == "2026-11-10T10:00:00-05:00"
    assert len(list(tmp_path.glob("*.json"))) == 1
    assert await agent.record_result(ctx, "confirmed", "DEMO42", "") == result


@pytest.mark.asyncio
async def test_correction_invalidates_review(monkeypatch):
    from my_agent import MyAgent

    monkeypatch.setenv("CARECALL_BACKEND", "mock")
    agent = MyAgent()
    await agent.check_slot(
        "2026-11-10T10:00:00-05:00",
        "2026-11-10T10:30:00-05:00",
        "Dr Lee",
        "10 Example Plaza",
    )
    agent.state.reviewed_message = "review"
    await agent.check_slot(
        "2026-11-10T10:00:00-05:00",
        "2026-11-10T10:30:00-05:00",
        "Dr Chen",
        "20 Example Plaza",
    )
    assert agent.state.reviewed_message is None


@pytest.mark.asyncio
async def test_failed_replacement_clears_old_slot(monkeypatch):
    from livekit.agents import ToolError

    from my_agent import MyAgent

    monkeypatch.setenv("CARECALL_BACKEND", "mock")
    agent = MyAgent()
    await agent.check_slot(
        "2026-11-10T10:00:00-05:00",
        "2026-11-10T10:30:00-05:00",
        "Dr Lee",
        "10 Example Plaza",
    )
    agent.state.reviewed_message = "old-review"
    with pytest.raises(ToolError):
        await agent.check_slot("unclear", "unclear", "Dr Lee", "10 Example Plaza")
    assert agent.state.candidate is None
    assert agent.state.reviewed_message is None


@pytest.mark.asyncio
async def test_network_must_be_rechecked_at_new_location(monkeypatch):
    from my_agent import MyAgent

    monkeypatch.setenv("CARECALL_BACKEND", "mock")
    agent = MyAgent()
    await agent.note_insurance("in_network")
    await agent.check_slot(
        "2026-11-10T10:00:00-05:00",
        "2026-11-10T10:30:00-05:00",
        "Dr Lee",
        "10 Example Plaza",
    )
    await agent.check_slot(
        "2026-11-10T10:00:00-05:00",
        "2026-11-10T10:30:00-05:00",
        "Dr Lee",
        "20 Example Plaza",
    )
    assert agent.state.insurance == "unknown"


@pytest.mark.asyncio
async def test_record_failure_retry_and_no_post_commit_edits(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from livekit.agents import ToolError

    from my_agent import MyAgent

    monkeypatch.setenv("CARECALL_BACKEND", "mock")
    monkeypatch.setenv("CARECALL_RESULTS_DIR", str(tmp_path))
    agent = MyAgent()
    original = agent.backend.record

    async def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr(agent.backend, "record", fail)
    ctx = SimpleNamespace(disallow_interruptions=lambda: None)
    with pytest.raises(ToolError):
        await agent.record_result(ctx, "needs_patient", "", "patient consent required")
    assert agent.state.result is None
    monkeypatch.setattr(agent.backend, "record", original)
    assert (
        await agent.record_result(ctx, "needs_patient", "", "patient consent required")
    )["status"] == "needs_patient"
    with pytest.raises(ToolError):
        await agent.note_insurance("in_network")


@pytest.mark.asyncio
async def test_review_interruption_invalidates_previous_receipt(monkeypatch):
    from types import SimpleNamespace

    from livekit.agents import ToolError

    from my_agent import MyAgent

    monkeypatch.setenv("CARECALL_BACKEND", "mock")
    agent = MyAgent()
    await agent.note_insurance("in_network")
    await agent.check_slot(
        "2026-11-10T10:00:00-05:00",
        "2026-11-10T10:30:00-05:00",
        "Dr Lee",
        "10 Example Plaza",
    )

    async def playout():
        pass

    speech = SimpleNamespace(wait_for_playout=playout, interrupted=True)
    fake_session = SimpleNamespace(say=lambda text: speech)
    monkeypatch.setattr(MyAgent, "session", property(lambda self: fake_session))
    agent.state.reviewed_message = "stale-review"
    with pytest.raises(ToolError):
        await agent.review_slot(SimpleNamespace())
    assert agent.state.reviewed_message is None


@pytest.mark.asyncio
async def test_hours_boundaries_and_offset_equivalence(monkeypatch):
    monkeypatch.setenv("CARECALL_BACKEND", "mock")
    b, s = Backend(), CallState(load_profile())
    assert not (
        await b.available(s, "2026-11-10T16:45:00-05:00", "2026-11-10T17:15:00-05:00")
    )["available"]
    assert not (
        await b.available(s, "2026-11-14T10:00:00-05:00", "2026-11-14T10:30:00-05:00")
    )["available"]
    assert not (
        await b.available(s, "2026-11-10T19:00:00+00:00", "2026-11-10T19:30:00+00:00")
    )["available"]
    assert (
        await b.available(s, "2026-11-10T15:00:00-05:00", "2026-11-10T15:30:00-05:00")
    )["available"]


@pytest.mark.asyncio
async def test_hold_acknowledges_once_and_resumes(monkeypatch):
    from types import SimpleNamespace

    from livekit.agents import StopResponse

    from my_agent import MyAgent

    monkeypatch.setenv("CARECALL_BACKEND", "mock")
    agent = MyAgent()
    spoken = []

    async def say(text):
        spoken.append(text)

    fake_session = SimpleNamespace(say=say)
    monkeypatch.setattr(MyAgent, "session", property(lambda self: fake_session))
    for _ in range(2):
        with pytest.raises(StopResponse):
            await agent.set_hold(True)
    assert agent.state.on_hold
    assert len(spoken) == 1
    assert (await agent.set_hold(False))["on_hold"] is False


@pytest.mark.asyncio
async def test_same_slot_recheck_is_noop(monkeypatch):
    from my_agent import MyAgent

    monkeypatch.setenv("CARECALL_BACKEND", "mock")
    agent = MyAgent()
    await agent.note_insurance("in_network")
    args = (
        "2026-11-10T10:00:00-05:00",
        "2026-11-10T10:30:00-05:00",
        "Dr Lee",
        "10 Example Plaza",
    )
    await agent.check_slot(*args)
    agent.state.reviewed_message = "review"
    await agent.check_slot(*args)
    assert agent.state.reviewed_message == "review"


@pytest.mark.asyncio
async def test_calendar_rechecks_have_unique_keys(monkeypatch):
    monkeypatch.setenv("CARECALL_BACKEND", "http")
    monkeypatch.setenv("CARECALL_API_URL", "https://backend.example")
    b, s = Backend(), CallState(load_profile())
    keys = []

    async def request(path, payload, key):
        keys.append(key)
        return {"available": True}

    monkeypatch.setattr(b, "request", request)
    for _ in range(2):
        await b.available(s, "2026-11-10T10:00:00-05:00", "2026-11-10T10:30:00-05:00")
    assert keys[0] != keys[1]
