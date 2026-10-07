"""Export swarm results as a ux-evidence-bundle.v1 (spec section 8).

The bundle is accepted by scripts/validate_bundle.py. Findings are ``verified``
only when every linked observation is a measured (observed) value from a
completed run of the same scenario/profile pair **and** that profile is the
run's recorded owner (``owner_profile_id`` from analyze_run); model and judgment
findings stay ``unverified`` with epistemic status ``inferred``. Ownerless
``--device`` captures and analytical cross-profile evaluations are exported as
``cross_profile_evaluation`` runs and can never verify a finding: they are
simulated coverage, not persona executions.
"""

from __future__ import annotations

from typing import Any, Iterable

from .profiles import COVERAGE_STRATA, profile_fingerprint, profile_index


def _persona_record(profile: dict[str, Any], strategy: str, seed: int | None) -> dict[str, Any]:
    ref = profile.get("persona_ref") or {}
    attrs = profile["attributes"]
    assumptions = {field: attrs.get(field) for field in profile.get("assumption_fields", []) if field in attrs}
    filled = [profile["coverage_stratum"]] if profile.get("coverage_stratum") else []
    record = {
        "id": profile["profile_id"],
        "basis": "synthetic",
        "label_ko": profile.get("label_ko", ""),
        "adapter_revision": "ergoqa-profiles/1",
        "schema_fingerprint": profile_fingerprint(profile),
        "seed": seed if seed is not None else 0,
        "shard_or_config": strategy,
        "max_scanned_rows": 0,
        "max_bytes_read": 0,
        "timeout_ms": 0,
        "selected_record_ids": [ref["record_id"]] if ref.get("record_id") else [],
        "filled_strata": filled,
        "unfilled_strata": [],
        "stop_reason": "count_reached",
        "original_attributes": {k: v for k, v in ref.items()},
        "scenario_assumptions": assumptions,
    }
    if profile.get("audience_ref"):
        # Which Stage-0 segment and facet the synthetic profile stands for (still synthetic).
        record["audience_ref"] = profile["audience_ref"]
    return record


def to_evidence_bundle(
    bundle_id: str,
    analyses: Iterable[dict[str, Any]],
    findings: Iterable[dict[str, Any]],
    profiles: Iterable[dict[str, Any]],
    strategy: str = "stratified_coverage",
    seed: int | None = None,
) -> dict[str, Any]:
    analyses = list(analyses)
    findings = list(findings)
    profiles = list(profiles)
    profile_index(profiles)
    personas = [_persona_record(p, strategy, seed) for p in profiles]
    pairs: dict[str, dict[str, Any]] = {}
    runs: dict[str, dict[str, Any]] = {}
    observations: dict[str, dict[str, Any]] = {}
    obs_pair: dict[str, str] = {}
    obs_run_status: dict[str, str] = {}
    obs_profile: dict[str, str] = {}
    obs_owner: dict[str, str | None] = {}
    for analysis in analyses:
        scenario_id = analysis.get("scenario_id") or "unknown"
        # The recorded owner is the identity the run actually executed with; a missing
        # explicit owner (legacy analyses, --device captures) means no evaluation can
        # claim a persona execution, so every evaluation is analytical.
        owner_profile_id = analysis.get("owner_profile_id")
        evaluated = analysis.get("profiles_evaluated", [])
        for pid in dict.fromkeys([*evaluated, *(o["profile_id"] for o in analysis["observations"])]):
            pair_id = f"{scenario_id}@{pid}"
            pairs.setdefault(pair_id, {"id": pair_id, "persona_id": pid, "scenario_ref": scenario_id})
            run_record_id = f"{analysis['run_id']}@{pid}"
            if run_record_id in runs:
                raise ValueError(f"duplicate run evaluation {run_record_id!r}")
            runs[run_record_id] = {
                "id": run_record_id,
                "scenario_id": pair_id,
                "status": str(analysis.get("run_status") or "unknown"),
                "task_success": analysis.get("run_success"),
                "recorded_run_id": analysis["run_id"],
                "cross_profile_evaluation": pid != owner_profile_id,
                "coverage": [key for key, pids in analysis.get("coverage", {}).items() if pid in pids],
            }
        for obs in analysis["observations"]:
            if obs["passed"] or (obs.get("extra") or {}).get("verdict") == "inconclusive":
                continue
            pair_id = f"{scenario_id}@{obs['profile_id']}"
            run_record_id = f"{analysis['run_id']}@{obs['profile_id']}"
            if obs["id"] in observations:
                raise ValueError(f"duplicate observation id {obs['id']!r}")
            observations[obs["id"]] = {
                "id": obs["id"],
                "run_id": run_record_id,
                "epistemic_status": obs["epistemic_status"],
                "basis": obs["basis"],
                "check_id": obs["check_id"],
                "element_key": obs["element_key"],
                "measurement": obs["measurement"],
                "severity": obs["severity"],
                "summary": obs["message_ko"],
            }
            obs_pair[obs["id"]] = pair_id
            obs_run_status[obs["id"]] = runs[run_record_id]["status"]
            obs_profile[obs["id"]] = obs["profile_id"]
            obs_owner[obs["id"]] = owner_profile_id
    bundle_findings: list[dict[str, Any]] = []
    proposals: list[dict[str, Any]] = []
    for finding in findings:
        per_pair: dict[str, list[str]] = {}
        for obs_id in finding["observation_ids"]:
            if obs_id in obs_pair:
                per_pair.setdefault(obs_pair[obs_id], []).append(obs_id)
        ids = []
        for pair_id, obs_ids in sorted(per_pair.items()):
            pair_profile = pairs[pair_id]["persona_id"]
            # Only the profile that executed the run (measured, observed, completed) can
            # verify a finding. Analytical cross-profile and ownerless (--device only)
            # evaluations stay unverified: they are model coverage, never a persona's
            # observed execution of the scenario.
            verified = (
                finding.get("tier") != "hypothesis"
                and all(
                    observations[o]["epistemic_status"] == "observed" and obs_run_status[o] == "completed"
                    and observations[o]["basis"] == "measured" and obs_owner[o] is not None
                    and obs_profile[o] == obs_owner[o] == pair_profile
                    for o in obs_ids
                )
            )
            record_id = f"{finding['id']}@{pairs[pair_id]['persona_id']}"
            ids.append(record_id)
            bundle_findings.append({
                "id": record_id,
                "swarm_finding_id": finding["id"],
                "scenario_id": pair_id,
                "observation_ids": obs_ids,
                "severity": finding["severity"],
                "epistemic_status": "observed" if verified else "inferred",
                "verification_status": "verified" if verified else "unverified",
                "check_id": finding["check_id"],
                "summary": finding["summary_ko"],
                "segments_affected": list(finding.get("segments_affected") or []),
            })
        if ids and finding.get("recommendation_ko"):
            proposals.append({
                "id": f"PR-{finding['id']}",
                "finding_ids": ids,
                "fix_layer": finding["fix_layer"],
                "summary": finding["recommendation_ko"],
            })
    return {
        "schema_version": "ux-evidence-bundle.v1",
        "bundle_id": bundle_id,
        "permissions": {"requested": ["read_only"], "granted": ["read_only"], "blocked": []},
        "records": {
            "sources": [], "evidence": [], "claims": [],
            "personas": personas,
            "scenarios": list(pairs.values()),
            "runs": list(runs.values()),
            "observations": list(observations.values()),
            "findings": bundle_findings,
            "proposals": proposals,
            "figma": [],
        },
        "notes": {
            "coverage_strata": [name for name, _ in COVERAGE_STRATA],
            "prevalence": "Synthetic ergonomic profiles give coverage, not prevalence.",
            "limitations": sorted({line for analysis in analyses for line in analysis.get("limitations", [])}),
        },
    }
