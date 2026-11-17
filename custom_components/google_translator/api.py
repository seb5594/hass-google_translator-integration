"""Lean asynchronous clients for Google Translate.

Two ways in are offered. The *web* client talks to the endpoint behind translate.google.com and
needs no account at all. The *cloud* client uses the official Cloud Translation API (Basic) with
an API key. Both only need the aiohttp session Home Assistant already shares, so the integration
brings no extra dependency and no extra process.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
import logging
from time import monotonic
from typing import Any

import aiohttp

from .const import (
    CLOUD_MAX_REQUEST_CHARACTERS,
    CLOUD_MAX_TEXT_CHARACTERS,
    CLOUD_MAX_TEXTS_PER_REQUEST,
    CLOUD_URL,
    LANGUAGES_CACHE_SECONDS,
    MAX_ATTEMPTS,
    MAX_RETRY_DELAY,
    REQUEST_TIMEOUT,
    WEB_MAX_REQUEST_CHARACTERS,
    WEB_MAX_TEXTS_PER_REQUEST,
    WEB_REQUEST_SPACING,
    WEB_URL,
)

_LOGGER = logging.getLogger(__name__)

RETRYABLE_STATUSES = (429, 500, 502, 503, 504)
# Reasons the Cloud API gives for a request that is refused because of a limit, not a key.
_LIMIT_REASONS = frozenset(
    {"rateLimitExceeded", "userRateLimitExceeded", "dailyLimitExceeded", "quotaExceeded"}
)


class GoogleError(Exception):
    """Base class for everything that can go wrong while talking to Google."""


class GoogleConnectionError(GoogleError):
    """Google could not be reached in time."""


class GoogleAuthError(GoogleError):
    """The API key was rejected."""


class GoogleQuotaError(GoogleError):
    """Google refuses further requests for now: a quota or a rate limit was hit."""


class GoogleRequestError(GoogleError):
    """Google refused the request, for example because of an unsupported language."""


@dataclass(frozen=True)
class TranslateOptions:
    """Everything that shapes a translation besides the text itself."""

    target_lang: str
    source_lang: str | None = None


@dataclass(frozen=True)
class Translation:
    """One translated text."""

    text: str
    detected_source_language: str | None = None


@dataclass(frozen=True)
class Language:
    """A language Google can translate from or to."""

    code: str
    name: str


@dataclass(frozen=True)
class Capabilities:
    """The limits of a connection, so oversized requests are refused before anything is sent."""

    max_text_characters: int
    max_request_characters: int
    max_texts_per_request: int
    billed: bool


def split_into_batches(
    texts: Sequence[str], max_texts: int, max_characters: int
) -> Iterator[list[str]]:
    """Group texts into requests that stay within the count and size limits."""
    batch: list[str] = []
    size = 0
    for text in texts:
        if batch and (len(batch) >= max_texts or size + len(text) > max_characters):
            yield batch
            batch, size = [], 0
        batch.append(text)
        size += len(text)
    if batch:
        yield batch


class GoogleClient:
    """What both clients have in common: retries, error handling and the language list."""

    capabilities: Capabilities
    _spacing = 0.0

    def __init__(self, session: aiohttp.ClientSession, user_agent: str) -> None:
        self._session = session
        self._user_agent = user_agent
        self._languages: tuple[float, list[Language]] | None = None
        self._last_request = 0.0

    async def async_translate(
        self,
        texts: Sequence[str],
        options: TranslateOptions,
        on_batch_sent: Callable[[int], None] | None = None,
    ) -> list[Translation]:
        """Translate texts, keeping their order. Empty texts must be filtered by the caller.

        ``on_batch_sent`` receives the number of characters of every request that Google
        answered, so a failure halfway still leaves an accurate count.
        """
        results: list[Translation] = []
        for batch in split_into_batches(
            texts, self.capabilities.max_texts_per_request, self.capabilities.max_request_characters
        ):
            translations = await self._translate_batch(batch, options)
            if len(translations) != len(batch):
                raise GoogleError("Google returned an unexpected number of translations")
            results.extend(translations)
            if on_batch_sent is not None:
                on_batch_sent(sum(len(text) for text in batch))
        return results

    async def async_get_languages(self, language_type: str = "target") -> list[Language]:
        """List the supported languages (targets and sources are the same); kept for a day."""
        if self._languages and monotonic() - self._languages[0] < LANGUAGES_CACHE_SECONDS:
            return self._languages[1]
        languages = await self._fetch_languages()
        self._languages = (monotonic(), languages)
        return languages

    async def async_check(self) -> None:
        """Prove that translating works; used when an account is set up."""
        await self.async_translate(["Hello"], TranslateOptions(target_lang="de", source_lang="en"))

    async def _translate_batch(
        self, batch: list[str], options: TranslateOptions
    ) -> list[Translation]:
        raise NotImplementedError

    async def _fetch_languages(self) -> list[Language]:
        raise NotImplementedError

    def _error_for(self, status: int, payload: Any, retry_after: str | None) -> GoogleError:
        raise NotImplementedError

    async def _request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        data: Any = None,
        json: Any = None,
    ) -> Any:
        """Send a request, retrying when Google asks to slow down."""
        headers = {"User-Agent": self._user_agent, **(headers or {})}
        timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
        for attempt in range(1, MAX_ATTEMPTS + 1):
            await self._space_requests()
            try:
                async with self._session.request(
                    method, url, headers=headers, params=params, data=data, json=json, timeout=timeout
                ) as response:
                    payload = await _read_payload(response)
                    if response.status < 400:
                        if payload is None:
                            raise GoogleError("Google answered with something other than data")
                        return payload
                    if response.status in RETRYABLE_STATUSES and attempt < MAX_ATTEMPTS:
                        delay = _retry_delay(response.headers.get("Retry-After"), attempt)
                        _LOGGER.debug("Google asked to slow down, retrying in %s s", delay)
                    else:
                        raise self._error_for(
                            response.status, payload, response.headers.get("Retry-After")
                        )
            except asyncio.TimeoutError as err:
                raise GoogleConnectionError("Timed out while talking to Google") from err
            except aiohttp.ClientError as err:
                raise GoogleConnectionError(f"Cannot reach Google: {err}") from err
            await asyncio.sleep(delay)
        raise GoogleQuotaError("Google is overloaded, try again later")  # pragma: no cover

    async def _space_requests(self) -> None:
        """Keep a small gap between requests, which the web endpoint rewards with fewer blocks."""
        if self._spacing:
            wait = self._last_request + self._spacing - monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
        self._last_request = monotonic()


class GoogleWebClient(GoogleClient):
    """The keyless endpoint behind translate.google.com.

    It is not a product with a contract: Google can change or block it, and it limits clients
    that send a lot. That is why requests are small, spaced out and counted.
    """

    capabilities = Capabilities(
        max_text_characters=WEB_MAX_REQUEST_CHARACTERS,
        max_request_characters=WEB_MAX_REQUEST_CHARACTERS,
        max_texts_per_request=WEB_MAX_TEXTS_PER_REQUEST,
        billed=False,
    )
    _spacing = WEB_REQUEST_SPACING

    async def _translate_batch(
        self, batch: list[str], options: TranslateOptions
    ) -> list[Translation]:
        form = [("q", text) for text in batch]
        params = {
            "client": "gtx",
            "format": "text",
            "sl": options.source_lang or "auto",
            "tl": options.target_lang,
        }
        payload = await self._request("POST", f"{WEB_URL}/t", params=params, data=form)
        return [_parse_web_item(item) for item in payload] if isinstance(payload, list) else []

    async def _fetch_languages(self) -> list[Language]:
        payload = await self._request("GET", f"{WEB_URL}/l", params={"client": "gtx", "hl": "en"})
        try:
            return [Language(code, name) for code, name in payload["tl"].items()]
        except (KeyError, TypeError, AttributeError) as err:
            raise GoogleError("Google returned an unexpected language list") from err

    def _error_for(self, status: int, payload: Any, retry_after: str | None) -> GoogleError:
        if status == 429 or status == 503:
            return GoogleQuotaError(
                "Google is limiting requests from this connection for now. Wait a while, or set "
                "the integration up with an API key"
            )
        if status < 500:
            return GoogleRequestError(f"Google rejected the request (HTTP {status})")
        return GoogleError(f"Google answered with HTTP {status}")


def _parse_web_item(item: Any) -> Translation:
    """The endpoint answers with plain texts, or with ``[text, detected_language]`` pairs."""
    if isinstance(item, str):
        return Translation(item)
    if isinstance(item, list) and item and isinstance(item[0], str):
        detected = item[1] if len(item) > 1 and isinstance(item[1], str) else None
        return Translation(item[0], detected)
    raise GoogleError("Google returned an unexpected translation")


class GoogleCloudClient(GoogleClient):
    """The official Cloud Translation API (Basic, v2) with an API key."""

    capabilities = Capabilities(
        max_text_characters=CLOUD_MAX_TEXT_CHARACTERS,
        max_request_characters=CLOUD_MAX_REQUEST_CHARACTERS,
        max_texts_per_request=CLOUD_MAX_TEXTS_PER_REQUEST,
        billed=True,
    )

    def __init__(self, session: aiohttp.ClientSession, api_key: str, user_agent: str) -> None:
        super().__init__(session, user_agent)
        self._api_key = api_key

    @property
    def _headers(self) -> dict[str, str]:
        # A header keeps the key out of URLs, which end up in logs.
        return {"X-goog-api-key": self._api_key}

    async def _translate_batch(
        self, batch: list[str], options: TranslateOptions
    ) -> list[Translation]:
        body: dict[str, Any] = {"q": batch, "target": options.target_lang, "format": "text"}
        if options.source_lang:
            body["source"] = options.source_lang
        payload = await self._request("POST", CLOUD_URL, headers=self._headers, json=body)
        try:
            items = payload["data"]["translations"]
            return [
                Translation(item["translatedText"], item.get("detectedSourceLanguage"))
                for item in items
            ]
        except (KeyError, TypeError) as err:
            raise GoogleError("Google returned an unexpected translation") from err

    async def _fetch_languages(self) -> list[Language]:
        payload = await self._request(
            "GET", f"{CLOUD_URL}/languages", headers=self._headers, params={"target": "en"}
        )
        try:
            return [Language(item["language"], item.get("name", item["language"])) for item in payload["data"]["languages"]]
        except (KeyError, TypeError) as err:
            raise GoogleError("Google returned an unexpected language list") from err

    def _error_for(self, status: int, payload: Any, retry_after: str | None) -> GoogleError:
        message, reason = _cloud_error(payload)
        if reason in _LIMIT_REASONS or status == 429:
            return GoogleQuotaError(message or "The Google quota or rate limit was hit")
        if status in (401, 403) or reason == "API_KEY_INVALID" or "API key" in message:
            return GoogleAuthError(message or "The API key was rejected")
        if status < 500:
            return GoogleRequestError(message or f"Google rejected the request (HTTP {status})")
        return GoogleError(message or f"Google answered with HTTP {status}")


def _cloud_error(payload: Any) -> tuple[str, str]:
    """The message and the machine-readable reason of a Cloud API error answer."""
    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        return "", ""
    reasons = [
        item.get("reason", "")
        for item in (error.get("errors") or []) + (error.get("details") or [])
        if isinstance(item, dict)
    ]
    # ``API_KEY_INVALID`` is more telling than the generic ``badRequest`` that comes first.
    specific = next((reason for reason in reasons if reason and reason != "badRequest"), "")
    return str(error.get("message", ""))[:300], specific or (reasons[0] if reasons else "")


async def _read_payload(response: aiohttp.ClientResponse) -> Any:
    """The JSON body of an answer; error pages and empty bodies give None."""
    try:
        return await response.json(content_type=None)
    except (aiohttp.ClientError, ValueError):
        return None


def _retry_delay(retry_after: str | None, attempt: int) -> float:
    """Honour the Retry-After header, otherwise back off 1, 2, 4 ... seconds."""
    try:
        return min(float(retry_after), MAX_RETRY_DELAY) if retry_after else 2 ** (attempt - 1)
    except ValueError:
        return 2 ** (attempt - 1)
