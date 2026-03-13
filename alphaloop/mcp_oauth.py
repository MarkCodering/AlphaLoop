"""MCP OAuth 2.0 / PKCE authentication helpers.

Supports the MCP Authorization spec:
  https://spec.modelcontextprotocol.io/specification/basic/authorization/

Flow
----
1. Discover auth endpoints from ``{server_url}/.well-known/oauth-authorization-server``
   (falls back to ``/.well-known/openid-configuration``).
2. Generate a PKCE code_verifier / code_challenge pair.
3. Open the authorization URL in the browser (or print it for manual use).
4. Start a local HTTP server on ``localhost:CALLBACK_PORT`` to receive the code.
5. Exchange the code for tokens at the token endpoint.
6. Persist the token to ``~/.alphaloop/mcp_tokens.json``.

Later connections read the stored token and inject it as a Bearer header.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import secrets
import time
import urllib.parse
import webbrowser
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Awaitable, Callable

import httpx

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CALLBACK_PORT  = 9_999
_CALLBACK_URI   = f"http://localhost:{_CALLBACK_PORT}/callback"
_CLIENT_ID      = "alphaloop"
_DEFAULT_SCOPE  = "openid profile"
_TOKENS_FILE    = Path("~/.alphaloop/mcp_tokens.json")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class OAuthToken:
    access_token:  str
    token_type:    str   = "Bearer"
    refresh_token: str   | None = None
    expires_at:    float | None = None   # unix timestamp

    def is_expired(self, buffer: float = 60.0) -> bool:
        if self.expires_at is None:
            return False
        return time.time() + buffer >= self.expires_at


@dataclass
class OAuthMetadata:
    authorization_endpoint: str
    token_endpoint:         str
    scopes_supported:       list[str]


# ---------------------------------------------------------------------------
# Token storage
# ---------------------------------------------------------------------------


def _tokens_path() -> Path:
    return _TOKENS_FILE.expanduser()


def load_tokens() -> dict[str, OAuthToken]:
    p = _tokens_path()
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text())
        return {k: OAuthToken(**v) for k, v in raw.items()}
    except Exception:
        return {}


def save_tokens(tokens: dict[str, OAuthToken]) -> None:
    p = _tokens_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({k: asdict(v) for k, v in tokens.items()}, indent=2))


def get_token(server_name: str) -> OAuthToken | None:
    return load_tokens().get(server_name)


def delete_token(server_name: str) -> None:
    tokens = load_tokens()
    tokens.pop(server_name, None)
    save_tokens(tokens)


def get_auth_headers(server_name: str) -> dict[str, str]:
    """Return ``{"Authorization": "Bearer …"}`` if a valid token exists, else ``{}``."""
    token = get_token(server_name)
    if token and not token.is_expired():
        return {"Authorization": f"{token.token_type} {token.access_token}"}
    return {}


# ---------------------------------------------------------------------------
# OAuth metadata discovery
# ---------------------------------------------------------------------------


async def discover_oauth_metadata(server_url: str) -> OAuthMetadata | None:
    """Try to fetch OAuth server metadata from well-known endpoints."""
    base = server_url.rstrip("/")
    candidates = [
        f"{base}/.well-known/oauth-authorization-server",
        f"{base}/.well-known/openid-configuration",
    ]
    async with httpx.AsyncClient(timeout=8) as client:
        for url in candidates:
            try:
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    return OAuthMetadata(
                        authorization_endpoint=data["authorization_endpoint"],
                        token_endpoint=data["token_endpoint"],
                        scopes_supported=data.get("scopes_supported", ["openid"]),
                    )
            except Exception:
                continue
    return None


# ---------------------------------------------------------------------------
# PKCE helpers
# ---------------------------------------------------------------------------


def _pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge)."""
    verifier  = secrets.token_urlsafe(64)
    digest    = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


# ---------------------------------------------------------------------------
# Local callback server
# ---------------------------------------------------------------------------


async def _wait_for_callback(port: int, timeout: float = 120.0) -> tuple[str | None, str | None]:
    """Start a temporary HTTP server and wait for the OAuth redirect.

    Returns ``(code, state)`` or ``(None, None)`` on timeout/error.
    """
    code_future: asyncio.Future[tuple[str | None, str | None]] = asyncio.get_event_loop().create_future()

    async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            data = await reader.read(8192)
            first_line = data.decode(errors="replace").split("\r\n")[0]
            path = first_line.split(" ")[1] if " " in first_line else "/"
            qs   = urllib.parse.parse_qs(urllib.parse.urlparse(path).query)
            code  = qs.get("code",  [None])[0]
            state = qs.get("state", [None])[0]
            error = qs.get("error", [None])[0]
            if not code_future.done():
                code_future.set_result((code if not error else None, state))
            body = (
                b"<html><body style='font-family:monospace;background:#050505;color:#a1a1aa'>"
                b"<h2 style='color:#f59e0b'>AlphaLoop &mdash; Authorization complete.</h2>"
                b"<p>You may close this tab.</p></body></html>"
            )
            resp = (
                b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n"
                b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body
            )
            writer.write(resp)
            await writer.drain()
        except Exception:
            pass
        finally:
            writer.close()

    server = await asyncio.start_server(_handle, "localhost", port)
    try:
        async with server:
            return await asyncio.wait_for(code_future, timeout=timeout)
    except asyncio.TimeoutError:
        return None, None


# ---------------------------------------------------------------------------
# Token exchange
# ---------------------------------------------------------------------------


async def _exchange_code(
    token_endpoint: str,
    code: str,
    code_verifier: str,
) -> OAuthToken | None:
    payload = {
        "grant_type":    "authorization_code",
        "code":          code,
        "redirect_uri":  _CALLBACK_URI,
        "client_id":     _CLIENT_ID,
        "code_verifier": code_verifier,
    }
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(token_endpoint, data=payload)
        resp.raise_for_status()
        data = resp.json()
    expires_in = data.get("expires_in")
    return OAuthToken(
        access_token  = data["access_token"],
        token_type    = data.get("token_type", "Bearer"),
        refresh_token = data.get("refresh_token"),
        expires_at    = time.time() + expires_in if expires_in else None,
    )


async def _refresh_token(token_endpoint: str, refresh_token: str) -> OAuthToken | None:
    payload = {
        "grant_type":    "refresh_token",
        "refresh_token": refresh_token,
        "client_id":     _CLIENT_ID,
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(token_endpoint, data=payload)
            resp.raise_for_status()
            data = resp.json()
        expires_in = data.get("expires_in")
        return OAuthToken(
            access_token  = data["access_token"],
            token_type    = data.get("token_type", "Bearer"),
            refresh_token = data.get("refresh_token", refresh_token),
            expires_at    = time.time() + expires_in if expires_in else None,
        )
    except Exception:
        return None


# ---------------------------------------------------------------------------
# High-level: ensure a valid token (refresh or full re-auth)
# ---------------------------------------------------------------------------


async def ensure_token(
    server_name: str,
    server_url:  str,
    on_progress: Callable[[str], Awaitable[None]] | None = None,
) -> OAuthToken | None:
    """Return a valid token, refreshing or re-authing as needed."""

    async def _info(msg: str) -> None:
        if on_progress:
            await on_progress(msg)

    # Check stored token
    existing = get_token(server_name)
    if existing and not existing.is_expired():
        return existing

    # Try refresh
    if existing and existing.refresh_token:
        await _info("Refreshing OAuth token…")
        meta = await discover_oauth_metadata(server_url)
        if meta:
            refreshed = await _refresh_token(meta.token_endpoint, existing.refresh_token)
            if refreshed:
                tokens = load_tokens()
                tokens[server_name] = refreshed
                save_tokens(tokens)
                await _info("Token refreshed.")
                return refreshed

    # Full authorization flow
    return await run_oauth_flow(server_name, server_url, on_progress)


# ---------------------------------------------------------------------------
# Full PKCE authorization flow
# ---------------------------------------------------------------------------


async def run_oauth_flow(
    server_name: str,
    server_url:  str,
    on_progress: Callable[[str], Awaitable[None]] | None = None,
) -> OAuthToken | None:
    """Run a full PKCE OAuth 2.0 authorization flow.

    Discovers the server's auth endpoints, opens the browser, waits for the
    local callback, and exchanges the code for a token.

    Returns the stored :class:`OAuthToken`, or ``None`` on failure.
    """

    async def _info(msg: str) -> None:
        if on_progress:
            await on_progress(msg)

    await _info(f"Discovering OAuth endpoints for {server_url}…")
    meta = await discover_oauth_metadata(server_url)
    if not meta:
        await _info(
            "No OAuth metadata found at this server.\n"
            "The server may not support OAuth or may use a different auth method."
        )
        return None

    code_verifier, code_challenge = _pkce_pair()
    state = secrets.token_urlsafe(16)

    scope = " ".join(meta.scopes_supported[:4]) if meta.scopes_supported else _DEFAULT_SCOPE

    params = urllib.parse.urlencode({
        "response_type":         "code",
        "client_id":             _CLIENT_ID,
        "redirect_uri":          _CALLBACK_URI,
        "scope":                 scope,
        "state":                 state,
        "code_challenge":        code_challenge,
        "code_challenge_method": "S256",
    })
    auth_url = f"{meta.authorization_endpoint}?{params}"

    await _info(f"Opening browser for authorization…\n\n{auth_url}\n\nWaiting for callback (2 min timeout)…")

    try:
        webbrowser.open(auth_url)
    except Exception:
        pass  # headless — user copies the URL

    code, returned_state = await _wait_for_callback(_CALLBACK_PORT, timeout=120.0)

    if not code:
        await _info("Authorization timed out or was denied.")
        return None

    if returned_state and returned_state != state:
        await _info("OAuth state mismatch — possible CSRF. Aborting.")
        return None

    await _info("Exchanging authorization code for token…")
    try:
        token = await _exchange_code(meta.token_endpoint, code, code_verifier)
    except Exception as exc:
        await _info(f"Token exchange failed: {exc}")
        return None

    tokens = load_tokens()
    tokens[server_name] = token
    save_tokens(tokens)

    await _info(f"OAuth complete. Token stored for '{server_name}'.")
    return token
