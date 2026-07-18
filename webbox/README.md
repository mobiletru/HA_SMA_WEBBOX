# Sunny Island WebBox

**Home Assistant OS / Supervisor Add-on**

A first-class Home Assistant add-on that gives you a single, modern dashboard for
**SMA Sunny WebBox** RPC + Modbus — live plant data and Sunny Island parameter
tuning for one or more WebBoxes.

## Features

- **Multi-WebBox view** — manage every WebBox on your network from one place.
- **Live plant overview** — KPIs pulled straight from each WebBox.
- **Per-device live data** — every channel reported by every connected
  inverter / Sunny Island / sensor.
- **Parameter editor** — read and (with the installer password) write
  device parameters. Comes with a curated catalog of the most-tuned
  **Sunny Island** parameters (battery type, charge/discharge currents,
  float/boost voltages, grid limits, self-consumption mode, generator
  rules, …) so you get friendly labels, units, ranges, and dropdowns even
  when the WebBox firmware only returns raw `meta` keys.
- **Subnet scan** — point it at a `/24` prefix and it finds every WebBox
  that answers.
- **Home Assistant Ingress** — no exposed port required; click "Open Web
  UI" in the sidebar.
- **Cloudflare Tunnel passthrough** — each WebBox's native web UI is
  reachable from anywhere via its public Cloudflare hostname; no LAN
  access required.

## Installation (local add-on)

This add-on is installed as a **local add-on** — no add-on repository
needed. The Supervisor builds the Docker image directly on your HA host.

1. Enable access to the HA `/addons` folder, e.g. install the
   **Samba share** add-on (or use the **SSH & Web Terminal** add-on /
   `scp`).
2. Copy this entire `webbox` folder to `/addons/webbox` on the HA host,
   so that `/addons/webbox/config.yaml` exists. Do **not** copy the
   repository root — only the `webbox` folder itself.
3. In Home Assistant open **Settings → Add-ons → Add-on Store**, click
   the three-dot menu → **Check for updates** (or reload the page).
4. A new **Local add-ons** section appears at the top with
   **WebBox Dashboard**. Click it → **Install**. The first install
   builds the image locally and can take a few minutes.
5. Optionally pre-seed some WebBoxes from the **Configuration** tab
   (see below), then **Start** the add-on and **Open Web UI**.

To ship an update later: copy the changed files again, bump `version:`
in `config.yaml` (otherwise use the add-on's **Rebuild** button), and
the update will be offered in the add-on page.

## Configuration

```yaml
log_level: info        # trace | debug | info | notice | warning | error | fatal
scan_subnet: "192.168.100"  # optional /24 prefix used as default for "Scan…"
cloudflare_tunnel_token: ""  # paste from Cloudflare Zero Trust → Networks → Tunnels (see below)
webboxes:              # optional pre-seeded list (you can also add WebBoxes from the UI)
  - name: Sunny Island WebBox
    host: 192.168.100.180
    password: "sma"            # WebBox "user" password (read access)
    installer_password: "sma"  # required to write parameters
    poll_interval: 30
    modbus_port: 502
    modbus_unit_id: 3
    modbus_profile: SI6048MBP
    public_url: ""             # optional Cloudflare Tunnel hostname for this WebBox
```

WebBoxes added via the UI are stored in `/data/webboxes.json` and survive
add-on restarts. Anything in the `webboxes:` option block is treated as
seed data.

## Cloudflare Tunnel setup

The dashboard's **Open WebBox ↗** button opens each WebBox's native
web interface via a Cloudflare Tunnel — so you can reach the WebBox
remotely (and over HTTPS) without exposing your LAN. The add-on bundles
[`cloudflared`](https://github.com/cloudflare/cloudflared) and runs it
as a sidecar when a tunnel token is configured.

1. **Create a tunnel.** In the Cloudflare dashboard go to **Zero Trust
   → Networks → Tunnels** and click **Create a tunnel**. Pick
   _Cloudflared_ as the connector, give it a name (e.g. `home-webbox`),
   and on the install screen click **Docker** (or any platform) to
   reveal the tunnel token — the long base64-looking string after
   `--token`. Copy just the token; you don't need to run the docker
   command.
2. **Paste the token.** In Home Assistant open **Settings → Add-ons →
   WebBox Dashboard → Configuration** and paste the token into
   `cloudflare_tunnel_token`. Save and **Restart** the add-on.
3. **Map a public hostname per WebBox.** Back in the Cloudflare tunnel,
   open the **Public Hostnames** tab and **Add a public hostname** for
   every WebBox you want to expose:
   - **Subdomain / domain** — pick a hostname on one of your Cloudflare
     zones (e.g. `webbox-roof.example.com`).
   - **Service** — `HTTP` and the WebBox's LAN address (e.g.
     `192.168.1.42` — no `http://` prefix in the host field).
4. **Tell the dashboard which hostname goes with which WebBox.** Open
   each WebBox in the dashboard, click **Edit**, and paste the full URL
   (e.g. `https://webbox-roof.example.com`) into **Public URL**. Save.
5. **Click Open WebBox ↗.** The button stays disabled until a Public
   URL is set; once it is, clicking it opens the WebBox UI via the
   tunnel.

Notes:

- Add **Cloudflare Access** policies in front of each hostname if you
  want auth (Google / GitHub SSO, one-time PIN, etc.) before the WebBox
  UI loads.
- The tunnel token is stored in the add-on's `/data/options.json` in
  plaintext, the same place HA stores other add-on secrets. Anyone
  with this token can control your tunnel — treat it accordingly.
- On `armhf` (Raspberry Pi 1 / Zero, ARMv6) cloudflared has no upstream
  binary; the add-on logs a warning and skips the tunnel, but the rest
  of the dashboard still works.

## Security notes

- Passwords are stored in plain text inside the add-on's `/data` volume,
  the same place HA stores other add-on state. Treat the add-on directory
  the way you treat any other HA secrets file.
- The dashboard sends the WebBox-style MD5 password digest (`md5("usr" + pw)`
  for the read role, `md5("istl" + pw)` for installer) on every request,
  as expected by the WebBox JSON-RPC API.
- Parameter writes are rejected if no installer password is configured.

## The Sunny Island parameter catalog

The catalog in
[`app/parameters/sunny_island.py`](app/parameters/sunny_island.py) lists
the most commonly tuned installer parameters across the Sunny Island
family. Each entry includes a friendly label, group (Battery, Charging,
Discharging, Inverter, Grid, Energy management, Backup, Generator),
units, sensible min/max, and dropdown options for enumerated values.
Add to it freely — entries are matched by the WebBox `meta` key (and any
`aliases` you list for older firmwares).

## API

The dashboard is just a thin client over the backend's REST API:

| Method | Path | Notes |
| --- | --- | --- |
| `GET`    | `/api/health` | liveness probe |
| `GET`    | `/api/webboxes` | list configured WebBoxes |
| `POST`   | `/api/webboxes` | add a WebBox |
| `PATCH`  | `/api/webboxes/{id}` | edit |
| `DELETE` | `/api/webboxes/{id}` | remove (UI-added only) |
| `GET`    | `/api/webboxes/{id}/status` | online flag + plant overview + devices |
| `GET`    | `/api/webboxes/{id}/devices` | device list |
| `GET`    | `/api/webboxes/{id}/devices/{key}/data` | live process data |
| `GET`    | `/api/webboxes/{id}/devices/{key}/parameters` | enriched parameter list |
| `PUT`    | `/api/webboxes/{id}/devices/{key}/parameters` | `{channel, value}` |
| `POST`   | `/api/webboxes/{id}/devices/{key}/command` | Execute named command or raw `{channel, value}`. Requires installer password. |
| `POST`   | `/api/scan` | `{subnet: "192.168.1"}` — returns responding hosts |
| `GET`    | `/api/catalog/sunny-island` | the curated parameter catalog |
| `GET`    | `/api/commands` | list of high-level named commands (for the app UI and automation) |
| `POST`   | `/api/webboxes/{id}/devices/{key}/command` | `{ "command": "start" }` or raw channel+value. Requires installer password. |

Named commands (e.g. `start`, `stop`, `self_consumption`, `force_full_charge`, `generator_auto_soc`...) are defined in `app/parameters/sunny_island.py` (COMMANDS list) and work in both the add-on API (the "app") and the HACS integration services/buttons.

The dashboard ("the app") has been rebuilt as a proper interactive **Add-on App**:

- Prominent quick Start/Stop buttons in the device header.
- Full **Commands** tab with grouped actions (Inverter, Grid, Energy, Generator, etc.).
- All powered by the shared named commands from the catalog (also available as HA Buttons + `webbox.execute_command` service).

See the Commands tab and `/api/commands` for the current list.

## Development

The backend is plain Python 3.11+ / FastAPI; the UI is a single
`index.html` + vanilla JS. To iterate locally:

```sh
cd webbox
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
WEBBOX_DATA_DIR=/tmp/webbox python -m uvicorn app.main:app --reload --port 8099 --app-dir .
```

Then open <http://localhost:8099/>.

For containerized development, you can build the add-on image directly:

```sh
docker build -t webbox-dashboard:local .
docker run -p 8099:8099 -v webbox-data:/data webbox-dashboard:local
```

### Debug tips

- Set `WEBBOX_LOG_LEVEL=debug` (or `trace`) when running uvicorn to see:
  - Every RPC call with round-trip time
  - Per-device process channel counts
  - Parameter cache hits/misses
  - Full poll timing
- With debug logging enabled the client emits rich diagnostics useful when investigating polling behavior, missing entities, or slow WebBox responses.
- The app supports the `/api/commands` endpoint and per-device command execution for quick actions.

### Docker (standalone / development)

You can build and run the dashboard directly with Docker (useful for testing the container image that the HA add-on uses):

```bash
cd webbox
docker compose up --build
```

Then open http://localhost:8099.

- Persistent data lives in a Docker volume named `webbox-data`.
- Set `WEBBOX_LOG_LEVEL=debug` in `docker-compose.yml` for verbose logs (including the new command execution).
- The compose file also demonstrates the healthcheck.

To build the image manually:

```bash
docker build -t webbox-dashboard:local .
docker run -p 8099:8099 -v webbox-data:/data webbox-dashboard:local
```

Note: When running outside Home Assistant, you configure WebBoxes either through the UI (stored in the volume) or by mounting a custom `options.json`.

See also the `dev.ps1` (Windows native) and the Unix venv instructions above for non-container development.
