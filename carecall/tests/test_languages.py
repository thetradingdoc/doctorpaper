from types import SimpleNamespace

import pytest

from carecall import load_profile
from carecall_languages import appointment_readback, initial_language, phrase


@pytest.mark.parametrize(
    "value,expected",
    [
        ("auto", "en"),
        ("en", "en"),
        ("ru", "ru"),
        ("ru-RU", "ru"),
        ("zh", "zh"),
        ("zh-CN", "zh"),
    ],
)
def test_initial_languages(monkeypatch, value, expected):
    monkeypatch.setenv("CARECALL_LANGUAGE", value)
    assert initial_language() == expected


def test_unknown_language_fails_clearly(monkeypatch):
    monkeypatch.setenv("CARECALL_LANGUAGE", "unsupported")
    with pytest.raises(ValueError):
        initial_language()


@pytest.mark.parametrize("language", ["en", "ru", "zh"])
def test_localized_readback_preserves_identifiers(language):
    c = {
        "start": "2026-11-10T10:00:00-05:00",
        "end": "2026-11-10T10:30:00-05:00",
        "provider": "Dr Lee",
        "location": "20 Example Plaza",
    }
    text = appointment_readback(load_profile(), c, language)
    assert "Alex Morgan" in text and "Dr Lee" in text and "20 Example Plaza" in text
    assert "2026" in text and "10:30" in text
    if language == "ru":
        assert "10 ноября" in text and "Нью-Йорка" in text
    if language == "zh":
        assert "2026年11月10日" in text and "纽约时间" in text


@pytest.mark.asyncio
async def test_language_switch_preserves_booking_state(monkeypatch):
    from my_agent import MyAgent

    monkeypatch.setenv("CARECALL_LANGUAGE", "en")
    monkeypatch.setenv("CARECALL_BACKEND", "mock")
    agent = MyAgent()
    updates = []
    fake_session = SimpleNamespace(
        tts=SimpleNamespace(update_options=lambda **kw: updates.append(kw))
    )
    monkeypatch.setattr(MyAgent, "session", property(lambda self: fake_session))
    agent.state.candidate = {"provider": "Dr Lee"}
    agent.state.reviewed_message = "review-id"
    for language in ["ru", "zh", "en"]:
        assert (await agent.set_language(language))["language"] == language
        assert agent.state.candidate == {"provider": "Dr Lee"}
        assert agent.state.reviewed_message == "review-id"
    assert updates == [{"language": "ru"}, {"language": "zh"}, {"language": "en"}]


@pytest.mark.asyncio
async def test_stt_metadata_switches_without_modifying_transcript(monkeypatch):
    from livekit.agents import Agent, stt

    from my_agent import MyAgent

    monkeypatch.setenv("CARECALL_LANGUAGE", "en")
    agent = MyAgent()
    updates = []
    fake_session = SimpleNamespace(
        tts=SimpleNamespace(update_options=lambda **kw: updates.append(kw))
    )
    monkeypatch.setattr(MyAgent, "session", property(lambda self: fake_session))
    events = [
        stt.SpeechEvent(
            type=stt.SpeechEventType.FINAL_TRANSCRIPT,
            alternatives=[stt.SpeechData(language="ru", text="Здравствуйте")],
        ),
        stt.SpeechEvent(
            type=stt.SpeechEventType.FINAL_TRANSCRIPT,
            alternatives=[stt.SpeechData(language="zh", text="您好")],
        ),
    ]

    async def source(*args):
        for event in events:
            yield event

    monkeypatch.setattr(Agent.default, "stt_node", source)
    received = [event async for event in agent.stt_node(None, None)]
    assert received == events
    assert agent.language == "zh"
    assert updates == [{"language": "ru"}, {"language": "zh"}]


def test_multilingual_stt_keeps_existing_model_without_english_lock(monkeypatch):
    import models

    captured = {}

    def fake(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(models.inference, "STT", fake)
    models.multilingual_stt()
    assert captured["model"] == "assemblyai/universal-3-6-pro"
    assert "language" not in captured
    assert captured["extra_kwargs"]["language_detection"] is True


@pytest.mark.parametrize("language", ["ru", "zh"])
def test_all_fixed_phrases_have_translation(language):
    for key in ["greeting", "hold", "check_in", "goodbye"]:
        assert phrase(language, key, name="Alex Morgan") != phrase(
            "en", key, name="Alex Morgan"
        )
