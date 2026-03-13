"""MCP server integration — loads tools from configured MCP servers."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import BaseTool

from alphaloop.config import Config
from alphaloop.logger import get_logger, log_event

logger = get_logger(__name__)


async def load_mcp_tools(config: Config) -> list[BaseTool]:
    """Return LangChain tools from all configured MCP servers.

    Reads server definitions from ``config.mcp_config`` (a JSON file mapping
    server names to connection specs accepted by ``MultiServerMCPClient``).

    Returns an empty list if no config is set or the file is missing.

    Example ``~/.alphaloop/mcp.json``::

        {
          "filesystem": {
            "transport": "stdio",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
          },
          "myserver": {
            "transport": "http",
            "url": "http://localhost:8000/mcp"
          }
        }
    """
    if config.mcp_config is None:
        return []

    if not config.mcp_config.exists():
        logger.warning("mcp.load: config file not found: %s", config.mcp_config)
        return []

    try:
        connections: dict[str, Any] = json.loads(config.mcp_config.read_text())
    except Exception as exc:
        logger.error("mcp.load: failed to parse %s: %s", config.mcp_config, exc)
        return []

    if not connections:
        return []

    from langchain_mcp_adapters.client import MultiServerMCPClient

    try:
        async with MultiServerMCPClient(connections) as client:
            tools = await client.get_tools()
        log_event(
            logger,
            "mcp.loaded",
            servers=list(connections.keys()),
            tools=[t.name for t in tools],
        )
        return tools
    except Exception as exc:
        logger.error("mcp.load: failed to connect to MCP servers: %s", exc)
        return []
