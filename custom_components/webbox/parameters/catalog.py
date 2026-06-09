"""
Cross-device parameter catalog.

Today this only knows the Sunny Island family; if/when Sunny Boy or
Cluster Controller catalogs are added they should also be merged into
:data:`LOOKUP` here.

MAINTENANCE NOTE:
    This file (and sunny_island.py) is duplicated between
    custom_components/webbox/parameters/ and webbox/app/parameters/.
    Keep the two directories in sync.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Iterable

from .sunny_island import LOOKUP as SUNNY_ISLAND_LOOKUP, ParameterSpec


_LOOKUP: dict[str, ParameterSpec] = {**SUNNY_ISLAND_LOOKUP}


def parameter_catalog() -> list[dict[str, Any]]:
    """Return the full catalog as a list of plain dicts, sorted by group/label."""
    seen: set[str] = set()
    specs: list[ParameterSpec] = []
    for spec in _LOOKUP.values():
        if spec.key in seen:
            continue
        seen.add(spec.key)
        specs.append(spec)
    specs.sort(key=lambda s: (s.group, s.label))
    return [_spec_to_dict(s) for s in specs]


def enrich_parameters(channels: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Decorate raw WebBox channel dicts with catalog metadata.

    Each returned entry preserves the firmware-supplied ``value``, ``unit``,
    ``min``/``max`` (when present) and adds catalog-provided ``label``,
    ``group``, ``description``, ``type``, ``options``, etc.

    For ``options`` (enum values), catalog-provided labeled options are preferred
    over raw firmware lists (which are often just strings). Raw firmware options
    are normalized to [{"value": ..., "label": ...}] format if no catalog entry.
    """
    def _normalize_options(opts: Any) -> list[dict[str, Any]]:
        if not opts:
            return []
        if isinstance(opts, list) and opts and isinstance(opts[0], dict):
            return opts
        # raw list of values (str/int/etc.) -> make simple labeled options
        return [{"value": o, "label": str(o)} for o in opts]

    enriched: list[dict[str, Any]] = []
    for ch in channels:
        name = ch.get("name")
        if not name:
            enriched.append({**ch, "group": "Unknown"})
            continue

        spec = _LOOKUP.get(name)
        if not spec:
            entry = {**ch, "group": "Other", "label": name, "type": _infer_type(ch.get("value"))}
            if "options" in entry:
                entry["options"] = _normalize_options(entry.get("options"))
            enriched.append(entry)
            continue

        meta = _spec_to_dict(spec)
        firmware = {k: v for k, v in ch.items() if v is not None}
        # Prefer catalog options (they have friendly labels) over firmware raw options
        if meta.get("options") and "options" in firmware:
            firmware.pop("options", None)
        merged = {**meta, **firmware}
        # If no catalog options but firmware gave us some, normalize them
        if "options" in merged:
            merged["options"] = _normalize_options(merged.get("options"))
        merged["key"] = spec.key  # canonical key for writes
        merged["name"] = name      # original key, useful for debugging
        enriched.append(merged)

    enriched.sort(key=lambda c: (c.get("group", "zzz"), c.get("label", c.get("name", ""))))
    return enriched


def _spec_to_dict(spec: ParameterSpec) -> dict[str, Any]:
    data = asdict(spec)
    data["options"] = [
        {"value": value, "label": label} for value, label in spec.options
    ]
    return data


def _infer_type(value: Any) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "number"
    return "text"
