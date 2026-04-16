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

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Force HTTP transport on Railway
ENV MCP_TRANSPORT=http
ENV MCP_HTTP_PORT=8000

CMD ["uv", "run", "uvicorn", "investorai_mcp.server:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
