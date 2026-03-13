"""Sandbox backends for safe agent shell execution.

Two sandbox levels are available:

``RestrictedLocalSandbox``
    Runs commands on the host using a command allowlist + per-command
    timeouts + resource limits.  Zero extra dependencies.

``DockerSandbox``
    Wraps every command inside an ephemeral ``docker exec`` call against a
    long-lived container.  Requires Docker and the ``docker`` CLI.

Typical usage::

    from alphaloop.sandbox import build_sandbox
    backend = build_sandbox(use_docker=False, work_dir="/tmp/agent-workspace")

Both classes implement ``deepagents.backends.protocol.SandboxBackendProtocol``
via ``BaseSandbox``, so they drop straight into ``create_deep_agent(backend=...)``.
"""

from __future__ import annotations

import resource
import shlex
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from deepagents.backends.sandbox import BaseSandbox
from deepagents.backends.protocol import (
    ExecuteResponse,
    FileDownloadResponse,
    FileInfo,
    FileUploadResponse,
)

from alphaloop.logger import get_logger

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Command allowlist — only these prefixes may run in the restricted sandbox
# ---------------------------------------------------------------------------
_ALLOWED_PREFIXES: frozenset[str] = frozenset(
    {
        # Python & package mgmt
        "python3",
        "python",
        "pip",
        "uv",
        # Filesystem inspection
        "ls",
        "cat",
        "head",
        "tail",
        "find",
        "grep",
        "rg",
        "wc",
        "diff",
        "stat",
        "file",
        "tree",
        # Text processing
        "awk",
        "sed",
        "sort",
        "uniq",
        "cut",
        "tr",
        "echo",
        "printf",
        # Version checks / help
        "git",
        "curl",
        "wget",
        "jq",
        "yq",
        # Build / test
        "make",
        "pytest",
        "npm",
        "node",
    }
)

# Hard-blocked substrings — refuse any command that contains these
_BLOCKED_PATTERNS: tuple[str, ...] = (
    "rm -rf",
    "rm -r",
    "sudo",
    "su ",
    "chmod 777",
    "> /dev/",
    "dd if",
    "mkfs",
    "fdisk",
    "parted",
    ":(){:|:&};:",  # fork bomb
    "$()",
    "`",  # command substitution — could smuggle blocked commands
    "eval ",
    "exec ",
    "kill ",
    "pkill",
    "killall",
    "/etc/passwd",
    "/etc/shadow",
    "~/.ssh",
    "~/.aws",
    "curl.*|.*sh",
    "wget.*|.*sh",
)

_DEFAULT_TIMEOUT = 30  # seconds
_DEFAULT_MAX_OUTPUT = 100_000  # bytes


def _is_allowed(command: str) -> tuple[bool, str]:
    """Return (allowed, reason) for a command string."""
    stripped = command.strip()

    # Check hard-blocked patterns first
    for pattern in _BLOCKED_PATTERNS:
        if pattern in stripped:
            return False, f"blocked pattern: {pattern!r}"

    # Extract the leading executable name
    try:
        tokens = shlex.split(stripped)
    except ValueError:
        return False, "unparseable command"

    if not tokens:
        return False, "empty command"

    exe = Path(tokens[0]).name  # strip any path prefix
    if exe in _ALLOWED_PREFIXES:
        return True, ""

    # Allow python3 -c "..." style wrapped commands (already parsed above)
    if exe in ("python3", "python"):
        return True, ""

    return False, f"executable {exe!r} not in allowlist"


def _set_resource_limits() -> None:
    """Lower resource limits for child processes (POSIX only)."""
    try:
        # Max CPU seconds
        resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
        # Max file size: 50 MB
        resource.setrlimit(resource.RLIMIT_FSIZE, (50 * 1024 * 1024, 50 * 1024 * 1024))
        # Max open files
        resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    except (ValueError, resource.error):
        pass  # not all limits are available on every platform


# ---------------------------------------------------------------------------
# Restricted local sandbox
# ---------------------------------------------------------------------------


class RestrictedLocalSandbox(BaseSandbox):
    """Run agent commands on the local host with an allowlist and resource limits.

    Args:
        work_dir: Working directory for all commands. Created if it doesn't exist.
        timeout: Per-command timeout in seconds.
        max_output: Truncate combined stdout/stderr to this many bytes.
    """

    def __init__(
        self,
        work_dir: str | Path | None = None,
        timeout: int = _DEFAULT_TIMEOUT,
        max_output: int = _DEFAULT_MAX_OUTPUT,
    ) -> None:
        self._work_dir = Path(work_dir or tempfile.mkdtemp(prefix="alphaloop-"))
        self._work_dir.mkdir(parents=True, exist_ok=True)
        self._timeout = timeout
        self._max_output = max_output
        self._id = str(uuid.uuid4())[:8]
        logger.info("RestrictedLocalSandbox ready: work_dir=%s", self._work_dir)

    @property
    def id(self) -> str:
        return f"restricted-local-{self._id}"

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        allowed, reason = _is_allowed(command)
        if not allowed:
            return ExecuteResponse(
                output=f"[sandbox] Command blocked: {reason}\nCommand: {command[:200]}",
                exit_code=1,
                truncated=False,
            )

        effective_timeout = timeout or self._timeout
        try:
            result = subprocess.run(  # noqa: S603
                command,
                shell=True,  # noqa: S602
                capture_output=True,
                text=True,
                cwd=self._work_dir,
                timeout=effective_timeout,
                preexec_fn=_set_resource_limits,
            )
            combined = result.stdout + result.stderr
            truncated = len(combined.encode()) > self._max_output
            if truncated:
                combined = combined[: self._max_output].decode(errors="replace") if isinstance(combined, bytes) else combined[: self._max_output]
                combined += "\n[output truncated]"
            return ExecuteResponse(
                output=combined,
                exit_code=result.returncode,
                truncated=truncated,
            )
        except subprocess.TimeoutExpired:
            return ExecuteResponse(
                output=f"[sandbox] Command timed out after {effective_timeout}s",
                exit_code=124,
                truncated=False,
            )
        except Exception as exc:
            return ExecuteResponse(
                output=f"[sandbox] Error: {exc}",
                exit_code=1,
                truncated=False,
            )

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        results: list[FileUploadResponse] = []
        for rel_path, content in files:
            dest = self._work_dir / rel_path
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(content)
                results.append(FileUploadResponse(path=str(dest)))
            except Exception as exc:
                results.append(FileUploadResponse(path=rel_path, error=str(exc)))
        return results

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        results: list[FileDownloadResponse] = []
        for p in paths:
            full = self._work_dir / p
            try:
                results.append(FileDownloadResponse(path=p, content=full.read_bytes()))
            except Exception as exc:
                results.append(FileDownloadResponse(path=p, content=b"", error=str(exc)))
        return results

    def ls_info(self, path: str) -> list[FileInfo]:
        """List directory contents relative to work_dir."""
        target = self._work_dir / path.lstrip("/")
        if not target.exists():
            return []
        return [
            FileInfo(path=str(entry.relative_to(self._work_dir)), is_dir=entry.is_dir())
            for entry in target.iterdir()
        ]


# ---------------------------------------------------------------------------
# Docker sandbox
# ---------------------------------------------------------------------------

_DOCKER_IMAGE = "python:3.12-slim"
_DOCKER_CONTAINER_PREFIX = "alphaloop-sandbox-"


class DockerSandbox(BaseSandbox):
    """Run agent commands inside an isolated Docker container.

    The container is started once and reused across calls.  It is removed
    on :meth:`close`.

    Args:
        image: Docker image to use.
        work_dir: Host directory mounted into the container at ``/workspace``.
        timeout: Per-command timeout in seconds.
        max_output: Truncate combined output to this many bytes.
        network: Docker network mode (``"none"`` disables network access).
    """

    def __init__(
        self,
        image: str = _DOCKER_IMAGE,
        work_dir: str | Path | None = None,
        timeout: int = _DEFAULT_TIMEOUT,
        max_output: int = _DEFAULT_MAX_OUTPUT,
        network: str = "none",
    ) -> None:
        self._image = image
        self._work_dir = Path(work_dir or tempfile.mkdtemp(prefix="alphaloop-docker-"))
        self._work_dir.mkdir(parents=True, exist_ok=True)
        self._timeout = timeout
        self._max_output = max_output
        self._network = network
        self._container_id: str | None = None
        self._id = str(uuid.uuid4())[:8]

    @property
    def id(self) -> str:
        return f"docker-{self._id}"

    def _ensure_container(self) -> str:
        """Start the container if it isn't already running."""
        if self._container_id:
            return self._container_id

        cmd = [
            "docker", "run",
            "--detach",
            "--rm",
            "--network", self._network,
            "--memory", "512m",
            "--cpus", "1.0",
            "--pids-limit", "64",
            "--security-opt", "no-new-privileges",
            "--read-only",
            "--tmpfs", "/tmp:size=128m",
            "--tmpfs", "/workspace:size=256m",
            "--workdir", "/workspace",
            self._image,
            "sleep", "infinity",
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=True)  # noqa: S603
            self._container_id = result.stdout.strip()
            logger.info("DockerSandbox container started: %s", self._container_id[:12])

            # Upload initial work_dir contents
            files_to_upload = [
                (str(f.relative_to(self._work_dir)), f.read_bytes())
                for f in self._work_dir.rglob("*")
                if f.is_file()
            ]
            if files_to_upload:
                self._copy_to_container(files_to_upload)

            return self._container_id
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
            msg = f"Failed to start Docker container: {exc}"
            raise RuntimeError(msg) from exc

    def _copy_to_container(self, files: list[tuple[str, bytes]]) -> None:
        """Copy files into the container's /workspace."""
        if not self._container_id:
            return
        with tempfile.TemporaryDirectory() as staging:
            for rel, content in files:
                dest = Path(staging) / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(content)
            subprocess.run(  # noqa: S603
                ["docker", "cp", f"{staging}/.", f"{self._container_id}:/workspace/"],
                capture_output=True,
                timeout=30,
                check=False,
            )

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        try:
            cid = self._ensure_container()
        except RuntimeError as exc:
            return ExecuteResponse(output=str(exc), exit_code=1, truncated=False)

        effective_timeout = timeout or self._timeout
        exec_cmd = ["docker", "exec", cid, "sh", "-c", command]
        try:
            result = subprocess.run(  # noqa: S603
                exec_cmd,
                capture_output=True,
                text=True,
                timeout=effective_timeout,
                check=False,
            )
            combined = result.stdout + result.stderr
            truncated = len(combined.encode()) > self._max_output
            if truncated:
                combined = combined[: self._max_output]
                combined += "\n[output truncated]"
            return ExecuteResponse(
                output=combined,
                exit_code=result.returncode,
                truncated=truncated,
            )
        except subprocess.TimeoutExpired:
            return ExecuteResponse(
                output=f"[docker-sandbox] Command timed out after {effective_timeout}s",
                exit_code=124,
                truncated=False,
            )
        except Exception as exc:
            return ExecuteResponse(output=f"[docker-sandbox] Error: {exc}", exit_code=1, truncated=False)

    def close(self) -> None:
        """Stop and remove the sandbox container."""
        if self._container_id:
            subprocess.run(  # noqa: S603
                ["docker", "rm", "-f", self._container_id],
                capture_output=True,
                timeout=10,
                check=False,
            )
            logger.info("DockerSandbox container removed: %s", self._container_id[:12])
            self._container_id = None

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        results: list[FileUploadResponse] = []
        try:
            cid = self._ensure_container()
        except RuntimeError as exc:
            return [FileUploadResponse(path=p, error=str(exc)) for p, _ in files]

        for rel_path, content in files:
            dest_host = self._work_dir / rel_path
            try:
                dest_host.parent.mkdir(parents=True, exist_ok=True)
                dest_host.write_bytes(content)
                # Sync to container
                with tempfile.NamedTemporaryFile(delete=False) as tmp:
                    tmp.write(content)
                    tmp_path = tmp.name
                subprocess.run(  # noqa: S603
                    ["docker", "cp", tmp_path, f"{cid}:/workspace/{rel_path}"],
                    capture_output=True,
                    timeout=15,
                    check=False,
                )
                Path(tmp_path).unlink(missing_ok=True)
                results.append(FileUploadResponse(path=rel_path))
            except Exception as exc:
                results.append(FileUploadResponse(path=rel_path, error=str(exc)))
        return results

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        results: list[FileDownloadResponse] = []
        try:
            cid = self._ensure_container()
        except RuntimeError as exc:
            return [FileDownloadResponse(path=p, content=b"", error=str(exc)) for p in paths]

        for p in paths:
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                tmp_path = tmp.name
            try:
                subprocess.run(  # noqa: S603
                    ["docker", "cp", f"{cid}:/workspace/{p}", tmp_path],
                    capture_output=True,
                    timeout=15,
                    check=True,
                )
                results.append(FileDownloadResponse(path=p, content=Path(tmp_path).read_bytes()))
            except Exception as exc:
                results.append(FileDownloadResponse(path=p, content=b"", error=str(exc)))
            finally:
                Path(tmp_path).unlink(missing_ok=True)
        return results


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def build_sandbox(
    use_docker: bool = False,
    work_dir: str | Path | None = None,
    docker_image: str = _DOCKER_IMAGE,
    docker_network: str = "none",
    timeout: int = _DEFAULT_TIMEOUT,
) -> RestrictedLocalSandbox | DockerSandbox:
    """Create the appropriate sandbox backend.

    Args:
        use_docker: Use Docker isolation if True, restricted local shell if False.
        work_dir: Working directory for the sandbox.
        docker_image: Docker image (only used when ``use_docker=True``).
        docker_network: Docker network mode (only used when ``use_docker=True``).
        timeout: Per-command timeout in seconds.

    Returns:
        A ready-to-use sandbox backend.
    """
    if use_docker:
        return DockerSandbox(
            image=docker_image,
            work_dir=work_dir,
            timeout=timeout,
            network=docker_network,
        )
    return RestrictedLocalSandbox(work_dir=work_dir, timeout=timeout)
