"""Supported voice languages and deterministic booking readbacks."""

# Native Chinese punctuation is intentional in spoken localization strings.
# ruff: noqa: RUF001

import os
from datetime import datetime
from zoneinfo import ZoneInfo

SUPPORTED = {"en": "English", "ru": "Russian", "zh": "Mandarin Chinese"}


def initial_language() -> str:
    value = os.getenv("CARECALL_LANGUAGE", "auto").strip().lower()
    aliases = {
        "auto": "en",
        "en-us": "en",
        "ru-ru": "ru",
        "zh-cn": "zh",
        "zh-hans": "zh",
        "mandarin": "zh",
        "russian": "ru",
    }
    value = aliases.get(value, value)
    if value not in SUPPORTED:
        raise ValueError("CARECALL_LANGUAGE must be auto, en, ru, or zh")
    return value


MESSAGES = {
    "en": {
        "greeting": "Hi, I'm CareCall, an AI assistant calling for {name}. Am I speaking with the appointment desk?",
        "hold": "Of course, I'll hold.",
        "check_in": "Are you still there?",
        "goodbye": "I'll let you go. Thanks, goodbye.",
    },
    "ru": {
        "greeting": "Здравствуйте! Я CareCall, ИИ-помощник. Звоню от имени {name}. Это регистратура?",
        "hold": "Конечно, я подожду.",
        "check_in": "Вы ещё на линии?",
        "goodbye": "Тогда завершим звонок. Спасибо, до свидания.",
    },
    "zh": {
        "greeting": "您好，我是 CareCall 人工智能助理，代表 {name} 致电。请问这里是预约处吗？",
        "hold": "好的，我等您。",
        "check_in": "请问您还在线吗？",
        "goodbye": "那我先挂电话了。谢谢，再见。",
    },
}


def phrase(language: str, key: str, **values) -> str:
    return MESSAGES[language][key].format(**values)


def appointment_readback(profile: dict, candidate: dict, language: str) -> str:
    start = datetime.fromisoformat(candidate["start"]).astimezone(
        ZoneInfo(profile["timezone"])
    )
    end = datetime.fromisoformat(candidate["end"]).astimezone(
        ZoneInfo(profile["timezone"])
    )
    name, provider, location = (
        profile["name"],
        candidate["provider"],
        candidate["location"],
    )
    zone = profile["timezone"]
    if language == "ru":
        months = (
            "января",
            "февраля",
            "марта",
            "апреля",
            "мая",
            "июня",
            "июля",
            "августа",
            "сентября",
            "октября",
            "ноября",
            "декабря",
        )
        zone = (
            "по времени Нью-Йорка"
            if zone == "America/New_York"
            else f"часовой пояс {zone}"
        )
        return f"Подтверждаю: пациент {name}, {start.day} {months[start.month - 1]} {start.year} года, с {start:%H:%M} до {end:%H:%M}, {zone}, врач {provider}, адрес {location}. Приём уже записан в вашей системе?"
    if language == "zh":
        zone = "纽约时间" if zone == "America/New_York" else f"时区 {zone}"
        return f"确认一下：患者是 {name}，预约时间是{start.year}年{start.month}月{start.day}日，{zone}{start:%H:%M}至{end:%H:%M}，医生是 {provider}，地址是 {location}。这个预约已经在您的系统中确认了吗？"
    return f"To confirm, this is for {name}, {start:%A, %B %d, %Y at %I:%M %p} to {end:%I:%M %p %Z}, with {provider} at {location}. Is that appointment now booked?"
