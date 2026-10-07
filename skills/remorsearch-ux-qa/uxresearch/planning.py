"""Plan initialization/preflight: axes, acknowledgements and an empty search ledger together.

`start` only creates a run folder; the workflow requires axes.json,
axis-acknowledgements.json and search-ledger.jsonl before the first search.
This command validates every companion against its pinned schema and the
manifest semantics, then writes them atomically. It never fabricates search
receipts: an existing nonempty search ledger is preserved and refused, and a
different existing plan is never silently replaced.
"""
from __future__ import annotations

from .canonical import EngineError, canonical, loads
from .merge import manifest_plan
from .schema import Resolver
from .storage import atomic, read_bytes, safe_path

SCHEMAS = {"manifest": "ux-research-axes.v1.schema.json", "acknowledgements": "ux-axis-acknowledgements.v1.schema.json"}


def _issue(code, location, reason, next_step):
    return dict(code=code, location=location, reason=reason, next_step=next_step)


def _semantic_issues(manifest, run):
    """Field-level manifest checks with exact paths; manifest_plan stays the authority."""
    issues = []
    if manifest.get("run_id") != run.meta["run_id"]:
        issues.append(_issue("run_id", "run_id", "Manifest belongs to a different run.",
                             "Use the run_id printed by `start` for this run folder."))
    axes, assignments, covered = {}, {}, set()
    for i, axis in enumerate(manifest.get("axes", [])):
        aid = axis.get("axis_id")
        where = f"axes[{i}]"
        if aid in axes:
            issues.append(_issue("duplicate_axis", f"{where}.axis_id", "Axis IDs must be unique.",
                                 "Give each axis a distinct lowercase ID."))
            continue
        axes[aid] = axis
        if axis.get("excluded"):
            if not axis.get("reason"):
                issues.append(_issue("excluded_reason", f"{where}.reason", "Excluded axes need a reason.",
                                     "State why this axis is excluded, or include it with assignments."))
            if axis.get("assignments"):
                issues.append(_issue("excluded_assignments", f"{where}.assignments",
                                     "Excluded axes cannot carry assignments.", "Remove the assignments or the exclusion."))
        else:
            if not any(x.get("purpose") == "discovery" and x.get("round") == 0 for x in axis.get("assignments", [])):
                issues.append(_issue("missing_discovery", f"{where}.assignments",
                                     "Included axes need an original round 0 discovery assignment.",
                                     "Add {assignment_id, reader_id, round: 0, purpose: discovery}."))
            covered.update(axis.get("audience_questions", []))
        for j, x in enumerate(axis.get("assignments", [])):
            path = f"{where}.assignments[{j}]"
            if x.get("assignment_id") in assignments:
                issues.append(_issue("duplicate_assignment", f"{path}.assignment_id",
                                     "Assignment IDs must be unique across the plan.", "Use a distinct assignment ID."))
            else:
                assignments[x["assignment_id"]] = (aid, x)
            purpose, rnd = x.get("purpose"), x.get("round")
            if purpose == "discovery" and rnd != 0:
                issues.append(_issue("assignment_round", f"{path}.round",
                                     "Discovery assignments run only in round 0.", "Set round to 0."))
            elif purpose == "counter_search" and rnd not in {0, 1, 2}:
                issues.append(_issue("assignment_round", f"{path}.round",
                                     "Counter-search assignments may run in rounds 0-2 only.", "Set round to 0, 1 or 2."))
            elif purpose == "expansion" and rnd not in {1, 2}:
                issues.append(_issue("assignment_round", f"{path}.round",
                                     "Expansion assignments run only in the two EXPAND rounds 1-2.", "Set round to 1 or 2."))
    segments = [x.get("segment_id") for x in manifest.get("segments", [])]
    if len(segments) != len(set(segments)):
        issues.append(_issue("duplicate_segment", "segments", "Segment IDs must be unique.",
                             "Give each planned segment a distinct ID."))
    brief = read_bytes(run.path / "brief.json") if (run.path / "brief.json").exists() else None
    if brief is not None:
        from .canonical import loads
        requested = set(loads(brief).get("audience_questions", []))
        gaps = {g.get("question") for g in manifest.get("question_gaps", [])}
        if requested - covered - gaps:
            issues.append(_issue("question_coverage", "axes.audience_questions",
                                 "Requested brief questions need coverage or an explicit gap.",
                                 "Cover the question in an axis, or add it to question_gaps with a reason."))
        if (covered | gaps) - requested:
            issues.append(_issue("question_coverage", "question_gaps",
                                 "Extra questions beyond the brief are refused.",
                                 "Remove questions the brief did not request."))
    return issues


def _ack_issues(doc, assignments):
    issues = []
    if doc.get("run_id") != assignments["run_id"]:
        issues.append(_issue("run_id", "run_id", "Acknowledgements belong to a different run.",
                             "Use this run's run_id."))
    for i, entry in enumerate(doc.get("entries", [])):
        path = f"entries[{i}]"
        if entry.get("kind") == "unattributed_request":
            continue
        if entry.get("kind") == "excluded":
            axis = assignments["axes"].get(entry.get("axis_id"))
            if axis is None or not axis["excluded"]:
                issues.append(_issue("axis_mismatch", f"entries[{i}].axis_id",
                                     "Excluded acknowledgement must name an excluded plan axis.",
                                     "Use an excluded axis from the plan."))
            continue
        aid = entry.get("assignment_id")
        if aid not in assignments["map"]:
            issues.append(_issue("unknown_assignment", f"{path}.assignment_id",
                                 "Acknowledgement names an assignment that is not in the plan.",
                                 "Use an assignment_id from axes.json, or kind unattributed_request."))
        elif assignments["map"][aid][0] != entry.get("axis_id"):
            issues.append(_issue("axis_mismatch", f"{path}.axis_id",
                                 "Acknowledgement axis does not match its assignment.",
                                 "Set axis_id to the axis that owns the assignment."))
    return issues


def plan_command(args, run, store):
    del store  # the engine lock is held; plan writes companion files, not engine snapshots
    issues = []
    run.verify_files()
    if run.closed:
        return 2, [], [_issue("closed_run", "run", "A closed run cannot initialize a plan.",
                              "Start a new run for a new plan.")], []
    try:
        raw = read_bytes(args.manifest)
        manifest = loads(raw)
    except EngineError as exc:
        return 2, [], [_issue("plan_input", "manifest",
                              f"Manifest cannot be read: {exc.issue.get('code', 'io')}.",
                              "Provide a readable regular JSON file within the size limit.")], []
    except ValueError:
        return 2, [], [_issue("plan_input", "manifest", "Manifest is not valid JSON.",
                              "Fix the JSON syntax and rerun.")], []
    for error in Resolver().validate(manifest, SCHEMAS["manifest"])[:20]:
        path, _, detail = error.partition(":")
        issues.append(_issue("plan_schema", path.replace("$.", "", 1).replace("$", "<root>"),
                             f"Manifest field fails its pinned schema: {detail.strip()}.",
                             "Correct the field at this path (ux-research-axes.v1)."))
    if not issues:
        issues.extend(_semantic_issues(manifest, run))
    if not issues:
        try:
            manifest_plan(manifest, run)
        except EngineError as exc:
            issues.append(_issue(exc.issue.get("code", "manifest"), "manifest",
                                 exc.issue.get("reason", "Manifest fails the merge contract."),
                                 "Correct the manifest and rerun; see references/research/audience-pipeline.md."))
    if issues:
        return 2, [], issues, []
    axes_path, ack_path, ledger_path = (safe_path(run.path / name, run.path) for name in
                                        ("axes.json", "axis-acknowledgements.json", "search-ledger.jsonl"))
    ack_source = args.acknowledgements or (ack_path if ack_path.exists() else None)
    ack_doc = dict(schema_version="ux-axis-acknowledgements.v1", run_id=manifest.get("run_id"), entries=[])
    if ack_source:
        try:
            ack_doc = loads(read_bytes(ack_source))
        except (EngineError, ValueError) as exc:
            reason = "Acknowledgements cannot be read or parsed." if isinstance(exc, EngineError) else "Acknowledgements are not valid JSON."
            return 2, [], issues + [_issue("plan_input", "acknowledgements", reason,
                                           "Provide a readable ux-axis-acknowledgements.v1 JSON file.")], []
        for error in Resolver().validate(ack_doc, SCHEMAS["acknowledgements"])[:20]:
            path, _, detail = error.partition(":")
            issues.append(_issue("ack_schema", "acknowledgements." + path.replace("$.", "", 1).replace("$", "<root>"),
                                 f"Acknowledgement field fails its pinned schema: {detail.strip()}.",
                                 "Correct the field at this path (ux-axis-acknowledgements.v1)."))
        if not issues:
            issues.extend(_ack_issues(ack_doc, {"run_id": manifest.get("run_id"),
                                                "axes": {a["axis_id"]: a for a in manifest["axes"]},
                                                "map": {x["assignment_id"]: (a["axis_id"], x) for a in manifest["axes"] for x in a["assignments"]}}))
    if issues:
        return 2, [], issues, []

    new_axes = canonical(manifest)
    ack = canonical(ack_doc)
    existing_axes = read_bytes(axes_path) if axes_path.exists() else None
    if existing_axes is not None and canonical(loads(existing_axes)) != new_axes:
        return 2, [], [_issue("plan_conflict", "axes.json",
                              "A different plan already exists; it is preserved.",
                              "Merge the changes into the existing axes.json through a remerge, or start a new run.")], []
    if ack_path.exists() and canonical(loads(read_bytes(ack_path))) != ack:
        return 2, [], [_issue("plan_conflict", "axis-acknowledgements.json",
                              "Existing acknowledgements differ from the provided file; both are preserved.",
                              "Review and merge the acknowledgement entries explicitly, or start a new run.")], []
    ledger_raw = read_bytes(ledger_path) if ledger_path.exists() else b""
    if ledger_raw.strip():
        if existing_axes is None:
            return 2, [], [_issue("search_ledger_not_empty", "search-ledger.jsonl",
                                  "Actual search receipts already exist; a plan cannot be initialized around them.",
                                  "Keep the ledger, write axes.json describing the already-run assignments, or start a new run.")], []
    written, warnings = [], []
    companions = ((axes_path, new_axes), (ack_path, ack), (ledger_path, b""))
    try:
        for path, value in companions:
            if path.exists():
                warnings.append(f"{path.name} already exists and was left unchanged.")
            else:
                written.append(path.name)
                atomic(path, value)
    except (OSError, EngineError):
        # Only new companions are rolled back; existing evidence and receipts stay intact.
        for path, value in companions:
            if path.name in written and path.exists() and read_bytes(path) == value:
                path.unlink()
        return 2, [], [_issue("plan_write", "run", "Plan companion files could not be written together.",
                              "Check available space and file permissions; existing records were preserved.")], []
    return 0, written, issues, warnings
