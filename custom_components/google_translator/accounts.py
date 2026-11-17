"""Identity helpers for accounts, shared by the config flow and the YAML import."""

from __future__ import annotations

import hashlib

from .const import BACKEND_CLOUD, BACKEND_WEB


def account_unique_id(backend: str, api_key: str | None = None) -> str:
    """Identify an account without keeping the key itself in the registry.

    There is only ever one keyless web account; Cloud accounts are told apart by their key.
    """
    if backend == BACKEND_WEB or not api_key:
        return BACKEND_WEB
    return hashlib.sha256(api_key.encode()).hexdigest()[:16]


def account_title(backend: str) -> str:
    """The name shown in the UI."""
    return "Google Translate" if backend == BACKEND_WEB else "Google Cloud Translation"
