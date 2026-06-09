"""
Asynchronous client for the SMA Sunny WebBox JSON-RPC API.

Specification: *SUNNY WEBBOX RPC User Manual* v1.4
(SWebBoxRPC-BA-en-14, SMA Solar Technology AG, 2013).

Request envelope (section 4.1):

    {
        "version": "1.0",                # RPC version
        "proc":    "<ProcedureName>",
        "id":      "<id>",               # max 16 chars, echoed in response
        "format":  "JSON",
        "passwd":  "<md5(password)>",    # OPTIONAL, top-level (not in params)
        "params":  { ... }               # procedure-specific arguments
    }

If ``passwd`` is omitted, the WebBox assumes user-level access. To gain
installer-level access (required for ``GetParameter``, ``SetParameter``
and ``GetParameterChannels``), send the MD5 hex digest of the installer
password.

The WebBox advertises a minimum query interval of 30 seconds
(section 4.3); callers should respect that.

The :class:`WebBoxClient` exposes one method per procedure documented in
sections 7.1–7.7. ``GetProcessDataChannels`` and ``GetParameterChannels``
are exposed for completeness, but :meth:`process_data` and
:meth:`get_parameters` already accept "all channels" when the
``channels`` selection is omitted (section 7.4 / 7.6), saving a round
trip.

MAINTENANCE NOTE:
    This file is intentionally duplicated (once under custom_components/
    for the HACS integration, once under webbox/app/ for the add-on).
    When making changes here, also update the copy in
    custom_components/webbox/webbox_client.py (or vice-versa) so the two
    stay in sync.
"""

from __future__ import annotations

import asyncio
import hashlib
import itertools
import json
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx


def _create_httpx_client(timeout: httpx.Timeout) -> httpx.AsyncClient:
    """Create httpx client in a thread to avoid blocking event loop on SSL cert load."""
    return httpx.AsyncClient(timeout=timeout)


LOGGER = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = httpx.Timeout(connect=4.0, read=15.0, write=5.0, pool=4.0)


class WebBoxError(RuntimeError):
    """Raised when a WebBox JSON-RPC call fails."""

    def __init__(self, message: str, *, code: int | str | None = None, host: str | None = None):
        super().__init__(message)
        self.code = code
        self.host = host


def _md5(value: str) -> str:
    return hashlib.md5(value.encode("utf-8")).hexdigest()


def normalize_host_url(host: str) -> str:
    """Return ``host`` as a fully-qualified base URL, defaulting to http://."""
    host = host.strip().rstrip("/")
    if not host.startswith(("http://", "https://")):
        host = f"http://{host}"
    return host


@dataclass(slots=True)
class WebBoxCredentials:
    """Holds the WebBox user / installer passwords.

    Per spec section 4.1, the request's ``passwd`` field is
    ``md5(password)`` — there is no role prefix; the WebBox identifies
    the access level by which configured password the digest matches.
    """

    user_password: str | None = None
    installer_password: str | None = None

    def hash_user(self) -> str | None:
        return _md5(self.user_password) if self.user_password else None

    def hash_installer(self) -> str | None:
        return _md5(self.installer_password) if self.installer_password else None


class WebBoxClient:
    """Thin async wrapper around the SMA Sunny WebBox JSON-RPC API."""

    def __init__(
        self,
        host: str,
        *,
        credentials: WebBoxCredentials | None = None,
        timeout: httpx.Timeout = _DEFAULT_TIMEOUT,
        client: httpx.AsyncClient | None = None,
    ):
        self.host = host.strip()
        self.credentials = credentials or WebBoxCredentials()
        self._timeout = timeout
        self._client = client
        self._owns_client = client is None
        self._id_counter = itertools.count(1)

    async def __aenter__(self) -> "WebBoxClient":
        if self._client is None:
            loop = asyncio.get_running_loop()
            self._client = await loop.run_in_executor(
                None, _create_httpx_client, self._timeout
            )
            self._owns_client = True
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    # ----- low-level RPC -------------------------------------------------

    @property
    def _endpoint(self) -> str:
        return f"{normalize_host_url(self.host)}/rpc"

    async def _rpc(
        self,
        proc: str,
        params: dict[str, Any] | None = None,
        *,
        passwd: str | None = None,
    ) -> Any:
        if self._client is None:
            loop = asyncio.get_running_loop()
            self._client = await loop.run_in_executor(
                None, _create_httpx_client, self._timeout
            )
            self._owns_client = True

        request: dict[str, Any] = {
            "version": "1.0",
            "proc": proc,
            "id": str(next(self._id_counter))[:16],
            "format": "JSON",
        }
        if passwd:
            # Per spec section 4.1, passwd is a top-level request field —
            # not nested in `params`.
            request["passwd"] = passwd
        if params:
            request["params"] = params

        LOGGER.debug("webbox %s -> %s %s", self.host, proc, params or {})
        # SMA Sunny WebBoxes expect the request body as
        # ``RPC=<json>`` with ``application/x-www-form-urlencoded`` —
        # not a raw JSON body. The response is symmetric: it may be
        # bare JSON or prefixed with ``RPC=``.
        body_bytes = b"RPC=" + json.dumps(request).encode("utf-8")

        start = time.perf_counter()
        try:
            response = await self._client.post(
                self._endpoint,
                content=body_bytes,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        except httpx.HTTPError as exc:
            raise WebBoxError(f"WebBox at {self.host} unreachable: {exc}", host=self.host) from exc

        duration_ms = int((time.perf_counter() - start) * 1000)

        if LOGGER.isEnabledFor(logging.DEBUG):
            body_preview = ""
            try:
                txt = (response.text or "")[:300]
                body_preview = " ".join(txt.split())[:220]
            except Exception:
                pass
            LOGGER.debug(
                "webbox %s <- %s (%s) %dms status=%s | %s",
                self.host, proc, response.headers.get("content-type", "?"),
                duration_ms, response.status_code, body_preview
            )

        if response.status_code != 200:
            raise WebBoxError(
                f"WebBox at {self.host} returned HTTP {response.status_code}",
                code=response.status_code,
                host=self.host,
            )

        raw = response.text
        if raw.lstrip().startswith("RPC="):
            raw = raw.lstrip()[4:]
        try:
            body = json.loads(raw)
        except ValueError as exc:
            # The response wasn't JSON, which usually means we're hitting the
            # WebBox's HTML admin/login page (RPC not enabled in WebBox
            # settings, or the device at this IP isn't an SMA WebBox at all).
            # Surface the content-type and a body snippet so it's diagnosable.
            content_type = response.headers.get("content-type", "").lower()
            snippet = " ".join((response.text or "").split())[:200]
            if "html" in content_type or snippet.lstrip().startswith("<"):
                detail = (
                    f"WebBox at {self.host}: POST /rpc returned an HTML page, "
                    f"not JSON. Most common cause: the WebBox's JSON-RPC "
                    f"interface is not enabled — open the WebBox web UI → "
                    f"‘WebBox’ → ‘External communication’ and "
                    f"enable ‘RPC over HTTP’, then retry. "
                    f"(content-type={content_type or 'unset'!r}, body[:200]={snippet!r})"
                )
            else:
                detail = (
                    f"WebBox at {self.host} returned a non-JSON body "
                    f"(content-type={content_type or 'unset'!r}, "
                    f"body[:200]={snippet!r})"
                )
            raise WebBoxError(detail, host=self.host) from exc

        if not isinstance(body, dict):
            raise WebBoxError(f"Unexpected response shape from {self.host}", host=self.host)

        if "error" in body and body["error"]:
            err = body["error"]
            if isinstance(err, dict):
                message = err.get("description") or err.get("message") or str(err)
                code = err.get("code")
            else:
                message = str(err)
                code = None
            raise WebBoxError(f"{proc} failed: {message}", code=code, host=self.host)

        return body.get("result")

    # ----- public methods ------------------------------------------------

    async def plant_overview(self) -> dict[str, Any]:
        """Section 7.1 — POWER, DAILY-YIELD, TOTAL-YIELD, STATUS, ERROR."""
        result = await self._rpc("GetPlantOverview")
        return _normalise_overview(result)

    async def list_devices(self) -> list[dict[str, Any]]:
        """Section 7.2 — hierarchical list of detected plant devices."""
        result = await self._rpc("GetDevices")
        devices = result.get("devices", []) if isinstance(result, dict) else []
        return [_normalise_device(d) for d in devices]

    async def process_data_channels(self, device_key: str) -> list[str]:
        """Section 7.3 — meta names of the available process-data channels."""
        result = await self._rpc("GetProcessDataChannels", {"device": device_key})
        return _extract_channel_names(result, device_key)

    async def process_data(
        self, device_key: str, channels: list[str] | None = None
    ) -> list[dict[str, Any]]:
        """Section 7.4 — process data; omit ``channels`` to request all."""
        device: dict[str, Any] = {"key": device_key}
        if channels:
            device["channels"] = channels
        result = await self._rpc("GetProcessData", {"devices": [device]})
        return _flatten_channels(result)

    async def parameter_channels(self, device_key: str) -> list[str]:
        """Section 7.5 — installer access required for the full list."""
        passwd = self.credentials.hash_installer() or self.credentials.hash_user()
        result = await self._rpc(
            "GetParameterChannels", {"device": device_key}, passwd=passwd
        )
        return _extract_channel_names(result, device_key)

    async def get_parameters(
        self, device_key: str, channels: list[str] | None = None
    ) -> list[dict[str, Any]]:
        """Section 7.6 — read parameter values; installer for the full set."""
        device: dict[str, Any] = {"key": device_key}
        if channels:
            device["channels"] = channels
        passwd = self.credentials.hash_installer() or self.credentials.hash_user()
        result = await self._rpc(
            "GetParameter", {"devices": [device]}, passwd=passwd
        )
        return _flatten_channels(result)

    async def set_parameter(
        self, device_key: str, channel: str, value: Any
    ) -> list[dict[str, Any]]:
        """Section 7.7 — write a parameter. Installer password is required."""
        passwd = self.credentials.hash_installer()
        if not passwd:
            raise WebBoxError(
                "Installer password is required to write parameters.",
                host=self.host,
            )
        result = await self._rpc(
            "SetParameter",
            {
                "devices": [
                    {
                        "key": device_key,
                        "channels": [{"meta": channel, "value": str(value) if value is not None else value}],
                    }
                ]
            },
            passwd=passwd,
        )
        return _flatten_channels(result)


# ----- helpers -----------------------------------------------------------


def _extract_channel_names(payload: Any, device_key: str | None = None) -> list[str]:
    """Pull the channel-name list out of a ``GetXxxChannels`` response.

    The documented shape is ``{"<device_key>": ["meta1", "meta2", ...]}``
    (sections 7.3 and 7.5). For robustness we also accept a bare list or
    a ``{"channels": [...]}`` dict.
    """
    if isinstance(payload, list):
        return [str(item) for item in payload]
    if isinstance(payload, dict):
        if device_key:
            value = payload.get(device_key)
            if isinstance(value, list):
                return [str(item) for item in value]
        for key in ("channels", "names"):
            value = payload.get(key)
            if isinstance(value, list):
                return [str(item) for item in value]
        # Last resort: if exactly one value is a list, use it.
        lists = [v for v in payload.values() if isinstance(v, list)]
        if len(lists) == 1:
            return [str(item) for item in lists[0]]
    return []


def _flatten_channels(payload: Any) -> list[dict[str, Any]]:
    """Flatten a ``GetProcessData``/``GetParameter`` response.

    The wire shape (sections 7.4 / 7.6) is::

        {"devices": [{"key": ..., "channels": [<Channel>, ...]}, ...]}

    Each Channel object has at minimum ``meta`` and ``value``, optionally
    ``name``, ``unit``, ``min``, ``max`` and ``options`` (section 6.2).
    """
    if not isinstance(payload, dict):
        return []
    devices = payload.get("devices") or []
    out: list[dict[str, Any]] = []
    for device in devices:
        for ch in device.get("channels", []) or []:
            out.append(
                {
                    "name": ch.get("meta") or ch.get("name"),
                    "display_name": ch.get("name"),
                    "value": _coerce_value(ch.get("value")),
                    "unit": ch.get("unit") or None,
                    "min": _coerce_number(ch.get("min")),
                    "max": _coerce_number(ch.get("max")),
                    "options": ch.get("options"),
                }
            )
    return out


def _coerce_value(value: Any) -> Any:
    """WebBox sends numbers as strings; try to recover the native type."""
    if not isinstance(value, str):
        return value
    if value == "":
        return None
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value


def _coerce_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalise_overview(payload: Any) -> dict[str, Any]:
    """Turn the section 7.1 response into ``{meta: {value, unit}}``."""
    if not isinstance(payload, dict):
        return {}
    overview = payload.get("overview")
    if not isinstance(overview, list):
        return {}
    summary: dict[str, Any] = {}
    for item in overview:
        if not isinstance(item, dict):
            continue
        key = item.get("meta") or item.get("name")
        if not key:
            continue
        summary[str(key)] = {
            "value": _coerce_value(item.get("value")),
            "unit": item.get("unit") or None,
            "display_name": item.get("name"),
        }
    return summary


def _normalise_device(device: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": device.get("key"),
        "name": device.get("name") or device.get("key") or "Unknown",
        "channels": device.get("channels"),
        "children": [_normalise_device(c) for c in (device.get("children") or [])],
    }


# ----- subnet scan ---------------------------------------------------------


async def scan_subnet(
    prefix: str, *, concurrency: int = 32, timeout: float = 1.5
) -> list[str]:
    """Probe every host on a /24 for a responsive WebBox ``/rpc`` endpoint."""
    prefix = prefix.strip().rstrip(".")
    if prefix.count(".") != 2:
        raise ValueError("scan prefix must be a /24, e.g. '192.168.1'")

    sem = asyncio.Semaphore(concurrency)
    found: list[str] = []

    probe_body = b"RPC=" + json.dumps({
        "version": "1.0",
        "proc": "GetPlantOverview",
        "id": "scan",
        "format": "JSON",
    }).encode("utf-8")

    # Create client off the event loop to avoid blocking SSL cert load.
    loop = asyncio.get_running_loop()
    client = await loop.run_in_executor(
        None, _create_httpx_client, httpx.Timeout(timeout)
    )
    async with client:
        async def probe(ip: str) -> None:
            async with sem:
                try:
                    r = await client.post(
                        f"http://{ip}/rpc",
                        content=probe_body,
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                    )
                    if r.status_code != 200:
                        return
                    text = r.text.lstrip()
                    if text.startswith("RPC="):
                        text = text[4:]
                    try:
                        body = json.loads(text)
                    except ValueError:
                        return
                    if isinstance(body, dict) and ("result" in body or "error" in body):
                        found.append(ip)
                except Exception:
                    return

        await asyncio.gather(*(probe(f"{prefix}.{n}") for n in range(1, 255)))

    found.sort(key=lambda ip: int(ip.rsplit(".", 1)[-1]))
    return found
