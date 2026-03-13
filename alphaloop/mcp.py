"""MCP server integration — loads tools from configured MCP servers."""

from __future__ import annotations

import json
from contextlib import AsyncExitStack
from typing import Any

from langchain_core.tools import BaseTool

from alphaloop.config import Config
from alphaloop.logger import get_logger, log_event

logger = get_logger(__name__)


_TRANSPORT_ALIASES: dict[str, str] = {
    "http": "streamable_http",
    "https": "streamable_http",
    "streamable-http": "streamable_http",
}


def normalize_mcp_connection(spec: Any) -> dict[str, Any]:
    """Normalize one MCP connection spec to the shape expected by the adapter."""
    if not isinstance(spec, dict):
        return {}

    normalized = dict(spec)
    if "transport" not in normalized and isinstance(normalized.get("type"), str):
        normalized["transport"] = normalized["type"]

    transport = normalized.get("transport")
    if isinstance(transport, str):
        normalized["transport"] = _TRANSPORT_ALIASES.get(transport.lower(), transport)

    return normalized


def _read_mcp_raw(config: Config) -> dict[str, Any]:
    """Read the raw MCP config document from disk."""
    if config.mcp_config is None or not config.mcp_config.exists():
        return {}
    try:
        data = json.loads(config.mcp_config.read_text())
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.error("mcp.load: failed to parse %s: %s", config.mcp_config, exc)
        return {}


def split_mcp_document(data: dict[str, Any]) -> tuple[dict[str, Any], str | None, dict[str, Any]]:
    """Return ``(connections, wrapper_key, extras)`` for a parsed MCP document."""
    if not isinstance(data, dict):
        return {}, None, {}

    for wrapper_key in ("servers", "mcpServers"):
        wrapped = data.get(wrapper_key)
        if isinstance(wrapped, dict):
            extras = {k: v for k, v in data.items() if k != wrapper_key}
            return wrapped, wrapper_key, extras

    return data, None, {}


def build_mcp_document(
    connections: dict[str, Any],
    *,
    wrapper_key: str | None = None,
    extras: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a serializable MCP document from connections plus optional metadata."""
    extras = extras or {}
    if wrapper_key:
        return {wrapper_key: connections, **extras}
    return connections


def read_mcp_document(config: Config) -> tuple[dict[str, Any], str | None, dict[str, Any]]:
    """Read and normalize the MCP document from disk."""
    return split_mcp_document(_read_mcp_raw(config))


def read_mcp_connections(config: Config) -> dict[str, Any]:
    """Parse the MCP config file and return the server connections dict (or empty dict)."""
    connections, _, _ = read_mcp_document(config)
    return {
        name: normalize_mcp_connection(spec)
        for name, spec in connections.items()
        if isinstance(spec, dict)
    }


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
                        "transport": "streamable_http",
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

    all_tools: list[BaseTool] = []
    loaded_servers: list[str] = []
    failed_servers: list[str] = []

    for name, spec in authed.items():
        try:
            # Isolate each server so one bad config doesn't block all MCP tools.
            client = MultiServerMCPClient({name: spec})
            await stack.enter_async_context(client)
            tools = await client.get_tools()
            all_tools.extend(tools)
            loaded_servers.append(name)
        except Exception as exc:
            failed_servers.append(name)
            logger.error("mcp.load: failed server '%s': %s", name, exc)

    if all_tools:
        log_event(
            logger,
            "mcp.loaded",
            servers=loaded_servers,
            failed=failed_servers,
            tools=[t.name for t in all_tools],
        )
    elif failed_servers:
        logger.error("mcp.load: all configured MCP servers failed: %s", failed_servers)

    return all_tools
