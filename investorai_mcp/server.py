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
    
async def _main() -> None:
    logging.basicConfig(level=settings.log_level)
    logger.info("InvestorAi starting", version="0.1.0")
    
    await init_db()
    logger.info("Database ready")
    
    _register_tools()
    tools = await mcp.list_tools()
    logger.info("Tools registered", count=len(tools))
    
    if settings.mcp_transport == "stdio":
        await _start_mcp_stdio()
    elif settings.mcp_transport == "http":
        await _start_mcp_http()

# regular function - just calls asyncio.run(). asyncio.run() is sync function.
# asyncio.run() starts the event loop. 
# We want to call asyncio.run() from a regular function because this allows us to run the server without requiring the caller to manage the event loop. 
# By providing a simple synchronous entry point, we make it easier for users to start the server without needing to understand the complexities of async code.        
def cli() -> None:
    """Entry point for running the MCP server registered in pyproject.yaml"""
    asyncio.run(_main())
 
if __name__ == "__main__":
    cli()
    