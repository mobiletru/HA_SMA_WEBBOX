# SMA Sunny WebBox for Home Assistant

A Home Assistant **custom integration** (installable via HACS) for SMA
Sunny WebBox data loggers and the inverters / Sunny Islands attached to
them. Each WebBox becomes a hub device, every device on the WebBox bus
becomes a child device, and every channel becomes a native HA entity:

- **Sensors** for plant overview and per-device live process data.
- **Number entities** for writable numeric parameters (battery
  capacity, max charge / discharge current, float / boost voltages,
  grid limits, generator thresholds, …).
- **Select entities** for enumerated parameters (battery type, operating
  mode, self-consumption mode, generator auto-start mode, …).
- **`webbox.set_parameter` service** for anything not in the curated
  catalog.

The integration ships with a curated catalog of **33 well-known Sunny
Island parameters** across Battery / Charging / Discharging / Inverter /
Grid / Energy management / Backup / Generator groups, with friendly
labels, units, ranges, and dropdown options — so the entities have the
right metadata even when WebBox firmware only returns raw `meta` keys.

## Install via HACS

1. In Home Assistant, open **HACS → Integrations**.
2. Top right menu → **Custom repositories** → add this repository URL
   with category **Integration**.
3. Find **SMA Sunny WebBox** in the HACS Integrations list, click
   **Download**, then restart Home Assistant.
4. **Settings → Devices & services → Add integration → SMA Sunny WebBox**.
5. Enter the WebBox host/IP and (optionally) the user / installer
   passwords.

The installer password is what unlocks read+write of device parameters;
without it the integration only exposes live process-data sensors.

### Commands for Parameters

The integration (and add-on) now provide convenient **named commands** on top of the raw parameter catalog.

**In the HACS custom integration:**
- **Button entities** for common actions (Start, Stop, Self-Consumption, Generator modes, Force Full Charge, etc.).
- Dedicated services:
  - `webbox.start` / `webbox.stop`
  - `webbox.execute_command` (name + device_id) — the most flexible
  - `webbox.set_parameter` for advanced use

See `examples/commands.yaml` for many ready-to-use automation and script examples.

**In the HA OS Add-on (dashboard + API):**
- The same named commands are available via the REST API:
  `POST /api/webboxes/{id}/devices/{device_key}/command`
  with body `{"command": "start"}` or `{"command": "force_full_charge"}`.
- This makes it easy to build quick-action buttons in the dashboard or call from external tools.
- The full list of commands lives in `parameters/sunny_island.py` (COMMANDS) so the integration and add-on stay in sync.

All commands are driven from the curated Sunny Island catalog — add new ones there and they become available everywhere.

## Manual install

If you don't use HACS, copy `custom_components/webbox/` into your HA
config's `custom_components/` directory and restart.

## Options

After adding a WebBox, **Configure** lets you tune:

- *Process-data poll interval* (default 30 s) — how often live sensors
  refresh.
- *Parameter refresh interval* (default 300 s) — how often writable
  number/select entities re-read their values from the WebBox.

## Service: `webbox.set_parameter`

```yaml
service: webbox.set_parameter
data:
  device_id: !input device
  device_key: SI-44M:1234567890
  channel: Bat.ChaCapNom
  value: 200
```

Use this for parameters that aren't covered by the catalog yet, or for
scripted bulk changes.

## Extending the Sunny Island catalog

The catalog is plain Python — see
[`custom_components/webbox/parameters/sunny_island.py`](custom_components/webbox/parameters/sunny_island.py).
Each entry is a `ParameterSpec(key, label, group, unit, type, min, max,
step, options, writable, description, aliases)`. Add entries you care
about and HA will create the matching number/select entity on the next
reload.

## WebBox Dashboard Add-on (Home Assistant OS / Supervisor)

This repository also provides a first-class **Home Assistant OS add-on**
that gives you a beautiful, self-contained modern dashboard for your
WebBoxes:

- Multi-WebBox management
- Live data + full parameter editor with the Sunny Island catalog
- Subnet scanning
- Optional Cloudflare Tunnel passthrough for remote native WebBox UI access
- Ingress support (no exposed ports required)

The add-on is **fully supported** and works great alongside (or instead of)
the HACS custom integration.

**To install the add-on:**

1. Go to **Settings → Add-ons → Add-on Store** in Home Assistant.
2. Add this repository as a custom repository:  
   `https://github.com/mobiletru/HA_SMA_WEBBOX`
3. Install **WebBox Dashboard**, configure (optional), and start it.
4. Use **Open Web UI** or the sidebar panel.

Full documentation, configuration reference, and Cloudflare Tunnel setup
are in [`webbox/DOCS.md`](webbox/DOCS.md) and [`webbox/README.md`](webbox/README.md).

Most users install **both** the add-on (great dashboard + parameter tuning)
**and** the HACS integration (native sensors, Energy dashboard, automations).
