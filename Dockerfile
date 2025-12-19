# Minimal Dockerfile for running the MNQ Agent service
FROM python:3.12-slim

WORKDIR /app

# System deps (tzdata for correct timezones, curl for basic checks)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata curl && \
    rm -rf /var/lib/apt/lists/*

# Copy project
COPY . /app

# Install in editable-like mode
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -e .[dev]

# Default env (override in docker-compose or runtime)
ENV PYTHONUNBUFFERED=1 \
    PEARLALGO_DATA_PROVIDER=ibkr

# The container expects IBKR Gateway to be reachable via host networking or another container.
# Entrypoint runs the NQ agent service in the foreground.
CMD ["python", "-m", "pearlalgo.nq_agent.main"]
