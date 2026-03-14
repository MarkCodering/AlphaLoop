"""Runtime configuration for AlphaLoop."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _default_mcp_config() -> Path | None:
    env = os.getenv("ALPHALOOP_MCP_CONFIG")
    if env:
        return Path(env).expanduser()
    default = Path("~/.alphaloop/mcp.json").expanduser()
    return default if default.exists() else None


@dataclass
class Config:
    """Central config read from environment variables with sane defaults."""

    # Model provider to use: ollama | openai | anthropic | gemini | ollama_cloud
    provider: str = field(default_factory=lambda: os.getenv("ALPHALOOP_PROVIDER", "ollama"))

    # Model to use (provider-specific model identifier)
    model: str = field(default_factory=lambda: os.getenv("ALPHALOOP_MODEL", "lfm2.5-thinking:1.2b"))

    # Local Ollama base URL
    ollama_base_url: str = field(
        default_factory=lambda: os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    )

    # OpenAI configuration
    openai_api_key: str | None = field(default_factory=lambda: os.getenv("OPENAI_API_KEY"))
    openai_base_url: str | None = field(default_factory=lambda: os.getenv("OPENAI_BASE_URL"))

    # Anthropic configuration
    anthropic_api_key: str | None = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY"))

    # Gemini configuration (Google AI Studio)
    gemini_api_key: str | None = field(
        default_factory=lambda: os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    )

    # Ollama Cloud configuration (OpenAI-compatible endpoint)
    ollama_api_key: str | None = field(default_factory=lambda: os.getenv("OLLAMA_API_KEY"))
    ollama_cloud_base_url: str = field(
        default_factory=lambda: os.getenv("OLLAMA_CLOUD_BASE_URL", "https://ollama.com")
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

    # MCP servers config file (JSON mapping of server-name → connection spec).
    # Defaults to ~/.alphaloop/mcp.json if it exists; override with ALPHALOOP_MCP_CONFIG.
    mcp_config: Path | None = field(
        default_factory=lambda: _default_mcp_config()
    )

    # --- Telegram channel ---
    # Bot token from @BotFather.  Leave unset to disable the Telegram channel.
    telegram_bot_token: str | None = field(
        default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN")
    )
    # Comma-separated list of numeric chat IDs allowed to use the bot.
    # Empty means all users are allowed.
    telegram_allowed_users: list[int] = field(
        default_factory=lambda: [
            int(x)
            for x in os.getenv("TELEGRAM_ALLOWED_USERS", "").split(",")
            if x.strip()
        ]
    )

    # --- WhatsApp channel (Meta Cloud API) ---
    # Phone Number ID from the Meta developer console.
    whatsapp_phone_id: str | None = field(
        default_factory=lambda: os.getenv("WHATSAPP_PHONE_NUMBER_ID")
    )
    # Bearer access token for the Meta Graph API.
    whatsapp_access_token: str | None = field(
        default_factory=lambda: os.getenv("WHATSAPP_ACCESS_TOKEN")
    )
    # Verification token you chose when registering the webhook in Meta's console.
    whatsapp_verify_token: str | None = field(
        default_factory=lambda: os.getenv("WHATSAPP_VERIFY_TOKEN")
    )
    # Local address and port for the incoming webhook server.
    whatsapp_webhook_host: str = field(
        default_factory=lambda: os.getenv("WHATSAPP_WEBHOOK_HOST", "0.0.0.0")
    )
    whatsapp_webhook_port: int = field(
        default_factory=lambda: int(os.getenv("WHATSAPP_WEBHOOK_PORT", "8765"))
    )

    def __post_init__(self) -> None:
        aliases = {
            "google": "gemini",
            "google-genai": "gemini",
            "ollama-cloud": "ollama_cloud",
        }
        self.provider = aliases.get(self.provider.lower(), self.provider.lower())

        allowed = {"ollama", "openai", "anthropic", "gemini", "ollama_cloud"}
        if self.provider not in allowed:
            raise ValueError(
                f"Unsupported ALPHALOOP_PROVIDER '{self.provider}'. "
                "Use one of: ollama, openai, anthropic, gemini, ollama_cloud."
            )

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
