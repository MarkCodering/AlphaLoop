from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from alphaloop.agent import create_agent
from alphaloop.config import Config


@pytest.mark.asyncio
async def test_create_agent_uses_live_sqlite_saver(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}
    graph_sentinel = object()

    fake_deepagents = ModuleType("deepagents")

    def fake_create_deep_agent(*, model, system_prompt, checkpointer, backend):
        captured["model"] = model
        captured["system_prompt"] = system_prompt
        captured["checkpointer"] = checkpointer
        captured["backend"] = backend
        return graph_sentinel

    fake_deepagents.create_deep_agent = fake_create_deep_agent
    monkeypatch.setitem(sys.modules, "deepagents", fake_deepagents)
    monkeypatch.setattr("alphaloop.agent._build_ollama_model", lambda config: object())

    cfg = Config(
        checkpoint_db=tmp_path / "checkpoints.db",
        sandbox_enabled=False,
        work_dir=tmp_path / "workspace",
    )

    graph, checkpointer, stack = await create_agent(cfg)
    try:
        assert graph is graph_sentinel
        assert isinstance(checkpointer, AsyncSqliteSaver)
        assert captured["checkpointer"] is checkpointer
        assert captured["backend"] is None
    finally:
        await stack.aclose()
