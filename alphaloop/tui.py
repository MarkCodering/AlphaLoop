"""AlphaLoop TUI — a Textual terminal UI for the 24/7 agent.

Layout
------
┌─────────────────────────────────────────────────────────┐
│  ◉ ALPHALOOP  model=…  thread=…                          │  ← AppHeader
│  hb=● tick=N up=100%  sandbox=…  mcp=N                  │  ← StatusBar
├──────────────────────────┬──────────────────────────────┤
│                          │  [ HB: ● | tick | up | fail ]│
│   Chat                   │  Heartbeat Log               │
├──────────────────────────┴──────────────────────────────┤
│  /command preview (shown when typing /)                  │  ← CommandPreview
│  ▶  Message or /help for commands…                       │  ← InputRow
└─────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from pathlib import Path
from typing import ClassVar

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.events import Key
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
    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text


class HeartbeatTick(Message):
    def __init__(self, stats: HeartbeatStats, healthy: bool) -> None:
        super().__init__()
        self.stats = stats
        self.healthy = healthy


class StatusUpdate(Message):
    def __init__(self, text: str, level: str = "info") -> None:
        super().__init__()
        self.text = text
        self.level = level   # "info" | "ok" | "warn" | "error"


class AgentRestart(Message):
    """Posted to ask the runner to restart (e.g. after config change)."""


# ---------------------------------------------------------------------------
# Command registry
# ---------------------------------------------------------------------------

_COMMANDS: list[tuple[str, str]] = [
    ("/help",             "Show available commands"),
    ("/clear",            "Clear chat history"),
    ("/status",           "Show config & heartbeat state"),
    ("/restart",          "Restart the agent"),
    ("/set model",        "Switch Ollama model  · /set model <name>"),
    ("/mcp list",         "List connected MCP servers"),
    ("/mcp add",          "Add MCP server  · /mcp add <name> <url>  [transport=http]"),
    ("/mcp remove",       "Remove MCP server  · /mcp remove <name>"),
    ("/sandbox",          "Show sandbox status"),
    ("/sandbox on",       "Enable restricted-local sandbox"),
    ("/sandbox off",      "Disable sandbox"),
    ("/sandbox docker",   "Switch to Docker isolation (--network none, 512MB)"),
    ("/sandbox local",    "Switch to restricted-local sandbox"),
    ("/thread",           "Show current thread ID"),
]


# ---------------------------------------------------------------------------
# Widgets
# ---------------------------------------------------------------------------


class AppHeader(Static):
    """Brand header — logo + model + thread (updated on restart)."""

    model_name: reactive[str] = reactive("")

    def __init__(self, config: Config, **kwargs) -> None:
        super().__init__(**kwargs)
        self._cfg = config
        self.model_name = config.model

    def render(self) -> Text:
        t = Text(overflow="ellipsis", no_wrap=True)
        t.append("  ◉ ", style="bold bright_yellow")
        t.append("ALPHALOOP", style="bold white")
        t.append("  │  ", style="bright_black")
        t.append("model=", style="bright_black")
        t.append(self.model_name, style="cyan")
        t.append("  │  ", style="bright_black")
        t.append("thread=", style="bright_black")
        t.append(self._cfg.thread_id, style="yellow")
        return t


class StatusBar(Static):
    """Live heartbeat + sandbox + MCP state."""

    healthy:  reactive[bool]  = reactive(True)
    tick:     reactive[int]   = reactive(0)
    uptime:   reactive[float] = reactive(100.0)
    failures: reactive[int]   = reactive(0)
    mcp_count: reactive[int]  = reactive(0)

    def __init__(self, config: Config, **kwargs) -> None:
        super().__init__(**kwargs)
        self._cfg = config

    def render(self) -> Text:
        hb_color = "bright_green" if self.healthy else "bright_red"
        hb_icon  = "●" if self.healthy else "✗"
        t = Text(overflow="ellipsis", no_wrap=True)
        t.append("  hb=",              style="bright_black")
        t.append(hb_icon,              style=hb_color)
        t.append(f" tick={self.tick}", style=hb_color)
        t.append(f" up={self.uptime:.0f}%", style=hb_color)
        if self.failures:
            t.append(f" fail={self.failures}", style="bright_red")
        if self._cfg.sandbox_enabled:
            mode = "docker" if self._cfg.sandbox_use_docker else "local"
            t.append("  │  sandbox=", style="bright_black")
            t.append(mode,            style="magenta")
        if self.mcp_count:
            t.append("  │  mcp=",          style="bright_black")
            t.append(str(self.mcp_count),  style="bright_green")
        return t


class HbStats(Static):
    """Live stats strip at the top of the sidebar."""

    healthy:  reactive[bool]  = reactive(True)
    tick:     reactive[int]   = reactive(0)
    uptime:   reactive[float] = reactive(100.0)
    failures: reactive[int]   = reactive(0)

    def render(self) -> Text:
        hb_color = "bright_green" if self.healthy else "bright_red"
        icon = "● HEALTHY" if self.healthy else "✗ DEGRADED"
        t = Text(overflow="ellipsis", no_wrap=True)
        t.append(" ",     style="")
        t.append(icon,    style=f"bold {hb_color}")
        t.append("  tick=",  style="bright_black")
        t.append(str(self.tick), style="white")
        t.append("  up=",    style="bright_black")
        t.append(f"{self.uptime:.0f}%", style="white")
        t.append("  fail=",  style="bright_black")
        t.append(str(self.failures),
                 style="bright_red" if self.failures else "bright_black")
        return t


class CommandPreview(Static):
    """Floating command palette shown when the user types '/'."""

    _matches: list[tuple[str, str]]
    _selected: int

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._matches = []
        self._selected = 0

    # -- public API ----------------------------------------------------------

    def filter(self, prefix: str) -> None:
        """Filter command list to entries matching *prefix* and refresh."""
        p = prefix.lower()
        self._matches = [(cmd, desc) for cmd, desc in _COMMANDS if cmd.startswith(p)]
        self._selected = 0
        self._sync_height()
        self.refresh()

    def move_up(self) -> None:
        if self._matches:
            self._selected = (self._selected - 1) % len(self._matches)
            self.refresh()

    def move_down(self) -> None:
        if self._matches:
            self._selected = (self._selected + 1) % len(self._matches)
            self.refresh()

    def selected_command(self) -> str:
        if self._matches:
            return self._matches[self._selected][0]
        return ""

    # -- rendering -----------------------------------------------------------

    def render(self) -> Text:
        t = Text()
        for i, (cmd, desc) in enumerate(self._matches):
            if i == self._selected:
                t.append(f" {cmd:<20}", style="bold bright_yellow on #1a1a0a")
                t.append(f" {desc}\n",  style="white on #1a1a0a")
            else:
                t.append(f" {cmd:<20}", style="bright_black")
                t.append(f" {desc}\n",  style="bright_black")
        return t

    def _sync_height(self) -> None:
        """Resize widget to fit the number of matches (max 10)."""
        n = min(len(self._matches), 10)
        self.styles.height = max(n, 0)
        self.display = n > 0


# ---------------------------------------------------------------------------
# Theme constants
# ---------------------------------------------------------------------------

_DARK    = "#08080a"
_SURFACE = "#0f0f12"
_BORDER  = "#27272a"
_AMBER   = "#f59e0b"


# ---------------------------------------------------------------------------
# Main App
# ---------------------------------------------------------------------------


class AlphaLoopApp(App[None]):
    """Textual TUI for AlphaLoop."""

    TITLE = "AlphaLoop"

    CSS = f"""
    Screen {{
        background: {_DARK};
        color: #a1a1aa;
    }}

    /* ── Top headers ── */
    #app-header {{
        height: 2;
        background: {_SURFACE};
        border-bottom: tall {_BORDER};
        content-align: left middle;
    }}
    #status-bar {{
        height: 1;
        background: {_DARK};
        border-bottom: solid {_AMBER};
        content-align: left middle;
        color: #71717a;
    }}

    /* ── Main layout ── */
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
    }}
    #sidebar-log-header {{
        height: 1;
        background: {_SURFACE};
        border-bottom: solid {_BORDER};
        color: #3f3f46;
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

    /* ── Command preview ── */
    #cmd-preview {{
        display: none;
        background: {_SURFACE};
        border-top: solid {_AMBER};
        border-left: solid {_AMBER};
        border-right: solid {_AMBER};
        padding: 0 0;
        height: 0;
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
        Binding("ctrl+c", "quit",       "Quit"),
        Binding("ctrl+l", "clear_chat", "Clear"),
        Binding("escape", "dismiss_preview", show=False),
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
        yield CommandPreview(id="cmd-preview")
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

    @on(Input.Changed, "#user-input")
    def on_input_changed(self, event: Input.Changed) -> None:
        preview = self.query_one("#cmd-preview", CommandPreview)
        val = event.value
        if val.startswith("/"):
            preview.filter(val)
        else:
            preview.display = False

    @on(Input.Submitted, "#user-input")
    def on_submit(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        event.input.clear()
        self.query_one("#cmd-preview", CommandPreview).display = False
        if text.startswith("/"):
            self._handle_slash_command(text)
        else:
            self._append_chat("you", text)
            self._send_message(text)

    def on_key(self, event: Key) -> None:
        preview = self.query_one("#cmd-preview", CommandPreview)
        inp = self.query_one("#user-input", Input)
        if not preview.display:
            return
        if event.key == "up":
            preview.move_up()
            event.prevent_default()
        elif event.key == "down":
            preview.move_down()
            event.prevent_default()
        elif event.key == "tab":
            cmd = preview.selected_command()
            if cmd:
                inp.value = cmd + " "
                inp.cursor_position = len(inp.value)
                preview.filter(cmd)
            event.prevent_default()
        elif event.key == "escape":
            preview.display = False
            event.prevent_default()

    # ------------------------------------------------------------------
    # /command dispatcher
    # ------------------------------------------------------------------

    def _handle_slash_command(self, text: str) -> None:
        parts = text.split()
        cmd   = parts[0].lower()

        # Two-word commands: /set model, /mcp add|remove|list
        if len(parts) >= 2:
            two = f"{parts[0].lower()} {parts[1].lower()}"
        else:
            two = ""

        if cmd in ("/help", "/?"):
            self._cmd_help()
        elif cmd == "/clear":
            self.action_clear_chat()
        elif cmd == "/status":
            self._cmd_status()
        elif cmd == "/restart":
            self._cmd_restart()
        elif cmd == "/thread":
            self._append_chat("sys", f"thread={self._cfg.thread_id}")
        elif two == "/set model":
            self._cmd_set_model(parts[2] if len(parts) > 2 else "")
        elif two == "/mcp list":
            self._cmd_mcp_list()
        elif two == "/mcp add":
            self._cmd_mcp_add(parts[2:] if len(parts) > 2 else [])
        elif two == "/mcp remove":
            self._cmd_mcp_remove(parts[2] if len(parts) > 2 else "")
        elif cmd == "/mcp":
            self._cmd_mcp_list()
        elif two == "/sandbox on":
            self._cmd_sandbox_set(enabled=True, docker=False)
        elif two == "/sandbox off":
            self._cmd_sandbox_set(enabled=False, docker=False)
        elif two == "/sandbox docker":
            self._cmd_sandbox_set(enabled=True, docker=True)
        elif two == "/sandbox local":
            self._cmd_sandbox_set(enabled=True, docker=False)
        elif cmd == "/sandbox":
            self._cmd_sandbox()
        else:
            self._append_chat("sys", f"Unknown command: {text}  · type /help")

    def _cmd_help(self) -> None:
        log = self.query_one("#chat-log", RichLog)
        log.write(Text.from_markup(
            "[bright_yellow]── Commands ─────────────────────────────────────[/bright_yellow]\n"
        ))
        for cmd, desc in _COMMANDS:
            log.write(Text.from_markup(
                f"  [cyan]{cmd:<20}[/cyan] [bright_black]{desc}[/bright_black]\n"
            ))

    def _cmd_status(self) -> None:
        from alphaloop.mcp import read_mcp_connections
        hb  = self.query_one("#status-bar", StatusBar)
        mcp = read_mcp_connections(self._cfg)
        log = self.query_one("#chat-log", RichLog)
        rows = [
            ("model",      self._cfg.model),
            ("thread",     self._cfg.thread_id),
            ("hb tick",    str(hb.tick)),
            ("hb uptime",  f"{hb.uptime:.0f}%"),
            ("hb healthy", str(hb.healthy)),
            ("sandbox",    ("docker" if self._cfg.sandbox_use_docker else "local")
                           if self._cfg.sandbox_enabled else "off"),
            ("mcp",        ", ".join(mcp) if mcp else "none"),
            ("checkpoint", str(self._cfg.checkpoint_db)),
        ]
        log.write(Text.from_markup(
            "[bright_yellow]── Status ───────────────────────────────────────[/bright_yellow]\n"
        ))
        for key, val in rows:
            log.write(Text.from_markup(
                f"  [bright_black]{key:<14}[/bright_black] [white]{val}[/white]\n"
            ))

    def _cmd_sandbox(self) -> None:
        if self._cfg.sandbox_enabled:
            mode = ("docker (--network none, 512 MB RAM)"
                    if self._cfg.sandbox_use_docker
                    else "restricted-local (allowlist + ulimits)")
            self._append_chat("sys", f"Sandbox: {mode}")
            self._append_chat("sys", "Use /sandbox off | /sandbox docker | /sandbox local to change")
        else:
            self._append_chat("sys", "Sandbox: disabled  · use /sandbox on or /sandbox docker")

    def _cmd_sandbox_set(self, *, enabled: bool, docker: bool) -> None:
        self._cfg.sandbox_enabled    = enabled
        self._cfg.sandbox_use_docker = docker if enabled else False
        if not enabled:
            label = "disabled"
        elif docker:
            label = "docker (--network none, 512 MB RAM)"
        else:
            label = "restricted-local (allowlist + ulimits)"
        self._append_chat("sys", f"Sandbox → {label} — restarting…")
        self.post_message(AgentRestart())

    def _cmd_restart(self) -> None:
        self._append_chat("sys", "Restarting agent…")
        self.post_message(AgentRestart())

    def _cmd_set_model(self, name: str) -> None:
        if not name:
            self._append_chat("sys", "Usage: /set model <ollama-model-name>")
            return
        self._cfg.model = name
        header = self.query_one("#app-header", AppHeader)
        header.model_name = name
        self._append_chat("sys", f"Model set to [cyan]{name}[/cyan] — restarting agent…")
        self.post_message(AgentRestart())

    def _cmd_mcp_list(self) -> None:
        from alphaloop.mcp import read_mcp_connections
        servers = read_mcp_connections(self._cfg)
        log = self.query_one("#chat-log", RichLog)
        if not servers:
            log.write(Text.from_markup(
                "  [bright_black]No MCP servers configured.  "
                "Use[/bright_black] [cyan]/mcp add <name> <url>[/cyan]\n"
            ))
            return
        log.write(Text.from_markup(
            "[bright_yellow]── MCP Servers ──────────────────────────────────[/bright_yellow]\n"
        ))
        for name, spec in servers.items():
            transport = spec.get("transport", "?")
            url = spec.get("url") or spec.get("command", "")
            log.write(Text.from_markup(
                f"  [cyan]{name:<16}[/cyan]"
                f" [bright_black]{transport}[/bright_black]"
                f" [white]{url}[/white]\n"
            ))

    def _cmd_mcp_add(self, args: list[str]) -> None:
        """Usage: /mcp add <name> <url> [transport=http|sse|stdio]"""
        if len(args) < 2:  # noqa: PLR2004
            self._append_chat("sys", "Usage: /mcp add <name> <url>  [transport=http]")
            return
        name, url = args[0], args[1]
        transport = "http"
        for a in args[2:]:
            if a.startswith("transport="):
                transport = a.split("=", 1)[1]

        connections = _read_mcp_file(self._cfg)
        connections[name] = {"transport": transport, "url": url}
        _write_mcp_file(self._cfg, connections)

        # Refresh status bar count
        self.query_one("#status-bar", StatusBar).mcp_count = len(connections)
        self._append_chat("sys", f"Added MCP server [cyan]{name}[/cyan] ({transport} {url}) — restarting…")
        self.post_message(AgentRestart())

    def _cmd_mcp_remove(self, name: str) -> None:
        if not name:
            self._append_chat("sys", "Usage: /mcp remove <name>")
            return
        connections = _read_mcp_file(self._cfg)
        if name not in connections:
            self._append_chat("sys", f"Server [cyan]{name}[/cyan] not found")
            return
        del connections[name]
        _write_mcp_file(self._cfg, connections)

        self.query_one("#status-bar", StatusBar).mcp_count = len(connections)
        self._append_chat("sys", f"Removed MCP server [cyan]{name}[/cyan] — restarting…")
        self.post_message(AgentRestart())

    # ------------------------------------------------------------------
    # Agent restart message handler
    # ------------------------------------------------------------------

    def on_agent_restart(self, _: AgentRestart) -> None:
        if self._runner:
            self._do_restart()

    @work(exclusive=True, name="agent-restart")
    async def _do_restart(self) -> None:
        self.post_message(StatusUpdate("Restarting agent…", level="warn"))
        if self._runner:
            await self._runner.restart()

    # ------------------------------------------------------------------
    # Heartbeat / agent message handlers
    # ------------------------------------------------------------------

    def on_heartbeat_tick(self, msg: HeartbeatTick) -> None:
        bar = self.query_one("#status-bar", StatusBar)
        bar.healthy  = msg.healthy
        bar.tick     = msg.stats.total_ticks
        bar.uptime   = msg.stats.uptime_pct
        bar.failures = msg.stats.consecutive_failures

        stats = self.query_one("#hb-stats", HbStats)
        stats.healthy  = msg.healthy
        stats.tick     = msg.stats.total_ticks
        stats.uptime   = msg.stats.uptime_pct
        stats.failures = msg.stats.consecutive_failures

        hb_log = self.query_one("#hb-log", Log)
        ts   = time.strftime("%H:%M:%S")
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
        ts     = time.strftime("%H:%M:%S")
        prefix = {"info": "·", "ok": "✓", "warn": "!", "error": "✗"}.get(msg.level, "·")
        hb_log.write_line(f"{ts}  {prefix}  {msg.text}")

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_clear_chat(self) -> None:
        self._recent_messages.clear()
        self.query_one("#chat-log", RichLog).clear()

    def action_dismiss_preview(self) -> None:
        preview = self.query_one("#cmd-preview", CommandPreview)
        if preview.display:
            preview.display = False
        else:
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
        self._write_chat_line(self.query_one("#chat-log", RichLog), speaker, text)

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

    @work(exclusive=False)
    async def _send_message(self, text: str) -> None:
        if self._runner is None:
            return
        self._append_chat("agent", "…")
        reply = await self._runner.send(text)
        self._rebuild_chat(replace_last=("agent", reply or "(no reply)"))


# ---------------------------------------------------------------------------
# MCP file helpers
# ---------------------------------------------------------------------------


def _read_mcp_file(cfg: Config) -> dict:
    if cfg.mcp_config and cfg.mcp_config.exists():
        try:
            return json.loads(cfg.mcp_config.read_text())
        except Exception:
            pass
    return {}


def _write_mcp_file(cfg: Config, connections: dict) -> None:
    path = cfg.mcp_config or Path("~/.alphaloop/mcp.json").expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(connections, indent=2))
    # Ensure config points to the file
    cfg.mcp_config = path  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Background runner
# ---------------------------------------------------------------------------


class _BackgroundRunner:
    """Manages the agent + heartbeat as background asyncio tasks inside Textual."""

    def __init__(self, config: Config, app: AlphaLoopApp) -> None:
        self._cfg  = config
        self._app  = app
        self._graph       = None
        self._agent_stack = None
        self._monitor: HeartbeatMonitor | None = None
        self._hb_task:  asyncio.Task | None    = None

    def start_all(self) -> None:
        self._app.run_worker(self._boot(), exclusive=False, name="agent-boot")

    async def restart(self) -> None:
        await self.stop()
        await self._boot()

    async def _boot(self) -> None:
        from alphaloop.agent import create_agent
        from alphaloop.mcp import read_mcp_connections

        self._app.post_message(StatusUpdate("Booting agent…"))
        graph, _, stack = await create_agent(self._cfg)
        self._graph       = graph
        self._agent_stack = stack

        # Update status bar MCP count
        mcp_servers = read_mcp_connections(self._cfg)
        self._app.query_one("#status-bar", StatusBar).mcp_count = len(mcp_servers)

        parts = [f"Ready  model={self._cfg.model}"]
        if self._cfg.sandbox_enabled:
            mode = "docker" if self._cfg.sandbox_use_docker else "local"
            parts.append(f"sandbox={mode}")
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
        self._graph = None


# ---------------------------------------------------------------------------
# Heartbeat monitor (Textual-aware)
# ---------------------------------------------------------------------------


class _TuiHeartbeatMonitor(HeartbeatMonitor):
    """Posts Textual messages instead of plain log calls."""

    def __init__(self, graph, config: Config, app: AlphaLoopApp) -> None:  # noqa: ANN001
        super().__init__(graph, config)
        self._app = app

    async def _tick(self) -> None:
        await super()._tick()
        self._app.post_message(
            HeartbeatTick(stats=self.stats,
                          healthy=self.stats.consecutive_failures == 0)
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
