"""Language codes of Google Translate and the mapping from Home Assistant's own codes.

This module deliberately imports nothing from Home Assistant so it can be tested alone.
Google adds languages from time to time and the list is read from the service, so the tables
below only drive the drop-down menus and the spelling of codes that need a hint.
"""

from __future__ import annotations

from collections.abc import Collection

FALLBACK_TARGET_LANGUAGE = "en"

# Languages offered in the setup drop-down; any other code Google reports is accepted as well.
COMMON_LANGUAGES: dict[str, str] = {
    "ar": "Arabic",
    "bg": "Bulgarian",
    "cs": "Czech",
    "da": "Danish",
    "de": "German",
    "el": "Greek",
    "en": "English",
    "es": "Spanish",
    "et": "Estonian",
    "fi": "Finnish",
    "fr": "French",
    "iw": "Hebrew",
    "hi": "Hindi",
    "hr": "Croatian",
    "hu": "Hungarian",
    "id": "Indonesian",
    "it": "Italian",
    "ja": "Japanese",
    "ko": "Korean",
    "lt": "Lithuanian",
    "lv": "Latvian",
    "nl": "Dutch",
    "no": "Norwegian",
    "pl": "Polish",
    "pt": "Portuguese (Brazil)",
    "pt-PT": "Portuguese (Portugal)",
    "ro": "Romanian",
    "ru": "Russian",
    "sk": "Slovak",
    "sl": "Slovenian",
    "sr": "Serbian",
    "sv": "Swedish",
    "th": "Thai",
    "tr": "Turkish",
    "uk": "Ukrainian",
    "vi": "Vietnamese",
    "zh-CN": "Chinese (Simplified)",
    "zh-TW": "Chinese (Traditional)",
}

# Spellings used elsewhere (Home Assistant, DeepL, ISO 639) and the code Google lists for them.
_ALIASES = {
    "he": "iw",
    "nb": "no",
    "nn": "no",
    "zh": "zh-CN",
    "zh-hans": "zh-CN",
    "zh-hant": "zh-TW",
    "zh-sg": "zh-CN",
    "zh-hk": "zh-TW",
    "pt-br": "pt",
    "jv": "jw",
    "fil": "tl",
}


def _clean(code: str) -> str:
    return code.strip().replace("_", "-")


def normalize_language(code: str, supported: Collection[str] | None = None) -> str:
    """Return the spelling Google uses for a code, e.g. ``DE`` -> ``de`` or ``zh_hans`` -> ``zh-CN``.

    With the list of supported codes the match is made against it, falling back from a region
    (``en-US``) to its language (``en``); this keeps spellings Google adds later working. A code
    that matches nothing comes back tidied up but otherwise as typed, for the preflight check to
    refuse with a helpful message.
    """
    lowered = _clean(code).lower()
    base = lowered.partition("-")[0]
    if not supported:
        return _ALIASES.get(lowered) or _canonical_case(lowered)
    by_lower = {item.lower(): item for item in supported}
    for candidate in (lowered, _ALIASES.get(lowered), base, _ALIASES.get(base)):
        if candidate and candidate.lower() in by_lower:
            return by_lower[candidate.lower()]
    return _canonical_case(lowered)


def _canonical_case(lowered: str) -> str:
    """Language in lower case, region in upper case: ``pt-pt`` -> ``pt-PT``."""
    base, _, region = lowered.partition("-")
    return f"{base}-{region.upper()}" if len(region) == 2 else lowered


def target_from_home_assistant_language(language: str | None) -> str:
    """The Google code for a Home Assistant language such as ``de`` or ``pt-BR``."""
    if not language:
        return FALLBACK_TARGET_LANGUAGE
    cleaned = _clean(language).lower()
    if cleaned in _ALIASES:
        return _ALIASES[cleaned]
    if cleaned in {code.lower() for code in COMMON_LANGUAGES}:
        return normalize_language(cleaned)
    base = cleaned.partition("-")[0]
    if base in _ALIASES:
        return _ALIASES[base]
    return base if base in COMMON_LANGUAGES else FALLBACK_TARGET_LANGUAGE


def source_language(code: str, supported: Collection[str] | None = None) -> str:
    """A source language; Google detects the region itself, so only Chinese keeps its script."""
    normalized = normalize_language(code, supported)
    if normalized in ("zh-CN", "zh-TW"):
        return normalized
    return normalized.partition("-")[0]
