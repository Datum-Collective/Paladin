"""Workspace path and file-transfer helpers."""

from __future__ import annotations

import posixpath
from pathlib import PurePosixPath


WORKSPACE_ROOT = PurePosixPath("/workspace")


def safe_relative_path(value: str) -> PurePosixPath:
    """Return a normalized path that cannot escape the sandbox workspace."""
    if not value or "\x00" in value:
        raise ValueError("workspace path is empty or invalid")
    raw_parts = value.split("/")
    if any(part in ("", ".", "..") for part in raw_parts):
        raise ValueError("workspace path must be a normalized relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise ValueError("workspace path must be a normalized relative path")
    normalized = PurePosixPath(posixpath.normpath(str(path)))
    if normalized == PurePosixPath(".") or ".." in normalized.parts:
        raise ValueError("workspace path escapes the workspace")
    return normalized


def container_path(value: str) -> str:
    return str(WORKSPACE_ROOT / safe_relative_path(value))
