"""SMA Modbus profile XML parsing and value coding.

An SMA Modbus profile (e.g. ``SI6048MBP.xml``) describes every register a
device family exposes over the WebBox's Modbus TCP server::

    <modbusprofile name="Sunny Island - Geraetefamilie" devicename="SI 6048" …>
      <channel address="30845" name="BatSoc" type="U32" write="false"
               scale="1" disp="FIX0" unit="%"/>
      …
    </modbusprofile>

Attribute semantics (per WEBBOX-MODBUS-TB-en-19):

* ``type`` — register data type: ``U16``/``S16`` (1 word), ``U32``/``S32``
  (2 words, big-endian word order).
* ``disp`` — display format. ``FIXn`` means the raw integer carries *n*
  implied decimal places (raw 23050 + FIX2 → 230.50); ``TEMP`` carries
  one implied decimal place.
* ``scale`` — a display hint used by the WebBox's own UI (e.g. show
  seconds as hours with ``scale="3600"``). It is deliberately **not**
  applied here: the ``unit`` attribute describes the raw register value
  (``OnTmh`` unit="s" raw=seconds), so applying ``scale`` would produce
  values that contradict the reported unit.
* ``mapping`` — for ``TAGLIST`` channels, the semicolon-separated SMA tag
  IDs the raw value enumerates.

Profiles are looked up in the bundled ``profiles/`` directory; an extra
directory with user-supplied profiles can be added via the
``WEBBOX_MODBUS_PROFILE_DIR`` environment variable.
"""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

# raw register patterns SMA uses for "no value"
_NAN = {
    "U16": 0xFFFF,
    "S16": -0x8000,
    "U32": 0xFFFFFFFF,
    "S32": -0x80000000,
}

# TAGLIST/ENUM registers hold an SMA tag ID directly; tag 973 means
# "information not available". Labels below cover every tag referenced by
# the bundled SI6048MBP profile (source: WEBBOX-MODBUS-TB-en-19, section
# 5.4.8 "Device Family SI and SBU"); unknown tags render as "#<id>".
TAG_NO_INFORMATION = 973
TAG_LABELS = {
    26: "Acknowledge fault",
    35: "Fault",
    42: "AS4777.3",
    46: "Battery",
    51: "Closed",
    303: "Off",
    307: "OK",
    311: "Open",
    336: "Contact manufacturer",
    337: "Contact installer",
    338: "Invalid",
    381: "Stop",
    438: "VDE0126-1-1",
    455: "Warning",
    569: "Activated",
    802: "Active",
    803: "Inactive",
    886: "None",
    973: "—",
    1013: "Other standard",
    1129: "Yes",
    1130: "No",
    1146: "Execute",
    1392: "Fault",
    1394: "Waiting for valid AC grid",
    1438: "Automatic",
    1461: "Mains connected",
    1462: "Backup not available",
    1463: "Backup",
    1466: "Wait",
    1467: "Start",
    1767: "Quick charge",
    1768: "Full charge",
    1769: "Compensation charge",
    1770: "Maintenance charge",
    1771: "Charge with solar power",
    1772: "Charge with solar and mains power",
    1773: "No request",
    1774: "Load",
    1775: "Time control",
    1776: "Manual one hour",
    1777: "Manual start",
    1778: "External source",
    1779: "Separated",
    1780: "Public electricity mains",
    1781: "Island mains",
    1782: "Sealed lead battery (VRLA)",
    1783: "Flooded lead acid battery (FLA)",
    1784: "Nickel/Cadmium (NiCd)",
    1785: "Lithium-Ion (Li-Ion)",
    1787: "Initialisation",
    1788: "Ready",
    1789: "Warming",
    1790: "Synchronisation",
    1791: "Activated",
    1792: "Resynchronisation",
    1793: "Generator separation",
    1794: "Slow down",
    1795: "Bolted",
    1796: "Blocked after error",
    1799: "No",
    1801: "Mains",
    1802: "Mains and generator",
    1803: "Invalid configuration",
    2183: "Mains operation without consumption",
    2184: "Save energy while on mains",
    2185: "Stop save energy while on mains",
    2186: "Start save energy while on mains",
}


def tag_label(tag: Any) -> str:
    try:
        return TAG_LABELS.get(int(tag), f"#{int(tag)}")
    except (TypeError, ValueError):
        return str(tag)

_DISP_SCALE = {
    "FIX0": 1.0,
    "FIX1": 0.1,
    "FIX2": 0.01,
    "FIX3": 0.001,
    "FIX4": 0.0001,
    # per WEBBOX-MODBUS-TB-en-19 §3.x "TEMP": temperatures are delivered
    # commercially rounded with one decimal place (raw 253 → 25.3 °C)
    "TEMP": 0.1,
}


@dataclass(frozen=True)
class ModbusChannel:
    """One register definition from a profile."""

    address: int
    name: str
    type: str
    write: bool
    scale: float
    disp: str
    unit: str
    mapping: tuple[int, ...] = ()

    @property
    def words(self) -> int:
        return 1 if self.type in ("U16", "S16") else 2

    @property
    def value_scale(self) -> float:
        # only the disp format's implied decimal places; the profile's
        # `scale` attribute is a WebBox-UI display hint (see module doc)
        return _DISP_SCALE.get(self.disp, 1.0)

    def decode(self, words: list[int]) -> int | float | None:
        """Turn raw register words into a scaled value (None = SMA NaN)."""
        if self.type == "U16":
            raw = words[0] & 0xFFFF
        elif self.type == "S16":
            raw = words[0] & 0xFFFF
            if raw >= 0x8000:
                raw -= 0x10000
        else:
            raw = ((words[0] & 0xFFFF) << 16) | (words[1] & 0xFFFF)
            if self.type == "S32" and raw >= 0x80000000:
                raw -= 0x100000000
        if raw == _NAN.get(self.type):
            return None
        scale = self.value_scale
        if scale == 1.0:
            return raw
        return round(raw * scale, 4)

    def _encode_tag(self, value: Any) -> int:
        """Resolve an enum write to a tag ID from this channel's mapping.

        Accepts a tag ID or a tag label (case-insensitive); anything not in
        the channel's mapping is rejected so arbitrary values can never be
        written to enum registers of a live device.
        """
        valid = [t for t in self.mapping if t != TAG_NO_INFORMATION]
        if isinstance(value, str) and not value.strip().lstrip("-").isdigit():
            label = value.strip().lower()
            for tag in valid:
                if tag_label(tag).lower() == label:
                    return tag
            options = ", ".join(f"{tag_label(t)!r}" for t in dict.fromkeys(valid))
            raise ValueError(
                f"Value {value!r} is not a valid option for {self.name!r} "
                f"(expected one of: {options})"
            )
        try:
            tag = int(value)
        except (TypeError, ValueError):
            raise ValueError(f"Value {value!r} is not valid for channel {self.name!r}")
        if tag not in valid:
            raise ValueError(
                f"Tag {tag} is not a valid option for {self.name!r} "
                f"(allowed: {sorted(set(valid))})"
            )
        return tag

    def encode(self, value: Any) -> list[int]:
        """Turn a scaled value back into register words (raises ValueError)."""
        if self.disp == "TAGLIST" and self.mapping:
            raw = self._encode_tag(value)
        else:
            try:
                raw = int(round(float(value) / self.value_scale))
            except (TypeError, ValueError):
                raise ValueError(f"Value {value!r} is not numeric for channel {self.name!r}")
        if self.type == "U16":
            if not 0 <= raw <= 0xFFFF:
                raise ValueError(f"Value {value!r} out of U16 range for {self.name!r}")
            return [raw]
        if self.type == "S16":
            if not -0x8000 <= raw <= 0x7FFF:
                raise ValueError(f"Value {value!r} out of S16 range for {self.name!r}")
            return [raw & 0xFFFF]
        if self.type == "S32":
            if not -0x80000000 <= raw <= 0x7FFFFFFF:
                raise ValueError(f"Value {value!r} out of S32 range for {self.name!r}")
        elif not 0 <= raw <= 0xFFFFFFFF:
            raise ValueError(f"Value {value!r} out of U32 range for {self.name!r}")
        raw &= 0xFFFFFFFF
        return [(raw >> 16) & 0xFFFF, raw & 0xFFFF]

    def as_dict(self) -> dict[str, Any]:
        return {
            "address": self.address,
            "name": self.name,
            "type": self.type,
            "write": self.write,
            "scale": self.scale,
            "disp": self.disp,
            "unit": self.unit,
            "mapping": list(self.mapping),
        }


@dataclass(frozen=True)
class ModbusProfile:
    """A parsed profile: device metadata plus its channel table."""

    id: str
    name: str
    devicename: str
    susyid: int | None
    channels: tuple[ModbusChannel, ...]
    by_address: dict[int, ModbusChannel] = field(repr=False, default_factory=dict)
    by_name: dict[str, ModbusChannel] = field(repr=False, default_factory=dict)

    def find(self, key: str) -> ModbusChannel:
        """Look up a channel by name or register address.

        Raises ``KeyError`` (with a readable message as ``args[0]``) when
        the channel is unknown.
        """
        if key in self.by_name:
            return self.by_name[key]
        try:
            address = int(key)
        except ValueError:
            address = -1
        if address in self.by_address:
            return self.by_address[address]
        raise KeyError(f"Channel {key!r} not found in profile {self.id!r}")


def _profile_dirs() -> list[Path]:
    dirs = [Path(__file__).resolve().parent / "profiles"]
    extra = os.environ.get("WEBBOX_MODBUS_PROFILE_DIR")
    if extra:
        dirs.insert(0, Path(extra))
    return dirs


# ----- unit-ID configuration (unitid_config.xml) ---------------------------


@dataclass(frozen=True)
class UnitIdCategory:
    """One <category> from SMA's ``unitid_config.xml``.

    The file (shipped with SMA's WebBox Device Profile bundle) declares
    which unit-ID range the WebBox assigns to each device category by
    default; ``rules`` are profile-family names matched against a Modbus
    profile's ``name`` attribute.
    """

    name: str
    unitid_min: int
    unitid_max: int
    rules: tuple[str, ...] = ()


# devices without a matching category rule get this range (per
# WEBBOX-MODBUS-TB-en-19 the plant detection assigns plain devices
# starting at unit ID 3)
_DEFAULT_UNIT_RANGE = (3, 247)


@lru_cache(maxsize=1)
def unit_id_categories() -> tuple[UnitIdCategory, ...]:
    """Parse the bundled (or user-supplied) ``unitid_config.xml``.

    Returns an empty tuple when the file is missing or malformed — the
    unit-ID config only refines defaults, it must never break discovery.
    """
    candidates = [Path(__file__).resolve().parent / "unitid_config.xml"]
    extra = os.environ.get("WEBBOX_MODBUS_PROFILE_DIR")
    if extra:
        candidates.insert(0, Path(extra) / "unitid_config.xml")
    for path in candidates:
        if not path.is_file():
            continue
        try:
            root = ET.parse(path).getroot()
        except (ET.ParseError, OSError):
            return ()
        categories: list[UnitIdCategory] = []
        for el in root.findall("category"):
            try:
                lo = int(el.get("unitid_min", ""))
                hi = int(el.get("unitid_max", ""))
            except ValueError:
                continue
            rules = tuple(
                (r.get("name") or "").strip()
                for r in el.findall("rule")
                if (r.get("name") or "").strip()
            )
            categories.append(
                UnitIdCategory(
                    name=el.get("name") or "",
                    unitid_min=lo,
                    unitid_max=hi,
                    rules=rules,
                )
            )
        return tuple(categories)
    return ()


def unit_id_category_name(unit_id: int) -> str | None:
    """Category name whose configured range contains ``unit_id``, if any."""
    for category in unit_id_categories():
        if category.unitid_min <= unit_id <= category.unitid_max:
            return category.name
    return None


def unit_id_range_for(profile: "ModbusProfile") -> tuple[int, int]:
    """Default unit-ID range for a profile's device family.

    Matches the profile's ``name`` attribute against the category rules
    in ``unitid_config.xml``; unmatched device families fall back to the
    generic device range 3–247.
    """
    family = profile.name.strip().lower()
    for category in unit_id_categories():
        for rule in category.rules:
            if rule.strip().lower() == family:
                return (category.unitid_min, category.unitid_max)
    return _DEFAULT_UNIT_RANGE


def _parse(path: Path) -> ModbusProfile:
    root = ET.parse(path).getroot()
    channels: list[ModbusChannel] = []
    for el in root.findall("channel"):
        name = (el.get("name") or "").strip()
        if not name:
            continue
        mapping_attr = (el.get("mapping") or "").strip()
        mapping = tuple(
            int(t) for t in mapping_attr.split(";") if t.strip().isdigit()
        ) if mapping_attr else ()
        channels.append(
            ModbusChannel(
                address=int(el.get("address", "0")),
                name=name,
                type=(el.get("type") or "U32").upper(),
                write=(el.get("write") or "false").lower() == "true",
                scale=float(el.get("scale") or "1"),
                disp=el.get("disp") or "FIX0",
                unit=el.get("unit") or "",
                mapping=mapping,
            )
        )
    by_address = {ch.address: ch for ch in channels}
    by_name: dict[str, ModbusChannel] = {}
    for ch in channels:
        # duplicate names exist (e.g. BatChrgCurMax); keep the first, the
        # second stays reachable via its register address
        by_name.setdefault(ch.name, ch)
    susyid_attr = root.get("susyid")
    return ModbusProfile(
        id=path.stem,
        name=root.get("name") or path.stem,
        devicename=root.get("devicename") or "",
        susyid=int(susyid_attr) if susyid_attr and susyid_attr.isdigit() else None,
        channels=tuple(channels),
        by_address=by_address,
        by_name=by_name,
    )


# profile ids are file stems; anything else (path separators, "..") is
# rejected so API-supplied ids can never escape the profile directories
_PROFILE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]*$")


@lru_cache(maxsize=8)
def load_profile(profile_id: str) -> ModbusProfile:
    """Load a bundled (or user-supplied) profile by id, e.g. ``SI6048MBP``.

    Raises ``FileNotFoundError`` when no matching XML exists or the id is
    not a plain file stem.
    """
    if not _PROFILE_ID_RE.match(profile_id) or ".." in profile_id:
        raise FileNotFoundError(f"Invalid Modbus profile id {profile_id!r}")
    for directory in _profile_dirs():
        candidate = (directory / f"{profile_id}.xml").resolve()
        if candidate.parent != directory.resolve():
            continue
        if candidate.is_file():
            return _parse(candidate)
    raise FileNotFoundError(
        f"Modbus profile {profile_id!r} not found (looked in "
        + ", ".join(str(d) for d in _profile_dirs())
        + ")"
    )


def available_profiles() -> list[dict[str, Any]]:
    """List all discoverable profiles with device metadata.

    ``name`` is the profile id (file stem) — it's what the API accepts as
    the ``profile`` parameter and what the UI stores per WebBox.
    """
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for directory in _profile_dirs():
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.xml")):
            if path.stem in seen:
                continue
            seen.add(path.stem)
            # the unit-ID config lives next to user profiles but is not one
            if path.stem.lower() == "unitid_config":
                continue
            try:
                profile = load_profile(path.stem)
            except (ET.ParseError, OSError, ValueError):
                continue
            if not profile.channels:  # not a Modbus profile XML
                continue
            lo, hi = unit_id_range_for(profile)
            out.append(
                {
                    "name": profile.id,
                    "device_name": profile.devicename or profile.name,
                    "family": profile.name,
                    "susyid": profile.susyid,
                    "channel_count": len(profile.channels),
                    "writable_count": sum(1 for c in profile.channels if c.write),
                    # default unit-ID assignment per SMA's unitid_config.xml
                    "default_unit_id": lo,
                    "unit_id_range": [lo, hi],
                }
            )
    return out
