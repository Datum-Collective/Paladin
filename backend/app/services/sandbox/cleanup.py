"""Best-effort cleanup of abandoned sandbox resources."""

from __future__ import annotations

import time

from .docker_client import DockerClient


MANAGED_LABEL = "com.datum.sandbox.managed=true"
CREATED_LABEL = "com.datum.sandbox.created_at"


def cleanup_stale(client: DockerClient, *, older_than_seconds: int = 3600) -> dict[str, int]:
    """Remove labelled containers and volumes older than the configured age."""
    cutoff = time.time() - older_than_seconds
    removed = {"containers": 0, "volumes": 0}
    containers = client.run(
        ["ps", "-aq", "--filter", f"label={MANAGED_LABEL}"], check=False
    ).stdout.splitlines()
    for container in filter(None, containers):
        inspected = client.run(
            ["inspect", "-f", f"{{{{ index .Config.Labels \"{CREATED_LABEL}\" }}}}", container],
            check=False,
        )
        try:
            stale = float(inspected.stdout.strip()) < cutoff
        except ValueError:
            stale = True
        if stale:
            client.run(["rm", "-f", container], check=False)
            removed["containers"] += 1

    volumes = client.run(
        ["volume", "ls", "-q", "--filter", f"label={MANAGED_LABEL}"], check=False
    ).stdout.splitlines()
    for volume in filter(None, volumes):
        inspected = client.run(
            ["volume", "inspect", "-f", f"{{{{ index .Labels \"{CREATED_LABEL}\" }}}}", volume],
            check=False,
        )
        try:
            stale = float(inspected.stdout.strip()) < cutoff
        except ValueError:
            stale = True
        if stale:
            client.run(["volume", "rm", "-f", volume], check=False)
            removed["volumes"] += 1
    return removed
