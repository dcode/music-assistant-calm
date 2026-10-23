# Official Music Assistant server image + the Calm provider.
#
# Music Assistant only discovers providers inside its own package
# (music_assistant/providers/<domain>), so the provider is copied there and its
# Python requirement is installed into the server's virtualenv at build time.
ARG BUILD_FROM=ghcr.io/music-assistant/server:2.10.7
# hadolint ignore=DL3006
FROM ${BUILD_FROM}

ARG CALM_CLIENT_VERSION=0.2.1

COPY provider/calm /tmp/calm

# hadolint ignore=DL3013
RUN set -eu \
    && SITE_PACKAGES="$(/app/venv/bin/python -c 'import sysconfig; print(sysconfig.get_path("purelib"))')" \
    && test -d "${SITE_PACKAGES}/music_assistant/providers" \
    && rm -rf "${SITE_PACKAGES}/music_assistant/providers/calm" \
    && cp -r /tmp/calm "${SITE_PACKAGES}/music_assistant/providers/calm" \
    && rm -rf /tmp/calm \
    && uv pip install --python /app/venv/bin/python --no-cache "calm-client==${CALM_CLIENT_VERSION}" \
    && /app/venv/bin/python -c "import calm_client, music_assistant.providers.calm"
