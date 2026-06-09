"""Config + options flows for the WebBox integration."""

from __future__ import annotations

from typing import Any

import json

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import callback

from .const import (
    CONF_CUSTOM_COMMANDS,
    CONF_HOST,
    CONF_INSTALLER_PASSWORD,
    CONF_NAME,
    CONF_PARAMETER_INTERVAL,
    CONF_SCAN_INTERVAL,
    CONF_USER_PASSWORD,
    DEFAULT_PARAMETER_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)
from .webbox_client import WebBoxClient, WebBoxCredentials, WebBoxError

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Optional(CONF_NAME, default=""): str,
        vol.Optional(CONF_USER_PASSWORD, default=""): str,
        vol.Optional(CONF_INSTALLER_PASSWORD, default=""): str,
    }
)


class WebBoxConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Walk the user through adding a WebBox."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            await self.async_set_unique_id(host.lower())
            self._abort_if_unique_id_configured()

            creds = WebBoxCredentials(
                user_password=user_input.get(CONF_USER_PASSWORD) or None,
                installer_password=user_input.get(CONF_INSTALLER_PASSWORD) or None,
            )
            try:
                async with WebBoxClient(host, credentials=creds) as client:
                    await client.plant_overview()
            except WebBoxError:
                errors["base"] = "cannot_connect"
            else:
                title = (user_input.get(CONF_NAME) or "").strip() or f"WebBox @ {host}"
                return self.async_create_entry(
                    title=title,
                    data={
                        CONF_HOST: host,
                        CONF_NAME: title,
                        CONF_USER_PASSWORD: user_input.get(CONF_USER_PASSWORD, ""),
                        CONF_INSTALLER_PASSWORD: user_input.get(CONF_INSTALLER_PASSWORD, ""),
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=USER_SCHEMA,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry: config_entries.ConfigEntry) -> WebBoxOptionsFlow:
        return WebBoxOptionsFlow(entry)


class WebBoxOptionsFlow(config_entries.OptionsFlow):
    """Tune polling intervals after the WebBox has been added."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self.entry = entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            # Parse custom_commands from JSON string if provided
            data = dict(user_input)
            if CONF_CUSTOM_COMMANDS in data and isinstance(data[CONF_CUSTOM_COMMANDS], str):
                raw = data[CONF_CUSTOM_COMMANDS].strip()
                if raw:
                    try:
                        parsed = json.loads(raw)
                        if isinstance(parsed, list):
                            data[CONF_CUSTOM_COMMANDS] = parsed
                        else:
                            data[CONF_CUSTOM_COMMANDS] = []
                    except Exception:
                        data[CONF_CUSTOM_COMMANDS] = []
                else:
                    data[CONF_CUSTOM_COMMANDS] = []
            return self.async_create_entry(title="", data=data)

        options = self.entry.options
        custom_cmds = options.get(CONF_CUSTOM_COMMANDS, [])
        custom_default = json.dumps(custom_cmds, indent=2) if custom_cmds else "[]"

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): vol.All(vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL)),
                vol.Optional(
                    CONF_PARAMETER_INTERVAL,
                    default=options.get(CONF_PARAMETER_INTERVAL, DEFAULT_PARAMETER_INTERVAL),
                ): vol.All(vol.Coerce(int), vol.Range(min=30, max=86400)),
                vol.Optional(
                    CONF_CUSTOM_COMMANDS,
                    default=custom_default,
                    description={"suggested_value": custom_default},
                ): str,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
