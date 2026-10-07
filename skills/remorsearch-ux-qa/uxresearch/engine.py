"""Research transactions, gate integrity and the shared consumer data-flow lock."""
from __future__ import annotations

import copy
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.validate_bundle import validate_bundle
from . import scope
from .canonical import EngineError, byte_digest, canonical, claim_identity, digest, input_bundle, ordered, timestamp
from .grading import SUPPORTED, assess
from .merge import ARRAYS, CONTRACT, RULES, build, ledger_snapshot, problem, rules_inputs, validate_policy
from .schema import require
from .storage import Store, read_bytes, read_json, safe_path


def now_of(run):
    return datetime.fromtimestamp(run.clock(),timezone.utc)


def expired_sources(bundle,now):
    expired=[]
    for source in bundle["records"]["sources"]:
        if source.get("research_tombstone"):continue
        deadlines=[source.get("retention_until")]+[x["metadata"].get("retention_until") for x in source.get("captures",[])]
        if any(timestamp(x,bare_date=True)<=now for x in deadlines if x):expired.append(source["id"])
    return expired


def purge(bundle,receipt,source_ids,now):
    """Content repair is committed even when the subsequent assessment fails."""
    bundle,receipt=copy.deepcopy(bundle),copy.deepcopy(receipt)
    affected_sources=set(source_ids);removed=set();dead_captures=set()
    stamp=now.isoformat(timespec="seconds").replace("+00:00","Z")
    for i,src in enumerate(bundle["records"]["sources"]):
        if src["id"] not in affected_sources:continue
        live=[]
        for cap in src.get("captures",[]):
            deadline=cap["metadata"].get("retention_until")
            if deadline and timestamp(deadline,bare_date=True)<=now:dead_captures.add(cap["capture_ref"])
            else:live.append(cap)
        if live:
            latest=min(live,key=lambda c:(-timestamp(c["metadata"]["observed_at"]).timestamp(),c["capture_ref"]))
            src.update(latest["metadata"]);src["captures"]=live
            src.pop("summary",None)
        else:
            removed.add(src["id"])
            bundle["records"]["sources"][i]=dict(id=src["id"],channel="expired",source_ref="expired://"+src["id"],access_basis="redacted",access_method="retention_purge",public_scope="none",retention_status="deleted",research_tombstone=dict(reason="expired",removed_at=stamp,prior_access_basis=src["access_basis"]))
    eids={x["id"] for x in bundle["records"]["evidence"] if x["source_id"] in removed or x.get("capture_ref") in dead_captures}
    for i,ev in enumerate(bundle["records"]["evidence"]):
        if ev["id"] in eids:
            bundle["records"]["evidence"][i]=dict(id=ev["id"],source_id=ev["source_id"],evidence_type=ev["evidence_type"],epistemic_status="unknown",summary="Evidence removed at retention expiry.")
    affected=[]
    for claim in bundle["records"]["claims"]:
        fields=("evidence_ids","research_support_evidence_ids","research_context_evidence_ids","context_evidence_ids","counter_evidence_ids")
        linked=set(x for k in fields for x in claim.get(k,[]))
        if linked&eids:
            affected.append(claim["id"])
            counter_gap=bool(set(claim.get("counter_evidence_ids",[]))&eids)
            cs=claim.get("counter_search")
            gap=dict(code="evidence_expired",affected_claim_ids=[claim["id"]],removed_evidence_ids=sorted(linked&eids),counter_gap=counter_gap,note="Retained evidence was removed; obtain new evidence.",removed_at=stamp,prior_call_ids=cs["call_ids"] if cs else [])
            bundle["research"]["gaps"].append(gap)
            for field in fields:claim[field]=sorted(set(claim.get(field,[]))-eids)
            if cs:
                cs["counter_evidence_ids"]=sorted(set(cs["counter_evidence_ids"])-eids)
                cs["read_source_ids"]=sorted(set(cs["read_source_ids"])-removed)
                if counter_gap:claim["counter_search"]=None
            claim.update(statement="Evidence unavailable; claim requires new evidence.",audience_values=[],verification_status="unverified",epistemic_status="unknown",research_epistemic_status="unknown")
    bundle["research"]["verifier_decisions"]=[x for x in bundle["research"]["verifier_decisions"] if x["target_id"] not in removed|eids|set(affected) and not set(x["basis_evidence_ids"])&eids]
    bundle["research"]["scope_resolutions"]=[x for x in bundle["research"]["scope_resolutions"] if not (set(x["counter_evidence_ids"]+x["basis_evidence_ids"])&eids or x["claim_id"] in affected or x["prior_claim_id"] in affected)]
    bundle["research"]["summary_attestations"]=[x for x in bundle["research"].get("summary_attestations",[]) if x["record_id"] not in affected_sources|eids|set(affected)]
    for proof in receipt["source_proofs"]:
        if proof["source_id"] in affected_sources-removed:
            source=next(s for s in bundle["records"]["sources"] if s["id"]==proof["source_id"])
            proof["captures"]=source["captures"]
        if proof["source_id"] in removed:
            sid=proof["source_id"];proof.clear();proof.update(source_id=sid,captures=[],purged=True)
    for proof in receipt["evidence_proofs"]:
        if proof["evidence_id"] in eids:
            eid=proof["evidence_id"];proof.clear();proof.update(evidence_id=eid,purged=True)
    for proof in receipt["claim_proofs"]:
        if proof["claim_id"] in affected:
            proof["purged"]=True
            for field in ("original_support_ids","original_context_ids","original_counter_ids"):proof[field]=sorted(set(proof[field])-eids)
    for history in receipt["counter_history"]:history["counter_evidence_ids"]=sorted(set(history["counter_evidence_ids"])-eids)
    receipt["affected_input_files"]=sorted(receipt.get("input_sha256s",{}))
    receipt["input_sha256s"]={}
    receipt["purged_capture_refs"]=sorted(dead_captures)
    bundle["research"]["merge_receipt_sha256"]=digest(receipt)
    return bundle,receipt


def purge_artifacts(run,receipt):
    """Remove expired caches without changing reader policy, stops or charges."""
    dead=set(receipt.get("purged_capture_refs",[]))
    from .storage import atomic
    from .canonical import loads
    for capture in dead:
        if capture.startswith("F-"):
            path=run.path/"pages"/(capture+".txt")
            if path.exists():safe_path(path).unlink()
    imports_path=run.path/"sanitized-imports.json"
    if imports_path.exists():
        for item in read_json(imports_path).get("imports",[]):
            if item["import_id"] in dead:
                path=safe_path(run.path/item["artifact_ref"],run.path)
                if path.exists():path.unlink()
    for name in receipt.get("affected_input_files",[]):
        path=safe_path(run.path/name,run.path)
        if not path.exists() or not name.endswith(".json"):continue
        value=read_json(path)
        if isinstance(value,dict) and value.get("schema_version")=="ux-reader-return.v1" and any(x.get("capture_ref") in dead for x in value.get("excerpts",[])):
            path.unlink()
    with run._state():
        path=run.path/"access-ledger.jsonl"
        entries=[loads(line) for line in read_bytes(path,private=True).splitlines() if line.strip()]
        changed=False
        for entry in entries:
            if entry.get("fetch_id") in dead:
                for field in ("content_sha256","capture_metadata","scrubbed","flags","injection_risk","text_chars","reasons"):
                    entry.pop(field,None)
                for field in ("url","final_url"):
                    if entry.get(field):
                        from .privacy import origin_only
                        entry[field]=origin_only(entry[field])
                entry.pop("trail",None)
                entry.pop("redirects",None)
                changed=True
        if changed:atomic(path,b"".join(canonical(x)+b"\n" for x in entries))


def integrity(bundle,receipt,query,expansion,run):
    require(bundle,"ux-evidence-bundle.v1.schema.json")
    research=bundle.get("research")
    if not research or research["run_id"]!=run.meta["run_id"] or bundle["bundle_id"]!=receipt["bundle_id"] or receipt["run_id"]!=run.meta["run_id"]:
        raise EngineError("research_receipt","Research requires a matching external committed merge receipt.")
    if research["contract_version"]!=CONTRACT or research["rules_version"]!=RULES or receipt["rules_sha256"]!=digest(rules_inputs()):
        raise EngineError("rules_changed","The pinned research rules differ from the merge receipt; remerge.")
    if digest(research["manifest"])!=receipt["manifest_sha256"]:
        raise EngineError("manifest", "Manifest changed after merge; remerge the revised manifest.")
    if research["merge_receipt_sha256"]!=digest(receipt) or research["query_log_sha256"]!=digest(query) or research["expansion_log_sha256"]!=digest(expansion):
        raise EngineError("receipt_hash","Bundle process hashes differ from committed receipts.")
    errors=validate_bundle(bundle,now=now_of(run))
    if errors:
        raise EngineError("bundle_contract","Bundle does not satisfy its structural or graph contract.",location=errors[0])
    sources={x["id"]:x for x in bundle["records"]["sources"]}
    eproof={x["evidence_id"]:x for x in receipt["evidence_proofs"]}
    sproof={x["source_id"]:x for x in receipt["source_proofs"]}
    cproof={x["claim_id"]:x for x in receipt["claim_proofs"]}
    if len(sproof)!=len(receipt["source_proofs"]) or len(eproof)!=len(receipt["evidence_proofs"]) or len(cproof)!=len(receipt["claim_proofs"]):raise EngineError("receipt_duplicates","Proof IDs must be unique.")
    if set(sources)!=set(sproof):raise EngineError("source_receipt","Source set differs from committed merge proofs.")
    from .canonical import resource_url
    for sid,src in sources.items():
        proof=sproof[sid]
        if src.get("research_tombstone"):
            if not proof.get("purged"):raise EngineError("tombstone_receipt","Tombstone requires a committed purge receipt.")
            continue
        identity=[run.meta["run_id"],src["source_ref"],src.get("item_key")]
        if digest(identity)!=proof["full_id_sha256"] or sid!="SRC-"+proof["full_id_sha256"][:8] or src["captures"]!=proof["captures"]:
            raise EngineError("source_receipt","Resource identity or capture histories differ from their committed proof.")
        latest=min(src["captures"],key=lambda x:(-timestamp(x["metadata"]["observed_at"]).timestamp(),x["capture_ref"]))
        for key,value in latest["metadata"].items():
            if src.get(key)!=value:raise EngineError("source_header","Source header must be one complete selected capture.")
    if {x["id"] for x in bundle["records"]["evidence"]}!=set(eproof):raise EngineError("evidence_receipt","Evidence set differs from committed excerpt proofs.")
    for ev in bundle["records"]["evidence"]:
        proof=eproof[ev["id"]]
        if proof.get("purged"):
            if set(ev)!={"id","source_id","evidence_type","epistemic_status","summary"} or ev["epistemic_status"]!="unknown":raise EngineError("tombstone_receipt","Purged evidence retains content.")
            continue
        src=sources[ev["source_id"]]
        cap=next((x for x in src["captures"] if x["capture_ref"]==ev["capture_ref"]),None)
        if not cap or digest(ev)!=proof["fields_sha256"] or byte_digest(ev["excerpt"].encode())!=proof["normalized_excerpt_sha256"]:
            raise EngineError("evidence_receipt","Evidence content or metadata changed after authoritative merge.")
        full=digest([run.meta["run_id"],src["id"],ev["capture_ref"],cap["content_sha256"],ev["excerpt"],src.get("item_key")])
        if full!=proof["full_id_sha256"] or ev["id"]!="EV-"+full[:8]:raise EngineError("evidence_identity","Evidence identity does not match its canonical tuple.")
    for claim in bundle["records"]["claims"]:
        proof=cproof.get(claim["id"])
        if proof and proof.get("purged") and (claim["statement"]!="Evidence unavailable; claim requires new evidence." or claim["audience_values"]):
            raise EngineError("purge_identity","Purge identity exception permits only the fixed unknown statement and no derived audience values.")
        if not (proof and proof.get("purged")):
            full=digest(claim_identity(run.meta["run_id"],claim))
            if claim["id"]!="CLM-"+full[:8] or proof and proof["full_id_sha256"]!=full:raise EngineError("claim_identity","Claim identity differs from its joins, values, scope or statement.")
            if not proof and claim["claim_kind"]!="product_behavior" and not any(x["claim_id"]==claim["id"] for x in research["scope_resolutions"]):raise EngineError("claim_receipt","New source-based claims must enter through merge.")
    for history in receipt["counter_history"]:
        claim=next((x for x in bundle["records"]["claims"] if x["id"]==history["claim_id"]),None)
        if not claim or set(history["counter_evidence_ids"])-set(claim["counter_evidence_ids"]):raise EngineError("counter_history","A historical contrary link disappeared.")


def process_inputs(run,query,expansion,bundle,history=None):
    entries,hosts=ledger_snapshot(run)
    # close cuts URLs, removes pages/salt and adds summary; none changes these inputs.
    requests=sorted([dict(fetch_id=x.get("fetch_id"),kind=x["kind"],purpose=x.get("purpose"),host=x.get("host"),content_sha256=x.get("content_sha256"),bucket=x.get("bucket"),verdict=x.get("verdict"),stop_class=x.get("stop_class"),retention_until=x.get("retention_until")) for x in entries if x.get("kind") in {"request","ingest","outcome"}],key=canonical)
    return dict(counter_history=history or [],query_log=query,expansion_log=expansion,manifest=bundle["research"]["manifest"],policy=run.policy,
                mode="fixture" if run.meta.get("test_hooks") else "live",requests=requests,
                counts=hosts.get("run"),host_counts={k:{x:v.get(x,0) for x in ("docs","policy_requests")} for k,v in hosts.get("hosts",{}).items()},
                brief=read_json(run.path/"brief.json") if (run.path/"brief.json").exists() else {})


def projection(bundle,rows):
    out=copy.deepcopy(bundle);map_={r["claim_id"]:r for r in rows}
    for claim in out["records"]["claims"]:
        row=map_[claim["id"]]
        claim.update(evidence_ids=row["counting_evidence_ids"],context_evidence_ids=row["context_evidence_ids"],verification_status="verified" if row["status"] in SUPPORTED else "unverified",epistemic_status="observed" if row["status"] in SUPPORTED else claim["research_epistemic_status"])
    return ordered(out)


def check_partitions(bundle,store):
    if not store.has("gate.json"):return
    prior=store.committed("gate.json")
    committed=store.committed("bundle.json")
    old={x["id"]:x for x in committed["records"]["claims"]}
    for claim in bundle["records"]["claims"]:
        if claim["id"] not in old:continue
        previous=old[claim["id"]]
        for key,original in (("evidence_ids","research_support_evidence_ids"),("context_evidence_ids","research_context_evidence_ids")):
            if claim[key]!=previous[key] and claim[key]!=claim[original]:raise EngineError("output_partition","Manual output partitions do not match authored inputs or the prior gate projection.")


def gate_assessment(run,store,bundle,history_override=None):
    validate_policy(run)
    receipt=store.committed("merge_receipt.json");query=store.committed("query_log.json");expansion=store.committed("expansion_log.json")
    integrity(bundle,receipt,query,expansion,run);check_partitions(bundle,store)
    history=history_override if history_override is not None else store.committed("gate_receipt.json")["counter_history"] if store.has("gate_receipt.json") else []
    by_claim={c["id"]:c for c in bundle["records"]["claims"]}
    purged={e for gap in bundle["research"]["gaps"] for e in gap.get("removed_evidence_ids",[])}
    for entry in history:
        claim=by_claim.get(entry["claim_id"])
        if not claim or set(entry["counter_evidence_ids"])-set(claim["counter_evidence_ids"])-purged:
            raise EngineError("counter_history","A contrary link proven in an earlier gate was removed.")
    process=process_inputs(run,query,expansion,bundle,history)
    rules=rules_inputs()
    full=digest(dict(bundle=input_bundle(bundle),process=process,rules=rules))
    rows,issues,warnings=assess(bundle,process["brief"],query,receipt,full,now_of(run))
    from .integrity_checks import privacy_graph
    issues += privacy_graph(bundle)
    from .canonical import loads
    if (run.path/"search-ledger.jsonl").exists():
        searches=[loads(x) for x in read_bytes(run.path/"search-ledger.jsonl").splitlines() if x.strip()]
        calls={x["call_id"]:x for x in searches}
        if len(calls)!=len(searches) or sorted(calls.values(),key=lambda x:x["call_id"])!=query["receipts"]:
            issues.append(problem("search_state_changed","process","Search invocations changed after merge; remerge all returns."))
    # Reader receipts must still reconcile to the live charged state at every gate.
    if process["counts"]["docs"]!=query["document_requests"] or process["counts"]["policy_requests"]!=query["policy_requests"]:
        issues.append(problem("request_state_changed","process","Reader requests changed after merge; remerge all returns."))
    deadlines=[timestamp(x,bare_date=True) for s in bundle["records"]["sources"] for x in [s.get("retention_until")]+[c["metadata"].get("retention_until") for c in s.get("captures",[])] if x]
    deadlines += [datetime.fromisoformat(c["checked_on"]).replace(tzinfo=timezone.utc)+timedelta(days=scope.MAX_CHECK_AGE_DAYS+1) for c in run.policy.get("terms_checked",[])]
    counts=Counter(x["status"] for x in rows)
    result=dict(schema_version="ux-research-gate.v1",contract_version=CONTRACT,run_id=run.meta["run_id"],bundle_id=bundle["bundle_id"],rules_version=RULES,rules_sha256=digest(rules),brief_sha256=digest(process["brief"]),merge_receipt_sha256=digest(receipt),bundle_input_sha256=full,process_input_sha256=digest(process),valid_until=min(deadlines).isoformat().replace("+00:00","Z") if deadlines else None,result="fail" if issues else "pass",exit_code=1 if issues else 0,claims=sorted(rows,key=lambda x:x["claim_id"]),status_counts={k:counts[k] for k in ("supported_high","supported_medium","single_voice","lead_only","conflicting","needs_product_check","stale","unfit")},issues=issues,warnings=warnings,mode=process["mode"])
    require(result,"ux-research-gate.v1.schema.json")
    projected=projection(bundle,rows)
    if digest(dict(bundle=input_bundle(projected),process=process_inputs(run,query,expansion,projected,history),rules=rules))!=full:raise EngineError("self_invalidating_hash","Gate projection changes its normalized input hash.")
    return result,projected


def fresh(run,store,bundle_path,gate_path):
    if safe_path(gate_path)!= safe_path(run.path/"gate.json"):raise EngineError("gate_path","Consumers require the fixed committed gate.json.")
    if (run.path/"gate_failed.json").exists():raise EngineError("failed_gate","The latest gate attempt failed; consumers require a new pass.")
    gate=store.committed("gate.json");bundle=store.committed("bundle.json")
    if gate["result"]!="pass" or expired_sources(bundle,now_of(run)):raise EngineError("expired","Consumer cannot use expired evidence or a failed gate.")
    # Authored convenience annotations can invalidate a pass, never replace committed outputs.
    live=read_json(bundle_path)
    if input_bundle(live)!=input_bundle(bundle):raise EngineError("stale_gate","Bundle inputs changed after the committed gate.")
    assessed,_=gate_assessment(run,store,bundle)
    if canonical(assessed)!=canonical(gate):raise EngineError("stale_gate","The gate is stale for current bundle, process or rules inputs.")
    if gate["valid_until"] and timestamp(gate["valid_until"])<=now_of(run):raise EngineError("expired","The gate's earliest retention or policy deadline has passed.")
    return bundle,gate


def merge_command(args,run,store):
    digests={}
    def load(path):
        path=safe_path(path)
        raw=read_bytes(path);key=path.relative_to(safe_path(run.path)).as_posix() if path.is_relative_to(safe_path(run.path)) else path.name
        if key in digests and digests[key]!=byte_digest(raw):raise EngineError("input_name","Input artifact names collide.")
        digests[key]=byte_digest(raw)
        from .canonical import loads
        return loads(raw)
    manifest=load(args.manifest)
    ack=load(args.acknowledgements) if args.acknowledgements else dict(schema_version="ux-axis-acknowledgements.v1",run_id=run.meta["run_id"],entries=[])
    imports=load(args.imports) if args.imports else dict(schema_version="ux-sanitized-imports.v1",run_id=run.meta["run_id"],imports=[])
    from .canonical import loads
    raw=read_bytes(args.search_ledger);searches=[loads(x) for x in raw.splitlines() if x.strip()]
    digests["search-ledger.jsonl"]=byte_digest(raw)
    bundle,query,expansion,receipt,result=build(run,store,manifest=manifest,acknowledgements=ack,search_ledger=searches,imports_doc=imports,returns=[load(x) for x in args.returns],input_digests=digests)
    if result["exit_code"]:
        store.failure("merge_result.json",result)
        store.failure("gate_failed.json",dict(result="fail",exit_code=result["exit_code"],issues=result["issues"]))
        return result["exit_code"],["merge_result.json"],result["issues"],result["warnings"]
    expired=expired_sources(bundle,now_of(run))
    if expired:bundle,receipt=purge(bundle,receipt,expired,now_of(run))
    outputs=dict(zip(("bundle.json","query_log.json","expansion_log.json","merge_receipt.json","merge_result.json"),(bundle,query,expansion,receipt,result)))
    if store.has("gate_receipt.json"):
        outputs["gate_receipt.json"]=store.committed("gate_receipt.json")
    store.publish("merge",outputs,digests,keep=False,invalidates_gate=True)
    return 0,list(outputs),[],result["warnings"]


def gate_command(args,run,store):
    bundle=read_json(args.bundle);expired=expired_sources(bundle,now_of(run))
    purged=False
    if expired:
        if not args.write_bundle:raise EngineError("expired","Read-only gate refuses expired input; use --write-bundle to purge it.")
        receipt=store.committed("merge_receipt.json")
        bundle,receipt=purge(bundle,receipt,expired,now_of(run));purged=True
        store.publish("retention_purge",{"bundle.json":bundle,"merge_receipt.json":receipt},invalidates_gate=True)
        # The replacement manifest has already discarded every older snapshot.
        purge_artifacts(run,receipt)
    gate,projected=gate_assessment(run,store,bundle)
    history=store.committed("gate_receipt.json")["counter_history"] if store.has("gate_receipt.json") else []
    updated=copy.deepcopy(history)
    for claim in bundle["records"]["claims"]:
        cs=claim.get("counter_search") or {}
        if claim["counter_evidence_ids"] or cs:
            entry=dict(claim_id=claim["id"],counter_evidence_ids=sorted(claim["counter_evidence_ids"]),call_ids=cs.get("call_ids",[]),outcome=cs.get("outcome"),resolution_id=cs.get("resolution_id"))
            if entry not in updated:updated.append(entry)
    updated=sorted(updated,key=canonical)
    changed=updated!=history
    if changed:
        gate,projected=gate_assessment(run,store,bundle,updated)
    gate_receipt=dict(schema_version="ux-gate-receipt.v1",run_id=run.meta["run_id"],counter_history=updated)
    if gate["exit_code"]:
        if purged:store.publish("gate_failed",{"bundle.json":bundle,"gate_failed.json":gate,"gate_receipt.json":gate_receipt},invalidates_gate=True)
        elif changed:
            # Retain previous content bytes and the authored input mirror, while committing
            # only proven contrary history and a nonconsumable failure result.
            store.publish("gate_failed",{"gate_failed.json":gate,"gate_receipt.json":gate_receipt},invalidates_gate=True,mirror_exclusions={"bundle.json"})
        else:store.failure("gate_failed.json",gate)
        return gate["exit_code"],["gate_failed.json"],gate["issues"],gate["warnings"]
    outputs={"gate.json":gate,"bundle.json":projected if args.write_bundle else bundle,"gate_receipt.json":gate_receipt}
    store.publish("gate",outputs)
    if Path(args.bundle).absolute()!= (run.path/"bundle.json").absolute():
        from .storage import atomic
        atomic(Path(args.bundle),canonical(outputs["bundle.json"]))
    return 0,["gate.json"]+([str(args.bundle)] if args.write_bundle else []),[],gate["warnings"]
