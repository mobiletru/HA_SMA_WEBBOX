"""Sensor entities for the WebBox integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import WebBoxCoordinator
from .entity import WebBoxBaseEntity, WebBoxHubEntity

# Channel name → state_class hint. Most live readings are measurements;
# energy totals show up as "*.E.*" or "*Wh*" and become total_increasing.
_TOTAL_HINTS = ("Wh", "Total", "Energy")


def _state_class_for(name: str, unit: str | None) -> SensorStateClass | None:
    if any(h in name for h in _TOTAL_HINTS) or (unit and unit.lower() in {"kwh", "wh", "mwh"}):
        return SensorStateClass.TOTAL_INCREASING
    return SensorStateClass.MEASUREMENT


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: WebBoxCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = []

    # Plant-overview sensors live on the WebBox device itself.
    for key, info in (coordinator.data.get("overview") or {}).items():
        entities.append(
            WebBoxOverviewSensor(coordinator, key, info.get("unit"))
        )

    # Per-device process-data sensors.
    for device_key, device in (coordinator.data.get("devices") or {}).items():
        for ch in device.get("process", []) or []:
            name = ch.get("name")
            if not name:
                continue
            entities.append(
                WebBoxProcessDataSensor(coordinator, device_key, name, ch.get("unit"))
            )

    async_add_entities(entities)


class WebBoxOverviewSensor(WebBoxHubEntity, SensorEntity):
    def __init__(self, coordinator: WebBoxCoordinator, channel: str, unit: str | None) -> None:
        super().__init__(coordinator, channel)
        self._attr_name = _friendly(channel)
        self._attr_native_unit_of_measurement = unit
        self._attr_state_class = _state_class_for(channel, unit)

    @property
    def native_value(self) -> Any:
        overview = (self.coordinator.data or {}).get("overview") or {}
        info = overview.get(self.channel) or {}
        return info.get("value")


class WebBoxProcessDataSensor(WebBoxBaseEntity, SensorEntity):
    def __init__(
        self,
        coordinator: WebBoxCoordinator,
        device_key: str,
        channel: str,
        unit: str | None,
    ) -> None:
        super().__init__(coordinator, device_key, channel, translation_label=_friendly(channel))
        self._attr_native_unit_of_measurement = unit
        self._attr_state_class = _state_class_for(channel, unit)

    @property
    def native_value(self) -> Any:
        record = self._device_record or {}
        for ch in record.get("process", []) or []:
            if ch.get("name") == self.channel:
                return ch.get("value")
        return None


def _friendly(name: str) -> str:
    """Turn ``Inverter.WMax`` into ``Inverter W Max``."""
    pretty = name.replace("_", " ").replace(".", " ")
    # Camel → spaced
    out = []
    for i, ch in enumerate(pretty):
        if ch.isupper() and i > 0 and pretty[i - 1].islower():
            out.append(" ")
        out.append(ch)
    return "".join(out).strip()
