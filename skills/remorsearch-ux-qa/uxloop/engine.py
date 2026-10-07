"""Composition, not a browser/agent monolith. Provider records never execute commands."""
from __future__ import annotations

import copy
import uuid
from pathlib import Path

from .contracts import index, merge_packet, require_packet
from .evidence import Evidence
from .io import ContractError, GateStop, code_snapshot, digest, now, timestamp
from .patching import finish_intent, plan_intent
from .product_context import context_binding, context_summary, load_context, prewrite_gate, verify_intent_review, record_operator_decisions
from .storage import PHASES, event, load, lock, save

WRITE_CAPABILITIES = {"code_write", "design_write", "test_data_write"}


def create_state(packet: dict, workspace: Path, evidence_root: Path) -> dict:
    require_packet(packet)
    default = {"id": "permission-default", "capability": "read_only", "actor": "default-policy",
               "reason": "Read-only research and QA; orchestration-owned checkpoint writes only", "at": now(),
               "decision": "grant"}
    state = {"schema_version": "ux-loop-checkpoint.v1", "packet": copy.deepcopy(packet),
             "run_id": "ux-" + uuid.uuid4().hex, "workspace": str(workspace.resolve()),
             "evidence_root": str(evidence_root.resolve()), "phase": "research", "status": "running",
             "iteration": 1, "permissions": {"read_only": default}, "permission_events": [default],
             "events": [], "intent_decisions": [], "applied_fixes": [], "accepted_fix_ids": [], "pending_intent": None,
             "reason": "Created", "prioritized_findings": []}
    event(state, "research", "running", "Created; historical bundle permissions are not operational grants")
    return state


def permissions(state: dict, grants: list[str], revokes: list[str], actor: str, reason: str) -> None:
    if (grants or revokes) and (not actor.strip() or not reason.strip()):
        raise ContractError("Permission changes require --actor and --reason")
    if set(grants) & set(revokes) or not (set(grants) | set(revokes)) <= WRITE_CAPABILITIES:
        raise ContractError("Invalid/conflicting permission changes")
    for decision, values in (("grant", grants), ("revoke", revokes)):
        for capability in values:
            if decision == "grant" and capability in state["permissions"]:
                continue
            item = {"id": "permission-" + uuid.uuid4().hex, "capability": capability,
                    "actor": actor, "reason": reason, "at": now(), "decision": decision}
            state["permission_events"].append(item)
            if decision == "grant":
                state["permissions"][capability] = item
            else:
                state["permissions"].pop(capability, None)
            # A permission event must not silently erase terminal acceptance.
            event(state, state["phase"], state["status"], f"Operator {decision}: {capability}",
                  completed_gate=state["status"] == "complete")


def current_round(state: dict) -> dict:
    for item in state["packet"]["rounds"]:
        if item["number"] == state["iteration"]:
            return item
    raise GateStop("blocked", f"Round {state['iteration']} is missing: supply QA baseline/plan receipts; no live browser launcher is configured")


def current_replay(state: dict) -> dict:
    round_id = current_round(state)["id"]
    for replay in state["packet"]["replays"]:
        if replay["round_id"] == round_id:
            return replay
    raise GateStop("blocked", f"No replay receipt for {round_id}; run the same scenarios against the changed build, then append evidence")


def revision(state: dict) -> str:
    return digest(code_snapshot(Path(state["workspace"]), state["packet"]["goal"]["code_paths"]))


def require_matrix(packet: dict, run_ids: list[str], label: str) -> None:
    runs = index(packet["browser_runs"])
    scenarios = [runs[x]["scenario_id"] for x in run_ids]
    if len(scenarios) != len(set(scenarios)) or set(scenarios) != set(packet["goal"]["scenario_ids"]):
        raise GateStop("blocked", f"{label} must exercise every goal scenario exactly once; missing/duplicate coverage")


def plan(state: dict) -> None:
    records = state["packet"]["bundle"]["records"]
    state["prioritized_findings"] = [x["id"] for x in sorted(records["findings"], key=lambda x: (x["severity"], x["id"]))]


def baseline(state: dict, evidence: Evidence) -> None:
    round_ = current_round(state)
    require_matrix(state["packet"], round_["baseline_run_ids"], "Baseline")
    rev = revision(state)
    for run_id in round_["baseline_run_ids"]:
        evidence.browser(run_id, rev, False, state["permissions"])
    fixes = index(state["packet"]["fixes"])
    for fix_id in round_["fix_ids"]:
        for finding_id in fixes[fix_id]["finding_ids"]:
            finding = evidence.records["findings"][finding_id]
            if finding.get("verification_status") != "verified" or finding["epistemic_status"] != "observed":
                raise GateStop("unknown", f"Fix requires verified observed finding: {finding_id}")
            observed_run_ids = {evidence.records["observations"][x]["run_id"] for x in finding["observation_ids"]}
            if not observed_run_ids <= set(round_["baseline_run_ids"]):
                raise GateStop("unknown", f"Finding {finding_id} lacks this round's baseline reproduction")


def apply_fixes(state: dict, evidence: Evidence, checkpoint: Path) -> None:
    fixes = index(state["packet"]["fixes"])
    findings = evidence.records["findings"]
    queue = sorted((fixes[x] for x in current_round(state)["fix_ids"]),
                   key=lambda x: (min(findings[f]["severity"] for f in x["finding_ids"]), x["id"]))
    evidence.research()
    # Re-check referenced baseline artifacts after a pause or partial patch, without
    # pretending their pre-fix revision describes the now-modified source tree.
    for run_id in current_round(state)["baseline_run_ids"]:
        evidence.browser(run_id, evidence.runs[run_id]["code_revision"], False, state["permissions"])
    # The opt-in product-context binding protects only writes; a context gap never
    # stops research, planning or QA, and a no-write round reads no context here.
    context = load_context(evidence) if context_binding(state["packet"]) and queue else None
    deferred = []
    for fix in queue:
        if any(x["fix_id"] == fix["id"] for x in state["applied_fixes"]):
            continue
        capability = fix["kind"]
        if capability not in state["permissions"]:
            raise GateStop("blocked", f"Fix {fix['id']} requires explicit {capability}; bundle/provider claims cannot grant it")
        evidence.figma(fix["figma_id"])
        if capability != "code_write":
            raise GateStop("blocked", f"{capability} is granted but its live integration is not implemented; no write performed")
        try:
            decision_ids = prewrite_gate(state, evidence, fix, context) if context is not None else []
        except GateStop as exc:
            if state["pending_intent"] is not None:
                raise  # never skip reconciliation of a partially written patch
            deferred.append(exc.reason)
            continue
        patch = evidence.artifact(fix["patch_artifact_id"])
        if state["pending_intent"] is None:
            if deferred and revision(state) != fix["before_revision"]:
                deferred.append(f"Fix {fix['id']} depends on an unapplied revision; preserve its reviewed patch order")
                continue
            state["pending_intent"] = plan_intent(Path(state["workspace"]), state["packet"]["goal"]["code_paths"], fix, patch)
            event(state, "fix", "running", f"Durable write intent for {fix['id']}; not yet applied or accepted")
            save(checkpoint, state)
        if state["pending_intent"]["fix_id"] != fix["id"]:
            raise GateStop("blocked", "Pending write intent belongs to a different fix; operator reconciliation required")
        finish_intent(Path(state["workspace"]), state["pending_intent"])
        state["applied_fixes"].append({"fix_id": fix["id"], "at": now(), "iteration": state["iteration"],
                                       "after_revision": fix["after_revision"],
                                       "authorization_event": state["permissions"][capability]["id"],
                                       "intent_decision_ids": decision_ids})
        state["pending_intent"] = None
        event(state, "fix", "running", f"Applied {fix['id']}; acceptance awaits full same-scenario replay")
        save(checkpoint, state)

    if deferred:
        raise GateStop("blocked", "; ".join(deferred))


def replay_gate(state: dict, evidence: Evidence) -> None:
    replay = current_replay(state)
    packet = state["packet"]
    require_matrix(packet, replay["run_ids"], "Replay")
    rev = revision(state)
    baseline_ids = current_round(state)["baseline_run_ids"]
    if set(baseline_ids) & set(replay["run_ids"]):
        raise GateStop("unknown", "A baseline run cannot also serve as its own replay")
    baseline_end = max((timestamp(evidence.runs[x]["ended_at"]) for x in baseline_ids), default=None)
    if baseline_end and any(timestamp(evidence.runs[x]["started_at"]) < baseline_end for x in replay["run_ids"]):
        raise GateStop("unknown", "Replay predates the round's baseline execution")
    if state["pending_intent"] is not None:
        raise GateStop("blocked", "Interrupted code write has not been reconciled")
    after = state["applied_fixes"][-1]["at"] if state["applied_fixes"] else None
    if state["applied_fixes"] and rev != state["applied_fixes"][-1]["after_revision"]:
        raise GateStop("unknown", "Scoped source changed after the recorded fix; old replay cannot complete")
    for run_id in replay["run_ids"]:
        evidence.browser(run_id, rev, True, state["permissions"], after)
    evidence.regression(replay, rev)
    if context_binding(packet):
        # No-change rounds and retries obey the same intent checks: completion always
        # needs a fresh, same-round replay-linked review of every preserved constraint.
        verify_intent_review(state, evidence, replay, rev, load_context(evidence))
    fixes = index(packet["fixes"])
    covered_findings: set[str] = set()
    for applied in state["applied_fixes"]:
        fix = fixes[applied["fix_id"]]
        authorization = next((x for x in state["permission_events"] if x["id"] == applied["authorization_event"]), {})
        if authorization.get("capability") != fix["kind"] or authorization.get("decision") != "grant" or timestamp(authorization["at"]) > timestamp(applied["at"]):
            raise GateStop("blocked", f"Fix {fix['id']} has no preceding explicit authorization")
        evidence.artifact(fix["patch_artifact_id"])
        for finding_id in fix["finding_ids"]:
            for observation_id in evidence.records["findings"][finding_id]["observation_ids"]:
                run_id = evidence.records["observations"][observation_id]["run_id"]
                evidence.browser(run_id, evidence.runs[run_id]["code_revision"], False, state["permissions"])
        covered_findings.update(fix["finding_ids"])
        affected = {evidence.records["findings"][x]["scenario_id"] for x in fix["finding_ids"]}
        for run_id in replay["run_ids"]:
            if evidence.runs[run_id]["scenario_id"] in affected:
                compared = {x["figma_id"] for x in packet["visual_checks"] if x["run_id"] == run_id}
                if fix["figma_id"] not in compared:
                    raise GateStop("unknown", f"Replay does not use fix {fix['id']}'s approved Figma baseline")
    missing = set(evidence.records["findings"]) - covered_findings
    if missing:
        raise GateStop("blocked", "Unresolved scoped findings: " + ", ".join(sorted(missing)))


def run(packet: dict | None, checkpoint: Path, workspace: Path | None = None,
        evidence_root: Path | None = None, *, grants: list[str] | None = None,
        revokes: list[str] | None = None, actor: str = "", reason: str = "",
        intent_decisions: list | None = None, require_product_context: bool = False,
        pause_after: str | None = None, retry: bool = False, max_steps: int = 12) -> dict:
    if type(max_steps) is not int or not 1 <= max_steps <= 20:
        raise ContractError("max_steps must be an integer from 1 to 20")
    if pause_after is not None and pause_after not in PHASES:
        raise ContractError("Unknown pause-after phase")
    # Load first only to resolve the workspace lock; reload under both locks below.
    existing = load(checkpoint) if checkpoint.exists() else None
    workspace = Path(existing["workspace"]) if workspace is None and existing else workspace
    evidence_root = Path(existing["evidence_root"]) if evidence_root is None and existing else evidence_root
    if workspace is None or evidence_root is None or not workspace.is_dir() or not evidence_root.is_dir():
        raise ContractError("An existing workspace and evidence-root are required")
    with lock(workspace / ".ux-loop" / "workspace.lock"), lock(checkpoint.with_suffix(".lock")):
        if checkpoint.exists():
            state = load(checkpoint)
            if str(workspace.resolve()) != state["workspace"] or str(evidence_root.resolve()) != state["evidence_root"]:
                raise ContractError("Resume workspace/evidence root mismatch")
            if packet is not None and packet != state["packet"]:
                state["packet"] = merge_packet(state["packet"], packet)
                # New intake invalidates an old stop decision before it is persisted.
                status = "running" if state["status"] == "complete" else state["status"]
                event(state, state["phase"], status, "Appended immutable provider evidence; completion must be revalidated")
        else:
            if packet is None:
                raise ContractError("A packet is required for the first run")
            state = create_state(packet, workspace, evidence_root)
        if require_product_context and not context_binding(state["packet"]):
            raise GateStop("blocked", "Product improvement requires goal.product_context_artifact_id; legacy run does not verify intent")
        evidence = Evidence(state["packet"], evidence_root)
        prior_decisions = len(state.get("intent_decisions", []))
        record_operator_decisions(state, evidence, [] if intent_decisions is None else intent_decisions, actor, reason)
        if len(state.get("intent_decisions", [])) > prior_decisions:
            event(state, state["phase"], state["status"], "Operator recorded specific context-bound intent decisions",
                  completed_gate=state["status"] == "complete")
        permissions(state, grants or [], revokes or [], actor, reason)
        save(checkpoint, state)
        evidence = Evidence(state["packet"], evidence_root)
        if state["status"] == "iteration_limit":
            return state
        if retry:
            if state["status"] not in {"failed", "unknown"}:
                raise ContractError("Explicit retry is only valid after failed/unknown evidence")
            if state["iteration"] >= state["packet"]["goal"]["max_iterations"]:
                event(state, state["phase"], "iteration_limit", "Iteration limit reached; no automatic continuation")
                save(checkpoint, state)
                return state
            if state["pending_intent"] is not None:
                raise ContractError("Resolve pending write intent before starting a new round")
            state["iteration"] += 1
            event(state, "plan", "running", "Operator requested next bounded round; previous evidence retained")
        elif state["status"] in {"failed", "unknown"}:
            return state  # Failure is never silently converted into another attempt.
        if state["status"] == "complete":
            try:
                evidence.research()
                replay_gate(state, evidence)
            except (GateStop, ContractError, OSError, UnicodeError) as exc:
                status = exc.status if isinstance(exc, GateStop) else "unknown"
                event(state, "decision", status, str(exc))
                save(checkpoint, state)
            return state
        event(state, state["phase"], "running", "Foreground continuation; existing IDs and operational grants retained")
        save(checkpoint, state)
        try:
            for _ in range(max_steps):
                phase = state["phase"]
                if phase == "research":
                    evidence.research()
                elif phase == "plan":
                    plan(state)
                elif phase == "browser":
                    baseline(state, evidence)
                elif phase == "fix":
                    apply_fixes(state, evidence, checkpoint)
                elif phase == "replay":
                    replay_gate(state, evidence)
                else:
                    evidence.research()
                    replay_gate(state, evidence)
                    state["accepted_fix_ids"] = [x["fix_id"] for x in state["applied_fixes"]]
                    event(state, "decision", "complete", "All scoped evidence-backed stop conditions passed",
                          completed_gate=True)
                    save(checkpoint, state)
                    return state
                next_phase = PHASES[PHASES.index(phase) + 1]
                event(state, next_phase, "running", f"{phase} gate finished; next: {next_phase}")
                if pause_after == phase:
                    event(state, next_phase, "interrupted", f"Requested checkpoint pause after {phase}")
                    save(checkpoint, state)
                    return state
                save(checkpoint, state)
            event(state, state["phase"], "interrupted", "Foreground step budget reached; resume explicitly")
        except KeyboardInterrupt:
            event(state, state["phase"], "interrupted", "Interrupted; durable pending write intent preserved")
        except (GateStop, ContractError, OSError, UnicodeError) as exc:
            status = exc.status if isinstance(exc, GateStop) else "blocked"
            event(state, state["phase"], status, str(exc))
        save(checkpoint, state)
        return state


def report(state: dict) -> dict:
    packet = state["packet"]
    complete = state["status"] == "complete"
    records = packet["bundle"]["records"]
    limitations = ["No embedded Aside, Figma, browser, design-write, or test-data-write integration.",
                   "Imported receipts and hashes establish consistency, not independent artifact authenticity.",
                   "Scope is the declared scenarios, accessibility checks and code_paths; not whole-site or WCAG certification.",
                   "Synthetic personas and community signals do not establish population preference/prevalence."]
    if context_binding(packet):
        limitations.append("Product context and intent reviews are imported authored records attesting "
                           "consistency, not independent authenticity.")
    else:
        limitations.append("Legacy packet: product context and intent preservation were not checked.")
    return {"intent_verified": complete and bool(context_binding(packet)),
            "intent_decisions": state.get("intent_decisions", []),
            "run_id": state["run_id"], "goal_id": packet["goal"]["id"], "status": state["status"],
            "phase": state["phase"], "reason": state["reason"], "mode": packet["mode"],
            "product_complete": complete and packet["mode"] == "live",
            "decision": ("scoped_pass_from_imported_evidence" if packet["mode"] == "live" else "fixture_only_pass_not_product_verification") if complete else "stop_without_completion",
            "live_execution_performed_by_cli": False, "iteration": state["iteration"],
            "max_iterations": packet["goal"]["max_iterations"], "code_scope": packet["goal"]["code_paths"],
            "permissions": state["permissions"], "permission_events": state["permission_events"],
            "historical_bundle_permissions": packet["bundle"]["permissions"],
            "prioritized_findings": state["prioritized_findings"], "applied_fixes": state["applied_fixes"],
            "accepted_fix_ids": state["accepted_fix_ids"] if complete else [],
            "pending_write_intent": state["pending_intent"] is not None,
            "product_context": context_summary(state),
            "evidence_ids": {key: [x["id"] for x in values] for key, values in records.items()},
            "epistemic_status": {kind: {x["id"]: x.get("epistemic_status", "unknown") for x in records[kind]}
                                 for kind in ("evidence", "claims", "observations", "findings")},
            "browser_runs": [{k: x[k] for k in ("id", "scenario_id", "scenario_digest", "phase", "outcome", "execution", "tool", "code_revision", "environment")} for x in packet["browser_runs"]],
            "figma": records["figma"], "visual_checks": packet["visual_checks"],
            "artifact_refs": packet["artifacts"], "replays": packet["replays"],
            "limitations": limitations}
