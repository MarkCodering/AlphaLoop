"""AlphaLoop CLI entry point.

Commands
--------
start   Run the 24/7 agent (blocks until Ctrl-C).
send    Inject a one-off message and print the reply.
status  Print current config and heartbeat stats.
"""

from __future__ import annotations

import asyncio

import click
from rich.console import Console
from rich.table import Table

console = Console()


@click.group()
def cli() -> None:
    """AlphaLoop — a 24/7 deep agent with heartbeat and pluggable model providers."""


@cli.command()
@click.option(
    "--provider",
    default=None,
    type=click.Choice(["ollama", "openai", "anthropic", "gemini", "ollama_cloud"], case_sensitive=False),
    help="Model provider override",
)
@click.option("--model", default=None, help="Model override (provider-specific)")
@click.option("--interval", default=None, type=float, help="Heartbeat interval in seconds")
@click.option("--thread", default=None, help="Conversation thread ID")
@click.option("--sandbox", is_flag=True, default=False, help="Enable Docker sandbox for shell execution")
def start(provider: str | None, model: str | None, interval: float | None, thread: str | None, sandbox: bool) -> None:  # noqa: FBT001
    """Start the agent and keep it running 24/7."""
    import os

    if provider:
        os.environ["ALPHALOOP_PROVIDER"] = provider.lower()
    if model:
        os.environ["ALPHALOOP_MODEL"] = model
    if interval:
        os.environ["ALPHALOOP_HEARTBEAT_INTERVAL"] = str(interval)
    if thread:
        os.environ["ALPHALOOP_THREAD_ID"] = thread
    if sandbox:
        os.environ["ALPHALOOP_SANDBOX"] = "1"

    from alphaloop.config import Config
    from alphaloop.logger import setup_logging
    from alphaloop.runner import Runner

    cfg = Config()
    setup_logging(cfg.log_level)

    sandbox_note = " [sandbox enabled]" if sandbox else ""
    console.print(
        f"[bold green]AlphaLoop starting[/bold green]{sandbox_note} · "
        f"provider=[cyan]{cfg.provider}[/cyan] · "
        f"model=[cyan]{cfg.model}[/cyan] · "
        f"heartbeat=[cyan]{cfg.heartbeat_interval}s[/cyan] · "
        f"thread=[cyan]{cfg.thread_id}[/cyan]"
    )

    runner = Runner(cfg)
    try:
        asyncio.run(runner.start())
    except KeyboardInterrupt:
        console.print("[yellow]Stopped.[/yellow]")


@cli.command()
@click.argument("message")
@click.option("--thread", default=None, help="Conversation thread ID")
def send(message: str, thread: str | None) -> None:
    """Send MESSAGE to the running agent and print the reply."""
    import os

    if thread:
        os.environ["ALPHALOOP_THREAD_ID"] = thread

    from alphaloop.agent import create_agent, invoke_agent
    from alphaloop.config import Config

    cfg = Config()

    async def _run() -> str:
        graph, _, stack = await create_agent(cfg)
        try:
            return await invoke_agent(graph, message, cfg.thread_id)
        finally:
            await stack.aclose()

    reply = asyncio.run(_run())
    console.print(reply)


@cli.command()
@click.option(
    "--provider",
    default=None,
    type=click.Choice(["ollama", "openai", "anthropic", "gemini", "ollama_cloud"], case_sensitive=False),
    help="Model provider override",
)
@click.option("--model", default=None, help="Model override (provider-specific)")
@click.option("--interval", default=None, type=float, help="Heartbeat interval in seconds")
@click.option("--thread", default=None, help="Conversation thread ID")
@click.option("--sandbox", is_flag=True, default=False, help="Enable sandbox for shell execution")
@click.option("--docker", is_flag=True, default=False, help="Use Docker sandbox (requires Docker)")
def tui(provider: str | None, model: str | None, interval: float | None, thread: str | None, sandbox: bool, docker: bool) -> None:  # noqa: FBT001
    """Launch the interactive TUI."""
    import os

    if provider:
        os.environ["ALPHALOOP_PROVIDER"] = provider.lower()
    if model:
        os.environ["ALPHALOOP_MODEL"] = model
    if interval:
        os.environ["ALPHALOOP_HEARTBEAT_INTERVAL"] = str(interval)
    if thread:
        os.environ["ALPHALOOP_THREAD_ID"] = thread
    if sandbox or docker:
        os.environ["ALPHALOOP_SANDBOX"] = "1"
    if docker:
        os.environ["ALPHALOOP_SANDBOX_DOCKER"] = "1"

    from alphaloop.config import Config
    from alphaloop.tui import AlphaLoopApp

    cfg = Config()
    AlphaLoopApp(config=cfg).run()


@cli.command()
def status() -> None:
    """Show current AlphaLoop configuration."""
    from alphaloop.config import Config

    cfg = Config()

    from alphaloop.mcp import read_mcp_connections

    table = Table(title="AlphaLoop Config", show_header=False)
    table.add_column("Key", style="bold cyan")
    table.add_column("Value")
    table.add_row("Provider", cfg.provider)
    table.add_row("Model", cfg.model)

    endpoint = "n/a"
    if cfg.provider == "ollama":
        endpoint = cfg.ollama_base_url
    elif cfg.provider == "openai":
        endpoint = cfg.openai_base_url or "https://api.openai.com/v1"
    elif cfg.provider == "anthropic":
        endpoint = "https://api.anthropic.com"
    elif cfg.provider == "gemini":
        endpoint = "https://generativelanguage.googleapis.com"
    elif cfg.provider == "ollama_cloud":
        endpoint = cfg.ollama_cloud_base_url
    table.add_row("Provider endpoint", endpoint)

    table.add_row("Heartbeat interval", f"{cfg.heartbeat_interval}s")
    table.add_row("Heartbeat timeout", f"{cfg.heartbeat_timeout}s")
    table.add_row("Max failures", str(cfg.max_heartbeat_failures))
    table.add_row("Thread ID", cfg.thread_id)
    table.add_row("Checkpoint DB", str(cfg.checkpoint_db))
    table.add_row("Work dir", str(cfg.work_dir))

    sandbox_val = "disabled"
    if cfg.sandbox_enabled:
        sandbox_val = "docker (--network none, 512MB RAM)" if cfg.sandbox_use_docker else "restricted-local (allowlist + ulimits)"
    table.add_row("Sandbox", sandbox_val)

    mcp_connections = read_mcp_connections(cfg)
    if mcp_connections:
        table.add_row("MCP config", str(cfg.mcp_config))
        table.add_row("MCP servers", ", ".join(mcp_connections.keys()))
    else:
        table.add_row("MCP servers", "none (add ~/.alphaloop/mcp.json to enable)")

    console.print(table)


if __name__ == "__main__":
    cli()
