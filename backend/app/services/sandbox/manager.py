"""Lifecycle manager for isolated repository execution containers."""

from __future__ import annotations

import os
import secrets
import shlex
import time
from dataclasses import dataclass
from typing import Iterable

from .cleanup import CREATED_LABEL, MANAGED_LABEL, cleanup_stale
from .docker_client import DockerClient, DockerError
from .executor import CommandResult, SandboxExecutor, SandboxRunResult
from .workspace import container_path


@dataclass(frozen=True)
class SandboxConfig:
    image: str = "datum-sandbox:latest"
    cpu_limit: float = 1.0
    memory_limit: str = "1g"
    pids_limit: int = 256
    command_timeout_seconds: float = 300
    clone_timeout_seconds: float = 120
    tmpfs_size: str = "256m"
    user: str = "10001:10001"
    network: str = "bridge"

    @classmethod
    def from_env(cls) -> "SandboxConfig":
        return cls(
            image=os.getenv("SANDBOX_IMAGE", cls.image),
            cpu_limit=float(os.getenv("SANDBOX_CPUS", str(cls.cpu_limit))),
            memory_limit=os.getenv("SANDBOX_MEMORY", cls.memory_limit),
            pids_limit=int(os.getenv("SANDBOX_PIDS_LIMIT", str(cls.pids_limit))),
            command_timeout_seconds=float(os.getenv("SANDBOX_TIMEOUT", str(cls.command_timeout_seconds))),
            clone_timeout_seconds=float(os.getenv("SANDBOX_CLONE_TIMEOUT", str(cls.clone_timeout_seconds))),
            tmpfs_size=os.getenv("SANDBOX_TMPFS_SIZE", cls.tmpfs_size),
            user=os.getenv("SANDBOX_USER", cls.user),
            network=os.getenv("SANDBOX_NETWORK", cls.network),
        )


class SandboxSession:
    def __init__(self, client: DockerClient, config: SandboxConfig) -> None:
        token = secrets.token_hex(8)
        self.client = client
        self.config = config
        self.sandbox_id = token
        self.container_name = f"datum-sandbox-{token}"
        self.volume_name = f"datum-sandbox-work-{token}"
        self.created = False
        self.destroyed = False
        self.executor = SandboxExecutor(client, self)

    def __enter__(self) -> "SandboxSession":
        return self.create()

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.destroy()

    def create(self) -> "SandboxSession":
        if self.created:
            return self
        created_at = str(time.time())
        labels = ["--label", MANAGED_LABEL, "--label", f"{CREATED_LABEL}={created_at}"]
        self.client.run(["volume", "create", *labels, self.volume_name])
        try:
            self.client.run([
                "run", "-d",
                "--name", self.container_name,
                *labels,
                "--read-only",
                "--tmpfs", f"/tmp:rw,nosuid,nodev,noexec,size={self.config.tmpfs_size}",
                "--mount", f"type=volume,src={self.volume_name},dst=/workspace",
                "--network", self.config.network,
                "--cpus", str(self.config.cpu_limit),
                "--memory", self.config.memory_limit,
                "--memory-swap", self.config.memory_limit,
                "--pids-limit", str(self.config.pids_limit),
                "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges:true",
                "--user", self.config.user,
                "--workdir", "/workspace",
                self.config.image,
            ])
        except Exception:
            self.client.run(["volume", "rm", "-f", self.volume_name], check=False)
            raise
        self.created = True
        return self

    def clone(self, repository_url: str, *, branch: str | None = None) -> CommandResult:
        if not repository_url.startswith(("https://", "http://")):
            raise ValueError("repository URL must use HTTP or HTTPS")
        branch_args = f" --branch {shlex.quote(branch)}" if branch else ""
        command = (
            "git -c core.hooksPath=/dev/null -c core.symlinks=false "
            "-c protocol.file.allow=never clone --depth 1 --no-tags --single-branch "
            f"--no-recurse-submodules{branch_args} {shlex.quote(repository_url)} /workspace/repo"
        )
        return self.executor.run(
            command,
            timeout=self.config.clone_timeout_seconds,
            workdir="/workspace",
        )

    def run(self, command: str, *, timeout: float | None = None) -> CommandResult:
        return self.executor.run(command, timeout=timeout)

    def read_file(self, relative_path: str, *, max_bytes: int = 1_000_000) -> bytes:
        path = container_path(f"repo/{relative_path}")
        script = (
            "import pathlib,sys; p=pathlib.Path(sys.argv[1]); n=int(sys.argv[2]); "
            "data=p.read_bytes(); "
            "sys.exit('file exceeds extraction limit') if len(data)>n else sys.stdout.buffer.write(data)"
        )
        result = self.client.run([
            "exec", "--user", self.config.user, self.container_name,
            "python", "-c", script, path, str(max_bytes),
        ])
        return result.stdout.encode("utf-8")

    def write_file(self, relative_path: str, content: bytes) -> None:
        path = container_path(f"repo/{relative_path}")
        script = (
            "import pathlib,sys; p=pathlib.Path(sys.argv[1]); "
            "p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(sys.stdin.buffer.read())"
        )
        self.client.run([
            "exec", "-i", "--user", self.config.user, self.container_name,
            "python", "-c", script, path,
        ], input_bytes=content)

    def destroy(self) -> None:
        if self.destroyed:
            return
        self.client.run(["rm", "-f", self.container_name], check=False)
        self.client.run(["volume", "rm", "-f", self.volume_name], check=False)
        self.destroyed = True


class SandboxManager:
    """Public entry point for future scanner, fixer, test, and AI workflows."""

    def __init__(self, client: DockerClient | None = None, config: SandboxConfig | None = None) -> None:
        self.client = client or DockerClient(host=os.getenv("SANDBOX_DOCKER_HOST"))
        self.config = config or SandboxConfig.from_env()

    def session(self) -> SandboxSession:
        return SandboxSession(self.client, self.config)

    def cleanup_stale(self, *, older_than_seconds: int = 3600) -> dict[str, int]:
        return cleanup_stale(self.client, older_than_seconds=older_than_seconds)

    def run_repository(
        self,
        repository_url: str,
        *,
        analysis_commands: Iterable[str] = (),
        test_commands: Iterable[str] = (),
        branch: str | None = None,
    ) -> SandboxRunResult:
        session = self.session()
        result: SandboxRunResult | None = None
        try:
            session.create()
            clone = session.clone(repository_url, branch=branch)
            result = SandboxRunResult(session.sandbox_id, clone)
            if not clone.ok:
                return result
            result.analysis = session.executor.run_many(analysis_commands)
            if all(item.ok for item in result.analysis):
                result.tests = session.executor.run_many(test_commands)
            return result
        finally:
            session.destroy()
            if result is not None:
                result.cleaned_up = True
