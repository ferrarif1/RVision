ARG PYTHON_BASE_IMAGE=python:3.11-slim
FROM ${PYTHON_BASE_IMAGE}

ARG PIP_INDEX_URL
ARG PIP_EXTRA_INDEX_URL
ARG PIP_TRUSTED_HOST

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN set -eux; \
    PIP_ARGS=""; \
    if [ -n "${PIP_INDEX_URL:-}" ]; then PIP_ARGS="$PIP_ARGS --index-url ${PIP_INDEX_URL}"; fi; \
    if [ -n "${PIP_EXTRA_INDEX_URL:-}" ]; then PIP_ARGS="$PIP_ARGS --extra-index-url ${PIP_EXTRA_INDEX_URL}"; fi; \
    if [ -n "${PIP_TRUSTED_HOST:-}" ]; then PIP_ARGS="$PIP_ARGS --trusted-host ${PIP_TRUSTED_HOST}"; fi; \
    pip install --no-cache-dir $PIP_ARGS -r /app/requirements.txt

COPY agent /app/agent
COPY inference /app/inference

CMD ["python", "-m", "agent.main"]
