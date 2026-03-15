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
import difflib
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
    ("/palette",         "Open command palette"),
    ("/help",             "Show available commands"),
    ("/new",              "Start a new session (generates new thread)"),
    ("/clear",            "Clear chat history (keeps current thread)"),
    ("/status",           "Show config & heartbeat state"),
    ("/restart",          "Restart the agent"),
    ("/provider",         "Show current provider"),
    ("/providers",        "List supported providers"),
    ("/models",           "Open interactive model picker (Ollama)"),
    ("/set provider",     "Switch provider  · /set provider <name>"),
    ("/set model",        "Switch model  · /set model <name>"),
    ("/set endpoint",     "Set provider endpoint  · /set endpoint <url>"),
    ("/set key",          "Set provider API key  · /set key <token>"),
    ("/mcp list",         "List connected MCP servers"),
    ("/mcp add",          "Add MCP server  · /mcp add <name> <url|json-spec>  [transport=streamable_http]"),
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
    ("/copy chat",        "Copy full chat transcript to clipboard"),
    ("/paste",            "Paste clipboard text into the input box"),
    ("/export",           "Open full conversation in a selectable text view"),
    ("/thread",           "Show current thread ID"),
    ("/tips",             "Show productivity shortcuts"),
    ("/channels",         "List configured communication channels"),
    ("/channels start",   "Start a channel  · /channels start <telegram|whatsapp>"),
    ("/channels stop",    "Stop a channel   · /channels stop <telegram|whatsapp>"),
]


# ---------------------------------------------------------------------------
# Widgets
# ---------------------------------------------------------------------------


class AppHeader(Static):
    """Brand header — logo + model + thread (updated on restart)."""

    model_name: reactive[str] = reactive("")
    provider_name: reactive[str] = reactive("")

    def __init__(self, config: Config, **kwargs) -> None:
        super().__init__(**kwargs)
        self._cfg = config
        self.model_name = config.model
        self.provider_name = config.provider

    def render(self) -> Text:
        t = Text(overflow="ellipsis", no_wrap=True)
        t.append("  ◉ ", style="bold bright_yellow")
        t.append("ALPHALOOP", style="bold white")
        t.append("  │  ", style="bright_black")
        t.append("provider=", style="bright_black")
        t.append(self.provider_name, style="magenta")
        t.append("  │  ", style="bright_black")
        t.append("model=", style="bright_black")
        t.append(self.model_name, style="cyan")
        t.append("  │  ", style="bright_black")
        t.append("thread=", style="bright_black")
        t.append(self._cfg.thread_id, style="yellow")
        return t


class StatusBar(Static):
    """Live heartbeat + sandbox + MCP + channel state."""

    healthy:   reactive[bool]  = reactive(True)
    tick:      reactive[int]   = reactive(0)
    uptime:    reactive[float] = reactive(100.0)
    failures:  reactive[int]   = reactive(0)
    mcp_count: reactive[int]   = reactive(0)
    mcp_tools: reactive[int]   = reactive(0)
    channels:  reactive[int]   = reactive(0)

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
        t.append("  │  mcp=", style="bright_black")
        if self.mcp_count:
            t.append(str(self.mcp_count), style="bright_green")
            t.append(" tools=", style="bright_black")
            if self.mcp_tools:
                t.append(str(self.mcp_tools), style="bright_green")
            else:
                t.append("0", style="bright_red")
        else:
            t.append("none", style="bright_black")
        t.append("  │  ch=", style="bright_black")
        if self.channels:
            t.append(str(self.channels), style="bright_green")
        else:
            t.append("0", style="bright_black")
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
    _offset: int
    _max_visible: int

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._matches = []
        self._selected = 0
        self._offset = 0
        self._max_visible = 10

    # -- public API ----------------------------------------------------------

    def filter(self, prefix: str) -> None:
        """Filter command list to entries matching *prefix* and refresh."""
        p = prefix.lower()
        self._matches = [(cmd, desc) for cmd, desc in _COMMANDS if cmd.startswith(p)]
        self._selected = 0
        self._offset = 0
        self._sync_height()
        self.refresh()

    def move_up(self) -> None:
        if self._matches:
            self._selected = (self._selected - 1) % len(self._matches)
            self._ensure_visible()
            self.refresh()

    def move_down(self) -> None:
        if self._matches:
            self._selected = (self._selected + 1) % len(self._matches)
            self._ensure_visible()
            self.refresh()

    def page_up(self) -> None:
        if self._matches:
            self._selected = max(0, self._selected - self._max_visible)
            self._ensure_visible()
            self.refresh()

    def page_down(self) -> None:
        if self._matches:
            self._selected = min(len(self._matches) - 1, self._selected + self._max_visible)
            self._ensure_visible()
            self.refresh()

    def selected_command(self) -> str:
        if self._matches:
            return self._matches[self._selected][0]
        return ""

    # -- rendering -----------------------------------------------------------

    def render(self) -> Text:
        t = Text()
        window = self._matches[self._offset:self._offset + self._max_visible]
        for rel_i, (cmd, desc) in enumerate(window):
            i = self._offset + rel_i
            if i == self._selected:
                t.append(f" {cmd:<20}", style="bold bright_yellow on #1a1a0a")
                t.append(f" {desc}\n",  style="white on #1a1a0a")
            else:
                t.append(f" {cmd:<20}", style="bright_black")
                t.append(f" {desc}\n",  style="bright_black")

        if len(self._matches) > self._max_visible:
            t.append(
                f" [{self._selected + 1}/{len(self._matches)}] scroll: Up/Down/PgUp/PgDn\n",
                style="bright_black",
            )
        return t

    def _sync_height(self) -> None:
        """Resize widget to fit the number of matches (max 10)."""
        n = min(len(self._matches), self._max_visible)
        self.styles.height = max(n, 0)
        self.display = n > 0

    def _ensure_visible(self) -> None:
        if self._selected < self._offset:
            self._offset = self._selected
        elif self._selected >= self._offset + self._max_visible:
            self._offset = self._selected - self._max_visible + 1


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


class ApiKeyScreen(ModalScreen[str | None]):
    """Prompt for API key with masked input."""

    BINDINGS = [Binding("escape", "dismiss_none", "Cancel", show=True)]

    CSS = """
    ApiKeyScreen {
        align: center middle;
    }
    #apikey-dialog {
        width: 70;
        height: auto;
        background: #0f0f12;
        border: solid #f59e0b;
        padding: 1 2;
    }
    #apikey-title {
        height: 2;
        color: #f59e0b;
        text-style: bold;
        content-align: center middle;
        border-bottom: solid #27272a;
        margin-bottom: 1;
    }
    #apikey-input {
        height: 3;
        border: round #27272a;
        background: #08080a;
        color: #e4e4e7;
    }
    #apikey-hint {
        height: auto;
        color: #3f3f46;
        margin-top: 1;
    }
    """

    def __init__(self, provider: str) -> None:
        super().__init__()
        self._provider = provider

    def compose(self) -> ComposeResult:
        with Vertical(id="apikey-dialog"):
            yield Label("  SET API KEY", id="apikey-title")
            yield Input(
                placeholder=f"Enter API key for provider={self._provider}",
                id="apikey-input",
                password=True,
            )
            yield Label("Press Enter to save  ·  Esc to cancel", id="apikey-hint")

    def on_mount(self) -> None:
        self.query_one("#apikey-input", Input).focus()

    @on(Input.Submitted, "#apikey-input")
    def on_submit(self, event: Input.Submitted) -> None:
        token = event.value.strip()
        self.query_one("#apikey-input", Input).value = ""
        self.dismiss(token or None)

    def action_dismiss_none(self) -> None:
        self.dismiss(None)


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


class CommandPaletteScreen(ModalScreen[str | None]):
    """Searchable command palette for fast discovery and insertion."""

    BINDINGS = [Binding("escape", "dismiss_none", "Cancel", show=True)]

    CSS = """
    CommandPaletteScreen {
        align: center middle;
    }
    #palette-dialog {
        width: 80;
        height: auto;
        max-height: 32;
        background: #0f0f12;
        border: solid #f59e0b;
        padding: 1 2;
    }
    #palette-title {
        height: 2;
        color: #f59e0b;
        text-style: bold;
        content-align: center middle;
        border-bottom: solid #27272a;
        margin-bottom: 1;
    }
    #palette-filter {
        height: 3;
        border: round #27272a;
        margin-bottom: 1;
        background: #08080a;
        color: #e4e4e7;
    }
    #palette-hint {
        height: 1;
        color: #3f3f46;
        content-align: center middle;
        margin-top: 1;
    }
    OptionList {
        background: #0f0f12;
        border: none;
        height: auto;
        max-height: 20;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="palette-dialog"):
            yield Label("  COMMAND PALETTE", id="palette-title")
            yield Input(placeholder="Type to filter commands…", id="palette-filter")
            yield OptionList(id="palette-list")
            yield Label("↑ ↓ navigate  ·  Enter insert  ·  Esc cancel", id="palette-hint")

    def on_mount(self) -> None:
        self._refresh_options("")
        self.query_one("#palette-filter", Input).focus()

    @on(Input.Changed, "#palette-filter")
    def on_filter_changed(self, event: Input.Changed) -> None:
        self._refresh_options(event.value)

    @on(Input.Submitted, "#palette-filter")
    def on_filter_submit(self, _: Input.Submitted) -> None:
        self._dismiss_current()

    @on(OptionList.OptionSelected, "#palette-list")
    def on_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id)

    def _refresh_options(self, query: str) -> None:
        q = query.lower().strip()

        def _score(item: tuple[str, str]) -> tuple[int, str]:
            cmd, desc = item
            cmd_l = cmd.lower()
            desc_l = desc.lower()
            if not q:
                return (0, cmd)
            if cmd_l.startswith(q):
                return (0, cmd)
            if q in cmd_l:
                return (1, cmd)
            if q in desc_l:
                return (2, cmd)
            return (3, cmd)

        scored = sorted(_COMMANDS, key=_score)
        filtered = [item for item in scored if _score(item)[0] < 3]
        if not q:
            filtered = scored

        options = []
        for cmd, desc in filtered[:20]:
            label = Text()
            label.append(f" {cmd:<22}", style="cyan")
            label.append(desc, style="bright_black")
            options.append(Option(label, id=cmd))

        ol = self.query_one("#palette-list", OptionList)
        ol.clear_options()
        if options:
            ol.add_options(options)
            ol.highlighted = 0

    def _dismiss_current(self) -> None:
        ol = self.query_one("#palette-list", OptionList)
        if ol.option_count <= 0:
            self.dismiss(None)
            return
        idx = ol.highlighted
        option = ol.get_option_at_index(idx if idx is not None else 0)
        self.dismiss(option.id)

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
        Binding("ctrl+n", "new_session",     "New"),
        Binding("ctrl+l", "clear_chat",      "Clear"),
        Binding("ctrl+k", "open_palette",    "Palette"),
        Binding("f1",     "show_help",       "Help"),
        Binding("ctrl+r", "restart_agent",   "Restart"),
        Binding("ctrl+m", "open_models",     "Models"),
        Binding("ctrl+y", "copy_last",       "Copy"),
        Binding("ctrl+shift+c", "copy_chat", "Copy Chat"),
        Binding("ctrl+shift+v", "paste_to_input", "Paste"),
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
        self._append_chat(
            "sys",
            "Welcome to AlphaLoop. Press Ctrl+K for command palette, F1 for help, or type /tips.",
        )

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
            elif event.key == "pageup":
                preview.page_up()
                event.prevent_default()
            elif event.key == "pagedown":
                preview.page_down()
                event.prevent_default()
            elif event.key == "enter":
                cmd = preview.selected_command()
                if cmd:
                    inp.value = cmd + " "
                    inp.cursor_position = len(inp.value)
                    preview.filter(cmd)
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
            if event.key == "ctrl+shift+c":
                self.action_copy_chat()
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
        elif cmd == "/palette":
            self.action_open_palette()
        elif cmd == "/new":
            self.action_new_session()
        elif cmd == "/clear":
            self.action_clear_chat()
        elif cmd == "/status":
            self._cmd_status()
        elif cmd == "/restart":
            self._cmd_restart()
        elif cmd == "/provider":
            self._cmd_provider()
        elif cmd == "/providers":
            self._cmd_providers()
        elif cmd in ("/models", "/model"):
            self._open_model_picker()
        elif two == "/copy chat":
            self.action_copy_chat()
        elif cmd == "/copy":
            self.action_copy_last()
        elif cmd == "/paste":
            self.action_paste_to_input()
        elif cmd == "/export":
            self.action_export_chat()
        elif cmd == "/thread":
            self._append_chat("sys", f"thread={self._cfg.thread_id}")
        elif cmd == "/tips":
            self._cmd_tips()
        elif two == "/set model":
            name = parts[2] if len(parts) > 2 else ""
            if name:
                self._cmd_set_model(name)
            else:
                self._open_model_picker()
        elif two == "/set provider":
            name = parts[2] if len(parts) > 2 else ""
            if name:
                self._cmd_set_provider(name)
            else:
                self._cmd_providers()
        elif two == "/set endpoint":
            endpoint = parts[2] if len(parts) > 2 else ""
            self._cmd_set_endpoint(endpoint)
        elif two == "/set key":
            token = parts[2] if len(parts) > 2 else ""
            self._cmd_set_key(token)
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
        elif two == "/channels start":
            self._cmd_channels_start(parts[2] if len(parts) > 2 else "")
        elif two == "/channels stop":
            self._cmd_channels_stop(parts[2] if len(parts) > 2 else "")
        elif cmd == "/channels":
            self._cmd_channels_list()
        else:
            self._append_chat("sys", self._suggest_unknown_command(text))

    def _cmd_help(self) -> None:
        log = self.query_one("#chat-log", ChatLog)
        title = Text("── Commands ─────────────────────────────────────\n", style="bright_yellow")
        log.write(title)
        for cmd, desc in _COMMANDS:
            row = Text()
            row.append(f"  {cmd:<22}", style="cyan")
            row.append(desc + "\n",   style="bright_black")
            log.write(row)
        log.write(Text("  Tip: press Ctrl+K for searchable command palette.\n", style="bright_black"))
        log.write(Text("  Slash menu supports Up/Down/PgUp/PgDn scrolling.\n", style="bright_black"))

    def _cmd_tips(self) -> None:
        tips = [
            "Ctrl+K: open command palette",
            "F1: show help",
            "Ctrl+R: restart agent",
            "Ctrl+M: open local Ollama model picker",
            "Ctrl+Y: copy last AI response",
            "Ctrl+E: export conversation",
            "Type '/': open inline command suggestions",
            "Use PgUp/PgDn to scroll long slash-command lists",
            "Use '/set key' for secure masked API key prompt",
            "Use '/provider' and '/set provider <name>' for runtime model routing",
        ]
        self._append_chat("sys", "Shortcuts:\n- " + "\n- ".join(tips))

    def _suggest_unknown_command(self, text: str) -> str:
        parts = text.strip().split()
        typed = parts[0] if parts else text.strip()
        known = [cmd for cmd, _ in _COMMANDS]
        matches = difflib.get_close_matches(typed.lower(), known, n=1, cutoff=0.5)
        if matches:
            return f"Unknown command: {text}  · maybe {matches[0]} ?"
        return f"Unknown command: {text}  · type /help or press Ctrl+K"

    def _cmd_status(self) -> None:
        from alphaloop.mcp import read_mcp_connections
        hb  = self.query_one("#status-bar", StatusBar)
        mcp = read_mcp_connections(self._cfg)
        log = self.query_one("#chat-log", ChatLog)
        rows = [
            ("provider",   self._cfg.provider),
            ("model",      self._cfg.model),
            ("endpoint",   self._provider_endpoint()),
            ("api key",    "set" if self._provider_key_present() else "missing"),
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

    # ------------------------------------------------------------------
    # /channels commands
    # ------------------------------------------------------------------

    def _cmd_channels_list(self) -> None:
        runner = getattr(self, "_runner", None)
        mgr = getattr(runner, "_channel_manager", None) if runner else None
        if mgr is None:
            self._append_chat("sys", "Channel manager not available — agent may still be booting.")
            return
        names = mgr.channel_names()
        if not names:
            self._append_chat(
                "sys",
                "No channels configured.\n"
                "Set TELEGRAM_BOT_TOKEN and/or WHATSAPP_* environment variables, "
                "then restart.",
            )
            return
        log = self.query_one("#chat-log", ChatLog)
        t = Text()
        t.append("Communication Channels\n", style="bold white")
        for st in mgr.statuses():
            icon = "●" if st.running else "○"
            color = "bright_green" if st.running else "bright_black"
            t.append(f"  {icon} ", style=color)
            t.append(st.name, style="cyan")
            t.append(f" [{st.platform}]", style="bright_black")
            t.append(f"  rx={st.messages_received} tx={st.messages_sent}", style="white")
            if st.last_error:
                t.append(f"  err={st.last_error[:60]}", style="bright_red")
            t.append("\n")
        log.write(t)

    @work(exclusive=False, thread=False)
    async def _cmd_channels_start(self, name: str) -> None:
        runner = getattr(self, "_runner", None)
        mgr = getattr(runner, "_channel_manager", None) if runner else None
        if mgr is None:
            self._append_chat("sys", "Channel manager not ready.")
            return
        if not name:
            # Start all
            names = mgr.channel_names()
            if not names:
                self._append_chat("sys", "No channels configured.")
                return
            for n in names:
                await mgr.start_channel(n)
            status_bar = self.query_one("#status-bar", StatusBar)
            status_bar.channels = sum(1 for s in mgr.statuses() if s.running)
            self._append_chat("sys", f"Started: {', '.join(names)}")
        else:
            ok = await mgr.start_channel(name)
            if ok:
                status_bar = self.query_one("#status-bar", StatusBar)
                status_bar.channels = sum(1 for s in mgr.statuses() if s.running)
                self._append_chat("sys", f"Channel '{name}' started.")
            else:
                self._append_chat("sys", f"Channel '{name}' not found. Use /channels to list.")

    @work(exclusive=False, thread=False)
    async def _cmd_channels_stop(self, name: str) -> None:
        runner = getattr(self, "_runner", None)
        mgr = getattr(runner, "_channel_manager", None) if runner else None
        if mgr is None:
            self._append_chat("sys", "Channel manager not ready.")
            return
        if not name:
            await mgr.stop_all()
            status_bar = self.query_one("#status-bar", StatusBar)
            status_bar.channels = 0
            self._append_chat("sys", "All channels stopped.")
        else:
            ok = await mgr.stop_channel(name)
            if ok:
                status_bar = self.query_one("#status-bar", StatusBar)
                status_bar.channels = sum(1 for s in mgr.statuses() if s.running)
                self._append_chat("sys", f"Channel '{name}' stopped.")
            else:
                self._append_chat("sys", f"Channel '{name}' not found.")

    def _cmd_restart(self) -> None:
        self._append_chat("sys", "Restarting agent…")
        self.post_message(AgentRestart())

    def _cmd_provider(self) -> None:
        self._append_chat(
            "sys",
            f"provider={self._cfg.provider}  endpoint={self._provider_endpoint()}  "
            f"api_key={'set' if self._provider_key_present() else 'missing'}",
        )

    def _cmd_providers(self) -> None:
        self._append_chat("sys", "Supported providers: ollama, openai, anthropic, gemini, ollama_cloud")
        self._append_chat("sys", "Use /set provider <name> to switch")

    def _cmd_set_provider(self, name: str) -> None:
        aliases = {
            "google": "gemini",
            "google-genai": "gemini",
            "ollama-cloud": "ollama_cloud",
        }
        provider = aliases.get(name.lower(), name.lower())
        supported = {"ollama", "openai", "anthropic", "gemini", "ollama_cloud"}
        if provider not in supported:
            self._append_chat("sys", f"Unknown provider '{name}'. Use /providers")
            return
        self._cfg.provider = provider
        header = self.query_one("#app-header", AppHeader)
        header.provider_name = provider
        self._append_chat("sys", f"Provider -> {provider}  restarting agent…")
        self.post_message(AgentRestart())

    def _open_model_picker(self) -> None:
        if self._cfg.provider != "ollama":
            self._append_chat("sys", "Model picker is available only for provider=ollama. Use /set model <name>.")
            return

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

    def _cmd_set_endpoint(self, endpoint: str) -> None:
        if not endpoint:
            self._append_chat("sys", "Usage: /set endpoint <url>")
            return
        if not endpoint.startswith("http://") and not endpoint.startswith("https://"):
            self._append_chat("sys", "Endpoint must start with http:// or https://")
            return

        if self._cfg.provider == "ollama":
            self._cfg.ollama_base_url = endpoint
        elif self._cfg.provider == "openai":
            self._cfg.openai_base_url = endpoint
        elif self._cfg.provider == "ollama_cloud":
            self._cfg.ollama_cloud_base_url = endpoint
        else:
            self._append_chat("sys", f"Provider '{self._cfg.provider}' does not use a configurable endpoint here.")
            return

        self._append_chat("sys", f"Endpoint -> {endpoint}  restarting agent…")
        self.post_message(AgentRestart())

    def _cmd_set_key(self, token: str) -> None:
        if token:
            self._append_chat(
                "sys",
                "Inline API keys are disabled for security. Use /set key to open the secure prompt.",
            )
            return

        self._open_api_key_prompt()

    def _apply_provider_key(self, token: str) -> bool:
        token = token.strip()
        if not token:
            self._append_chat("sys", "API key cannot be empty.")
            return

        if self._cfg.provider == "openai":
            self._cfg.openai_api_key = token
        elif self._cfg.provider == "anthropic":
            self._cfg.anthropic_api_key = token
        elif self._cfg.provider == "gemini":
            self._cfg.gemini_api_key = token
        elif self._cfg.provider == "ollama_cloud":
            self._cfg.ollama_api_key = token
        else:
            self._append_chat("sys", "Provider 'ollama' does not require an API key.")
            return False

        self._append_chat("sys", f"API key updated for provider={self._cfg.provider}  restarting agent…")
        self.post_message(AgentRestart())
        return True

    def _open_api_key_prompt(self) -> None:
        if self._cfg.provider == "ollama":
            self._append_chat("sys", "Provider 'ollama' does not require an API key.")
            return

        def _on_submit(token: str | None) -> None:
            if token:
                self._apply_provider_key(token)
            else:
                self._append_chat("sys", "API key update cancelled.")

        self.push_screen(ApiKeyScreen(self._cfg.provider), _on_submit)

    def _provider_endpoint(self) -> str:
        if self._cfg.provider == "ollama":
            return self._cfg.ollama_base_url
        if self._cfg.provider == "openai":
            return self._cfg.openai_base_url or "https://api.openai.com/v1"
        if self._cfg.provider == "anthropic":
            return "https://api.anthropic.com"
        if self._cfg.provider == "gemini":
            return "https://generativelanguage.googleapis.com"
        if self._cfg.provider == "ollama_cloud":
            return self._cfg.ollama_cloud_base_url
        return "n/a"

    def _provider_key_present(self) -> bool:
        if self._cfg.provider == "openai":
            return bool(self._cfg.openai_api_key)
        if self._cfg.provider == "anthropic":
            return bool(self._cfg.anthropic_api_key)
        if self._cfg.provider == "gemini":
            return bool(self._cfg.gemini_api_key)
        if self._cfg.provider == "ollama_cloud":
            return bool(self._cfg.ollama_api_key)
        return True

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
        """Usage: /mcp add <name> <url|json-spec> [transport=streamable_http|sse|stdio]"""
        if len(args) < 2:  # noqa: PLR2004
            self._append_chat(
                "sys",
                "Usage: /mcp add <name> <url|json-spec>  [transport=streamable_http]",
            )
            return
        name, payload = args[0], args[1]
        transport = "streamable_http"
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

        try:
            token = await run_oauth_flow(name, url, on_progress=_progress)
        except Exception as exc:
            self._append_chat("sys", f"OAuth flow failed: {exc}")
            return
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

    def action_new_session(self) -> None:
        import uuid
        self._cfg.thread_id = str(uuid.uuid4())
        self.query_one("#app-header", AppHeader).refresh()
        self._recent_messages.clear()
        self.query_one("#chat-log", ChatLog).clear()
        self._append_chat("sys", f"Started new session (thread={self._cfg.thread_id}). MCP servers remain attached. Restarting agent…")
        self.post_message(AgentRestart())

    def action_clear_chat(self) -> None:
        self._recent_messages.clear()
        self.query_one("#chat-log", ChatLog).clear()

    def action_open_models(self) -> None:
        self._open_model_picker()

    def action_open_palette(self) -> None:
        def _on_pick(cmd: str | None) -> None:
            if not cmd:
                return
            inp = self.query_one("#user-input", HistoryInput)
            inp.value = cmd + " "
            inp.cursor_position = len(inp.value)
            inp.focus()

        self.push_screen(CommandPaletteScreen(), _on_pick)

    def action_show_help(self) -> None:
        self._cmd_help()

    def action_restart_agent(self) -> None:
        self._cmd_restart()

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

    def action_copy_chat(self) -> None:
        """Copy full conversation transcript to the system clipboard."""
        transcript = self._build_plain_transcript()
        if self._clipboard_copy(transcript):
            self._append_chat("sys", "Copied full chat transcript to clipboard.")
        else:
            self._append_chat("sys", "Clipboard unavailable — use /export to copy manually.")


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

    def _write_chat_line(
        self, log: RichLog, speaker: str, text: str, *, streaming: bool = False
    ) -> None:
        style, label = self._SPEAKER_STYLE.get(speaker, ("white", speaker.upper()))
        ts = time.strftime("%H:%M:%S")

        # Header row: timestamp + speaker badge
        header = Text(no_wrap=True)
        header.append(ts,     style="bright_black")
        header.append("  ")
        header.append(label,  style=style)
        log.write(header)

        render_markdown = (
            speaker in self._MARKDOWN_SPEAKERS
            and text not in ("…", "(no reply)")
            and not streaming
        )
        if render_markdown:
            # Render body as Markdown, indented 2 spaces to align under the label
            md = Markdown(text, code_theme="monokai", hyperlinks=False)
            log.write(Padding(md, pad=(0, 0, 1, 2)))
        else:
            # Plain text for user input, sys messages, placeholders, and streaming
            body = Text(no_wrap=False)
            body.append("  ")
            body.append(text, style="white" if speaker != "sys" else "bright_black")
            body.append("\n")
            log.write(body)

    def _rebuild_chat(
        self,
        replace_last: tuple[str, str] | None = None,
        *,
        streaming: bool = False,
    ) -> None:
        log = self.query_one("#chat-log", ChatLog)
        log.clear()
        messages = list(self._recent_messages)
        if replace_last and messages:
            messages[-1] = replace_last
            self._recent_messages[-1] = replace_last
        for i, (speaker, text) in enumerate(messages):
            is_streaming = streaming and i == len(messages) - 1
            self._write_chat_line(log, speaker, text, streaming=is_streaming)

    @work(exclusive=False)
    async def _send_message(self, text: str) -> None:
        if self._runner is None:
            return
        self._append_chat("agent", "…")
        accumulated = ""
        chunk_count = 0
        async for chunk in self._runner.stream(text):
            accumulated += chunk
            chunk_count += 1
            # Batch updates: redraw every 5 chunks to reduce flicker
            if chunk_count % 5 == 0:
                self._rebuild_chat(
                    replace_last=("agent", accumulated), streaming=True
                )
        # Final render with full Markdown formatting
        self._rebuild_chat(replace_last=("agent", accumulated or "(no reply)"))


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
    aliases = {
        "http": "streamable_http",
        "https": "streamable_http",
        "streamable-http": "streamable_http",
    }

    default_transport = aliases.get(default_transport.lower(), default_transport)
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
        elif isinstance(spec.get("transport"), str):
            t = str(spec["transport"]).lower()
            spec["transport"] = aliases.get(t, str(spec["transport"]))
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
        self._channel_manager = None

    def start_all(self) -> None:
        self._app.run_worker(self._boot(), exclusive=False, name="agent-boot")

    async def restart(self) -> None:
        await self.stop()
        await self._boot()

    async def _boot(self) -> None:
        from alphaloop.agent import create_agent
        from alphaloop.mcp import read_mcp_connections
        from alphaloop.skills import get_enabled_tools

        self._app.post_message(StatusUpdate("Booting agent…"))
        try:
            graph, _, stack = await create_agent(self._cfg)
        except Exception as exc:
            self._graph = None
            self._agent_stack = None
            self._app.post_message(StatusUpdate(f"Agent boot failed: {exc}", level="error"))
            return
        self._graph       = graph
        self._agent_stack = stack

        # Update status bar MCP count
        mcp_servers = read_mcp_connections(self._cfg)
        status_bar = self._app.query_one("#status-bar", StatusBar)
        status_bar.mcp_count = len(mcp_servers)

        # Approximate exposed MCP tools: total skills + MCP tools loaded into graph.
        # create_agent wires all tools as [mcp_tools + skill_tools].
        skill_count = len(get_enabled_tools())
        try:
            graph_tools = getattr(self._graph, "tools", None)
            total_tool_count = len(graph_tools) if graph_tools is not None else 0
            status_bar.mcp_tools = max(total_tool_count - skill_count, 0)
        except Exception:
            status_bar.mcp_tools = 0

        parts = [f"Ready  provider={self._cfg.provider}", f"model={self._cfg.model}"]
        if self._cfg.sandbox_enabled:
            mode = "docker" if self._cfg.sandbox_use_docker else "local"
            parts.append(f"sandbox={mode}")
        if mcp_servers:
            parts.append(f"mcp=[{', '.join(mcp_servers)}]")
            if status_bar.mcp_tools:
                parts.append(f"mcp_tools={status_bar.mcp_tools}")
        self._app.post_message(StatusUpdate("  ".join(parts), level="ok"))

        self._monitor = _TuiHeartbeatMonitor(graph, self._cfg, self._app)
        self._hb_task = asyncio.create_task(self._monitor.run(), name="hb")

        # Build channel manager (channels only start on explicit /channels start)
        from alphaloop.channels import ChannelManager
        from alphaloop.agent import invoke_agent as _invoke

        async def _channel_handler(channel_name: str, user_id: str, message: str) -> str:
            if self._graph is None:
                return "(agent not ready)"
            return await _invoke(self._graph, message, user_id)

        self._channel_manager = ChannelManager(self._cfg, _channel_handler)
        ch_names = self._channel_manager.channel_names()
        status_bar = self._app.query_one("#status-bar", StatusBar)
        status_bar.channels = 0
        if ch_names:
            self._app.post_message(StatusUpdate(
                f"Channels configured: {', '.join(ch_names)} — use /channels start to activate",
                level="info",
            ))

    async def send(self, message: str) -> str:
        if self._graph is None:
            return "(agent not ready)"
        from alphaloop.agent import invoke_agent
        return await invoke_agent(self._graph, message, self._cfg.thread_id)

    async def stream(self, message: str):  # AsyncIterator[str]
        if self._graph is None:
            yield "(agent not ready)"
            return
        from alphaloop.agent import stream_agent
        async for chunk in stream_agent(self._graph, message, self._cfg.thread_id):
            yield chunk

    async def stop(self) -> None:
        if self._channel_manager is not None:
            await self._channel_manager.stop_all()
            self._channel_manager = None
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
