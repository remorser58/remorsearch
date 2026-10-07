"""Opt-in product-context intent protection bound to an immutable goal artifact.

The product-context artifact is authored by the host agent from actual project docs,
memory and the observed product; it is imported evidence, so every check below attests
consistency with the declared sources, never independent authenticity. Packets whose
goal carries no product_context_artifact_id keep the exact v1 behavior: these gates
only run while the binding exists, and the binding can never be added, removed or
replaced on resume because the goal is immutable.
"""
from __future__ import annotations

from pathlib import Path
from datetime import date, datetime, timezone
import uuid

from .evidence import Evidence
from .io import ContractError, GateStop, safe_relative, timestamp, digest, now

SOURCE_KINDS = {"project_doc", "memory", "current_user_decision"}
MEMORY_SEARCH_STATUSES = {"searched_available", "searched_not_available"}
SCOPE_KEYS = {"paths", "scenario_ids"}


def context_binding(packet: dict) -> str | None:
    value = packet["goal"].get("product_context_artifact_id")
    return value if isinstance(value, str) and value else None


def _scope(record: dict, goal: dict, where: str) -> tuple[set[str], set[str]]:
    scope = record.get("scope")
    if not isinstance(scope, dict) or set(scope) - SCOPE_KEYS:
        raise GateStop("blocked", f"product context {where}: scope must name paths and/or scenario_ids only")
    paths = scope.get("paths", [])
    scenarios = scope.get("scenario_ids", [])
    if not isinstance(paths, list) or not isinstance(scenarios, list) or not (paths or scenarios):
        raise GateStop("blocked", f"product context {where}: scope must name at least one path or scenario")
    for name in paths:
        if not isinstance(name, str):
            raise GateStop("blocked", f"product context {where}: scope paths must be strings")
        try:
            safe_relative(name)
        except ContractError as exc:
            raise GateStop("blocked", f"product context {where}: {exc}") from exc
    if any(not isinstance(x, str) for x in scenarios) or set(scenarios) - set(goal["scenario_ids"]):
        raise GateStop("blocked", f"product context {where}: scope names scenarios outside the goal matrix")
    return set(paths), set(scenarios)


def _date(value, where: str):
    try:
        if isinstance(value, str) and len(value) == 10:
            return datetime.combine(date.fromisoformat(value), datetime.min.time(), timezone.utc)
        return timestamp(value)
    except (ContractError, ValueError) as exc:
        raise GateStop("blocked", f"product context {where}: invalid date") from exc


def _check_shape(packet: dict, payload: dict, context_at) -> None:
    def fail(reason: str) -> GateStop:
        return GateStop("blocked", "product context " + reason)

    if payload.get("kind") != "product_context":
        raise fail("artifact must carry kind=product_context")
    if payload.get("goal_id") != packet["goal"]["id"]:
        raise fail("goal_id does not match this goal")
    memory = payload.get("memory_search")
    if not isinstance(memory, dict) or not isinstance(memory.get("status"), str) or memory["status"] not in MEMORY_SEARCH_STATUSES:
        raise fail("memory_search must explicitly record searched_available or searched_not_available; "
                   "absent memory may not be presented as searched-and-found or fabricated")
    sources = payload.get("sources")
    if not isinstance(sources, list) or not sources:
        raise fail("must record at least one inspectable source (project docs, memory or a current user decision)")
    source_ids: set[str] = set()
    for source in sources:
        if not isinstance(source, dict) or not isinstance(source.get("id"), str) or not source["id"]:
            raise fail("source entries need string ids")
        if source["id"] in source_ids:
            raise fail(f"source {source['id']}: duplicate id")
        source_ids.add(source["id"])
        if not isinstance(source.get("kind"), str) or source["kind"] not in SOURCE_KINDS:
            raise fail(f"source {source['id']}: kind must be project_doc, memory or current_user_decision; "
                       "intent cannot be inferred from code alone")
        for field in ("ref", "version", "checked_at"):
            if not isinstance(source.get(field), str) or not source[field].strip():
                raise fail(f"source {source['id']}: {field} is required for inspectable source identity")
        if _date(source["checked_at"], "source checked_at") > context_at:
            raise fail(f"source {source['id']}: checked_at is after context creation")
        if source["kind"] == "memory" and memory["status"] != "searched_available":
            raise fail(f"source {source['id']}: memory cannot be cited when the recorded search found none available")
    for group, text_field in (("constraints", "reason"), ("conflicts", "description")):
        records = payload.get(group)
        if not isinstance(records, list):
            raise fail(f"{group} must be a list")
        seen: set[str] = set()
        for record in records:
            if not isinstance(record, dict) or not isinstance(record.get("id"), str) or not record["id"]:
                raise fail(f"{group}: entries need string ids")
            if record["id"] in seen:
                raise fail(f"{group} {record['id']}: duplicate id")
            seen.add(record["id"])
            if not isinstance(record.get(text_field), str) or not record[text_field].strip():
                raise fail(f"{group} {record['id']}: {text_field} is required")
            if not isinstance(record.get("source_id"), str) or record["source_id"] not in source_ids:
                raise fail(f"{group} {record['id']}: source_id must reference a recorded source")
            if "decision_date" in record:
                source = next(x for x in sources if x["id"] == record["source_id"])
                if _date(record["decision_date"], "decision_date") > _date(source["checked_at"], "source checked_at"):
                    raise fail(f"{group} {record['id']}: decision_date is after source check")
            _scope(record, packet["goal"], f"{group} {record['id']}")
    mapping = payload.get("path_scenarios", {})
    if not isinstance(mapping, dict):
        raise fail("path_scenarios must be an object")
    for path, scenarios in mapping.items():
        if path not in packet["goal"]["code_paths"] or not isinstance(scenarios, list) or not scenarios or any(
                not isinstance(x, str) for x in scenarios):
            raise fail("path_scenarios must map goal code paths to nonempty scenario lists")
        if len(scenarios) != len(set(scenarios)) or set(scenarios) - set(packet["goal"]["scenario_ids"]):
            raise fail("path_scenarios has duplicate or foreign scenarios")
    for record in payload["constraints"] + payload["conflicts"]:
        paths, _ = _scope(record, packet["goal"], record["id"])
        if (paths & set(packet["goal"]["code_paths"])) - set(mapping):
            raise fail(f"{record['id']}: path_scenarios must bind each in-scope path to tested scenarios")


def load_context(evidence: Evidence) -> dict:
    """Hash-verified read of the bound context artifact plus its shape contract."""
    binding = context_binding(evidence.packet)
    if binding is None:
        raise GateStop("blocked", "goal has no product_context_artifact_id binding")
    payload = evidence.payload(binding)
    context_at = timestamp(evidence.artifacts[binding]["created_at"])
    if context_at > timestamp(now()):
        raise GateStop("blocked", "product context creation is future-dated")
    _check_shape(evidence.packet, payload, context_at)
    return payload


def _overlapping(records: dict, payload: dict, group: str, fix: dict, goal: dict) -> list[dict]:
    """Entries whose declared scope touches this fix's changed paths or findings' scenarios."""
    fix_paths = set(fix.get("changed_paths") or [])
    fix_scenarios = {records["findings"][x]["scenario_id"] for x in fix["finding_ids"]}
    for path in fix_paths:
        # Unknown changed-path reach cannot be treated as proof of isolation.
        fix_scenarios.update(payload.get("path_scenarios", {}).get(path, goal["scenario_ids"]))
    result = []
    for record in payload[group]:
        paths, scenarios = _scope(record, goal, f"{group} {record['id']}")
        if (paths & fix_paths) or (scenarios & fix_scenarios):
            result.append(record)
    return result


def record_operator_decisions(state: dict, evidence: Evidence, decisions: list, actor: str, reason: str) -> None:
    """Only a direct operator API/CLI argument can add authority; never packet input.

    Like operational grants, this is a local trust boundary, not authentication of
    the human or protection against someone rewriting the entire checkpoint.
    """
    if not isinstance(decisions, list):
        raise ContractError("Operator intent decisions must be a list")
    if not decisions:
        return
    if not isinstance(actor, str) or not actor.strip() or not isinstance(reason, str) or not reason.strip():
        raise ContractError("Operator intent decisions require --actor and --reason")
    context = load_context(evidence)
    binding = context_binding(evidence.packet)
    artifact = evidence.artifacts[binding]
    fixes = {x["id"]: x for x in evidence.packet["fixes"]}
    pending = []
    for item in decisions:
        base = {"context_artifact_id", "context_sha256", "fix_id", "decision", "decided_at", "reference"}
        if not isinstance(item, dict) or set(item) not in (base | {"constraint_id"}, base | {"conflict_id"}):
            raise ContractError("Operator decision needs context ID/hash, fix_id, one constraint_id/conflict_id, decision, decided_at and reference")
        if any(not isinstance(v, str) or not v.strip() for v in item.values()):
            raise ContractError("Operator decision fields must be nonempty strings")
        if item["context_artifact_id"] != binding or item["context_sha256"] != artifact["sha256"]:
            raise ContractError("Operator decision does not match the bound context ID/hash")
        fix = fixes.get(item["fix_id"])
        if not fix:
            raise ContractError("Operator decision names an unknown fix")
        if any(x["fix_id"] == fix["id"] for x in state["applied_fixes"]):
            raise ContractError("Operator intent decisions cannot retroactively authorize an applied fix")
        kind = "constraint" if "constraint_id" in item else "conflict"
        expected = "authorized_change" if kind == "constraint" else "resolve"
        targets = _overlapping(evidence.records, context, kind + "s", fix, evidence.packet["goal"])
        if item["decision"] != expected or item[kind + "_id"] not in {x["id"] for x in targets}:
            raise ContractError("Operator decision is not for an applicable constraint/conflict and action")
        decided_at = timestamp(item["decided_at"])
        recorded_at = now()
        if not timestamp(artifact["created_at"]) <= decided_at <= timestamp(recorded_at):
            raise ContractError("Operator decision must follow context creation and cannot be future-dated")
        pending.append({**item, "id": "intent-decision-" + uuid.uuid4().hex,
                        "goal_id": evidence.packet["goal"]["id"], "fix_digest": digest(fix),
                        "actor": actor, "reason": reason, "recorded_at": recorded_at})
    state.setdefault("intent_decisions", []).extend(pending)


def _require_current_decision(state: dict, evidence: Evidence, fix: dict, kind: str, target: str) -> str:
    binding = context_binding(evidence.packet)
    artifact = evidence.artifacts[binding]
    for item in state.get("intent_decisions", []):
        if (item.get("goal_id") == evidence.packet["goal"]["id"] and
                item.get("context_artifact_id") == binding and item.get("context_sha256") == artifact["sha256"] and
                item.get("fix_id") == fix["id"] and item.get("fix_digest") == digest(fix) and
                item.get(kind + "_id") == target and
                item.get("decision") == ("authorized_change" if kind == "constraint" else "resolve")):
            if timestamp(artifact["created_at"]) <= timestamp(item["decided_at"]) <= timestamp(item["recorded_at"]):
                return item["id"]
    raise GateStop("blocked", f"Fix {fix['id']} needs a specific operator intent decision for {kind} {target}; "
                              "an imported actor or generic code_write grant is not a human decision")


def prewrite_gate(state: dict, evidence: Evidence, fix: dict, context: dict) -> list[str]:
    goal = evidence.packet["goal"]
    acks = {x["constraint_id"]: x for x in fix.get("constraint_acknowledgements", [])}
    resolutions = {x["conflict_id"]: x for x in fix.get("conflict_resolutions", [])}
    applicable = _overlapping(evidence.records, context, "constraints", fix, goal)
    conflicts = _overlapping(evidence.records, context, "conflicts", fix, goal)
    if set(acks) - {x["id"] for x in applicable} or set(resolutions) - {x["id"] for x in conflicts}:
        raise GateStop("blocked", f"Fix {fix['id']} acknowledges a foreign constraint/conflict")
    decision_ids = []
    for constraint in applicable:
        ack = acks.get(constraint["id"])
        if ack is None:
            raise GateStop("blocked", f"Fix {fix['id']} does not acknowledge preserved constraint {constraint['id']}; no code was written")
        if not ack["evidence"].strip():
            raise GateStop("blocked", f"Fix {fix['id']} acknowledges {constraint['id']} without concrete prewrite evidence")
        if ack["decision"] == "authorized_change":
            decision_ids.append(_require_current_decision(state, evidence, fix, "constraint", constraint["id"]))
    for conflict in conflicts:
        if conflict["id"] not in resolutions:
            raise GateStop("blocked", f"Unresolved material intent conflict {conflict['id']} overlaps fix {fix['id']}")
        decision_ids.append(_require_current_decision(state, evidence, fix, "conflict", conflict["id"]))
    return decision_ids


def _scope_scenarios(record: dict, context: dict, goal: dict) -> set[str]:
    paths, scenarios = _scope(record, goal, record["id"])
    for path in paths & set(goal["code_paths"]):
        scenarios.update(context.get("path_scenarios", {}).get(path, []))
    return scenarios


def verify_intent_review(state: dict, evidence: Evidence, replay: dict, revision: str, context: dict) -> None:
    """Review every applicable constraint, including unchanged parts of the goal."""
    packet, goal = evidence.packet, evidence.packet["goal"]
    fixes = {x["id"]: x for x in packet["fixes"]}
    review_id = replay.get("intent_review_artifact_id")
    if not review_id:
        raise GateStop("blocked", f"Replay {replay['id']} has no linked intent review; preserved developer intent is unverified")
    payload = evidence.payload(review_id)
    identity = {"kind": "intent_review", "replay_id": replay["id"], "code_revision": revision,
                "run_ids": replay["run_ids"], "product_context_artifact_id": context_binding(packet),
                "product_context_sha256": evidence.artifacts[context_binding(packet)]["sha256"]}
    if any(payload.get(k) != v for k, v in identity.items()):
        raise GateStop("unknown", f"Intent review {review_id} is stale, cross-round or contradicts the replayed revision/context")
    applied = [x["fix_id"] for x in state["applied_fixes"]]
    if payload.get("fix_ids") != applied:
        raise GateStop("unknown", f"Intent review {review_id} does not cover exactly the fixes applied so far")
    # Keys include run_id so two declared scenarios cannot collapse into one row.
    expected = {"constraint": {}, "conflict": {}}
    covered = {"constraint": set(), "conflict": set()}
    def expect(kind, fix_id, record, outcome):
        scenarios = _scope_scenarios(record, context, goal)
        for run_id in replay["run_ids"]:
            if evidence.runs[run_id]["scenario_id"] in scenarios:
                expected[kind][(fix_id, record["id"], run_id)] = outcome
        if scenarios:
            covered[kind].add(record["id"])
    for applied_fix in state["applied_fixes"]:
        fix = fixes[applied_fix["fix_id"]]
        decisions = prewrite_gate(state, evidence, fix, context)
        if set(decisions) != set(applied_fix.get("intent_decision_ids", [])):
            raise GateStop("blocked", f"Applied fix {fix['id']} has no recorded prewrite intent authorization")
        for decision in state.get("intent_decisions", []):
            if decision["id"] in decisions and timestamp(decision["recorded_at"]) > timestamp(applied_fix["at"]):
                raise GateStop("blocked", "Intent authorization was recorded after the write")
        acks = {x["constraint_id"]: x for x in fix.get("constraint_acknowledgements", [])}
        for record in _overlapping(evidence.records, context, "constraints", fix, goal):
            expect("constraint", fix["id"], record,
                   "preserved" if acks[record["id"]]["decision"] == "preserved" else "intentionally_changed")
        for record in _overlapping(evidence.records, context, "conflicts", fix, goal):
            expect("conflict", fix["id"], record, "resolved")
    for record in context["constraints"]:
        if record["id"] not in covered["constraint"]:
            expect("constraint", None, record, "preserved")
    for record in context["conflicts"]:
        if record["id"] not in covered["conflict"] and _scope_scenarios(record, context, goal):
            raise GateStop("blocked", f"Unresolved material intent conflict {record['id']} remains in the target scope")
    if not expected["constraint"] and not expected["conflict"]:
        raise GateStop("blocked", "No applicable intent constraints were inspected; empty review cannot complete")
    for kind in ("constraint", "conflict"):
        entries = payload.get(kind + "_results")
        if not isinstance(entries, list):
            raise GateStop("unknown", f"Intent review {review_id} {kind}_results must be a list")
        seen = set()
        for entry in entries:
            if (not isinstance(entry, dict) or "fix_id" not in entry or
                    (entry["fix_id"] is not None and not isinstance(entry["fix_id"], str)) or
                    not isinstance(entry.get(kind + "_id"), str) or not isinstance(entry.get("run_id"), str)):
                raise GateStop("unknown", f"Intent review {review_id} has a malformed {kind} entry")
            key = entry["fix_id"], entry[kind + "_id"], entry["run_id"]
            if key in seen:
                raise GateStop("unknown", f"Intent review {review_id} duplicates {kind} coverage")
            seen.add(key)
            if entry["run_id"] not in replay["run_ids"]:
                raise GateStop("unknown", f"Intent review {review_id} cites a run outside this round")
            outcome = expected[kind].pop(key, None)
            if outcome is None:
                raise GateStop("unknown", f"Intent review {review_id} cites foreign {kind}/fix/scenario scope: {key}")
            if entry.get("outcome") != outcome:
                raise GateStop("unknown", f"Intent review {review_id} outcome for {key[1]} contradicts the recorded decision")
            if not isinstance(entry.get("evidence"), str) or not entry["evidence"].strip():
                raise GateStop("unknown", f"Intent review {review_id} lacks concrete replay evidence")
        if expected[kind]:
            raise GateStop("unknown", f"Intent review {review_id} does not cover applicable {kind}s: {list(expected[kind])}")
    capture_at = timestamp(evidence.artifacts[review_id]["created_at"])
    if capture_at < timestamp(evidence.artifacts[context_binding(packet)]["created_at"]):
        raise GateStop("unknown", "Intent review predates its bound product context")
    if capture_at < max(timestamp(evidence.runs[x]["ended_at"]) for x in replay["run_ids"]):
        raise GateStop("unknown", f"Intent review {review_id} predates its replay runs and is not fresh evidence")


def context_summary(state: dict) -> dict | None:
    """Best-effort report view; never turns an unreadable context into fabricated success."""
    packet = state["packet"]
    artifact_id = context_binding(packet)
    if artifact_id is None:
        return None
    summary: dict = {"artifact_id": artifact_id,
                     "intent_review_artifact_ids": {x["id"]: x.get("intent_review_artifact_id")
                                                    for x in packet["replays"]}}
    try:
        evidence = Evidence(packet, Path(state["evidence_root"]))
        context = load_context(evidence)
        summary["memory_search"] = context["memory_search"]["status"]
        summary["constraints"] = [{"id": x["id"], "title": x.get("title", ""), "scope": x["scope"]}
                                  for x in context["constraints"]]
        applied_decisions = {decision_id for fix in state["applied_fixes"]
                             for decision_id in fix.get("intent_decision_ids", [])}
        resolved = {x["conflict_id"] for x in state.get("intent_decisions", [])
                    if "conflict_id" in x and x["id"] in applied_decisions}
        summary["path_scenarios"] = context.get("path_scenarios", {})
        summary["resolved_conflict_ids"] = sorted(resolved)
        summary["unresolved_conflicts"] = [{"id": x["id"], "scope": x["scope"]}
                                           for x in context["conflicts"] if x["id"] not in resolved]
        fixes = {x["id"]: x for x in packet["fixes"]}
        decisions = {}
        for applied in state["applied_fixes"]:
            fix = fixes[applied["fix_id"]]
            decisions[fix["id"]] = {
                "applicable_constraints": [x["id"] for x in _overlapping(
                    evidence.records, context, "constraints", fix, packet["goal"])],
                "acknowledgements": {x["constraint_id"]: x["decision"]
                                     for x in (fix.get("constraint_acknowledgements") or [])}}
        summary["applied_fix_decisions"] = decisions
    except (ContractError, GateStop, OSError, UnicodeError) as exc:
        summary["unavailable"] = str(exc)
    return summary
