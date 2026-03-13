"""AlphaLoop agent factory — builds deepagents with pluggable model providers."""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from typing import Any

from langchain_core.messages import HumanMessage
from langchain_ollama import ChatOllama
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph.state import CompiledStateGraph

from alphaloop.config import Config, get_config
from alphaloop.logger import get_logger, log_event

logger = get_logger(__name__)


def _with_v1_path(base_url: str) -> str:
    """Return an OpenAI-compatible base URL that ends with /v1."""
    trimmed = base_url.rstrip("/")
    return trimmed if trimmed.endswith("/v1") else f"{trimmed}/v1"


def _build_model(config: Config) -> Any:
    """Instantiate the configured chat model provider from config."""
    provider = config.provider

    if provider == "ollama":
        return ChatOllama(
            model=config.model,
            base_url=config.ollama_base_url,
            # Keep temperature low for consistent, goal-driven behaviour
            temperature=0.1,
            # Thinking models may need more time to respond
            timeout=120,
        )

    if provider == "openai":
        from langchain_openai import ChatOpenAI

        if not config.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required when ALPHALOOP_PROVIDER=openai")
        kwargs: dict[str, Any] = {
            "model": config.model,
            "api_key": config.openai_api_key,
            "temperature": 0.1,
            "timeout": 120,
        }
        if config.openai_base_url:
            kwargs["base_url"] = config.openai_base_url
        return ChatOpenAI(**kwargs)

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        if not config.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is required when ALPHALOOP_PROVIDER=anthropic")
        return ChatAnthropic(
            model=config.model,
            api_key=config.anthropic_api_key,
            temperature=0.1,
            timeout=120,
        )

    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI

        if not config.gemini_api_key:
            raise ValueError("GOOGLE_API_KEY (or GEMINI_API_KEY) is required when ALPHALOOP_PROVIDER=gemini")
        return ChatGoogleGenerativeAI(
            model=config.model,
            google_api_key=config.gemini_api_key,
            temperature=0.1,
            timeout=120,
        )

    if provider == "ollama_cloud":
        from langchain_openai import ChatOpenAI

        if not config.ollama_api_key:
            raise ValueError("OLLAMA_API_KEY is required when ALPHALOOP_PROVIDER=ollama_cloud")
        return ChatOpenAI(
            model=config.model,
            api_key=config.ollama_api_key,
            base_url=_with_v1_path(config.ollama_cloud_base_url),
            temperature=0.1,
            timeout=120,
        )

    raise ValueError(f"Unsupported provider: {provider}")


async def create_agent(
    config: Config | None = None,
) -> tuple[CompiledStateGraph, AsyncSqliteSaver, AsyncExitStack]:
    """Build and return a compiled deepagent + its checkpointer.

    The checkpointer is returned separately so the caller can use it as an
    active saver while the returned exit stack owns the underlying SQLite
    connection lifecycle.

    Args:
        config: Runtime config. Defaults to the module-level singleton.

    Returns:
        A ``(compiled_graph, checkpointer, exit_stack)`` tuple.
    """
    from deepagents import create_deep_agent  # deferred — heavy import

    cfg = config or get_config()
    model = _build_model(cfg)
    stack = AsyncExitStack()
    try:
        checkpointer = await stack.enter_async_context(
            AsyncSqliteSaver.from_conn_string(str(cfg.checkpoint_db))
        )

        log_event(logger, "agent.build", model=cfg.model, db=str(cfg.checkpoint_db))

        # Optionally attach a sandbox backend for safe shell execution
        backend = None
        if cfg.sandbox_enabled:
            from alphaloop.sandbox import build_sandbox  # deferred — avoids import at module level

            sandbox = build_sandbox(
                use_docker=cfg.sandbox_use_docker,
                work_dir=cfg.work_dir,
                docker_image=cfg.sandbox_docker_image,
                timeout=cfg.sandbox_timeout,
            )
            backend = sandbox
            log_event(
                logger,
                "agent.sandbox",
                type="docker" if cfg.sandbox_use_docker else "restricted-local",
                id=sandbox.id,
            )

        from alphaloop.mcp import load_mcp_tools
        from alphaloop.skills import get_enabled_tools

        mcp_tools    = await load_mcp_tools(cfg, stack)
        skill_tools  = get_enabled_tools()
        all_tools    = mcp_tools + skill_tools

        graph = create_deep_agent(
            model=model,
            tools=all_tools or None,
            system_prompt=cfg.system_prompt,
            checkpointer=checkpointer,
            backend=backend,
        )
        return graph, checkpointer, stack
    except Exception:
        await stack.aclose()
        raise


async def invoke_agent(
    graph: CompiledStateGraph,
    message: str,
    thread_id: str,
) -> str:
    """Send a single message to the agent and collect the reply.

    Args:
        graph: Compiled agent graph.
        message: User message to send.
        thread_id: Conversation thread to use (enables persistence).

    Returns:
        The agent's last text response, or an empty string if none.
    """
    config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}
    input_state = {"messages": [HumanMessage(content=message)]}

    reply_parts: list[str] = []
    try:
        async for chunk in graph.astream(input_state, config=config, stream_mode="values"):
            msgs = chunk.get("messages", [])
            if msgs:
                last = msgs[-1]
                content = getattr(last, "content", "")
                if isinstance(content, str) and content:
                    reply_parts.append(content)
    except Exception as exc:
        logger.exception("agent.invoke failed: %s", exc)
        return ""

    # Return only the last non-empty chunk (avoids echoing intermediate thoughts)
    for part in reversed(reply_parts):
        if part.strip():
            return part.strip()
    return ""


async def ping_agent(graph: CompiledStateGraph, thread_id: str) -> bool:
    """Send a lightweight ping to verify the agent is responsive.

    Args:
        graph: Compiled agent graph.
        thread_id: Conversation thread.

    Returns:
        ``True`` if the agent replied within the timeout, otherwise ``False``.
    """
    try:
        reply = await asyncio.wait_for(
            invoke_agent(graph, "Heartbeat ping — respond with 'OK'.", thread_id),
            timeout=30.0,
        )
        return bool(reply)
    except (asyncio.TimeoutError, Exception):
        return False
