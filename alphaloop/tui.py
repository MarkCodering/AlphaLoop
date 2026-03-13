"""AlphaLoop TUI — a Textual terminal UI for the 24/7 agent.

Layout
------
┌─────────────────────────────────────┐
│  AlphaLoop  [model] [thread] [hb]   │  ← Header
├──────────────────┬──────────────────┤
│                  │  Heartbeat Log   │
│   Chat Panel     │  (right sidebar) │
│                  │                  │
├──────────────────┴──────────────────┤
│  > Input box                        │  ← Footer input
└─────────────────────────────────────┘

Run with::

    from alphaloop.tui import AlphaLoopApp
    AlphaLoopApp().run()
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import ClassVar

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import (
    Footer,
    Header,
    Input,
    Label,
    Log,
    RichLog,
    Static,
)

from alphaloop.config import Config, get_config
from alphaloop.heartbeat import HeartbeatMonitor, HeartbeatStats
from alphaloop.logger import setup_logging


# ---------------------------------------------------------------------------
# Custom messages
# ---------------------------------------------------------------------------

from textual.message import Message


class AgentReply(Message):
    """Posted when the agent produces a reply."""

    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text


class HeartbeatTick(Message):
    """Posted on each heartbeat tick with updated stats."""

    def __init__(self, stats: HeartbeatStats, healthy: bool) -> None:
        super().__init__()
        self.stats = stats
        self.healthy = healthy


class StatusUpdate(Message):
    """General status message for the sidebar."""

    def __init__(self, text: str, style: str = "dim") -> None:
        super().__init__()
        self.text = text
        self.style = style


# ---------------------------------------------------------------------------
# Widgets
# ---------------------------------------------------------------------------


class StatusBar(Static):
    """Top status bar showing model, thread, and heartbeat state."""

    healthy: reactive[bool] = reactive(True)
    tick: reactive[int] = reactive(0)
    uptime: reactive[float] = reactive(100.0)

    def __init__(self, config: Config, **kwargs) -> None:
        super().__init__(**kwargs)
        self._cfg = config

    def render(self) -> Text:
        hb_color = "green" if self.healthy else "red"
        hb_icon = "●" if self.healthy else "○"
        t = Text()
        t.append("  AlphaLoop", style="bold white")
        t.append(f"  model={self._cfg.model}", style="cyan")
        t.append(f"  thread={self._cfg.thread_id}", style="yellow")
        t.append(f"  hb={hb_icon} tick={self.tick} up={self.uptime:.0f}%", style=hb_color)
        return t


# ---------------------------------------------------------------------------
# Main App
# ---------------------------------------------------------------------------


class AlphaLoopApp(App[None]):
    """Textual TUI for AlphaLoop."""

    TITLE = "AlphaLoop"
    CSS = """
    Screen {
        background: $surface;
    }

    #main-layout {
        height: 1fr;
    }

    #chat-panel {
        width: 2fr;
        border: solid $primary;
        padding: 0 1;
    }

    #sidebar {
        width: 1fr;
        border: solid $accent;
        padding: 0 1;
    }

    #sidebar-title {
        color: $accent;
        text-style: bold;
        padding: 0 0 1 0;
    }

    #chat-title {
        color: $primary;
        text-style: bold;
        padding: 0 0 1 0;
    }

    #status-bar {
        height: 1;
        background: $primary-darken-2;
        color: $text;
        padding: 0 1;
    }

    #input-row {
        height: 3;
        border-top: solid $primary;
        padding: 0 1;
    }

    #user-input {
        width: 1fr;
    }

    #send-btn {
        width: 10;
        margin-left: 1;
    }

    RichLog {
        height: 1fr;
        scrollbar-gutter: stable;
    }

    Log {
        height: 1fr;
        scrollbar-gutter: stable;
    }
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("ctrl+c", "quit", "Quit", show=True),
        Binding("ctrl+l", "clear_chat", "Clear chat", show=True),
        Binding("escape", "blur_input", "Blur input", show=False),
    ]

    def __init__(self, config: Config | None = None) -> None:
        super().__init__()
        self._cfg = config or get_config()
        self._runner: _BackgroundRunner | None = None
        self._recent_messages: deque[tuple[str, str]] = deque(maxlen=200)

    # ------------------------------------------------------------------
    # Compose
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield StatusBar(self._cfg, id="status-bar")
        with Horizontal(id="main-layout"):
            with Vertical(id="chat-panel"):
                yield Label("Chat", id="chat-title")
                yield RichLog(id="chat-log", highlight=True, markup=True, wrap=True)
            with Vertical(id="sidebar"):
                yield Label("Heartbeat Log", id="sidebar-title")
                yield Log(id="hb-log", highlight=True)
        with Horizontal(id="input-row"):
            yield Input(placeholder="Send a message… (Enter to send)", id="user-input")
        yield Footer()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_mount(self) -> None:
        setup_logging("WARNING")  # suppress verbose logs inside TUI
        self._runner = _BackgroundRunner(self._cfg, self)
        self._runner.start_all()
        self.query_one("#user-input", Input).focus()

    async def on_unmount(self) -> None:
        if self._runner:
            await self._runner.stop()

    # ------------------------------------------------------------------
    # Input handling
    # ------------------------------------------------------------------

    @on(Input.Submitted, "#user-input")
    def on_submit(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        event.input.clear()
        self._append_chat("You", text, style="bold cyan")
        self._send_message(text)

    @work(exclusive=False)
    async def _send_message(self, text: str) -> None:
        if self._runner is None:
            return
        self._append_chat("Agent", "…thinking…", style="dim italic")
        reply = await self._runner.send(text)
        # Replace placeholder with actual reply
        chat = self.query_one("#chat-log", RichLog)
        # Remove last line (the thinking placeholder) — RichLog doesn't support
        # in-place edit, so we clear and re-render instead
        self._rebuild_chat(replace_last=("Agent", reply))

    # ------------------------------------------------------------------
    # Message handlers
    # ------------------------------------------------------------------

    def on_heartbeat_tick(self, msg: HeartbeatTick) -> None:
        bar = self.query_one("#status-bar", StatusBar)
        bar.healthy = msg.healthy
        bar.tick = msg.stats.total_ticks
        bar.uptime = msg.stats.uptime_pct

        hb_log = self.query_one("#hb-log", Log)
        ts = time.strftime("%H:%M:%S")
        icon = "✓" if msg.healthy else "✗"
        hb_log.write_line(
            f"{ts} {icon} tick={msg.stats.total_ticks} "
            f"up={msg.stats.uptime_pct:.0f}% "
            f"fail={msg.stats.consecutive_failures}"
        )

    def on_agent_reply(self, msg: AgentReply) -> None:
        self._append_chat("Heartbeat", msg.text, style="dim green")

    def on_status_update(self, msg: StatusUpdate) -> None:
        hb_log = self.query_one("#hb-log", Log)
        hb_log.write_line(msg.text)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_clear_chat(self) -> None:
        self._recent_messages.clear()
        self.query_one("#chat-log", RichLog).clear()

    def action_blur_input(self) -> None:
        self.query_one("#user-input", Input).blur()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _append_chat(self, speaker: str, text: str, style: str = "") -> None:
        self._recent_messages.append((speaker, text))
        log = self.query_one("#chat-log", RichLog)
        ts = time.strftime("%H:%M:%S")
        log.write(Text.from_markup(f"[dim]{ts}[/dim] [{style}]{speaker}[/{style}]: {text}\n"))

    def _rebuild_chat(self, replace_last: tuple[str, str] | None = None) -> None:
        """Re-render the chat log, optionally replacing the last entry."""
        log = self.query_one("#chat-log", RichLog)
        log.clear()
        messages = list(self._recent_messages)
        if replace_last and messages:
            messages[-1] = replace_last
            self._recent_messages[-1] = replace_last
        for speaker, text in messages:
            style = "bold cyan" if speaker == "You" else "green"
            ts = time.strftime("%H:%M:%S")
            log.write(Text.from_markup(f"[dim]{ts}[/dim] [{style}]{speaker}[/{style}]: {text}\n"))


# ---------------------------------------------------------------------------
# Background runner (non-blocking bridge between async agent and Textual)
# ---------------------------------------------------------------------------


class _BackgroundRunner:
    """Manages the agent + heartbeat as background asyncio tasks inside Textual."""

    def __init__(self, config: Config, app: AlphaLoopApp) -> None:
        self._cfg = config
        self._app = app
        self._graph = None
        self._agent_stack = None
        self._monitor: HeartbeatMonitor | None = None
        self._hb_task: asyncio.Task | None = None

    def start_all(self) -> None:
        """Kick off agent boot and heartbeat as Textual workers."""
        self._app.run_worker(self._boot(), exclusive=False, name="agent-boot")

    async def _boot(self) -> None:
        from alphaloop.agent import create_agent

        self._app.post_message(StatusUpdate("Booting agent…"))
        graph, _, stack = await create_agent(self._cfg)
        self._graph = graph
        self._agent_stack = stack
        self._app.post_message(StatusUpdate(f"Agent ready ({self._cfg.model})"))

        # Patch monitor to forward events to Textual
        self._monitor = _TuiHeartbeatMonitor(graph, self._cfg, self._app)
        self._hb_task = asyncio.create_task(self._monitor.run(), name="hb")

    async def send(self, message: str) -> str:
        if self._graph is None:
            return "(agent not ready)"
        from alphaloop.agent import invoke_agent

        return await invoke_agent(self._graph, message, self._cfg.thread_id)

    async def stop(self) -> None:
        if self._monitor:
            self._monitor.stop()
        if self._hb_task:
            self._hb_task.cancel()
            try:
                await self._hb_task
            except asyncio.CancelledError:
                pass
            self._hb_task = None
        if self._agent_stack is not None:
            await self._agent_stack.aclose()
            self._agent_stack = None


class _TuiHeartbeatMonitor(HeartbeatMonitor):
    """HeartbeatMonitor subclass that posts Textual messages instead of logging."""

    def __init__(self, graph, config: Config, app: AlphaLoopApp) -> None:  # noqa: ANN001
        super().__init__(graph, config)
        self._app = app

    async def _tick(self) -> None:
        await super()._tick()
        self._app.post_message(
            HeartbeatTick(stats=self.stats, healthy=self.stats.consecutive_failures == 0)
        )

    async def _pulse(self, wall_time: str) -> None:
        """Override: post agent reply to chat instead of logging."""
        from alphaloop.heartbeat import PULSE_MESSAGE
        from alphaloop.agent import invoke_agent

        message = PULSE_MESSAGE.format(timestamp=wall_time)
        try:
            reply = await asyncio.wait_for(
                invoke_agent(self._graph, message, self._cfg.thread_id),
                timeout=self._cfg.heartbeat_timeout,
            )
            if reply:
                self._app.post_message(AgentReply(reply[:500]))
        except (asyncio.TimeoutError, Exception):
            pass
