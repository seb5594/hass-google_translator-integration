"""Sensors that show how many characters were translated this month."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

try:
    from homeassistant.helpers.device_registry import DeviceInfo
except ImportError:  # Home Assistant older than 2023.9
    from homeassistant.helpers.entity import DeviceInfo

from .const import BACKEND_CLOUD, CONF_BACKEND, DOMAIN
from .usage import Usage, UsageTracker

UNIT_CHARACTERS = "characters"


def _description_dataclass(cls):
    """Entity descriptions are frozen dataclasses since Home Assistant 2024.4 and plain ones
    before; a subclass has to follow its base class."""
    try:
        return dataclass(frozen=True, kw_only=True)(cls)
    except TypeError:
        return dataclass(kw_only=True)(cls)


@_description_dataclass
class GoogleSensorDescription(SensorEntityDescription):
    """A sensor and the way to read its value from the usage figures."""

    value_fn: Callable[[Usage], int | float | datetime | None]


SENSORS: tuple[GoogleSensorDescription, ...] = (
    GoogleSensorDescription(
        key="characters_used",
        translation_key="characters_used",
        native_unit_of_measurement=UNIT_CHARACTERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda usage: usage.character_count,
    ),
    GoogleSensorDescription(
        key="characters_limit",
        translation_key="characters_limit",
        native_unit_of_measurement=UNIT_CHARACTERS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda usage: usage.character_limit,
    ),
    GoogleSensorDescription(
        key="characters_remaining",
        translation_key="characters_remaining",
        native_unit_of_measurement=UNIT_CHARACTERS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda usage: usage.characters_remaining,
    ),
    GoogleSensorDescription(
        key="usage_percent",
        translation_key="usage_percent",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda usage: usage.usage_percent,
    ),
    GoogleSensorDescription(
        key="period_end",
        translation_key="period_end",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda usage: dt_util.parse_datetime(usage.period_end),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Create the usage sensors of an account."""
    tracker = hass.data[DOMAIN][entry.entry_id].usage
    async_add_entities(GoogleUsageSensor(tracker, entry, description) for description in SENSORS)


class GoogleUsageSensor(SensorEntity):
    """One figure of the monthly count; it updates when a translation is counted."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    entity_description: GoogleSensorDescription

    def __init__(
        self, tracker: UsageTracker, entry: ConfigEntry, description: GoogleSensorDescription
    ) -> None:
        self._tracker = tracker
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        cloud = entry.data.get(CONF_BACKEND) == BACKEND_CLOUD
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Google",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=(
                "https://console.cloud.google.com/apis/api/translate.googleapis.com/metrics"
                if cloud
                else None
            ),
        )

    async def async_added_to_hass(self) -> None:
        """Follow the tracker instead of polling."""
        self.async_on_remove(self._tracker.async_add_listener(self.async_write_ha_state))

    @property
    def native_value(self) -> int | float | datetime | None:
        """The current value; unknown when no budget is set."""
        return self.entity_description.value_fn(self._tracker.usage)
