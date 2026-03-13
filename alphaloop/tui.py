"""AlphaLoop TUI — a Textual terminal UI for the 24/7 agent.

Layout
------
┌─────────────────────────────────────────────────────────┐
│  ◉ ALPHALOOP  model=…  thread=…                          │  ← App header
│  hb=● tick=N up=100%  sandbox=…  mcp=N                  │  ← Status bar
├──────────────────────────┬──────────────────────────────┤
│                          │  [ HB: ● | tick | up | fail ]│
│   Chat                   │  ──────────────────────────  │
│                          │  Heartbeat Log               │
├──────────────────────────┴──────────────────────────────┤
│  ▶  Input…                                              │  ← Input row
└─────────────────────────────────────────────────────────┘
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
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import (
    Footer,
    Input,
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


class AgentReply(Message):
    """Posted when the agent produces a heartbeat reply."""

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
    """General status line posted to the sidebar log."""

    def __init__(self, text: str, level: str = "info") -> None:
        super().__init__()
        self.text = text
        self.level = level  # "info" | "warn" | "error" | "ok"


# ---------------------------------------------------------------------------
# Widgets
# ---------------------------------------------------------------------------


class AppHeader(Static):
    """Brand header row — logo + model + thread."""

    def __init__(self, config: Config, **kwargs) -> None:
        super().__init__(**kwargs)
        self._cfg = config

    def render(self) -> Text:
        t = Text(overflow="ellipsis", no_wrap=True)
        t.append("  ◉ ", style="bold bright_yellow")
        t.append("ALPHALOOP", style="bold white")
        t.append("  │  ", style="bright_black")
        t.append("model", style="bright_black")
        t.append("=", style="bright_black")
        t.append(self._cfg.model, style="cyan")
        t.append("  │  ", style="bright_black")
        t.append("thread", style="bright_black")
        t.append("=", style="bright_black")
        t.append(self._cfg.thread_id, style="yellow")
        return t


class StatusBar(Static):
    """Second header row — live heartbeat + sandbox + MCP state."""

    healthy: reactive[bool] = reactive(True)
    tick: reactive[int] = reactive(0)
    uptime: reactive[float] = reactive(100.0)
    failures: reactive[int] = reactive(0)

    def __init__(self, config: Config, **kwargs) -> None:
        super().__init__(**kwargs)
        self._cfg = config

    def render(self) -> Text:
        from alphaloop.mcp import read_mcp_connections

        hb_color = "bright_green" if self.healthy else "bright_red"
        hb_icon = "●" if self.healthy else "✗"
        t = Text(overflow="ellipsis", no_wrap=True)
        t.append("  hb=", style="bright_black")
        t.append(hb_icon, style=hb_color)
        t.append(f" tick={self.tick}", style=hb_color)
        t.append(f" up={self.uptime:.0f}%", style=hb_color)
        if self.failures:
            t.append(f" fail={self.failures}", style="bright_red")
        if self._cfg.sandbox_enabled:
            t.append("  │  ", style="bright_black")
            mode = "docker" if self._cfg.sandbox_use_docker else "local"
            t.append("sandbox", style="bright_black")
            t.append("=", style="bright_black")
            t.append(mode, style="magenta")
        mcp_servers = read_mcp_connections(self._cfg)
        if mcp_servers:
            t.append("  │  ", style="bright_black")
            t.append("mcp", style="bright_black")
            t.append("=", style="bright_black")
            t.append(str(len(mcp_servers)), style="bright_green")
            t.append(f" ({', '.join(mcp_servers)})", style="bright_black")
        return t


class HbStats(Static):
    """Live heartbeat stats strip at the top of the sidebar."""

    healthy: reactive[bool] = reactive(True)
    tick: reactive[int] = reactive(0)
    uptime: reactive[float] = reactive(100.0)
    failures: reactive[int] = reactive(0)

    def render(self) -> Text:
        hb_color = "bright_green" if self.healthy else "bright_red"
        icon = "● HEALTHY" if self.healthy else "✗ DEGRADED"
        t = Text(overflow="ellipsis", no_wrap=True)
        t.append(" ", style="")
        t.append(icon, style=f"bold {hb_color}")
        t.append("  tick=", style="bright_black")
        t.append(str(self.tick), style="white")
        t.append("  up=", style="bright_black")
        t.append(f"{self.uptime:.0f}%", style="white")
        t.append("  fail=", style="bright_black")
        t.append(str(self.failures), style="bright_red" if self.failures else "bright_black")
        return t


# ---------------------------------------------------------------------------
# Main App
# ---------------------------------------------------------------------------

_DARK = "#08080a"
_SURFACE = "#0f0f12"
_BORDER = "#27272a"
_AMBER = "#f59e0b"
_CYAN = "#22d3ee"


class AlphaLoopApp(App[None]):
    """Textual TUI for AlphaLoop."""

    TITLE = "AlphaLoop"

    CSS = f"""
    Screen {{
        background: {_DARK};
        color: #a1a1aa;
        layers: base overlay;
    }}

    /* ── Header ── */
    #app-header {{
        height: 2;
        background: {_SURFACE};
        border-bottom: tall {_BORDER};
        content-align: left middle;
        padding: 0 0;
    }}

    #status-bar {{
        height: 1;
        background: {_DARK};
        border-bottom: solid {_AMBER};
        content-align: left middle;
        padding: 0 0;
        color: #71717a;
    }}

    /* ── Layout ── */
    #main-layout {{
        height: 1fr;
    }}

    /* ── Chat panel ── */
    #chat-panel {{
        width: 2fr;
        border-right: solid {_BORDER};
    }}

    #chat-header {{
        height: 2;
        background: {_SURFACE};
        border-bottom: solid {_BORDER};
        padding: 0 2;
        content-align: left middle;
        color: {_AMBER};
        text-style: bold;
    }}

    #chat-log {{
        height: 1fr;
        background: {_DARK};
        padding: 0 1;
        scrollbar-color: {_BORDER} {_DARK};
        scrollbar-size: 1 1;
        scrollbar-gutter: stable;
    }}

    /* ── Sidebar ── */
    #sidebar {{
        width: 1fr;
        background: {_SURFACE};
    }}

    #hb-stats {{
        height: 2;
        background: {_SURFACE};
        border-bottom: solid {_BORDER};
        content-align: left middle;
        padding: 0 0;
    }}

    #sidebar-log-header {{
        height: 1;
        background: {_SURFACE};
        border-bottom: solid {_BORDER};
        color: #52525b;
        text-style: bold;
        padding: 0 2;
        content-align: left middle;
    }}

    #hb-log {{
        height: 1fr;
        background: {_SURFACE};
        padding: 0 1;
        scrollbar-color: {_BORDER} {_SURFACE};
        scrollbar-size: 1 1;
        scrollbar-gutter: stable;
        color: #52525b;
    }}

    /* ── Input row ── */
    #input-row {{
        height: 3;
        background: {_SURFACE};
        border-top: tall {_AMBER};
        padding: 0 1;
        align: left middle;
    }}

    #prompt-label {{
        width: 3;
        color: {_AMBER};
        text-style: bold;
        content-align: left middle;
    }}

    #user-input {{
        width: 1fr;
        background: {_SURFACE};
        border: none;
        color: #e4e4e7;
        padding: 0 1;
    }}

    #user-input:focus {{
        border: none;
        background: {_SURFACE};
    }}

    Footer {{
        background: {_DARK};
        color: #3f3f46;
        border-top: solid {_BORDER};
    }}
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("ctrl+c", "quit", "Quit"),
        Binding("ctrl+l", "clear_chat", "Clear"),
        Binding("escape", "blur_input", show=False),
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
        yield AppHeader(self._cfg, id="app-header")
        yield StatusBar(self._cfg, id="status-bar")
        with Horizontal(id="main-layout"):
            with Vertical(id="chat-panel"):
                yield Static("  CHAT", id="chat-header")
                yield RichLog(id="chat-log", highlight=False, markup=True, wrap=True)
            with Vertical(id="sidebar"):
                yield HbStats(id="hb-stats")
                yield Static("  HEARTBEAT LOG", id="sidebar-log-header")
                yield Log(id="hb-log", highlight=False)
        with Horizontal(id="input-row"):
            yield Static("▶", id="prompt-label")
            yield Input(placeholder="Message or /help for commands…", id="user-input")
        yield Footer()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_mount(self) -> None:
        setup_logging("WARNING")
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
        if text.startswith("/"):
            self._handle_slash_command(text)
        else:
            self._append_chat("you", text)
            self._send_message(text)

    def _handle_slash_command(self, text: str) -> None:
        """Dispatch /commands entered in the input box."""
        parts = text.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if cmd in ("/help", "/?"):
            lines = [
                "[bright_yellow]Available commands:[/bright_yellow]",
                "  [cyan]/help[/cyan]         — show this help",
                "  [cyan]/clear[/cyan]        — clear chat history",
                "  [cyan]/status[/cyan]       — show config & heartbeat state",
                "  [cyan]/model[/cyan] [dim]<name>[/dim]  — show current model (read-only)",
                "  [cyan]/thread[/cyan] [dim]<id>[/dim]   — show current thread (read-only)",
                "  [cyan]/mcp[/cyan]          — list connected MCP servers",
                "  [cyan]/sandbox[/cyan]      — show sandbox mode",
            ]
            log = self.query_one("#chat-log", RichLog)
            for line in lines:
                log.write(Text.from_markup(line + "\n"))

        elif cmd == "/clear":
            self.action_clear_chat()

        elif cmd == "/status":
            self._show_status()

        elif cmd == "/model":
            self._append_chat("sys", f"model={self._cfg.model}")

        elif cmd == "/thread":
            self._append_chat("sys", f"thread={self._cfg.thread_id}")

        elif cmd == "/mcp":
            from alphaloop.mcp import read_mcp_connections
            servers = read_mcp_connections(self._cfg)
            if servers:
                self._append_chat("sys", f"MCP servers: {', '.join(servers)}")
            else:
                self._append_chat("sys", "No MCP servers configured (add ~/.alphaloop/mcp.json)")

        elif cmd == "/sandbox":
            if self._cfg.sandbox_enabled:
                mode = "docker (--network none, 512MB RAM)" if self._cfg.sandbox_use_docker else "restricted-local (allowlist + ulimits)"
                self._append_chat("sys", f"Sandbox: {mode}")
            else:
                self._append_chat("sys", "Sandbox: disabled (use --sandbox to enable)")

        else:
            self._append_chat("sys", f"Unknown command: {cmd}  (type /help for list)")

    def _show_status(self) -> None:
        from alphaloop.mcp import read_mcp_connections
        hb = self.query_one("#status-bar", StatusBar)
        servers = read_mcp_connections(self._cfg)
        log = self.query_one("#chat-log", RichLog)
        rows = [
            ("model",     self._cfg.model),
            ("thread",    self._cfg.thread_id),
            ("hb tick",   str(hb.tick)),
            ("hb uptime", f"{hb.uptime:.0f}%"),
            ("hb healthy",str(hb.healthy)),
            ("sandbox",   ("docker" if self._cfg.sandbox_use_docker else "local") if self._cfg.sandbox_enabled else "off"),
            ("mcp",       ", ".join(servers) if servers else "none"),
            ("checkpoint",str(self._cfg.checkpoint_db)),
        ]
        log.write(Text.from_markup("[bright_yellow]── Status ──────────────────────[/bright_yellow]\n"))
        for key, val in rows:
            log.write(Text.from_markup(f"  [bright_black]{key:<12}[/bright_black] [white]{val}[/white]\n"))

    @work(exclusive=False)
    async def _send_message(self, text: str) -> None:
        if self._runner is None:
            return
        self._append_chat("agent", "…")
        reply = await self._runner.send(text)
        self._rebuild_chat(replace_last=("agent", reply or "(no reply)"))

    # ------------------------------------------------------------------
    # Message handlers
    # ------------------------------------------------------------------

    def on_heartbeat_tick(self, msg: HeartbeatTick) -> None:
        # Update status bar
        bar = self.query_one("#status-bar", StatusBar)
        bar.healthy = msg.healthy
        bar.tick = msg.stats.total_ticks
        bar.uptime = msg.stats.uptime_pct
        bar.failures = msg.stats.consecutive_failures

        # Update sidebar stats strip
        stats = self.query_one("#hb-stats", HbStats)
        stats.healthy = msg.healthy
        stats.tick = msg.stats.total_ticks
        stats.uptime = msg.stats.uptime_pct
        stats.failures = msg.stats.consecutive_failures

        # Append to heartbeat log
        hb_log = self.query_one("#hb-log", Log)
        ts = time.strftime("%H:%M:%S")
        icon = "✓" if msg.healthy else "✗"
        hb_log.write_line(
            f"{ts}  {icon}  t={msg.stats.total_ticks}"
            f"  up={msg.stats.uptime_pct:.0f}%"
            f"  f={msg.stats.consecutive_failures}"
        )

    def on_agent_reply(self, msg: AgentReply) -> None:
        self._append_chat("pulse", msg.text)

    def on_status_update(self, msg: StatusUpdate) -> None:
        hb_log = self.query_one("#hb-log", Log)
        ts = time.strftime("%H:%M:%S")
        prefix = {"info": "·", "ok": "✓", "warn": "!", "error": "✗"}.get(msg.level, "·")
        hb_log.write_line(f"{ts}  {prefix}  {msg.text}")

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_clear_chat(self) -> None:
        self._recent_messages.clear()
        self.query_one("#chat-log", RichLog).clear()

    def action_blur_input(self) -> None:
        self.query_one("#user-input", Input).blur()

    # ------------------------------------------------------------------
    # Chat helpers
    # ------------------------------------------------------------------

    _SPEAKER_STYLE: ClassVar[dict[str, tuple[str, str]]] = {
        "you":   ("bold bright_cyan",   "YOU"),
        "agent": ("bold bright_green",  "AGENT"),
        "pulse": ("dim green",          "PULSE"),
        "sys":   ("bold bright_yellow", "SYS"),
    }

    def _append_chat(self, speaker: str, text: str) -> None:
        self._recent_messages.append((speaker, text))
        log = self.query_one("#chat-log", RichLog)
        self._write_chat_line(log, speaker, text)

    def _write_chat_line(self, log: RichLog, speaker: str, text: str) -> None:
        style, label = self._SPEAKER_STYLE.get(speaker, ("white", speaker.upper()))
        ts = time.strftime("%H:%M:%S")
        log.write(Text.from_markup(
            f"[bright_black]{ts}[/bright_black]  "
            f"[{style}]{label}[/{style}]  "
            f"[white]{text}[/white]\n"
        ))

    def _rebuild_chat(self, replace_last: tuple[str, str] | None = None) -> None:
        log = self.query_one("#chat-log", RichLog)
        log.clear()
        messages = list(self._recent_messages)
        if replace_last and messages:
            messages[-1] = replace_last
            self._recent_messages[-1] = replace_last
        for speaker, text in messages:
            self._write_chat_line(log, speaker, text)


# ---------------------------------------------------------------------------
# Background runner
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
        self._app.run_worker(self._boot(), exclusive=False, name="agent-boot")

    async def _boot(self) -> None:
        from alphaloop.agent import create_agent
        from alphaloop.mcp import read_mcp_connections

        self._app.post_message(StatusUpdate("Booting agent…"))
        graph, _, stack = await create_agent(self._cfg)
        self._graph = graph
        self._agent_stack = stack

        parts: list[str] = [f"Ready  model={self._cfg.model}"]
        if self._cfg.sandbox_enabled:
            mode = "docker" if self._cfg.sandbox_use_docker else "local"
            parts.append(f"sandbox={mode}")
        mcp_servers = read_mcp_connections(self._cfg)
        if mcp_servers:
            parts.append(f"mcp=[{', '.join(mcp_servers)}]")
        self._app.post_message(StatusUpdate("  ".join(parts), level="ok"))

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
    """HeartbeatMonitor that posts Textual messages instead of logging."""

    def __init__(self, graph, config: Config, app: AlphaLoopApp) -> None:  # noqa: ANN001
        super().__init__(graph, config)
        self._app = app

    async def _tick(self) -> None:
        await super()._tick()
        self._app.post_message(
            HeartbeatTick(stats=self.stats, healthy=self.stats.consecutive_failures == 0)
        )

    async def _pulse(self, wall_time: str) -> None:
        from alphaloop.agent import invoke_agent
        from alphaloop.heartbeat import PULSE_MESSAGE

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
