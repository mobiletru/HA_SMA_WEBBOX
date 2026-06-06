# Changelog

## 0.4.0

**Major add-on improvements** — the WebBox Dashboard is now a first-class,
well-packaged Home Assistant OS / Supervisor add-on (no longer considered legacy).

- Added `webbox/DOCS.md` (shown in the Add-on Store).
- Added `webbox/translations/en.yaml` for friendly labels and help text in the add-on configuration UI.
- Added `watchdog` using the existing `/api/health` endpoint.
- Added `config:rw` map.
- Improved `Dockerfile` (better caching, HEALTHCHECK, clearer cloudflared handling, PYTHONPATH).
- Improved `build.yaml` (more labels, `io.hass.*` annotations, args).
- Improved `run.sh` (proper signal handling / cleanup for the cloudflared sidecar).
- Updated root README and repository metadata to promote the add-on properly.
- Bumped add-on version to 0.4.0.
- Local development: `webbox/dev.ps1 -DebugLog` + VS Code launch configs make it easy to work on the add-on code.

## 0.2.1

- Fix WebBox authentication / RPC for firmwares that require the
  legacy form-encoded transport. Requests are now sent as
  ``RPC=<json>`` with ``Content-Type: application/x-www-form-urlencoded``,
  and responses are accepted with or without an ``RPC=`` prefix.
  Without this, ``POST /rpc`` could land on the WebBox's HTML login
  page (or the WebBox would silently ignore the request), so logins
  appeared to fail and parameter writes (e.g. ``BatChrgCurMax``) had
  no effect. Affects the add-on dashboard client, the HACS integration
  client, and the subnet-scan probe.

## 0.2.0

**Breaking** — the in-process `/proxy/{webbox_id}/…` reverse proxy is
gone. Remote access to each WebBox's native web UI now flows through a
Cloudflare Tunnel that runs as a `cloudflared` sidecar inside the add-on
container.

- Add-on container now bundles `cloudflared` (downloaded from upstream
  GitHub releases per arch; `armhf` / unknown archs skip the install).
- New top-level add-on option `cloudflare_tunnel_token` (password). When
  set, `run.sh` starts `cloudflared tunnel --no-autoupdate run --token …`
  in the background before launching uvicorn.
- New per-WebBox field `public_url` (also in the add-on options schema).
  The **Open WebBox ↗** button now opens this URL in a new tab. The
  button is disabled with an explanatory tooltip when `public_url` is
  empty.
- Removed: `/proxy/{webbox_id}/{path}` route and all the HTML / CSS
  rewriting, cookie re-scoping, and redirect-rewriting helpers that
  supported it; the FastAPI lifespan that held a long-lived `httpx`
  client; the `re` / `httpx` / `RedirectResponse` / `StreamingResponse`
  imports in `app/main.py`.
- See the README's "Cloudflare Tunnel setup" section for the dashboard
  walkthrough.

## 0.1.6

- Add a reverse-proxy passthrough so the WebBox's native web UI is
  reachable through the add-on (and therefore through HA Ingress / any
  reverse proxy fronting HA).
  - `GET|POST|... /proxy/{webbox_id}/{path}` forwards method, body,
    headers, and query string to `http://<webbox-host>/<path>`.
  - HTML responses get `<base href="/proxy/{id}/">` injected and all
    root-relative `href` / `src` / `action` / `formaction` attributes
    are rewritten so static assets, form posts, and frames keep working.
  - CSS `url(/...)` references are rewritten the same way.
  - `Set-Cookie` headers have their `Domain` attribute stripped and
    `Path` re-scoped to the proxy prefix, so the WebBox's session
    cookie binds to the HA host and survives the round-trip.
  - 3xx `Location` headers with absolute paths are rewritten.
  - Dashboard adds an **Open WebBox ↗** button that opens
    `proxy/<id>/` in a new tab.
- New dependency: `httpx` is already pulled in transitively, no
  changes to `requirements.txt`.

## 0.1.5

- After saving a WebBox the main view now re-renders immediately, so the
  "installer password ✓" badge shows up the moment the password is stored
  on disk — even when the WebBox itself isn't reachable yet. Previously
  `probeStatus`'s offline-catch branch only repainted the sidebar, so
  the header subtitle kept showing the stale (pre-save) state and it
  looked like the password hadn't been saved.
- Cache-bust `app.js` / `styles.css` with `?v=<addon-version>` so
  browsers stop serving the prior version's UI after an add-on rebuild.

## 0.1.4

- Make password handling in the WebBox modal less confusing:
  - The subtitle now shows "user password ✓" / "installer password ✓"
    badges when secrets are stored, so users have feedback that the
    password really did save (the form intentionally never re-sends
    stored secrets, which previously looked like "didn't save").
  - On Edit, the password inputs get a "(saved — leave blank to keep)"
    placeholder; on Add they stay blank.
  - The Edit button is disabled (with a tooltip explaining where to
    edit it) for WebBoxes that come from the add-on options — those
    edits would silently 404 before because `update_webbox` only knew
    about user-added state.
  - The PATCH endpoint now returns a clear 400 for `opt:` IDs, matching
    the DELETE behavior.

## 0.1.3

- Dashboard now disables the "Delete" button (with an explanatory tooltip)
  for WebBoxes seeded from the add-on `webboxes:` options block.
  Previously the click hit `DELETE /api/webboxes/opt:<host>` and the
  server correctly answered HTTP 400 *"This WebBox is defined in the
  add-on options; remove it there instead"*, but the disabled-state
  feedback wasn't there.

## 0.1.2

- Bring the JSON-RPC client in line with the *Sunny WebBox RPC User Manual*
  v1.4 (SWebBoxRPC-BA-en-14):
  - `passwd` is now sent as a top-level request field (section 4.1) rather
    than nested inside `params`, so authenticated calls actually reach the
    installer access level.
  - The MD5 digest is `md5(password)` only — the previous `md5(role+password)`
    form was speculative and produced digests the WebBox would never accept.
  - `omit passwd` entirely when no credentials are configured, matching the
    spec's "no passwd ⇒ user level" default.
  - Channel-name extractor handles the documented
    `{"<device_key>": [...]}` shape returned by `GetProcessDataChannels` /
    `GetParameterChannels` (sections 7.3 / 7.5).
- `GetProcessData` / `GetParameter` now omit the `channels` selection so
  the WebBox returns every available channel in a single call (sections
  7.4 / 7.6) — one fewer round-trip per device per poll.
- Values returned as strings (the WebBox always does this) are coerced
  back to int / float for downstream consumers.

## 0.1.1

- Fix add-on failing to start on FastAPI ≥0.112: the `DELETE
  /api/webboxes/{id}` route now declares a bodyless `Response` class so
  FastAPI no longer asserts at import time that "status code 204 must
  not have a response body".

## 0.1.0

- Initial release.
- Multi-WebBox dashboard with live plant overview, per-device process data,
  and a parameter editor.
- Curated Sunny Island parameter catalog (Battery, Charging, Discharging,
  Inverter, Grid, Energy management, Backup, Generator groups) with
  friendly labels, units, ranges, and enum options.
- Subnet scan to discover WebBoxes on a `/24`.
- Home Assistant Ingress support.
