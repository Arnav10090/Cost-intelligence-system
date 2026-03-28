# Single-stage build — asyncpg ships pre-built wheels for Python 3.12,
# so no gcc or libpq-dev needed. Pinned to bookworm (Debian 12 stable)
# to avoid trixie DNS/mirror issues.

FROM python:3.12-slim-bookworm

WORKDIR /app

# Only curl needed for the healthcheck — bookworm repos are stable
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first (better layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Ensure all package __init__.py files exist
RUN touch \
    agents/__init__.py \
    db/__init__.py \
    models/__init__.py \
    routers/__init__.py \
    services/__init__.py \
    services/action_handlers/__init__.py \
    core/__init__.py \
    tests/__init__.py 2>/dev/null || true

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]