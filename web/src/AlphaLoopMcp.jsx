import { useMemo, useState } from 'react'
import {
  Check,
  Copy,
  ExternalLink,
  KeyRound,
  Link2,
  TerminalSquare,
  Waves,
} from 'lucide-react'

const RECIPES = {
  github: {
    label: 'GitHub MCP with PAT',
    summary: 'Hosted HTTP MCP with document-level inputs. Best added by editing the MCP JSON file directly.',
    accent: 'from-amber-300 via-orange-400 to-red-500',
    icon: KeyRound,
    fileMode: 'Full config file',
    fileCode: `{
  "servers": {
    "github": {
      "type": "http",
      "url": "https://api.githubcopilot.com/mcp/",
      "headers": {
        "Authorization": "Bearer \${input:github_mcp_pat}"
      }
    }
  },
  "inputs": [
    {
      "type": "promptString",
      "id": "github_mcp_pat",
      "description": "GitHub Personal Access Token",
      "password": true
    }
  ]
}`,
    tuiCode: `/mcp add github '{"url":"https://api.githubcopilot.com/mcp/","headers":{"Authorization":"Bearer YOUR_PAT"}}'`,
    tuiNote: 'Use the TUI only if you already have the token value. The TUI command cannot create top-level `inputs` prompts.',
    notes: [
      'AlphaLoop now accepts the wrapped `servers` shape directly and maps `type` to `transport` automatically.',
      'If you want a reusable password prompt, keep the full JSON document in `~/.alphaloop/mcp.json`.',
    ],
  },
  notion: {
    label: 'Simple Hosted MCP',
    summary: 'Single hosted MCP endpoint with no extra inputs. This works cleanly from either the config file or the TUI.',
    accent: 'from-cyan-300 via-sky-400 to-blue-500',
    icon: Link2,
    fileMode: 'Config file or paste-in snippet',
    fileCode: `{
  "mcpServers": {
    "notion": {
      "url": "https://mcp.notion.com/mcp"
    }
  }
}`,
    tuiCode: '/mcp add notion https://mcp.notion.com/mcp',
    tuiNote: 'Best option for simple hosted MCPs. AlphaLoop fills in `transport=http` for you.',
    notes: [
      'AlphaLoop accepts `mcpServers`, wrapped `servers`, or the older flat `{name: spec}` format.',
      'If you later add custom headers or OAuth, you can replace the TUI-added entry with a full JSON spec.',
    ],
  },
}

function CopyButton({ value }) {
  const [copied, setCopied] = useState(false)

  async function onCopy() {
    await navigator.clipboard.writeText(value)
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1400)
  }

  return (
    <button
      type="button"
      onClick={onCopy}
      className="inline-flex items-center gap-2 rounded-full border border-white/12 bg-white/6 px-3 py-1.5 text-xs font-medium text-zinc-200 transition hover:border-white/25 hover:bg-white/10"
    >
      {copied ? <Check className="h-3.5 w-3.5 text-emerald-300" /> : <Copy className="h-3.5 w-3.5" />}
      {copied ? 'Copied' : 'Copy'}
    </button>
  )
}

function CodePanel({ eyebrow, title, body, footer }) {
  return (
    <section className="rounded-[28px] border border-white/10 bg-[#0d1014]/95 p-5 shadow-[0_18px_80px_rgba(0,0,0,0.35)]">
      <div className="mb-4 flex items-start justify-between gap-4">
        <div>
          <div className="text-[11px] uppercase tracking-[0.24em] text-zinc-500">{eyebrow}</div>
          <h3 className="mt-2 text-lg font-semibold text-white">{title}</h3>
        </div>
        <CopyButton value={body} />
      </div>
      <pre className="overflow-x-auto rounded-2xl border border-white/8 bg-black/40 p-4 text-sm leading-6 text-zinc-200">
        <code>{body}</code>
      </pre>
      {footer ? <p className="mt-3 text-sm leading-6 text-zinc-400">{footer}</p> : null}
    </section>
  )
}

export default function AlphaLoopMcp() {
  const [selected, setSelected] = useState('github')
  const recipe = RECIPES[selected]
  const Icon = recipe.icon

  const compatibility = useMemo(() => ([
    {
      label: 'Accepted file shapes',
      value: '`servers`, `mcpServers`, or flat server maps',
    },
    {
      label: 'Runtime normalization',
      value: '`type: "http"` is mapped to `transport: "http"`',
    },
    {
      label: 'Best use for `/mcp add`',
      value: 'Simple URLs or one quoted server JSON object',
    },
    {
      label: 'Needs file editing',
      value: 'Anything with top-level `inputs` or multiple servers at once',
    },
  ]), [])

  return (
    <main className="min-h-screen bg-[#06070a] text-zinc-200">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_top,rgba(81,142,255,0.18),transparent_38%),radial-gradient(circle_at_20%_30%,rgba(255,176,86,0.12),transparent_28%)]" />
      <div className="relative mx-auto flex w-full max-w-7xl flex-col gap-14 px-6 py-10 md:px-10 md:py-14">
        <header className="overflow-hidden rounded-[36px] border border-white/10 bg-[linear-gradient(135deg,rgba(15,20,28,0.96),rgba(9,11,16,0.92))] p-8 shadow-[0_30px_120px_rgba(0,0,0,0.5)] md:p-12">
          <div className="flex flex-col gap-10 lg:flex-row lg:items-end lg:justify-between">
            <div className="max-w-3xl">
              <div className="inline-flex items-center gap-2 rounded-full border border-cyan-400/20 bg-cyan-400/8 px-3 py-1 text-xs uppercase tracking-[0.24em] text-cyan-200">
                <Waves className="h-3.5 w-3.5" />
                MCP Setup
              </div>
              <h1 className="mt-5 max-w-2xl text-4xl font-semibold tracking-tight text-white md:text-6xl">
                Add hosted MCPs without guessing which JSON shape AlphaLoop expects.
              </h1>
              <p className="mt-5 max-w-2xl text-base leading-7 text-zinc-400 md:text-lg">
                Use the full config file for wrappers like <code className="text-zinc-200">servers + inputs</code>.
                Use the TUI for quick one-server adds like Notion.
              </p>
            </div>

            <div className="grid gap-3 text-sm text-zinc-300 md:min-w-[22rem]">
              {compatibility.map((item) => (
                <div key={item.label} className="rounded-2xl border border-white/8 bg-white/[0.03] px-4 py-3">
                  <div className="text-[11px] uppercase tracking-[0.22em] text-zinc-500">{item.label}</div>
                  <div className="mt-1">{item.value}</div>
                </div>
              ))}
            </div>
          </div>
        </header>

        <section className="grid gap-6 lg:grid-cols-[0.92fr_1.08fr]">
          <aside className="rounded-[32px] border border-white/10 bg-[#0b0e12]/90 p-5">
            <div className="mb-4 text-[11px] uppercase tracking-[0.24em] text-zinc-500">Recipe</div>
            <div className="space-y-3">
              {Object.entries(RECIPES).map(([key, entry]) => {
                const EntryIcon = entry.icon
                const active = key === selected
                return (
                  <button
                    key={key}
                    type="button"
                    onClick={() => setSelected(key)}
                    className={`w-full rounded-[24px] border p-5 text-left transition ${
                      active
                        ? 'border-white/20 bg-white/[0.06]'
                        : 'border-white/8 bg-transparent hover:border-white/14 hover:bg-white/[0.03]'
                    }`}
                  >
                    <div className="flex items-start gap-4">
                      <div className={`mt-1 flex h-11 w-11 items-center justify-center rounded-2xl bg-gradient-to-br ${entry.accent} text-black`}>
                        <EntryIcon className="h-5 w-5" />
                      </div>
                      <div>
                        <div className="text-lg font-medium text-white">{entry.label}</div>
                        <p className="mt-2 text-sm leading-6 text-zinc-400">{entry.summary}</p>
                      </div>
                    </div>
                  </button>
                )
              })}
            </div>

            <div className="mt-5 rounded-[24px] border border-white/8 bg-black/20 p-5 text-sm leading-6 text-zinc-400">
              AlphaLoop reads <code className="text-zinc-200">~/.alphaloop/mcp.json</code>. If the document already
              contains metadata like <code className="text-zinc-200">inputs</code>, the TUI preserves it when you add or remove servers.
            </div>
          </aside>

          <section className="space-y-6">
            <div className="rounded-[32px] border border-white/10 bg-[#0b0f14]/92 p-6 md:p-7">
              <div className="flex flex-col gap-6 md:flex-row md:items-center md:justify-between">
                <div>
                  <div className="text-[11px] uppercase tracking-[0.24em] text-zinc-500">Selected Flow</div>
                  <div className="mt-3 flex items-center gap-3">
                    <div className={`flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br ${recipe.accent} text-black`}>
                      <Icon className="h-5 w-5" />
                    </div>
                    <div>
                      <h2 className="text-2xl font-semibold text-white">{recipe.label}</h2>
                      <div className="text-sm text-zinc-400">{recipe.fileMode}</div>
                    </div>
                  </div>
                </div>

                <a
                  href="https://modelcontextprotocol.io"
                  className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/[0.04] px-4 py-2 text-sm text-zinc-200 transition hover:border-white/20 hover:bg-white/[0.08]"
                >
                  MCP docs
                  <ExternalLink className="h-4 w-4" />
                </a>
              </div>

              <div className="mt-6 grid gap-3">
                {recipe.notes.map((note) => (
                  <div key={note} className="rounded-2xl border border-white/8 bg-black/20 px-4 py-3 text-sm leading-6 text-zinc-300">
                    {note}
                  </div>
                ))}
              </div>
            </div>

            <CodePanel
              eyebrow="Config File"
              title="Paste into ~/.alphaloop/mcp.json"
              body={recipe.fileCode}
              footer={selected === 'github'
                ? 'This is the recommended path for auth prompts because the prompt metadata lives at the document root.'
                : 'This wrapped form is accepted directly by AlphaLoop and stays readable if you add more servers later.'}
            />

            <CodePanel
              eyebrow="TUI"
              title="Quick add command"
              body={recipe.tuiCode}
              footer={recipe.tuiNote}
            />

            <section className="rounded-[28px] border border-white/10 bg-[#0d1014]/95 p-5">
              <div className="mb-4 flex items-center gap-3">
                <TerminalSquare className="h-5 w-5 text-cyan-300" />
                <h3 className="text-lg font-semibold text-white">What changed in AlphaLoop</h3>
              </div>
              <div className="grid gap-3 text-sm leading-6 text-zinc-400 md:grid-cols-2">
                <div className="rounded-2xl border border-white/8 bg-black/20 p-4">
                  The loader now understands wrapped documents like <code className="text-zinc-200">{"{ \"servers\": ... }"}</code> and <code className="text-zinc-200">{"{ \"mcpServers\": ... }"}</code>.
                </div>
                <div className="rounded-2xl border border-white/8 bg-black/20 p-4">
                  <code className="text-zinc-200">/mcp add</code> now accepts either a raw URL or one quoted JSON server spec, which is enough for custom headers.
                </div>
              </div>
            </section>
          </section>
        </section>
      </div>
    </main>
  )
}
