"""Number entities for writable numeric WebBox parameters."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import WebBoxCoordinator
from .entity import WebBoxBaseEntity
from .webbox_client import WebBoxError

LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: WebBoxCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[NumberEntity] = []
    for device_key, device in (coordinator.data.get("devices") or {}).items():
        for param in device.get("parameters", []) or []:
            if not param.get("writable", True):
                continue
            if param.get("type") not in ("number", "duration"):
                continue
            entities.append(WebBoxNumber(coordinator, device_key, param))
    async_add_entities(entities)


class WebBoxNumber(WebBoxBaseEntity, NumberEntity):
    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        coordinator: WebBoxCoordinator,
        device_key: str,
        param: dict[str, Any],
    ) -> None:
        channel = param.get("key") or param.get("name")
        super().__init__(coordinator, device_key, channel, translation_label=param.get("label") or channel)
        self._param_key = channel
        self._attr_native_min_value = _as_float(param.get("min"))
        self._attr_native_max_value = _as_float(param.get("max"))
        self._attr_native_step = _as_float(param.get("step"))
        self._attr_native_unit_of_measurement = param.get("unit")
        self._attr_icon = "mdi:tune-variant"
        self._attr_entity_registry_enabled_default = True
        if param.get("description"):
            self._attr_extra_state_attributes = {"description": param["description"]}

    def _param(self) -> dict[str, Any] | None:
        record = self._device_record or {}
        for p in record.get("parameters", []) or []:
            if (p.get("key") or p.get("name")) == self._param_key:
                return p
        return None

    @property
    def native_value(self) -> float | None:
        param = self._param()
        if not param:
            return None
        return _as_float(param.get("value"))

    async def async_set_native_value(self, value: float) -> None:
        try:
            await self.coordinator.async_set_parameter(self.device_key, self._param_key, value)
        except WebBoxError as exc:
            raise HomeAssistantError(str(exc)) from exc
        await self.coordinator.async_request_refresh()


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
