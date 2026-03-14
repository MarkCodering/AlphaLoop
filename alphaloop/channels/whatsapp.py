"""WhatsApp communication channel for AlphaLoop.

Uses the Meta WhatsApp Business Cloud API (free tier) with a local webhook
server.  Each WhatsApp phone number gets its own LangGraph thread so users
have independent, persistent memory with the agent.

Setup
-----
1. Create a Meta developer app and enable the WhatsApp product.
2. Obtain your Phone Number ID and a temporary/permanent access token.
3. Choose a verify token (any string you control).
4. Expose the webhook publicly — for local dev use ngrok or similar::

       ngrok http 8765

5. Register ``https://<your-ngrok-url>/webhook`` in the Meta developer
   console, using the same verify token.
6. Set the environment variables::

       WHATSAPP_PHONE_NUMBER_ID=<id>
       WHATSAPP_ACCESS_TOKEN=<token>
       WHATSAPP_VERIFY_TOKEN=<your-chosen-secret>
       WHATSAPP_WEBHOOK_PORT=8765   # optional

7. Run: ``alphaloop channels start``

Dependency::

    uv add aiohttp
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from alphaloop.channels.base import Channel, MessageHandler, _split_text
from alphaloop.logger import get_logger

logger = get_logger(__name__)

_META_API_BASE = "https://graph.facebook.com/v19.0"


class WhatsAppChannel(Channel):
    """WhatsApp Business Cloud API channel.

    Runs a lightweight aiohttp HTTP server to receive Meta webhook events
    and replies using the Cloud API.
    """

    def __init__(
        self,
        phone_number_id: str,
        access_token: str,
        verify_token: str,
        handler: MessageHandler,
        host: str = "0.0.0.0",
        port: int = 8765,
        name: str = "whatsapp",
    ) -> None:
        super().__init__(name=name, platform="whatsapp", handler=handler)
        self._phone_number_id = phone_number_id
        self._access_token = access_token
        self._verify_token = verify_token
        self._host = host
        self._port = port

    async def _run(self) -> None:
        try:
            from aiohttp import web
        except ImportError as exc:
            raise ImportError(
                "aiohttp is required for the WhatsApp channel.\n"
                "Install it with:  uv add aiohttp"
            ) from exc

        app = web.Application()
        app.router.add_get("/webhook", self._handle_verify)
        app.router.add_post("/webhook", self._handle_event)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, self._host, self._port)
        await site.start()

        logger.info(
            "whatsapp.channel webhook listening on %s:%d",
            self._host,
            self._port,
        )
        try:
            while self._status.running:
                await asyncio.sleep(0.5)
        finally:
            await runner.cleanup()

    # ------------------------------------------------------------------
    # Webhook handlers
    # ------------------------------------------------------------------

    async def _handle_verify(self, request: Any) -> Any:
        """Respond to Meta's webhook verification challenge."""
        from aiohttp import web

        mode = request.rel_url.query.get("hub.mode")
        token = request.rel_url.query.get("hub.verify_token")
        challenge = request.rel_url.query.get("hub.challenge", "")

        if mode == "subscribe" and token == self._verify_token:
            logger.info("whatsapp.webhook verified successfully")
            return web.Response(text=challenge)
        logger.warning("whatsapp.webhook verification failed — token mismatch")
        return web.Response(status=403, text="Forbidden")

    async def _handle_event(self, request: Any) -> Any:
        """Accept a webhook event and process it asynchronously."""
        from aiohttp import web

        try:
            body = await request.json()
        except Exception:
            return web.Response(status=400, text="Bad Request")

        # Respond immediately — Meta requires a fast 200 OK.
        asyncio.create_task(self._process_event(body))
        return web.Response(status=200, text="OK")

    # ------------------------------------------------------------------
    # Event processing
    # ------------------------------------------------------------------

    async def _process_event(self, body: dict[str, Any]) -> None:
        """Extract text messages from the Meta payload and dispatch them."""
        try:
            for entry in body.get("entry", []):
                for change in entry.get("changes", []):
                    value = change.get("value", {})
                    for msg in value.get("messages", []):
                        await self._handle_message(msg)
        except Exception as exc:
            logger.exception("whatsapp.process_event error: %s", exc)

    async def _handle_message(self, msg: dict[str, Any]) -> None:
        if msg.get("type") != "text":
            return  # images, audio, etc. are not handled yet

        from_number = msg.get("from", "")
        text = msg.get("text", {}).get("body", "").strip()
        if not from_number or not text:
            return

        # Each phone number gets its own persistent agent thread.
        user_id = f"whatsapp-{from_number}"
        logger.info("whatsapp.message user=%s text=%r", user_id, text[:80])

        reply = await self._dispatch(user_id, text)
        if reply:
            await self._send_text(from_number, reply)

    # ------------------------------------------------------------------
    # Outbound messaging
    # ------------------------------------------------------------------

    async def _send_text(self, to: str, text: str) -> None:
        """Send a text message via the Meta Cloud API."""
        url = f"{_META_API_BASE}/{self._phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=30) as client:
            for chunk in _split_text(text, 4096):
                payload = {
                    "messaging_product": "whatsapp",
                    "to": to,
                    "type": "text",
                    "text": {"body": chunk},
                }
                resp = await client.post(url, json=payload, headers=headers)
                if resp.status_code not in (200, 201):
                    logger.error(
                        "whatsapp.send_error to=%s status=%d body=%s",
                        to,
                        resp.status_code,
                        resp.text[:200],
                    )
