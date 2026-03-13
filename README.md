# AlphaLoop

> A 24/7 autonomous deep agent — powered by local Ollama models, secured by a hard-gated sandbox, kept alive by a heartbeat monitor.

Built on [deepagents](https://github.com/langchain-ai/deepagents) + [LangGraph](https://github.com/langchain-ai/langgraph).

---

## Features

| | |
|---|---|
| **Heartbeat loop** | Pings the agent every 30s. Auto-restarts after 3 consecutive failures. Sends autonomous "pulse" prompts so the agent reasons without human input. |
| **Local Ollama models** | Plug in any model — `lfm2.5-thinking:1.2b`, Llama, Gemma, Phi. Zero API cost, zero data leakage. |
| **Persistent memory** | SQLite checkpointer at `~/.alphaloop/checkpoints.db`. Same `thread_id` = memory across restarts. |
| **Sandbox — restricted** | Command allowlist + `ulimit` + 30s timeout. Blocks `rm -rf`, `sudo`, `eval`, and 10+ dangerous patterns. |
| **Sandbox — Docker** | Ephemeral container, `--network none`, 512MB RAM, PID limit. Full host isolation. |
| **TUI** | Textual terminal UI with a live chat panel and heartbeat sidebar. |

---

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- [Ollama](https://ollama.com/) running locally

---

## Quick Start

```bash
# 1. Clone
git clone https://github.com/your-org/alphaloop && cd alphaloop

# 2. Install Python dependencies
uv sync

# 3. Pull the model
ollama pull lfm2.5-thinking:1.2b

# 4. Launch
./run.sh tui        # interactive TUI
./run.sh start      # headless 24/7 mode
```

---

## CLI

```bash
./run.sh [mode] [options]
```

| Mode | Description |
|------|-------------|
| `start` | Run 24/7 headless agent (blocks until Ctrl-C) |
| `tui` | Launch the interactive terminal UI |
| `send "<msg>"` | Inject a one-off message and print the reply |
| `status` | Show current config table |

**Options** (for `start` and `tui`):

| Flag | Description |
|------|-------------|
| `--model MODEL` | Override Ollama model (e.g. `gemma3:4b`) |
| `--interval N` | Heartbeat interval in seconds (default: 30) |
| `--thread ID` | Conversation thread ID (default: `alphaloop-main`) |
| `--sandbox` | Enable restricted local sandbox |
| `--sandbox --docker` | Enable Docker sandbox (requires Docker) |

---

## Sandbox Modes

### Restricted Local (default with `--sandbox`)

Runs on the host with:
- Command allowlist (`python3`, `git`, `grep`, `ls`, `curl`, …)
- Hard-blocked patterns (`rm -rf`, `sudo`, `eval`, backticks, …)
- Per-command timeout (30s)
- `ulimit` on CPU, file size, and open files

### Docker (`--sandbox --docker`)

Every command runs inside an ephemeral container:
- `--network none` — no outbound network
- `--memory 512m` — RAM cap
- `--pids-limit 64` — fork bomb protection
- `--security-opt no-new-privileges`
- `--read-only` root fs + `/tmp` tmpfs
- Container is destroyed after use

---

## Configuration

All config is via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `ALPHALOOP_MODEL` | `lfm2.5-thinking:1.2b` | Ollama model |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL |
| `ALPHALOOP_HEARTBEAT_INTERVAL` | `30` | Seconds between heartbeats |
| `ALPHALOOP_HEARTBEAT_TIMEOUT` | `60` | Max seconds to wait for agent response |
| `ALPHALOOP_MAX_HEARTBEAT_FAILURES` | `3` | Consecutive failures before restart |
| `ALPHALOOP_THREAD_ID` | `alphaloop-main` | Conversation thread (persistence key) |
| `ALPHALOOP_CHECKPOINT_DB` | `~/.alphaloop/checkpoints.db` | SQLite checkpoint path |
| `ALPHALOOP_WORK_DIR` | `~/.alphaloop/workspace` | Agent working directory |
| `ALPHALOOP_SANDBOX` | `0` | Set to `1` to enable sandbox |
| `ALPHALOOP_SANDBOX_DOCKER` | `0` | Set to `1` to use Docker sandbox |
| `ALPHALOOP_SANDBOX_TIMEOUT` | `30` | Per-command sandbox timeout |
| `ALPHALOOP_LOG_LEVEL` | `INFO` | Log level (`DEBUG`, `INFO`, `WARNING`) |
| `ALPHALOOP_SYSTEM_PROMPT` | *(see config.py)* | Agent system prompt prefix |

Example:

```bash
ALPHALOOP_MODEL=gemma3:4b \
ALPHALOOP_HEARTBEAT_INTERVAL=60 \
./run.sh tui
```

---

## Project Structure

```
alphaloop/
├── agent.py        # deepagents factory: create_agent(), invoke_agent(), ping_agent()
├── heartbeat.py    # HeartbeatMonitor — health-check + autonomous pulse every N seconds
├── runner.py       # Runner — 24/7 loop, signal handling, auto-restart
├── sandbox.py      # RestrictedLocalSandbox + DockerSandbox
├── tui.py          # Textual TUI: chat panel + heartbeat sidebar
├── config.py       # Config dataclass — all settings from env vars
└── logger.py       # Rich structured logging

main.py             # Click CLI entry point
run.sh              # Shell launcher script
web/                # Landing page (Vite + React + Tailwind)
```

---

## Landing Page

```bash
cd web
npm install
npm run dev     # dev server at http://localhost:5173
npm run build   # production build → web/dist/
```

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  Runner (24/7 loop)                                  │
│                                                      │
│  ┌──────────────────┐    ┌─────────────────────┐    │
│  │  HeartbeatMonitor│    │  Agent (LangGraph)   │    │
│  │  ── tick every   │───▶│  ── ChatOllama       │    │
│  │     30s          │    │  ── deepagents tools │    │
│  │  ── ping (health)│    │  ── SQLite memory    │    │
│  │  ── pulse (task) │    │  ── Sandbox backend  │    │
│  └──────────────────┘    └─────────────────────┘    │
│           │                                          │
│           ▼ on 3 failures                            │
│       auto-restart                                   │
└─────────────────────────────────────────────────────┘
```

---

## License

MIT
