"""Persistent storage for the WebBox dashboard.

State is split between two files in ``/data``:

* ``options.json`` — written by the Supervisor from the add-on's
  configuration UI. Read-only at runtime.
* ``webboxes.json`` — written by the dashboard itself when the user
  adds/edits/removes a WebBox from the UI. Lives alongside ``options.json``
  so it survives add-on restarts.

WebBoxes from both sources are merged at read-time; entries added through
the UI win over entries from ``options.json`` when their hosts collide.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from pathlib import Path
from typing import Any


class Storage:
    def __init__(self, data_dir: str | os.PathLike[str], options_path: str | os.PathLike[str] | None = None):
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._state_path = self._data_dir / "webboxes.json"
        self._options_path = Path(options_path) if options_path else self._data_dir / "options.json"
        self._lock = threading.Lock()

    # ----- options (read-only) ------------------------------------------

    def options(self) -> dict[str, Any]:
        if not self._options_path.exists():
            return {}
        try:
            with self._options_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    # ----- user-managed webboxes ----------------------------------------

    def _load_state(self) -> list[dict[str, Any]]:
        if not self._state_path.exists():
            return []
        try:
            with self._state_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    def _save_state(self, items: list[dict[str, Any]]) -> None:
        tmp = self._state_path.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(items, f, indent=2)
        tmp.replace(self._state_path)

    # ----- merged view --------------------------------------------------

    def list_webboxes(self) -> list[dict[str, Any]]:
        with self._lock:
            options = self.options()
            seeded = options.get("webboxes") or []
            user = self._load_state()

        merged: dict[str, dict[str, Any]] = {}
        for entry in seeded:
            host = (entry.get("host") or "").strip()
            if not host:
                continue
            merged[host] = {
                "id": f"opt:{host}",
                "name": entry.get("name") or host,
                "host": host,
                "password": entry.get("password") or "",
                "installer_password": entry.get("installer_password") or "",
                "poll_interval": entry.get("poll_interval") or 30,
                "public_url": (entry.get("public_url") or "").strip(),
                "source": "options",
            }
        for entry in user:
            host = (entry.get("host") or "").strip()
            if not host:
                continue
            merged[host] = {
                "id": entry.get("id") or f"user:{uuid.uuid4().hex[:8]}",
                "name": entry.get("name") or host,
                "host": host,
                "password": entry.get("password") or "",
                "installer_password": entry.get("installer_password") or "",
                "poll_interval": entry.get("poll_interval") or 30,
                "public_url": (entry.get("public_url") or "").strip(),
                "source": "user",
            }
        return list(merged.values())

    def add_webbox(self, payload: dict[str, Any]) -> dict[str, Any]:
        host = (payload.get("host") or "").strip()
        if not host:
            raise ValueError("host is required")
        with self._lock:
            items = self._load_state()
            new_id = payload.get("id") or f"user:{uuid.uuid4().hex[:8]}"
            entry = {
                "id": new_id,
                "name": payload.get("name") or host,
                "host": host,
                "password": payload.get("password") or "",
                "installer_password": payload.get("installer_password") or "",
                "poll_interval": int(payload.get("poll_interval") or 30),
                "public_url": (payload.get("public_url") or "").strip(),
            }
            items = [i for i in items if i.get("id") != new_id and i.get("host") != host]
            items.append(entry)
            self._save_state(items)
        return {**entry, "source": "user"}

    def update_webbox(self, webbox_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            items = self._load_state()
            found = next((i for i in items if i.get("id") == webbox_id), None)
            if not found:
                raise KeyError(webbox_id)
            for key in ("name", "host", "password", "installer_password", "public_url"):
                if key in payload and payload[key] is not None:
                    found[key] = payload[key]
            if "poll_interval" in payload and payload["poll_interval"] is not None:
                found["poll_interval"] = int(payload["poll_interval"])
            self._save_state(items)
        return {**found, "source": "user"}

    def remove_webbox(self, webbox_id: str) -> bool:
        with self._lock:
            items = self._load_state()
            new_items = [i for i in items if i.get("id") != webbox_id]
            if len(new_items) == len(items):
                return False
            self._save_state(new_items)
        return True

    def find(self, webbox_id: str) -> dict[str, Any] | None:
        return next((wb for wb in self.list_webboxes() if wb["id"] == webbox_id), None)
