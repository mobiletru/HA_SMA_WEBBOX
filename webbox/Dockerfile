ARG BUILD_FROM
ARG BUILD_ARCH=amd64
FROM ${BUILD_FROM}

# Standard Home Assistant add-on environment
ENV LANG=C.UTF-8 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/opt/webbox

RUN apk add --no-cache \
        python3 \
        py3-pip \
        ca-certificates \
        wget

WORKDIR /opt/webbox

# Python dependencies first for better layer caching
COPY requirements.txt .
RUN pip3 install --break-system-packages -r requirements.txt

# cloudflared sidecar (for Cloudflare Tunnel remote WebBox UI access)
# The add-on starts it in the background when a token is configured.
# Use --build-arg CLOUDFLARED_VERSION=2025.5.0 for reproducible builds.
ARG CLOUDFLARED_VERSION=latest
ARG BUILD_ARCH
RUN set -eu; \
    case "${BUILD_ARCH}" in \
        amd64)   CF_ARCH=amd64 ;; \
        aarch64) CF_ARCH=arm64 ;; \
        *) \
            echo "[cloudflared] ${BUILD_ARCH} has no upstream binary; skipping" >&2; \
            exit 0 ;; \
    esac; \
    if [ "${CLOUDFLARED_VERSION}" = "latest" ]; then \
        CF_URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${CF_ARCH}"; \
    else \
        CF_URL="https://github.com/cloudflare/cloudflared/releases/download/${CLOUDFLARED_VERSION}/cloudflared-linux-${CF_ARCH}"; \
    fi; \
    apk add --no-cache --virtual .cf-deps wget; \
    wget -q -O /usr/local/bin/cloudflared "${CF_URL}"; \
    chmod +x /usr/local/bin/cloudflared; \
    apk del .cf-deps; \
    /usr/local/bin/cloudflared --version || true

# Application code
COPY app ./app
COPY run.sh /run.sh
RUN chmod a+x /run.sh

# The app exposes its own health endpoint used by the add-on watchdog
EXPOSE 8099

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD wget -q --spider http://127.0.0.1:8099/api/health || exit 1

CMD ["/run.sh"]
