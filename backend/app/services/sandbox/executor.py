"""Command execution and structured sandbox results."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Iterable

from .docker_client import DockerClient, DockerTimeout

if TYPE_CHECKING:
    from .manager import SandboxSession


@dataclass(frozen=True)
class CommandResult:
    command: str
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


@dataclass
class SandboxRunResult:
    sandbox_id: str
    clone: CommandResult
    analysis: list[CommandResult] = field(default_factory=list)
    tests: list[CommandResult] = field(default_factory=list)
    cleaned_up: bool = False

    @property
    def ok(self) -> bool:
        return self.clone.ok and all(r.ok for r in self.analysis + self.tests)


class SandboxExecutor:
    def __init__(self, client: DockerClient, session: "SandboxSession") -> None:
        self.client = client
        self.session = session

    def run(
        self,
        command: str,
        *,
        timeout: float | None = None,
        workdir: str = "/workspace/repo",
    ) -> CommandResult:
        if not command or "\x00" in command:
            raise ValueError("command is empty or invalid")
        limit = timeout if timeout is not None else self.session.config.command_timeout_seconds
        args = [
            "exec",
            "--user",
            self.session.config.user,
            "--workdir",
            workdir,
            self.session.container_name,
            "/bin/sh",
            "-lc",
            command,
        ]
        try:
            result = self.client.run(args, timeout=limit, check=False)
        except DockerTimeout:
            self.session.destroy()
            return CommandResult(command, 124, "", f"execution timed out after {limit}s", True)
        return CommandResult(command, result.exit_code, result.stdout, result.stderr)

    def run_many(self, commands: Iterable[str]) -> list[CommandResult]:
        results = []
        for command in commands:
            result = self.run(command)
            results.append(result)
            if not result.ok:
                break
        return results
