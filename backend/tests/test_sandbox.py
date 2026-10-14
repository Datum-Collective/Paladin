from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.services.sandbox.docker_client import DockerResult, DockerTimeout
from app.services.sandbox.manager import SandboxConfig, SandboxManager
from app.services.sandbox.workspace import container_path, safe_relative_path


@dataclass
class Call:
    args: list[str]
    input_bytes: bytes | None
    check: bool


class FakeDocker:
    def __init__(self, *, timeout_on_exec: bool = False):
        self.calls: list[Call] = []
        self.timeout_on_exec = timeout_on_exec

    def run(self, args, *, input_bytes=None, timeout=None, check=True, env=None):
        args = list(args)
        self.calls.append(Call(args, input_bytes, check))
        if self.timeout_on_exec and args[0] == "exec":
            raise DockerTimeout("timed out")
        stdout = "volume\n" if args[:2] == ["volume", "create"] else "container\n" if args[0] == "run" else ""
        return DockerResult(("docker", *args), 0, stdout, "")


def config() -> SandboxConfig:
    return SandboxConfig(image="sandbox:test", cpu_limit=0.5, memory_limit="256m", pids_limit=64)


def test_session_uses_security_controls_and_cleans_up():
    client = FakeDocker()
    manager = SandboxManager(client=client, config=config())
    with manager.session() as session:
        name = session.container_name
        volume = session.volume_name
        result = session.run("python -m pytest -q")
        assert result.ok

    run = next(call.args for call in client.calls if call.args[0] == "run")
    assert "--read-only" in run
    assert ["--network", "bridge"] == run[run.index("--network"):run.index("--network") + 2]
    assert ["--cap-drop", "ALL"] == run[run.index("--cap-drop"):run.index("--cap-drop") + 2]
    assert "no-new-privileges:true" in run
    assert ["--user", "10001:10001"] == run[run.index("--user"):run.index("--user") + 2]
    assert not any("docker.sock" in value for value in run)
    assert ["rm", "-f", name] in [call.args for call in client.calls]
    assert ["volume", "rm", "-f", volume] in [call.args for call in client.calls]


def test_timeout_destroys_container_and_returns_structured_result():
    client = FakeDocker(timeout_on_exec=True)
    session = SandboxManager(client=client, config=config()).session().create()
    result = session.run("sleep 999")
    assert result.timed_out and result.exit_code == 124
    assert session.destroyed


def test_run_repository_clones_runs_commands_and_cleans_up():
    client = FakeDocker()
    result = SandboxManager(client=client, config=config()).run_repository(
        "https://github.com/example/repo.git",
        analysis_commands=["python -m compileall ."],
        test_commands=["python -m pytest -q"],
    )
    assert result.ok and result.cleaned_up
    exec_commands = [call.args[-1] for call in client.calls if call.args[0] == "exec" and call.args[-2] == "-lc"]
    assert "core.hooksPath=/dev/null" in exec_commands[0]
    assert exec_commands[1:] == ["python -m compileall .", "python -m pytest -q"]
    clone_call = next(call.args for call in client.calls if call.args[-1] == exec_commands[0])
    assert clone_call[clone_call.index("--workdir") + 1] == "/workspace"


@pytest.mark.parametrize("path", ["../secret", "/etc/passwd", "a/../../b", "", "./file"])
def test_workspace_paths_cannot_escape(path):
    with pytest.raises(ValueError):
        safe_relative_path(path)


def test_workspace_path_is_rooted():
    assert container_path("repo/src/app.py") == "/workspace/repo/src/app.py"
