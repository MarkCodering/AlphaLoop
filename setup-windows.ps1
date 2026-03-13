Param(
    [ValidateSet("ollama", "openai", "anthropic", "gemini", "ollama_cloud")]
    [string]$Provider = "ollama",
    [string]$Model = "lfm2.5-thinking:1.2b",
    [string]$ThreadId = "alphaloop-main",
    [switch]$SkipModelPull,
    [switch]$SkipUvSync
)

$ErrorActionPreference = "Stop"

function Write-Info {
    Param([string]$Message)
    Write-Host "[INFO] $Message" -ForegroundColor Cyan
}

function Write-Warn {
    Param([string]$Message)
    Write-Host "[WARN] $Message" -ForegroundColor Yellow
}

function Write-Step {
    Param([string]$Message)
    Write-Host "\n==> $Message" -ForegroundColor Green
}

function Test-Command {
    Param([string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Require-Python312 {
    if (-not (Test-Command "python")) {
        throw "Python is not installed. Install Python 3.12+ from https://www.python.org/downloads/windows/"
    }

    $versionRaw = python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    $parts = $versionRaw.Trim().Split('.')
    $major = [int]$parts[0]
    $minor = [int]$parts[1]

    if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 12)) {
        throw "Python 3.12+ is required. Found: $versionRaw"
    }

    Write-Info "Python version OK: $versionRaw"
}

function Ensure-Uv {
    if (Test-Command "uv") {
        Write-Info "uv is already installed"
        return
    }

    Write-Step "Installing uv"
    powershell -ExecutionPolicy Bypass -c "irm https://astral.sh/uv/install.ps1 | iex"

    if (-not (Test-Command "uv")) {
        Write-Warn "uv was installed, but is not in this shell's PATH yet."
        Write-Warn "Restart PowerShell, then run this script again."
        throw "uv not available in PATH"
    }

    Write-Info "uv installed successfully"
}

function Ensure-Ollama {
    if (Test-Command "ollama") {
        Write-Info "Ollama is already installed"
        return
    }

    Write-Warn "Ollama is not installed."
    Write-Warn "Install from https://ollama.com/download/windows and rerun this script."
    throw "Ollama missing"
}

function Pull-OllamaModel {
    Param([string]$ModelName)

    if ($SkipModelPull) {
        Write-Info "Skipping model pull as requested"
        return
    }

    Write-Step "Pulling Ollama model: $ModelName"
    ollama pull $ModelName
}

Write-Step "AlphaLoop Windows Setup"

Set-Location -Path $PSScriptRoot

Require-Python312
Ensure-Uv

if (-not $SkipUvSync) {
    Write-Step "Installing Python dependencies"
    uv sync
} else {
    Write-Info "Skipping uv sync as requested"
}

if ($Provider -eq "ollama") {
    Ensure-Ollama
    Pull-OllamaModel -ModelName $Model
}

Write-Step "Exporting environment variables for this PowerShell session"
$env:ALPHALOOP_PROVIDER = $Provider
$env:ALPHALOOP_MODEL = $Model
$env:ALPHALOOP_THREAD_ID = $ThreadId

Write-Host ""
Write-Host "Setup complete." -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1) Start interactive TUI:" -ForegroundColor Cyan
Write-Host "     uv run python -m main tui" -ForegroundColor White
Write-Host ""
Write-Host "  2) Start headless mode:" -ForegroundColor Cyan
Write-Host "     uv run python -m main start" -ForegroundColor White
Write-Host ""
Write-Host "Current session settings:" -ForegroundColor Cyan
Write-Host "  ALPHALOOP_PROVIDER=$($env:ALPHALOOP_PROVIDER)"
Write-Host "  ALPHALOOP_MODEL=$($env:ALPHALOOP_MODEL)"
Write-Host "  ALPHALOOP_THREAD_ID=$($env:ALPHALOOP_THREAD_ID)"
