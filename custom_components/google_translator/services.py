"""Services of the Google Translator integration.

Every service can hand its result back (``response_variable`` in automations and scripts,
``return_response`` for other integrations), which is what makes them usable as a translation
backend by anything else running in Home Assistant. They answer in the same shape as the
services of the DeepL Translator integration, so callers can use either one.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import wraps
from pathlib import Path
from typing import Any

import voluptuous as vol
import yaml

from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, Unauthorized, UnknownUser
from homeassistant.helpers import config_validation as cv

try:
    from homeassistant.exceptions import ServiceValidationError
except ImportError:  # Home Assistant older than 2023.12
    ServiceValidationError = HomeAssistantError

from . import placeholders, preflight, structured
from .api import (
    GoogleAuthError,
    GoogleError,
    GoogleRequestError,
    Language,
    TranslateOptions,
    Translation,
)
from .cache import TranslationCache
from .const import (
    ATTR_CONFIG_ENTRY_ID,
    ATTR_DATA,
    ATTR_DRY_RUN,
    ATTR_FORMAT,
    ATTR_IGNORE_KEYS,
    ATTR_INPUT_FILE,
    ATTR_LANGUAGE_TYPE,
    ATTR_ONLY_KEYS,
    ATTR_OUTPUT_FILE,
    ATTR_OVERWRITE,
    ATTR_PROTECT_PLACEHOLDERS,
    ATTR_REFRESH,
    ATTR_SKIP_TECHNICAL_VALUES,
    ATTR_SOURCE_LANGUAGE,
    ATTR_TARGET_LANGUAGE,
    ATTR_TEXT,
    DOMAIN,
    LANGUAGE_TYPES,
    MAX_DOCUMENT_BYTES,
    SERVICE_GET_LANGUAGES,
    SERVICE_GET_USAGE,
    SERVICE_TRANSLATE_STRUCTURE,
    SERVICE_TRANSLATE_TEXT,
    STRUCTURE_FORMATS,
    STRUCTURE_SUFFIXES,
)
from .data import GoogleRuntimeData
from .languages import COMMON_LANGUAGES, normalize_language, source_language
from .translator import async_run_plan, plan_translation

# The only existing files a translation may replace.
OVERWRITABLE_SUFFIXES = frozenset({".json"})

_ENTRY_FIELD = {vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string}

TRANSLATE_TEXT_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_TEXT): vol.All(cv.ensure_list, [cv.string], vol.Length(min=1)),
        vol.Optional(ATTR_TARGET_LANGUAGE): cv.string,
        vol.Optional(ATTR_SOURCE_LANGUAGE): cv.string,
        **_ENTRY_FIELD,
    }
)

TRANSLATE_STRUCTURE_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_DATA): vol.Any(dict, list),
        vol.Optional(ATTR_INPUT_FILE): cv.string,
        vol.Optional(ATTR_OUTPUT_FILE): cv.string,
        vol.Optional(ATTR_FORMAT, default="auto"): vol.In(STRUCTURE_FORMATS),
        vol.Optional(ATTR_OVERWRITE, default=False): cv.boolean,
        vol.Optional(ATTR_ONLY_KEYS, default=list): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(ATTR_IGNORE_KEYS, default=list): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(ATTR_SKIP_TECHNICAL_VALUES, default=True): cv.boolean,
        vol.Optional(ATTR_PROTECT_PLACEHOLDERS, default=True): cv.boolean,
        vol.Optional(ATTR_DRY_RUN, default=False): cv.boolean,
        vol.Optional(ATTR_TARGET_LANGUAGE): cv.string,
        vol.Optional(ATTR_SOURCE_LANGUAGE): cv.string,
        **_ENTRY_FIELD,
    }
)

GET_LANGUAGES_SCHEMA = vol.Schema(
    {vol.Optional(ATTR_LANGUAGE_TYPE, default="target"): vol.In(LANGUAGE_TYPES), **_ENTRY_FIELD}
)

GET_USAGE_SCHEMA = vol.Schema({vol.Optional(ATTR_REFRESH, default=False): cv.boolean, **_ENTRY_FIELD})


class GoogleServices:
    """Implements the services on top of the loaded config entries."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass

    def register(self) -> None:
        """Make the services available; called once for the whole integration."""
        for name, handler, schema, admin_only in (
            (SERVICE_TRANSLATE_TEXT, self.translate_text, TRANSLATE_TEXT_SCHEMA, False),
            (SERVICE_TRANSLATE_STRUCTURE, self.translate_structure, TRANSLATE_STRUCTURE_SCHEMA, True),
            (SERVICE_GET_LANGUAGES, self.get_languages, GET_LANGUAGES_SCHEMA, False),
            (SERVICE_GET_USAGE, self.get_usage, GET_USAGE_SCHEMA, False),
        ):
            self._hass.services.async_register(
                DOMAIN,
                name,
                self._require_admin(handler) if admin_only else handler,
                schema=schema,
                supports_response=SupportsResponse.OPTIONAL,
            )

    def _require_admin(
        self, handler: Callable[[ServiceCall], Awaitable[dict[str, Any]]]
    ) -> Callable[[ServiceCall], Awaitable[dict[str, Any]]]:
        """Let only administrators call a service that reads or writes files.

        ``async_register_admin_service`` does this too, but in the oldest supported Home Assistant
        it drops the response of the service, which the callers of these services need. Calls
        without a user, such as automations and scripts, are trusted like they are there.
        """

        @wraps(handler)
        async def admin_handler(call: ServiceCall) -> dict[str, Any]:
            if call.context.user_id:
                user = await self._hass.auth.async_get_user(call.context.user_id)
                if user is None:
                    raise UnknownUser(context=call.context)
                if not user.is_admin:
                    raise Unauthorized(context=call.context)
            return await handler(call)

        return admin_handler

    async def translate_text(self, call: ServiceCall) -> dict[str, Any]:
        """Translate one or more texts."""
        runtime = self._runtime(call.data.get(ATTR_CONFIG_ENTRY_ID))
        options = await self._options(runtime, call.data)
        translations = await self._translate(runtime, call.data[ATTR_TEXT], options)
        return {
            "text": translations[0].text,
            "translations": [
                {"text": item.text, "detected_source_language": item.detected_source_language}
                for item in translations
            ],
            "target_language": options.target_lang,
        }

    async def translate_structure(self, call: ServiceCall) -> dict[str, Any]:
        """Translate only the text values of structured data, leaving its shape untouched.

        The data is either passed inline or read from a JSON or YAML file. Files keep their exact
        layout (indentation, key order, quoting, comments); inline data comes back as a copy.
        """
        runtime = self._runtime(call.data.get(ATTR_CONFIG_ENTRY_ID))
        options = await self._options(runtime, call.data)
        rules = structured.Rules(
            only_keys=frozenset(call.data[ATTR_ONLY_KEYS]),
            ignore_keys=frozenset(call.data[ATTR_IGNORE_KEYS]),
            skip_technical_values=call.data[ATTR_SKIP_TECHNICAL_VALUES],
        )
        inline = ATTR_DATA in call.data
        if inline == (ATTR_INPUT_FILE in call.data):
            raise ServiceValidationError(
                f"Give either '{ATTR_DATA}' or '{ATTR_INPUT_FILE}', not both and not neither"
            )
        dry_run = call.data[ATTR_DRY_RUN]

        document: _Document | None = None
        output_file: Path | None = None
        if inline:
            scan = structured.scan_object(call.data[ATTR_DATA], rules)
        else:
            input_file = Path(self._hass.config.path(call.data[ATTR_INPUT_FILE]))
            fmt = _structure_format(call.data[ATTR_FORMAT], input_file)
            if not dry_run:
                output_file = _output_path(
                    self._hass, input_file, options.target_lang, call.data.get(ATTR_OUTPUT_FILE)
                )
            document = await self._hass.async_add_executor_job(
                _read_structure, self._hass, input_file, output_file, call.data[ATTR_OVERWRITE], fmt, rules
            )
            scan = document.scan

        if dry_run:
            return {
                "dry_run": True,
                "strings": [
                    {"path": structured.render_path(slot.path), "text": slot.text} for slot in scan.slots
                ],
                "characters": sum(len(slot.text) for slot in scan.slots),
                "skipped_strings": scan.skipped,
                "characters_remaining": runtime.usage.usage.characters_remaining,
            }

        translations = await self._translate_slots(
            runtime, scan.slots, options, call.data[ATTR_PROTECT_PLACEHOLDERS]
        )
        result: dict[str, Any] = {
            "target_language": options.target_lang,
            "translated_strings": len(scan.slots),
            "skipped_strings": scan.skipped,
        }
        if document is None:
            by_path = {slot.path: text for slot, text in zip(scan.slots, translations)}
            result["data"] = structured.rebuild_object(call.data[ATTR_DATA], by_path)
        else:
            await self._hass.async_add_executor_job(
                _write_structure, output_file, document, translations
            )
            result["output_file"] = str(output_file)
        return result

    async def _translate_slots(
        self,
        runtime: GoogleRuntimeData,
        slots: Sequence[structured.Slot],
        options: TranslateOptions,
        protect_placeholders: bool,
    ) -> list[str]:
        """Translate the texts of the slots, shielding placeholders such as ``{name}`` if asked to."""
        texts = [slot.text for slot in slots]
        if not texts:
            return []
        if not (protect_placeholders and any(placeholders.contains_placeholder(t) for t in texts)):
            return [item.text for item in await self._translate(runtime, texts, options)]

        shield = placeholders.Shield()
        protected = [shield.protect(text) for text in texts]
        # Protected texts carry a one-time token, so caching them would only fill the cache.
        translations = await self._translate(
            runtime, [text for text, _ in protected], options, TranslationCache(0)
        )
        try:
            return [
                shield.restore(item.text, originals)
                for item, (_, originals) in zip(translations, protected)
            ]
        except placeholders.PlaceholderError as err:
            raise HomeAssistantError(
                f"Google: {err}. Set '{ATTR_PROTECT_PLACEHOLDERS}' to false to translate the "
                "texts as they are, or translate them without these placeholders."
            ) from err

    async def _translate(
        self,
        runtime: GoogleRuntimeData,
        texts: Sequence[str],
        options: TranslateOptions,
        cache: TranslationCache[Translation] | None = None,
    ) -> list[Translation]:
        """Check the whole request, then translate it: either everything is sent, or nothing."""
        cache = runtime.cache if cache is None else cache
        plan = plan_translation(cache, texts, options)
        if plan.missing:
            await self._preflight_request(runtime, options, plan.pending_texts, plan.characters)
        try:
            return await async_run_plan(runtime.client, cache, plan, runtime.usage.add)
        except GoogleError as err:
            raise self._failure(runtime, err) from err

    async def _preflight_request(
        self,
        runtime: GoogleRuntimeData,
        options: TranslateOptions,
        texts: Sequence[str],
        characters: int,
    ) -> None:
        """Languages, sizes and the monthly budget; raises before anything is sent."""
        try:
            supported = {item.code for item in await self._languages(runtime)}
            preflight.check_language(options.target_lang, supported, "target")
            if options.source_lang:
                preflight.check_language(options.source_lang, supported, "source")
            preflight.check_text_sizes(texts, runtime.client.capabilities.max_text_characters)
            usage = runtime.usage.usage
            preflight.check_budget(characters, usage.characters_remaining, usage.period_end)
        except preflight.PreflightError as err:
            raise ServiceValidationError(str(err)) from err

    async def _languages(self, runtime: GoogleRuntimeData) -> list[Language]:
        """What Google offers; if that cannot be read, the common languages stand in."""
        try:
            return await runtime.client.async_get_languages()
        except GoogleError:
            return [Language(code, name) for code, name in COMMON_LANGUAGES.items()]

    def _failure(self, runtime: GoogleRuntimeData, err: GoogleError) -> HomeAssistantError:
        """Turn a Google error into a service error; a rejected key also asks for a new one."""
        if isinstance(err, GoogleAuthError):
            runtime.entry.async_start_reauth(self._hass)
        return _as_home_assistant_error(err)

    async def get_usage(self, call: ServiceCall) -> dict[str, Any]:
        """The characters counted this month and what is left of the budget.

        Google offers no usage API, so these are the figures of this integration. ``estimated``
        says so, and callers should show them as such.
        """
        runtime = self._runtime(call.data.get(ATTR_CONFIG_ENTRY_ID))
        if call.data[ATTR_REFRESH]:
            runtime.usage.refresh()
        usage = runtime.usage.usage
        return {
            "available": True,
            "estimated": True,
            "character_count": usage.character_count,
            "character_limit": usage.character_limit,
            "characters_remaining": usage.characters_remaining,
            "unlimited": usage.is_unlimited,
            "end_time": usage.period_end,
            "refreshed": call.data[ATTR_REFRESH],
        }

    async def get_languages(self, call: ServiceCall) -> dict[str, Any]:
        """List the languages Google supports."""
        runtime = self._runtime(call.data.get(ATTR_CONFIG_ENTRY_ID))
        try:
            languages = await runtime.client.async_get_languages(call.data[ATTR_LANGUAGE_TYPE])
        except GoogleError as err:
            raise self._failure(runtime, err) from err
        return {
            "languages": [
                {"code": language.code, "name": language.name, "supports_formality": None}
                for language in languages
            ]
        }

    def _runtime(self, entry_id: str | None) -> GoogleRuntimeData:
        """The account a call is meant for: the named one, or the only one there is."""
        loaded: Mapping[str, GoogleRuntimeData] = self._hass.data.get(DOMAIN, {})
        if entry_id:
            if entry_id not in loaded:
                raise ServiceValidationError(f"The Google account {entry_id} is not loaded")
            return loaded[entry_id]
        if not loaded:
            raise ServiceValidationError("No Google account is set up")
        if len(loaded) > 1:
            raise ServiceValidationError(
                f"Several Google accounts are set up, choose one with '{ATTR_CONFIG_ENTRY_ID}'"
            )
        return next(iter(loaded.values()))

    async def _options(self, runtime: GoogleRuntimeData, data: Mapping[str, Any]) -> TranslateOptions:
        """Turn the service fields into request options, filling in the account's default language."""
        supported = {item.code for item in await self._languages(runtime)}
        source = data.get(ATTR_SOURCE_LANGUAGE)
        return TranslateOptions(
            target_lang=normalize_language(
                data.get(ATTR_TARGET_LANGUAGE) or runtime.default_target_language, supported
            ),
            source_lang=source_language(source, supported) if source else None,
        )


def _as_home_assistant_error(err: GoogleError) -> HomeAssistantError:
    """A refused request is the caller's mistake, everything else a failure of the service."""
    if isinstance(err, GoogleRequestError):
        return ServiceValidationError(f"Google: {err}")
    return HomeAssistantError(f"Google: {err}")


def _output_path(
    hass: HomeAssistant, input_file: Path, target_language: str, requested: str | None
) -> Path:
    """Default to ``strings.json`` -> ``strings.de.json`` next to the original."""
    if requested:
        return Path(hass.config.path(requested))
    return input_file.with_name(f"{input_file.stem}.{target_language.lower()}{input_file.suffix}")


def _read_input(
    hass: HomeAssistant, input_file: Path, output_file: Path | None, overwrite: bool
) -> bytes:
    """Check the paths and read the source; runs in the executor (blocking file access)."""
    for path in (input_file, output_file):
        if path is not None and not hass.config.is_allowed_path(str(path)):
            raise ServiceValidationError(
                f"{path} is not allowed, add its folder to allowlist_external_dirs "
                "or use a path inside the configuration folder"
            )
    if not input_file.is_file():
        raise ServiceValidationError(f"{input_file} does not exist or is not a file")
    if output_file is not None:
        if input_file.resolve() == output_file.resolve():
            raise ServiceValidationError("The output file must differ from the input file")
        if output_file.exists():
            # YAML files hold the configuration, automations and secrets of Home Assistant, so a
            # translation may create them but never replace one. Only JSON can be overwritten.
            if output_file.suffix.lower() not in OVERWRITABLE_SUFFIXES:
                raise ServiceValidationError(
                    f"{output_file} already exists and only JSON files can be replaced. "
                    "Choose another output file"
                )
            if not overwrite:
                raise ServiceValidationError(
                    f"{output_file} already exists, set '{ATTR_OVERWRITE}' to replace it"
                )
    if input_file.stat().st_size > MAX_DOCUMENT_BYTES:
        raise ServiceValidationError(
            f"{input_file.name} is larger than {MAX_DOCUMENT_BYTES // (1024 * 1024)} MiB"
        )
    return input_file.read_bytes()


def _write_output(output_file: Path, content: bytes) -> None:
    """Store the result; a half written file never replaces a good one."""
    output_file.parent.mkdir(parents=True, exist_ok=True)
    partial = output_file.with_name(output_file.name + ".part")
    partial.write_bytes(content)
    partial.replace(output_file)


@dataclass(frozen=True)
class _Document:
    """A structured file as it was read: its text, whether it had a BOM, and what to translate."""

    text: str
    has_bom: bool
    fmt: str
    scan: structured.Scan


def _structure_format(requested: str, input_file: Path) -> str:
    """Use the requested format, or guess it from the file extension."""
    if requested != "auto":
        return requested
    if fmt := STRUCTURE_SUFFIXES.get(input_file.suffix.lower()):
        return fmt
    raise ServiceValidationError(
        f"Cannot tell the format of {input_file.name}, set '{ATTR_FORMAT}' to json or yaml"
    )


def _read_structure(
    hass: HomeAssistant,
    input_file: Path,
    output_file: Path | None,
    overwrite: bool,
    fmt: str,
    rules: structured.Rules,
) -> _Document:
    """Read and scan a structured file; runs in the executor."""
    raw = _read_input(hass, input_file, output_file, overwrite)
    try:
        text = raw.decode("utf-8-sig")
        scan = structured.scan_text(text, fmt, rules)
    except (UnicodeDecodeError, ValueError, yaml.YAMLError) as err:
        raise ServiceValidationError(f"{input_file.name} is not valid {fmt.upper()}: {err}") from err
    return _Document(text, raw.startswith(b"\xef\xbb\xbf"), fmt, scan)


def _write_structure(output_file: Path, document: _Document, translations: Sequence[str]) -> None:
    """Splice the translations into the original text and store it; runs in the executor."""
    text = structured.apply_translations(document.text, document.scan, translations, document.fmt)
    _write_output(output_file, (("﻿" if document.has_bom else "") + text).encode("utf-8"))
