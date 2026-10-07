"""Deterministic harvest and authoritative capture/import merge."""
from __future__ import annotations

import copy
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from . import envelope, ladder, ledger, privacy, scope, verdict
from .canonical import EngineError, Ids, byte_digest, canonical, claim_identity, digest, loads, ordered, quote_text, resource_url, timestamp
from .flags import HITS, combine, captured, empty
from .schema import Resolver, require
from .storage import read_bytes, read_json, safe_path

CONTRACT = "research-engine-2026-10-01.1"
RULES = "source-grading-2026-10-01.1"
ARRAYS = ("sources", "evidence", "claims", "personas", "scenarios", "runs", "observations", "findings", "proposals", "figma")


def problem(code, location="input", reason="Input does not satisfy the research contract.", next_step="Correct the input and rerun."):
    return dict(code=code, location=location, reason=reason, next_step=next_step)


def rules_inputs():
    root = Path(__file__).resolve().parent
    files = [root / "data" / x for x in ("markers.json", "suffixes.json", "grading-rules.json", "organization-aliases.json", "research-schema-pins.json")]
    return {x.name: byte_digest(x.read_bytes()) for x in files}


def ledger_snapshot(run):
    with run._state() as state:
        entries = [loads(x) for x in read_bytes(run.path / "access-ledger.jsonl", private=True).splitlines() if x.strip()]
        hosts = copy.deepcopy(state)
    if any(not isinstance(x, dict) for x in entries):
        raise EngineError("ledger", "The access ledger contains malformed entries.")
    return entries, hosts


def validate_policy(run, *, open_required=False):
    if open_required:
        run.require_open()
    else:
        run.verify_files()
        try:
            scope.validate_checks(run.policy.get("terms_checked", []), ledger.utc_today(run.clock))
            scope.validate_lifts(run.policy, run.scope_lists)
        except ValueError as exc:
            raise EngineError("policy", "The reader terms checks are no longer current.") from exc


def manifest_plan(manifest, run, previous=None):
    require(manifest, "ux-research-axes.v1.schema.json")
    if manifest["run_id"] != run.meta["run_id"]:
        raise EngineError("run_id", "Manifest belongs to a different run.")
    axes, assignments = {}, {}
    covered = set()
    for axis in manifest["axes"]:
        aid = axis["axis_id"]
        if aid in axes:
            raise EngineError("manifest", "Axis IDs must be unique.")
        axes[aid] = axis
        if axis["excluded"]:
            if not axis["reason"] or axis["assignments"]:
                raise EngineError("manifest", "Excluded axes need a reason and no assignments.")
        elif not any(x["purpose"] == "discovery" and x["round"] == 0 for x in axis["assignments"]):
            raise EngineError("manifest", "Included axes need an original assignment.")
        if not axis["excluded"]:
            covered.update(axis["audience_questions"])
        for x in axis["assignments"]:
            # Round indexes the search stage: discovery only starts a plan (round 0); expansion
            # only runs in the two EXPAND rounds (1-2); counter_search may be dispatched in any
            # round (0-2) because required counters arise from initial or expanded findings and
            # run inside the same budgets. The schema range and the expansion budget are unchanged.
            if x["assignment_id"] in assignments or (x["purpose"] == "discovery" and x["round"] != 0) or (x["purpose"] == "counter_search" and x["round"] not in {0, 1, 2}) or (x["purpose"] == "expansion" and x["round"] not in {1, 2}):
                raise EngineError("manifest", "Assignments have invalid identity, purpose or round.")
            assignments[x["assignment_id"]] = (axis, x)
    if len({x["segment_id"] for x in manifest["segments"]}) != len(manifest["segments"]):
        raise EngineError("manifest", "Segment IDs must be unique.")
    brief = read_json(run.path / "brief.json") if (run.path / "brief.json").exists() else {}
    requested = set(brief.get("audience_questions", []))
    gaps = {g["question"] for g in manifest["question_gaps"]}
    if requested - covered - gaps or (covered | gaps) - requested:
        raise EngineError("question_coverage", "Requested questions need coverage or explicit gaps; extra questions are refused.")
    if previous:
        old_axes = {x["axis_id"]: x for x in previous["axes"]}
        for aid, old in old_axes.items():
            new = axes.get(aid)
            if not new or any(new[k] != old[k] for k in ("audience_questions", "excluded", "reason")):
                raise EngineError("manifest_changed", "Frozen axis coverage changed.")
            old_assign = {x["assignment_id"]: x for x in old["assignments"]}
            new_assign = {x["assignment_id"]: x for x in new["assignments"]}
            if any(new_assign.get(k) != v for k, v in old_assign.items()):
                raise EngineError("manifest_changed", "Frozen assignments changed or disappeared.")
            if any(x["purpose"] == "discovery" for k, x in new_assign.items() if k not in old_assign):
                raise EngineError("manifest_changed", "Only expansion/counter assignments can be appended.")
        if set(axes) != set(old_axes):
            raise EngineError("manifest_changed", "Frozen axis IDs changed.")
    return axes, assignments


def import_identity(item):
    return "IMP-" + digest({"content_sha256": item["content_sha256"], "acquisition": item["acquisition"]})


def privacy_scan(value, *, skip=frozenset()):
    """Identifier patterns only; reviewer attestation covers plain names."""
    if isinstance(value, str):
        import re
        if re.fullmatch(r"(?:[0-9a-f]{64}|(?:SRC|EV|CLM)-[0-9a-f]{8}|IMP-[0-9a-f]{64}|F-[0-9a-f]{12}|Q-[0-9a-f]{16}|(?:bundle-)?run-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{6}|[0-9]{4}-[0-9]{2}-[0-9]{2}(?:T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?Z)?)", value):
            return False
        return bool(sum(privacy.scrub(value)[1].values()))
    if isinstance(value, list):
        return any(privacy_scan(x, skip=skip) for x in value)
    if isinstance(value, dict):
        return any(privacy_scan(k) or privacy_scan(v, skip=skip) for k, v in value.items() if k not in skip)
    return False


def load_imports(doc, run, resolver, issues):
    # Shape/type errors outrank otherwise-well-formed privacy process failures.
    adjusted = copy.deepcopy(doc)
    for item in adjusted.get("imports", []) if isinstance(adjusted, dict) and isinstance(adjusted.get("imports"), list) else []:
        sanit = item.get("sanitization") if isinstance(item, dict) else None
        if isinstance(sanit, dict) and (sanit.get("review_attestation") is None or sanit.get("review_attestation") is False):
            sanit["review_attestation"] = True
            issues.append(problem("unreviewed_import", "imports", "Sanitized imports need producer review."))
    errors = resolver.validate(adjusted, "ux-sanitized-imports.v1.schema.json")
    if errors:
        raise EngineError("schema", "Import metadata fails its schema.", location=errors[0])
    if doc["run_id"] != run.meta["run_id"]:
        raise EngineError("run_id", "Imports belong to a different run.")
    result = {}
    brief = read_json(run.path / "brief.json") if (run.path / "brief.json").exists() else {}
    for item in doc["imports"]:
        path = item["artifact_ref"]
        if Path(path).is_absolute() or ".." in Path(path).parts:
            raise EngineError("unsafe_import", "Import artifacts must be safe run-relative text files.")
        raw = read_bytes(run.path / path, private=True, root=run.path)
        try:
            text = raw.decode("utf-8")
        except UnicodeError as exc:
            raise EngineError("import_encoding", "Import must be sanitized UTF-8 text.") from exc
        if item["content_sha256"] != byte_digest(raw) or item["import_id"] != import_identity(item):
            raise EngineError("import_hash", "Import content or provenance hash does not match.")
        if item["import_id"] in result and result[item["import_id"]][0] != item:
            raise EngineError("import_conflict", "An import ID has conflicting provenance.")
        if text.lstrip().startswith(("{", "[", "PK")) or Path(path).suffix.lower() not in {".txt", ".text"}:
            raise EngineError("raw_import", "Imports must be reviewed sanitized text, not raw exports.", 1)
        import re
        if re.search(r"(?im)^\s*(?:full[ _]?name|name|row[ _]?id|reverse[ _]?map|이름)\s*[:=]",text) or privacy_scan(text) or privacy_scan(item):
            issues.append(problem("import_identifiers", "imports", "Sanitized import still has identifier patterns."))
        if envelope.scan(text)["risk"] != "none":
            issues.append(problem("import_injection", "imports", "Import has unreviewed instruction markers."))
        acq = item["acquisition"]
        if acq["product"] != brief.get("product", {}).get("name"):
            raise EngineError("import_product", "Import acquisition names another product.")
        if acq["period_start"] > acq["period_end"] or acq["period_end"] > run.now_iso()[:10]:
            raise EngineError("import_period", "Import period is invalid.")
        if acq["kind"] == "store_console_export" and (acq["app_id"] not in acq["permission_ref"] or acq["app_id"] not in str(brief.get("product", {}).get("url", ""))):
            raise EngineError("import_permission", "Console permission must identify the authorized own app.")
        result[item["import_id"]] = (item, text)
    return result


def reconcile(returns, searches, assignments, acks, run, entries, hosts, issues):
    receipts = {}
    for call in searches:
        errors = Resolver().validate(call, "ux-reader-return.v1.schema.json", "searchReceipt")
        if errors:
            raise EngineError("schema", "Search receipt fails its schema.", location=errors[0])
        aid = call["assignment_id"]
        if aid not in assignments or call["phase"] != assignments[aid][1]["purpose"]:
            raise EngineError("search_assignment", "A search receipt does not match its assignment.")
        if call["call_id"] in receipts and receipts[call["call_id"]] != call:
            raise EngineError("search_conflict", "Search receipts with one ID disagree.")
        receipts[call["call_id"]] = call
    returned_calls, returned_requests = set(), set()
    doc_entries = {x["fetch_id"]: x for x in entries if x.get("kind") in {"request", "ingest"} and x.get("purpose") != "robots" and x.get("fetch_id")}
    policy_entries = {x["fetch_id"]: x for x in entries if x.get("kind") == "request" and x.get("purpose") == "robots" and x.get("fetch_id")}
    for part in returns:
        calls = {x["call_id"] for x in part["queries_run"]}
        for call in part["queries_run"]:
            if call["call_id"] not in receipts or receipts[call["call_id"]] != call:
                raise EngineError("invented_search", "A returned search receipt is absent or different in the search ledger.")
            if call["assignment_id"] != part["axis"]["assignment_id"]:
                raise EngineError("search_assignment", "Return includes a call from another assignment.")
        returned_calls |= calls
        budget = part["budget_used"]
        if part["search_count"] != len(calls) or budget["searches"] != len(calls):
            issues.append(problem("search_count", "returns", "Returned search counts do not match invocations."))
        ids = set(budget["request_fetch_ids"])
        if ids - doc_entries.keys() - policy_entries.keys():
            raise EngineError("invented_request", "A request ID is absent from the access ledger.")
        if budget["document_requests"] != len(ids & doc_entries.keys()) or budget["policy_requests"] != len(ids & policy_entries.keys()):
            issues.append(problem("request_count", "returns", "Returned request counts do not match request IDs."))
        returned_requests |= ids
    if returned_calls != set(receipts):
        issues.append(problem("unattributed_search", "search-ledger", "Actual search calls are not all reconciled to returns."))
    if set(doc_entries) - returned_requests:
        issues.append(problem("unattributed_document", "returns", "Document requests are not all reconciled to returns."))
    gaps = []
    by_host = Counter(x.get("host", "") for x in doc_entries.values())
    for host, row in hosts.get("hosts", {}).items():
        charged = row.get("docs", 0)
        logged = by_host[host]
        if type(charged) is not int or charged < logged:
            raise EngineError("request_integrity", "Logged requests exceed charged document slots.")
        if charged > logged:
            gap = dict(host=host, charged_documents=charged, logged_documents=logged, unmatched_count=charged-logged)
            gaps.append(gap)
            if not any(x["kind"] == "unattributed_request" and x["request_gap"] == gap for x in acks["entries"]):
                issues.append(problem("unattributed_request", "hosts", "Charged crash reservations require a current acknowledgement."))
    for ack in acks["entries"]:
        if ack["kind"] == "unattributed_request" and ack["request_gap"] not in gaps:
            raise EngineError("request_ack", "Request acknowledgement does not match current charged slots.")
    docs = hosts.get("run", {}).get("docs", 0)
    policies = hosts.get("run", {}).get("policy_requests", 0)
    if type(docs) is not int or docs != sum(x.get("docs", 0) for x in hosts.get("hosts", {}).values()) or docs < len(doc_entries):
        raise EngineError("request_integrity", "Global charged document slots disagree with host state.")
    if type(policies) is not int or policies < len(policy_entries):
        raise EngineError("request_integrity", "Policy request counts disagree with ledger state.")
    limit = run.policy.get("search_queries", 120)
    if len(receipts) > limit or docs > run.policy["per_run"]:
        issues.append(problem("budget", "budgets", "Run budget exceeded."))
    for host, row in hosts.get("hosts", {}).items():
        if row.get("docs", 0) > run.host_limit(host):
            issues.append(problem("budget", "hosts", "Host document budget exceeded."))
    warnings = [problem("search_budget_near", "budgets", "Search count is at least eighty percent of its budget.")] if len(receipts) >= (4*limit+4)//5 else []
    grouped = defaultdict(list)
    for call in receipts.values():
        for q in call["queries"]:
            grouped[(quote_text(q["q"]), q["lang"])].append(call["call_id"])
    return dict(schema_version="ux-query-log.v1", run_id=run.meta["run_id"], receipts=sorted(receipts.values(), key=lambda x: x["call_id"]),
                duplicate_queries=[dict(q=k[0],lang=k[1],call_ids=sorted(set(v))) for k,v in sorted(grouped.items()) if len(set(v))>1],
                total_invocations=len(receipts), counts_by_phase={k:sum(x["phase"]==k for x in receipts.values()) for k in ("discovery","expansion","counter_search")},
                counts_by_assignment={k:sum(x["assignment_id"]==k for x in receipts.values()) for k in sorted(assignments)},
                request_fetch_ids=sorted(set(doc_entries)|set(policy_entries)), document_requests=docs, policy_requests=policies, request_gaps=gaps, issues=[], warnings=warnings)


def harvest(returns, assignments, axes, acks, issues):
    parts, seen = {}, {}
    for ret in returns:
        rid = ret["return_id"]
        if rid in seen and seen[rid] != canonical(ret):
            raise EngineError("return_conflict", "A return ID has changed canonical content.")
        seen[rid] = canonical(ret)
        axis = ret["axis"]
        aid, index = axis["assignment_id"], axis["part_index"]
        if aid not in assignments:
            raise EngineError("unexpected_return", "Return is from an undeclared or excluded assignment.")
        plan, assign = assignments[aid]
        if any(axis[k] != v for k,v in {"axis_id":plan["axis_id"], "reader_id":assign["reader_id"], "round":assign["round"], "audience_questions":plan["audience_questions"]}.items()):
            raise EngineError("assignment_changed", "Return does not match its frozen assignment.")
        if index > axis["part_count"]:
            raise EngineError("part_index", "Return part index exceeds its part count.")
        key = aid,index
        if key in parts and canonical(parts[key]) != canonical(ret):
            raise EngineError("part_overlap", "Different returns overlap one assignment part.")
        parts[key] = ret
    for ack in acks["entries"]:
        kind = ack["kind"]
        if kind == "unattributed_request":
            continue
        axis = axes.get(ack["axis_id"])
        if kind == "excluded":
            if not axis or not axis["excluded"] or ack["reason"] != axis["reason"]:
                raise EngineError("acknowledgement", "Excluded acknowledgement disagrees with manifest.")
        elif ack["assignment_id"] not in assignments or assignments[ack["assignment_id"]][0]["axis_id"] != ack["axis_id"]:
            raise EngineError("acknowledgement", "Acknowledgement names an incompatible assignment.")
    gaps = []
    for aid,(axis,_) in assignments.items():
        found = [x for (a,_),x in parts.items() if a==aid]
        counts = {x["axis"]["part_count"] for x in found}
        if len(counts)>1:
            raise EngineError("part_count", "Assignment parts disagree about part count.")
        complete = bool(found) and len(found)==next(iter(counts)) and all(x["axis"]["completion"]=="complete" for x in found)
        if not complete:
            kind = "partial" if found else "missing"
            ack = next((x for x in acks["entries"] if x["assignment_id"]==aid and x["kind"]==kind), None)
            gaps.append(dict(code="coverage_"+kind,assignment_id=aid,axis_id=axis["axis_id"],acknowledged=bool(ack)))
            if not ack:
                issues.append(problem("harvest_"+kind, "assignments", "Incomplete coverage requires acknowledgement."))
    return [parts[k] for k in sorted(parts)], gaps


def source_capture(src, run, entries, imports, issues, warnings, prior_bundle=None):
    prov = src["provenance"]
    if prov["kind"] == "import":
        if prov["import_id"] not in imports:
            raise EngineError("import_provenance", "Source import has no producer provenance.")
        imp,text = imports[prov["import_id"]]
        if any(src[k] != imp[v] for k,v in (("source_type","source_type"),("org","producer_org"),("producer_stake","producer_stake"),("retention_until","retention_until"))):
            raise EngineError("import_metadata", "Source metadata differs from its reviewed import.")
        if prov["content_sha256"] != imp["content_sha256"]:
            raise EngineError("import_hash", "Source hash differs from import content.")
        scan = captured({**verdict.content_flags(text),"injection":envelope.scan(text)})
        if any(set(digest(x) for x in scan[k])-set(digest(x) for x in src["flags"][k]) for k in HITS):
            raise EngineError("capture_flags", "Import source omits captured flag candidates.")
        if src.get("item_key") or src.get("author_key") or src.get("thread_key"):
            warnings.append(problem("identity_unknown","sources","Reviewed import text has no item/author binding; the entire import is one unknown-identity unit."))
        src.update(item_key=None,author_key=None,thread_key=None,identity_status="unknown")
        return "team-import://"+run.meta["run_id"]+"/"+prov["import_id"], prov["import_id"], text, None
    fetch = prov["fetch_id"]
    outcomes = [x for x in entries if x.get("kind")=="outcome" and x.get("fetch_id")==fetch]
    if len(outcomes)!=1:
        raise EngineError("capture_provenance", "Fetch ID must identify exactly one successful reader outcome.")
    outcome = outcomes[0]
    if outcome.get("source") not in {"read","ingest"} or outcome.get("bucket")!="read" or outcome.get("verdict") not in {"ok_strong","ok_weak"} or outcome.get("stop_class"):
        raise EngineError("capture_provenance", "Fetch ID is not a successful unstopped read or ingest outcome.")
    if resource_url(privacy.mask_url(outcome["url"])) != resource_url(src["url"]):
        raise EngineError("capture_url", "Return URL does not match the successful capture URL.")
    platform,_=ladder.Routes(run.routes).match(src["url"])
    expected_family=platform.get("platform_family") if platform else src["source_type"]
    if src["platform_family"]!=expected_family:
        raise EngineError("platform_family","Source channel family differs from the pinned route or source type.")
    requests = [x for x in entries if x.get("fetch_id")==fetch and x.get("kind") in {"request","ingest"}]
    if len(requests)!=1 or requests[0].get("purpose")=="robots":
        raise EngineError("capture_request", "Capture has no matching document request or booked render.")
    request = requests[0]
    for x in [request,*outcome.get("trail", [])]:
        for key in ("url","final_url"):
            url = x.get(key)
            if url:
                stopped,_ = ladder.scope_check(run, ladder.Routes(run.routes), url)
                if stopped and not (src["access_basis"]=="official_api" and stopped.kind=="terms"):
                    raise EngineError("capture_policy", "Capture trail contains a policy-stopped URL.")
    if src["access_basis"] == "official_api" and (not outcome.get("api") or src["access"]["rung"]!="R0"):
        raise EngineError("api_provenance", "Official API source has no packaged adapter success.")
    if src["access_basis"] == "authorised_member" and not ladder.authorised_community(run, src["url"]):
        raise EngineError("member_provenance", "Member source lacks applicable brief authorization.")
    page_path=run.path/"pages"/(fetch+".txt")
    text=read_bytes(page_path,private=True,root=run.path).decode("utf-8") if page_path.exists() else None
    prior_source=next((x for x in (prior_bundle or {}).get("records",{}).get("sources",[]) if any(c["capture_ref"]==fetch and c["content_sha256"]==prov["content_sha256"] for c in x.get("captures",[])) and resource_url(src["url"]) in {resource_url(u) for u in x.get("aliases",[]) if u}),None)
    if text is None and prior_source is None:
        raise EngineError("capture_purged", "New quotations need captured text; only unchanged receipt-checked evidence can be reused after page TTL.")
    if prov["content_sha256"]!=outcome.get("content_sha256") or text is not None and byte_digest(text.encode())!=prov["content_sha256"]:
        raise EngineError("capture_hash", "Scrubbed capture hash differs from ledger or return.")
    meta=outcome.get("capture_metadata")
    if not meta:
        if text is None:
            selected=next(c for c in prior_source["captures"] if c["capture_ref"]==fetch)
            original=selected["metadata"]
            meta=dict(access=original["access"],flags=original["flags"],retention_until=original["retention_until"],access_basis=original["access_basis"],final_url=prior_source["source_ref"])
        else:
            flags=captured({**verdict.content_flags(text),"injection":envelope.scan(text)})
            access={k:outcome.get(k) for k in ("rung","presentation","verdict","context","terms")}
            access.update(stop_class="none",fetched_at=outcome.get("fetched_at"),robots=outcome.get("robots"))
            meta=dict(access=access,flags=flags,retention_until=outcome.get("retention_until"),access_basis=outcome.get("access_basis"),final_url=request.get("final_url"))
    expected=meta["access"]
    if src["access"]!=expected or src["observed_at"]!=outcome.get("fetched_at") or src["access_basis"]!=outcome.get("access_basis") or src["retention_until"]!=meta["retention_until"] or src["retention_status"]!="retained" or src["access_method"]!=outcome.get("presentation"):
        raise EngineError("capture_access", "Source access, dates or retention differ from authoritative capture metadata.")
    selected_attestation=(meta.get("item_attestations") or {}).get(src["item_key"]) if src.get("item_key") else None
    scan=selected_attestation.get("flags",meta["flags"]) if selected_attestation else meta["flags"]
    rescan = captured({**verdict.content_flags(text),"injection":envelope.scan(text)}) if text is not None else empty()
    # Metadata retains block-specific scans; whole-page injection must never disappear.
    scan=combine(scan,{**empty(),"injection_flags":rescan["injection_flags"]})
    if any(set(digest(x) for x in scan[k])-set(digest(x) for x in src["flags"][k]) for k in HITS):
        raise EngineError("capture_flags", "Return omits authoritative capture flag candidates.")
    if meta.get("final_url"):
        final=resource_url(meta["final_url"])
        if request.get("final_url") and final!=resource_url(privacy.mask_url(request["final_url"])):
            raise EngineError("redirect_provenance", "Final URL is not established by the successful trail.")
    else:
        final=resource_url(src["url"])
    # No adapter currently exposes item/author attestations in generic captures.
    attest = (meta.get("item_attestations") or {}).get(src["item_key"]) if src.get("item_key") else None
    if attest:
        if attest.get("author_key")!=src["author_key"] or attest.get("content_sha256")!=prov["content_sha256"]:
            raise EngineError("item_attestation", "Item identity is not bound to this capture.")
        if text is not None:
            text = text[attest["start"]:attest["end"]]
            if byte_digest(text.encode())!=attest["text_sha256"]:
                raise EngineError("item_attestation","Captured item offsets do not match the adapter attestation.")
        if src["published_at"]!=attest["published_at"]:
            raise EngineError("item_date","Return item publication date differs from the adapter attestation.")
        src["identity_status"]="attested"
    else:
        if src["author_key"] or src["item_key"] or src["thread_key"]:
            warnings.append(problem("identity_unknown","sources","Unattested item and author hints were reduced to the whole captured page."))
        src.update(author_key=None,item_key=None,thread_key=None,identity_status="unknown")
    return final,fetch,text,meta


def build(run, store, *, manifest, acknowledgements, search_ledger, imports_doc, returns, input_digests=None, hash_fn=digest):
    validate_policy(run,open_required=True)
    issues,warnings=[],[]
    resolver=Resolver()
    prior_bundle=store.committed("bundle.json") if store.has("bundle.json") else None
    if prior_bundle:
        from .engine import expired_sources,purge,now_of,purge_artifacts
        expired=expired_sources(prior_bundle,now_of(run))
        if expired:
            prior_bundle,old_receipt=purge(prior_bundle,store.committed("merge_receipt.json"),expired,now_of(run))
            store.publish("retention_purge",{"bundle.json":prior_bundle,"merge_receipt.json":old_receipt},invalidates_gate=True)
            purge_artifacts(run,old_receipt)
    axes,assignments=manifest_plan(manifest,run,prior_bundle["research"]["manifest"] if prior_bundle else None)
    require(acknowledgements,"ux-axis-acknowledgements.v1.schema.json")
    if acknowledgements["run_id"]!=run.meta["run_id"]:
        raise EngineError("run_id","Acknowledgements belong to a different run.")
    normalized=[]
    for original in returns:
        value=copy.deepcopy(original)
        if isinstance(value,dict) and isinstance(value.get("excerpts"),list):
            for excerpt in value["excerpts"]:
                if isinstance(excerpt,dict) and isinstance(excerpt.get("excerpt"),str):
                    excerpt["excerpt"]=quote_text(excerpt["excerpt"])
                    if len(excerpt["excerpt"])>300:
                        issues.append(problem("quote_length","excerpts","Normalized quote exceeds 300 code points."))
                        # Preserve hard shape precedence without misclassifying a length failure.
                        excerpt["excerpt"]=excerpt["excerpt"][:300]
        validation_value=copy.deepcopy(value)
        import re
        for src in validation_value.get("sources",[]) if isinstance(validation_value,dict) and isinstance(validation_value.get("sources"),list) else []:
            if isinstance(src,dict) and src.get("privacy_class")=="aggregate":
                if src.get("item_key") is not None or src.get("author_key") is not None or src.get("thread_key") is not None:
                    issues.append(problem("aggregate_identity","sources","Aggregates must not retain personal item, author or thread keys."))
                for key in ("author_key","thread_key"):
                    if isinstance(src.get(key),str) and re.fullmatch(r"[0-9a-f]{16}",src[key]):src[key]=None
        errors=resolver.validate(validation_value,"ux-reader-return.v1.schema.json")
        if errors:
            raise EngineError("schema","Reader return fails its schema.",location=errors[0])
        if value["run_id"]!=run.meta["run_id"]:
            raise EngineError("run_id","Reader return belongs to a different run.")
        normalized.append(value)
    parts,gaps=harvest(normalized,assignments,axes,acknowledgements,issues)
    entries,hosts=ledger_snapshot(run)
    import_map=load_imports(imports_doc,run,resolver,issues)
    query=reconcile(parts,search_ledger,assignments,acknowledgements,run,entries,hosts,issues)
    warnings+=query["warnings"]
    ids=Ids(hash_fn); records={k:[] for k in ARRAYS}; sources={}; evidence={}; claims={}; proofs={k:[] for k in ("source_proofs","evidence_proofs","claim_proofs")}; rewrites=[]
    excerpt_count=defaultdict(set)
    for ret in parts:
        local_src={};local_ev={};local_claim={}
        assignment=ret["axis"]["assignment_id"]; part=ret["axis"]["part_index"]
        def rewrite(local,kind,global_id):
            rewrites.append(dict(assignment_id=assignment,part_index=part,local_id=local,record_kind=kind,id=global_id))
        if any(len({x['local_id'] for x in ret[k]})!=len(ret[k]) for k in ('sources','excerpts','candidate_claims')):
            raise EngineError("local_id","Local record IDs must be unique within each part and kind.")
        for original in ret["sources"]:
            src=copy.deepcopy(original)
            url,capture,text,_=source_capture(src,run,entries,import_map,issues,warnings,prior_bundle)
            if src["privacy_class"]=="protected_individual" or (src["flags"]["protected_attribute_cue"] and src["privacy_class"]!="aggregate"):
                issues.append(problem("protected_component","sources","Remove the entire personal evidence component and resubmit."))
            if src["privacy_class"]=="aggregate" and (src["author_key"] or src["thread_key"] or src["item_key"] or src["source_family"]=="voice"):
                issues.append(problem("aggregate_identity","sources","An aggregate cannot retain individual keys or voice post locators."))
            if privacy_scan({k:v for k,v in src.items() if k not in {"url","stat_card"}}):
                issues.append(problem("identifiers","sources","Source metadata contains identifier patterns."))
            sid,full=ids.make("SRC",[run.meta["run_id"],url,src["item_key"]])
            meta={k:v for k,v in src.items() if k not in {"local_id","url","item_key","identity_status"}}
            cap=dict(capture_ref=capture,content_sha256=src["provenance"]["content_sha256"],metadata=meta)
            src.pop("local_id");src.pop("url");src.update(id=sid,source_ref=url,channel=src["platform_family"],aliases=[original["url"]] if original["url"] else [],captures=[cap])
            if sid in sources:
                old=sources[sid]
                oldcap=next((x for x in old["captures"] if x["capture_ref"]==capture),None)
                if oldcap and oldcap!=cap:
                    raise EngineError("capture_conflict","One capture has conflicting source metadata.")
                for key in ("author_key","org"):
                    if old.get(key) and src.get(key) and old[key]!=src[key]:
                        raise EngineError("identity_conflict","One resource has conflicting producer identities.")
                if any(old.get(k)!=src.get(k) for k in ("published_at","valid_at","version")):
                    warnings.append(problem("capture_dates_changed","sources","Different capture dates/versions remain separately visible for grading."))
                captures=old["captures"]+([] if oldcap else [cap]); aliases=sorted(set(old["aliases"]+src["aliases"]))
                if src["observed_at"]>old["observed_at"] or src["observed_at"]==old["observed_at"] and capture<old["provenance"].get("fetch_id",old["provenance"].get("import_id")):
                    old.update(src)
                old.update(captures=captures,aliases=aliases)
            else:
                sources[sid]=src
                proofs["source_proofs"].append(dict(source_id=sid,full_id_sha256=full,captures=[]))
            local_src[original["local_id"]]=(sid,capture,text,src)
            rewrite(original["local_id"],"source",sid)
        for original in ret["excerpts"]:
            if original["source_local_id"] not in local_src:
                raise EngineError("local_reference","Excerpt references an unknown local source.")
            sid,capture,text,src=local_src[original["source_local_id"]]
            if original["capture_ref"]!=capture:
                raise EngineError("capture_ref","Excerpt references another capture.")
            quote=original["excerpt"]
            scrubbed,replacements=privacy.scrub(quote)
            if sum(replacements.values()) or privacy_scan(original["summary"]):
                issues.append(problem("quote_identifiers","excerpts","Backstop identifier replacement requires a sanitized resubmission."))
            prior_excerpt=next((e for e in (prior_bundle or {}).get("records",{}).get("evidence",[]) if e.get("source_id")==sid and e.get("capture_ref")==capture and e.get("excerpt")==quote),None)
            if text is None and prior_excerpt is None:
                raise EngineError("capture_purged","A new or changed quotation requires captured text.")
            if text is not None and quote_text(scrubbed) not in quote_text(text):
                raise EngineError("invented_quote","Normalized quote is not contiguous in the scrubbed capture.")
            eid,full=ids.make("EV",[run.meta["run_id"],sid,capture,src["provenance"]["content_sha256"],quote,src["item_key"]])
            item={k:copy.deepcopy(v) for k,v in original.items() if k not in {"local_id","source_local_id"}}
            if item.get("approved_values"):
                if src["source_type"]!="product_brief" or src["access_basis"]!="team_provided":
                    raise EngineError("approved_value_provenance","Approved task values require a reviewed native product brief.")
                for proof in item["approved_values"]:
                    vals=proof["value"].values() if isinstance(proof["value"],dict) else [proof["value"]]
                    def literal(v):
                        return "true" if v is True else "false" if v is False else "null" if v is None else str(v)
                    if any(literal(v).casefold() not in (text or quote).casefold() for v in vals):
                        raise EngineError("approved_value_literal","Approved task values must occur in the reviewed brief text.")
            item.update(id=eid,source_id=sid,flags=combine(src["flags"],item["flags"]),copypaste_group=byte_digest(quote.encode()))
            if item["flags"]["protected_attribute_cue"] and src["privacy_class"]!="aggregate":
                issues.append(problem("protected_component","excerpts","Personal protected-attribute links must be removed and resubmitted."))
            if eid in evidence and evidence[eid]!=item:
                raise EngineError("evidence_conflict","Equal excerpt identities have conflicting metadata.")
            if text is None and item!=prior_excerpt:
                raise EngineError("capture_purged","Changed evidence metadata needs an available capture and new merge proof.")
            evidence[eid]=item;local_ev[original["local_id"]]=eid
            excerpt_count[sid].add(quote)
            if not any(x["evidence_id"]==eid for x in proofs["evidence_proofs"]):
                proofs["evidence_proofs"].append(dict(evidence_id=eid,source_id=sid,capture_ref=capture,full_id_sha256=full,normalized_excerpt_sha256=byte_digest(quote.encode()),item_binding_sha256=digest([sid,capture,src["item_key"]]),fields_sha256=digest(item)))
            rewrite(original["local_id"],"evidence",eid)
        def refs(values,mapping):
            if any(x not in mapping for x in values):
                raise EngineError("local_reference","Reader record references an unknown local record.")
            return sorted(set(mapping[x] for x in values))
        for original in ret["candidate_claims"]:
            claim=copy.deepcopy(original)
            claim.pop("local_id")
            claim["evidence_ids"]=refs(claim.pop("excerpt_ids"),local_ev)
            claim["counter_evidence_ids"]=refs(claim.pop("counter_excerpt_ids"),local_ev)
            claim["context_evidence_ids"]=refs(claim.pop("context_excerpt_ids"),local_ev)
            registered_observations={x["id"] for x in (prior_bundle or {}).get("records",{}).get("observations",[])}
            if set(claim["observation_ids"])-registered_observations:
                raise EngineError("observation_reference","Reader returns cannot introduce unregistered product observations.")
            for value in claim["audience_values"]:
                value["denominator_evidence_ids"]=refs(value["denominator_evidence_ids"],local_ev)
                for check in value["value_checks"]:
                    check["evidence_id"]=refs([check["evidence_id"]],local_ev)[0]
            if claim["counter_search"]:
                c=claim["counter_search"];c["read_source_ids"]=refs(c["read_source_ids"],{k:v[0] for k,v in local_src.items()});c["counter_evidence_ids"]=refs(c["counter_evidence_ids"],local_ev)
            claim["statement"]=quote_text(claim["statement"])
            cid,full=ids.make("CLM",claim_identity(run.meta["run_id"],claim))
            claim.update(id=cid,epistemic_status="unknown",verification_status="unverified",research_epistemic_status="unknown",research_support_evidence_ids=list(claim["evidence_ids"]),research_context_evidence_ids=list(claim["context_evidence_ids"]))
            if privacy_scan(claim["statement"]) or privacy_scan(claim["audience_values"]):
                issues.append(problem("claim_identifiers","claims","Claim content contains identifier patterns."))
            if cid in claims:
                old=claims[cid]
                if old["counter_search"] is None:old["counter_search"]=claim["counter_search"]
                elif claim["counter_search"] is not None and old["counter_search"]!=claim["counter_search"]:
                    raise EngineError("claim_conflict","Equal claim identities have incompatible counter-search records.")
                for k in ("stakes","about_current_version"):
                    if old[k]!=claim[k]:
                        raise EngineError("claim_conflict","Equal claim identities have conflicting metadata.")
                for k in ("evidence_ids","research_support_evidence_ids","context_evidence_ids","research_context_evidence_ids","counter_evidence_ids","scenario_priorities","audience_values"):
                    old[k]=[loads(x) for x in sorted(set(canonical(x) for x in old[k]+claim[k]))]
            else:
                claims[cid]=claim
                proofs["claim_proofs"].append(dict(claim_id=cid,full_id_sha256=full,original_support_ids=claim["evidence_ids"],original_context_ids=claim["context_evidence_ids"],original_counter_ids=claim["counter_evidence_ids"]))
            local_claim[original["local_id"]]=cid;rewrite(original["local_id"],"claim",cid)
    from .integrity_checks import privacy_graph
    if prior_bundle:
        old_receipt=store.committed("merge_receipt.json")
        for name in ARRAYS[3:]:records[name]=copy.deepcopy(prior_bundle["records"][name])
        for old_source in prior_bundle["records"]["sources"]:
            if old_source.get("research_tombstone") and old_source["id"] not in sources:
                sources[old_source["id"]]=copy.deepcopy(old_source)
                proof=next(x for x in old_receipt["source_proofs"] if x["source_id"]==old_source["id"])
                proofs["source_proofs"].append(copy.deepcopy(proof))
        for old_evidence in prior_bundle["records"]["evidence"]:
            if old_evidence["source_id"] in sources and sources[old_evidence["source_id"]].get("research_tombstone") and old_evidence["id"] not in evidence:
                evidence[old_evidence["id"]]=copy.deepcopy(old_evidence)
                proof=next(x for x in old_receipt["evidence_proofs"] if x["evidence_id"]==old_evidence["id"])
                proofs["evidence_proofs"].append(copy.deepcopy(proof))
        for old_claim in prior_bundle["records"]["claims"]:
            cid=old_claim["id"]
            old_proof=next((x for x in old_receipt["claim_proofs"] if x["claim_id"]==cid),None)
            if cid not in claims and (old_claim["claim_kind"]=="product_behavior" or old_proof and old_proof.get("purged")):
                claim=copy.deepcopy(old_claim);claim.update(verification_status="unverified",epistemic_status=claim["research_epistemic_status"])
                claim["evidence_ids"]=claim["research_support_evidence_ids"][:];claim["context_evidence_ids"]=claim["research_context_evidence_ids"][:]
                claims[cid]=claim
                if old_proof:proofs["claim_proofs"].append(copy.deepcopy(old_proof))
            elif cid in claims:
                claim=claims[cid]
                if set(old_claim["counter_evidence_ids"])-set(evidence):
                    raise EngineError("counter_history","Remerge cannot discard historical contrary evidence; retain its return or purge it.")
                claim["counter_evidence_ids"]=sorted(set(claim["counter_evidence_ids"])|set(old_claim["counter_evidence_ids"]))
                if not claim["counter_search"]:claim["counter_search"]=copy.deepcopy(old_claim.get("counter_search"))
                claim["observation_ids"]=sorted(set(claim["observation_ids"])|set(old_claim["observation_ids"]))
    if any(len(v)>5 for v in excerpt_count.values()):
        issues.append(problem("resource_excerpt_cap","excerpts","A resource exceeds five distinct excerpts."))
    for proof in proofs["source_proofs"]:
        if not proof.get("purged"):
            proof["captures"]=ordered(sources[proof["source_id"]]["captures"],"captures")
    for proof in proofs["claim_proofs"]:
        c=claims[proof["claim_id"]]
        for key,field in (("original_support_ids","research_support_evidence_ids"),("original_context_ids","research_context_evidence_ids"),("original_counter_ids","counter_evidence_ids")):
            proof[key]=c[field]
    for name,collection in (("sources",sources),("evidence",evidence),("claims",claims)):
        records[name]=[collection[k] for k in sorted(collection)]
    bid="bundle-"+run.meta["run_id"]
    expansion=expansion_log(parts,assignments,run,gaps)
    receipt=dict(schema_version="ux-merge-receipt.v1",contract_version=CONTRACT,run_id=run.meta["run_id"],bundle_id=bid,input_sha256s=input_digests or {},manifest_sha256=digest(manifest),query_log_sha256=digest(query),expansion_log_sha256=digest(expansion),rules_sha256=digest(rules_inputs()),**proofs,id_rewrites=sorted(rewrites,key=canonical),counter_history=[])
    if prior_bundle:
        old=store.committed("merge_receipt.json")
        receipt["counter_history"]=old["counter_history"]
        old_ids={x["id"] for x in prior_bundle["records"]["claims"]}
        if old_ids-set(claims):
            raise EngineError("claim_history","Remerge cannot remove historical claims.")
    for c in claims.values():
        if c["counter_evidence_ids"] or c["counter_search"]:
            cs=c["counter_search"] or {}
            entry=dict(claim_id=c["id"],counter_evidence_ids=c["counter_evidence_ids"],call_ids=cs.get("call_ids",[]),outcome=cs.get("outcome"),resolution_id=cs.get("resolution_id"))
            if entry not in receipt["counter_history"]:receipt["counter_history"].append(entry)
    bundle=dict(schema_version="ux-evidence-bundle.v1",bundle_id=bid,permissions=dict(requested=["read_only"],granted=["read_only"],blocked=[]),records=records,
                research=dict(contract_version=CONTRACT,run_id=run.meta["run_id"],manifest=manifest,query_log_sha256=digest(query),expansion_log_sha256=digest(expansion),merge_receipt_sha256=digest(receipt),rules_version=RULES,verifier_decisions=copy.deepcopy(prior_bundle["research"]["verifier_decisions"]) if prior_bundle else [],scope_resolutions=copy.deepcopy(prior_bundle["research"]["scope_resolutions"]) if prior_bundle else [],gaps=gaps+[x for x in prior_bundle["research"]["gaps"] if x.get("code") in {"evidence_expired","evidence_unavailable"}] if prior_bundle else gaps,summary_attestations=[]))
    issues += privacy_graph(bundle)
    require(bundle,"ux-evidence-bundle.v1.schema.json")
    result=dict(schema_version="ux-merge-result.v1",result="fail" if issues else "pass",exit_code=1 if issues else 0,issues=issues,warnings=warnings,gaps=gaps,counts={k:len(v) for k,v in records.items()},input_sha256s=input_digests or {})
    return bundle,query,expansion,receipt,result


def expansion_log(parts,assignments,run,gaps):
    seen=set();segments=set();problems=set();rounds=[]
    groups={number:[x for x in parts if x["axis"]["round"]==number] for number in (0,1,2)}
    for number in (0,1,2):
        new_leads=[];rejected=[];new_segments=set();new_problems=set()
        for ret in groups[number]:
            for dead in ret["dead_ends"]:
                lead=dead.get("lead") or dead.get("url") or dead.get("q") if isinstance(dead,dict) else dead
                if isinstance(lead,str) and lead:
                    key=resource_url(lead) if lead.startswith(("http://","https://")) else quote_text(lead).casefold()
                    seen.add(key)
            for lead in ret["expand_leads"]:
                key=resource_url(lead["lead"]) if lead["lead"].startswith(("http://","https://")) else quote_text(lead["lead"]).casefold()
                if key in seen:rejected.append(dict(lead=lead,reason="already_seen"))
                else:seen.add(key);new_leads.append(lead)
            for claim in ret["candidate_claims"]:
                segment=claim["subject"].get("segment_id");pain=claim["subject"].get("pain_point_id")
                if segment and segment not in segments:new_segments.add(segment)
                if pain and pain not in problems:new_problems.add(pain)
        segments|=new_segments;problems|=new_problems
        assigned=[k for k,v in assignments.items() if v[1]["purpose"]=="expansion" and v[1]["round"]==number]
        if assigned:rounds.append(dict(round=number,assignment_ids=sorted(assigned),new_leads=new_leads,rejected_leads=rejected,new_segment_keys=sorted(new_segments),new_problem_keys=sorted(new_problems)))
    stop="two_rounds_without_new" if len(rounds)==2 and all(not x["new_segment_keys"] and not x["new_problem_keys"] for x in rounds) else "round_limit" if len(rounds)==2 else "budget" if len(parts) and any(x["budget_used"]["searches"]>=run.policy.get("search_queries",120) for x in parts) else "no_leads"
    return dict(schema_version="ux-expansion-log.v1",run_id=run.meta["run_id"],rounds=rounds,seen_leads=sorted(seen),stop_reason=stop,gaps=gaps)
