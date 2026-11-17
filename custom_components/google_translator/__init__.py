"""Google Translator: Google Translate as Home Assistant services and sensors."""

from __future__ import annotations

from datetime import datetime
import logging

from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import CONF_API_KEY, Platform
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType

from .api import GoogleAuthError, GoogleError, Translation
from .cache import TranslationCache
from .companion import async_watch_translator
from .const import (
    BACKEND_CLOUD,
    CONF_BACKEND,
    CONF_CACHE_SIZE,
    CONF_DEFAULT_TARGET_LANGUAGE,
    CONF_MONTHLY_CHARACTER_LIMIT,
    DEFAULT_CACHE_SIZE,
    DOMAIN,
)
from .data import GoogleRuntimeData, async_client_for_entry
from .languages import target_from_home_assistant_language
from .services import GoogleServices
from .usage import UsageTracker, month_bounds
from .yaml_config import (  # noqa: F401 - CONFIG_SCHEMA is Home Assistant's YAML entry point
    CONFIG_SCHEMA,
    YamlConflict,
    apply_to_existing_account,
    default_monthly_limit,
)

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.SENSOR]
STORAGE_VERSION = 1


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the services once, so they exist even before an account is loaded."""
    GoogleServices(hass).register()
    if DOMAIN in config:
        _import_yaml_account(hass, config[DOMAIN])
    return True


def _import_yaml_account(hass: HomeAssistant, account: ConfigType) -> None:
    """Bring the config entry in line with ``configuration.yaml``.

    An existing account is updated right here, before any account is set up, so it starts with
    the new values. Only a missing account is created through the import flow, which has to run
    as a task: awaiting it here would make the new entry wait for this very setup.
    """
    try:
        if apply_to_existing_account(hass, account):
            return
    except YamlConflict:
        _LOGGER.warning(
            "The account in configuration.yaml is the same as one that is not managed by YAML; "
            "remove one of them under Settings > Devices & services"
        )
        return
    hass.async_create_task(
        hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_IMPORT}, data=account)
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Connect to Google with the stored settings."""
    options = entry.options
    backend = entry.data[CONF_BACKEND]
    client = await async_client_for_entry(hass, entry)
    if backend == BACKEND_CLOUD:
        try:
            await client.async_get_languages()  # the cheapest request that proves the key
        except GoogleAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except GoogleError as err:
            raise ConfigEntryNotReady(str(err)) from err

    tracker = UsageTracker(
        Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"),
        options.get(CONF_MONTHLY_CHARACTER_LIMIT, default_monthly_limit(backend)),
    )
    await tracker.async_load()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = GoogleRuntimeData(
        entry=entry,
        client=client,
        usage=tracker,
        cache=TranslationCache[Translation](options.get(CONF_CACHE_SIZE, DEFAULT_CACHE_SIZE)),
        default_target_language=options.get(
            CONF_DEFAULT_TARGET_LANGUAGE,
            target_from_home_assistant_language(hass.config.language),
        ),
    )
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    entry.async_on_unload(_schedule_month_change(hass, tracker))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    async_watch_translator(hass, entry)
    return True


def _schedule_month_change(hass: HomeAssistant, tracker: UsageTracker) -> CALLBACK_TYPE:
    """Let the sensors start from zero when a new month begins, even if nothing is translated."""
    cancel: CALLBACK_TYPE | None = None

    @callback
    def arm() -> None:
        nonlocal cancel
        cancel = async_track_point_in_utc_time(
            hass, new_month, month_bounds(datetime.now().astimezone())[1]
        )

    @callback
    def new_month(_now: datetime) -> None:
        tracker.refresh()
        arm()

    arm()
    return lambda: cancel() if cancel else None


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an account."""
    if unloaded := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        runtime = hass.data[DOMAIN].pop(entry.entry_id)
        await runtime.usage.async_flush()
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Forget the saved count of a removed account."""
    await Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}").async_remove()


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Apply changed options by reloading the account."""
    await hass.config_entries.async_reload(entry.entry_id)
