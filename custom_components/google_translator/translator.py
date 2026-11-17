"""Translation with a cache in front of the client, split into planning and doing.

Planning is free of side effects, so the caller can check the whole request (budget, languages,
sizes) before a single character is sent.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from .api import GoogleClient, TranslateOptions, Translation
from .cache import TranslationCache
from .const import CACHE_MAX_TEXT_LENGTH


@dataclass
class TranslationPlan:
    """What a call needs from Google once cached texts are taken out."""

    options: TranslateOptions
    results: list[Translation | None]
    missing: dict[str, list[int]]

    @property
    def pending_texts(self) -> list[str]:
        """The distinct texts Google has to translate."""
        return list(self.missing)

    @property
    def characters(self) -> int:
        """How many characters the pending texts add up to."""
        return sum(len(text) for text in self.missing)


def plan_translation(
    cache: TranslationCache[Translation], texts: Sequence[str], options: TranslateOptions
) -> TranslationPlan:
    """Sort the texts into empty ones, cached ones and the ones still to translate."""
    results: list[Translation | None] = [None] * len(texts)
    missing: dict[str, list[int]] = {}
    for index, text in enumerate(texts):
        if not text.strip():
            results[index] = Translation(text)
        elif (cached := cache.get((text, options))) is not None:
            results[index] = cached
        else:
            missing.setdefault(text, []).append(index)
    return TranslationPlan(options, results, missing)


async def async_run_plan(
    client: GoogleClient,
    cache: TranslationCache[Translation],
    plan: TranslationPlan,
    on_batch_sent: Callable[[int], None] | None = None,
) -> list[Translation]:
    """Translate what the plan is missing and return every result in the order of the request."""
    if plan.missing:
        texts = plan.pending_texts
        translations = await client.async_translate(texts, plan.options, on_batch_sent)
        for text, translation in zip(texts, translations):
            for index in plan.missing[text]:
                plan.results[index] = translation
            if len(text) <= CACHE_MAX_TEXT_LENGTH:
                cache.put((text, plan.options), translation)
    return [item for item in plan.results if item is not None]
