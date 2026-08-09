# Stage 0: Build vendored frontend assets (quadlet-lint, see #198)
#
# `copy-assets` is what actually produces the vendored build at
# static/vendor/quadlet-lint/. It normally runs via npm's `postinstall` hook,
# but this stage installs with `--ignore-scripts` so no dependency's own
# lifecycle script can execute during the build, and therefore invokes
# `copy-assets` explicitly. The `mkdir -p` that leads `copy-assets` is
# required here specifically because this stage has no pre-existing
# `static/` directory (unlike a checked-out repo); reordering that script
# so the mkdir isn't first breaks this build while still passing everywhere
# else the tests check. This stage's xterm cp commands also run and land
# in /build/static, but that copy of /build/static is discarded entirely --
# only /build/static/vendor is copied out into the runtime stage below.
FROM node:20-slim AS assets
WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts && npm run copy-assets

# Stage 1: Install dependencies
FROM python:3.12-slim AS builder

WORKDIR /build

# requirements.txt is the pip-compile lock: every direct and transitive
# dependency pinned with hashes. --require-hashes makes a substituted or
# tampered-with PyPI artifact fail the build instead of being installed, and
# --only-binary :all: keeps any sdist's setup.py from executing.
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install \
        --only-binary :all: --require-hashes -r requirements.txt

# Stage 2: Runtime image
FROM python:3.12-slim

WORKDIR /app

COPY --from=builder /install /usr/local

COPY main.py .
COPY requirements.txt .
COPY api/ api/
COPY core/ core/
COPY services/ services/
COPY templates/ templates/
COPY static/ static/
# The production image has no bind mount, so the vendored asset must be
# baked in explicitly from the assets stage. This is separate from (not
# redundant with) the postinstall hook in package.json: postinstall covers
# the host tree that docker-compose.test.yml bind-mounts over this image
# during E2E; this COPY covers the image itself. Both paths are required.
COPY --from=assets /build/static/vendor static/vendor

RUN mkdir -p /data && \
    groupadd -r appuser && useradd -r -g appuser -d /app appuser && \
    chown -R appuser:appuser /app /data && \
    apt-get update && apt-get install -y --no-install-recommends gosu && \
    rm -rf /var/lib/apt/lists/*

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ARG APP_VERSION=dev
ENV APP_VERSION=${APP_VERSION}
ENV QUADLET_CONFIG_PATH=/data/config.yaml
ENV QUADLET_DB_PATH=/data/quadlets.db

EXPOSE 8000

VOLUME /data

# Container starts as root so the entrypoint can fix /data ownership on
# volumes left over from older images, then drops to appuser via gosu
# before the app itself ever runs. See #162.
ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
