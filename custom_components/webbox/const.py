"""Constants for the SMA Sunny WebBox integration."""

from __future__ import annotations

DOMAIN = "webbox"

CONF_HOST = "host"
CONF_NAME = "name"
CONF_USER_PASSWORD = "user_password"
CONF_INSTALLER_PASSWORD = "installer_password"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_PARAMETER_INTERVAL = "parameter_interval"

DEFAULT_SCAN_INTERVAL = 30        # seconds — process data
DEFAULT_PARAMETER_INTERVAL = 300  # seconds — parameter refresh
MIN_SCAN_INTERVAL = 10
MAX_SCAN_INTERVAL = 3600

MANUFACTURER = "SMA"
MODEL_WEBBOX = "Sunny WebBox"

SERVICE_SET_PARAMETER = "set_parameter"
SERVICE_START = "start"
SERVICE_STOP = "stop"
SERVICE_EXECUTE_COMMAND = "execute_command"

ATTR_DEVICE_KEY = "device_key"
ATTR_CHANNEL = "channel"
ATTR_VALUE = "value"
