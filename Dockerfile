FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8877 \
    BROWSER_HEADLESS=0 \
    CLOAKBROWSER_CACHE_DIR=/opt/cloakbrowser \
    CLOAKBROWSER_AUTO_UPDATE=false \
    CLOAKBROWSER_SUPPRESS_FONT_WARNING=1

# Xvfb for headed browsers on a headless box, plus fonts so fingerprints look like a desktop.
RUN apt-get update && apt-get install -y --no-install-recommends \
        xvfb xauth curl ca-certificates tini \
        fonts-liberation fonts-noto-core fonts-noto-color-emoji fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt "cloakbrowser[geoip]==0.4.12" \
    # Chromium's shared-library deps, then bake the CloakBrowser binary into the image.
    && playwright install-deps chromium \
    && rm -rf /var/lib/apt/lists/* \
    && cloakbrowser install

COPY . .
RUN useradd -m -u 1000 solver \
    && mkdir -p /app/arkose/models \
    && chown -R solver:solver /app /opt/cloakbrowser \
    && chmod +x /app/docker-entrypoint.sh

USER solver
EXPOSE 8877
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:${PORT}/health || exit 1

ENTRYPOINT ["/usr/bin/tini", "--", "/app/docker-entrypoint.sh"]
