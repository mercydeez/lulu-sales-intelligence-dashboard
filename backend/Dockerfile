FROM python:3.14-slim

WORKDIR /app

# Install system dependencies (best-effort; all Python deps ship binary wheels,
# so a flaky Debian mirror shouldn't block the build)
RUN (apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*) || echo "skipping optional build deps"

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser appuser

# Copy requirements first for caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Set ownership and switch to non-root user
RUN chown -R appuser:appuser /app
USER appuser

# Expose port (documentation only; the runtime port comes from $PORT below)
EXPOSE 8000

# Run the application.
#
# SHELL FORM, ON PURPOSE. Managed/free-tier hosts (Render, Railway, Fly, Cloud
# Run) assign a port at boot and inject it as $PORT, then route only to that
# port. The previous exec-form CMD hardcoded 8000, so the container listened
# somewhere the platform never routed to and every request 502'd while the app
# itself looked perfectly healthy in its own logs.
#
# Shell form is what expands $PORT. Defaults to 8000 so docker-compose, which
# sets no PORT and maps 8000 explicitly, behaves exactly as before.
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}