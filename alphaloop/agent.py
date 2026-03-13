"""AlphaLoop agent factory — wraps deepagents with an Ollama model."""

from __future__ import annotations

import asyncio
from typing import Any

from langchain_core.messages import HumanMessage
from langchain_ollama import ChatOllama
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph.state import CompiledStateGraph

from alphaloop.config import Config, get_config
from alphaloop.logger import get_logger, log_event

logger = get_logger(__name__)


def _build_ollama_model(config: Config) -> ChatOllama:
    """Instantiate the ChatOllama model from config."""
    return ChatOllama(
        model=config.model,
        base_url=config.ollama_base_url,
        # Keep temperature low for consistent, goal-driven behaviour
        temperature=0.1,
        # Thinking models may need more time to respond
        timeout=120,
    )


def create_agent(config: Config | None = None) -> tuple[CompiledStateGraph, AsyncSqliteSaver]:
    """Build and return a compiled deepagent + its checkpointer.

    The checkpointer is returned separately so the caller can use it as an
    async context manager when running the agent.

    Args:
        config: Runtime config. Defaults to the module-level singleton.

    Returns:
        A ``(compiled_graph, checkpointer)`` pair.
    """
    from deepagents import create_deep_agent  # deferred — heavy import

    cfg = config or get_config()
    model = _build_ollama_model(cfg)
    checkpointer = AsyncSqliteSaver.from_conn_string(str(cfg.checkpoint_db))

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

    graph = create_deep_agent(
        model=model,
        system_prompt=cfg.system_prompt,
        checkpointer=checkpointer,
        backend=backend,
    )
    return graph, checkpointer


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
