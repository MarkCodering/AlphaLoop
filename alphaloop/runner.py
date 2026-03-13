"""24/7 runner — orchestrates the agent lifecycle and heartbeat.

Usage::

    runner = Runner()
    asyncio.run(runner.start())
"""

from __future__ import annotations

import asyncio
import signal
import sys
from contextlib import AsyncExitStack
from typing import Any

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph.state import CompiledStateGraph

from alphaloop.agent import create_agent, invoke_agent
from alphaloop.config import Config, get_config
from alphaloop.heartbeat import HeartbeatMonitor
from alphaloop.logger import get_logger, log_event, setup_logging

logger = get_logger(__name__)


class Runner:
    """Manages the full agent + heartbeat lifecycle.

    Args:
        config: Runtime config. Defaults to the module-level singleton.
    """

    def __init__(self, config: Config | None = None) -> None:
        self._cfg = config or get_config()
        self._graph: CompiledStateGraph | None = None
        self._checkpointer: AsyncSqliteSaver | None = None
        self._agent_stack: AsyncExitStack | None = None
        self._monitor: HeartbeatMonitor | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._running = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the agent and heartbeat; block until stopped."""
        setup_logging(self._cfg.log_level)
        log_event(logger, "runner.start", model=self._cfg.model, thread=self._cfg.thread_id)

        self._running = True
        self._install_signal_handlers()

        await self._boot_agent()
        await self._run_until_stopped()

    async def stop(self) -> None:
        """Gracefully shut down the heartbeat and agent."""
        log_event(logger, "runner.stop")
        self._running = False
        if self._monitor is not None:
            self._monitor.stop()
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None
        await self._close_agent()

    async def send(self, message: str) -> str:
        """Inject an ad-hoc message into the running agent.

        Args:
            message: The message to send.

        Returns:
            The agent's reply.
        """
        if self._graph is None:
            raise RuntimeError("Agent not started. Call start() first.")
        return await invoke_agent(self._graph, message, self._cfg.thread_id)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _boot_agent(self) -> None:
        """(Re-)create the agent and start the heartbeat."""
        log_event(logger, "runner.boot")

        # Build agent + checkpointer
        await self._close_agent()
        self._graph, self._checkpointer, self._agent_stack = await create_agent(self._cfg)

        # Wire up heartbeat with restart callback
        self._monitor = HeartbeatMonitor(
            graph=self._graph,
            config=self._cfg,
            on_restart=self._restart_agent,
        )
        self._heartbeat_task = asyncio.create_task(
            self._monitor.run(), name="alphaloop-heartbeat"
        )
        log_event(logger, "runner.ready")

    async def _restart_agent(self) -> None:
        """Stop old heartbeat, rebuild agent, restart heartbeat."""
        log_event(logger, "runner.restart")

        # Stop the old monitor without cancelling ourselves
        if self._monitor is not None:
            self._monitor.stop()

        await self._boot_agent()

    async def _run_until_stopped(self) -> None:
        """Block until the runner is stopped, propagating heartbeat errors."""
        while self._running:
            if self._heartbeat_task is not None and self._heartbeat_task.done():
                exc = self._heartbeat_task.exception()
                if exc is not None:
                    logger.exception("Heartbeat task died: %s", exc)
                    await self._restart_agent()
            await asyncio.sleep(1)

    async def _close_agent(self) -> None:
        """Close agent resources held by the current saver context."""
        if self._agent_stack is not None:
            await self._agent_stack.aclose()
            self._agent_stack = None
        self._graph = None
        self._checkpointer = None

    def _install_signal_handlers(self) -> None:
        """Register SIGINT/SIGTERM handlers for graceful shutdown."""
        loop = asyncio.get_running_loop()

        def _shutdown(signame: str) -> None:
            log_event(logger, "runner.signal", sig=signame)
            asyncio.create_task(self.stop())  # noqa: RUF006

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _shutdown, sig.name)
            except (NotImplementedError, RuntimeError):
                # Windows / some environments don't support add_signal_handler
                signal.signal(sig, lambda s, f: _shutdown(signal.Signals(s).name))
