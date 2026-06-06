"""SMA Sunny WebBox integration."""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr

from .const import (
    ATTR_CHANNEL,
    ATTR_DEVICE_KEY,
    ATTR_VALUE,
    DOMAIN,
    SERVICE_EXECUTE_COMMAND,
    SERVICE_SET_PARAMETER,
    SERVICE_START,
    SERVICE_STOP,
)
from .parameters import COMMANDS
from .coordinator import WebBoxCoordinator
from .webbox_client import WebBoxError

LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.BUTTON,
]

SET_PARAMETER_SCHEMA = vol.Schema(
    {
        vol.Required("device_id"): str,
        vol.Required(ATTR_DEVICE_KEY): str,
        vol.Required(ATTR_CHANNEL): str,
        vol.Required(ATTR_VALUE): vol.Any(str, int, float, bool),
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a WebBox from a config entry."""
    coordinator = WebBoxCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    _register_services(hass)
    _register_command_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    hass.data[DOMAIN].pop(entry.entry_id, None)
    if not hass.data[DOMAIN]:
        hass.services.async_remove(DOMAIN, SERVICE_SET_PARAMETER)
        hass.services.async_remove(DOMAIN, SERVICE_START)
        hass.services.async_remove(DOMAIN, SERVICE_STOP)
        hass.services.async_remove(DOMAIN, SERVICE_EXECUTE_COMMAND)
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


def _register_services(hass: HomeAssistant) -> None:
    """Register the webbox.set_parameter service exactly once."""
    if hass.services.has_service(DOMAIN, SERVICE_SET_PARAMETER):
        return

    async def _set_parameter(call: ServiceCall) -> None:
        device_id: str = call.data["device_id"]
        device_key: str = call.data[ATTR_DEVICE_KEY]
        channel: str = call.data[ATTR_CHANNEL]
        value = call.data[ATTR_VALUE]

        registry = dr.async_get(hass)
        device = registry.async_get(device_id)
        if device is None:
            raise HomeAssistantError(f"Unknown device {device_id!r}")

        # Find the config entry this device belongs to.
        for entry_id in device.config_entries:
            coordinator: WebBoxCoordinator | None = hass.data.get(DOMAIN, {}).get(entry_id)
            if coordinator is None:
                continue
            try:
                await coordinator.async_set_parameter(device_key, channel, value)
            except WebBoxError as exc:
                raise HomeAssistantError(str(exc)) from exc
            await coordinator.async_request_refresh()
            return

        raise HomeAssistantError(
            f"Device {device_id!r} is not bound to a WebBox config entry."
        )

    hass.services.async_register(
        DOMAIN, SERVICE_SET_PARAMETER, _set_parameter, schema=SET_PARAMETER_SCHEMA
    )


# ----- convenience command services (Start / Stop) -----------------------


START_STOP_SCHEMA = vol.Schema(
    {
        vol.Required("device_id"): str,
    }
)


def _register_command_services(hass: HomeAssistant) -> None:
    """Register high-level command services (start/stop + generic execute_command)."""
    if hass.services.has_service(DOMAIN, SERVICE_START):
        return

    async def _start(call: ServiceCall) -> None:
        await _execute_named_command(hass, call, "start")

    async def _stop(call: ServiceCall) -> None:
        await _execute_named_command(hass, call, "stop")

    EXECUTE_SCHEMA = vol.Schema(
        {
            vol.Required("device_id"): str,
            vol.Required("command"): str,  # e.g. "start", "stop", "self_consumption", "force_full_charge"
        }
    )

    async def _execute_command(call: ServiceCall) -> None:
        await _execute_named_command(hass, call, call.data["command"])

    hass.services.async_register(DOMAIN, SERVICE_START, _start, schema=START_STOP_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_STOP, _stop, schema=START_STOP_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_EXECUTE_COMMAND, _execute_command, schema=EXECUTE_SCHEMA)


async def _execute_named_command(hass: HomeAssistant, call: ServiceCall, command_name: str) -> None:
    """Execute a named command from the centralized COMMANDS list using only device_id."""
    device_id: str = call.data["device_id"]

    # Find the command definition
    cmd = next((c for c in COMMANDS if c["name"] == command_name), None)
    if not cmd:
        available = ", ".join(c["name"] for c in COMMANDS)
        raise HomeAssistantError(f"Unknown command {command_name!r}. Available: {available}")

    channel = cmd["channel"]
    value = cmd["value"]

    registry = dr.async_get(hass)
    device = registry.async_get(device_id)
    if device is None:
        raise HomeAssistantError(f"Unknown device {device_id!r}")

    for entry_id in device.config_entries:
        coordinator: WebBoxCoordinator | None = hass.data.get(DOMAIN, {}).get(entry_id)
        if coordinator is None:
            continue

        data = coordinator.data or {}
        for dev_key, record in data.get("devices", {}).items():
            params = record.get("parameters", []) or []
            has_channel = any((p.get("key") or p.get("name")) == channel for p in params)
            if has_channel:
                try:
                    await coordinator.async_set_parameter(dev_key, channel, value)
                except WebBoxError as exc:
                    raise HomeAssistantError(str(exc)) from exc
                await coordinator.async_request_refresh()
                return

    raise HomeAssistantError(
        f"Device {device_id!r} does not expose the parameter for command {command_name!r} "
        "(installer password required for parameter access)."
    )
