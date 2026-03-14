"""Channel manager — creates and supervises all enabled communication channels."""

from __future__ import annotations

from typing import TYPE_CHECKING

from alphaloop.channels.base import Channel, ChannelStatus, MessageHandler
from alphaloop.logger import get_logger, log_event

if TYPE_CHECKING:
    from alphaloop.config import Config

logger = get_logger(__name__)


class ChannelManager:
    """Creates, starts, and stops all configured communication channels.

    Channels are built from the runtime ``Config`` object.  Only channels
    whose required credentials are present in the config are registered.

    Each incoming message is routed to ``handler(channel_name, user_id, text)``
    which is expected to call the agent and return a reply string.
    """

    def __init__(self, config: "Config", handler: MessageHandler) -> None:
        self._config = config
        self._handler = handler
        self._channels: dict[str, Channel] = {}
        self._build_channels()

    # ------------------------------------------------------------------
    # Channel registry
    # ------------------------------------------------------------------

    def _build_channels(self) -> None:
        cfg = self._config

        if cfg.telegram_bot_token:
            from alphaloop.channels.telegram import TelegramChannel

            self._channels["telegram"] = TelegramChannel(
                token=cfg.telegram_bot_token,
                handler=self._handler,
                allowed_users=cfg.telegram_allowed_users or None,
            )
            log_event(logger, "channel.register", name="telegram")

        if (
            cfg.whatsapp_phone_id
            and cfg.whatsapp_access_token
            and cfg.whatsapp_verify_token
        ):
            from alphaloop.channels.whatsapp import WhatsAppChannel

            self._channels["whatsapp"] = WhatsAppChannel(
                phone_number_id=cfg.whatsapp_phone_id,
                access_token=cfg.whatsapp_access_token,
                verify_token=cfg.whatsapp_verify_token,
                handler=self._handler,
                host=cfg.whatsapp_webhook_host,
                port=cfg.whatsapp_webhook_port,
            )
            log_event(
                logger,
                "channel.register",
                name="whatsapp",
                port=cfg.whatsapp_webhook_port,
            )

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def channel_names(self) -> list[str]:
        """Return names of all registered channels."""
        return list(self._channels.keys())

    def statuses(self) -> list[ChannelStatus]:
        """Return runtime status of all registered channels."""
        return [ch.status for ch in self._channels.values()]

    def get_channel(self, name: str) -> Channel | None:
        return self._channels.get(name)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start_all(self) -> None:
        """Start every registered channel concurrently."""
        for ch in self._channels.values():
            await ch.start()
        log_event(logger, "channels.started", count=len(self._channels))

    async def stop_all(self) -> None:
        """Stop every running channel gracefully."""
        for ch in self._channels.values():
            await ch.stop()
        log_event(logger, "channels.stopped")

    async def start_channel(self, name: str) -> bool:
        """Start a single channel by name.  Returns False if not found."""
        ch = self._channels.get(name)
        if ch is None:
            return False
        await ch.start()
        return True

    async def stop_channel(self, name: str) -> bool:
        """Stop a single channel by name.  Returns False if not found."""
        ch = self._channels.get(name)
        if ch is None:
            return False
        await ch.stop()
        return True
