"""Small, auditable boundary around the Docker CLI.

Commands are always passed as an argv list.  The host shell is never involved;
shell interpretation is limited to commands intentionally executed inside the
untrusted sandbox container.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import Mapping, Sequence


class DockerError(RuntimeError):
    """Raised when the Docker engine rejects an infrastructure operation."""


class DockerTimeout(TimeoutError):
    """Raised when a Docker operation exceeds its configured deadline."""


@dataclass(frozen=True)
class DockerResult:
    argv: tuple[str, ...]
    exit_code: int
    stdout: str
    stderr: str


class DockerClient:
    """Invoke Docker without a shell and return bounded, structured output."""

    def __init__(
        self,
        binary: str = "docker",
        *,
        host: str | None = None,
        max_output_bytes: int = 1_000_000,
    ) -> None:
        self.binary = binary
        self.host = host
        self.max_output_bytes = max_output_bytes

    def run(
        self,
        args: Sequence[str],
        *,
        input_bytes: bytes | None = None,
        timeout: float | None = None,
        check: bool = True,
        env: Mapping[str, str] | None = None,
    ) -> DockerResult:
        argv = (self.binary, *map(str, args))
        process_env = os.environ.copy()
        if self.host:
            process_env["DOCKER_HOST"] = self.host
        if env:
            process_env.update(env)
        try:
            completed = subprocess.run(
                argv,
                input=input_bytes,
                capture_output=True,
                timeout=timeout,
                check=False,
                env=process_env,
            )
        except subprocess.TimeoutExpired as exc:
            raise DockerTimeout(f"Docker command timed out after {timeout}s") from exc
        except OSError as exc:
            raise DockerError(f"Docker CLI is unavailable: {exc}") from exc

        stdout = self._decode(completed.stdout)
        stderr = self._decode(completed.stderr)
        result = DockerResult(argv, completed.returncode, stdout, stderr)
        if check and result.exit_code != 0:
            detail = stderr.strip() or stdout.strip() or "no diagnostic output"
            raise DockerError(f"Docker command failed ({result.exit_code}): {detail}")
        return result

    def _decode(self, value: bytes) -> str:
        clipped = value[: self.max_output_bytes]
        text = clipped.decode("utf-8", errors="replace")
        if len(value) > self.max_output_bytes:
            text += f"\n[output truncated after {self.max_output_bytes} bytes]"
        return text
