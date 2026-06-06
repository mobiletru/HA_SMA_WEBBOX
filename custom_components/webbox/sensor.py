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
# We only assign state_class for numeric values to avoid HA errors on string
# channels (e.g. device roles like "Master", relay/operating statuses).
_TOTAL_HINTS = ("Wh", "Total", "Energy")

# Status / mode / relay / operating-state channels that are strings or enums.
# Never assign state_class=measurement to these (common on Sunny Island clusters).
_STATUS_HINTS = (
    "Stt", "OpStt", "Op_", "Prio", "Rly", "Mode", "Stat", "ConStt",
    "GdStt", "Backup", "GridCon", "Relay", "OpSttSlv"
)


def _looks_like_status(name: str) -> bool:
    n = (name or "").lower().replace("_", "").replace(".", "")
    return any(h.lower().replace("_", "").replace(".", "") in n for h in _STATUS_HINTS)


def _state_class_for(name: str, unit: str | None, value: Any = None) -> SensorStateClass | None:
    if _looks_like_status(name):
        return None
    if value is not None and not isinstance(value, (int, float)):
        return None
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
        initial_value = info.get("value")
        entities.append(
            WebBoxOverviewSensor(coordinator, key, info.get("unit"), initial_value)
        )

    # Per-device process-data sensors.
    for device_key, device in (coordinator.data.get("devices") or {}).items():
        for ch in device.get("process", []) or []:
            name = ch.get("name")
            if not name:
                continue
            initial_value = ch.get("value")
            entities.append(
                WebBoxProcessDataSensor(coordinator, device_key, name, ch.get("unit"), initial_value)
            )

    async_add_entities(entities)


class WebBoxOverviewSensor(WebBoxHubEntity, SensorEntity):
    def __init__(self, coordinator: WebBoxCoordinator, channel: str, unit: str | None, initial_value: Any = None) -> None:
        super().__init__(coordinator, channel)
        self._attr_name = _friendly(channel)
        self._attr_native_unit_of_measurement = unit
        self._attr_state_class = _state_class_for(channel, unit, initial_value)

    @property
    def native_value(self) -> Any:
        overview = (self.coordinator.data or {}).get("overview") or {}
        info = overview.get(self.channel) or {}
        val = info.get("value")
        # Defensive: prevent HA core crash if a previously-numeric sensor becomes a status string
        if self._attr_state_class is not None and isinstance(val, str):
            return val
        return val


class WebBoxProcessDataSensor(WebBoxBaseEntity, SensorEntity):
    def __init__(
        self,
        coordinator: WebBoxCoordinator,
        device_key: str,
        channel: str,
        unit: str | None,
        initial_value: Any = None,
    ) -> None:
        super().__init__(coordinator, device_key, channel, translation_label=_friendly(channel))
        self._attr_native_unit_of_measurement = unit
        self._attr_state_class = _state_class_for(channel, unit, initial_value)

    @property
    def native_value(self) -> Any:
        record = self._device_record or {}
        for ch in record.get("process", []) or []:
            if ch.get("name") == self.channel:
                val = ch.get("value")
                # Defensive: prevent HA core crash if a previously-numeric sensor becomes a status string
                if self._attr_state_class is not None and isinstance(val, str):
                    return val
                return val
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
