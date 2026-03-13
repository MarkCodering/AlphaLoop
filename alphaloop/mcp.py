"""MCP server integration — loads tools from configured MCP servers."""

from __future__ import annotations

import json
from contextlib import AsyncExitStack
from typing import Any

from langchain_core.tools import BaseTool

from alphaloop.config import Config
from alphaloop.logger import get_logger, log_event

logger = get_logger(__name__)


def read_mcp_connections(config: Config) -> dict[str, Any]:
    """Parse the MCP config file and return the connections dict (or empty dict)."""
    if config.mcp_config is None:
        return {}
    if not config.mcp_config.exists():
        return {}
    try:
        return json.loads(config.mcp_config.read_text())
    except Exception as exc:
        logger.error("mcp.load: failed to parse %s: %s", config.mcp_config, exc)
        return {}


async def load_mcp_tools(config: Config, stack: AsyncExitStack) -> list[BaseTool]:
    """Connect to all configured MCP servers and return their LangChain tools.

    The ``MultiServerMCPClient`` is entered into *stack* so its sessions stay
    alive for the full lifetime of the agent (closed when ``stack.aclose()`` is
    called on shutdown).

    Reads server definitions from ``config.mcp_config`` — a JSON file mapping
    server names to connection specs accepted by ``MultiServerMCPClient``.

    Returns an empty list if no config is set, the file is missing, or all
    servers fail to connect.

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
    connections = read_mcp_connections(config)
    if not connections:
        return []

    # Inject stored OAuth tokens as Bearer headers for each server
    from alphaloop.mcp_oauth import get_auth_headers
    authed: dict[str, Any] = {}
    for name, spec in connections.items():
        merged = dict(spec)
        headers = get_auth_headers(name)
        if headers:
            existing = merged.get("headers", {}) or {}
            merged["headers"] = {**existing, **headers}
        authed[name] = merged

    from langchain_mcp_adapters.client import MultiServerMCPClient

    try:
        client = MultiServerMCPClient(authed)
        # Enter into the caller's stack — keeps all server sessions open until
        # the agent shuts down.
        await stack.enter_async_context(client)
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
