"""Shared base classes for WebBox entities."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL_WEBBOX
from .coordinator import WebBoxCoordinator


class WebBoxBaseEntity(CoordinatorEntity[WebBoxCoordinator]):
    """Common boilerplate: per-bus-device DeviceInfo, availability, naming."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: WebBoxCoordinator,
        device_key: str,
        channel: str,
        *,
        translation_label: str | None = None,
    ) -> None:
        super().__init__(coordinator)
        self.device_key = device_key
        self.channel = channel
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{device_key}_{channel}"
        self._attr_name = translation_label or channel

    @property
    def _device_record(self) -> dict[str, Any] | None:
        return (self.coordinator.data or {}).get("devices", {}).get(self.device_key)

    @property
    def device_info(self) -> DeviceInfo:
        record = self._device_record or {}
        info = record.get("info") or {}
        name = info.get("name") or self.device_key
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self.coordinator.host}:{self.device_key}")},
            via_device=(DOMAIN, self.coordinator.host),
            manufacturer=MANUFACTURER,
            model=name,
            name=f"{name} ({self.device_key})",
        )

    @property
    def available(self) -> bool:
        return super().available and self._device_record is not None


class WebBoxHubEntity(CoordinatorEntity[WebBoxCoordinator]):
    """Entities attached to the WebBox itself (e.g. plant overview)."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: WebBoxCoordinator, channel: str) -> None:
        super().__init__(coordinator)
        self.channel = channel
        self._attr_unique_id = f"{coordinator.entry.entry_id}_overview_{channel}"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.host)},
            manufacturer=MANUFACTURER,
            model=MODEL_WEBBOX,
            name=self.coordinator.entry.title,
            configuration_url=f"http://{self.coordinator.host}/",
        )
