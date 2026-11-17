"""What a loaded config entry keeps in memory."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.loader import async_get_integration

from .api import GoogleClient, GoogleCloudClient, GoogleWebClient, Translation
from .cache import TranslationCache
from .const import BACKEND_CLOUD, CONF_BACKEND, DOMAIN
from .usage import UsageTracker


@dataclass
class GoogleRuntimeData:
    """Shared by the services and the entities of one Google account."""

    entry: ConfigEntry
    client: GoogleClient
    usage: UsageTracker
    cache: TranslationCache[Translation]
    default_target_language: str


async def async_user_agent(hass: HomeAssistant) -> str:
    """Identify this integration to Google."""
    integration = await async_get_integration(hass, DOMAIN)
    return f"home-assistant-{DOMAIN}/{integration.version}"


async def async_create_client(
    hass: HomeAssistant, backend: str, api_key: str | None = None
) -> GoogleClient:
    """Build the client of a backend on Home Assistant's shared HTTP session."""
    session = async_get_clientsession(hass)
    user_agent = await async_user_agent(hass)
    if backend == BACKEND_CLOUD:
        return GoogleCloudClient(session, api_key or "", user_agent)
    return GoogleWebClient(session, user_agent)


async def async_client_for_entry(hass: HomeAssistant, entry: ConfigEntry) -> GoogleClient:
    """The client an existing entry was set up with."""
    return await async_create_client(hass, entry.data[CONF_BACKEND], entry.data.get(CONF_API_KEY))
