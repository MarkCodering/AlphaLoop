"""Agent skill registry — toggleable tool bundles the agent can use.

Skills are pre-built tool groups that can be enabled/disabled at runtime
via the TUI ``/skills`` command.  Enabled skill names are persisted in
``~/.alphaloop/skills.json``.

Built-in skills
---------------
web_search    DuckDuckGo text search (no API key needed)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

_SKILLS_FILE = Path("~/.alphaloop/skills.json")


# ---------------------------------------------------------------------------
# Skill descriptor
# ---------------------------------------------------------------------------


@dataclass
class SkillInfo:
    name:        str
    description: str
    tags:        list[str]


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

REGISTRY: dict[str, SkillInfo] = {
    "web_search": SkillInfo(
        name        = "web_search",
        description = "DuckDuckGo web search — search the internet for up-to-date information",
        tags        = ["search", "internet", "research"],
    ),
}


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def _skills_path() -> Path:
    return _SKILLS_FILE.expanduser()


def load_enabled() -> set[str]:
    p = _skills_path()
    if not p.exists():
        return set()
    try:
        data = json.loads(p.read_text())
        return set(data.get("enabled", []))
    except Exception:
        return set()


def save_enabled(enabled: set[str]) -> None:
    p = _skills_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"enabled": sorted(enabled)}, indent=2))


def enable_skill(name: str) -> bool:
    """Enable a skill by name. Returns False if unknown."""
    if name not in REGISTRY:
        return False
    enabled = load_enabled()
    enabled.add(name)
    save_enabled(enabled)
    return True


def disable_skill(name: str) -> bool:
    """Disable a skill. Returns False if it wasn't enabled."""
    enabled = load_enabled()
    if name not in enabled:
        return False
    enabled.discard(name)
    save_enabled(enabled)
    return True


# ---------------------------------------------------------------------------
# Tool builders
# ---------------------------------------------------------------------------


def _build_web_search_tools() -> list[BaseTool]:
    from langchain_core.tools import tool

    @tool
    def web_search(query: str, max_results: int = 5) -> str:
        """Search the web using DuckDuckGo and return a summary of results.

        Args:
            query: The search query.
            max_results: Maximum number of results to return (1-10).
        """
        try:
            from duckduckgo_search import DDGS
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=max_results))
            if not results:
                return "No results found."
            lines = []
            for r in results:
                lines.append(f"**{r.get('title', '')}**")
                lines.append(r.get("href", ""))
                lines.append(r.get("body", ""))
                lines.append("")
            return "\n".join(lines)
        except Exception as exc:
            return f"Search failed: {exc}"

    @tool
    def web_news(query: str, max_results: int = 5) -> str:
        """Search for recent news using DuckDuckGo.

        Args:
            query: News search query.
            max_results: Maximum number of results (1-10).
        """
        try:
            from duckduckgo_search import DDGS
            with DDGS() as ddgs:
                results = list(ddgs.news(query, max_results=max_results))
            if not results:
                return "No news found."
            lines = []
            for r in results:
                date = r.get("date", "")
                lines.append(f"**{r.get('title', '')}** ({date})")
                lines.append(r.get("url", ""))
                lines.append(r.get("body", ""))
                lines.append("")
            return "\n".join(lines)
        except Exception as exc:
            return f"News search failed: {exc}"

    return [web_search, web_news]


_TOOL_BUILDERS: dict[str, callable] = {
    "web_search": _build_web_search_tools,
}


# ---------------------------------------------------------------------------
# Load enabled tools
# ---------------------------------------------------------------------------


def get_enabled_tools() -> list[BaseTool]:
    """Return tool instances for all currently-enabled skills."""
    enabled = load_enabled()
    tools: list[BaseTool] = []
    for name in enabled:
        builder = _TOOL_BUILDERS.get(name)
        if builder:
            try:
                tools.extend(builder())
            except Exception:
                pass
    return tools
