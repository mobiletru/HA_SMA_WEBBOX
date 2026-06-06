"""Polling coordinator for a single SMA Sunny WebBox.

The coordinator owns the :class:`WebBoxClient`, fetches plant overview +
per-device process data on every cycle, and refreshes the (much larger)
parameter set on a slower cadence so writable entities still pick up
external changes without hammering the WebBox.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_HOST,
    CONF_INSTALLER_PASSWORD,
    CONF_PARAMETER_INTERVAL,
    CONF_SCAN_INTERVAL,
    CONF_USER_PASSWORD,
    DEFAULT_PARAMETER_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .parameters import enrich_parameters
from .webbox_client import WebBoxClient, WebBoxCredentials, WebBoxError

LOGGER = logging.getLogger(__name__)


class WebBoxCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """One coordinator per WebBox config entry."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.entry = entry
        self.host: str = entry.data[CONF_HOST]
        self._credentials = WebBoxCredentials(
            user_password=entry.data.get(CONF_USER_PASSWORD) or None,
            installer_password=entry.data.get(CONF_INSTALLER_PASSWORD) or None,
        )
        self._parameter_interval = timedelta(
            seconds=entry.options.get(CONF_PARAMETER_INTERVAL, DEFAULT_PARAMETER_INTERVAL)
        )
        self._last_parameter_refresh: dict[str, float] = {}
        self._cached_parameters: dict[str, list[dict[str, Any]]] = {}

        super().__init__(
            hass,
            LOGGER,
            name=f"{DOMAIN} {self.host}",
            update_interval=timedelta(
                seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
        )

    # ----- HA hook -------------------------------------------------------

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            async with WebBoxClient(self.host, credentials=self._credentials) as client:
                t0 = self.hass.loop.time()
                overview = await client.plant_overview()
                devices = await client.list_devices()
                LOGGER.debug(
                    "WebBox %s: overview + %d device(s) discovered in %.0fms",
                    self.host, len(devices), (self.hass.loop.time() - t0) * 1000
                )

                bus: dict[str, dict[str, Any]] = {}
                for dev in devices:
                    key = dev.get("key")
                    if not key:
                        continue
                    t_dev = self.hass.loop.time()
                    process = await client.process_data(key)
                    parameters = await self._maybe_refresh_parameters(client, key)
                    bus[key] = {
                        "info": dev,
                        "process": process,
                        "parameters": parameters,
                    }
                    LOGGER.debug(
                        "WebBox %s device %s: %d process channels, %d parameters (%.0fms)",
                        self.host, key, len(process), len(parameters or []),
                        (self.hass.loop.time() - t_dev) * 1000
                    )
        except WebBoxError as exc:
            raise UpdateFailed(str(exc)) from exc

        total_channels = sum(len(d.get("process", [])) for d in bus.values())
        LOGGER.debug(
            "WebBox %s poll complete: %d devices, %d total process channels (overview keys=%d)",
            self.host, len(bus), total_channels, len(overview or {})
        )

        return {
            "host": self.host,
            "overview": overview,
            "devices": bus,
        }

    # ----- internals -----------------------------------------------------

    async def _maybe_refresh_parameters(
        self, client: WebBoxClient, device_key: str
    ) -> list[dict[str, Any]]:
        if not self._credentials.installer_password:
            return []

        now = self.hass.loop.time()
        last = self._last_parameter_refresh.get(device_key, 0)
        age = (now - last) if last else 9999
        interval = self._parameter_interval.total_seconds()

        if device_key in self._cached_parameters and age < interval:
            LOGGER.debug(
                "parameters cache hit for %s (age=%.0fs < %.0fs)",
                device_key, age, interval
            )
            return self._cached_parameters[device_key]

        LOGGER.debug(
            "parameters cache miss/refresh for %s (age=%.0fs, interval=%.0fs)",
            device_key, age, interval
        )
        try:
            raw = await client.get_parameters(device_key)
        except WebBoxError as exc:
            LOGGER.warning("Couldn't refresh parameters for %s: %s", device_key, exc)
            return self._cached_parameters.get(device_key, [])

        enriched = enrich_parameters(raw)
        self._cached_parameters[device_key] = enriched
        self._last_parameter_refresh[device_key] = now
        LOGGER.debug("parameters refreshed for %s: %d entries", device_key, len(enriched))
        return enriched

    # ----- write path ----------------------------------------------------

    async def async_set_parameter(self, device_key: str, channel: str, value: Any) -> None:
        if not self._credentials.installer_password:
            raise WebBoxError(
                "Installer password is not configured; cannot write parameters.",
                host=self.host,
            )
        async with WebBoxClient(self.host, credentials=self._credentials) as client:
            await client.set_parameter(device_key, channel, value)
        # Force a parameter refresh on the next poll so entities pick up the new value.
        self._last_parameter_refresh.pop(device_key, None)
