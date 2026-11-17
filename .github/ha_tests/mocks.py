"""Shared helpers for the tests against a real Home Assistant."""

from __future__ import annotations

from collections.abc import Callable

from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMockResponse

WEB = "https://translate.googleapis.com/translate_a"
CLOUD = "https://translation.googleapis.com/language/translate/v2"

WEB_LANGUAGES = {"sl": {"auto": "Detect language"}, "tl": {"de": "German", "en": "English", "fr": "French", "zh-CN": "Chinese (Simplified)", "iw": "Hebrew"}}
CLOUD_LANGUAGES = {"data": {"languages": [{"language": code, "name": name} for code, name in WEB_LANGUAGES["tl"].items()]}}


def mock_web(mock, translate: Callable[[str], str] = lambda text: f"DE {text}"):
    """Answer like the keyless endpoint: a list of translated texts."""

    async def answer(method, url, data):
        return AiohttpClientMockResponse(method, url, json=[translate(text) for key, text in data if key == "q"])

    mock.get(f"{WEB}/l", json=WEB_LANGUAGES)
    mock.post(f"{WEB}/t", side_effect=answer)


def mock_cloud(mock, translate: Callable[[str], str] = lambda text: f"DE {text}"):
    """Answer like the Cloud Translation API."""

    async def answer(method, url, data):
        return AiohttpClientMockResponse(
            method,
            url,
            json={"data": {"translations": [{"translatedText": translate(text), "detectedSourceLanguage": "en"} for text in data["q"]]}},
        )

    mock.get(f"{CLOUD}/languages", json=CLOUD_LANGUAGES)
    mock.post(CLOUD, side_effect=answer)


def translate_calls(mock, kind: str = "web"):
    """The requests that asked for translations (not the language lists)."""
    marker = f"{WEB}/t" if kind == "web" else CLOUD
    return [call for call in mock.mock_calls if call[0].lower() == "post" and str(call[1]).startswith(marker)]
