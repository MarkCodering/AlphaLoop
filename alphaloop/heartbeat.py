"""Heartbeat monitor — keeps AlphaLoop alive 24/7.

The heartbeat does three things on every tick:
1. **Health check** — pings the agent; if it fails N times in a row the
   runner is asked to restart the agent.
2. **Proactive pulse** — sends a "wake up and reflect" message so the
   agent can decide what to do next without waiting for a human.
3. **Metrics** — emits structured log events you can pipe to any
   monitoring tool.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any

from langgraph.graph.state import CompiledStateGraph

from alphaloop.agent import invoke_agent, ping_agent
from alphaloop.config import Config, get_config
from alphaloop.logger import get_logger, log_event

logger = get_logger(__name__)

# Sent to the agent on every heartbeat to trigger autonomous reasoning
PULSE_MESSAGE = (
    "Heartbeat. Current time: {timestamp}. "
    "Review your todo list and recent activity. "
    "Identify your highest-priority next action and take it. "
    "If there is nothing urgent, record a brief status note."
)

RestartCallback = Callable[[], Coroutine[Any, Any, None]]


@dataclass
class HeartbeatStats:
    """Running statistics for the heartbeat monitor."""

    total_ticks: int = 0
    healthy_ticks: int = 0
    failed_ticks: int = 0
    consecutive_failures: int = 0
    last_tick_at: float = field(default_factory=time.monotonic)
    last_healthy_at: float = field(default_factory=time.monotonic)

    @property
    def uptime_pct(self) -> float:
        """Percentage of ticks that were healthy."""
        if self.total_ticks == 0:
            return 100.0
        return 100.0 * self.healthy_ticks / self.total_ticks


class HeartbeatMonitor:
    """Async monitor that drives the agent's 24/7 loop.

    Args:
        graph: The compiled agent graph to monitor.
        config: Runtime config.
        on_restart: Async callback invoked when the agent needs to be
            restarted due to consecutive failures.
    """

    def __init__(
        self,
        graph: CompiledStateGraph,
        config: Config | None = None,
        on_restart: RestartCallback | None = None,
    ) -> None:
        self._graph = graph
        self._cfg = config or get_config()
        self._on_restart = on_restart
        self.stats = HeartbeatStats()
        self._stop_event = asyncio.Event()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Run the heartbeat loop until :meth:`stop` is called."""
        log_event(
            logger,
            "heartbeat.start",
            interval=self._cfg.heartbeat_interval,
            model=self._cfg.model,
        )
        while not self._stop_event.is_set():
            await self._tick()
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._cfg.heartbeat_interval,
                )
            except asyncio.TimeoutError:
                pass  # normal — just means interval elapsed

    def stop(self) -> None:
        """Signal the heartbeat loop to stop after the current tick."""
        self._stop_event.set()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _tick(self) -> None:
        """Execute one heartbeat cycle."""
        now = time.monotonic()
        wall_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        self.stats.total_ticks += 1
        self.stats.last_tick_at = now

        log_event(
            logger,
            "heartbeat.tick",
            tick=self.stats.total_ticks,
            uptime_pct=f"{self.stats.uptime_pct:.1f}%",
        )

        # 1. Health check (lightweight ping)
        healthy = await self._health_check()

        if healthy:
            self.stats.healthy_ticks += 1
            self.stats.consecutive_failures = 0
            self.stats.last_healthy_at = now

            # 2. Proactive pulse — let the agent reason autonomously
            await self._pulse(wall_time)
        else:
            self.stats.failed_ticks += 1
            self.stats.consecutive_failures += 1
            log_event(
                logger,
                "heartbeat.unhealthy",
                consecutive_failures=self.stats.consecutive_failures,
                max=self._cfg.max_heartbeat_failures,
            )
            if self.stats.consecutive_failures >= self._cfg.max_heartbeat_failures:
                await self._handle_restart()

    async def _health_check(self) -> bool:
        """Ping the agent and return True if it responds."""
        try:
            ok = await asyncio.wait_for(
                ping_agent(self._graph, self._cfg.thread_id),
                timeout=self._cfg.heartbeat_timeout,
            )
            log_event(logger, "heartbeat.ping", result="ok" if ok else "no_reply")
            return ok
        except asyncio.TimeoutError:
            log_event(logger, "heartbeat.ping", result="timeout")
            return False
        except Exception as exc:
            log_event(logger, "heartbeat.ping", result="error", error=str(exc))
            return False

    async def _pulse(self, wall_time: str) -> None:
        """Send the autonomous reasoning prompt to the agent."""
        message = PULSE_MESSAGE.format(timestamp=wall_time)
        try:
            reply = await asyncio.wait_for(
                invoke_agent(self._graph, message, self._cfg.thread_id),
                timeout=self._cfg.heartbeat_timeout,
            )
            log_event(
                logger,
                "heartbeat.pulse",
                reply_len=len(reply),
                preview=reply[:120].replace("\n", " "),
            )
        except asyncio.TimeoutError:
            log_event(logger, "heartbeat.pulse", result="timeout")
        except Exception as exc:
            log_event(logger, "heartbeat.pulse", result="error", error=str(exc))

    async def _handle_restart(self) -> None:
        """Invoke the restart callback and reset failure counters."""
        log_event(
            logger,
            "heartbeat.restart",
            reason=f"{self.stats.consecutive_failures} consecutive failures",
        )
        self.stats.consecutive_failures = 0
        if self._on_restart is not None:
            try:
                await self._on_restart()
            except Exception as exc:
                logger.exception("heartbeat.restart callback failed: %s", exc)
