import asyncio
import logging

import structlog
from fastmcp import FastMCP

from investorai_mcp.config import settings
from investorai_mcp.db import init_db

logger = structlog.get_logger()

"""
MCP - gives structured access to information and actions. USB-C for AI. Creates std way for models to interact with servers which have real-world data.
MCP can do three main things. 
1. Expose data as resources (similar to GET endpoints)
2. Provide actions through tools (similar to POST endpoints)
3. Define prompts which guide the model interact with data or users. 

Components of MCP:
1. MCP hosts - Apps like Claude Desktop, IDE or AI tools which use MCP to access data. 
2. MCP Clients - Protocol clients which establish 1:1 connection with servers. 
3. MCP Servers - Lightweight programs which expose specific capabilities via MCP. 
4. Local data sources - DB and services in machins which MCP servers can securely access. 
5. Remote services - APIs and external data sources available over internet. 

Conencting LLM to MCP server will give power to use your own data and logic in real time. 
You can write custom tools which the model can call to get data or perform actions.

FastMCP - simplify implementation of MCP. You can build clients and servers faster. 

What's fastMCP? - A python SDK which implement full MCP specification
1. Define tools with @mcp.tool() decorator.
2. Run server with mcp.run() - supports stdio and http transports.
3. FastMCP handles serialization, transport, and protocol details. You just write the logic for your tools.

You can build MCP clients which can connect to any MCP server. 
You can create MCP servers to expose prompts, tools and data sources. 
It uses standard transports like Stdio and HTTP, so it's flexible for different use cases.

@tool - used to call an external function such as fetching weather from an API. 
@resource - decorator used to expose stored data - such as user profile or stock price history.
@prompt - stcuturing the response format - you can define predefined respose templates. 


"""



mcp = FastMCP(
    name="investorai",
    instructions=""" You are a stock research assistant for retail investors.
    You have access to daily price history, news and AI summaries for 50 selected stocks. 
    Always use search_ticker first if you are unsure of a ticker symbol.
    Never guess ticker symbols - only use tickers confirmed by search_ticker or get_ticker_info tools.
    Do not answer questions about the stocks outside the supported universe.
    """,
    
)

#regular def - no await inside its just imports
def _register_tools():
    """import all tool modules so their @mcp.tool() decorators fire"""
    from investorai_mcp.tools import search_ticker    # noqa: F401
    from investorai_mcp.tools import get_stock_info   # noqa: F401
    from investorai_mcp.tools import get_price_history # noqa: F401
    from investorai_mcp.tools import get_daily_summary # noqa: F401
    from investorai_mcp.tools import get_cache_status  # noqa: F401
    from investorai_mcp.tools import refresh_ticker     # noqa: F401
    from investorai_mcp.tools import get_news
    from investorai_mcp.tools import get_trend_summary    # noqa: F401
    from investorai_mcp.tools import get_sentiment        # noqa: F401
    from investorai_mcp.tools import parse_question       # noqa: F401
    from investorai_mcp.tools import get_system_info      # noqa: F401
    
async def _start_mcp_stdio() -> None:
    logger.info("Starting MCP server", transport="stdio")
    await mcp.run_async(transport="stdio")
    
async def _start_mcp_http() -> None:
    logger.info(
        "Starting MCP server",
        transport="http",
        port=settings.mcp_http_port,
    )
    
    await mcp.run_async(
        transport="streamable-http",
        host="0.0.0.0",
        port=settings.mcp_http_port,
    )


### FastAPI app factory -----------------------------------


def create_app():
    from contextlib import asynccontextmanager
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse
    from slowapi.errors import RateLimitExceeded
    from slowapi.middleware import SlowAPIMiddleware
    from pathlib import Path

    from investorai_mcp.api.error_handler import rate_limit_handler
    from investorai_mcp.api.rate_limit import limiter
    from investorai_mcp.api.router import router

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await init_db()
        logger.info("Database ready")
        yield

    app = FastAPI(
        title="InvestorAI BFF",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS — allow React dev server in development + production domain via env var
    import os
    _extra_origin = os.environ.get("ALLOWED_ORIGIN", "")
    _origins = ["http://localhost:5173", "http://localhost:3000"]
    if _extra_origin:
        _origins.append(_extra_origin)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Rate limiting
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)
    app.add_exception_handler(RateLimitExceeded, rate_limit_handler)

    # API routes
    app.include_router(router)

    # Serve React build in production
    frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"
    if frontend_dist.exists():
        app.mount("/assets", StaticFiles(directory=str(frontend_dist / "assets")), name="assets")

        @app.get("/{full_path:path}")
        async def serve_spa(full_path: str):
            # API routes are handled above — this catches everything else
            index = frontend_dist / "index.html"
            return FileResponse(str(index))

    return app
    
    
async def _main() -> None:
    logging.basicConfig(level=settings.log_level)
    logger.info("InvestorAI starting", version="0.1.0")

    await init_db()
    logger.info("Database ready")

    _register_tools()
    logger.info("Tools registered")

    # On Railway, always run HTTP transport
    import os
    if os.environ.get("RAILWAY_ENVIRONMENT") or settings.mcp_transport == "http":
        await mcp.run_async(
            transport="streamable-http",
            host="0.0.0.0",
            port=int(os.environ.get("PORT", settings.mcp_http_port)),
        )
    else:
        await _start_mcp_stdio()

# regular function - just calls asyncio.run(). asyncio.run() is sync function.
# asyncio.run() starts the event loop. 
# We want to call asyncio.run() from a regular function because this allows us to run the server without requiring the caller to manage the event loop. 
# By providing a simple synchronous entry point, we make it easier for users to start the server without needing to understand the complexities of async code.        
def cli() -> None:
    """Entry point for running the MCP server registered in pyproject.yaml"""
    asyncio.run(_main())
 
if __name__ == "__main__":
    cli()
    