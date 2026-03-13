from __future__ import annotations

import httpx

from alphaloop.mcp_oauth import (
    _default_oauth_metadata,
    _format_http_error,
    _oauth_metadata_candidates,
)


def test_oauth_metadata_candidates_include_origin_and_mcp_path() -> None:
    candidates = _oauth_metadata_candidates("https://mcp.notion.com/mcp")

    assert candidates[0] == "https://mcp.notion.com/.well-known/oauth-authorization-server"
    assert "https://mcp.notion.com/.well-known/openid-configuration" in candidates
    assert "https://mcp.notion.com/mcp/.well-known/oauth-authorization-server" in candidates


def test_oauth_metadata_candidates_walk_nested_paths_once() -> None:
    candidates = _oauth_metadata_candidates("https://example.com/a/b/mcp/")

    assert "https://example.com/.well-known/oauth-authorization-server" in candidates
    assert "https://example.com/a/.well-known/oauth-authorization-server" in candidates
    assert "https://example.com/a/b/.well-known/oauth-authorization-server" in candidates
    assert "https://example.com/a/b/mcp/.well-known/oauth-authorization-server" in candidates
    assert len(candidates) == len(set(candidates))


def test_default_oauth_metadata_uses_server_origin() -> None:
    meta = _default_oauth_metadata("https://api.githubcopilot.com/mcp/")

    assert meta is not None
    assert meta.authorization_endpoint == "https://api.githubcopilot.com/authorize"
    assert meta.token_endpoint == "https://api.githubcopilot.com/token"
    assert meta.registration_endpoint == "https://api.githubcopilot.com/register"


def test_format_http_error_includes_response_body() -> None:
    request = httpx.Request("POST", "https://example.com/token")
    response = httpx.Response(400, request=request, text='{"error":"invalid_client"}')
    exc = httpx.HTTPStatusError("bad request", request=request, response=response)

    message = _format_http_error(exc)

    assert "invalid_client" in message
