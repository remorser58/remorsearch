#!/usr/bin/env python3
"""Validate the UX evidence bundle contract without external dependencies."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


CAPABILITIES = {"read_only", "design_write", "test_data_write", "code_write"}
EPISTEMIC_STATUSES = {"observed", "inferred", "unknown"}
VERIFIED_STATUSES = {"verified", "unverified", "proposed"}
WITHDRAWN_SOURCE_STATES = {"withdrawn", "deleted"}
RECORD_NAMES = (
    "sources",
    "evidence",
    "claims",
    "personas",
    "scenarios",
    "runs",
    "observations",
    "findings",
    "proposals",
    "figma",
)


def _records(bundle: dict[str, Any], name: str) -> list[dict[str, Any]]:
    records = bundle.get("records")
    if not isinstance(records, dict):
        return []
    values = records.get(name, [])
    if not isinstance(values, list):
        return []
    return [value for value in values if isinstance(value, dict)]


def _index(bundle: dict[str, Any], name: str, errors: list[str]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    raw_records = bundle.get("records")
    values = raw_records.get(name) if isinstance(raw_records, dict) else None
    if not isinstance(values, list):
        errors.append(f"records.{name} must be an array")
        return indexed
    for position, record in enumerate(values):
        if not isinstance(record, dict):
            errors.append(f"records.{name}[{position}] must be an object")
            continue
        record_id = record.get("id")
        if not isinstance(record_id, str) or not record_id.strip():
            errors.append(f"records.{name}[{position}].id is required")
            continue
        if record_id in indexed:
            errors.append(f"records.{name} contains duplicate id {record_id}")
            continue
        indexed[record_id] = record
    return indexed


def _require_ref(
    value: Any,
    target: dict[str, dict[str, Any]],
    location: str,
    errors: list[str],
) -> None:
    if not isinstance(value, str) or value not in target:
        errors.append(f"{location} references an unknown record")


def _require_ref_list(
    value: Any,
    target: dict[str, dict[str, Any]],
    location: str,
    errors: list[str],
    *, allow_empty: bool = False,
) -> None:
    if not isinstance(value, list) or (not allow_empty and not value):
        errors.append(f"{location} must contain at least one record id")
        return
    for index, item in enumerate(value):
        _require_ref(item, target, f"{location}[{index}]", errors)


def _validate_permissions(bundle: dict[str, Any], errors: list[str]) -> None:
    permissions = bundle.get("permissions")
    if not isinstance(permissions, dict):
        errors.append("permissions must be an object")
        return
    requested = permissions.get("requested")
    granted = permissions.get("granted")
    blocked = permissions.get("blocked")
    if not isinstance(requested, list) or not requested:
        errors.append("permissions.requested must be a non-empty array")
        requested = []
    if not isinstance(granted, list):
        errors.append("permissions.granted must be an array")
        granted = []
    if not isinstance(blocked, list):
        errors.append("permissions.blocked must be an array")
        blocked = []
    for capability in [*requested, *granted]:
        if capability not in CAPABILITIES:
            errors.append(f"unknown permission capability {capability!r}")
    if len(set(requested)) != len(requested):
        errors.append("permissions.requested must not contain duplicates")
    if len(set(granted)) != len(granted):
        errors.append("permissions.granted must not contain duplicates")
    for capability in granted:
        if capability not in requested:
            errors.append(f"granted permission {capability!r} was not requested")
    blocked_capabilities: set[str] = set()
    for index, entry in enumerate(blocked):
        if not isinstance(entry, dict):
            errors.append(f"permissions.blocked[{index}] must be an object")
            continue
        capability = entry.get("capability")
        reason = entry.get("reason")
        if capability not in CAPABILITIES:
            errors.append(f"permissions.blocked[{index}].capability is invalid")
        if not isinstance(reason, str) or not reason.strip():
            errors.append(f"permissions.blocked[{index}].reason is required")
        if isinstance(capability, str):
            blocked_capabilities.add(capability)
            if capability not in requested:
                errors.append(f"blocked permission {capability!r} was not requested")
            if capability in granted:
                errors.append(f"permission {capability!r} cannot be granted and blocked")
    for capability in requested:
        if capability not in granted and capability not in blocked_capabilities:
            errors.append(f"unresolved permission {capability!r} must be granted or blocked")


def _validate_sources(sources: dict[str, dict[str, Any]], errors: list[str]) -> None:
    required = ("channel", "source_ref", "access_basis", "access_method", "public_scope", "retention_status")
    for source_id, source in sources.items():
        for field in required:
            value = source.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"records.sources[{source_id}].{field} is required")


def _retention_end(value: str) -> datetime | None:
    """When a retention_until value runs out: an ISO 8601 date-time (UTC when it has no offset), or a date,
    which is kept through that day (UTC). None when the value is neither."""
    text = value.strip()
    try:
        if len(text) == 10:
            return datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=timezone.utc) + timedelta(days=1)
        moment = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text)
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _validate_retention(sources: dict[str, dict[str, Any]], errors: list[str], now: datetime) -> None:
    """Items read through an official API carry retention_until, and none is kept past it: the reader only
    stamps the date, so an expired item in a bundle is an error until it is deleted or read again."""
    for source_id, source in sources.items():
        until = source.get("retention_until")
        if until is None:
            if source.get("access_basis") == "official_api":
                errors.append(f"records.sources[{source_id}].retention_until is required for an official_api source")
            continue
        end = _retention_end(until) if isinstance(until, str) else None
        if end is None:
            errors.append(f"records.sources[{source_id}].retention_until must be an ISO 8601 date or date-time")
        elif end <= now:
            errors.append(f"records.sources[{source_id}].retention_until {until} has passed: delete the item, "
                          "or read it again and update the date")


def _validate_personas(personas: dict[str, dict[str, Any]], errors: list[str]) -> None:
    required = (
        "adapter_revision",
        "schema_fingerprint",
        "seed",
        "shard_or_config",
        "max_scanned_rows",
        "max_bytes_read",
        "timeout_ms",
        "selected_record_ids",
        "filled_strata",
        "unfilled_strata",
        "stop_reason",
        "original_attributes",
        "scenario_assumptions",
    )
    for persona_id, persona in personas.items():
        if persona.get("basis") != "synthetic":
            continue
        for field in required:
            if field not in persona:
                errors.append(f"records.personas[{persona_id}].{field} is required for synthetic personas")
        for field in ("max_scanned_rows", "max_bytes_read", "timeout_ms"):
            value = persona.get(field)
            if not isinstance(value, int) or value < 0:
                errors.append(f"records.personas[{persona_id}].{field} must be a non-negative integer")
        if not isinstance(persona.get("selected_record_ids"), list):
            errors.append(f"records.personas[{persona_id}].selected_record_ids must be an array")
        if not isinstance(persona.get("filled_strata"), list):
            errors.append(f"records.personas[{persona_id}].filled_strata must be an array")
        if not isinstance(persona.get("unfilled_strata"), list):
            errors.append(f"records.personas[{persona_id}].unfilled_strata must be an array")
        if not isinstance(persona.get("original_attributes"), dict):
            errors.append(f"records.personas[{persona_id}].original_attributes must be an object")
        if not isinstance(persona.get("scenario_assumptions"), dict):
            errors.append(f"records.personas[{persona_id}].scenario_assumptions must be an object")


def _validate_links(
    sources: dict[str, dict[str, Any]],
    evidence: dict[str, dict[str, Any]],
    claims: dict[str, dict[str, Any]],
    personas: dict[str, dict[str, Any]],
    scenarios: dict[str, dict[str, Any]],
    runs: dict[str, dict[str, Any]],
    observations: dict[str, dict[str, Any]],
    findings: dict[str, dict[str, Any]],
    proposals: dict[str, dict[str, Any]],
    figma: dict[str, dict[str, Any]],
    errors: list[str],
    *, research: bool = False,
) -> None:
    for evidence_id, item in evidence.items():
        _require_ref(item.get("source_id"), sources, f"records.evidence[{evidence_id}].source_id", errors)
    for claim_id, item in claims.items():
        _require_ref_list(item.get("evidence_ids"), evidence, f"records.claims[{claim_id}].evidence_ids", errors,
                          allow_empty=bool(research or item.get("claim_kind") == "product_behavior" or "research_support_evidence_ids" in item))
        for name, target in (("observation_ids", observations), ("counter_evidence_ids", evidence), ("context_evidence_ids", evidence), ("research_support_evidence_ids", evidence), ("research_context_evidence_ids", evidence)):
            if name in item:
                _require_ref_list(item[name], target, f"records.claims[{claim_id}].{name}", errors, allow_empty=True)
        counter = item.get("counter_search")
        if counter is not None:
            if not isinstance(counter, dict):
                errors.append(f"records.claims[{claim_id}].counter_search must be an object")
            else:
                for name, target in (("read_source_ids", sources), ("counter_evidence_ids", evidence)):
                    _require_ref_list(counter.get(name), target, f"records.claims[{claim_id}].counter_search.{name}", errors, allow_empty=True)
        if "persona_ids" in item:
            _require_ref_list(item.get("persona_ids"), personas, f"records.claims[{claim_id}].persona_ids", errors)
    for scenario_id, item in scenarios.items():
        _require_ref(item.get("persona_id"), personas, f"records.scenarios[{scenario_id}].persona_id", errors)
        if "motivation_claim_ids" in item:
            _require_ref_list(item["motivation_claim_ids"], claims, f"records.scenarios[{scenario_id}].motivation_claim_ids", errors, allow_empty=True)
    for run_id, item in runs.items():
        _require_ref(item.get("scenario_id"), scenarios, f"records.runs[{run_id}].scenario_id", errors)
    for observation_id, item in observations.items():
        _require_ref(item.get("run_id"), runs, f"records.observations[{observation_id}].run_id", errors)
    for finding_id, item in findings.items():
        _require_ref(item.get("scenario_id"), scenarios, f"records.findings[{finding_id}].scenario_id", errors)
        _require_ref_list(item.get("observation_ids"), observations, f"records.findings[{finding_id}].observation_ids", errors)
        if "claim_ids" in item:
            _require_ref_list(item.get("claim_ids"), claims, f"records.findings[{finding_id}].claim_ids", errors, allow_empty=True)
        if "figma_id" in item:
            _require_ref(item.get("figma_id"), figma, f"records.findings[{finding_id}].figma_id", errors)
    for proposal_id, item in proposals.items():
        _require_ref_list(item.get("finding_ids"), findings, f"records.proposals[{proposal_id}].finding_ids", errors)
        if "figma_id" in item:
            _require_ref(item.get("figma_id"), figma, f"records.proposals[{proposal_id}].figma_id", errors)


def _validate_semantics(
    evidence: dict[str, dict[str, Any]],
    claims: dict[str, dict[str, Any]],
    personas: dict[str, dict[str, Any]],
    observations: dict[str, dict[str, Any]],
    findings: dict[str, dict[str, Any]],
    sources: dict[str, dict[str, Any]],
    figma: dict[str, dict[str, Any]],
    errors: list[str],
) -> None:
    for record_type, records in (("evidence", evidence), ("claims", claims), ("observations", observations), ("findings", findings)):
        for record_id, item in records.items():
            status = item.get("epistemic_status")
            if status not in EPISTEMIC_STATUSES:
                errors.append(f"records.{record_type}[{record_id}].epistemic_status is invalid")

    for claim_id, claim in claims.items():
        verification_status = claim.get("verification_status", "unverified")
        if verification_status not in VERIFIED_STATUSES:
            errors.append(f"records.claims[{claim_id}].verification_status is invalid")
        evidence_ids = claim.get("evidence_ids") if isinstance(claim.get("evidence_ids"), list) else []
        supporting = [evidence[evidence_id] for evidence_id in evidence_ids if evidence_id in evidence]
        synthetic_persona_ids = {
            persona_id for persona_id in claim.get("persona_ids", [])
            if persona_id in personas and personas[persona_id].get("basis") == "synthetic"
        }
        preference_kind = claim.get("claim_kind") in {"user_preference", "real_user_preference", "prevalence", "discomfort"}
        if preference_kind and synthetic_persona_ids:
            errors.append(f"records.claims[{claim_id}] uses a synthetic persona as direct real-user support")
        if preference_kind and claim.get("support_basis") == "synthetic_persona":
            errors.append(f"records.claims[{claim_id}] cannot use synthetic_persona support for a real-user claim")
        if verification_status == "verified":
            if claim.get("epistemic_status") != "observed":
                errors.append(f"records.claims[{claim_id}] cannot be verified from non-observed epistemic status")
            if claim.get("claim_kind") != "product_behavior" and (not supporting or any(item.get("epistemic_status") != "observed" for item in supporting)):
                errors.append(f"records.claims[{claim_id}] requires observed evidence for verification")
            if any(sources.get(item.get("source_id"), {}).get("retention_status") in WITHDRAWN_SOURCE_STATES for item in supporting):
                errors.append(f"records.claims[{claim_id}] uses withdrawn or deleted source material")

    for finding_id, finding in findings.items():
        if finding.get("verification_status") == "verified":
            observation_ids = finding.get("observation_ids")
            linked = [observations[observation_id] for observation_id in observation_ids if observation_id in observations] if isinstance(observation_ids, list) else []
            if not linked:
                errors.append(f"records.findings[{finding_id}] cannot be verified without an observation")
            elif any(item.get("epistemic_status") != "observed" for item in linked):
                errors.append(f"records.findings[{finding_id}] requires observed product observations for verification")

    for figma_id, item in figma.items():
        required = ("file_key", "branch_key", "baseline_version", "node_ids", "read_at", "design_status")
        for field in required:
            if field not in item or item[field] in (None, "", []):
                errors.append(f"records.figma[{figma_id}].{field} is required")
        if not isinstance(item.get("node_ids"), list) or not item.get("node_ids"):
            errors.append(f"records.figma[{figma_id}].node_ids must be a non-empty array")
        design_status = item.get("design_status")
        if design_status in {"comparison_ready", "approved", "implemented"} and not item.get("readback_artifact_ref"):
            errors.append(f"records.figma[{figma_id}].readback_artifact_ref is required for {design_status}")
        readback_version = item.get("readback_version")
        if readback_version and readback_version != item.get("baseline_version") and design_status in {"comparison_ready", "approved", "implemented"}:
            errors.append(f"records.figma[{figma_id}] has a baseline/readback version conflict")
        defect_class = item.get("defect_class")
        if defect_class and defect_class not in {"implementation_defect", "design_defect", "spec_conflict", "approved_deviation"}:
            errors.append(f"records.figma[{figma_id}].defect_class is invalid")


def _input_shapes(bundle: dict[str, Any]) -> list[str]:
    """Reject malformed optional fields before set membership / reference lookups."""
    errors: list[str] = []
    permissions = bundle.get("permissions", {})
    if isinstance(permissions, dict):
        for name in ("requested", "granted"):
            values = permissions.get(name, [])
            if isinstance(values, list) and any(not isinstance(x, str) for x in values):
                errors.append(f"permissions.{name} entries must be strings")
        blocked = permissions.get("blocked", [])
        if isinstance(blocked, list):
            for item in blocked:
                if isinstance(item, dict) and not isinstance(item.get("capability"), str):
                    errors.append("permissions.blocked capability must be a string")
    records = bundle.get("records", {})
    if not isinstance(records, dict):
        return errors
    string_fields = {"id", "source_id", "persona_id", "scenario_id", "run_id", "figma_id",
                     "epistemic_status", "verification_status", "claim_kind", "support_basis",
                     "basis", "retention_status", "design_status", "defect_class",
                     "baseline_version", "readback_version", "severity", "readback_artifact_ref",
                     "file_key", "branch_key", "read_at", "status"}
    list_fields = {"evidence_ids", "persona_ids", "observation_ids", "claim_ids", "finding_ids", "node_ids"}
    for name in RECORD_NAMES:
        values = records.get(name, [])
        if not isinstance(values, list):
            continue
        for i, item in enumerate(values):
            if not isinstance(item, dict):
                continue
            for key in string_fields & item.keys():
                if not isinstance(item[key], str):
                    errors.append(f"records.{name}[{i}].{key} must be a string")
            for key in list_fields & item.keys():
                if not isinstance(item[key], list) or any(not isinstance(x, str) for x in item[key]):
                    errors.append(f"records.{name}[{i}].{key} must be an array of strings")
    return errors


def _validate_bundle(bundle: Any, *, now: datetime | None = None) -> list[str]:
    """Every contract error in the bundle (empty when it is valid). `now` is the moment retention dates are
    checked against (default: the current time)."""
    errors: list[str] = []
    if not isinstance(bundle, dict):
        return ["bundle must be a JSON object"]
    shape_errors = _input_shapes(bundle)
    if shape_errors:
        return shape_errors
    if bundle.get("schema_version") != "ux-evidence-bundle.v1":
        errors.append("schema_version must be ux-evidence-bundle.v1")
    if not isinstance(bundle.get("bundle_id"), str) or not bundle.get("bundle_id", "").strip():
        errors.append("bundle_id is required")
    records = bundle.get("records")
    if not isinstance(records, dict):
        errors.append("records must be an object")
        return errors
    _validate_permissions(bundle, errors)
    indexed = {name: _index(bundle, name, errors) for name in RECORD_NAMES}
    all_ids = [record_id for records in indexed.values() for record_id in records]
    if len(set(all_ids)) != len(all_ids):
        errors.append("record ids must be globally unique")
    for finding_id, finding in indexed["findings"].items():
        status = finding.get("verification_status", "unverified")
        if status not in VERIFIED_STATUSES:
            errors.append(f"records.findings[{finding_id}].verification_status is invalid")
        if status == "verified":
            if finding.get("epistemic_status") != "observed":
                errors.append(f"records.findings[{finding_id}] requires observed epistemic status")
            for observation_id in finding.get("observation_ids", []):
                observation = indexed["observations"].get(observation_id, {})
                run = indexed["runs"].get(observation.get("run_id"), {})
                if run.get("status") != "completed" or run.get("scenario_id") != finding.get("scenario_id"):
                    errors.append(f"records.findings[{finding_id}] requires a completed same-scenario run")
    _validate_sources(indexed["sources"], errors)
    _validate_retention(indexed["sources"], errors, now or datetime.now(timezone.utc))
    _validate_personas(indexed["personas"], errors)
    _validate_links(*(indexed[name] for name in RECORD_NAMES), errors, research=research_bundle(bundle) or "minimized_from" in bundle)
    _validate_semantics(
        indexed["evidence"],
        indexed["claims"],
        indexed["personas"],
        indexed["observations"],
        indexed["findings"],
        indexed["sources"],
        indexed["figma"],
        errors,
    )
    return errors



def scope_matches(constraints, facts):
    return isinstance(facts, dict) and all(value is None or facts.get(key) == value for key, value in (constraints or {}).items())


def eligible_observations(bundle, claim, *, require_scope=False):
    records = bundle.get("records", {})
    maps = {k: {x["id"]: x for x in records.get(k, []) if isinstance(x, dict) and isinstance(x.get("id"), str)} for k in ("observations", "runs", "scenarios")}
    good = []
    for oid in claim.get("observation_ids", []):
        obs = maps["observations"].get(oid, {})
        run = maps["runs"].get(obs.get("run_id"), {})
        scenario = maps["scenarios"].get(run.get("scenario_id"), {})
        if not obs or obs.get("epistemic_status") != "observed" or not obs.get("result") or run.get("status") != "completed" or not scenario:
            continue
        if require_scope:
            if not isinstance(obs.get("scope"), dict) or obs["scope"].get("product_relation") != "product_surface":
                continue
            if not scope_matches(claim.get("scope"), obs["scope"]) or not scope_matches(claim.get("scope"), run.get("scope")) or not scope_matches(claim.get("scope"), scenario.get("scope")):
                continue
            subject = claim.get("subject", {})
            if any(subject.get(k) is not None and scenario.get(k) != subject[k] for k in ("segment_id", "task_id", "context_id")):
                continue
        good.append(oid)
    return sorted(good)


def research_bundle(bundle):
    if "research" in bundle:
        return True
    for group in ("sources", "claims", "personas", "scenarios"):
        for record in _records(bundle, group):
            if any(k in record for k in ("provenance", "access", "research_support_evidence_ids", "research_context_evidence_ids", "audience_ref")) or record.get("access_basis") in {"public_anonymous", "authorised_member", "team_provided"}:
                return True
    return False


def bundle_warnings(bundle):
    if not isinstance(bundle, dict):
        return []
    return [f"records.claims[{c['id']}] legacy product verification has no completed observed run" for c in _records(bundle, "claims") if c.get("claim_kind") == "product_behavior" and c.get("verification_status") == "verified" and not eligible_observations(bundle, c)]


def _extra_checks(bundle, now):
    from uxresearch.schema import Resolver
    from uxresearch.canonical import EngineError
    errors = Resolver().validate(bundle, "ux-evidence-bundle.v1.schema.json")
    if errors:
        return errors
    records = bundle["records"]
    maps = {k: {x["id"]: x for x in records[k]} for k in RECORD_NAMES}
    research = research_bundle(bundle)
    for source in maps["sources"].values():
        tomb = source.get("research_tombstone")
        if tomb:
            allowed = {"id", "channel", "source_ref", "access_basis", "access_method", "public_scope", "retention_status", "research_tombstone"}
            if set(source) != allowed:
                errors.append("Source tombstone retains content or unknown fields")
        elif source.get("retention_status") in {"deleted", "withdrawn"} and any(k in source for k in ("excerpt", "body", "raw", "text", "title", "summary", "captures")):
            errors.append("Deleted or withdrawn source retains content")
        for capture in source.get("captures", []):
            metadata = capture.get("metadata", {})
            until = metadata.get("retention_until")
            if until is not None:
                end = _retention_end(until) if isinstance(until, str) else None
                if end is None or end <= now:
                    errors.append("A source capture retains expired content")
    for claim in maps["claims"].values():
        if claim.get("verification_status") == "verified" and claim.get("claim_kind") == "product_behavior":
            if research and not eligible_observations(bundle, claim, require_scope=True):
                errors.append("Research product_behavior requires completed observed same-scope product observations")
            elif not research and not eligible_observations(bundle, claim) and not claim.get("evidence_ids"):
                errors.append("Legacy product_behavior requires observations or legacy source evidence")
        for field in ("evidence_ids", "observation_ids", "persona_ids", "research_support_evidence_ids", "research_context_evidence_ids", "counter_evidence_ids", "context_evidence_ids"):
            if field in claim and len(set(claim[field])) != len(claim[field]):
                errors.append("Claim reference arrays must be unique")
        for value in claim.get("audience_values", []):
            _require_ref_list(value["denominator_evidence_ids"], maps["evidence"], "audience_values.denominator_evidence_ids", errors, allow_empty=True)
            for check in value["value_checks"]:
                _require_ref(check["evidence_id"], maps["evidence"], "audience_values.value_checks.evidence_id", errors)
        if claim.get("counter_search") and claim["counter_search"].get("resolution_id"):
            target={x["id"]:x for x in bundle.get("research", {}).get("scope_resolutions", [])}
            _require_ref(claim["counter_search"]["resolution_id"], target, "counter_search.resolution_id", errors)
        support = [maps["evidence"].get(x, {}) for x in claim.get("evidence_ids", [])]
        if claim.get("verification_status") == "verified":
            for ev in support:
                src = maps["sources"].get(ev.get("source_id"), {})
                if src.get("research_tombstone") or src.get("retention_status") in {"deleted", "withdrawn", "redacted"} or src.get("source_family") == "none" or src.get("source_type") in {"llm_output", "synthetic"} or (src.get("access") or {}).get("stop_class") not in {None, "none"} or ev.get("flags", {}).get("lead_kind", "full_text") != "full_text":
                    errors.append("Verified claim uses ineligible stopped, lead or synthetic source support")
        numeric = claim.get("claim_kind") in {"segment_share", "device_mix", "condition_share", "prevalence", "user_preference", "real_user_preference", "discomfort"}
        if claim.get("verification_status") == "verified" and numeric:
            for ev in support:
                den = ev.get("denominator")
                if ev.get("epistemic_status") != "observed" or ev.get("evidence_type") not in {"quantitative", "statistic"} or not isinstance(den, dict) or not den.get("sampling_frame") or not den.get("period_start") or not den.get("period_end"):
                    errors.append("Verified preference or prevalence needs observed quantitative/statistic evidence and a neutral frame/period")
    envelope = bundle.get("research", {})
    for decision in envelope.get("verifier_decisions", []):
        target = {"source": "sources", "evidence": "evidence", "claim": "claims"}.get(decision["target_kind"])
        _require_ref(decision["target_id"], maps.get(target, {}), "research.verifier_decisions.target_id", errors)
        _require_ref_list(decision["basis_evidence_ids"], maps["evidence"], "research.verifier_decisions.basis_evidence_ids", errors, allow_empty=True)
        if "resolution_id" in decision:
            _require_ref(decision["resolution_id"], {x["id"]:x for x in envelope.get("scope_resolutions", [])}, "research.verifier_decisions.resolution_id", errors)
        if "basis_claim_id" in decision:
            _require_ref(decision["basis_claim_id"], maps["claims"], "research.verifier_decisions.basis_claim_id", errors)
    for resolution in envelope.get("scope_resolutions", []):
        for field in ("prior_claim_id", "claim_id"):
            _require_ref(resolution[field], maps["claims"], "research.scope_resolutions." + field, errors)
        for field in ("counter_evidence_ids", "basis_evidence_ids"):
            _require_ref_list(resolution[field], maps["evidence"], "research.scope_resolutions." + field, errors, allow_empty=True)
        _require_ref_list(resolution["verifier_decision_ids"], {x["id"]:x for x in envelope.get("verifier_decisions",[])}, "scope_resolutions.verifier_decision_ids", errors, allow_empty=True)
    segments = {x["segment_id"] for x in envelope.get("manifest", {}).get("segments", [])}
    for group in ("personas", "scenarios"):
        for record in maps[group].values():
            ref = record.get("audience_ref")
            if ref:
                if group == "personas" and record.get("basis") != "synthetic":
                    errors.append("audience_ref requires synthetic persona basis")
                _require_ref_list(ref.get("claim_ids", []), maps["claims"], "audience_ref.claim_ids", errors, allow_empty=True)
                if research and ref.get("segment_id") not in segments:
                    errors.append("audience_ref references unknown research segment")
    for finding in maps["findings"].values():
        if research and any(x not in segments for x in finding.get("segments_affected", [])):
            errors.append("segments_affected references unknown research segment")
    return errors


def validate_receipts(bundle, root):
    from uxresearch.canonical import byte_digest, timestamp
    from uxresearch.storage import read_bytes, safe_path
    errors = []
    records = bundle["records"]
    observations = {x["id"]: x for x in records["observations"]}
    runs = {x["id"]: x for x in records["runs"]}
    for finding in records["findings"]:
        if finding.get("severity") not in {"P0", "P1"}:
            continue
        second = finding.get("second_pass")
        if not second or (second.get("severity") == "disagree" and not second.get("resolution")) or second.get("finding_id", finding["id"]) != finding["id"]:
            errors.append("Priority finding requires a resolved second pass")
        receipts = 0
        for oid in finding.get("observation_ids", []):
            observation = observations.get(oid, {})
            receipt = observation.get("receipt")
            if not receipt:
                continue
            try:
                path = Path(receipt["artifact_path"])
                if path.is_absolute():
                    raise ValueError()
                raw = read_bytes(safe_path(Path(root) / path, root))
                run = runs[observation["run_id"]]
                if byte_digest(raw) != receipt["sha256"] or timestamp(receipt["captured_at"]) < timestamp(run["started_at"]):
                    raise ValueError()
                receipts += 1
            except (OSError, ValueError, KeyError, TypeError):
                errors.append("Priority finding capture receipt is absent, unsafe, stale or has a mismatched SHA-256")
        if not receipts:
            errors.append("Priority finding requires an artifact receipt from its run")
    return errors


def validate_bundle(bundle: Any, *, now: datetime | None = None, artifacts_root=None, report=None) -> list[str]:
    """Malformed input returns diagnostics; optional receipt/report checks are additive."""
    try:
        errors = _validate_bundle(bundle, now=now)
        if not errors:
            errors += _extra_checks(bundle, now or datetime.now(timezone.utc))
        if not errors and artifacts_root is not None:
            errors += validate_receipts(bundle, artifacts_root)
        if report is not None:
            from uxresearch.reports import decision_section
            import re
            section, _ = decision_section(Path(report).read_text(encoding="utf-8"))
            if not re.search(r"(?im)^\s*(?:[-*]\s*)?(?:verdict|판정|결론)\s*:\s*(?:ship after fixes|ship|hold|inconclusive|출시 가능|수정 후 출시|보류|판단 불가)(?:[.\s:—-]|$)", section):
                errors.append("Decision requires one of the four verdict labels")
        return errors
    except OSError:
        return ["Required artifact or report cannot be read"]
    except (ValueError, TypeError, KeyError, AttributeError, IndexError, OverflowError, RecursionError):
        return ["bundle has malformed fields, references or report decision"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--artifacts-root", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    from uxresearch.canonical import loads, EngineError
    try:
        bundle = loads(args.bundle.read_bytes())
        if args.report is not None:
            args.report.read_text(encoding="utf-8")
    except (OSError, UnicodeError, EngineError):
        print("ERROR: input is missing or invalid UTF-8 JSON", file=sys.stderr)
        return 2
    errors = validate_bundle(bundle, artifacts_root=args.artifacts_root, report=args.report)
    if errors:
        for error in errors:
            print("ERROR: " + error)
        return 1
    for warning in bundle_warnings(bundle):
        print("WARNING: " + warning, file=sys.stderr)
    print(f"VALID: {bundle['bundle_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
