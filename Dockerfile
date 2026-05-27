FROM python:3.11-slim

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app
COPY . .

# Create non-root user
RUN useradd -m -s /bin/bash hibachi && chown -R hibachi:hibachi /app
USER hibachi

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8080/api/state || exit 1

# Default: grid strategy (overridable via CMD)
ENTRYPOINT ["python", "main.py"]
CMD ["--strategy", "grid"]
