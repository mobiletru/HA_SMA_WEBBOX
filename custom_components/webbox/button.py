"""Button entities for common Sunny Island / WebBox commands.

These are convenience buttons that map to specific parameter writes.
They are derived from the curated parameter catalog so the most frequently
used "action" commands (start/stop, operating modes, generator control, etc.)
appear as first-class Button entities in Home Assistant.

Users can still use the generic `webbox.set_parameter` service for anything
not covered here.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_CUSTOM_COMMANDS, DOMAIN
from .coordinator import WebBoxCoordinator
from .entity import WebBoxBaseEntity
from .parameters import get_commands
from .webbox_client import WebBoxError


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: WebBoxCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[ButtonEntity] = []

    # Merge built-in commands with any custom commands defined in options
    custom_cmds: list[dict[str, Any]] = entry.options.get(CONF_CUSTOM_COMMANDS, []) or []
    commands = get_commands(custom_cmds)

    for device_key, device in (coordinator.data or {}).get("devices", {}).items():
        params = device.get("parameters") or []

        # Build a quick lookup of available channels for this device
        available_channels = {
            (p.get("key") or p.get("name")): p for p in params if p.get("writable", True)
        }

        for cmd in commands:
            channel = cmd.get("channel")
            value = cmd.get("value")
            if not channel or value is None:
                continue
            if channel not in available_channels:
                continue

            # Only create the button if this specific value is valid for the parameter
            param_info = available_channels[channel]
            options = param_info.get("options") or []

            # For enum parameters, check that the value is one of the known options
            if options:
                valid_values = [opt.get("value") for opt in options]
                if value not in valid_values:
                    continue

            entities.append(
                WebBoxParameterCommandButton(
                    coordinator,
                    device_key,
                    channel,
                    value,
                    label=cmd.get("label") or channel,
                    icon=cmd.get("icon"),
                    description=cmd.get("description", ""),
                )
            )

    async_add_entities(entities)


class WebBoxParameterCommandButton(WebBoxBaseEntity, ButtonEntity):
    """A button that writes a specific value to a WebBox parameter when pressed."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: WebBoxCoordinator,
        device_key: str,
        channel: str,
        value: Any,
        *,
        label: str,
        icon: str | None = None,
        description: str = "",
    ) -> None:
        super().__init__(
            coordinator,
            device_key,
            channel,
            translation_label=label,
        )
        self._command_value = value
        self._attr_icon = icon or "mdi:flash"
        self._attr_entity_registry_enabled_default = True

        if description:
            self._attr_extra_state_attributes = {"description": description}

    async def async_press(self) -> None:
        """Execute the command by writing the parameter value."""
        try:
            await self.coordinator.async_set_parameter(
                self.device_key, self.channel, self._command_value
            )
        except WebBoxError as exc:
            raise HomeAssistantError(str(exc)) from exc

        # Request a refresh so any related number/select entities update immediately
        await self.coordinator.async_request_refresh()
