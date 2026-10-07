"""Narrow, standard-library unified-text patching with durable write-ahead intent.

No shell, hooks, binary patches, modes, renames, symlinks, deployment or commits.
All predicted contents must hash to the reviewed after_revision BEFORE any write.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from .io import ContractError, GateStop, atomic_bytes, code_snapshot, digest, safe_relative, sha, within

HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?:.*)\n?$")


def apply_text_patch(before: dict[str, str | None], patch: str) -> dict[str, str | None]:
    lines = patch.splitlines(keepends=True)
    output = dict(before)
    touched: set[str] = set()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith(("diff --git ", "index ", "new file mode 100644", "deleted file mode 100644")):
            i += 1
            continue
        if not line.startswith("--- ") or i + 1 >= len(lines) or not lines[i + 1].startswith("+++ "):
            raise ContractError("Only ordinary unified text patches are supported (no binary/mode/rename changes)")
        old = line[4:].rstrip("\n")
        new = lines[i + 1][4:].rstrip("\n")
        if old != "/dev/null" and not old.startswith("a/"):
            raise ContractError("Old patch paths require a/ prefix")
        if new != "/dev/null" and not new.startswith("b/"):
            raise ContractError("New patch paths require b/ prefix")
        name = safe_relative(new[2:] if new != "/dev/null" else old[2:])
        if old != "/dev/null" and new != "/dev/null" and old[2:] != new[2:]:
            raise ContractError("Renames are not supported")
        if name not in before or name in touched:
            raise ContractError(f"Duplicate or out-of-scope patch target: {name}")
        if (old == "/dev/null") != (before[name] is None):
            raise ContractError(f"Patch creation/existence mismatch: {name}")
        source = (before[name] or "").splitlines(keepends=True)
        cursor, result, hunk_count = 0, [], 0
        i += 2
        while i < len(lines) and lines[i].startswith("@@ "):
            match = HUNK.match(lines[i])
            if not match:
                raise ContractError("Invalid hunk header")
            a, ac, b, bc = (int(match[1]), int(match[2] or 1), int(match[3]), int(match[4] or 1))
            start = a - 1 if ac else a
            if start < cursor or start > len(source):
                raise ContractError("Overlapping or out-of-bounds hunk")
            result.extend(source[cursor:start])
            cursor = start
            expected_new_start = b - 1 if bc else b
            if expected_new_start != len(result):
                raise ContractError("New hunk offset mismatch")
            i += 1
            removed, added = [], []
            while i < len(lines) and lines[i][:1] in {" ", "+", "-"}:
                # A following file header begins only after hunk counts are met.
                if len(removed) == ac and len(added) == bc:
                    break
                prefix, content = lines[i][0], lines[i][1:]
                i += 1
                if i < len(lines) and lines[i].startswith("\\ No newline at end of file"):
                    content = content.removesuffix("\n")
                    i += 1
                if prefix in {" ", "-"}:
                    removed.append(content)
                if prefix in {" ", "+"}:
                    added.append(content)
            if len(removed) != ac or len(added) != bc or source[cursor:cursor + ac] != removed:
                raise ContractError(f"Hunk context/count mismatch: {name}")
            cursor += ac
            result.extend(added)
            hunk_count += 1
        if not hunk_count:
            raise ContractError("A changed file requires at least one hunk")
        result.extend(source[cursor:])
        if new == "/dev/null":
            if result:
                raise ContractError("Deletion must remove the complete file")
            output[name] = None
        else:
            output[name] = "".join(result)
        touched.add(name)
    if not touched:
        raise ContractError("Empty patch")
    return output


def plan_intent(workspace: Path, paths: list[str], fix: dict, patch: bytes) -> dict:
    before = code_snapshot(workspace, paths)
    if digest(before) != fix["before_revision"]:
        raise GateStop("blocked", f"Workspace drift before fix {fix['id']}; no code was changed")
    try:
        after = apply_text_patch(before, patch.decode("utf-8"))
    except UnicodeError as exc:
        raise ContractError("Code patch must be UTF-8 text") from exc
    changed = {k for k in before if before[k] != after[k]}
    if changed != set(fix["changed_paths"]) or digest(after) != fix["after_revision"]:
        raise ContractError("Predicted patch scope/revision differs from reviewed fix")
    return {"fix_id": fix["id"], "before_hashes": {k: digest(v) for k, v in before.items()},
            "after_files": after, "after_revision": digest(after), "changed_paths": sorted(changed)}


def finish_intent(workspace: Path, intent: dict) -> None:
    after = intent["after_files"]
    current = code_snapshot(workspace, list(after))
    for name, text in current.items():
        allowed = {intent["before_hashes"][name], digest(after[name])}
        if digest(text) not in allowed:
            raise GateStop("blocked", f"Interrupted patch conflicts with concurrent edit: {name}")
    for name in intent["changed_paths"]:
        path = within(workspace, name)
        value = after[name]
        if current[name] == value:
            continue  # Already written before interruption: do not apply twice.
        if value is None:
            path.unlink()
            fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        else:
            mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
            atomic_bytes(path, value.encode("utf-8"), mode)
    if digest(code_snapshot(workspace, list(after))) != intent["after_revision"]:
        raise GateStop("blocked", "Workspace changed during patch; preserve intent for operator reconciliation")
