FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    curl \ 
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev

COPY investorai_mcp/ ./investorai_mcp/
COPY alembic.ini ./
COPY scripts/ ./scripts/

RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs

COPY frontend/ ./frontend/
RUN cd frontend && npm ci && npm run build

RUN mkdir -p /data

ENV MCP_TRANSPORT=http

HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=5 \
    CMD curl -f http://localhost:${PORT:-8000}/api/health || exit 1

# Use Railway's dynamic PORT env var
CMD ["sh", "-c", "uv run uvicorn investorai_mcp.server:create_app --factory --host 0.0.0.0 --port ${PORT:-8000}"]
