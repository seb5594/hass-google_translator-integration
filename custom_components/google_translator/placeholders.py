"""Keep placeholders such as ``{name}`` or ``{{ states('x') }}`` out of the translation.

Google has no way to mark text as untouchable in plain-text mode, so every placeholder is swapped
for a short token made of letters and digits, which Google leaves alone, and swapped back in the
answer. A token that did not come back exactly once means the translation cannot be trusted, and
the caller gets an error instead of a silently broken text.

This module deliberately imports nothing from Home Assistant so it can be tested alone.
"""

from __future__ import annotations

from collections import Counter
import re
from uuid import uuid4

_PLACEHOLDER = re.compile(
    r"""
    \{\{.*?\}\}                      # Jinja expression
  | \{%.*?%\}                        # Jinja statement
  | \{\#.*?\#\}                      # Jinja comment
  | \$\{[^}]*\}                      # ${name}
  | \{\w[\w.\[\]'"-]*\}              # {name}, {0}, {device.name}
  | %\([A-Za-z_]\w*\)[sdif]          # %(name)s
  | %[sdif]                          # %s
    """,
    re.X | re.S,
)


class PlaceholderError(ValueError):
    """A translation lost or changed a protected placeholder."""


def contains_placeholder(text: str) -> bool:
    """Whether the text has anything worth protecting."""
    return _PLACEHOLDER.search(text) is not None


class Shield:
    """Protects the placeholders of one batch of texts; use a new one for every request."""

    def __init__(self) -> None:
        self._prefix = f"PH{uuid4().hex[:10]}X"
        self._token = re.compile(re.escape(self._prefix) + r"\d+X")

    def protect(self, text: str) -> tuple[str, dict[str, str]]:
        """The text with every placeholder replaced by a token, and what each token stands for."""
        originals: dict[str, str] = {}

        def swap(match: re.Match[str]) -> str:
            token = f"{self._prefix}{len(originals)}X"
            originals[token] = match.group()
            return token

        return _PLACEHOLDER.sub(swap, text), originals

    def restore(self, translated: str, originals: dict[str, str]) -> str:
        """Put the placeholders back; every token must be present exactly once."""
        if Counter(self._token.findall(translated)) != Counter(originals.keys()):
            raise PlaceholderError("The translation changed or lost a placeholder")
        return self._token.sub(lambda match: originals[match.group()], translated)
