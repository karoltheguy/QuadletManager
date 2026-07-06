# Stage 1: Install dependencies
FROM python:3.12-slim AS builder

WORKDIR /build

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Stage 2: Runtime image
FROM python:3.12-slim

WORKDIR /app

COPY --from=builder /install /usr/local

COPY main.py .
COPY requirements.txt .
COPY VERSION .
COPY api/ api/
COPY core/ core/
COPY services/ services/
COPY templates/ templates/
COPY static/ static/

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
