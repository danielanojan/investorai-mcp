# 📈 InvestorAI MCP

AI-native stock research MCP server for retail investors — 11 tools, BYOK AI chat with SSE streaming, sentiment analysis, and a React playground dashboard.

![Python](https://img.shields.io/badge/python-3.11+-blue)
![FastMCP](https://img.shields.io/badge/FastMCP-2.0+-green)
![License](https://img.shields.io/badge/license-Apache%202.0-blue)

---

InvestorAI MCP gives AI assistants structured, grounded access to price history, news, and sentiment for 50 curated blue-chip stocks across 5 sectors. All data comes from a local SQLite cache (or PostgreSQL in production), keeping responses fast and offline-capable. The LLM layer is fully BYOK — bring your own Anthropic, OpenAI, or Groq key. Nothing is ever stored server-side.

## Feature
- **Price History** — Daily OHLCV data for 50 stocks, 7 time ranges (1W → 5Y), adjusted close with split/dividend correction
- **Stock Profiles** — Company name, sector, exchange, market cap for every supported ticker
- **News Feed** — Latest headlines cached from yfinance, refreshed on demand
- **AI Trend Summaries** — LLM-generated narrative with inline citations, multi-stock comparison, sector queries, and natural language date ranges
- **Sentiment Analysis** — AI scores recent headlines positive / negative / neutral with reasoning and key themes
- **Semantic Ticker Search** — Fuzzy search by company name, product keyword, or exact symbol (no embeddings required)
- **Natural Language Dates** — Understands "yesterday", "last Wednesday", "May 2023 to January 2025", "last 54 days"
- **BYOK AI Chat** — Bring your own API key (Claude, OpenAI, Groq) — keys stored in browser localStorage only, never sent to the server
- **SSE Streaming** — Token-by-token response streaming via Server-Sent Events, with live citation and sentiment injection
- **Response Validation** — Configurable strict / warm-only LLM output validation, skipped automatically for news-focused queries
- **Playground Dashboard** — DB health, cache status, Langfuse traces, and latency percentiles in a single React pane
- **Langfuse Observability** — Optional LLM tracing, token counting, and latency monitoring with direct trace links
- **Smart Cache** — Stale-while-available with background refresh; `refresh_ticker` for on-demand live pulls
- **MCP Server** — 11 tools via FastMCP, streamable HTTP + stdio for Claude Desktop / Claude Code / VS Code / Cursor
- **Rate Limiting** — SlowAPI-backed per-minute limiting, configurable per deployment

## Supported Universe

50 stocks across 5 sectors:

| Sector | Count | Tickers |
|---|---|---|
| Technology | 14 | AAPL, MSFT, NVDA, GOOGL, META, AMZN, TSLA, AMD, INTC, ORCL, CRM, ADBE, QCOM, NFLX |
| Finance | 10 | JPM, BAC, GS, MS, V, MA, BRK-B, AXP, WFC, BLK |
| Healthcare | 8 | JNJ, UNH, PFE, ABBV, MRK, LLY, TMO, AMGN |
| Consumer | 10 | WMT, COST, NKE, MCD, SBUX, TGT, HD, DIS, PYPL, SHOP |
| Energy & Industrials | 8 | XOM, CVX, BA, CAT, GE, LMT, NEE, ENPH |

## Quick Start

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

### Install

```bash
# Clone and install
git clone https://github.com/danielanojan/investorai-mcp.git
cd investorai-mcp

# Install with uv (recommended)
uv sync

# Or with pip
pip install -e .
```

### Run

```bash
# HTTP mode — MCP endpoint available at http://localhost:8000/mcp
MCP_TRANSPORT=http uv run investorai-mcp

# stdio mode — for Claude Desktop (no HTTP port)
uv run investorai-mcp
```

> **Note:** First startup may take ~30 seconds — LiteLLM downloads model metadata on first run.

The MCP endpoint is available at [http://localhost:8000/mcp](http://localhost:8000/mcp). This is not a browser UI — connect an MCP client (Claude Code, VS Code, Cursor) to that URL.

### React Frontend (optional)

The frontend is a Vite + React app that talks to the FastAPI BFF on port 8000.

**Terminal 1 — FastAPI backend:**

```bash
uvicorn investorai_mcp.server:create_app --factory --port 8000 --reload
```

**Terminal 2 — React dev server:**

```bash
npm --prefix frontend install
npm --prefix frontend run dev
```

Open [http://localhost:5173](http://localhost:5173) — Vite automatically proxies `/api/*` requests to the backend on port 8000.

### Configuration

Create a `.env` file in the project root:

```env
# Data provider
DATA_PROVIDER=yfinance          # yfinance (default) | alpha_vantage | polygon
ALPHA_VANTAGE_KEY=your_key      # required if DATA_PROVIDER=alpha_vantage
POLYGON_KEY=your_key            # required if DATA_PROVIDER=polygon

# LLM — BYOK (web chat reads from browser localStorage; this is for MCP/server-side use)
LLM_PROVIDER=anthropic          # anthropic | openai | groq
LLM_API_KEY=sk-ant-...
LLM_MODEL=claude-sonnet-4-20250514

# Langfuse (optional — LLM observability + playground analytics)
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=https://cloud.langfuse.com

# MCP transport
MCP_TRANSPORT=http              # stdio (default) | http
MCP_HTTP_PORT=8000
MCP_HTTP_API_KEY=               # optional bearer token for HTTP transport

# Feature flags
AI_CHAT_ENABLED=true
SERVE_STALE_ONLY=false
VALIDATION_MODE=strict          # strict | warm_only

# Rate limiting
RATE_LIMIT_PER_MIN=60

# Logging
LOG_LEVEL=INFO                  # DEBUG | INFO | WARNING | ERROR
LOG_FORMAT=text                 # text | json

# Database
DATABASE_URL=sqlite+aiosqlite:///./investorai.db   # or postgresql+asyncpg://...

# Server
PORT=8000
HOST=0.0.0.0
```

### Graceful Degradation

InvestorAI starts with whatever is configured. Missing keys disable the corresponding feature — no crashes.

| Config | Available | Notes |
|---|---|---|
| None | Price history, statistics, news, search | Zero-config, all data-only tools work |
| `LLM_API_KEY` | + AI summaries, sentiment analysis, chat | Required for `get_trend_summary`, `get_sentiment` |
| `LANGFUSE_*` | + Observability dashboard | Playground shows traces, latency, token usage |
| `DATABASE_URL` (PostgreSQL) | + Production-grade persistence | Railway sets this automatically via addon |

## MCP Client Setup

InvestorAI exposes 11 MCP tools via two transports:

| Transport | How it works | Best for |
|---|---|---|
| Streamable HTTP (`/mcp`) | Client connects to a running InvestorAI server | Claude Code, VS Code, Cursor |
| stdio | MCP client spawns `investorai-mcp` as a child process | Claude Desktop |

### Claude Desktop ✅ Tested

Claude Desktop uses stdio transport — it spawns `investorai-mcp` as a child process.

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "investorai": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/investorai-mcp", "investorai-mcp"],
      "env": {
        "MCP_TRANSPORT": "stdio",
        "LLM_API_KEY": "sk-ant-..."
      }
    }
  }
}
```

After saving, restart Claude Desktop completely. Look for the tools icon — investorai should appear with 11 tools.

### Claude Code ✅ Tested

Claude Code uses streamable HTTP transport — it connects to a running InvestorAI server.

First, start the server in HTTP mode:

```bash
MCP_TRANSPORT=http uv run investorai-mcp
```

Then register the MCP server:

```bash
claude mcp add investorai --transport http http://localhost:8000/mcp
```

Try asking: *"How has NVDA performed over the last year compared to AMD?"*


## Available MCP Tools

| Tool | Description |
|---|---|
| `search_ticker` | Fuzzy semantic search — find any supported ticker by name, keyword, or symbol |
| `get_stock_info` | Company profile — name, sector, exchange, market cap, currency |
| `get_price_history` | Daily OHLCV data for any range (1W / 1M / 3M / 6M / 1Y / 3Y / 5Y) |
| `get_daily_summary` | Pre-computed statistics — return %, high, low, volatility, volume (no LLM) |
| `get_news` | Latest news headlines, cached from provider with on-demand refresh |
| `get_sentiment` | AI-scored news sentiment — positive / negative / neutral with reasoning and key themes |
| `get_trend_summary` | AI narrative summary — supports multi-stock, sector queries, natural language dates, SSE streaming |
| `get_cache_status` | Data freshness diagnostics — TTL status, age, error counts per data type |
| `refresh_ticker` | Force live data refresh, bypassing cache TTL (rate-limited: once per 5 min per ticker) |
| `parse_question` | NLP helper — detect symbols, sector, time range, and dates from free-text questions |
| `get_system_info` | Meta questions — which stocks are supported, sectors, today's date |

> **Always use `search_ticker` first** if you're unsure of a ticker symbol. Never guess — only use tickers confirmed by `search_ticker` or `get_stock_info`.

## API Reference

The FastAPI BFF layer serves the React frontend. The same internal service functions back both the REST API and MCP tools.

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Health check |
| GET | `/tickers` | List all 50 supported tickers |
| GET | `/tickers/search?q=` | Search tickers by name / keyword |
| GET | `/stocks/{symbol}/prices` | Price history (range, price_type params) |
| GET | `/stocks/{symbol}/summary` | Statistical summary |
| GET | `/stocks/{symbol}/news` | Recent news articles |
| GET | `/stocks/{symbol}/sentiment` | AI sentiment score |
| GET | `/stocks/{symbol}/cache` | Cache freshness status |
| POST | `/stocks/{symbol}/refresh` | Force live data refresh |
| POST | `/stocks/{symbol}/trend` | AI trend summary (non-streaming) |
| POST | `/chat` | BYOK chat (non-streaming) |
| POST | `/chat/stream` | BYOK chat with SSE streaming |
| POST | `/llm/validate` | Validate an LLM response against price stats |
| GET | `/monitoring/db` | DB health, cache stats, row counts |
| GET | `/monitoring/langfuse` | Langfuse traces and latency |
| GET | `/monitoring/latency` | Request latency percentiles |

### SSE Streaming Events

The `/chat/stream` endpoint emits the following Server-Sent Events:

| Event type | Payload | Description |
|---|---|---|
| `token` | `{ content: string }` | Incremental LLM response tokens |
| `citations` | `{ citations: Citation[] }` | Source citations (DB dates + news URLs) |
| `stats` | `{ stats: PriceStats }` | Period return, high/low, volatility |
| `sentiment` | `{ sentiment: SentimentResult }` | Single-stock sentiment score |
| `sentiments` | `{ sentiments: Record<string, SentimentResult> }` | Multi-stock sentiment map |
| `done` | — | Stream complete |
| `error` | `{ message: string }` | Stream-level error |

## Architecture Overview

InvestorAI is a Python/FastAPI backend with a React + Vite + Tailwind frontend. The same internal service layer is consumed by four surfaces: the REST API (web UI), the MCP server (11 tools for AI clients), the SSE chat stream, and the monitoring endpoints.

**Data flow:**
1. **yfinance adapter** fetches OHLCV + news from Yahoo Finance on-demand and persists to SQLite
2. **Cache manager** enforces TTLs per data type (prices vs news) and tracks fetch errors
3. **MCP tools** query the SQLite cache and return structured results — no LLM needed for price or news lookups
4. **LiteLLM gateway** (`litellm_client.py`) handles all LLM calls — provider-agnostic, supports Claude / OpenAI / Groq via a single BYOK interface
5. **Response validator** checks LLM output against DB-sourced price stats to catch hallucinated numbers (skipped for news-focused queries where prices in articles may differ from DB aggregates)
6. **Citation extractor** strips inline source markers from LLM responses and returns structured citation objects
7. **Langfuse** wraps each tool invocation as a span via `lf_span()` context manager — zero-overhead when keys are not configured

**Database:** SQLite with aiosqlite (default) or PostgreSQL via asyncpg. Alembic handles schema migrations. Railway's PostgreSQL addon is detected automatically via the `DATABASE_URL` environment variable.

**Frontend:** React 18 + Vite, Tailwind CSS. Components include `PriceChart`, `NewsFeed`, `StatsCard`, `ChatPanel` (with `SentimentBadge` + `SentimentBlock`), `TickerSelector`, `BYOKSetup`, and `MonitoringDashboard`. API keys are stored in browser localStorage only — never sent to the server outside of request headers.

## Playground Dashboard

The `/` route serves the React playground — a unified interface for stock research and system observability.

### Stock Research

- **Ticker Selector** — Browse or search the 50-stock universe by name, keyword, or sector
- **Price Chart** — Interactive OHLCV chart with configurable time range
- **Stats Card** — Period return, high/low, volatility, trading days
- **News Feed** — Latest headlines with source links
- **AI Chat Panel** — BYOK chat that streams token-by-token; shows inline sentiment badges (▲ positive / ▼ negative / ● neutral) with reasoning and key themes

### Monitoring Dashboard

Accessible from the playground header:

- **DB Health** — Table row counts, cache hit/miss, last refresh timestamps per ticker
- **Langfuse Traces** — Last 20 LLM traces with latency, token counts, and direct "View ↗" links to the full Langfuse span tree
- **Latency** — p50 / p95 / p99 request latency across all chat endpoints

Langfuse sections are hidden gracefully when keys are not configured.

## Architectural Decisions

| Decision | Approach | Rationale |
|---|---|---|
| 50-stock curated universe | Hardcoded in `stocks.py` | Eliminates hallucinated tickers. Every response is grounded in supported symbols. `search_ticker` bridges natural language to exact symbols |
| Cache-first, refresh-on-demand | SQLite cache with TTL + `refresh_ticker` | Keeps p95 latency under 200ms for price lookups. LLM latency dominates; DB is never the bottleneck |
| LiteLLM as LLM gateway | Unified API for Claude, OpenAI, Groq | Single tool-calling implementation supports all major providers — swap `LLM_PROVIDER` without code changes |
| Response validation | Compare LLM numbers against DB stats | Catches hallucinated return percentages and price levels. Skipped for news-focused queries where article prices are legitimately different from DB |
| Citation extraction | Inline markers stripped post-generation | Lets the LLM cite sources naturally in its response; structured citation objects are returned separately for UI rendering |
| News-focused path | Parallel `get_news` + `get_sentiment` | Sentiment enriches the prompt before the LLM runs, so the summary reflects pre-scored headlines rather than asking the LLM to score and summarise in one pass |
| Multi-stock via concurrent gather | `asyncio.gather` per symbol | Parallelises DB reads and sentiment calls for comparison queries; scales to full sector queries (~14 stocks) without sequential latency stacking |
| SSE streaming (final-response only) | Full tool-calling loop server-side, only LLM tokens streamed | Avoids complex partial-stream / tool-call interleaving. Tool status goes to structured fields; final reply streams token-by-token |
| BYOK security model | API keys in browser localStorage | Keys never touch the server at rest — sent per-request in the POST body, never logged, never persisted |
| FastMCP dual transport | Streamable HTTP (`/mcp`) + stdio mode | HTTP for remote/web clients, stdio for local desktop clients (Claude Desktop) |
| Langfuse opt-in via `lf_span` | Context manager, no-op when unconfigured | Zero overhead in deployments without Langfuse keys — same code path, observability added by setting two env vars |
| SQLite default, PostgreSQL optional | Detected via `DATABASE_URL` | Zero-config local development. Railway's PostgreSQL addon is a one-click upgrade for production |

## Data Sources

| Source | Data | Key required | Method |
|---|---|---|---|
| Yahoo Finance (yfinance) | OHLCV price history, news headlines, company info | None | HTTP (cached to SQLite) |
| Alpha Vantage | Price history (alternative) | `ALPHA_VANTAGE_KEY` | HTTP (on-demand) |
| Polygon.io | Price history (alternative) | `POLYGON_KEY` | HTTP (on-demand) |
| LiteLLM | LLM routing — Claude, OpenAI, Groq | `LLM_API_KEY` (BYOK) | HTTP (per chat request) |
| Langfuse | LLM observability + trace analytics | `LANGFUSE_PUBLIC_KEY` + `LANGFUSE_SECRET_KEY` | OTEL callbacks + REST reads |

> yfinance is the default and requires no API key. Alternative providers are hot-swappable via `DATA_PROVIDER` without changing any tool code.

## Development

### Setup

```bash
git clone https://github.com/your-username/investorai-mcp.git
cd investorai-mcp
uv sync                  # install all dependencies including dev
cp .env.example .env     # add your API keys
pre-commit install       # ruff, black, gitleaks hooks
```

### Run tests

```bash
uv run pytest                        # full suite (346 tests)
uv run pytest --cov=investorai_mcp   # with coverage report
uv run pytest tests/unit/            # unit tests only
```

### Start dev server

```bash
uv run investorai-mcp
# Frontend dev server (hot reload)
cd frontend && npm install && npm run dev
```

The backend runs on port 8000; the Vite dev server proxies API calls from port 5173.

### Project Structure

```
investorai_mcp/
├── server.py           # FastMCP server + FastAPI app factory
├── config.py           # Pydantic settings (loaded from .env)
├── stocks.py           # Single source of truth for the 50-stock universe
├── calendar.py         # US market calendar — trading hours, holidays
├── tools/              # MCP tools (11 @mcp.tool() decorated functions)
├── api/                # FastAPI router, rate limiting, error handlers
├── data/               # Data adapters (yfinance, alpha_vantage, polygon)
├── db/                 # SQLAlchemy models, Alembic migrations, cache manager
└── llm/                # LiteLLM client, Langfuse tracing, validator, citations
frontend/
└── src/
    ├── components/     # React UI — ChatPanel, PriceChart, MonitoringDashboard…
    └── hooks/          # useChat (SSE), useBYOK
tests/
├── unit/               # Per-tool unit tests with mocked DB and LLM
└── integration/        # End-to-end API tests
```

## Roadmap

| Item | Status |
|---|---|
| 50-stock universe with 5 sectors | ✅ Done |
| Price history (7 time ranges, adj close) | ✅ Done |
| News feed with on-demand refresh | ✅ Done |
| AI trend summary with citations | ✅ Done |
| Multi-stock comparison queries | ✅ Done |
| Sector-wide queries | ✅ Done |
| Natural language date parsing | ✅ Done |
| AI sentiment analysis | ✅ Done |
| BYOK AI chat with SSE streaming | ✅ Done |
| Playground dashboard | ✅ Done |
| Langfuse observability | ✅ Done |
| Response validation (hallucination guard) | ✅ Done |
| Claude Desktop MCP integration | ✅ Tested |
| Claude Code MCP integration | ✅ Tested |
| Railway deployment (PostgreSQL) | ✅ Done |
| VS Code + GitHub Copilot MCP integration |🔜 Planned |
| Cursor MCP integration | 🔜 Planned|
| RAG to capture revevant historical news articles | 🔜 Planned|
| Historical price explanations using past news articles | 🔜 Planned|
| LLM evaluation scripts (offline prompt benchmarking, hallucination rate scoring) | 🔜 Planned |
| Real-time quotes (WebSocket) | 🔜 Planned |
| Earnings calendar integration | 🔜 Planned |
| Expand universe beyond 50 stocks | 🔮 Future |
| Technical indicators (RSI, MACD, Bollinger) | 🔮 Future |


## Contributing

InvestorAI MCP is open source under the Apache 2.0 license. Contributions are welcome:

- 🐛 **Bug reports** — Open an issue with reproduction steps
- 💡 **Feature requests** — Suggest ideas via GitHub Issues
- 🔧 **Pull requests** — Especially welcome in:
  - Additional data provider adapters
  - New MCP tools
  - Test coverage improvements
  - Frontend components

## Disclaimer

InvestorAI MCP is an educational project demonstrating real-time financial data integration, [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) tool-calling patterns, and BYOK AI chat for retail investors.

- Price data is sourced from Yahoo Finance via yfinance. Accuracy and availability are not guaranteed.
- AI-generated summaries and sentiment scores are for informational purposes only and should not be used as sole sources for investment decisions.
- BYOK API keys are stored in browser localStorage only — never persisted server-side.
- This project is not affiliated with any financial institution, brokerage, or data provider.

**Nothing in this project constitutes financial advice.**

## License

Apache 2.0 — see [LICENSE](LICENSE) for details.
