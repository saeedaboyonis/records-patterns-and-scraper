# Dockerfile for Dono Data Engineer Assessment
# Uses Python slim for minimal image size

FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for layer caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY src/ ./src/
COPY outputs/ ./outputs/

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash appuser && \
    chown -R appuser:appuser /app

USER appuser

# Default command (can be overridden)
CMD ["python", "-m", "src.pattern_analyzer", "--help"]
