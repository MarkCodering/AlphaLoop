import {
  ArrowLeft,
  BookOpen,
  CheckCircle2,
  Github,
  MessageCircle,
  RefreshCw,
  ShieldCheck,
  Terminal,
} from 'lucide-react';

const REPO_URL = 'https://github.com/MarkCodering/AlphaLoop';

const FEATURE_ROWS = [
  ['Heartbeat loop', 'Pings the agent every 30s, auto-restarts after repeated failures, and sends pulse prompts for autonomous reasoning.'],
  ['Local Ollama models', 'Runs fully on local hardware with Ollama-backed models such as Llama, Gemma, and Phi.'],
  ['Persistent memory', 'Keeps conversation state in SQLite checkpoints so the same thread can resume across restarts.'],
  ['Restricted sandbox', 'Uses an allowlist, ulimits, and timeouts to block dangerous local execution patterns.'],
  ['Docker sandbox', 'Supports an ephemeral air-gapped container with RAM and process limits for stronger isolation.'],
  ['Text UI', 'Provides a Textual-based terminal interface with chat history and heartbeat status.'],
  ['Communication channels', 'Bridges Telegram and WhatsApp to the agent — each user gets their own persistent memory thread.'],
];

const CLI_ROWS = [
  ['start', 'Run the 24/7 headless agent loop until interrupted.'],
  ['tui', 'Launch the interactive terminal UI.'],
  ['send "<msg>"', 'Inject a one-off message and print the reply.'],
  ['status', 'Show the active runtime configuration.'],
  ['channels start', 'Start all configured communication channels (Telegram, WhatsApp).'],
  ['channels status', 'Show which channels are configured and their credentials.'],
];

const ENV_ROWS = [
  ['ALPHALOOP_MODEL', 'lfm2.5-thinking:1.2b', 'Ollama model to load.'],
  ['OLLAMA_BASE_URL', 'http://localhost:11434', 'Local Ollama server URL.'],
  ['ALPHALOOP_HEARTBEAT_INTERVAL', '30', 'Seconds between autonomous heartbeat ticks.'],
  ['ALPHALOOP_HEARTBEAT_TIMEOUT', '60', 'Maximum wait time for an agent response.'],
  ['ALPHALOOP_MAX_HEARTBEAT_FAILURES', '3', 'Restart threshold for consecutive failures.'],
  ['ALPHALOOP_THREAD_ID', 'alphaloop-main', 'Persistence key for memory and checkpoints.'],
  ['ALPHALOOP_CHECKPOINT_DB', '~/.alphaloop/checkpoints.db', 'SQLite checkpoint location.'],
  ['ALPHALOOP_WORK_DIR', '~/.alphaloop/workspace', 'Working directory for the agent.'],
  ['ALPHALOOP_SANDBOX', '0', 'Set to 1 to enable sandboxed execution.'],
  ['ALPHALOOP_SANDBOX_DOCKER', '0', 'Set to 1 to use Docker isolation.'],
  ['TELEGRAM_BOT_TOKEN', '—', 'Bot token from @BotFather. Required for Telegram channel.'],
  ['TELEGRAM_ALLOWED_USERS', '—', 'Comma-separated chat IDs. Empty allows all users.'],
  ['WHATSAPP_PHONE_NUMBER_ID', '—', 'Phone Number ID from the Meta developer console.'],
  ['WHATSAPP_ACCESS_TOKEN', '—', 'Meta Graph API bearer token for outbound messages.'],
  ['WHATSAPP_VERIFY_TOKEN', '—', 'Webhook verification secret you choose in Meta console.'],
  ['WHATSAPP_WEBHOOK_PORT', '8765', 'Local port for the WhatsApp webhook server.'],
];

const PROJECT_FILES = [
  ['alphaloop/agent.py', 'Agent factory and invocation helpers.'],
  ['alphaloop/heartbeat.py', 'Health checks and autonomous pulse loop.'],
  ['alphaloop/runner.py', '24/7 runner, restart logic, and signal handling.'],
  ['alphaloop/sandbox.py', 'Restricted local sandbox and Docker sandbox backends.'],
  ['alphaloop/tui.py', 'Textual terminal UI.'],
  ['alphaloop/config.py', 'Environment-driven configuration model.'],
  ['alphaloop/channels/', 'Communication channels package (Telegram, WhatsApp).'],
  ['alphaloop/channels/base.py', 'Abstract Channel base class and MessageHandler type.'],
  ['alphaloop/channels/telegram.py', 'Telegram bot channel — polling mode, per-user threads.'],
  ['alphaloop/channels/whatsapp.py', 'WhatsApp channel — Meta Cloud API with webhook server.'],
  ['alphaloop/channels/manager.py', 'ChannelManager that starts/stops all configured channels.'],
  ['main.py', 'CLI entry point.'],
  ['run.sh', 'Primary shell launcher.'],
];

const CodeBlock = ({ children }) => (
  <pre className="overflow-x-auto rounded-2xl border border-zinc-800 bg-black/70 p-5 text-sm leading-relaxed text-zinc-300">
    <code>{children}</code>
  </pre>
);

const Section = ({ eyebrow, title, description, children }) => (
  <section className="rounded-[2rem] border border-zinc-900 bg-[#050505] p-8 md:p-10 shadow-[0_30px_80px_rgba(0,0,0,0.35)]">
    <div className="mb-8 max-w-3xl">
      <div className="mb-3 text-xs font-mono font-bold uppercase tracking-[0.35em] text-amber-500">{eyebrow}</div>
      <h2 className="text-3xl font-black uppercase tracking-tight text-white md:text-4xl">{title}</h2>
      <p className="mt-4 text-sm font-mono leading-7 text-zinc-500 md:text-base">{description}</p>
    </div>
    {children}
  </section>
);

export default function AlphaLoopDocs() {
  return (
    <div className="min-h-screen bg-black text-zinc-300 selection:bg-amber-500/30 selection:text-amber-100">
      <div className="fixed inset-0 pointer-events-none bg-[radial-gradient(circle_at_top,rgba(245,158,11,0.12),transparent_26%),radial-gradient(circle_at_80%_20%,rgba(255,255,255,0.08),transparent_18%),linear-gradient(#000,#000)]" />

      <header className="sticky top-0 z-50 border-b border-zinc-900 bg-black/85 backdrop-blur-xl">
        <div className="mx-auto flex h-20 max-w-7xl items-center justify-between px-6">
          <a href="/" className="inline-flex items-center gap-3 text-sm font-mono font-bold uppercase tracking-[0.28em] text-zinc-200 transition-colors hover:text-white">
            <RefreshCw className="h-5 w-5" />
            AlphaLoop
          </a>
          <div className="flex items-center gap-4">
            <a href="/" className="inline-flex items-center gap-2 border border-zinc-800 px-4 py-2 text-xs font-mono font-bold uppercase tracking-[0.24em] text-zinc-400 transition-colors hover:border-zinc-600 hover:text-zinc-100">
              <ArrowLeft className="h-4 w-4" />
              Home
            </a>
            <a href={REPO_URL} className="inline-flex items-center gap-2 bg-white px-4 py-2 text-xs font-mono font-bold uppercase tracking-[0.24em] text-black transition-colors hover:bg-zinc-200">
              <Github className="h-4 w-4" />
              Repo
            </a>
          </div>
        </div>
      </header>

      <main className="relative z-10">
        <section className="mx-auto max-w-7xl px-6 pb-16 pt-20 md:pb-24 md:pt-28">
          <div className="grid gap-12 lg:grid-cols-[1.3fr_0.7fr] lg:items-end">
            <div>
              <div className="mb-5 inline-flex items-center gap-3 border border-zinc-800 bg-[#050505] px-4 py-2 text-xs font-mono uppercase tracking-[0.3em] text-zinc-400">
                <BookOpen className="h-4 w-4 text-amber-500" />
                Documentation
              </div>
              <h1 className="max-w-4xl text-5xl font-black uppercase leading-none tracking-tight text-white md:text-7xl">
                Run a Local
                <span className="block bg-gradient-to-r from-white to-zinc-500 bg-clip-text text-transparent">Autonomous Agent Stack</span>
              </h1>
              <p className="mt-8 max-w-3xl text-base font-mono leading-8 text-zinc-500 md:text-lg">
                AlphaLoop is a 24/7 autonomous agent runner built on local Ollama models, heartbeat supervision, and a hard-gated sandbox. This page mirrors the current repository so setup, architecture, and operations stay in one place.
              </p>
            </div>

            <div className="rounded-[2rem] border border-zinc-900 bg-[#050505] p-6">
              <div className="mb-5 flex items-center gap-3 text-xs font-mono font-bold uppercase tracking-[0.28em] text-zinc-400">
                <CheckCircle2 className="h-4 w-4 text-emerald-400" />
                Requirements
              </div>
              <div className="space-y-4">
                {['Python 3.12+', 'uv', 'Ollama running locally'].map((item) => (
                  <div key={item} className="flex items-center gap-3 border-b border-zinc-900 pb-4 last:border-b-0 last:pb-0">
                    <span className="h-2.5 w-2.5 rounded-full bg-amber-500 shadow-[0_0_14px_rgba(245,158,11,0.8)]" />
                    <span className="text-sm font-mono text-zinc-300">{item}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>

        <div className="mx-auto flex max-w-7xl flex-col gap-8 px-6 pb-24">
          <Section
            eyebrow="Quick Start"
            title="Bootstrap in Minutes"
            description="The repository is structured to get a local autonomous loop running with minimal setup."
          >
            <CodeBlock>{`git clone ${REPO_URL} && cd AlphaLoop
uv sync
ollama pull lfm2.5-thinking:1.2b
./run.sh tui`}</CodeBlock>
          </Section>

          <Section
            eyebrow="Core Features"
            title="What The Repo Already Provides"
            description="These capabilities are implemented in the current codebase and reflected in the CLI, runtime modules, and landing page."
          >
            <div className="grid gap-4 md:grid-cols-2">
              {FEATURE_ROWS.map(([title, description]) => (
                <div key={title} className="rounded-2xl border border-zinc-900 bg-black/50 p-5">
                  <div className="mb-3 text-sm font-mono font-bold uppercase tracking-[0.18em] text-zinc-200">{title}</div>
                  <p className="text-sm font-mono leading-7 text-zinc-500">{description}</p>
                </div>
              ))}
            </div>
          </Section>

          <Section
            eyebrow="CLI"
            title="Launch Modes"
            description="The shell entrypoint exposes a small set of modes for interactive use, background execution, and direct message injection."
          >
            <div className="overflow-hidden rounded-2xl border border-zinc-900">
              <div className="grid grid-cols-[minmax(120px,180px)_1fr] bg-zinc-950 text-xs font-mono font-bold uppercase tracking-[0.22em] text-zinc-500">
                <div className="border-r border-zinc-900 px-4 py-4">Mode</div>
                <div className="px-4 py-4">Description</div>
              </div>
              {CLI_ROWS.map(([mode, description]) => (
                <div key={mode} className="grid grid-cols-[minmax(120px,180px)_1fr] border-t border-zinc-900 text-sm font-mono">
                  <div className="border-r border-zinc-900 px-4 py-4 text-zinc-100">{mode}</div>
                  <div className="px-4 py-4 text-zinc-500">{description}</div>
                </div>
              ))}
            </div>
            <div className="mt-6">
              <CodeBlock>{`./run.sh [mode] [options]
./run.sh start --sandbox
./run.sh tui --model gemma3:4b
./run.sh send "Summarize the latest project state"`}</CodeBlock>
            </div>
          </Section>

          <Section
            eyebrow="Security"
            title="Two Sandbox Paths"
            description="AlphaLoop can operate with a restricted local shell or a more isolated Docker runtime depending on the risk level of the task."
          >
            <div className="grid gap-6 lg:grid-cols-2">
              <div className="rounded-2xl border border-zinc-900 bg-black/50 p-6">
                <div className="mb-4 inline-flex items-center gap-3 text-sm font-mono font-bold uppercase tracking-[0.22em] text-zinc-100">
                  <ShieldCheck className="h-4 w-4 text-amber-500" />
                  Restricted Local
                </div>
                <ul className="space-y-3 text-sm font-mono leading-7 text-zinc-500">
                  <li>Command allowlist for safe shell usage.</li>
                  <li>Dangerous patterns blocked before execution.</li>
                  <li>Per-command timeout and ulimit enforcement.</li>
                </ul>
              </div>
              <div className="rounded-2xl border border-zinc-900 bg-black/50 p-6">
                <div className="mb-4 inline-flex items-center gap-3 text-sm font-mono font-bold uppercase tracking-[0.22em] text-zinc-100">
                  <Terminal className="h-4 w-4 text-amber-500" />
                  Docker Isolation
                </div>
                <ul className="space-y-3 text-sm font-mono leading-7 text-zinc-500">
                  <li>No outbound network with `--network none`.</li>
                  <li>Ephemeral container lifecycle per execution.</li>
                  <li>RAM, PID, and privilege restrictions for containment.</li>
                </ul>
              </div>
            </div>
          </Section>

          <Section
            eyebrow="Configuration"
            title="Environment Controls"
            description="Most runtime behavior is controlled through environment variables defined in the repository configuration layer."
          >
            <div className="overflow-hidden rounded-2xl border border-zinc-900">
              <div className="grid grid-cols-[1.2fr_1fr_1.4fr] bg-zinc-950 text-xs font-mono font-bold uppercase tracking-[0.22em] text-zinc-500">
                <div className="border-r border-zinc-900 px-4 py-4">Variable</div>
                <div className="border-r border-zinc-900 px-4 py-4">Default</div>
                <div className="px-4 py-4">Purpose</div>
              </div>
              {ENV_ROWS.map(([name, value, description]) => (
                <div key={name} className="grid grid-cols-[1.2fr_1fr_1.4fr] border-t border-zinc-900 text-sm font-mono">
                  <div className="border-r border-zinc-900 px-4 py-4 text-zinc-100">{name}</div>
                  <div className="border-r border-zinc-900 px-4 py-4 text-amber-400">{value}</div>
                  <div className="px-4 py-4 text-zinc-500">{description}</div>
                </div>
              ))}
            </div>
          </Section>

          <Section
            eyebrow="Communication Channels"
            title="Telegram & WhatsApp"
            description="AlphaLoop can receive messages from Telegram and WhatsApp and reply using the same AI agent. Every platform user gets an independent, persistent memory thread backed by SQLite."
          >
            <div className="grid gap-6 lg:grid-cols-2">
              <div className="rounded-2xl border border-zinc-900 bg-black/50 p-6">
                <div className="mb-4 inline-flex items-center gap-3 text-sm font-mono font-bold uppercase tracking-[0.22em] text-zinc-100">
                  <MessageCircle className="h-4 w-4 text-amber-500" />
                  Telegram
                </div>
                <ul className="space-y-3 text-sm font-mono leading-7 text-zinc-500">
                  <li>Polling mode — no public URL or webhook needed.</li>
                  <li>Create a bot with @BotFather, set TELEGRAM_BOT_TOKEN.</li>
                  <li>Optional allowlist via TELEGRAM_ALLOWED_USERS.</li>
                  <li>Install: <code className="text-amber-400">uv add 'python-telegram-bot&gt;=21.0'</code></li>
                </ul>
              </div>
              <div className="rounded-2xl border border-zinc-900 bg-black/50 p-6">
                <div className="mb-4 inline-flex items-center gap-3 text-sm font-mono font-bold uppercase tracking-[0.22em] text-zinc-100">
                  <MessageCircle className="h-4 w-4 text-emerald-400" />
                  WhatsApp
                </div>
                <ul className="space-y-3 text-sm font-mono leading-7 text-zinc-500">
                  <li>Meta WhatsApp Business Cloud API (free tier).</li>
                  <li>Runs a local webhook server on port 8765 (configurable).</li>
                  <li>Expose publicly with ngrok for local development.</li>
                  <li>Install: <code className="text-amber-400">uv add aiohttp</code></li>
                </ul>
              </div>
            </div>
            <div className="mt-6 space-y-4">
              <CodeBlock>{`# Telegram — set token and start
export TELEGRAM_BOT_TOKEN=7123456789:AAF...
alphaloop channels start

# WhatsApp — set Meta credentials, expose webhook, start
export WHATSAPP_PHONE_NUMBER_ID=12345678901234
export WHATSAPP_ACCESS_TOKEN=EAA...
export WHATSAPP_VERIFY_TOKEN=my-secret-token
ngrok http 8765   # register the HTTPS URL in Meta console
alphaloop channels start

# Check what is configured
alphaloop channels status`}</CodeBlock>
              <div className="rounded-2xl border border-zinc-900 bg-black/50 p-5">
                <div className="mb-3 text-xs font-mono font-bold uppercase tracking-[0.22em] text-zinc-400">TUI commands</div>
                <div className="grid gap-2 text-sm font-mono">
                  {[
                    ['/channels', 'List configured channels and their status.'],
                    ['/channels start <name>', 'Start a specific channel (telegram or whatsapp).'],
                    ['/channels stop <name>', 'Stop a running channel.'],
                  ].map(([cmd, desc]) => (
                    <div key={cmd} className="flex items-start gap-4 border-b border-zinc-900 pb-2 last:border-b-0">
                      <span className="min-w-[220px] text-amber-400">{cmd}</span>
                      <span className="text-zinc-500">{desc}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </Section>

          <Section
            eyebrow="Structure"
            title="Repository Layout"
            description="These files define the current runtime loop, agent integration, shell interfaces, and web landing experience."
          >
            <div className="grid gap-4 md:grid-cols-2">
              {PROJECT_FILES.map(([path, description]) => (
                <div key={path} className="rounded-2xl border border-zinc-900 bg-black/50 p-5">
                  <div className="mb-2 text-sm font-mono font-bold text-zinc-100">{path}</div>
                  <div className="text-sm font-mono leading-7 text-zinc-500">{description}</div>
                </div>
              ))}
            </div>
          </Section>
        </div>
      </main>
    </div>
  );
}
