"""Checks that run before anything is sent to Google.

A request that cannot be translated completely is refused up front with a clear message,
instead of being sent, counted and then failing halfway. Every message ends with the sentence
"Nothing was sent to Google." because that is the promise these checks keep.

This module deliberately imports nothing from Home Assistant so it can be tested alone.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable
import difflib

NOTHING_SENT = "Nothing was sent to Google."


class PreflightError(ValueError):
    """The request cannot be fulfilled completely; raised before anything is sent."""


def check_budget(needed: int, remaining: int | None, period_end: str | None = None) -> None:
    """Refuse when the monthly character budget cannot cover the whole request."""
    if remaining is None or needed <= remaining:
        return
    until = f" until the count starts again on {period_end[:10]}" if period_end else ""
    raise PreflightError(
        f"The monthly character budget would be exceeded: this request needs about {needed:,} "
        f"characters but only {remaining:,} are left{until}. Raise the limit in the options or "
        f"wait for the next month. {NOTHING_SENT}"
    )


def check_language(code: str, supported: Collection[str] | None, role: str) -> None:
    """Refuse a language Google does not offer; ``role`` is ``target`` or ``source``.

    Google's keyless endpoint answers an unknown target with the unchanged text, so this check
    is what keeps a typo from passing as a translation.
    """
    if not supported or code in supported:
        return
    direction = "into" if role == "target" else "from"
    close = difflib.get_close_matches(code, supported, n=3, cutoff=0.5)
    hint = f" Did you mean {', '.join(close)}?" if close else ""
    raise PreflightError(
        f"Google cannot translate {direction} '{code}'.{hint} "
        f"The service get_languages lists what is available. {NOTHING_SENT}"
    )


def check_text_sizes(texts: Iterable[str], max_characters: int) -> None:
    """Refuse a single text that is too long for one request, however it is split."""
    for text in texts:
        if len(text) > max_characters:
            raise PreflightError(
                f"A text of {len(text):,} characters is longer than the {max_characters:,} "
                f"characters Google accepts per text on this connection. Split it into smaller "
                f"texts. {NOTHING_SENT}"
            )
