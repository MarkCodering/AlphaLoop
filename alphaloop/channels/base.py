"""Abstract base class for all AlphaLoop communication channels."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from alphaloop.logger import get_logger

logger = get_logger(__name__)

# A handler that receives (channel_name, user_id, message) and returns a reply.
# The user_id is used as the LangGraph thread_id for per-user memory.
MessageHandler = Callable[[str, str, str], Awaitable[str]]


@dataclass
class ChannelStatus:
    """Runtime state of a single communication channel."""

    name: str
    platform: str
    running: bool = False
    messages_received: int = 0
    messages_sent: int = 0
    last_error: str | None = None


def _split_text(text: str, max_len: int) -> list[str]:
    """Split a long message into chunks no larger than *max_len* characters."""
    if len(text) <= max_len:
        return [text]
    chunks: list[str] = []
    while text:
        chunks.append(text[:max_len])
        text = text[max_len:]
    return chunks


class Channel(ABC):
    """Abstract base for every communication channel integration.

    Subclasses implement ``_run()`` to receive messages from a platform,
    call ``_dispatch()`` to route them through the agent, and deliver the
    reply back to the user.  Lifecycle is managed by ``start()`` / ``stop()``.
    """

    def __init__(
        self,
        name: str,
        platform: str,
        handler: MessageHandler,
    ) -> None:
        self.name = name
        self.platform = platform
        self._handler = handler
        self._task: asyncio.Task | None = None
        self._status = ChannelStatus(name=name, platform=platform)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def status(self) -> ChannelStatus:
        return self._status

    async def start(self) -> None:
        """Start the channel's background task if not already running."""
        if self._task and not self._task.done():
            return
        self._status.running = True
        self._status.last_error = None
        self._task = asyncio.create_task(
            self._safe_run(), name=f"channel-{self.name}"
        )
        logger.info("channel.start name=%s platform=%s", self.name, self.platform)

    async def stop(self) -> None:
        """Stop the channel gracefully."""
        self._status.running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("channel.stop name=%s", self.name)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _safe_run(self) -> None:
        try:
            await self._run()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._status.running = False
            self._status.last_error = str(exc)
            logger.exception("channel.error name=%s: %s", self.name, exc)

    @abstractmethod
    async def _run(self) -> None:
        """Main channel loop.  Must be overridden by every subclass."""

    async def _dispatch(self, user_id: str, message: str) -> str:
        """Route an incoming message through the agent handler.

        Args:
            user_id: Platform-scoped user identifier used as the thread ID
                     so each user has independent, persistent memory.
            message: Raw text received from the user.

        Returns:
            The agent's reply, or a fallback error string.
        """
        self._status.messages_received += 1
        try:
            reply = await self._handler(self.name, user_id, message)
            self._status.messages_sent += 1
            return reply
        except Exception as exc:
            logger.exception("channel.dispatch error: %s", exc)
            return "Sorry, I encountered an error processing your message."
