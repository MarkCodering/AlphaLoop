"""Structured logging for AlphaLoop using Rich."""

from __future__ import annotations

import logging
from typing import Any

from rich.console import Console
from rich.logging import RichHandler

_console = Console(stderr=True)
_configured = False


def setup_logging(level: str = "INFO") -> None:
    """Configure Rich-based logging once."""
    global _configured  # noqa: PLW0603
    if _configured:
        return
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=_console, rich_tracebacks=True, markup=True)],
    )
    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Return a named logger."""
    return logging.getLogger(name)


def log_event(logger: logging.Logger, event: str, **kwargs: Any) -> None:
    """Log a structured event with key=value pairs."""
    details = " ".join(f"{k}={v!r}" for k, v in kwargs.items())
    logger.info("[bold]%s[/bold] %s", event, details, extra={"markup": True})
