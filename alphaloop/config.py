"""Runtime configuration for AlphaLoop."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    """Central config read from environment variables with sane defaults."""

    # Ollama model to use
    model: str = field(default_factory=lambda: os.getenv("ALPHALOOP_MODEL", "lfm2.5-thinking:1.2b"))

    # Ollama base URL
    ollama_base_url: str = field(
        default_factory=lambda: os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    )

    # Heartbeat interval in seconds
    heartbeat_interval: float = field(
        default_factory=lambda: float(os.getenv("ALPHALOOP_HEARTBEAT_INTERVAL", "30"))
    )

    # How long to wait for a heartbeat response before declaring the agent unhealthy
    heartbeat_timeout: float = field(
        default_factory=lambda: float(os.getenv("ALPHALOOP_HEARTBEAT_TIMEOUT", "60"))
    )

    # Maximum consecutive heartbeat failures before restarting
    max_heartbeat_failures: int = field(
        default_factory=lambda: int(os.getenv("ALPHALOOP_MAX_HEARTBEAT_FAILURES", "3"))
    )

    # SQLite checkpoint database path
    checkpoint_db: Path = field(
        default_factory=lambda: Path(
            os.getenv("ALPHALOOP_CHECKPOINT_DB", "~/.alphaloop/checkpoints.db")
        ).expanduser()
    )

    # Thread/conversation ID for persistence (same thread = memory across restarts)
    thread_id: str = field(
        default_factory=lambda: os.getenv("ALPHALOOP_THREAD_ID", "alphaloop-main")
    )

    # System prompt prefix injected before the deep agent's base prompt
    system_prompt: str = field(
        default_factory=lambda: os.getenv(
            "ALPHALOOP_SYSTEM_PROMPT",
            "You are AlphaLoop, a persistent AI agent running 24/7. "
            "On each heartbeat, reflect on your current goals, review recent progress, "
            "and decide what to do next. Be proactive and self-directed.",
        )
    )

    # Log level
    log_level: str = field(default_factory=lambda: os.getenv("ALPHALOOP_LOG_LEVEL", "INFO"))

    # Working directory for the agent's filesystem backend
    work_dir: Path = field(
        default_factory=lambda: Path(
            os.getenv("ALPHALOOP_WORK_DIR", "~/.alphaloop/workspace")
        ).expanduser()
    )

    # Sandbox configuration
    sandbox_enabled: bool = field(
        default_factory=lambda: os.getenv("ALPHALOOP_SANDBOX", "0") == "1"
    )
    sandbox_use_docker: bool = field(
        default_factory=lambda: os.getenv("ALPHALOOP_SANDBOX_DOCKER", "0") == "1"
    )
    sandbox_docker_image: str = field(
        default_factory=lambda: os.getenv("ALPHALOOP_SANDBOX_IMAGE", "python:3.12-slim")
    )
    sandbox_timeout: int = field(
        default_factory=lambda: int(os.getenv("ALPHALOOP_SANDBOX_TIMEOUT", "30"))
    )

    def __post_init__(self) -> None:
        self.checkpoint_db.parent.mkdir(parents=True, exist_ok=True)
        self.work_dir.mkdir(parents=True, exist_ok=True)


# Module-level singleton
_config: Config | None = None


def get_config() -> Config:
    """Return the singleton config instance."""
    global _config  # noqa: PLW0603
    if _config is None:
        _config = Config()
    return _config
