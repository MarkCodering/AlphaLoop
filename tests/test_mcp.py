from __future__ import annotations

import sys
from contextlib import AsyncExitStack
from pathlib import Path
from types import ModuleType

import pytest

from alphaloop.config import Config
from alphaloop.mcp import load_mcp_tools, normalize_mcp_connection


class _DummyTool:
    def __init__(self, name: str) -> None:
        self.name = name


@pytest.mark.asyncio
async def test_load_mcp_tools_partial_failure_keeps_working_servers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[dict[str, object]] = []

    class FakeClient:
        def __init__(self, spec):
            self.spec = spec
            calls.append(spec)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get_tools(self):
            name = next(iter(self.spec.keys()))
            if name == "broken":
                raise RuntimeError("boom")
            return [_DummyTool(f"tool-{name}")]

    fake_client_mod = ModuleType("langchain_mcp_adapters.client")
    fake_client_mod.MultiServerMCPClient = FakeClient
    monkeypatch.setitem(sys.modules, "langchain_mcp_adapters.client", fake_client_mod)

    monkeypatch.setattr("alphaloop.mcp_oauth.get_auth_headers", lambda name: {})

    cfg = Config(
        mcp_config=tmp_path / "mcp.json",
        checkpoint_db=tmp_path / "checkpoints.db",
        work_dir=tmp_path / "workspace",
    )
    cfg.mcp_config.write_text(
        '{"ok":{"transport":"streamable_http","url":"https://ok/mcp"},'
        '"broken":{"transport":"streamable_http","url":"https://bad/mcp"}}'
    )

    async with AsyncExitStack() as stack:
        tools = await load_mcp_tools(cfg, stack)

    assert [t.name for t in tools] == ["tool-ok"]
    assert len(calls) == 2


def test_normalize_mcp_connection_maps_http_alias_to_streamable_http() -> None:
    spec = normalize_mcp_connection({"transport": "http", "url": "https://example.com/mcp"})

    assert spec["transport"] == "streamable_http"
