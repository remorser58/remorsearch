"""One writer lock and a manifest-last committed snapshot, with no network."""
from __future__ import annotations

import fcntl
import os
import re
import shutil
import stat
import time
from pathlib import Path

from .canonical import EngineError, byte_digest, canonical, digest, loads

MAX_BYTES = 16 * 1024 * 1024
PERSONA_OUTPUTS = {"persona.hypotheses.starter.json", "qa-personas.json", "qa-personas.md", "persona-export.json"}


def scenario_output(name):
    return re.fullmatch(r"qa-scenarios/SC-[A-Za-z0-9_.:-]{1,64}\.json", name) is not None


def safe_path(path, root=None):
    path = Path(path).absolute()
    # POSIX system aliases on macOS are outside the artifact boundary.
    for alias in (Path("/tmp"), Path("/var")):
        if path.is_relative_to(alias) and alias.is_symlink():
            path = alias.resolve() / path.relative_to(alias)
    if ".." in path.parts or any(p.is_symlink() for p in (path, *path.parents)):
        raise EngineError("unsafe_path", "Symlinks and traversal are refused.")
    if root is not None and not path.is_relative_to(safe_path(root)):
        raise EngineError("unsafe_path", "Artifact must be inside the run.")
    return path


def read_bytes(path, *, private=False, root=None):
    path = safe_path(path, root)
    try:
        mode = path.stat().st_mode
        if not stat.S_ISREG(mode) or path.stat().st_size > MAX_BYTES:
            raise EngineError("unsafe_file", "Input must be a bounded regular file.")
        if mode & 0o022 or (private and mode & 0o077):
            raise EngineError("unsafe_mode", "Input file permissions are unsafe.")
        return path.read_bytes()
    except OSError as exc:
        raise EngineError("io", "Required artifact cannot be read.") from exc


def read_json(path, **kw):
    return loads(read_bytes(path, **kw))


def atomic(path, raw):
    path = safe_path(path)
    tmp = path.with_name("." + path.name + ".engine-tmp")
    safe_path(tmp)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        sync_dir(path.parent)
    finally:
        if tmp.exists():
            tmp.unlink()


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class Store:
    def __init__(self, root, timeout=5, *, fault=None):
        self.root = safe_path(root)
        if not 0 <= timeout <= 60:
            raise EngineError("lock_timeout", "Lock timeout must be between 0 and 60 seconds.")
        self.timeout, self.fault = timeout, fault or (lambda _: None)
        self.fd = None
        self.validator = None

    def __enter__(self):
        lock = safe_path(self.root / "engine.lock")
        self.fd = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        if not stat.S_ISREG(os.fstat(self.fd).st_mode):
            os.close(self.fd)
            self.fd=None
            raise EngineError("unsafe_lock", "Run lock must be a regular file.")
        os.fchmod(self.fd, 0o600)
        end = time.monotonic() + self.timeout
        while True:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except BlockingIOError:
                if time.monotonic() >= end:
                    os.close(self.fd)
                    self.fd = None
                    raise EngineError("lock_busy", "Another engine operation holds the run lock.", 3)
                time.sleep(min(0.05, max(0, end - time.monotonic())))

    def __exit__(self, *_):
        if self.fd is not None:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
            os.close(self.fd)

    def state(self):
        path = self.root / "engine-state.json"
        if not path.exists():
            return None
        state = read_json(path, private=True)
        if state.get("schema_version") != "ux-research-engine-state.v1":
            raise EngineError("snapshot", "Committed manifest is invalid.")
        if digest({k: state[k] for k in ("operation", "inputs", "outputs")}) != state["generation_id"]:
            raise EngineError("snapshot", "Committed manifest digest is invalid.")
        return state

    def committed(self, name):
        state = self.state()
        if not state or name not in state["outputs"]:
            raise EngineError("missing_snapshot", "A required committed engine artifact is absent.")
        item = state["outputs"][name]
        path = safe_path(self.root / item["generation_path"], self.root / ".engine")
        if item["file"] != name:
            raise EngineError("snapshot", "Manifest output name is invalid.")
        raw = read_bytes(path, private=True)
        if byte_digest(raw) != item["sha256"]:
            raise EngineError("snapshot", "Committed snapshot digest does not match.")
        return loads(raw) if name.endswith(".json") else raw.decode("utf-8")

    def has(self, name):
        state = self.state()
        return bool(state and name in state["outputs"])

    def failure(self, name, value):
        # Failure markers invalidate consumption while retaining the previous snapshot.
        atomic(self.root / name, canonical(value))
        if name == "gate_failed.json" and (self.root / "gate.json").exists():
            safe_path(self.root / "gate.json").unlink()

    def publish(self, operation, outputs, inputs=None, *, keep=True, invalidates_gate=False, mirror_exclusions=()):
        prior = self.state()
        invalidates_personas = invalidates_gate or (
            "gate.json" in outputs and prior and "gate.json" in prior["outputs"]
            and self.committed("gate.json")["bundle_input_sha256"] != outputs["gate.json"]["bundle_input_sha256"])
        combined = {}
        if keep and prior:
            for name in prior["outputs"]:
                if invalidates_gate and name in {"gate.json", "gate_failed.json", "audience.draft.json", "audience.todo.md", "report_check.json", "bundle.min.json", "minimize.json"}:
                    continue
                if invalidates_personas and (name in PERSONA_OUTPUTS or scenario_output(name)):
                    continue
                if operation == "export-personas" and scenario_output(name):
                    continue
                combined[name] = self.committed(name)
        combined.update(outputs)
        if "gate.json" in outputs:
            combined.pop("gate_failed.json", None)
        if "gate_failed.json" in outputs:
            combined.pop("gate.json", None)
        raw = {k: v.encode("utf-8") if isinstance(v, str) else canonical(v) for k, v in combined.items()}
        for name in raw:
            if Path(name).name != name and not scenario_output(name):
                raise EngineError("unsafe_path", "Outputs must be plain filenames or generated QA scenario paths.")
        for name in outputs:
            if not scenario_output(name):
                continue
            path = safe_path(self.root / name, self.root)
            if path.exists():
                old = prior["outputs"].get(name) if prior else None
                if old is None or byte_digest(read_bytes(path)) != old["sha256"]:
                    raise EngineError("output_conflict", "An authored or unrelated scenario already uses this output path; it is preserved.",
                                      location=name, next_step="Choose a new scenario ID or move your authored scenario to a separate input directory.")
        snapshot = digest({k: byte_digest(v) for k, v in raw.items()})
        engine = safe_path(self.root / ".engine")
        engine.mkdir(mode=0o700, exist_ok=True)
        stage = safe_path(engine / "staged")
        if stage.exists():
            shutil.rmtree(stage)
        stage.mkdir(mode=0o700)
        dest = safe_path(engine / snapshot)
        try:
            for name, data in raw.items():
                safe_path((stage / name).parent, stage).mkdir(mode=0o700, exist_ok=True)
                atomic(stage / name, data)
            sync_dir(stage)
            self.fault("staged")
            if dest.exists():
                shutil.rmtree(stage)
            else:
                os.replace(stage, dest)
            self.fault("snapshot")
            entries = {k: dict(file=k, generation_path=".engine/" + snapshot + "/" + k, sha256=byte_digest(v)) for k, v in raw.items()}
            value = dict(operation=operation, inputs=inputs or {}, outputs=entries)
            state = dict(schema_version="ux-research-engine-state.v1", generation_id=digest(value),
                         previous_generation_id=prior["generation_id"] if prior else None, **value)
            if self.validator is not None:
                self.validator(combined)
            self.fault("before_manifest")
            atomic(self.root / "engine-state.json", canonical(state))
            self.fault("after_manifest")
            # Mirrors are for agent review only; consumers never read them as authority.
            # Scenario snapshots are already complete when the manifest advances. Publish
            # their review mirrors before the pass marker; edited mirrors remain authored.
            for name in sorted(raw, key=lambda x: (x == "persona-export.json", not scenario_output(x), x)):
                data = raw[name]
                if scenario_output(name) and name not in outputs:
                    continue
                if name not in mirror_exclusions:
                    safe_path((self.root / name).parent, self.root).mkdir(mode=0o700, exist_ok=True)
                    atomic(self.root / name, data)
            for name in (set(prior["outputs"]) if prior else set()) - set(raw):
                path = safe_path(self.root / name)
                if path.exists():
                    if scenario_output(name) and byte_digest(read_bytes(path)) != prior["outputs"][name]["sha256"]:
                        continue
                    path.unlink()
            if "gate.json" in raw:
                failed = safe_path(self.root / "gate_failed.json")
                if failed.exists():
                    failed.unlink()
            for path in engine.iterdir():
                safe_path(path)
                if path != dest:
                    if path.is_dir():
                        shutil.rmtree(path)
                    else:
                        path.unlink()
            sync_dir(engine)
        except BaseException:
            # If the manifest advanced, retain its snapshot; otherwise discard the stage.
            active = self.state()
            active_paths = {self.root / x["generation_path"] for x in active["outputs"].values()} if active else set()
            if stage.exists():
                shutil.rmtree(stage)
            if dest.exists() and not any(p.is_relative_to(dest) for p in active_paths):
                shutil.rmtree(dest)
            for discarded in engine.iterdir():
                safe_path(discarded)
                if not any(p.is_relative_to(discarded) for p in active_paths):
                    if discarded.is_dir():shutil.rmtree(discarded)
                    else:discarded.unlink()
            sync_dir(engine)
            raise
        return state
