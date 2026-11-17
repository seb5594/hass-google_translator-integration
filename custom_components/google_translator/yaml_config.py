"""The optional account in ``configuration.yaml``.

A bare ``google_translator:`` sets up the keyless web account; adding an ``api_key`` sets up the
Cloud Translation account instead. YAML only ever describes one account. It is imported into a
normal config entry, so the account shows up in the UI, keeps its sensors and can be removed there.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from .accounts import account_title, account_unique_id
from .const import (
    BACKEND_CLOUD,
    BACKEND_WEB,
    CLOUD_FREE_MONTHLY_CHARACTERS,
    CONF_BACKEND,
    CONF_CACHE_SIZE,
    CONF_DEFAULT_TARGET_LANGUAGE,
    CONF_DISCOVER_TRANSLATOR,
    CONF_MONTHLY_CHARACTER_LIMIT,
    CONF_YAML_MANAGED,
    DOMAIN,
    MAX_CACHE_SIZE,
    MAX_MONTHLY_CHARACTER_LIMIT,
)
from .languages import normalize_language

_ACCOUNT_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_API_KEY): vol.All(cv.string, str.strip, vol.Length(min=1)),
        vol.Optional(CONF_DEFAULT_TARGET_LANGUAGE): vol.All(cv.string, normalize_language),
        vol.Optional(CONF_MONTHLY_CHARACTER_LIMIT): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=MAX_MONTHLY_CHARACTER_LIMIT)
        ),
        vol.Optional(CONF_CACHE_SIZE): vol.All(vol.Coerce(int), vol.Range(min=0, max=MAX_CACHE_SIZE)),
        vol.Optional(CONF_DISCOVER_TRANSLATOR): cv.boolean,
    }
)

# ``google_translator:`` on its own is YAML for "None"; treat it as an empty block.
YAML_ACCOUNT_SCHEMA = vol.All(vol.Any(None, dict), lambda value: value or {}, _ACCOUNT_SCHEMA)

# Other integrations' keys share configuration.yaml, so unknown top-level keys must pass.
CONFIG_SCHEMA = vol.Schema({vol.Optional(DOMAIN): YAML_ACCOUNT_SCHEMA}, extra=vol.ALLOW_EXTRA)


class YamlConflict(Exception):
    """The YAML account is the same as an account that YAML does not manage."""


def backend_of(account: dict[str, Any]) -> str:
    """An API key means the Cloud API, no key means the keyless web endpoint."""
    return BACKEND_CLOUD if account.get(CONF_API_KEY) else BACKEND_WEB


def default_monthly_limit(backend: str) -> int:
    """The Cloud API is free up to a monthly allowance, so that is its budget; the web has none."""
    return CLOUD_FREE_MONTHLY_CHARACTERS if backend == BACKEND_CLOUD else 0


def entry_data(account: dict[str, Any]) -> dict[str, Any]:
    """The config entry data that belongs to a validated YAML account."""
    data: dict[str, Any] = {CONF_BACKEND: backend_of(account), CONF_YAML_MANAGED: True}
    if api_key := account.get(CONF_API_KEY):
        data[CONF_API_KEY] = api_key
    return data


def entry_options(account: dict[str, Any]) -> dict[str, Any]:
    """The options a YAML account sets; whatever it leaves out is not touched."""
    return {key: value for key, value in account.items() if key != CONF_API_KEY}


def _find_accounts(
    entries: list[ConfigEntry], unique_id: str
) -> tuple[ConfigEntry | None, ConfigEntry | None]:
    """The account YAML manages, and the account that already has this identity."""
    managed = next(
        (e for e in entries if e.source == SOURCE_IMPORT or e.data.get(CONF_YAML_MANAGED)), None
    )
    matching = next((e for e in entries if e.unique_id == unique_id), None)
    return managed, matching


def apply_to_existing_account(hass: HomeAssistant, account: dict[str, Any]) -> bool:
    """Write the YAML values into the account they belong to; False if there is none yet.

    This is synchronous on purpose: during startup it runs before any account is set up, so the
    account starts with the new values and no reload is needed. A loaded account is reloaded by
    its own update listener.
    """
    backend = backend_of(account)
    unique_id = account_unique_id(backend, account.get(CONF_API_KEY))
    managed, matching = _find_accounts(hass.config_entries.async_entries(DOMAIN), unique_id)
    if managed is not None and matching is not None and managed.entry_id != matching.entry_id:
        raise YamlConflict
    current = managed or matching
    if current is None:
        return False
    data = entry_data(account)
    options = {**current.options, **entry_options(account)}
    if current.data.get(CONF_BACKEND) != backend and CONF_MONTHLY_CHARACTER_LIMIT not in account:
        # Moving between the free web endpoint and a billed API changes what the budget is for.
        options[CONF_MONTHLY_CHARACTER_LIMIT] = default_monthly_limit(backend)
    if (data, options, current.unique_id) != (current.data, current.options, unique_id):
        hass.config_entries.async_update_entry(
            current, data=data, options=options, unique_id=unique_id, title=account_title(backend)
        )
    return True
