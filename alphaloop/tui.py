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
import shlex
import time
from collections import deque
from pathlib import Path
from typing import ClassVar

from rich.markdown import Markdown
from rich.padding import Padding
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.events import Key
from textual.message import Message
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import (
    Footer,
    Input,
    Label,
    Log,
    OptionList,
    RichLog,
    Static,
    TextArea,
)
from textual.widgets.option_list import Option

from alphaloop.config import Config, get_config
from alphaloop.heartbeat import HeartbeatMonitor, HeartbeatStats
from alphaloop.logger import setup_logging
from alphaloop.mcp import build_mcp_document, normalize_mcp_connection, read_mcp_document


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
    ("/models",           "Open interactive model picker (Ollama)"),
    ("/set model",        "Switch Ollama model  · /set model <name>"),
    ("/mcp list",         "List connected MCP servers"),
    ("/mcp add",          "Add MCP server  · /mcp add <name> <url|json-spec>  [transport=http]"),
    ("/mcp remove",       "Remove MCP server  · /mcp remove <name>"),
    ("/sandbox",          "Show sandbox status"),
    ("/sandbox on",       "Enable restricted-local sandbox"),
    ("/sandbox off",      "Disable sandbox"),
    ("/sandbox docker",   "Switch to Docker isolation (--network none, 512MB)"),
    ("/sandbox local",    "Switch to restricted-local sandbox"),
    ("/skills",           "List available agent skills"),
    ("/skills on",        "Enable a skill  · /skills on <name>"),
    ("/skills off",       "Disable a skill  · /skills off <name>"),
    ("/mcp auth",         "Authenticate with an MCP server via OAuth  · /mcp auth <name>"),
    ("/mcp deauth",       "Remove stored OAuth token  · /mcp deauth <name>"),
    ("/copy",             "Copy last AI response to clipboard  (also Ctrl+Y)"),
    ("/export",           "Open full conversation in a selectable text view"),
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


class ChatLog(RichLog):
    """RichLog that can receive keyboard focus (for scrolling and copy shortcuts)."""
    can_focus = True


class HistoryInput(Input):
    """Input widget with ↑/↓ message history navigation.

    When the slash-command preview is visible, the same keys navigate that
    preview instead of chat history.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._history: list[str] = []
        self._history_idx: int = -1
        self._history_draft: str = ""

    def push_history(self, text: str) -> None:
        """Record a sent message in history and reset the cursor."""
        if not self._history or self._history[-1] != text:
            self._history.append(text)
        self._history_idx = -1
        self._history_draft = ""

    def key_up(self, event: Key) -> None:
        preview = self.app.query_one("#cmd-preview", CommandPreview)
        if preview.display:
            preview.move_up()
        else:
            self._go_up()
        event.prevent_default()
        event.stop()

    def key_down(self, event: Key) -> None:
        preview = self.app.query_one("#cmd-preview", CommandPreview)
        if preview.display:
            preview.move_down()
        else:
            self._go_down()
        event.prevent_default()
        event.stop()

    def _go_up(self) -> None:
        if not self._history:
            return
        if self._history_idx == -1:
            self._history_draft = self.value
            self._history_idx = len(self._history) - 1
        elif self._history_idx > 0:
            self._history_idx -= 1
        self.value = self._history[self._history_idx]
        self.cursor_position = len(self.value)

    def _go_down(self) -> None:
        if self._history_idx == -1:
            return
        if self._history_idx < len(self._history) - 1:
            self._history_idx += 1
            self.value = self._history[self._history_idx]
        else:
            self._history_idx = -1
            self.value = self._history_draft
            self._history_draft = ""
        self.cursor_position = len(self.value)


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
# Export / conversation view modal
# ---------------------------------------------------------------------------


class ExportScreen(ModalScreen[None]):
    """Full-screen modal showing the raw conversation as selectable text."""

    BINDINGS = [Binding("escape", "dismiss", "Close", show=True),
                Binding("ctrl+a", "select_all", "Select all", show=True)]

    CSS = """
    ExportScreen {
        align: center middle;
    }
    #export-dialog {
        width: 90%;
        height: 90%;
        background: #0f0f12;
        border: solid #f59e0b;
        padding: 0;
    }
    #export-title {
        height: 2;
        background: #0f0f12;
        color: #f59e0b;
        text-style: bold;
        content-align: center middle;
        border-bottom: solid #27272a;
    }
    #export-hint {
        height: 1;
        background: #0f0f12;
        color: #3f3f46;
        content-align: center middle;
        border-top: solid #27272a;
    }
    #export-area {
        height: 1fr;
        background: #08080a;
        color: #a1a1aa;
        border: none;
    }
    """

    def __init__(self, transcript: str) -> None:
        super().__init__()
        self._transcript = transcript

    def compose(self) -> ComposeResult:
        with Vertical(id="export-dialog"):
            yield Label("  CONVERSATION EXPORT", id="export-title")
            area = TextArea(self._transcript, id="export-area", read_only=True)
            yield area
            yield Label(
                "  Select text then Ctrl+C to copy  ·  Ctrl+A select all  ·  Esc close",
                id="export-hint",
            )

    def on_mount(self) -> None:
        self.query_one("#export-area", TextArea).focus()

    def action_select_all(self) -> None:
        area = self.query_one("#export-area", TextArea)
        area.select_all()


# ---------------------------------------------------------------------------
# Ollama model helpers
# ---------------------------------------------------------------------------


async def _fetch_ollama_models(base_url: str) -> list[tuple[str, str]]:
    """Return [(name, size_label), …] from Ollama /api/tags, or [] on error."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{base_url}/api/tags")
            resp.raise_for_status()
            models = resp.json().get("models", [])
            result = []
            for m in models:
                name = m.get("name", "")
                size = m.get("size", 0)
                gb   = size / 1_073_741_824
                label = f"{gb:.1f} GB" if gb >= 0.1 else f"{size // 1_048_576} MB"  # noqa: PLR2004
                result.append((name, label))
            return sorted(result, key=lambda x: x[0])
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Model picker modal
# ---------------------------------------------------------------------------


class ModelPickerScreen(ModalScreen[str | None]):
    """Full-screen modal for selecting an Ollama model."""

    BINDINGS = [Binding("escape", "dismiss_none", "Cancel", show=True)]

    CSS = """
    ModelPickerScreen {
        align: center middle;
    }
    #picker-dialog {
        width: 70;
        height: auto;
        max-height: 30;
        background: #0f0f12;
        border: solid #f59e0b;
        padding: 1 2;
    }
    #picker-title {
        height: 2;
        color: #f59e0b;
        text-style: bold;
        content-align: center middle;
        border-bottom: solid #27272a;
        margin-bottom: 1;
    }
    #picker-hint {
        height: 1;
        color: #3f3f46;
        content-align: center middle;
        margin-top: 1;
    }
    #picker-loading {
        height: 3;
        color: #52525b;
        content-align: center middle;
    }
    OptionList {
        background: #0f0f12;
        border: none;
        height: auto;
        max-height: 20;
        scrollbar-color: #27272a #0f0f12;
        scrollbar-size: 1 1;
    }
    OptionList > .option-list--option {
        color: #a1a1aa;
        padding: 0 1;
    }
    OptionList > .option-list--option-highlighted {
        background: #1a1a0a;
        color: #f59e0b;
        text-style: bold;
    }
    """

    def __init__(self, base_url: str, current_model: str) -> None:
        super().__init__()
        self._base_url      = base_url
        self._current_model = current_model

    def compose(self) -> ComposeResult:
        with Vertical(id="picker-dialog"):
            yield Label("  SELECT MODEL", id="picker-title")
            yield Label("Fetching models from Ollama…", id="picker-loading")
            yield Label("↑ ↓ navigate  ·  Enter select  ·  Esc cancel", id="picker-hint")

    def on_mount(self) -> None:
        self._load_models()

    @work(exclusive=True)
    async def _load_models(self) -> None:
        models = await _fetch_ollama_models(self._base_url)
        loading = self.query_one("#picker-loading", Label)
        if not models:
            loading.update("[red]No models found — is Ollama running?[/red]")
            return

        loading.remove()
        options = []
        for name, size in models:
            marker = " ●" if name == self._current_model else "  "
            options.append(Option(
                Text.from_markup(
                    f"[cyan]{marker} {name}[/cyan]  [bright_black]{size}[/bright_black]"
                ),
                id=name,
            ))

        ol = OptionList(*options, id="picker-list")
        await self.query_one("#picker-dialog").mount(ol, before="#picker-hint")
        ol.focus()

        # Pre-select current model if present
        for i, (name, _) in enumerate(models):
            if name == self._current_model:
                ol.highlighted = i
                break

    @on(OptionList.OptionSelected, "#picker-list")
    def on_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id)

    def action_dismiss_none(self) -> None:
        self.dismiss(None)


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
    #chat-log:focus {{
        border: solid {_AMBER};
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
        Binding("ctrl+c", "quit",            "Quit"),
        Binding("ctrl+l", "clear_chat",      "Clear"),
        Binding("ctrl+m", "open_models",     "Models"),
        Binding("ctrl+y", "copy_last",       "Copy"),
        Binding("ctrl+e", "export_chat",     "Export"),
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
                yield ChatLog(id="chat-log", highlight=False, markup=False, wrap=True)
            with Vertical(id="sidebar"):
                yield HbStats(id="hb-stats")
                yield Static("  HEARTBEAT LOG", id="sidebar-log-header")
                yield Log(id="hb-log", highlight=False)
        yield CommandPreview(id="cmd-preview")
        with Horizontal(id="input-row"):
            yield Static("▶", id="prompt-label")
            yield HistoryInput(placeholder="Message or /help for commands…", id="user-input")
        yield Footer()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_mount(self) -> None:
        setup_logging("WARNING")
        self._runner = _BackgroundRunner(self._cfg, self)
        self._runner.start_all()
        self.query_one("#user-input", HistoryInput).focus()

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
        inp = self.query_one("#user-input", HistoryInput)
        event.input.clear()
        self.query_one("#cmd-preview", CommandPreview).display = False
        if text.startswith("/"):
            self._handle_slash_command(text)
        else:
            inp.push_history(text)
            self._append_chat("you", text)
            self._send_message(text)

    def on_key(self, event: Key) -> None:
        preview = self.query_one("#cmd-preview", CommandPreview)
        inp     = self.query_one("#user-input", HistoryInput)

        if preview.display:
            # Command preview is open — Up/Down/Tab/Escape control it
            if event.key == "up":
                preview.move_up()
                event.prevent_default()
            elif event.key == "down":
                preview.move_down()
                event.prevent_default()
            elif event.key == "tab":
                cmd = preview.selected_command()
                if cmd:
                    inp.value          = cmd + " "
                    inp.cursor_position = len(inp.value)
                    preview.filter(cmd)
                event.prevent_default()
            elif event.key == "escape":
                preview.display = False
                event.prevent_default()
            return

        chat_log = self.query_one("#chat-log", ChatLog)

        # Ctrl+V: paste into input from anywhere except when the input itself has focus
        # (when input is focused, its native Ctrl+V paste handler works unblocked)
        if event.key == "ctrl+v" and self.focused is not inp:
            self.action_paste_to_input()
            event.prevent_default()
            return

        # When chat panel is focused: Ctrl+C copies last message
        if self.focused is chat_log:
            if event.key == "ctrl+c":
                self.action_copy_last()
                event.prevent_default()
            return

    # ------------------------------------------------------------------
    # /command dispatcher
    # ------------------------------------------------------------------

    def _handle_slash_command(self, text: str) -> None:
        try:
            parts = shlex.split(text)
        except ValueError as exc:
            self._append_chat("sys", f"Command parse error: {exc}")
            return
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
        elif cmd in ("/models", "/model"):
            self._open_model_picker()
        elif cmd == "/copy":
            self.action_copy_last()
        elif cmd == "/export":
            self.action_export_chat()
        elif cmd == "/thread":
            self._append_chat("sys", f"thread={self._cfg.thread_id}")
        elif two == "/set model":
            name = parts[2] if len(parts) > 2 else ""
            if name:
                self._cmd_set_model(name)
            else:
                self._open_model_picker()
        elif two == "/mcp list":
            self._cmd_mcp_list()
        elif two == "/mcp add":
            self._cmd_mcp_add(parts[2:] if len(parts) > 2 else [])
        elif two == "/mcp remove":
            self._cmd_mcp_remove(parts[2] if len(parts) > 2 else "")
        elif two == "/mcp auth":
            self._cmd_mcp_auth(parts[2] if len(parts) > 2 else "")
        elif two == "/mcp deauth":
            self._cmd_mcp_deauth(parts[2] if len(parts) > 2 else "")
        elif cmd == "/mcp":
            self._cmd_mcp_list()
        elif two == "/skills on":
            self._cmd_skills_on(parts[2] if len(parts) > 2 else "")
        elif two == "/skills off":
            self._cmd_skills_off(parts[2] if len(parts) > 2 else "")
        elif cmd == "/skills":
            self._cmd_skills_list()
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
        log = self.query_one("#chat-log", ChatLog)
        title = Text("── Commands ─────────────────────────────────────\n", style="bright_yellow")
        log.write(title)
        for cmd, desc in _COMMANDS:
            row = Text()
            row.append(f"  {cmd:<22}", style="cyan")
            row.append(desc + "\n",   style="bright_black")
            log.write(row)

    def _cmd_status(self) -> None:
        from alphaloop.mcp import read_mcp_connections
        hb  = self.query_one("#status-bar", StatusBar)
        mcp = read_mcp_connections(self._cfg)
        log = self.query_one("#chat-log", ChatLog)
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
        log.write(Text("── Status ───────────────────────────────────────\n", style="bright_yellow"))
        for key, val in rows:
            row = Text()
            row.append(f"  {key:<16}", style="bright_black")
            row.append(val + "\n",    style="white")
            log.write(row)

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

    def _open_model_picker(self) -> None:
        def _on_pick(model: str | None) -> None:
            if model:
                self._cmd_set_model(model)

        self.push_screen(
            ModelPickerScreen(self._cfg.ollama_base_url, self._cfg.model),
            _on_pick,
        )

    def _cmd_set_model(self, name: str) -> None:
        self._cfg.model = name
        self.query_one("#app-header", AppHeader).model_name = name
        self._append_chat("sys", f"Model → {name}  restarting agent…")
        self.post_message(AgentRestart())

    def _cmd_mcp_list(self) -> None:
        from alphaloop.mcp import read_mcp_connections
        servers = read_mcp_connections(self._cfg)
        log = self.query_one("#chat-log", ChatLog)
        if not servers:
            row = Text()
            row.append("  No MCP servers configured.  Use ", style="bright_black")
            row.append("/mcp add <name> <url|json-spec>",    style="cyan")
            row.append("\n")
            log.write(row)
            return
        log.write(Text("── MCP Servers ──────────────────────────────────\n", style="bright_yellow"))
        for name, spec in servers.items():
            transport = spec.get("transport", "?")
            url = spec.get("url") or spec.get("command", "")
            row = Text()
            row.append(f"  {name:<18}", style="cyan")
            row.append(f"{transport:<8}", style="bright_black")
            row.append(url + "\n",       style="white")
            log.write(row)

    def _cmd_mcp_add(self, args: list[str]) -> None:
        """Usage: /mcp add <name> <url|json-spec> [transport=http|sse|stdio]"""
        if len(args) < 2:  # noqa: PLR2004
            self._append_chat(
                "sys",
                "Usage: /mcp add <name> <url|json-spec>  [transport=http]",
            )
            return
        name, payload = args[0], args[1]
        transport = "http"
        for a in args[2:]:
            if a.startswith("transport="):
                transport = a.split("=", 1)[1]

        try:
            spec = _coerce_mcp_spec(payload, transport)
        except ValueError as exc:
            self._append_chat("sys", str(exc))
            return

        connections, wrapper_key, extras = read_mcp_document(self._cfg)
        connections[name] = spec
        _write_mcp_file(self._cfg, connections, wrapper_key=wrapper_key, extras=extras)

        # Refresh status bar count
        self.query_one("#status-bar", StatusBar).mcp_count = len(connections)
        descriptor = spec.get("url") or spec.get("command") or "custom spec"
        self._append_chat("sys", f"Added MCP server '{name}' ({descriptor}) — restarting…")
        self.post_message(AgentRestart())

    def _cmd_mcp_remove(self, name: str) -> None:
        if not name:
            self._append_chat("sys", "Usage: /mcp remove <name>")
            return
        connections, wrapper_key, extras = read_mcp_document(self._cfg)
        if name not in connections:
            self._append_chat("sys", f"Server '{name}' not found")
            return
        del connections[name]
        _write_mcp_file(self._cfg, connections, wrapper_key=wrapper_key, extras=extras)

        self.query_one("#status-bar", StatusBar).mcp_count = len(connections)
        self._append_chat("sys", f"Removed MCP server '{name}' — restarting…")
        self.post_message(AgentRestart())

    # ------------------------------------------------------------------
    # MCP OAuth commands
    # ------------------------------------------------------------------

    def _cmd_mcp_auth(self, name: str) -> None:
        if not name:
            self._append_chat("sys", "Usage: /mcp auth <server-name>")
            return
        connections = _read_mcp_file(self._cfg)
        if name not in connections:
            self._append_chat("sys", f"Server '{name}' not found — add it first with /mcp add")
            return
        spec = connections[name]
        url  = spec.get("url") or spec.get("command", "")
        if not url.startswith("http"):
            self._append_chat("sys", "OAuth is only supported for http/sse MCP servers.")
            return
        self._do_mcp_auth(name, url)

    @work(exclusive=False)
    async def _do_mcp_auth(self, name: str, url: str) -> None:
        from alphaloop.mcp_oauth import run_oauth_flow

        async def _progress(msg: str) -> None:
            self._append_chat("sys", msg)

        token = await run_oauth_flow(name, url, on_progress=_progress)
        if token:
            self._append_chat("sys", f"Authenticated with '{name}'. Restarting agent…")
            self.post_message(AgentRestart())
        else:
            self._append_chat("sys", "OAuth flow failed or was cancelled.")

    def _cmd_mcp_deauth(self, name: str) -> None:
        if not name:
            self._append_chat("sys", "Usage: /mcp deauth <server-name>")
            return
        from alphaloop.mcp_oauth import delete_token, get_token
        if not get_token(name):
            self._append_chat("sys", f"No stored token for '{name}'.")
            return
        delete_token(name)
        self._append_chat("sys", f"Token removed for '{name}'. Restarting…")
        self.post_message(AgentRestart())

    # ------------------------------------------------------------------
    # Skills commands
    # ------------------------------------------------------------------

    def _cmd_skills_list(self) -> None:
        from alphaloop.skills import REGISTRY, load_enabled
        enabled = load_enabled()
        log = self.query_one("#chat-log", ChatLog)
        log.write(Text("── Skills ───────────────────────────────────────\n", style="bright_yellow"))
        for skill_name, info in REGISTRY.items():
            active = skill_name in enabled
            status_style = "bright_green" if active else "bright_black"
            status_label = "ON " if active else "OFF"
            row = Text()
            row.append(f"  [{status_label}] ", style=status_style)
            row.append(f"{skill_name:<18}", style="cyan" if active else "bright_black")
            row.append(info.description + "\n", style="white" if active else "bright_black")
            log.write(row)
        log.write(Text(
            "  Use /skills on <name> or /skills off <name> to toggle.\n",
            style="bright_black",
        ))

    def _cmd_skills_on(self, name: str) -> None:
        if not name:
            self._append_chat("sys", "Usage: /skills on <skill-name>")
            self._cmd_skills_list()
            return
        from alphaloop.skills import enable_skill, REGISTRY
        if name not in REGISTRY:
            self._append_chat("sys", f"Unknown skill '{name}'. Type /skills to see available skills.")
            return
        enable_skill(name)
        self._append_chat("sys", f"Skill '{name}' enabled — restarting agent…")
        self.post_message(AgentRestart())

    def _cmd_skills_off(self, name: str) -> None:
        if not name:
            self._append_chat("sys", "Usage: /skills off <skill-name>")
            return
        from alphaloop.skills import disable_skill
        if not disable_skill(name):
            self._append_chat("sys", f"Skill '{name}' was not enabled.")
            return
        self._append_chat("sys", f"Skill '{name}' disabled — restarting agent…")
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
        self.query_one("#chat-log", ChatLog).clear()

    def action_open_models(self) -> None:
        self._open_model_picker()

    def action_export_chat(self) -> None:
        self.push_screen(ExportScreen(self._build_plain_transcript()))

    def action_paste_to_input(self) -> None:
        """Paste clipboard text into the input field (works from anywhere)."""
        inp = self.query_one("#user-input", HistoryInput)
        text = self._clipboard_paste()
        if not text:
            return
        # Insert at cursor position
        pos = inp.cursor_position
        inp.value = inp.value[:pos] + text + inp.value[pos:]
        inp.cursor_position = pos + len(text)
        inp.focus()

    def action_dismiss_preview(self) -> None:
        preview = self.query_one("#cmd-preview", CommandPreview)
        if preview.display:
            preview.display = False
        else:
            self.query_one("#user-input", HistoryInput).blur()

    def action_copy_last(self) -> None:
        """Copy the most recent agent/pulse response to the system clipboard."""
        for speaker, text in reversed(self._recent_messages):
            if speaker in ("agent", "pulse") and text not in ("…", "(no reply)"):
                if self._clipboard_copy(text):
                    self._append_chat("sys", "Copied last response to clipboard.")
                else:
                    self._append_chat("sys", "Clipboard unavailable — see chat log for text.")
                return
        self._append_chat("sys", "No agent response to copy yet.")


    # ------------------------------------------------------------------
    # Clipboard helper
    # ------------------------------------------------------------------

    @staticmethod
    def _clipboard_copy(text: str) -> bool:
        """Write *text* to the system clipboard. Returns True on success."""
        import subprocess, sys
        try:
            if sys.platform == "darwin":
                subprocess.run(["pbcopy"], input=text.encode(), check=True, timeout=3)
                return True
            if sys.platform.startswith("linux"):
                for cmd in (["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]):
                    try:
                        subprocess.run(cmd, input=text.encode(), check=True, timeout=3)
                        return True
                    except FileNotFoundError:
                        continue
            if sys.platform == "win32":
                subprocess.run(["clip"], input=text.encode("utf-16-le"), check=True, timeout=3)
                return True
        except Exception:
            pass
        # Last resort: pyperclip
        try:
            import pyperclip  # type: ignore[import]
            pyperclip.copy(text)
            return True
        except Exception:
            return False

    @staticmethod
    def _clipboard_paste() -> str:
        """Read text from the system clipboard. Returns empty string on failure."""
        import subprocess, sys
        try:
            if sys.platform == "darwin":
                result = subprocess.run(["pbpaste"], capture_output=True, timeout=3)
                return result.stdout.decode(errors="replace")
            if sys.platform.startswith("linux"):
                for cmd in (["xclip", "-selection", "clipboard", "-o"],
                            ["xsel", "--clipboard", "--output"]):
                    try:
                        result = subprocess.run(cmd, capture_output=True, timeout=3)
                        return result.stdout.decode(errors="replace")
                    except FileNotFoundError:
                        continue
            if sys.platform == "win32":
                result = subprocess.run(["powershell", "-command", "Get-Clipboard"],
                                        capture_output=True, timeout=3)
                return result.stdout.decode(errors="replace").strip()
        except Exception:
            pass
        try:
            import pyperclip  # type: ignore[import]
            return pyperclip.paste()
        except Exception:
            return ""

    def _build_plain_transcript(self) -> str:
        """Render the conversation as a plain-text string for the export view."""
        lines: list[str] = ["── AlphaLoop Conversation ──────────────────────────", ""]
        for speaker, text in self._recent_messages:
            _, label = self._SPEAKER_STYLE.get(speaker, ("", speaker.upper()))
            lines.append(f"[{label}]")
            lines.append(text)
            lines.append("")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Chat helpers
    # ------------------------------------------------------------------

    _SPEAKER_STYLE: ClassVar[dict[str, tuple[str, str]]] = {
        "you":   ("bold bright_cyan",   "YOU"),
        "agent": ("bold bright_green",  "AGENT"),
        "pulse": ("dim green",          "PULSE"),
        "sys":   ("bold bright_yellow", "SYS"),
    }
    # Speakers whose content should be rendered as Markdown
    _MARKDOWN_SPEAKERS: ClassVar[frozenset[str]] = frozenset({"agent", "pulse"})

    def _append_chat(self, speaker: str, text: str) -> None:
        self._recent_messages.append((speaker, text))
        self._write_chat_line(self.query_one("#chat-log", ChatLog), speaker, text)

    def _write_chat_line(self, log: RichLog, speaker: str, text: str) -> None:
        style, label = self._SPEAKER_STYLE.get(speaker, ("white", speaker.upper()))
        ts = time.strftime("%H:%M:%S")

        # Header row: timestamp + speaker badge
        header = Text(no_wrap=True)
        header.append(ts,     style="bright_black")
        header.append("  ")
        header.append(label,  style=style)
        log.write(header)

        if speaker in self._MARKDOWN_SPEAKERS and text not in ("…", "(no reply)"):
            # Render body as Markdown, indented 2 spaces to align under the label
            md = Markdown(text, code_theme="monokai", hyperlinks=False)
            log.write(Padding(md, pad=(0, 0, 1, 2)))
        else:
            # Plain text for user input, sys messages, and placeholders
            body = Text(no_wrap=False)
            body.append("  ")
            body.append(text, style="white" if speaker != "sys" else "bright_black")
            body.append("\n")
            log.write(body)

    def _rebuild_chat(self, replace_last: tuple[str, str] | None = None) -> None:
        log = self.query_one("#chat-log", ChatLog)
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
    connections, _, _ = read_mcp_document(cfg)
    return connections


def _write_mcp_file(
    cfg: Config,
    connections: dict,
    *,
    wrapper_key: str | None = None,
    extras: dict | None = None,
) -> None:
    path = cfg.mcp_config or Path("~/.alphaloop/mcp.json").expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_connections, existing_wrapper, existing_extras = read_mcp_document(cfg)
    del existing_connections  # not needed; only here to preserve wrapper metadata
    wrapper = wrapper_key if wrapper_key is not None else existing_wrapper
    metadata = extras if extras is not None else existing_extras
    if wrapper is None and metadata:
        wrapper = "mcpServers"
    document = build_mcp_document(connections, wrapper_key=wrapper, extras=metadata)
    path.write_text(json.dumps(document, indent=2))
    # Ensure config points to the file
    cfg.mcp_config = path  # type: ignore[assignment]


def _coerce_mcp_spec(payload: str, default_transport: str) -> dict[str, object]:
    """Parse a server payload from a URL or a JSON object."""
    payload = payload.strip()
    if not payload:
        raise ValueError("MCP server URL/spec cannot be empty.")

    if payload.startswith("{"):
        try:
            spec = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid MCP JSON spec: {exc.msg}") from exc
        if not isinstance(spec, dict):
            raise ValueError("MCP JSON spec must be an object.")
        if "servers" in spec or "mcpServers" in spec:
            raise ValueError("Pass a single server spec, not a whole MCP document.")
        spec = normalize_mcp_connection(spec)
        if "transport" not in spec:
            if "command" in spec:
                spec["transport"] = "stdio"
            elif "url" in spec:
                spec["transport"] = default_transport
        return spec

    if payload.startswith("http://") or payload.startswith("https://"):
        return {"transport": default_transport, "url": payload}

    raise ValueError("Use an http(s) URL or quote a JSON server spec.")


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
