"""Versioned graph validation, independent from execution and permissions."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from scripts.validate_bundle import RECORD_NAMES, validate_bundle
from .io import ContractError, digest, load_json, safe_relative, timestamp
from .schema import validate

SCHEMA = Path(__file__).resolve().parents[1] / "schemas" / "ux-loop.v1.schema.json"
COLLECTIONS = ("scenarios", "artifacts", "browser_runs", "visual_checks", "fixes", "rounds", "replays")
REQUIRED_A11Y = {"keyboard", "focus", "semantics"}


def index(items: list[dict]) -> dict[str, dict]:
    return {item["id"]: item for item in items}


def validate_packet(packet: Any) -> list[str]:
    errors = validate(packet, load_json(SCHEMA))
    if errors:
        return errors
    errors.extend(validate_bundle(packet["bundle"]))
    if errors:
        return errors
    minimized = packet["bundle"].get("minimized_from")
    if minimized and minimized.get("mode") != packet["mode"]:
        errors.append("bundle.minimized_from.mode must match the consuming loop mode")
    if set(packet["bundle"]["records"]) != set(RECORD_NAMES):
        return ["bundle.records: unexpected record collection"]
    maps = {key: index(packet[key]) for key in COLLECTIONS}
    records = {key: index(value) for key, value in packet["bundle"]["records"].items() if isinstance(value, list)}
    for key in COLLECTIONS:
        if len(maps[key]) != len(packet[key]):
            errors.append(f"{key}: duplicate id")

    def need(value: Any, target: dict, where: str) -> dict:
        if value not in target:
            errors.append(f"{where}: unknown record {value!r}")
            return {}
        return target[value]

    def artifact(value: Any, kinds: set[str], where: str, required: bool = True) -> None:
        if value is None:
            if required:
                errors.append(f"{where}: artifact is required")
            return
        item = need(value, maps["artifacts"], where)
        if item and item["kind"] not in kinds:
            errors.append(f"{where}: wrong artifact kind")

    goal = packet["goal"]
    context_binding = goal.get("product_context_artifact_id")
    if context_binding is not None:
        artifact(context_binding, {"product_context"}, "goal.product_context_artifact_id")
    if set(goal["scenario_ids"]) != set(maps["scenarios"]):
        errors.append("goal.scenario_ids must exactly cover the explicit scenario matrix")
    for name in goal["code_paths"]:
        try:
            safe_relative(name)
        except ContractError as exc:
            errors.append(str(exc))
    for evidence_id in goal["evidence_ids"]:
        need(evidence_id, records["evidence"], "goal.evidence_ids")
    # The loop retains metadata and authored summaries, never raw community dumps.
    for group in ("sources", "evidence"):
        for record in records[group].values():
            if set(record) & {"excerpt", "raw", "raw_html", "raw_content", "body"}:
                errors.append(f"{group}.{record['id']}: minimize raw/excerpt content before loop intake")
    for claim in records["claims"].values():
        if claim.get("verification_status") == "verified" and claim.get("claim_kind") in {
            "prevalence", "user_preference", "real_user_preference", "discomfort"
        }:
            for evidence_id in claim["evidence_ids"]:
                evidence = records["evidence"][evidence_id]
                if evidence.get("evidence_type") != "quantitative" or claim.get("support_basis") != "measured_sample":
                    errors.append(f"claim {claim['id']}: community/persona signals do not prove preference or prevalence")
    for scenario in maps["scenarios"].values():
        need(scenario["id"], records["scenarios"], "scenario")
        try:
            parsed = urlsplit(scenario["origin"])
            _ = parsed.port
        except ValueError:
            errors.append(f"scenario {scenario['id']}: malformed origin")
            continue
        native = parsed.scheme in {"ios-app", "android-app"}
        common_invalid = (not parsed.hostname or parsed.username or parsed.password
                          or parsed.path not in {"", "/"} or parsed.query or parsed.fragment)
        if native:
            # Application identity, never a screenshot viewer or backend origin.
            if (scenario["origin"] not in {f"{parsed.scheme}://{parsed.netloc}", f"{parsed.scheme}://{parsed.netloc}/"}
                    or common_invalid or parsed.port is not None or not re.fullmatch(
                    r"[A-Za-z][A-Za-z0-9_-]*(?:\.[A-Za-z][A-Za-z0-9_-]*)+", parsed.netloc)):
                errors.append(f"scenario {scenario['id']}: expected a credential-free native application origin")
        elif parsed.scheme not in {"http", "https"} or common_invalid:
            errors.append(f"scenario {scenario['id']}: expected a credential-free HTTP(S) origin")
        if not scenario["route"].startswith("/") or scenario["route"].startswith("//"):
            errors.append(f"scenario {scenario['id']}: expected an origin-relative route")
        if len({x["id"] for x in scenario["steps"]}) != len(scenario["steps"]):
            errors.append(f"scenario {scenario['id']}: duplicate step id")
        if not REQUIRED_A11Y <= set(scenario["a11y_checks"]):
            errors.append(f"scenario {scenario['id']}: keyboard/focus/semantics coverage is mandatory")
    for item in maps["artifacts"].values():
        try:
            safe_relative(item["path"])
            timestamp(item["created_at"])
        except ContractError as exc:
            errors.append(str(exc))
        if item["provenance"] != packet["mode"]:
            errors.append(f"artifact {item['id']}: fixture/live provenance mismatch")
    paths = [x["path"] for x in packet["artifacts"]]
    if len(set(paths)) != len(paths):
        errors.append("artifact paths must be unique and immutable per artifact id")
    for figma in records["figma"].values():
        artifact(figma.get("readback_artifact_ref"), {"figma_readback"}, f"figma {figma['id']}")
        try:
            timestamp(figma["read_at"])
        except ContractError as exc:
            errors.append(str(exc))
        if figma.get("baseline_version") != figma.get("readback_version"):
            errors.append(f"figma {figma['id']}: versioned readback is required")
    sessions: set[str] = set()
    for run in maps["browser_runs"].values():
        legacy = need(run["id"], records["runs"], "browser run")
        scenario = need(run["scenario_id"], maps["scenarios"], "browser run scenario")
        if legacy and legacy["scenario_id"] != run["scenario_id"]:
            errors.append(f"run {run['id']}: v1 scenario mismatch")
        if run["execution"] != packet["mode"]:
            errors.append(f"run {run['id']}: fixture/live mismatch")
        env = run["environment"]
        if env["session_id"] in sessions:
            errors.append("browser sessions must be isolated per run")
        sessions.add(env["session_id"])
        if scenario:
            tool = run["tool"]
            try:
                native_origin = urlsplit(scenario["origin"])
            except ValueError:
                continue  # Malformed origin already reported by scenario validation.
            scheme = native_origin.scheme
            platform = {"ios-app": "ios", "android-app": "android"}.get(scheme, "web")
            if platform == "web":
                if tool.get("platform", "web") != "web" or not tool.get("browser") or not tool.get("browser_version") or any(
                        key in tool for key in ("os_version", "application_id")):
                    errors.append(f"run {run['id']}: web surface requires browser identity only")
            elif (tool.get("platform") != platform or not tool.get("os_version")
                  or tool.get("application_id") != native_origin.netloc
                  or any(key in tool for key in ("browser", "browser_version"))):
                errors.append(f"run {run['id']}: native surface requires matching platform/application and OS identity, without browser fields")
            if legacy.get("surface_ref") != scenario["origin"].rstrip("/") + scenario["route"]:
                errors.append(f"run {run['id']}: v1 surface_ref mismatch")
            if run["scenario_digest"] != digest(scenario):
                errors.append(f"run {run['id']}: changed scenario digest")
            expected = {k: scenario[k] for k in ("origin", "route", "viewport", "device")}
            expected.update({"fixture_id": scenario["fixture"]["id"],
                             "fixture_revision": scenario["fixture"]["revision"],
                             "account_ref": scenario["fixture"]["account_ref"]})
            if any(env[k] != v for k, v in expected.items()):
                errors.append(f"run {run['id']}: route/device/fixture mismatch")
        observed = run["outcome"] in {"passed", "failed"}
        if observed and (run["epistemic_status"] != "observed" or legacy.get("status") != "completed"):
            errors.append(f"run {run['id']}: executed outcomes require observed completed runs")
        if run["outcome"] != "passed" and not run["reason"].strip():
            errors.append(f"run {run['id']}: non-pass requires a reason")
        try:
            if timestamp(run["ended_at"]) < timestamp(run["started_at"]):
                errors.append(f"run {run['id']}: end before start")
        except ContractError as exc:
            errors.append(str(exc))
        for kind, value in run["evidence"].items():
            artifact(value, {kind}, f"run {run['id']} {kind}", observed)
        step_ids = [x["step_id"] for x in run["steps"]]
        a11y_names = [x["name"] for x in run["accessibility"]]
        if len(step_ids) != len(set(step_ids)) or len(a11y_names) != len(set(a11y_names)):
            errors.append(f"run {run['id']}: duplicate step/accessibility result")
        if observed and scenario:
            if step_ids != [x["id"] for x in scenario["steps"]]:
                errors.append(f"run {run['id']}: complete ordered scenario steps required")
            if set(a11y_names) != set(scenario["a11y_checks"]):
                errors.append(f"run {run['id']}: incomplete accessibility coverage")
        for step in run["steps"]:
            for value in step["artifact_ids"]:
                artifact(value, {"steps"}, "step result")
            if run["outcome"] == "passed" and step["outcome"] != "passed":
                errors.append(f"run {run['id']}: pass contradicts failed/unknown step")
        for check in run["accessibility"]:
            artifact(check["artifact_id"], {"accessibility"}, "accessibility", check["status"] in {"passed", "failed"})
    for finding in records["findings"].values():
        if finding["scenario_id"] not in maps["scenarios"]:
            errors.append(f"finding {finding['id']}: outside goal scenario scope")
        if finding.get("severity") not in {"P0", "P1", "P2", "P3"}:
            errors.append(f"finding {finding['id']}: severity P0-P3 required")
        for obs_id in finding["observation_ids"]:
            obs = records["observations"][obs_id]
            run = need(obs["run_id"], maps["browser_runs"], "finding browser observation")
            if run and finding.get("verification_status") == "verified" and run["outcome"] not in {"passed", "failed"}:
                errors.append(f"finding {finding['id']}: unexecuted run cannot verify finding")
    for visual in maps["visual_checks"].values():
        run = need(visual["run_id"], maps["browser_runs"], "visual run")
        figma = need(visual["figma_id"], records["figma"], "visual figma")
        if run and any(visual[k] != run["environment"][k] for k in ("route", "viewport")):
            errors.append(f"visual {visual['id']}: capture route/viewport mismatch")
        if figma:
            for key in ("file_key", "branch_key", "baseline_version", "readback_version"):
                if visual[key] != figma.get(key):
                    errors.append(f"visual {visual['id']}: pinned Figma {key} mismatch")
            if not set(visual["node_ids"]) <= set(figma["node_ids"]):
                errors.append(f"visual {visual['id']}: unknown Figma node")
        for key, kind in (("actual_artifact_id", "screenshot"), ("reference_artifact_id", "screenshot"), ("comparison_artifact_id", "visual_report")):
            artifact(visual[key], {kind}, f"visual {visual['id']} {key}", visual["status"] in {"passed", "failed"})
        if visual["status"] == "passed" and any(x != "passed" for x in visual["checks"].values()):
            errors.append(f"visual {visual['id']}: pass contradicts comparison checks")
        if visual["status"] != "passed" and not visual["reason"].strip():
            errors.append(f"visual {visual['id']}: non-pass requires a reason")
    for fix in maps["fixes"].values():
        proposal = need(fix["proposal_id"], records["proposals"], "fix proposal")
        need(fix["figma_id"], records["figma"], "fix Figma-first baseline")
        if proposal and not set(fix["finding_ids"]) <= set(proposal["finding_ids"]):
            errors.append(f"fix {fix['id']}: findings do not belong to proposal")
        for finding_id in fix["finding_ids"]:
            need(finding_id, records["findings"], "fix finding")
        if fix["before_revision"] == fix["after_revision"]:
            errors.append(f"fix {fix['id']}: no-op change cannot be accepted as a fix")
        if fix["kind"] == "code_write":
            artifact(fix["patch_artifact_id"], {"code_patch"}, "code fix patch")
            if not fix["changed_paths"] or not set(fix["changed_paths"]) <= set(goal["code_paths"]):
                errors.append(f"fix {fix['id']}: changed paths exceed explicit code scope")
        acks = fix.get("constraint_acknowledgements") or []
        resolutions = fix.get("conflict_resolutions") or []
        if (acks or resolutions) and context_binding is None:
            errors.append(f"fix {fix['id']}: intent acknowledgements require the goal product_context_artifact_id binding")
        if len({x["constraint_id"] for x in acks}) != len(acks):
            errors.append(f"fix {fix['id']}: duplicate constraint acknowledgement")
        if len({x["conflict_id"] for x in resolutions}) != len(resolutions):
            errors.append(f"fix {fix['id']}: duplicate conflict resolution")
    numbers = [x["number"] for x in packet["rounds"]]
    if numbers != list(range(1, len(numbers) + 1)) or len(numbers) > goal["max_iterations"]:
        errors.append("rounds must be contiguous, ordered and within max_iterations")
    used_fixes: set[str] = set()
    for round_ in packet["rounds"]:
        for run_id in round_["baseline_run_ids"]:
            need(run_id, maps["browser_runs"], "round baseline")
        for fix_id in round_["fix_ids"]:
            need(fix_id, maps["fixes"], "round fix")
            if fix_id in used_fixes:
                errors.append("a fix id may be attempted in only one round")
            used_fixes.add(fix_id)
    replay_rounds: set[str] = set()
    for replay in packet["replays"]:
        need(replay["round_id"], maps["rounds"], "replay round")
        if replay["round_id"] in replay_rounds:
            errors.append("one immutable replay per round; retry requires a new bounded round")
        replay_rounds.add(replay["round_id"])
        review_id = replay.get("intent_review_artifact_id")
        if review_id is not None:
            artifact(review_id, {"intent_review"}, f"replay {replay['id']} intent review")
            if context_binding is None:
                errors.append(f"replay {replay['id']}: intent review requires the goal product_context_artifact_id binding")
        for run_id in replay["run_ids"]:
            run = need(run_id, maps["browser_runs"], "replay run")
            if run and run["phase"] != "replay":
                errors.append("baseline capture is not a replay")
        regression = replay["regression"]
        if set(regression["scenario_ids"]) != set(goal["scenario_ids"]):
            errors.append("regression must cover every goal scenario")
        artifact(regression["artifact_id"], {"regression"}, "regression", regression["status"] in {"passed", "failed"})
    return errors


def require_packet(packet: Any) -> None:
    errors = validate_packet(packet)
    if errors:
        raise ContractError("\n".join(errors))


def merge_packet(old: dict, new: dict) -> dict:
    """Append only. Goal changes require a new checkpoint, never silent re-scoping."""
    require_packet(new)
    for key in ("schema_version", "mode", "goal", "policy", "scenarios"):
        if old[key] != new[key]:
            raise ContractError(f"Resume cannot change immutable {key}")
    for key in ("schema_version", "bundle_id", "permissions"):
        if old["bundle"][key] != new["bundle"][key]:
            raise ContractError(f"Resume cannot change historical bundle.{key}")
    pairs = [(key, old[key], new[key]) for key in COLLECTIONS]
    pairs += [("bundle." + key, value, new["bundle"]["records"][key])
              for key, value in old["bundle"]["records"].items()]
    for name, previous, updated in pairs:
        if updated[:len(previous)] != previous:
            raise ContractError(f"Append-only violation in {name}; evidence IDs cannot be rewritten/deleted/reordered")
    return new
