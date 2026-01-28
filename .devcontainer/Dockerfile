# PearlAlgo Devcontainer
# Base image with Python 3.12
FROM mcr.microsoft.com/devcontainers/python:3.12

# Install system dependencies for:
# - IBKR Gateway: openjdk-17-jre, xvfb (headless display)
# - Health checks: jq (JSON parsing), iproute2 (ss command for port checks)
# - VNC (optional manual login): tigervnc-standalone-server, xfce4
RUN apt-get update && apt-get install -y --no-install-recommends \
    openjdk-17-jre-headless \
    xvfb \
    jq \
    iproute2 \
    procps \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Optional: Install VNC for manual Gateway login (uncomment if needed)
# RUN apt-get update && apt-get install -y --no-install-recommends \
#     tigervnc-standalone-server \
#     xfce4 xfce4-terminal \
#     && rm -rf /var/lib/apt/lists/*

# Set environment defaults
ENV MPLBACKEND=Agg
ENV JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
ENV PATH="${JAVA_HOME}/bin:${PATH}"

# Create workspace directory
WORKDIR /workspaces/pearlalgo-dev-ai-agents

# The devcontainer.json postCreateCommand handles pip install -e ".[dev,lint]"
