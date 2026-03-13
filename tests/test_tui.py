from __future__ import annotations

import pytest

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
