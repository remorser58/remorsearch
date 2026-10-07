"""Attach a completed ergonomic run's analysis to an existing QA evidence bundle.

This is the persona-qa <-> ergonomics runtime bridge. It reuses the existing
pieces only: :func:`ergoqa.analyze.analyze_run` for detection,
:func:`ergoqa.swarm.aggregate` for findings and
``scripts/validate_bundle.py`` for the graph contract. There is no new schema:
the bridge appends records to a ``ux-evidence-bundle.v1`` that already exists.

Contract:

- The run must be a real ``ergo-run.v1`` directory whose ``run.json`` records a
  profile (the owner) and ``status: completed``. Owner analysis is the default;
  cross-profile evaluations are attached only as explicitly analytical records
  (``cross_profile_evaluation: true``) and can never verify a finding.
- ``binding`` maps an existing bundle scenario id to an ergo profile id. The
  scenario's ``persona_id`` is the persona the profile stands for; original
  persona/scenario/source/claim records and permissions are never modified.
- Capture receipts are copied out of the run directory (which stays untouched)
  into ``receipts_root`` so ``validate_bundle --artifacts-root receipts_root``
  can verify them. Timestamps, artifact hashes and any known build identifier
  come from recorded artifacts. An unknown build keeps findings unverified.
"""

from __future__ import annotations

import copy
import os
import re
import shutil
from pathlib import Path
from typing import Any

from . import analyze, swarm
from .profiles import profile_index
from .snapshot import SnapshotError, load_run_dir, resolve_within, sha256_file

_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SECOND_PASS_FIELDS = ("reviewer", "task_completed", "control_name", "omitted", "severity", "inconclusive")


class AttachError(ValueError):
    """The run, binding or bundle violates the attach contract."""


def _validate_input_bundle(bundle: Any) -> None:
    try:
        from validate_bundle import validate_bundle  # type: ignore[import-not-found]
    except ImportError:  # pragma: no cover - skill root vs scripts dir on sys.path
        from scripts.validate_bundle import validate_bundle  # type: ignore[no-redef]
    errors = validate_bundle(bundle)
    if errors:
        raise AttachError("input bundle is not a valid ux-evidence-bundle.v1: " + "; ".join(errors[:3])
                          + (f" (+{len(errors) - 3} more)" if len(errors) > 3 else ""))


def _parse_binding(binding: dict[str, str], bundle: dict[str, Any], profiles_by_id: dict[str, dict[str, Any]]) -> dict[str, str]:
    """Validate scenario->profile bindings; return {profile_id: scenario_id}."""
    records = bundle["records"]
    scenarios = {s.get("id"): s for s in records.get("scenarios", []) if isinstance(s, dict)}
    personas = {p.get("id") for p in records.get("personas", []) if isinstance(p, dict)}
    profile_to_scenario: dict[str, str] = {}
    for scenario_id, profile_id in binding.items():
        scenario = scenarios.get(scenario_id)
        if scenario is None:
            raise AttachError(f"binding {scenario_id}={profile_id}: bundle has no scenario {scenario_id!r}")
        if profile_id not in profiles_by_id:
            raise AttachError(f"binding {scenario_id}={profile_id}: profile {profile_id!r} was not supplied")
        persona_id = scenario.get("persona_id")
        if persona_id not in personas:
            raise AttachError(f"binding {scenario_id}={profile_id}: scenario {scenario_id!r} has no persona in this bundle")
        if profile_id in profile_to_scenario:
            raise AttachError(f"profile {profile_id!r} is bound to both {profile_to_scenario[profile_id]!r} and {scenario_id!r}")
        profile_to_scenario[profile_id] = scenario_id
    return profile_to_scenario


def _quoted_ui_text(snapshot: dict[str, Any], element_ids: list[str]) -> str:
    elements = {e.get("id"): e for e in snapshot.get("elements", []) if isinstance(e, dict)}
    for eid in element_ids:
        element = elements.get(eid)
        if element and (element.get("text") or element.get("name")):
            return str(element["text"] or element["name"])
    for element in snapshot.get("elements", []):
        if isinstance(element, dict) and element.get("text"):
            return str(element["text"])
    title = (snapshot.get("surface") or {}).get("title")
    return str(title) if title else ""


def _build_id(doc: dict[str, Any]) -> str | None:
    value = (doc.get("surface") or {}).get("build_id", doc.get("build_id"))
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise AttachError("recorded build_id must be a non-empty string")
    return None if value.strip().lower() in ("unknown", "unrecorded") else value


def _receipt_for_snapshot(run: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    """Prepare a receipt without mutating the source or destination."""
    shot = snapshot["screenshot"]
    surface_url = (snapshot.get("surface") or {}).get("url")
    if not isinstance(surface_url, str) or "://" not in surface_url:
        raise AttachError(f"{snapshot['snapshot_id']}: recorded surface URL {surface_url!r} is missing; a receipt needs it")
    run_build, snap_build = _build_id(run), _build_id(snapshot)
    if run_build and snap_build and run_build != snap_build:
        raise AttachError(f"{snapshot['snapshot_id']}: build_id differs from recorded run build_id")
    device = snapshot["device"]
    width, height = device["viewport_css"]
    return {
        "artifact_path": f"{run['run_id']}/{shot['path']}",
        "sha256": shot.get("sha256") or sha256_file(shot["resolved_path"]),
        "captured_at": snapshot["captured_at"],
        "surface_url": surface_url,
        "build_id": snap_build or run_build or "unknown",
        "device": f"{device['id']}/{device['orientation']} {width}x{height} dpr={device['dpr']}",
        "quoted_ui_text": "",
    }


def _second_pass_records(second_pass: dict[str, Any] | list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    if second_pass is None:
        return {}
    rows = [second_pass] if isinstance(second_pass, dict) else second_pass
    if not isinstance(rows, list):
        raise AttachError("--second-pass must contain an array of per-finding review records")
    indexed = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("finding_id"), str) or not row["finding_id"].strip():
            raise AttachError("each second pass needs its own exact finding_id; anonymous reviews cannot be reused")
        fid = row["finding_id"]
        if fid in indexed:
            raise AttachError(f"duplicate second pass finding_id {fid!r}")
        indexed[fid] = _second_pass_record(row)
    return indexed


def _second_pass_record(second_pass: dict[str, Any]) -> dict[str, Any]:
    record = {key: second_pass.get(key) for key in (*SECOND_PASS_FIELDS, "finding_id")}
    if record["reviewer"] not in ("subagent", "self"):
        raise AttachError("second_pass.reviewer must be 'subagent' or 'self'")
    if not isinstance(record["task_completed"], bool) or not isinstance(record["inconclusive"], bool):
        raise AttachError("second_pass.task_completed and .inconclusive must be booleans")
    if not isinstance(record["control_name"], str) or not record["control_name"].strip():
        raise AttachError("second_pass.control_name must be a non-empty string")
    if not isinstance(record["omitted"], list) or any(not isinstance(item, str) for item in record["omitted"]):
        raise AttachError("second_pass.omitted must be an array of strings")
    if record["severity"] == "disagree":
        resolution = second_pass.get("resolution")
        if not isinstance(resolution, str) or not resolution.strip():
            raise AttachError("second_pass severity 'disagree' needs a written resolution")
        record["resolution"] = resolution
    elif record["severity"] != "agree":
        raise AttachError("second_pass.severity must be 'agree' or 'disagree'")
    return record


def _receipt_destination(root: Path, relative: str, digest: str, run_path: Path) -> Path:
    if root.is_symlink():
        raise AttachError("receipt directory must not be a symlink")
    try:
        dest = resolve_within(root, relative)
    except SnapshotError as exc:
        raise AttachError(f"unsafe receipt destination: {exc}") from exc
    if dest.resolve().is_relative_to(run_path):
        raise AttachError("receipt artifacts must live outside the run directory")
    for parent in dest.parents:
        if parent == root.parent:
            break
        if parent.exists() and not parent.is_dir():
            raise AttachError(f"conflicting receipt directory: {parent}")
    if dest.exists() and (not dest.is_file() or sha256_file(dest) != digest):
        raise AttachError(f"conflicting preexisting receipt artifact: {relative}")
    return dest


def _copy_receipts(root: Path, plan: dict[str, tuple[str, str]], run_path: Path) -> None:
    # Check the entire plan before the first mkdir/copy; identical existing files
    # are reused unchanged. New files use exclusive creation and never chmod an
    # existing target or follow a file symlink.
    for relative, (_, digest) in plan.items():
        _receipt_destination(root, relative, digest, run_path)
    for relative, (source, digest) in plan.items():
        dest = _receipt_destination(root, relative, digest, run_path)
        if dest.exists():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        _receipt_destination(root, relative, digest, run_path)
        fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
        with os.fdopen(fd, "wb") as output, open(source, "rb") as input_file:
            shutil.copyfileobj(input_file, output)
        if sha256_file(dest) != digest:
            raise AttachError(f"capture changed while copying: {relative}")


def attach_run(
    bundle: dict[str, Any],
    run_dir: str | Path,
    profiles: list[dict[str, Any]],
    binding: dict[str, str],
    *,
    receipts_root: str | Path,
    scenario: dict[str, Any] | None = None,
    cross_profile: bool = False,
    gaze_enabled: bool = True,
    second_pass: dict[str, Any] | list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return a new bundle with the run's ergonomic evidence attached.

    The input bundle, the run directory and the profiles are not modified.
    Raises :class:`AttachError` on any contract violation (failed or ownerless
    runs, device/orientation mismatch, missing bindings, identity collisions,
    stale receipts, unsafe paths).
    """
    if not isinstance(bundle, dict) or not isinstance(bundle.get("records"), dict):
        raise AttachError("bundle must be a ux-evidence-bundle.v1 object with records")
    _validate_input_bundle(bundle)
    try:
        profiles_by_id = profile_index(profiles)
    except ValueError as exc:
        raise AttachError(str(exc)) from exc
    profile_to_scenario = _parse_binding(binding, bundle, profiles_by_id)
    run_path = Path(run_dir).resolve()
    if Path(receipts_root).is_symlink():
        raise AttachError("receipt directory must not be a symlink")
    receipts = Path(receipts_root).resolve()
    if receipts == run_path or receipts.is_relative_to(run_path):
        raise AttachError("receipts directory must live outside the run directory")

    try:
        run, snapshots = load_run_dir(run_dir, verify_screenshots=True)
    except SnapshotError as exc:
        raise AttachError(f"run {run_dir} failed verification: {exc}") from exc
    run_id = run.get("run_id")
    if not isinstance(run_id, str) or not _RUN_ID.match(run_id):
        raise AttachError(f"run_id {run_id!r} is not a safe path segment; refusing to build receipt paths from it")
    observed_task_failure = any(c.get("kind") == "task_check" and c.get("result") == "fail" and c.get("passed") is False
                                and c.get("snapshot_id") for c in (run.get("success_detail") or {}).get("criteria", []))
    if run.get("status") != "completed" or (run.get("success") is False and not observed_task_failure):
        raise AttachError(f"run {run_id}: status {run.get('status')!r}, success {run.get('success')!r}; "
                          "only completed runs with success or captured task mismatch can be attached as persona evidence")
    owner_id = run.get("profile_id")
    if not owner_id or owner_id == "no-profile":
        raise AttachError(f"run {run_id} was recorded with --device and no profile: no persona executed it, so it "
                          "cannot be attached to QA personas; use `ergo_qa.py swarm --bundle` for the analytical export")
    owner = profiles_by_id.get(owner_id)
    if owner is None:
        raise AttachError(f"run {run_id}: owner profile {owner_id!r} not supplied")
    if owner_id not in profile_to_scenario:
        raise AttachError(f"run {run_id}: owner profile {owner_id!r} is not bound to a bundle scenario "
                          f"(--bind BUNDLE_SCENARIO={owner_id})")
    if not snapshots:
        raise AttachError(f"run {run_id}: no captures to attach")
    recorded = run["device"]
    device_id = recorded["id"]
    orientation = recorded["orientation"]
    attrs = owner["attributes"]
    if device_id != attrs["device_id"] or orientation != attrs.get("orientation", "portrait"):
        raise AttachError(f"run {run_id}: recorded device {device_id!r}/{orientation!r} does not match profile "
                          f"{owner_id} ({attrs['device_id']!r}/{attrs.get('orientation', 'portrait')!r})")

    analysis = analyze.analyze_run(run_path, profiles, scenario, cross_profile=cross_profile, gaze_enabled=gaze_enabled)
    if analysis.get("owner_profile_id") != owner_id:
        raise AttachError(f"run {run_id}: analysis owner {analysis.get('owner_profile_id')!r} != recorded owner {owner_id!r}")
    evaluated = analysis["profiles_evaluated"]
    unbound = [pid for pid in evaluated if pid not in profile_to_scenario]
    if unbound:
        raise AttachError(f"run {run_id}: profiles {', '.join(unbound)} were evaluated but are not bound to a bundle "
                          "scenario; add --bind entries or drop --cross-profile")
    findings = swarm.aggregate([analysis], profiles)

    out = copy.deepcopy(bundle)
    records = out["records"]
    existing_ids = {rec.get("id") for group in records.values() if isinstance(group, list)
                    for rec in group if isinstance(rec, dict) and rec.get("id")}
    snapshots_by_id = {snap["snapshot_id"]: snap for snap in snapshots}
    receipts_by_snapshot: dict[str, dict[str, Any]] = {}
    copy_plan: dict[str, tuple[str, str]] = {}
    for snap in snapshots:
        receipt = _receipt_for_snapshot(run, snap)
        receipt["quoted_ui_text"] = _quoted_ui_text(snap, [])
        if not receipt["quoted_ui_text"]:
            raise AttachError(f"{snap['snapshot_id']}: capture has no UI text to quote in its receipt")
        relative, digest = receipt["artifact_path"], receipt["sha256"]
        _receipt_destination(receipts, relative, digest, run_path)
        if relative in copy_plan and copy_plan[relative][1] != digest:
            raise AttachError(f"conflicting capture paths: {relative}")
        copy_plan[relative] = (snap["screenshot"]["resolved_path"], digest)
        receipts_by_snapshot[snap["snapshot_id"]] = receipt
    new_runs: dict[str, dict[str, Any]] = {}
    pair_profile_of: dict[str, str] = {}
    new_observations: dict[str, dict[str, Any]] = {}

    def _claim(record_id: str) -> None:
        if record_id in existing_ids:
            raise AttachError(f"record id {record_id!r} already exists in this bundle; refusing to overwrite evidence")
        existing_ids.add(record_id)

    # Execution and checked coverage exist independently from defect findings.
    for pid in evaluated:
        pair_run_id = f"ERGO-RUN-{run_id}@{pid}"
        _claim(pair_run_id)
        pair_profile_of[pair_run_id] = pid
        record = {
            "id": pair_run_id,
            "scenario_id": profile_to_scenario[pid],
            "status": run["status"],
            "task_success": run.get("success"),
            "started_at": run["started_at"],
            "ended_at": run["ended_at"],
            "recorded_run_id": run_id,
            "profile_id": pid,
            "owner_profile_id": owner_id,
            "cross_profile_evaluation": pid != owner_id,
            "surface_ref": snapshots[-1]["surface"]["url"],
            "device_id": device_id,
            "orientation": orientation,
            "device": copy.deepcopy(recorded),
            "coverage": [key for key, pids in analysis["coverage"].items() if pid in pids],
            "build_id": _build_id(run) or "unknown",
            "build_identity_status": "recorded" if _build_id(run) else "unknown",
        }
        for key in ("focus_walks", "reflow"):
            if key in run:
                record[key] = copy.deepcopy(run[key])
        probes = [{"step_index": s["step_index"], "focus_probe": copy.deepcopy(s["focus_probe"])}
                  for s in run["steps"] if "focus_probe" in s]
        if probes:
            record["focus_probes"] = probes
        new_runs[pair_run_id] = record

    owner_obs_run = f"ERGO-RUN-{run_id}@{owner_id}"
    for snap in snapshots:
        coverage_id = f"ERGO-CAPTURE-{run_id}@{snap['snapshot_id']}"
        _claim(coverage_id)
        receipt = receipts_by_snapshot[snap["snapshot_id"]]
        new_observations[coverage_id] = {
            "id": coverage_id, "run_id": owner_obs_run,
            "kind": "capture_coverage", "epistemic_status": "observed", "basis": "measured",
            "analysis_kind": "owner_execution", "snapshot_id": snap["snapshot_id"],
            "snapshot_device": copy.deepcopy(snap["device"]),
            "receipt": copy.deepcopy(receipt),
            "build_identity_status": "unknown" if receipt["build_id"] == "unknown" else "recorded",
        }

    for obs in analysis["observations"]:
        if obs["passed"] or (obs.get("extra") or {}).get("verdict") == "inconclusive":
            continue
        pair_profile = obs["profile_id"]
        pair_run_id = f"ERGO-RUN-{run_id}@{pair_profile}"
        kind = "owner_execution" if pair_profile == owner_id else "analytical_cross_profile"
        obs_id = f"ERGO-{obs['id']}"
        _claim(obs_id)
        record: dict[str, Any] = {
            "id": obs_id,
            "run_id": pair_run_id,
            "epistemic_status": obs["epistemic_status"],
            "basis": obs["basis"],
            "check_id": obs["check_id"],
            "element_key": obs["element_key"],
            "measurement": obs["measurement"],
            "severity": obs["severity"],
            "summary": obs["message_ko"],
            "analysis_kind": kind,
            "selectors": list(obs.get("selectors") or []),
        }
        if obs.get("model"):
            record["model"] = obs["model"]
        snapshot = snapshots_by_id.get(obs.get("snapshot_id") or "")
        if snapshot is not None:
            receipt = copy.deepcopy(receipts_by_snapshot[snapshot["snapshot_id"]])
            receipt["quoted_ui_text"] = _quoted_ui_text(snapshot, obs.get("element_ids") or [])
            if not receipt["quoted_ui_text"]:
                raise AttachError(f"observation {obs_id}: no visible UI text in {snapshot['snapshot_id']} to quote "
                                  "in the capture receipt")
            record["receipt"] = receipt
            record["snapshot_id"] = snapshot["snapshot_id"]
            record["snapshot_device"] = copy.deepcopy(snapshot["device"])
        record["build_identity_status"] = "recorded" if (
            record.get("receipt", {}).get("build_id", _build_id(run) or "unknown") != "unknown"
        ) else "unknown"
        new_observations[obs_id] = record

    new_findings: list[dict[str, Any]] = []
    new_proposals: list[dict[str, Any]] = []
    reviews = _second_pass_records(second_pass)
    missing_reviews: list[str] = []
    for finding in findings:
        per_pair: dict[str, list[str]] = {}
        for obs_id in finding["observation_ids"]:
            mapped = f"ERGO-{obs_id}"
            if mapped in new_observations:
                per_pair.setdefault(new_observations[mapped]["run_id"], []).append(mapped)
        for pair_run_id, obs_ids in sorted(per_pair.items()):
            pair_profile = pair_profile_of[pair_run_id]
            finding_id = f"ERGO-{finding['id']}@{run_id}@{pair_profile}"
            _claim(finding_id)
            analytical = pair_run_id != owner_obs_run
            verified = (not analytical and finding.get("tier") != "hypothesis"
                        and all(new_observations[o]["epistemic_status"] == "observed"
                                and new_observations[o]["basis"] == "measured"
                                and new_observations[o]["build_identity_status"] == "recorded" for o in obs_ids))
            record = {
                "id": finding_id,
                "scenario_id": profile_to_scenario[pair_profile],
                "observation_ids": obs_ids,
                "severity": finding["severity"],
                "epistemic_status": "observed" if verified else "inferred",
                "verification_status": "verified" if verified else "unverified",
                "check_id": finding["check_id"],
                "summary": finding["summary_ko"],
                "basis": finding["basis"],
                "analysis_kind": "owner_execution" if not analytical else "analytical_cross_profile",
                "coverage_label": finding["coverage_label"],
                "triggered_profiles": list(finding["triggered_profiles"]),
            }
            if finding.get("segments_affected"):
                record["segments_affected"] = list(finding["segments_affected"])
            if finding.get("profile_specific"):
                record["profile_specific"] = dict(finding["profile_specific"])
            if finding["severity"] in ("P0", "P1"):
                review = reviews.get(finding_id)
                if review is None:
                    missing_reviews.append(finding_id)
                else:
                    record["second_pass"] = copy.deepcopy(review)
                    if review["inconclusive"] or not review["task_completed"]:
                        record["verification_status"], record["epistemic_status"] = "unverified", "inferred"
                if not any(new_observations[o].get("receipt") for o in obs_ids):
                    raise AttachError(f"P0/P1 finding {finding_id} has no screenshot anchor; record its capture before attachment")
            new_findings.append(record)
            if finding.get("recommendation_ko"):
                proposal_id = f"ERGO-PR-{finding['id']}@{run_id}@{pair_profile}"
                _claim(proposal_id)
                # Same-severity groups can carry different per-profile advice data;
                # each persona's proposal quotes its own observation, never a copy of
                # another profile's numbers (falls back to the labelled aggregate text
                # when this profile's observations have no advice data).
                own_summary = swarm.recommendation_for_profile(
                    finding["check_id"], [new_observations[o] for o in obs_ids], pair_profile)
                new_proposals.append({
                    "id": proposal_id,
                    "finding_ids": [finding_id],
                    "fix_layer": finding["fix_layer"],
                    "summary": own_summary or finding["recommendation_ko"],
                })

    if missing_reviews:
        raise AttachError("P0/P1 findings need identity-matched second pass records (--second-pass FILE, JSON array). "
                          "Review each capture/text dump, then supply finding_id for: " + ", ".join(missing_reviews))

    records.setdefault("runs", []).extend(new_runs.values())
    records.setdefault("observations", []).extend(new_observations.values())
    records.setdefault("findings", []).extend(new_findings)
    if new_proposals:
        records.setdefault("proposals", []).extend(new_proposals)
    notes = out.get("notes")
    if not isinstance(notes, dict):
        notes = {}
        out["notes"] = notes
    notes["ergo_attach"] = {
        "attached_runs": sorted(new_runs),
        "owner_executions": sum(1 for r in new_runs.values() if not r["cross_profile_evaluation"]),
        "analytical_evaluations": sum(1 for r in new_runs.values() if r["cross_profile_evaluation"]),
        "build_identity_status": "unknown" if any(r["build_id"] == "unknown" for r in receipts_by_snapshot.values()) else "recorded",
        "capture_count": len(receipts_by_snapshot),
        "limitations": list(analysis.get("limitations") or []),
        "basis_note": "Owner-execution findings may verify from measured observations; cross-profile evaluations are "
                      "analytical model coverage and never count as persona executions or verified experiences. "
                      "Counts are simulated-profile coverage, not prevalence.",
    }
    if notes["ergo_attach"]["build_identity_status"] == "unknown":
        notes["ergo_attach"]["build_gap"] = "빌드 ID가 기록되지 않은 캡처입니다. 해당 결과는 미검증 상태이며 같은 빌드의 재현 증거로 사용할 수 없습니다."
    _validate_input_bundle(out)
    _copy_receipts(receipts, copy_plan, run_path)
    return out
