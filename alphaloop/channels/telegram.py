"""Telegram communication channel for AlphaLoop.

Uses python-telegram-bot (v21+) in async polling mode — no public URL required.
Each Telegram chat gets its own LangGraph thread so users have independent,
persistent memory with the agent.

Setup
-----
1. Create a bot via @BotFather and obtain the token.
2. Set ``TELEGRAM_BOT_TOKEN`` in your environment.
3. Optionally restrict access: ``TELEGRAM_ALLOWED_USERS=123456,789012``
4. Run: ``alphaloop channels start``

Install the extra dependency::

    uv add 'python-telegram-bot>=21.0'
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from alphaloop.channels.base import Channel, MessageHandler, _split_text
from alphaloop.logger import get_logger

if TYPE_CHECKING:
    from telegram import Update
    from telegram.ext import ContextTypes

logger = get_logger(__name__)


class TelegramChannel(Channel):
    """Telegram bot that polls the Bot API and routes messages to the agent."""

    def __init__(
        self,
        token: str,
        handler: MessageHandler,
        allowed_users: list[int] | None = None,
        name: str = "telegram",
    ) -> None:
        super().__init__(name=name, platform="telegram", handler=handler)
        self._token = token
        self._allowed_users: frozenset[int] | None = (
            frozenset(allowed_users) if allowed_users else None
        )

    async def _run(self) -> None:
        try:
            from telegram.ext import (
                Application,
                CommandHandler,
                MessageHandler as TGMessageHandler,
                filters,
            )
        except ImportError as exc:
            raise ImportError(
                "python-telegram-bot is required for the Telegram channel.\n"
                "Install it with:  uv add 'python-telegram-bot>=21.0'"
            ) from exc

        app = (
            Application.builder()
            .token(self._token)
            .build()
        )

        app.add_handler(CommandHandler("start", self._on_start_command))
        app.add_handler(
            TGMessageHandler(filters.TEXT & ~filters.COMMAND, self._on_message)
        )

        logger.info("telegram.channel polling started")
        async with app:
            await app.updater.start_polling(drop_pending_updates=True)
            await app.start()
            try:
                while self._status.running:
                    await asyncio.sleep(0.5)
            finally:
                await app.updater.stop()
                await app.stop()

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    async def _on_start_command(
        self,
        update: "Update",
        context: "ContextTypes.DEFAULT_TYPE",
    ) -> None:
        if update.message is None:
            return
        if not self._is_allowed(update.effective_chat.id):
            await update.message.reply_text("You are not authorised to use this bot.")
            return
        await update.message.reply_text(
            "Hello! I'm your AlphaLoop AI agent.\n"
            "Send me any message and I'll reply. "
            "I remember our conversation, so you can pick up where we left off."
        )

    async def _on_message(
        self,
        update: "Update",
        context: "ContextTypes.DEFAULT_TYPE",
    ) -> None:
        if update.message is None or update.effective_chat is None:
            return

        chat_id = update.effective_chat.id
        if not self._is_allowed(chat_id):
            await update.message.reply_text("Unauthorized.")
            return

        text = (update.message.text or "").strip()
        if not text:
            return

        # Each chat gets its own persistent thread with the agent.
        user_id = f"telegram-{chat_id}"
        logger.info("telegram.message user=%s text=%r", user_id, text[:80])

        # Show typing indicator while the agent thinks.
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")

        reply = await self._dispatch(user_id, text)
        if reply:
            for chunk in _split_text(reply, 4096):
                await update.message.reply_text(chunk)

    def _is_allowed(self, chat_id: int) -> bool:
        return self._allowed_users is None or chat_id in self._allowed_users
