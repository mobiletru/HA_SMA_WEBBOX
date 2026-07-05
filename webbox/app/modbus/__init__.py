"""Modbus TCP support for SMA Sunny WebBox gateways.

The Sunny WebBox (with Modbus firmware) exposes every detected SMA device
over Modbus TCP on port 502:

* Unit ID 1 — the gateway itself (device ↔ unit-ID assignment table)
* Unit ID 2 — plant parameters
* Unit IDs 3–247 — individual SMA devices (e.g. a Sunny Island)

Reference: *SUNNY WEBBOX Modbus Interface* (WEBBOX-MODBUS-TB-en-19).

This package contains:

* :mod:`.profile` — parser/decoder for SMA Modbus profile XML files
  (``SI6048MBP.xml`` and friends) shipped in ``profiles/``, plus SMA's
  ``unitid_config.xml`` (default unit-ID ranges per device category)
* :mod:`.client`  — a minimal asyncio Modbus TCP client (FC 0x03 / 0x10)
* :func:`read_channels` / :func:`write_channel` / :func:`discover_units`
  — the high-level operations used by the REST API
"""

from __future__ import annotations

from .client import ModbusError, ModbusTcpClient
from .profile import (
    ModbusChannel,
    ModbusProfile,
    UnitIdCategory,
    available_profiles,
    load_profile,
    unit_id_categories,
    unit_id_range_for,
)
from .service import discover_units, read_channels, write_channel

__all__ = [
    "ModbusChannel",
    "ModbusError",
    "ModbusProfile",
    "ModbusTcpClient",
    "UnitIdCategory",
    "available_profiles",
    "discover_units",
    "load_profile",
    "read_channels",
    "unit_id_categories",
    "unit_id_range_for",
    "write_channel",
]
