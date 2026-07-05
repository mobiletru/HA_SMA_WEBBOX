# WebBox Dashboard

Modern dashboard for one or more **SMA Sunny WebBox** data loggers (Sunny Island, Sunny Boy, etc.).

## Installation

1. In Home Assistant, go to **Settings → Add-ons → Add-on Store**.
2. Click the three-dot menu (top right) → **Repositories**.
3. Add this repository URL: `https://github.com/mobiletru/ha_addon_webbox`
4. Find **WebBox Dashboard** in the store and click **Install**.
5. (Optional) Configure options below, then **Start** the add-on.
6. Click **Open Web UI** (or use the sidebar panel).

The add-on runs a FastAPI backend + single-page dashboard. It works great behind Home Assistant Ingress (no ports need to be exposed).

## Configuration

### Options

| Option | Description | Default |
|--------|-------------|---------|
| `log_level` | Logging verbosity (`trace` / `debug` / `info` / ...). Use `debug` when troubleshooting WebBox communication. | `info` |
| `scan_subnet` | Default /24 prefix used by the "Scan…" button (e.g. `192.168.1`). | (empty) |
| `cloudflare_tunnel_token` | Cloudflare Tunnel token (from Zero Trust → Tunnels). Enables the built-in `cloudflared` sidecar for remote access to WebBox UIs. | (empty) |
| `webboxes` | Optional list of WebBoxes to pre-seed. These survive restarts. You can also add WebBoxes from the UI. | `[]` |

Each entry in `webboxes`:

- `name`: Friendly name shown in the UI.
- `host`: IP or hostname of the WebBox (no `http://`).
- `password`: WebBox "user" password (read-only access).
- `installer_password`: Required for reading/writing parameters (highly recommended).
- `poll_interval`: How often to refresh live data (seconds).
- `public_url`: Full HTTPS URL (via Cloudflare Tunnel or other reverse proxy) for the **Open WebBox ↗** button.
- `modbus_port`: Port of the WebBox's Modbus TCP server (default `502`).
- `modbus_unit_id`: Modbus unit ID of the device (default `3`; the WebBox assigns 3+ to detected devices).
- `modbus_profile`: Bundled SMA Modbus profile to use (default `SI6048MBP`, Sunny Island 6048).

Example:

```yaml
webboxes:
  - name: Roof array
    host: 192.168.1.42
    password: ""
    installer_password: "my-installer-pw"
    poll_interval: 30
    public_url: "https://webbox-roof.example.com"
```

### Cloudflare Tunnel (recommended for remote access)

The add-on can run `cloudflared` as a sidecar. This lets you reach each WebBox's native web interface from anywhere without opening ports on your router.

See the full walkthrough in the add-on README (or the dashboard's own help).

High-level steps:
1. Create a Cloudflare Tunnel in Zero Trust.
2. Paste the tunnel token into `cloudflare_tunnel_token`.
3. For each WebBox, create a Public Hostname pointing at the LAN IP of the WebBox.
4. Set the matching `public_url` on each WebBox in the dashboard.
5. The **Open WebBox ↗** button will then work from anywhere.

### Security notes

- Passwords are stored in the add-on's persistent data (`/data`).
- The dashboard uses the standard WebBox MD5-digest authentication (`md5("usr"+pw)` for user, `md5("istl"+pw)` for installer).
- Parameter writes are rejected unless an installer password is configured for that WebBox.
- Treat the add-on data volume the same as any other Home Assistant secret storage.

## Usage

- **Multi-WebBox** support — add as many as you want.
- **Live plant overview** and per-device process data.
- **Parameter editor** with a curated catalog of common Sunny Island settings (battery type, charge currents, voltages, self-consumption modes, generator rules, grid limits, ...).
- **Subnet scan** to discover WebBoxes.
- **Open WebBox** button (via Cloudflare Tunnel when configured).
- **Commands tab** — one-click actions (Start/Stop, grid modes, self-consumption, generator control, force charge cycle, etc.) powered by the shared catalog.

The dashboard is a full interactive **Add-on App**. It is also usable as a thin client over its own REST API (including the new `/api/commands` and per-device `/command` endpoints) if you want to build automations or other frontends.

### Command API

You can execute high-level named commands (or raw parameter writes) via:

`POST /api/webboxes/{webbox_id}/devices/{device_key}/command`

```json
{ "command": "start" }
{ "command": "force_full_charge" }
```

or raw:
```json
{ "channel": "Operation.Mode", "value": "Start" }
```

Requires the installer password for the WebBox. The list of named commands is maintained in `app/parameters/sunny_island.py` (COMMANDS).

## Modbus TCP (direct register access)

Besides the JSON-RPC API, the WebBox (with Modbus firmware) exposes every detected SMA device over **Modbus TCP** on port 502. The dashboard's **Modbus** panel talks to it directly using the official SMA register profile — useful when RPC parameter access is limited, and it is what the Start/Stop and generator controls on a Sunny Island map to at register level (e.g. `ManStr` @ 40009, `GnManStr` @ 40055).

Setup:

1. In the WebBox web UI, enable the Modbus server (**WebBox → External communication → Modbus**) and note the port (default 502).
2. In the dashboard, select the WebBox and click **Discover units** in the Modbus panel — this reads the gateway's device table (unit ID 1) and shows each device's serial and unit ID.
3. Click a discovered unit (or type its ID) and press **Read** to load all profile registers: live measurements (SOC, battery voltage/current, power, generator/grid status, …) and writable parameters (charge currents/voltages, generator limits, manual start/stop, …).
4. Writes require the installer password to be stored for that WebBox (same safety bar as the RPC path — Modbus itself has no authentication).

Profiles live in `app/modbus/profiles/` (currently `SI6048MBP.xml` for the Sunny Island 6048 family, SusyID 69). Drop additional SMA profile XMLs there to support other device families.

### Modbus REST API

- `GET /api/modbus/profiles` — bundled profiles.
- `POST /api/webboxes/{id}/modbus/discover` — read the gateway's unit-ID table.
- `GET /api/webboxes/{id}/modbus/channels?unit_id=3&profile=SI6048MBP&channels=BatSoc,BatVtg` — read registers (omit `channels` for the full profile).
- `PUT /api/webboxes/{id}/modbus/channels` with `{ "channel": "GnManStr", "value": "Start" }` — write a register. Enum channels accept the tag code (`1467`) or its label (`"Start"`); numeric channels accept plain numbers in display units (the FIXn scaling is applied automatically).

## Related

- The companion **HACS custom integration** (`SMA Sunny WebBox`) exposes the same data as native Home Assistant sensors, numbers, and selects. Most users should install both the add-on (for the nice dashboard) and the integration (for Energy dashboard, automations, etc.).

## Add-on Icons (recommended)

For the best appearance in the Add-on Store, add two files in the `webbox/` directory:
- `icon.png` — 128×128 px
- `logo.png` — wider (e.g. 256×128 or similar)

You can place them next to `config.yaml`.

## Support

Report issues at https://github.com/mobiletru/ha_addon_webbox/issues
