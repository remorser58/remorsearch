"""Artifact integrity and scoped completion gates; never infer proof from a URL."""
from __future__ import annotations

import struct
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree

from .contracts import index
from .io import ContractError, GateStop, parse_json, read_artifact, timestamp


class Evidence:
    def __init__(self, packet: dict, root: Path):
        self.packet = packet
        self.root = root
        self.artifacts = index(packet["artifacts"])
        self.runs = index(packet["browser_runs"])
        self.scenarios = index(packet["scenarios"])
        self.records = {key: index(value) for key, value in packet["bundle"]["records"].items()}

    def artifact(self, artifact_id: str | None) -> bytes:
        if artifact_id not in self.artifacts:
            raise GateStop("blocked", f"Required artifact is not supplied: {artifact_id}")
        record = self.artifacts[artifact_id]
        if self.packet["mode"] == "live":
            captured = timestamp(record["created_at"])
            current = datetime.now(timezone.utc)
            if captured > current + timedelta(minutes=5) or captured < current - timedelta(days=self.packet["policy"]["retention_days"]):
                raise GateStop("unknown", f"Artifact is future-dated or outside retention/freshness window: {artifact_id}")
        return read_artifact(self.root, record)

    def payload(self, artifact_id: str | None) -> dict:
        raw = self.artifact(artifact_id)
        try:
            value = parse_json(raw)
        except ContractError as exc:
            raise GateStop("unknown", f"Malformed evidence payload {artifact_id}: {exc}") from exc
        if not isinstance(value, dict):
            raise GateStop("unknown", f"Evidence payload must be an object: {artifact_id}")
        return value

    def identity(self, payload: dict, run: dict, kind: str) -> None:
        expected = {"run_id": run["id"], "scenario_digest": run["scenario_digest"],
                    "code_revision": run["code_revision"], "kind": kind}
        if any(payload.get(k) != v for k, v in expected.items()):
            raise GateStop("unknown", f"Cross-run/stale {kind} evidence for {run['id']}")

    def capture_time(self, artifact_id: str, run: dict) -> None:
        at = timestamp(self.artifacts[artifact_id]["created_at"])
        if not timestamp(run["started_at"]) <= at <= timestamp(run["ended_at"]):
            raise GateStop("unknown", f"Capture {artifact_id} is not from run interval {run['id']}")

    def research(self) -> None:
        for evidence_id in self.packet["goal"]["evidence_ids"]:
            evidence = self.records["evidence"][evidence_id]
            source = self.records["sources"][evidence["source_id"]]
            if evidence["epistemic_status"] != "observed":
                raise GateStop("unknown", f"Required research evidence is not observed: {evidence_id}")
            if source["retention_status"] in {"withdrawn", "deleted", "redacted"}:
                raise GateStop("unknown", f"Required evidence uses unavailable source: {source['id']}")

    def figma(self, figma_id: str) -> None:
        figma = self.records["figma"][figma_id]
        if figma["design_status"] not in {"comparison_ready", "approved", "implemented"}:
            raise GateStop("blocked", f"Editable Figma baseline is not ready: {figma_id}")
        if figma.get("defect_class") in {"spec_conflict", "design_defect"}:
            raise GateStop("blocked", f"Resolve Figma design/spec decision before implementation: {figma_id}")
        payload = self.payload(figma["readback_artifact_ref"])
        fields = ("file_key", "branch_key", "baseline_version", "readback_version", "node_ids", "read_at")
        if payload.get("editable") is not True or any(payload.get(k) != figma.get(k) for k in fields):
            raise GateStop("unknown", f"Missing/mismatched editable Figma readback: {figma_id}")
        if self.artifacts[figma["readback_artifact_ref"]]["created_at"] != figma["read_at"]:
            raise GateStop("unknown", f"Figma readback timestamp mismatch: {figma_id}")

    def screenshot(self, artifact_id: str, viewport: dict) -> None:
        raw = self.artifact(artifact_id)
        expected = (round(viewport["width"] * viewport["device_scale_factor"]),
                    round(viewport["height"] * viewport["device_scale_factor"]))
        if self.packet["mode"] == "fixture" and raw.lstrip().startswith(b"<svg"):
            try:
                root = ElementTree.fromstring(raw)
                actual = (int(root.attrib["width"]), int(root.attrib["height"]))
                valid = root.attrib.get("data-ux-fixture") == "true"
            except (ElementTree.ParseError, ValueError, KeyError):
                actual, valid = None, False
            if actual != expected or not valid:
                raise GateStop("unknown", f"Malformed synthetic capture: {artifact_id}")
            return
        if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
            raise GateStop("unknown", f"Live capture must be PNG, not a URL/mock: {artifact_id}")
        offset, dimensions, saw_end, saw_pixels = 8, None, False, False
        while offset + 12 <= len(raw):
            size = struct.unpack(">I", raw[offset:offset + 4])[0]
            chunk = raw[offset + 4:offset + 8]
            end = offset + 12 + size
            if end > len(raw):
                break
            payload = raw[offset + 8:offset + 8 + size]
            checksum = struct.unpack(">I", raw[end - 4:end])[0]
            if zlib.crc32(chunk + payload) & 0xffffffff != checksum:
                break
            if offset == 8 and chunk == b"IHDR" and size == 13:
                dimensions = struct.unpack(">II", payload[:8])
            saw_pixels = saw_pixels or chunk == b"IDAT"
            if chunk == b"IEND" and size == 0:
                saw_end = end == len(raw)
                break
            offset = end
        if dimensions != expected or not saw_end or not saw_pixels:
            raise GateStop("unknown", f"Corrupt/wrong-size PNG capture: {artifact_id}")

    def visual(self, run: dict, must_pass: bool) -> None:
        checks = [x for x in self.packet["visual_checks"] if x["run_id"] == run["id"]]
        if not checks:
            raise GateStop("blocked", f"No versioned visual comparison for run {run['id']}")
        for check in checks:
            if check["status"] in {"unknown", "blocked"}:
                raise GateStop(check["status"], f"Visual comparison {check['id']}: {check['reason']}")
            self.figma(check["figma_id"])
            self.screenshot(check["actual_artifact_id"], check["viewport"])
            self.screenshot(check["reference_artifact_id"], check["viewport"])
            self.capture_time(check["actual_artifact_id"], run)
            self.capture_time(check["comparison_artifact_id"], run)
            payload = self.payload(check["comparison_artifact_id"])
            self.identity(payload, run, "visual_report")
            if payload.get("comparison") != check:
                raise GateStop("unknown", f"Visual report disagrees with declared comparison: {check['id']}")
            if must_pass and check["status"] != "passed":
                raise GateStop("failed", f"Visual comparison failed: {check['id']}: {check['reason']}")

    def browser(self, run_id: str, revision: str, must_pass: bool,
                grants: dict[str, dict], after: str | None = None) -> None:
        run = self.runs[run_id]
        if run["outcome"] in {"unknown", "blocked"}:
            raise GateStop(run["outcome"], f"Browser run {run_id}: {run['reason']}")
        if run["code_revision"] != revision:
            raise GateStop("unknown", f"Browser run {run_id} captured a different scoped code revision")
        if after and self.packet["mode"] == "live" and timestamp(run["started_at"]) < timestamp(after):
            raise GateStop("unknown", f"Replay {run_id} predates the last code change")
        scenario = self.scenarios[run["scenario_id"]]
        for step in scenario["steps"]:
            capability = step["requires"]
            if capability not in grants:
                raise GateStop("blocked", f"Scenario {scenario['id']} requires ungranted {capability}")
            if capability != "read_only" and self.packet["mode"] == "live" and timestamp(grants[capability]["at"]) > timestamp(run["started_at"]):
                raise GateStop("blocked", f"{capability} was not granted before live run {run_id}")
        for kind, artifact_id in run["evidence"].items():
            payload = self.payload(artifact_id)
            self.identity(payload, run, kind)
            self.capture_time(artifact_id, run)
            if not isinstance(payload.get("unexpected_errors"), list):
                raise GateStop("unknown", f"{kind} must explicitly record unexpected_errors")
            if must_pass and payload["unexpected_errors"]:
                raise GateStop("failed", f"Unexpected {kind} errors in replay {run_id}")
        for step in run["steps"]:
            for artifact_id in step["artifact_ids"]:
                payload = self.payload(artifact_id)
                self.identity(payload, run, "steps")
                self.capture_time(artifact_id, run)
                if payload.get("results") != run["steps"]:
                    raise GateStop("unknown", f"Step transcript mismatch for {run_id}")
        for check in run["accessibility"]:
            if check["artifact_id"] is None:
                raise GateStop(check["status"], f"Accessibility {check['name']} has no evidence")
            payload = self.payload(check["artifact_id"])
            self.identity(payload, run, "accessibility")
            self.capture_time(check["artifact_id"], run)
            if payload.get("results") != run["accessibility"]:
                raise GateStop("unknown", f"Accessibility report mismatch for {run_id}")
            if must_pass and check["status"] != "passed":
                raise GateStop(check["status"], f"Accessibility {check['name']} did not pass for {run_id}")
        self.visual(run, must_pass)
        if must_pass and run["outcome"] != "passed":
            raise GateStop("failed", f"Original scenario replay failed: {run_id}")

    def regression(self, replay: dict, revision: str) -> None:
        check = replay["regression"]
        if check["status"] != "passed":
            raise GateStop(check["status"], f"Regression is {check['status']}: {check['detail']}")
        payload = self.payload(check["artifact_id"])
        expected = {"kind": "regression", "replay_id": replay["id"], "code_revision": revision,
                    "run_ids": replay["run_ids"], "scenario_ids": check["scenario_ids"],
                    "status": "passed", "failed_checks": []}
        if check["code_revision"] != revision or any(payload.get(k) != v for k, v in expected.items()):
            raise GateStop("unknown", "Regression receipt is stale, incomplete or contradicts pass")
        capture_at = timestamp(self.artifacts[check["artifact_id"]]["created_at"])
        if capture_at < max(timestamp(self.runs[x]["ended_at"]) for x in replay["run_ids"]):
            raise GateStop("unknown", "Regression report predates its scenario runs")
