import { useState, useEffect } from 'react';
import {
  Terminal,
  ShieldCheck,
  Cpu,
  RefreshCw,
  Code2,
  Database,
  Lock,
  ChevronRight,
  Github,
  Command
} from 'lucide-react';

const TERMINAL_LINES = [
  "> alphaloop init --model lfm2.5-thinking:1.2b",
  "[System] Local model loaded successfully. RAM usage: 731MB",
  "> alphaloop task \"Analyze user feedback logs and generate a feature roadmap\"",
  "[Agent] Task received. Breaking down into sub-tasks...",
  "[Agent] 1. Parsing 10,000+ CSV rows...",
  "[Sandbox] Spawned isolated environment (ID: x7f9a) with read-only data access.",
  "[Agent] 2. Extracting key sentiment clusters...",
  "[Agent] 3. Cross-referencing with current GitHub issues...",
  "[Heartbeat] ● tick=4 uptime=100% — agent healthy",
  "[Loop] Deep work sequence initiated. Running in background 24/7.",
];

const REPO_URL = 'https://github.com/MarkCodering/AlphaLoop';

const TerminalSimulation = () => {
  const [visibleCount, setVisibleCount] = useState(0);

  useEffect(() => {
    let i = 0;
    const interval = setInterval(() => {
      i += 1;
      setVisibleCount(i);
      if (i >= TERMINAL_LINES.length) clearInterval(interval);
    }, 1200);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="w-full max-w-2xl mx-auto bg-[#050505] rounded-sm overflow-hidden border border-zinc-800 shadow-[0_0_50px_rgba(0,0,0,1)] relative font-mono">
      {/* Grid lines */}
      <div className="absolute inset-0 bg-[linear-gradient(rgba(255,255,255,0.02)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.02)_1px,transparent_1px)] bg-[size:24px_24px] pointer-events-none z-0" />
      {/* Vignette */}
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_center,transparent_20%,#050505_150%)] pointer-events-none z-10" />

      {/* Title bar */}
      <div className="relative z-20 flex items-center justify-between px-4 py-2 bg-[#0a0a0a] border-b border-zinc-800">
        <div className="flex items-center space-x-3">
          <div className="flex space-x-1">
            <div className="w-1.5 h-1.5 bg-zinc-700" />
            <div className="w-1.5 h-1.5 bg-zinc-700" />
            <div className="w-1.5 h-1.5 bg-amber-500 animate-pulse shadow-[0_0_8px_rgba(245,158,11,0.8)]" />
          </div>
          <div className="text-[10px] text-zinc-500 tracking-[0.2em] uppercase">SYS.TERM // 01</div>
        </div>
        <div className="text-[10px] text-zinc-600 tracking-widest uppercase">alphaloop-main</div>
      </div>

      {/* Output */}
      <div className="relative z-20 p-6 text-sm h-72 overflow-y-auto flex flex-col justify-end leading-relaxed">
        <div className="space-y-3">
          {TERMINAL_LINES.slice(0, visibleCount).map((line, i) => {
            const isCommand  = line.startsWith('>');
            const isSandbox  = line.startsWith('[Sandbox]');
            const isHeartbeat= line.startsWith('[Heartbeat]');
            const isLoop     = line.startsWith('[Loop]');
            return (
              <div
                key={i}
                className={
                  isCommand    ? 'text-zinc-100 font-bold' :
                  isSandbox    ? 'text-amber-500' :
                  isHeartbeat  ? 'text-emerald-400' :
                  isLoop       ? 'text-cyan-400' :
                  'text-zinc-500'
                }
              >
                {line}
              </div>
            );
          })}
          {visibleCount < TERMINAL_LINES.length && (
            <div className="animate-pulse w-2.5 h-5 bg-amber-500 mt-2 shadow-[0_0_10px_rgba(245,158,11,0.5)]" />
          )}
        </div>
      </div>
    </div>
  );
};

const FeatureCard = ({ icon: Icon, title, description }) => (
  <div className="p-8 bg-[#050505] border border-zinc-800 hover:border-zinc-500 transition-all duration-300 group relative overflow-hidden flex flex-col items-start">
    <div className="absolute top-0 right-0 w-16 h-16 bg-zinc-900 rotate-45 translate-x-8 -translate-y-8 border-l border-b border-zinc-800 group-hover:bg-amber-500 transition-colors" />
    <div className="w-12 h-12 bg-[#0a0a0a] border border-zinc-800 flex items-center justify-center mb-8 group-hover:border-amber-500 transition-colors relative z-10">
      <Icon className="w-5 h-5 text-zinc-400 group-hover:text-amber-500 transition-colors" />
    </div>
    <h3 className="text-lg font-mono font-bold tracking-wide uppercase text-zinc-100 mb-4 relative z-10">{title}</h3>
    <p className="text-sm font-mono text-zinc-500 leading-relaxed relative z-10">{description}</p>
  </div>
);

export default function AlphaLoopLanding() {
  return (
    <div className="min-h-screen bg-black text-zinc-300 font-sans selection:bg-amber-500/30 selection:text-amber-200 relative">
      <div className="fixed inset-0 pointer-events-none bg-[radial-gradient(circle_at_center,transparent_0%,#000_100%)] z-10 opacity-90" />

      {/* Nav */}
      <nav className="fixed w-full z-50 top-0 border-b border-zinc-900 bg-black/90 backdrop-blur-md">
        <div className="max-w-7xl mx-auto px-6 h-20 flex items-center justify-between">
          <div className="flex items-center space-x-3">
            <RefreshCw className="w-6 h-6 text-zinc-100" />
            <span className="text-lg font-mono font-bold tracking-widest uppercase text-white">AlphaLoop</span>
          </div>
          <div className="hidden md:flex items-center space-x-10 text-xs font-mono font-medium tracking-widest uppercase text-zinc-500">
            <a href="#features" className="hover:text-zinc-100 transition-colors">Features</a>
            <a href="#security" className="hover:text-amber-500 transition-colors">Security</a>
            <a href="/docs/" className="hover:text-zinc-100 transition-colors">Docs</a>
          </div>
          <div className="flex items-center space-x-6">
            <a href={REPO_URL} className="text-zinc-500 hover:text-white transition-colors">
              <Github className="w-5 h-5" />
            </a>
            <button className="hidden md:inline-flex items-center justify-center px-6 py-2.5 text-xs font-mono font-bold tracking-widest uppercase text-black bg-zinc-100 hover:bg-white transition-colors">
              Deploy
            </button>
          </div>
        </div>
      </nav>

      {/* Hero */}
      <section className="relative pt-40 pb-24 md:pt-52 md:pb-32 overflow-hidden px-6">
        <div className="absolute top-0 left-1/2 -translate-x-1/2 w-full h-[500px] bg-zinc-900/20 blur-[150px] -z-10 pointer-events-none" />
        <div className="absolute top-1/2 left-1/4 w-[600px] h-[400px] bg-amber-900/10 blur-[120px] -z-10 pointer-events-none rounded-full" />

        <div className="max-w-7xl mx-auto grid lg:grid-cols-2 gap-16 items-center relative z-20">
          <div className="space-y-10">
            <div className="inline-flex items-center space-x-3 px-4 py-2 border border-zinc-800 bg-[#050505]">
              <span className="flex h-2 w-2 bg-amber-500 shadow-[0_0_8px_rgba(245,158,11,0.8)] animate-pulse" />
              <span className="text-xs font-mono tracking-widest uppercase text-zinc-400">System v0.1.0 Online</span>
            </div>

            <h1 className="text-5xl md:text-6xl lg:text-7xl font-black text-white tracking-tighter uppercase leading-[1]">
              Autonomous <br />
              <span className="text-transparent bg-clip-text bg-gradient-to-r from-zinc-400 to-zinc-600">Deep Work</span> <br />
              Agent.
            </h1>

            <p className="text-base font-mono md:text-lg text-zinc-500 max-w-xl leading-relaxed">
              AlphaLoop runs 24/7 on your local hardware. Powered by Ollama local LLMs, secured by a hard-gated sandbox, and kept alive by a heartbeat monitor. It executes complex tasks relentlessly while you sleep.
            </p>

            <div className="flex flex-col sm:flex-row gap-6 pt-4">
              <button className="inline-flex items-center justify-center px-8 py-4 text-sm font-mono font-bold tracking-widest uppercase text-black bg-white hover:bg-zinc-200 transition-all group">
                <Command className="w-5 h-5 mr-3" />
                ./run.sh tui
              </button>
              <a href="/docs/" className="inline-flex items-center justify-center px-8 py-4 text-sm font-mono font-bold tracking-widest uppercase text-zinc-300 bg-transparent border border-zinc-700 hover:border-zinc-300 transition-all group">
                Documentation
                <ChevronRight className="w-4 h-4 ml-3 group-hover:translate-x-1 transition-transform" />
              </a>
            </div>
          </div>

          <div className="relative z-10 w-full">
            <div className="absolute -inset-4 border border-zinc-800/50 -z-10 hidden lg:block" />
            <div className="absolute -inset-8 border border-zinc-900/50 -z-10 hidden lg:block" />
            <TerminalSimulation />
          </div>
        </div>
      </section>

      {/* Features */}
      <section id="features" className="py-32 bg-[#020202] border-y border-zinc-900 relative z-20">
        <div className="max-w-7xl mx-auto px-6">
          <div className="flex flex-col md:flex-row md:items-end justify-between mb-20 gap-8">
            <div className="max-w-2xl">
              <h2 className="text-3xl md:text-5xl font-black uppercase tracking-tighter text-white mb-6">Relentless Execution</h2>
              <p className="text-base font-mono text-zinc-500 leading-relaxed">Hand off massive refactors or continuous data pipelines. AlphaLoop operates independently inside a secure perimeter until the objective is complete.</p>
            </div>
            <div className="hidden md:flex flex-col space-y-2 items-end">
              <div className="h-0.5 w-12 bg-zinc-800" />
              <div className="h-0.5 w-24 bg-amber-500" />
              <div className="h-0.5 w-16 bg-zinc-800" />
            </div>
          </div>

          <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-6">
            <FeatureCard icon={RefreshCw}   title="Heartbeat Loop"   description="Auto-restart on failure. Health-check every 30s. Autonomous pulse prompts drive goal-directed reasoning without human input." />
            <FeatureCard icon={Cpu}         title="Local Compute"    description="Plug in any Ollama model — lfm2.5-thinking, Llama, Gemma, Phi. Zero API latency, zero token bill, zero data leakage." />
            <FeatureCard icon={ShieldCheck} title="Hard Sandbox"     description="Restricted local shell with command allowlist + ulimits, or full Docker isolation. Host system stays untouched." />
            <FeatureCard icon={Lock}        title="Air-Gapped"       description="Your codebase and sensitive data never leave your machine. SQLite persistence keeps memory across restarts." />
          </div>

          {/* Sandbox spec table */}
          <div className="mt-16 relative">
            <div className="absolute -inset-px bg-gradient-to-b from-amber-500/10 to-transparent opacity-60 pointer-events-none" />
            <div className="relative bg-[#050505] border border-zinc-800 p-8 md:p-10">
              {/* corner marks */}
              <div className="absolute top-0 left-0 w-2 h-2 border-t-2 border-l-2 border-amber-500" />
              <div className="absolute top-0 right-0 w-2 h-2 border-t-2 border-r-2 border-amber-500" />
              <div className="absolute bottom-0 left-0 w-2 h-2 border-b-2 border-l-2 border-amber-500" />
              <div className="absolute bottom-0 right-0 w-2 h-2 border-b-2 border-r-2 border-amber-500" />

              <div className="flex items-center justify-between border-b border-zinc-800 pb-6 mb-8">
                <h3 className="text-sm font-mono font-bold tracking-widest uppercase text-zinc-300 flex items-center">
                  <Lock className="w-4 h-4 mr-3 text-amber-500" />
                  Perimeter Defenses
                </h3>
                <span className="text-[10px] font-mono tracking-widest text-red-500 uppercase px-2 py-1 border border-red-900/50 bg-red-950/20">Active</span>
              </div>

              <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-x-12 gap-y-0 font-mono text-xs uppercase tracking-wide text-zinc-400">
                {[
                  ['Runtime Isolation',  'Docker API / Restricted Shell'],
                  ['Network I/O',        'Terminated (--network none)'],
                  ['Filesystem',         'Ephemeral Volume / Work Dir'],
                  ['Compute Limits',     'CPU: ulimit | RAM: 512MB'],
                  ['Command Allowlist',  'python3, git, grep, ls…'],
                  ['Timeout',            '30s per command'],
                ].map(([label, value], i) => (
                  <div key={i} className="flex justify-between items-center py-4 border-b border-zinc-900 gap-4">
                    <span className="text-zinc-600 font-bold shrink-0">{label}</span>
                    <span className={
                      value.includes('none') || value.includes('Terminated') ? 'text-red-400' :
                      value.includes('ulimit') || value.includes('512') ? 'text-amber-500' :
                      'text-zinc-300'
                    }>{value}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Security deep-dive */}
      <section id="security" className="py-32 relative z-20">
        <div className="max-w-7xl mx-auto px-6">
          <div className="grid lg:grid-cols-2 gap-20 items-center">
            <div className="order-2 lg:order-1 relative">
              <div className="absolute -inset-px bg-gradient-to-b from-amber-500/20 to-transparent opacity-50 pointer-events-none" />
              <div className="relative bg-[#050505] border border-zinc-800 p-10 shadow-2xl">
                <div className="absolute top-0 left-0 w-2 h-2 border-t-2 border-l-2 border-amber-500" />
                <div className="absolute top-0 right-0 w-2 h-2 border-t-2 border-r-2 border-amber-500" />
                <div className="absolute bottom-0 left-0 w-2 h-2 border-b-2 border-l-2 border-amber-500" />
                <div className="absolute bottom-0 right-0 w-2 h-2 border-b-2 border-r-2 border-amber-500" />

                <div className="flex items-center justify-between border-b border-zinc-800 pb-6 mb-8">
                  <h3 className="text-sm font-mono font-bold tracking-widest uppercase text-zinc-300 flex items-center">
                    <Lock className="w-4 h-4 mr-3 text-amber-500" />
                    Perimeter Defenses
                  </h3>
                  <span className="text-[10px] font-mono tracking-widest text-red-500 uppercase px-2 py-1 border border-red-900/50 bg-red-950/20">Active</span>
                </div>

                <div className="space-y-6 font-mono text-xs uppercase tracking-wide text-zinc-400">
                  {[
                    ['Runtime Isolation',  'Docker API / Restricted Shell'],
                    ['Network I/O',        'Terminated (--network none)'],
                    ['Filesystem',         'Ephemeral Volume / Work Dir'],
                    ['Compute Limits',     'CPU: ulimit | RAM: 512MB'],
                    ['Command Allowlist',  'python3, git, grep, ls…'],
                    ['Timeout',            '30s per command'],
                  ].map(([label, value], i) => (
                    <div key={i} className={`flex flex-col sm:flex-row sm:justify-between pb-4 gap-2 ${i < 5 ? 'border-b border-zinc-900' : ''}`}>
                      <span className="text-zinc-600 font-bold">{label}</span>
                      <span className={
                        value.includes('none') || value.includes('Terminated') ? 'text-red-400' :
                        value.includes('ulimit') || value.includes('512') ? 'text-amber-500' :
                        'text-zinc-300'
                      }>{value}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            <div className="order-1 lg:order-2 space-y-10">
              <div>
                <span className="text-amber-500 text-sm font-mono font-bold tracking-widest uppercase mb-4 block">Containment Protocol</span>
                <h2 className="text-4xl md:text-5xl font-black uppercase tracking-tighter text-white leading-tight">Execute Code.<br />Without Risk.</h2>
              </div>
              <div className="space-y-6 text-sm font-mono text-zinc-500 leading-relaxed">
                <p>Autonomous agents write and execute scripts to solve problems. Without a physical barrier, a rogue script could overwrite host files or expose environment variables.</p>
                <p>AlphaLoop's sandbox intercepts every command, routing it to an allowlisted, resource-capped environment — or an air-gapped Docker container when you need full isolation.</p>
              </div>
              <ul className="space-y-5 text-sm font-mono tracking-wide text-zinc-300">
                {[
                  'Command allowlist blocks rm -rf, sudo, eval, and 10+ dangerous patterns.',
                  'Auto-destructing Docker containers post-execution.',
                  'Human-in-the-loop overrides for high-risk tool calls.',
                ].map((item, i) => (
                  <li key={i} className="flex items-start">
                    <ShieldCheck className="w-5 h-5 text-amber-500 mr-4 shrink-0" />
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      </section>

      {/* Use Cases */}
      <section className="py-32 bg-[#020202] border-t border-zinc-900 relative z-20">
        <div className="max-w-7xl mx-auto px-6">
          <h2 className="text-3xl md:text-4xl font-black uppercase tracking-tighter text-white mb-16 text-center">Operational Scenarios</h2>
          <div className="grid md:grid-cols-3 gap-6">
            {[
              { Icon: Code2,     title: 'Legacy Migration',  desc: 'Assign AlphaLoop to an outdated codebase. It migrates syntax, generates unit tests, and patches errors iteratively until the build is green.' },
              { Icon: Database,  title: 'Data Synthesis',    desc: 'Ingest a directory of 500 unstructured PDFs. The agent extracts metrics, sanitizes inputs, and outputs a structured SQL payload — fully offline.' },
              { Icon: Terminal,  title: 'Security Auditing', desc: 'Execute continuous penetration testing routines against a local staging app. Identifies CVEs, drafts patches, and compiles incident logs.' },
            ].map(({ Icon, title, desc }) => (
              <div key={title} className="p-10 bg-[#050505] border border-zinc-800 hover:border-zinc-600 transition-colors">
                <Icon className="w-6 h-6 text-zinc-100 mb-8" />
                <h4 className="text-sm font-mono font-bold tracking-widest uppercase text-white mb-4">{title}</h4>
                <p className="text-sm font-mono text-zinc-500 leading-relaxed">{desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Quick Start */}
      <section className="py-32 border-t border-zinc-900 relative z-20">
        <div className="max-w-4xl mx-auto px-6">
          <h2 className="text-3xl md:text-4xl font-black uppercase tracking-tighter text-white mb-4 text-center">Quick Start</h2>
          <p className="text-sm font-mono text-zinc-500 mb-12 text-center">Setup time: ~60 seconds. Requires Python 3.12+ and Ollama.</p>
          <div className="bg-[#050505] border border-zinc-800 p-8 font-mono text-sm space-y-3">
            {[
              ['#', 'Clone and enter the project', 'text-zinc-600'],
              ['git clone', 'https://github.com/MarkCodering/AlphaLoop && cd AlphaLoop', 'text-zinc-300'],
              ['#', 'Install Python dependencies', 'text-zinc-600'],
              ['uv sync', '', 'text-zinc-300'],
              ['#', 'Pull the model', 'text-zinc-600'],
              ['ollama pull', 'lfm2.5-thinking:1.2b', 'text-amber-400'],
              ['#', 'Launch the TUI', 'text-zinc-600'],
              ['./run.sh', 'tui', 'text-emerald-400'],
            ].map(([cmd, arg, cls], i) => (
              <div key={i} className={`${cls}`}>
                {cmd === '#' ? (
                  <span className="text-zinc-600"># {arg}</span>
                ) : (
                  <span><span className="text-zinc-100">{cmd}</span> {arg && <span className={cls}>{arg}</span>}</span>
                )}
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="py-40 relative z-20 border-t border-zinc-900 overflow-hidden">
        <div className="absolute inset-0 bg-black" />
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] bg-zinc-900/40 blur-[150px] pointer-events-none" />
        <div className="max-w-3xl mx-auto px-6 text-center relative z-10">
          <h2 className="text-4xl md:text-6xl font-black uppercase tracking-tighter text-white mb-6">Initialize Run</h2>
          <p className="text-sm font-mono text-zinc-500 mb-12">Open source. MIT licensed. Runs entirely on your hardware.</p>
          <div className="flex flex-col sm:flex-row justify-center gap-6">
            <a href={REPO_URL} className="inline-flex items-center justify-center px-8 py-4 text-sm font-mono font-bold tracking-widest uppercase text-black bg-white hover:bg-zinc-200 transition-all">
              <Github className="w-5 h-5 mr-3" />
              Source Code
            </a>
            <button className="inline-flex items-center justify-center px-8 py-4 text-sm font-mono font-bold tracking-widest uppercase text-zinc-300 bg-[#050505] border border-zinc-700 hover:border-zinc-500 transition-all">
              <Terminal className="w-5 h-5 mr-3" />
              ./run.sh tui
            </button>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="bg-black py-12 border-t border-zinc-900 relative z-20">
        <div className="max-w-7xl mx-auto px-6 flex flex-col md:flex-row justify-between items-center gap-8">
          <div className="flex items-center space-x-3">
            <RefreshCw className="w-5 h-5 text-zinc-500" />
            <span className="text-sm font-mono font-bold tracking-widest uppercase text-zinc-400">AlphaLoop</span>
          </div>
          <div className="flex flex-wrap justify-center gap-8 text-xs font-mono font-bold tracking-widest uppercase text-zinc-600">
            <a href="/docs/" className="hover:text-zinc-300 transition-colors">Docs</a>
            <a href={REPO_URL} className="hover:text-zinc-300 transition-colors">GitHub</a>
            <a href={REPO_URL} className="hover:text-zinc-300 transition-colors">Repository</a>
          </div>
          <p className="text-zinc-700 text-xs font-mono uppercase tracking-widest">© 2026 // MIT License</p>
        </div>
      </footer>
    </div>
  );
}
