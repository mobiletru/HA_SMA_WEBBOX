"""Select entities for enum-typed WebBox parameters."""

from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import WebBoxCoordinator
from .entity import WebBoxBaseEntity
from .webbox_client import WebBoxError


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: WebBoxCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SelectEntity] = []
    for device_key, device in (coordinator.data.get("devices") or {}).items():
        for param in device.get("parameters", []) or []:
            if not param.get("writable", True):
                continue
            if param.get("type") != "enum":
                continue
            options = param.get("options") or []
            if not options:
                continue
            entities.append(WebBoxSelect(coordinator, device_key, param))
    async_add_entities(entities)


class WebBoxSelect(WebBoxBaseEntity, SelectEntity):
    def __init__(
        self,
        coordinator: WebBoxCoordinator,
        device_key: str,
        param: dict[str, Any],
    ) -> None:
        channel = param.get("key") or param.get("name")
        super().__init__(coordinator, device_key, channel, translation_label=param.get("label") or channel)
        self._param_key = channel
        self._attr_icon = "mdi:cog-outline"
        if param.get("description"):
            self._attr_extra_state_attributes = {"description": param["description"]}

        # Maintain bidirectional maps between raw WebBox values and friendly labels.
        self._value_to_label: dict[str, str] = {}
        self._label_to_value: dict[str, Any] = {}
        for opt in param.get("options", []) or []:
            label = opt.get("label")
            value = opt.get("value")
            if label is None or value is None:
                continue
            self._value_to_label[str(value)] = label
            self._label_to_value[label] = value

        self._attr_options = list(self._label_to_value.keys())

    def _param(self) -> dict[str, Any] | None:
        record = self._device_record or {}
        for p in record.get("parameters", []) or []:
            if (p.get("key") or p.get("name")) == self._param_key:
                return p
        return None

    @property
    def current_option(self) -> str | None:
        param = self._param()
        if not param:
            return None
        return self._value_to_label.get(str(param.get("value")))

    async def async_select_option(self, option: str) -> None:
        if option not in self._label_to_value:
            raise HomeAssistantError(f"Unknown option {option!r}")
        raw_value = self._label_to_value[option]
        try:
            await self.coordinator.async_set_parameter(self.device_key, self._param_key, raw_value)
        except WebBoxError as exc:
            raise HomeAssistantError(str(exc)) from exc
        await self.coordinator.async_request_refresh()
