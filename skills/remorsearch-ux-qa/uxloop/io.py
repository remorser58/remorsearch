"""Small, strict JSON and local-file primitives. No network or command execution."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


class ContractError(ValueError):
    """Invalid input, stale checkpoint, or unsafe local path."""


class GateStop(Exception):
    def __init__(self, status: str, reason: str):
        super().__init__(reason)
        self.status = status
        self.reason = reason


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def timestamp(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError("timezone required")
        return result
    except (TypeError, ValueError, AttributeError) as exc:
        raise ContractError(f"Invalid timezone-aware timestamp: {value!r}") from exc


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def parse_json(raw: str | bytes) -> Any:
    def bad_constant(value: str) -> None:
        raise ContractError(f"Non-finite JSON number: {value}")
    try:
        return json.loads(raw, object_pairs_hook=_pairs, parse_constant=bad_constant)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ContractError(f"Invalid JSON: {exc}") from exc


def load_json(path: Path) -> Any:
    if path.stat().st_size > 8 * 1024 * 1024:
        raise ContractError("JSON input exceeds 8 MiB")
    return parse_json(path.read_bytes())


def safe_relative(value: str) -> str:
    # Restrict patch targets and artifact names to portable, reviewable names.
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_./+-]+", value):
        raise ContractError(f"Unsafe/nonportable relative path: {value!r}")
    p = PurePosixPath(value)
    denied = {".git", ".ux-loop", "node_modules", ".venv", "venv", "__pycache__"}
    if p.is_absolute() or any(x in {".", "..", ""} | denied for x in value.split("/")):
        raise ContractError(f"Unsafe relative path: {value!r}")
    return value


def within(root: Path, relative: str) -> Path:
    safe_relative(relative)
    root = root.resolve()
    current = root
    for part in PurePosixPath(relative).parts:
        current = current / part
        if current.is_symlink():
            raise ContractError(f"Symlink is not allowed: {relative}")
    if not current.resolve().is_relative_to(root):
        raise ContractError(f"Path escapes root: {relative}")
    return current


def read_artifact(root: Path, record: dict[str, Any]) -> bytes:
    path = within(root, record["path"])
    if not path.is_file():
        raise GateStop("blocked", f"Missing artifact {record['id']}: {record['path']}")
    if path.stat().st_size > 32 * 1024 * 1024:
        raise GateStop("blocked", f"Artifact exceeds 32 MiB: {record['id']}")
    raw = path.read_bytes()
    if not raw or sha(raw) != record["sha256"]:
        raise GateStop("unknown", f"Artifact hash/content mismatch: {record['id']}")
    return raw


def atomic_bytes(path: Path, raw: bytes, mode: int = 0o600) -> None:
    if path.is_symlink():
        raise ContractError(f"Refusing symlink output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".ux-write-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def atomic_json(path: Path, value: Any) -> None:
    raw = (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()
    atomic_bytes(path, raw)


def code_snapshot(workspace: Path, paths: list[str]) -> dict[str, str | None]:
    result: dict[str, str | None] = {}
    for name in sorted(paths):
        path = within(workspace, name)
        if path.exists():
            if not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
                raise ContractError(f"Code path must be a regular UTF-8 file <=2 MiB: {name}")
            result[name] = path.read_bytes().decode("utf-8")
        else:
            result[name] = None
    return result
