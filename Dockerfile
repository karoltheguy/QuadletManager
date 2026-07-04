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
COPY api/ api/
COPY core/ core/
COPY services/ services/
COPY templates/ templates/
COPY static/ static/

RUN mkdir -p /data && \
    groupadd -r appuser && useradd -r -g appuser -d /app appuser && \
    chown -R appuser:appuser /app /data

ENV QUADLET_CONFIG_PATH=/data/config.yaml
ENV QUADLET_DB_PATH=/data/quadlets.db

EXPOSE 8000

VOLUME /data

USER appuser

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
