"""High-level Modbus operations used by the REST API.

Everything here talks to the WebBox's Modbus TCP server:

* :func:`discover_units` reads the gateway's device ↔ unit-ID assignment
  table (unit ID 1, registers 42109…) so users can see which unit ID the
  WebBox gave each SMA device.
* :func:`read_channels` reads profile channels from one device unit,
  merging adjacent registers into block reads.
* :func:`write_channel` writes one writable channel (FC 0x10).
"""

from __future__ import annotations

import logging
from typing import Any

from .client import ILLEGAL_DATA_ADDRESS, ModbusError, ModbusTcpClient
from .profile import (
    TAG_NO_INFORMATION,
    ModbusChannel,
    load_profile,
    tag_label,
    unit_id_category_name,
)

LOGGER = logging.getLogger("webbox.modbus")

# gateway assignment table (unit ID 1): 4 registers per device slot
_ASSIGN_BASE = 42109
_ASSIGN_SLOTS = 245
_ASSIGN_WORDS = 4  # device-ID (U16), serial (U32), unit ID (U16)

# block-read tuning: SMA allows ≤125 words per FC3; keep margin and skip
# big address gaps so one bad register can't poison a whole block
_MAX_BLOCK_WORDS = 100
_MAX_BLOCK_GAP = 10


def _merge_blocks(
    channels: list[ModbusChannel],
) -> list[tuple[int, int, list[ModbusChannel]]]:
    """Group sorted channels into (start, word_count, channels) read blocks."""
    if not channels:
        return []
    ordered = sorted(channels, key=lambda c: c.address)
    blocks: list[tuple[int, int, list[ModbusChannel]]] = []
    start = ordered[0].address
    end = start + ordered[0].words
    members = [ordered[0]]
    for ch in ordered[1:]:
        gap = ch.address - end
        new_end = max(end, ch.address + ch.words)
        if gap <= _MAX_BLOCK_GAP and (new_end - start) <= _MAX_BLOCK_WORDS:
            end = new_end
            members.append(ch)
        else:
            blocks.append((start, end - start, members))
            start = ch.address
            end = ch.address + ch.words
            members = [ch]
    blocks.append((start, end - start, members))
    return blocks


def _channel_row(ch: ModbusChannel, value: Any) -> dict[str, Any]:
    """Shape one channel + value the way the dashboard UI expects."""
    row: dict[str, Any] = {
        "name": ch.name,
        "address": ch.address,
        "value": value,
        "unit": ch.unit,
        "writable": ch.write,
        "dtype": ch.type,
        "disp": ch.disp,
        "type": "number",
    }
    if ch.disp == "TAGLIST":
        # TAGLIST registers hold an SMA tag ID; the profile's mapping lists
        # the tags this channel can take (973 = "no information").
        row["type"] = "enum"
        if value is not None:
            row["label"] = tag_label(value)
        row["options"] = [
            {"value": tag, "label": tag_label(tag)}
            for tag in ch.mapping
            if tag != TAG_NO_INFORMATION
        ]
    return row


async def read_channels(
    host: str,
    unit_id: int,
    profile_id: str,
    *,
    port: int = 502,
    channels: list[str] | None = None,
) -> dict[str, Any]:
    """Read (a selection of) profile channels from one device unit.

    ``channels`` may contain channel names or register addresses; ``None``
    reads the whole profile. Unreadable registers are reported per-channel
    instead of failing the request.
    """
    profile = load_profile(profile_id)
    targets = (
        [profile.find(key) for key in channels]
        if channels is not None
        else list(profile.channels)
    )

    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    async with ModbusTcpClient(host, port) as client:
        for start, count, members in _merge_blocks(targets):
            try:
                words = await client.read_holding_registers(unit_id, start, count)
            except ModbusError as exc:
                # fall back to per-channel reads so one bad register in the
                # block doesn't hide the others
                LOGGER.debug("Block read @%s x%s failed: %s", start, count, exc)
                for ch in members:
                    try:
                        w = await client.read_holding_registers(
                            unit_id, ch.address, ch.words
                        )
                        rows.append(_channel_row(ch, ch.decode(w)))
                    except ModbusError as inner:
                        errors.append(f"{ch.name}: {inner}")
                continue
            for ch in members:
                offset = ch.address - start
                rows.append(_channel_row(ch, ch.decode(words[offset : offset + ch.words])))

    rows.sort(key=lambda r: r["address"])
    return {
        "host": host,
        "unit_id": unit_id,
        "profile": profile_id,
        "channels": rows,
        "errors": errors,
    }


async def write_channel(
    host: str,
    unit_id: int,
    profile_id: str,
    channel: str,
    value: Any,
    *,
    port: int = 502,
) -> dict[str, Any]:
    """Write one writable profile channel and read it back for confirmation."""
    profile = load_profile(profile_id)
    ch = profile.find(channel)
    if not ch.write:
        raise ValueError(f"Channel {ch.name!r} (register {ch.address}) is read-only")
    words = ch.encode(value)
    async with ModbusTcpClient(host, port) as client:
        await client.write_registers(unit_id, ch.address, words)
        try:
            readback = ch.decode(
                await client.read_holding_registers(unit_id, ch.address, ch.words)
            )
        except ModbusError:
            readback = None
    return {
        "status": "ok",
        "channel": ch.name,
        "address": ch.address,
        "written": value,
        "readback": readback,
        "unit_id": unit_id,
    }


async def discover_units(host: str, port: int = 502) -> list[dict[str, Any]]:
    """Read the gateway's device ↔ unit-ID assignment table (unit ID 1).

    Each slot holds device-ID (U16), serial number (U32), and the assigned
    unit ID (U16). Empty slots (device-ID 0/0xFFFF) end the table. Unit ID
    255 means "not addressable yet" — assign a real ID in the WebBox UI.
    """
    devices: list[dict[str, Any]] = []
    slots_per_read = _MAX_BLOCK_WORDS // _ASSIGN_WORDS
    async with ModbusTcpClient(host, port) as client:
        for first_slot in range(0, _ASSIGN_SLOTS, slots_per_read):
            n_slots = min(slots_per_read, _ASSIGN_SLOTS - first_slot)
            address = _ASSIGN_BASE + first_slot * _ASSIGN_WORDS
            try:
                words = await client.read_holding_registers(
                    1, address, n_slots * _ASSIGN_WORDS
                )
            except ModbusError as exc:
                if devices:
                    # past the populated part of the table on some firmwares
                    LOGGER.debug("Assignment table read @%s stopped: %s", address, exc)
                    break
                if exc.exception_code == ILLEGAL_DATA_ADDRESS:
                    # Real WebBoxes answer "Illegal data address" instead of
                    # empty slots when no device has been assigned yet
                    # (verified against a WebBox on fw with an empty table).
                    LOGGER.info("Assignment table on %s is empty: %s", host, exc)
                    return []
                raise
            done = False
            for i in range(n_slots):
                base = i * _ASSIGN_WORDS
                device_id = words[base]
                serial = (words[base + 1] << 16) | words[base + 2]
                unit_id = words[base + 3]
                if device_id in (0, 0xFFFF):
                    done = True
                    break
                entry: dict[str, Any] = {
                    "device_id": device_id,
                    "serial": serial,
                    "unit_id": unit_id,
                    "addressable": 3 <= unit_id <= 247,
                }
                # SMA's unitid_config.xml reserves ranges per device
                # category (Sensorbox, String Monitoring Unit, …)
                category = unit_id_category_name(unit_id)
                if category:
                    entry["category"] = category
                devices.append(entry)
            if done:
                break
    return devices
