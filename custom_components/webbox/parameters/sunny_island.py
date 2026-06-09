"""
Curated parameter catalog for the SMA Sunny Island family
(SI 3.0M, 4.4M, 6.0H, 8.0H — single-phase and multicluster).

The WebBox exposes parameters by their internal "meta" key (e.g.
``Bat.ChaCapNom``). Firmware-supplied metadata is usually sparse, so the
dashboard cross-references this catalog to render friendly labels, units,
sensible min/max bounds, and dropdown choices for enumerations.

MAINTENANCE NOTE:
    This file is duplicated between custom_components/webbox/parameters/
    and webbox/app/parameters/. Keep both copies in sync when editing.

This is a curated subset — the most commonly tuned installer parameters,
grouped the way an SMA installer would expect to see them. Channel names
follow the conventions documented in the *Sunny Island Parameter List*
that ships with SMA's installer software; entries that vary by firmware
include both historical and current names.

Each entry is a :class:`ParameterSpec`:

* ``key``        — the WebBox ``meta`` channel name
* ``label``      — short human label for the UI
* ``group``      — UI grouping (Battery, Charge, Grid, …)
* ``unit``       — display unit, when not returned by firmware
* ``type``       — ``"number"``, ``"enum"``, ``"bool"``, ``"text"``,
                   ``"duration"`` (seconds)
* ``min`` / ``max`` — numeric bounds (where standard)
* ``step``       — numeric step (defaults to 1 for ints, 0.1 for floats)
* ``options``    — list of ``(value, label)`` for enum/bool
* ``writable``   — ``False`` for read-only firmware values
* ``description`` — long-form help shown on hover
* ``aliases``    — alternative ``meta`` names seen on older firmwares
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True, frozen=True)
class ParameterSpec:
    key: str
    label: str
    group: str
    unit: str | None = None
    type: str = "number"
    min: float | None = None
    max: float | None = None
    step: float | None = None
    options: tuple[tuple[Any, str], ...] = ()
    writable: bool = True
    description: str = ""
    aliases: tuple[str, ...] = field(default_factory=tuple)


_BATTERY_TYPES = (
    (1, "FLA — Flooded lead-acid"),
    (2, "VRLA — Sealed lead-acid (AGM/Gel)"),
    (3, "LiIon — Lithium-ion (BMS-controlled)"),
    (4, "NiCd"),
)

_GRID_MODES = (
    ("OnGrd", "On-grid (grid-tied)"),
    ("OffGrd", "Off-grid (island mode)"),
    ("Bckp", "Backup (grid-parallel with backup)"),
)

_GRID_MANUAL_START = (
    ("Auto", "Automatic"),
    ("Stop", "Stop"),
    ("Start", "Start"),
)

_SELF_CONSUMPTION_MODES = (
    (0, "Off"),
    (1, "Self-consumption"),
    (2, "Time-of-use"),
    (3, "Zero feed-in"),
)

_OPERATING_MODES = (
    ("Stop", "Stopped"),
    ("Start", "Start"),
    ("Standby", "Standby"),
    ("Run", "Run"),
)

_GEN_AUTO = (
    (0, "Manual"),
    (1, "Auto by SOC"),
    (2, "Auto by load"),
    (3, "Auto by time"),
)


SUNNY_ISLAND_PARAMETERS: tuple[ParameterSpec, ...] = (
    # ---- Battery basics --------------------------------------------------
    ParameterSpec(
        key="Bat.Typ",
        label="Battery type",
        group="Battery",
        type="enum",
        options=_BATTERY_TYPES,
        description="Chemistry of the connected battery bank. Selects the default charge curves and protections.",
        aliases=("Battery.Type", "Bat.BatTyp"),
    ),
    ParameterSpec(
        key="Bat.ChaCapNom",
        label="Nominal capacity",
        group="Battery",
        unit="Ah",
        min=50,
        max=10000,
        step=1,
        description="C10 nominal capacity of the battery bank.",
        aliases=("Battery.NomCap", "Bat.NomCap"),
    ),
    ParameterSpec(
        key="Bat.NomV",
        label="Nominal voltage",
        group="Battery",
        unit="V",
        min=12,
        max=600,
        step=0.1,
        description="Nominal DC voltage of the bank (typically 48 V on SI single-cluster).",
        aliases=("Battery.NomV",),
    ),
    ParameterSpec(
        key="Bat.SocLowBatBck",
        label="Backup reserve SOC",
        group="Battery",
        unit="%",
        min=0,
        max=100,
        step=1,
        description="State-of-charge reserved for backup; the inverter stops self-consumption discharge below this level.",
        aliases=("BatBck.SocLow",),
    ),
    ParameterSpec(
        key="Bat.SocLowProt",
        label="Deep-discharge protection SOC",
        group="Battery",
        unit="%",
        min=0,
        max=80,
        step=1,
        description="Below this SOC the Sunny Island disconnects the battery to prevent damage.",
    ),

    # ---- Charging --------------------------------------------------------
    ParameterSpec(
        key="BatChrg.ChrgCurMax",
        label="Max charge current",
        group="Charging",
        unit="A",
        min=10,
        max=1200,
        step=1,
        description="Maximum DC current that may flow into the battery during charging. Actual charge current may be lower due to other limits (inverter, generator, grid, temperature, battery type).",
        aliases=("BatCha.ChrgCurMax", "BatChrgCurMax"),
    ),
    ParameterSpec(
        key="BatChrg.FloatV",
        label="Float voltage",
        group="Charging",
        unit="V",
        min=40,
        max=60,
        step=0.01,
        description="Float-stage charge voltage (typically ~54.0 V for VRLA, ~53.6 V for FLA at 25 °C).",
        aliases=("BatCha.FloatV",),
    ),
    ParameterSpec(
        key="BatChrg.BoostV",
        label="Boost voltage",
        group="Charging",
        unit="V",
        min=40,
        max=64,
        step=0.01,
        description="Absorption/boost charge voltage. Stay within the battery manufacturer's range.",
        aliases=("BatCha.BoostV",),
    ),
    ParameterSpec(
        key="BatChrg.EquV",
        label="Equalization voltage",
        group="Charging",
        unit="V",
        min=40,
        max=64,
        step=0.01,
        description="Equalization voltage for periodic FLA conditioning. Disabled for VRLA/Li-Ion.",
        aliases=("BatCha.EquV",),
    ),
    ParameterSpec(
        key="BatChrg.TmFullChrg",
        label="Full-charge cycle interval",
        group="Charging",
        unit="days",
        min=1,
        max=180,
        step=1,
        description="How often a full absorption cycle is forced.",
    ),

    # ---- Discharging -----------------------------------------------------
    ParameterSpec(
        key="BatDsch.DschCurMax",
        label="Max discharge current",
        group="Discharging",
        unit="A",
        min=0,
        max=400,
        step=1,
        description="Maximum DC current allowed out of the battery.",
        aliases=("BatDch.DchCurMax",),
    ),
    ParameterSpec(
        key="BatDsch.VLow",
        label="Low-voltage cut-off",
        group="Discharging",
        unit="V",
        min=36,
        max=54,
        step=0.01,
        description="Battery voltage at which discharge is halted.",
    ),

    # ---- Inverter / AC output -------------------------------------------
    ParameterSpec(
        key="Inverter.WMax",
        label="Max apparent power",
        group="Inverter",
        unit="W",
        min=0,
        max=20000,
        step=10,
        description="Maximum AC power the inverter is allowed to source.",
        aliases=("Inv.WMax",),
    ),
    ParameterSpec(
        key="Inverter.FrqNom",
        label="Nominal frequency",
        group="Inverter",
        unit="Hz",
        type="enum",
        options=((50, "50 Hz"), (60, "60 Hz")),
        description="Output frequency for off-grid operation.",
    ),
    ParameterSpec(
        key="Inverter.VNom",
        label="Nominal AC voltage",
        group="Inverter",
        unit="V",
        min=100,
        max=260,
        step=1,
        description="Output voltage for off-grid operation.",
    ),

    # ---- Grid handling ---------------------------------------------------
    ParameterSpec(
        key="Operation.GdOnOff",
        label="Operating mode",
        group="Grid",
        type="enum",
        options=_GRID_MODES,
        description="Selects grid-tied, off-grid, or backup operation.",
        aliases=("Operation.Mode",),
    ),
    ParameterSpec(
        key="GdManStr",
        label="Manual grid start",
        group="Grid",
        type="enum",
        options=_GRID_MANUAL_START,
        description="Manual control to request grid connection (Start), disconnect (Stop), or let automatic (Auto).",
    ),
    ParameterSpec(
        key="Operation.Mode",
        label="Operating state",
        group="Grid",
        type="enum",
        options=_OPERATING_MODES,
        description="Run/stop state command.",
    ),
    ParameterSpec(
        key="Grid.FrqMax",
        label="Grid frequency, max",
        group="Grid",
        unit="Hz",
        min=45,
        max=65,
        step=0.01,
        description="Upper grid frequency tolerance before disconnection.",
    ),
    ParameterSpec(
        key="Grid.FrqMin",
        label="Grid frequency, min",
        group="Grid",
        unit="Hz",
        min=45,
        max=65,
        step=0.01,
        description="Lower grid frequency tolerance before disconnection.",
    ),
    ParameterSpec(
        key="Grid.VMax",
        label="Grid voltage, max",
        group="Grid",
        unit="V",
        min=180,
        max=280,
        step=1,
        description="Upper grid voltage tolerance.",
    ),
    ParameterSpec(
        key="Grid.VMin",
        label="Grid voltage, min",
        group="Grid",
        unit="V",
        min=100,
        max=240,
        step=1,
        description="Lower grid voltage tolerance.",
    ),
    ParameterSpec(
        key="Grid.PwrMaxFeed",
        label="Max grid feed-in",
        group="Grid",
        unit="W",
        min=0,
        max=20000,
        step=10,
        description="Maximum power exported to the grid (zero = no feed-in).",
    ),
    ParameterSpec(
        key="Grid.CurNom",
        label="Nominal grid current",
        group="Grid",
        unit="A",
        min=0,
        max=100,
        step=0.1,
        description="Nominal current for the grid connection.",
        aliases=("GdCurNom", "Gd.CurNom", "GridCurNom"),
    ),

    # ---- Self-consumption / energy management ---------------------------
    ParameterSpec(
        key="SelfCsmp.LodCtl",
        label="Self-consumption mode",
        group="Energy management",
        type="enum",
        options=_SELF_CONSUMPTION_MODES,
        description="How the inverter prioritises battery vs. grid for household loads.",
        aliases=("Slf.Csmp.LodCtl", "EnergyMgmt.Mode"),
    ),
    ParameterSpec(
        key="SelfCsmp.SocStartChrg",
        label="Self-consumption start SOC",
        group="Energy management",
        unit="%",
        min=0,
        max=100,
        step=1,
        description="SOC at which the inverter starts charging from PV surplus.",
    ),
    ParameterSpec(
        key="SelfCsmp.SocStopChrg",
        label="Self-consumption stop SOC",
        group="Energy management",
        unit="%",
        min=0,
        max=100,
        step=1,
        description="SOC at which surplus charging stops.",
    ),

    # ---- Backup ----------------------------------------------------------
    ParameterSpec(
        key="Backup.TmBackUp",
        label="Backup transfer time",
        group="Backup",
        unit="ms",
        min=0,
        max=2000,
        step=10,
        description="Maximum allowed AC interruption when switching to backup.",
    ),
    ParameterSpec(
        key="Backup.SocStartChrg",
        label="Backup auto-recharge SOC",
        group="Backup",
        unit="%",
        min=0,
        max=100,
        step=1,
        description="SOC threshold at which the backup reserve is topped up from the grid.",
    ),

    # ---- Generator support ----------------------------------------------
    ParameterSpec(
        key="Gen.GenAutoStart",
        label="Generator auto-start",
        group="Generator",
        type="enum",
        options=_GEN_AUTO,
        description="How the generator may be started automatically.",
    ),
    ParameterSpec(
        key="Gen.GenStartSocLo",
        label="Generator start SOC",
        group="Generator",
        unit="%",
        min=0,
        max=100,
        step=1,
        description="SOC at which the generator is started in auto mode.",
    ),
    ParameterSpec(
        key="Gen.GenStopSocHi",
        label="Generator stop SOC",
        group="Generator",
        unit="%",
        min=0,
        max=100,
        step=1,
        description="SOC at which the generator is shut down in auto mode.",
    ),
    ParameterSpec(
        key="Gen.GenWMax",
        label="Generator max power",
        group="Generator",
        unit="W",
        min=0,
        max=30000,
        step=10,
        description="Rated max power of the connected generator.",
    ),
    ParameterSpec(
        key="Gen.RunTmMin",
        label="Generator min run time",
        group="Generator",
        unit="s",
        type="duration",
        min=0,
        max=86400,
        step=60,
        description="Minimum runtime once the generator has started.",
    ),

    # ---- Temperature compensation ---------------------------------------
    ParameterSpec(
        key="BatTmp.TmpCmpV",
        label="Temperature compensation",
        group="Battery",
        unit="mV/°C/cell",
        min=-10,
        max=0,
        step=0.1,
        description="Charge voltage compensation per cell per °C (typically −4 mV).",
    ),
)


# Build a fast lookup table keyed by both the canonical key and any aliases.
LOOKUP: dict[str, ParameterSpec] = {}
for spec in SUNNY_ISLAND_PARAMETERS:
    LOOKUP[spec.key] = spec
    for alias in spec.aliases:
        LOOKUP.setdefault(alias, spec)


# Named high-level commands for buttons, services, and the add-on dashboard.
# These provide user-friendly "one click" or service actions on top of raw parameters.
# Each command maps to a (channel, value) write when the device supports it.
COMMANDS: list[dict[str, Any]] = [
    # Inverter control
    {"name": "start", "channel": "Operation.Mode", "value": "Start", "label": "Start", "icon": "mdi:play", "group": "Inverter"},
    {"name": "stop", "channel": "Operation.Mode", "value": "Stop", "label": "Stop", "icon": "mdi:stop", "group": "Inverter"},
    {"name": "standby", "channel": "Operation.Mode", "value": "Standby", "label": "Standby", "icon": "mdi:pause", "group": "Inverter"},
    {"name": "run", "channel": "Operation.Mode", "value": "Run", "label": "Run", "icon": "mdi:play-circle", "group": "Inverter"},
    # Grid modes (using manual grid start for direct Start/Stop Grid buttons)
    {"name": "start_grid", "channel": "GdManStr", "value": "Start", "label": "Start Grid", "icon": "mdi:transmission-tower", "group": "Grid"},
    {"name": "stop_grid", "channel": "GdManStr", "value": "Stop", "label": "Stop Grid", "icon": "mdi:transmission-tower-off", "group": "Grid"},
    {"name": "on_grid", "channel": "Operation.GdOnOff", "value": "OnGrd", "label": "On-Grid", "icon": "mdi:transmission-tower", "group": "Grid"},
    {"name": "off_grid", "channel": "Operation.GdOnOff", "value": "OffGrd", "label": "Off-Grid", "icon": "mdi:home-lightning-bolt", "group": "Grid"},
    {"name": "backup", "channel": "Operation.GdOnOff", "value": "Bckp", "label": "Backup Mode", "icon": "mdi:battery-charging", "group": "Grid"},
    # Self consumption
    {"name": "self_consumption", "channel": "SelfCsmp.LodCtl", "value": 1, "label": "Self-Consumption", "icon": "mdi:solar-power", "group": "Energy"},
    {"name": "zero_feed_in", "channel": "SelfCsmp.LodCtl", "value": 3, "label": "Zero Feed-In", "icon": "mdi:flash-off", "group": "Energy"},
    {"name": "self_consumption_off", "channel": "SelfCsmp.LodCtl", "value": 0, "label": "Self-Consumption Off", "icon": "mdi:solar-power-off", "group": "Energy"},
    # Generator
    {"name": "generator_manual", "channel": "Gen.GenAutoStart", "value": 0, "label": "Generator: Manual", "icon": "mdi:generator-off", "group": "Generator"},
    {"name": "generator_auto_soc", "channel": "Gen.GenAutoStart", "value": 1, "label": "Generator: Auto by SOC", "icon": "mdi:generator", "group": "Generator"},
    {"name": "generator_auto_load", "channel": "Gen.GenAutoStart", "value": 2, "label": "Generator: Auto by Load", "icon": "mdi:generator", "group": "Generator"},
    # Useful "force" actions (using known parameter writes)
    {"name": "force_full_charge", "channel": "BatChrg.TmFullChrg", "value": 1, "label": "Force Full Charge Cycle", "icon": "mdi:battery-charging-100", "group": "Battery", "description": "Sets full-charge cycle interval to 1 day to trigger soon"},
]


def get_commands(extra: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Return built-in COMMANDS merged with optional user-defined extra commands.

    Commands are matched by "name". If an extra command has the same name as a
    built-in one, the extra one wins (user override). Extra commands must have
    at least "name" and "channel".
    """
    if not extra:
        return list(COMMANDS)

    result: dict[str, dict[str, Any]] = {cmd["name"]: cmd for cmd in COMMANDS}
    for cmd in extra:
        name = cmd.get("name")
        if name and cmd.get("channel"):
            result[name] = cmd  # override or add
    return list(result.values())
