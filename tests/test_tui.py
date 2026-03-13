from __future__ import annotations

import json

import pytest

from alphaloop.config import Config
from alphaloop.mcp import read_mcp_connections, read_mcp_document
from alphaloop.tui import AlphaLoopApp, CommandPreview, HistoryInput, _BackgroundRunner


@pytest.fixture
def stub_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_BackgroundRunner, "start_all", lambda self: None)

    async def _stop(self) -> None:
        return None

    monkeypatch.setattr(_BackgroundRunner, "stop", _stop)


@pytest.mark.asyncio
async def test_history_input_up_down_navigates_message_history(stub_runner: None) -> None:
    app = AlphaLoopApp()

    async with app.run_test() as pilot:
        inp = app.query_one("#user-input", HistoryInput)
        inp.push_history("first")
        inp.push_history("second")

        await pilot.press("up")
        await pilot.pause()
        assert inp.value == "second"

        await pilot.press("up")
        await pilot.pause()
        assert inp.value == "first"

        await pilot.press("down")
        await pilot.pause()
        assert inp.value == "second"


@pytest.mark.asyncio
async def test_history_input_up_down_navigates_command_preview_when_open(stub_runner: None) -> None:
    app = AlphaLoopApp()

    async with app.run_test() as pilot:
        inp = app.query_one("#user-input", HistoryInput)
        preview = app.query_one("#cmd-preview", CommandPreview)

        inp.value = "/m"
        preview.filter(inp.value)
        preview.display = True

        assert preview.selected_command() == "/models"

        await pilot.press("down")
        await pilot.pause()
        assert preview.selected_command() == "/mcp list"

        await pilot.press("up")
        await pilot.pause()
        assert preview.selected_command() == "/models"


def test_read_mcp_connections_supports_wrapped_documents(tmp_path) -> None:
    path = tmp_path / "mcp.json"
    path.write_text(json.dumps({
        "servers": {
            "github": {
                "type": "http",
                "url": "https://api.githubcopilot.com/mcp/",
                "headers": {
                    "Authorization": "Bearer ${input:github_mcp_pat}",
                },
            },
        },
        "inputs": [
            {
                "type": "promptString",
                "id": "github_mcp_pat",
                "description": "GitHub Personal Access Token",
                "password": True,
            },
        ],
    }))
    cfg = Config(mcp_config=path)

    connections, wrapper_key, extras = read_mcp_document(cfg)

    assert wrapper_key == "servers"
    assert list(connections) == ["github"]
    assert extras["inputs"][0]["id"] == "github_mcp_pat"
    assert read_mcp_connections(cfg)["github"]["url"] == "https://api.githubcopilot.com/mcp/"


@pytest.mark.asyncio
async def test_mcp_add_accepts_quoted_json_spec_and_preserves_wrapper(
    stub_runner: None,
    tmp_path,
) -> None:
    path = tmp_path / "mcp.json"
    path.write_text(json.dumps({
        "mcpServers": {
            "existing": {
                "url": "https://mcp.notion.com/mcp",
            },
        },
    }))
    app = AlphaLoopApp(config=Config(mcp_config=path))

    async with app.run_test():
        app.post_message = lambda message: None
        app._handle_slash_command(
            '/mcp add github \'{"url":"https://api.githubcopilot.com/mcp/","headers":{"Authorization":"Bearer ${input:github_mcp_pat}"}}\''
        )

    saved = json.loads(path.read_text())

    assert "mcpServers" in saved
    assert saved["mcpServers"]["existing"]["url"] == "https://mcp.notion.com/mcp"
    assert saved["mcpServers"]["github"]["transport"] == "http"
    assert saved["mcpServers"]["github"]["headers"]["Authorization"] == "Bearer ${input:github_mcp_pat}"


@pytest.mark.asyncio
async def test_set_provider_and_key_commands_update_config(stub_runner: None) -> None:
    cfg = Config(provider="ollama", model="lfm2.5-thinking:1.2b")
    app = AlphaLoopApp(config=cfg)

    async with app.run_test():
        app.post_message = lambda message: None
        app._handle_slash_command("/set provider openai")
        app._handle_slash_command("/set key sk-test-key")

    assert cfg.provider == "openai"
    assert cfg.openai_api_key == "sk-test-key"


def test_unknown_command_suggests_closest(stub_runner: None) -> None:
    app = AlphaLoopApp(config=Config())

    suggestion = app._suggest_unknown_command("/modles")

    assert "maybe /models" in suggestion


def test_command_registry_includes_palette_and_provider_commands() -> None:
    from alphaloop.tui import _COMMANDS

    names = {name for name, _ in _COMMANDS}

    assert "/palette" in names
    assert "/provider" in names
    assert "/providers" in names


def test_copy_chat_command_calls_copy_chat(stub_runner: None, monkeypatch: pytest.MonkeyPatch) -> None:
    app = AlphaLoopApp(config=Config())
    called = {"value": False}

    def _copy_chat() -> None:
        called["value"] = True

    monkeypatch.setattr(app, "action_copy_chat", _copy_chat)

    app._handle_slash_command("/copy chat")

    assert called["value"] is True


def test_paste_command_calls_paste_to_input(stub_runner: None, monkeypatch: pytest.MonkeyPatch) -> None:
    app = AlphaLoopApp(config=Config())
    called = {"value": False}

    def _paste() -> None:
        called["value"] = True

    monkeypatch.setattr(app, "action_paste_to_input", _paste)

    app._handle_slash_command("/paste")

    assert called["value"] is True
