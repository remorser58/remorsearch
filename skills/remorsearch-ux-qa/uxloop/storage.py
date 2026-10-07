"""Atomic checkpoints and process locks for a single foreground, bounded loop."""
from __future__ import annotations

import fcntl
import os
from contextlib import contextmanager
from pathlib import Path

from .contracts import require_packet
from .io import ContractError, GateStop, atomic_json, digest, load_json, now, timestamp

PHASES = ("research", "plan", "browser", "fix", "replay", "decision")
STATUSES = {"running", "interrupted", "blocked", "unknown", "failed", "iteration_limit", "complete"}


@contextmanager
def lock(path: Path):
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ContractError("Lock path cannot traverse symlinks")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ContractError("Lock path cannot be a symlink")
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise GateStop("blocked", f"Another process holds the lock: {path}") from exc
        yield
    finally:
        os.close(fd)  # Kernel releases flock even after a process crash.


def event(state: dict, phase: str, status: str, reason: str, *, completed_gate: bool = False) -> None:
    if phase not in PHASES or status not in STATUSES:
        raise ContractError("Invalid phase/status transition")
    if status == "complete" and not (phase == "decision" and state["phase"] == "decision" and completed_gate):
        raise ContractError("Only a successful decision gate can complete a goal")
    if phase != state["phase"]:
        normal = PHASES.index(phase) == PHASES.index(state["phase"]) + 1
        retry = phase == "plan" and state["status"] in {"failed", "unknown"}
        if not (normal or retry):
            raise ContractError(f"Illegal transition {state['phase']} -> {phase}")
    entry = {"seq": len(state["events"]) + 1, "at": now(), "from_phase": state["phase"],
             "from_status": state["status"], "phase": phase, "status": status,
             "iteration": state["iteration"], "reason": reason,
             "previous_hash": state["events"][-1]["hash"] if state["events"] else None}
    entry["hash"] = digest(entry)
    state["events"].append(entry)
    state["phase"], state["status"], state["reason"] = phase, status, reason
    if status != "complete":
        state["accepted_fix_ids"] = []


def save(path: Path, state: dict) -> None:
    value = {k: v for k, v in state.items() if k != "checksum"}
    value["checksum"] = digest(value)
    atomic_json(path, value)


def load(path: Path) -> dict:
    value = load_json(path)
    if not isinstance(value, dict):
        raise ContractError("Checkpoint must be an object")
    checksum = value.pop("checksum", None)
    if checksum != digest(value):
        raise ContractError("Checkpoint integrity mismatch; do not auto-recreate or discard it")
    required = {"schema_version", "packet", "phase", "status", "iteration", "run_id", "workspace",
                "evidence_root", "permissions", "permission_events", "events", "applied_fixes",
                "accepted_fix_ids", "pending_intent", "reason", "prioritized_findings"}
    if set(value) not in (required, required | {"intent_decisions"}) or value["schema_version"] != "ux-loop-checkpoint.v1":
        raise ContractError("Unsupported or malformed checkpoint")
    if "intent_decisions" in value and (not isinstance(value["intent_decisions"], list) or
            any(not isinstance(x, dict) for x in value["intent_decisions"])):
        raise ContractError("Malformed operator intent decision ledger")
    seen_decisions = set()
    base = {"id", "goal_id", "context_artifact_id", "context_sha256", "fix_id", "fix_digest",
            "decision", "decided_at", "reference", "actor", "reason", "recorded_at"}
    for decision in value.get("intent_decisions", []):
        if (set(decision) not in (base | {"constraint_id"}, base | {"conflict_id"}) or
                any(not isinstance(x, str) or not x.strip() for x in decision.values())):
            raise ContractError("Malformed operator intent decision ledger entry")
        expected = "authorized_change" if "constraint_id" in decision else "resolve"
        if decision["decision"] != expected or decision["id"] in seen_decisions:
            raise ContractError("Invalid/duplicate operator intent decision")
        if timestamp(decision["decided_at"]) > timestamp(decision["recorded_at"]):
            raise ContractError("Intent decision recorded before it was made")
        seen_decisions.add(decision["id"])
    require_packet(value["packet"])
    if value["phase"] not in PHASES or value["status"] not in STATUSES or type(value["iteration"]) is not int:
        raise ContractError("Invalid checkpoint phase/status/iteration")
    if not 1 <= value["iteration"] <= value["packet"]["goal"]["max_iterations"]:
        raise ContractError("Checkpoint iteration out of bounds")
    if not isinstance(value["events"], list) or not value["events"]:
        raise ContractError("Checkpoint needs an event ledger")
    previous = None
    previous_event = None
    for seq, item in enumerate(value["events"], 1):
        if not isinstance(item, dict):
            raise ContractError("Malformed ledger entry")
        body = {k: v for k, v in item.items() if k != "hash"}
        if item.get("seq") != seq or item.get("previous_hash") != previous or item.get("hash") != digest(body):
            raise ContractError("Checkpoint ledger continuity mismatch")
        if previous_event and (item["from_phase"], item["from_status"]) != (previous_event["phase"], previous_event["status"]):
            raise ContractError("Checkpoint ledger transition mismatch")
        previous, previous_event = item["hash"], item
    if (value["phase"], value["status"]) != (previous_event["phase"], previous_event["status"]):
        raise ContractError("Checkpoint disagrees with its last event")
    if value["status"] != "complete" and value["accepted_fix_ids"]:
        raise ContractError("Non-complete checkpoint cannot accept fixes")
    return value
