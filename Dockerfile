# Use Python 3.11 slim image for smaller size
FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    jq \
    bash \
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Copy dependency files
COPY pyproject.toml ./
COPY setup.py ./
COPY MANIFEST.in ./
COPY README.md ./

# Copy application code (needed for setup.py to read version)
COPY amebo/ ./amebo/

# Install build dependencies and build the package
RUN pip install --no-cache-dir build && \
    python -m build && \
    pip install --no-cache-dir dist/*.whl && \
    rm -rf dist/ build/ *.egg-info/

# Create a non-root user
RUN useradd --create-home --shell /bin/bash amebo && \
    chown -R amebo:amebo /app

# Switch to non-root user
USER amebo

# Expose the default port
EXPOSE 3310

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${AMEBO_PORT:-3310}/v1/applications || exit 1

# Default command
CMD ["amebo"]