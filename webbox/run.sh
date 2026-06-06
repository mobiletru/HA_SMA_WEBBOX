#!/usr/bin/env sh
set -e

CONFIG_PATH=/data/options.json
export WEBBOX_OPTIONS_PATH="${CONFIG_PATH}"
export WEBBOX_DATA_DIR=/data
export WEBBOX_HOST=0.0.0.0
export WEBBOX_PORT=8099

LOG_LEVEL="$(python3 -c 'import json,os;print(json.load(open(os.environ["WEBBOX_OPTIONS_PATH"])).get("log_level","info"))' 2>/dev/null || echo info)"
export WEBBOX_LOG_LEVEL="${LOG_LEVEL}"

CF_TUNNEL_TOKEN="$(python3 -c 'import json,os;print(json.load(open(os.environ["WEBBOX_OPTIONS_PATH"])).get("cloudflare_tunnel_token") or "")' 2>/dev/null || echo "")"

CLOUDFLARED_PID=""

cleanup() {
    if [ -n "$CLOUDFLARED_PID" ]; then
        echo "[webbox] stopping cloudflared (pid $CLOUDFLARED_PID)"
        kill "$CLOUDFLARED_PID" 2>/dev/null || true
    fi
}
trap cleanup TERM INT EXIT

if [ -n "${CF_TUNNEL_TOKEN}" ]; then
    if [ -x /usr/local/bin/cloudflared ]; then
        echo "[cloudflared] starting tunnel"
        /usr/local/bin/cloudflared tunnel --no-autoupdate run --token "${CF_TUNNEL_TOKEN}" &
        CLOUDFLARED_PID=$!
    else
        echo "[cloudflared] tunnel token configured but cloudflared binary is missing on this arch; skipping" >&2
    fi
fi

echo "[webbox] starting dashboard on ${WEBBOX_HOST}:${WEBBOX_PORT} (log_level=${WEBBOX_LOG_LEVEL})"

# Use exec so uvicorn becomes PID 1 and receives signals correctly
exec python3 -m uvicorn app.main:app \
    --host "${WEBBOX_HOST}" \
    --port "${WEBBOX_PORT}" \
    --log-level "${WEBBOX_LOG_LEVEL}" \
    --app-dir /opt/webbox

