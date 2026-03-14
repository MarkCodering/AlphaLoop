"""Communication channels for AlphaLoop — Telegram, WhatsApp, and more.

Each channel bridges an external messaging platform to the AlphaLoop agent.
Every user on a platform gets their own persistent LangGraph thread, so
conversations are remembered across sessions.

Available channels
------------------
- **Telegram** — polling bot via python-telegram-bot (no public URL needed).
- **WhatsApp** — Meta Cloud API webhook (requires a publicly reachable URL).

Extending
---------
Subclass :class:`~alphaloop.channels.base.Channel`, implement ``_run()``,
and register your channel in :class:`~alphaloop.channels.manager.ChannelManager`.
"""

from alphaloop.channels.base import Channel, ChannelStatus, MessageHandler
from alphaloop.channels.manager import ChannelManager

__all__ = ["Channel", "ChannelStatus", "MessageHandler", "ChannelManager"]
