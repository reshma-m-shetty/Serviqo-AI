# Serviqo AI - Production Docker Container
FROM python:3.11-slim

# Avoid writing .pyc files and buffer stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV ENVIRONMENT=production
ENV HOST=0.0.0.0
ENV PORT=8000

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code and models
COPY . .

# Expose backend port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Production startup command (dynamically supports cloud hosting PORT variable)
CMD sh -c "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"
