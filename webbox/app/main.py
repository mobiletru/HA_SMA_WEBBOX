"""FastAPI app exposing the WebBox dashboard and its REST API."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__
from .modbus import (
    ModbusError,
    available_profiles,
    discover_units,
    read_channels,
    write_channel,
)
from .parameters import COMMANDS, enrich_parameters, get_commands, parameter_catalog
from .storage import Storage
from .webbox_client import (
    WebBoxClient,
    WebBoxCredentials,
    WebBoxError,
    scan_subnet,
)

LOGGER = logging.getLogger("webbox.api")


def _configure_logging() -> None:
    """Configure root + webbox logging based on WEBBOX_LOG_LEVEL (or uvicorn's level).

    This makes local `dev.ps1 -DebugLog` and the add-on run.sh produce
    useful output from our own code (RPCs, polling, errors, etc.).
    """
    level_name = os.environ.get("WEBBOX_LOG_LEVEL", "info").upper()
    level = getattr(logging, level_name, logging.INFO)

    # Make sure our loggers emit at the requested level
    logging.getLogger("webbox").setLevel(level)
    logging.getLogger("webbox.api").setLevel(level)
    logging.getLogger("webbox.client").setLevel(level)

    # Ensure there's at least a basic handler when running outside uvicorn (e.g. direct python -m)
    if not logging.getLogger().handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logging.getLogger().addHandler(handler)
        logging.getLogger().setLevel(level)


_configure_logging()

_STATIC_DIR = Path(__file__).parent / "static"
_DATA_DIR = os.environ.get("WEBBOX_DATA_DIR", "/data")
_OPTIONS_PATH = os.environ.get("WEBBOX_OPTIONS_PATH", os.path.join(_DATA_DIR, "options.json"))

storage = Storage(_DATA_DIR, _OPTIONS_PATH)


def _render_index_html() -> str:
    """Read index.html once and stamp the add-on version into the asset URLs.

    The version-stamped HTML is cached at module load: it never changes
    within a process, so re-running ``read_text`` and two ``str.replace``
    calls on every "/" hit is pure waste.
    """
    html = (_STATIC_DIR / "index.html").read_text(encoding="utf-8")
    return (
        html.replace(
            'href="static/styles.css"', f'href="static/styles.css?v={__version__}"'
        ).replace(
            'src="static/app.js"', f'src="static/app.js?v={__version__}"'
        )
    )


_INDEX_HTML = _render_index_html() if (_STATIC_DIR / "index.html").exists() else ""


app = FastAPI(title="WebBox Dashboard", version=__version__)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ----- request models -----------------------------------------------------


class WebBoxIn(BaseModel):
    name: str | None = None
    host: str
    password: str | None = None
    installer_password: str | None = None
    poll_interval: int | None = Field(default=30, ge=5, le=3600)
    # Public Cloudflare Tunnel URL for the WebBox's native web UI
    # (e.g. "https://webbox.example.com"). Empty when not configured;
    # the "Open WebBox" button is disabled until this is set.
    public_url: str | None = None
    # Modbus TCP settings (WebBox gateway). unit_id 3 is the first device
    # assigned by the WebBox's plant detection.
    modbus_port: int | None = Field(default=502, ge=1, le=65535)
    modbus_unit_id: int | None = Field(default=3, ge=1, le=255)
    modbus_profile: str | None = "SI6048MBP"


class WebBoxPatch(BaseModel):
    name: str | None = None
    host: str | None = None
    password: str | None = None
    installer_password: str | None = None
    poll_interval: int | None = Field(default=None, ge=5, le=3600)
    public_url: str | None = None
    modbus_port: int | None = Field(default=None, ge=1, le=65535)
    modbus_unit_id: int | None = Field(default=None, ge=1, le=255)
    modbus_profile: str | None = None


class ParameterUpdate(BaseModel):
    channel: str
    value: Any


class ScanRequest(BaseModel):
    subnet: str | None = None


class CommandRequest(BaseModel):
    command: str | None = None
    channel: str | None = None
    value: Any | None = None


class ModbusWriteRequest(BaseModel):
    channel: str
    value: Any
    unit_id: int | None = Field(default=None, ge=1, le=255)
    profile: str | None = None
    # must match the stored installer password; Modbus itself is
    # unauthenticated, so the RPC path's password check is replicated here
    installer_password: str | None = None


# ----- helpers ------------------------------------------------------------


def _client_for(webbox: dict[str, Any]) -> WebBoxClient:
    creds = WebBoxCredentials(
        user_password=webbox.get("password") or None,
        installer_password=webbox.get("installer_password") or None,
    )
    return WebBoxClient(webbox["host"], credentials=creds)


def _require(webbox_id: str) -> dict[str, Any]:
    wb = storage.find(webbox_id)
    if not wb:
        raise HTTPException(status_code=404, detail=f"WebBox {webbox_id!r} not found")
    return wb


def _is_options_entry(webbox_id: str) -> bool:
    """True if the WebBox is seeded from the add-on options block."""
    return webbox_id.startswith("opt:")


def _safe(webbox: dict[str, Any]) -> dict[str, Any]:
    """Strip secrets before returning a WebBox config to the UI."""
    out = {k: v for k, v in webbox.items() if k not in ("password", "installer_password")}
    out["has_password"] = bool(webbox.get("password"))
    out["has_installer_password"] = bool(webbox.get("installer_password"))
    return out


# ----- root + static ------------------------------------------------------


if _STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def index() -> Response:
    return Response(content=_INDEX_HTML, media_type="text/html")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> FileResponse:
    icon = _STATIC_DIR / "favicon.svg"
    return FileResponse(icon) if icon.exists() else JSONResponse({}, status_code=204)


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "version": __version__}


# ----- webbox CRUD --------------------------------------------------------


@app.get("/api/webboxes")
async def list_webboxes() -> list[dict[str, Any]]:
    return [_safe(wb) for wb in storage.list_webboxes()]


@app.post("/api/webboxes", status_code=201)
async def create_webbox(payload: WebBoxIn) -> dict[str, Any]:
    try:
        wb = storage.add_webbox(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _safe(wb)


@app.patch("/api/webboxes/{webbox_id}")
async def update_webbox(webbox_id: str, payload: WebBoxPatch) -> dict[str, Any]:
    _require(webbox_id)
    if _is_options_entry(webbox_id):
        raise HTTPException(
            status_code=400,
            detail=(
                "This WebBox is defined in the add-on options. Edit it in "
                "Settings → Add-ons → WebBox Dashboard → Configuration, then restart."
            ),
        )
    try:
        wb = storage.update_webbox(webbox_id, payload.model_dump(exclude_unset=True))
    except KeyError:
        raise HTTPException(status_code=404, detail=f"WebBox {webbox_id!r} not found")
    return _safe(wb)


@app.delete("/api/webboxes/{webbox_id}", status_code=204, response_class=Response)
async def delete_webbox(webbox_id: str) -> Response:
    if _is_options_entry(webbox_id):
        raise HTTPException(
            status_code=400,
            detail="This WebBox is defined in the add-on options; remove it there instead.",
        )
    if not storage.remove_webbox(webbox_id):
        raise HTTPException(status_code=404, detail=f"WebBox {webbox_id!r} not found")
    return Response(status_code=204)


# ----- live data ----------------------------------------------------------


@app.get("/api/webboxes/{webbox_id}/status")
async def webbox_status(webbox_id: str) -> dict[str, Any]:
    wb = _require(webbox_id)
    async with _client_for(wb) as client:
        try:
            overview = await client.plant_overview()
            devices = await client.list_devices()
        except WebBoxError as exc:
            return {
                "online": False,
                "error": str(exc),
                "host": wb["host"],
            }
    return {
        "online": True,
        "host": wb["host"],
        "overview": overview,
        "devices": devices,
    }


@app.get("/api/webboxes/{webbox_id}/devices")
async def webbox_devices(webbox_id: str) -> list[dict[str, Any]]:
    wb = _require(webbox_id)
    async with _client_for(wb) as client:
        try:
            return await client.list_devices()
        except WebBoxError as exc:
            raise HTTPException(status_code=502, detail=str(exc))


@app.get("/api/webboxes/{webbox_id}/devices/{device_key}/data")
async def webbox_device_data(webbox_id: str, device_key: str) -> list[dict[str, Any]]:
    wb = _require(webbox_id)
    async with _client_for(wb) as client:
        try:
            return await client.process_data(device_key)
        except WebBoxError as exc:
            raise HTTPException(status_code=502, detail=str(exc))


@app.get("/api/webboxes/{webbox_id}/devices/{device_key}/parameters")
async def webbox_device_parameters(webbox_id: str, device_key: str) -> list[dict[str, Any]]:
    wb = _require(webbox_id)
    async with _client_for(wb) as client:
        try:
            raw = await client.get_parameters(device_key)
        except WebBoxError as exc:
            raise HTTPException(status_code=502, detail=str(exc))
    return enrich_parameters(raw)


@app.get("/api/catalog/sunny-island")
async def sunny_island_catalog() -> list[dict[str, Any]]:
    """Static catalog of well-known Sunny Island parameters with labels, units, and choices."""
    return parameter_catalog()


@app.get("/api/commands")
async def list_commands() -> list[dict[str, Any]]:
    """Return the list of high-level named commands (built-in + any custom_commands from add-on options)."""
    options = storage.options()
    custom = options.get("custom_commands") or []
    return get_commands(custom)


@app.put("/api/webboxes/{webbox_id}/devices/{device_key}/parameters")
async def webbox_set_parameter(
    webbox_id: str, device_key: str, payload: ParameterUpdate
) -> dict[str, Any]:
    wb = _require(webbox_id)
    if not wb.get("installer_password"):
        raise HTTPException(
            status_code=400,
            detail="Installer password is required to change parameters on this WebBox.",
        )
    async with _client_for(wb) as client:
        try:
            result = await client.set_parameter(device_key, payload.channel, payload.value)
        except WebBoxError as exc:
            raise HTTPException(status_code=502, detail=str(exc))
    return {"status": "ok", "result": result}


@app.post("/api/webboxes/{webbox_id}/devices/{device_key}/command")
async def webbox_execute_command(
    webbox_id: str, device_key: str, payload: CommandRequest
) -> dict[str, Any]:
    """Execute a named command or raw channel+value write.

    Named commands come from the shared catalog (start, stop, self_consumption, etc.).
    Falls back to raw channel/value if provided.
    Requires installer password on the WebBox.
    """
    wb = _require(webbox_id)
    if not wb.get("installer_password"):
        raise HTTPException(
            status_code=400,
            detail="Installer password is required to execute commands on this WebBox.",
        )

    channel = payload.channel
    value = payload.value

    if payload.command:
        options = storage.options()
        custom = options.get("custom_commands") or []
        effective_commands = get_commands(custom)
        cmd = next((c for c in effective_commands if c["name"] == payload.command), None)
        if not cmd:
            available = ", ".join(c["name"] for c in effective_commands)
            raise HTTPException(
                status_code=400,
                detail=f"Unknown command {payload.command!r}. Available: {available}",
            )
        channel = cmd["channel"]
        value = cmd["value"]

    if not channel:
        raise HTTPException(status_code=400, detail="Either 'command' or 'channel' is required.")

    async with _client_for(wb) as client:
        try:
            result = await client.set_parameter(device_key, channel, value)
        except WebBoxError as exc:
            raise HTTPException(status_code=502, detail=str(exc))
    return {"status": "ok", "command": payload.command, "channel": channel, "value": value, "result": result}


# ----- Modbus TCP (WebBox gateway) -----------------------------------------


def _modbus_target(
    wb: dict[str, Any], unit_id: int | None = None, profile: str | None = None
) -> tuple[str, int, int, str]:
    """Resolve (host, port, unit_id, profile) for a WebBox's Modbus gateway.

    The stored host may be an ``http://…`` URL for the RPC API; Modbus
    needs the bare hostname/IP.
    """
    host = wb["host"].strip()
    for prefix in ("http://", "https://"):
        if host.startswith(prefix):
            host = host[len(prefix):]
    host = host.split("/", 1)[0]        # drop any path
    # drop any HTTP port — Modbus has its own. Bracketed IPv6 literals
    # ([fe80::1]:80) keep their colons; a bare IPv6 (multiple colons,
    # no brackets) has no port to strip.
    if host.startswith("["):
        host = host[1:].split("]", 1)[0]
    elif host.count(":") == 1:
        host = host.split(":", 1)[0]
    return (
        host,
        int(wb.get("modbus_port") or 502),
        int(unit_id if unit_id is not None else (wb.get("modbus_unit_id") or 3)),
        profile or wb.get("modbus_profile") or "SI6048MBP",
    )


@app.get("/api/modbus/profiles")
async def modbus_profiles() -> list[dict[str, Any]]:
    """List the SMA Modbus profiles bundled with the add-on."""
    return available_profiles()


@app.post("/api/webboxes/{webbox_id}/modbus/discover")
async def modbus_discover(webbox_id: str) -> dict[str, Any]:
    """Read the gateway's device ↔ unit-ID table (unit ID 1)."""
    wb = _require(webbox_id)
    host, port, _unit, _profile = _modbus_target(wb)
    try:
        devices = await discover_units(host, port)
    except ModbusError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"host": host, "port": port, "devices": devices}


@app.get("/api/webboxes/{webbox_id}/modbus/channels")
async def modbus_read(
    webbox_id: str,
    unit_id: int | None = None,
    profile: str | None = None,
    channels: str | None = None,
) -> dict[str, Any]:
    """Read profile channels over Modbus TCP.

    ``channels`` is an optional comma-separated list of channel names or
    register addresses; omitted = the whole profile in block reads.
    """
    wb = _require(webbox_id)
    host, port, unit, prof = _modbus_target(wb, unit_id, profile)
    selection = [c.strip() for c in channels.split(",") if c.strip()] if channels else None
    try:
        return await read_channels(host, unit, prof, port=port, channels=selection)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc.args[0]))
    except ModbusError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.put("/api/webboxes/{webbox_id}/modbus/channels")
async def modbus_write(webbox_id: str, payload: ModbusWriteRequest) -> dict[str, Any]:
    """Write one writable profile channel over Modbus TCP.

    Modbus itself is unauthenticated. On the RPC path the WebBox verifies
    the installer password itself; to keep the same bar here, the request
    must carry the installer password and it must match the stored one.
    """
    wb = _require(webbox_id)
    stored = wb.get("installer_password")
    if not stored:
        raise HTTPException(
            status_code=400,
            detail="Installer password is required to write parameters via Modbus.",
        )
    if payload.installer_password != stored:
        raise HTTPException(
            status_code=403,
            detail="Wrong installer password.",
        )
    host, port, unit, prof = _modbus_target(wb, payload.unit_id, payload.profile)
    try:
        return await write_channel(host, unit, prof, payload.channel, payload.value, port=port)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc.args[0]))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ModbusError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


# ----- network scan -------------------------------------------------------


@app.post("/api/scan")
async def scan(payload: ScanRequest) -> dict[str, Any]:
    subnet = (payload.subnet or "").strip()
    if not subnet:
        options = storage.options()
        subnet = (options.get("scan_subnet") or "").strip()
    if not subnet:
        raise HTTPException(
            status_code=400,
            detail="No subnet supplied. Pass a /24 prefix like '192.168.1' or set 'scan_subnet' in the add-on options.",
        )
    try:
        found = await scan_subnet(subnet)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"subnet": subnet, "found": found}


