"""Allowlist loop projection with content-bound reviewer attestations."""
from __future__ import annotations

import copy
import re
from urllib.parse import urlsplit,urlunsplit

from scripts.validate_bundle import validate_bundle
from . import privacy,scope
from .canonical import EngineError,canonical,digest,quote_text
from .merge import privacy_scan,problem

VERSION="minimize-2026-10-01.2"
ALLOW={
"sources":"id channel source_ref access_basis access_method public_scope retention_status source_type source_family platform_family org retention_until privacy_class summary research_tombstone",
"evidence":"id source_id evidence_type epistemic_status summary denominator scope",
"claims":"id claim_kind statement epistemic_status verification_status evidence_ids context_evidence_ids counter_evidence_ids observation_ids persona_ids subject scope stakes about_current_version scenario_priorities support_basis",
"personas":"id basis adapter_revision schema_fingerprint seed shard_or_config max_scanned_rows max_bytes_read timeout_ms selected_record_ids filled_strata unfilled_strata stop_reason original_attributes scenario_assumptions audience_ref",
"scenarios":"id persona_id task task_id segment_id context_id priority motivation_claim_ids audience_ref scope",
"runs":"id scenario_id status surface_ref epistemic_status started_at ended_at version observed_at scope artifact_refs artifact_sha256s",
"observations":"id run_id epistemic_status result scope observed_at version artifact_refs artifact_sha256s",
"findings":"id scenario_id observation_ids claim_ids figma_id verification_status epistemic_status severity segments_affected title summary actual expected",
"proposals":"id finding_ids figma_id proposal_type expected_behavior_change summary status",
"figma":"id file_key branch_key baseline_version readback_version node_ids read_at readback_artifact_ref design_status defect_class",
}
RAW={"excerpt","raw","raw_html","raw_content","body","quote","text","page_text","html","content","capture","payload","page_body"}
LOCATORS={"author_key","thread_key","item_key","aliases","profile","profile_url","comment_id","post_id","video_id","api_id"}
AUTHORED={"summary","statement","result","actual","expected","task","title"}


def _bound_import_ref(record,run_id):
    """Recognize only the source locator generated from this run's import proof."""
    provenance=record.get("provenance") or {}
    import_id=provenance.get("import_id")
    if provenance.get("kind")!="import" or not isinstance(run_id,str) or not isinstance(import_id,str):
        return None
    if not re.fullmatch(r"run-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{6}",run_id) or not re.fullmatch(r"IMP-[0-9a-f]{64}",import_id):
        return None
    expected="team-import://"+run_id+"/"+import_id
    return expected if record.get("source_ref")==expected else None


def minimize(bundle,gate):
    dropped=[];issues=[];summaries=0;urls=0
    import_refs={record["id"]:_bound_import_ref(record,bundle["research"]["run_id"]) for record in bundle["records"]["sources"]}
    attestations={}
    for x in bundle["research"].get("summary_attestations",[]):
        key=x["record_id"],x["field"]
        if key in attestations and attestations[key]!=x:issues.append(problem("summary_attestation","research","Summary attestations disagree."))
        attestations[key]=x
    quotations=[quote_text(e["excerpt"]) for e in bundle["records"]["evidence"] if e.get("excerpt")]
    def drop(rid,path,category):dropped.append(dict(record_id=rid,path=path,category=category))
    def scrub(value,rid,path):
        if isinstance(value,dict):
            out={}
            for k,v in value.items():
                if k.casefold() in RAW:drop(rid,path+"/"+k,"raw_content")
                elif k.casefold() in LOCATORS:drop(rid,path+"/"+k,"personal_locator")
                else:out[k]=scrub(v,rid,path+"/"+k)
            return out
        if isinstance(value,list):return [scrub(v,rid,path+"/"+str(i)) for i,v in enumerate(value)]
        if isinstance(value,str):
            # Digest digit runs can look like phones/cards inside a locator. Authored text
            # and every unbound or extended locator still get the normal identifier scan.
            internal_ref=path=="/records/sources/source_ref" and value==import_refs.get(rid)
            if not internal_ref and (privacy_scan(value) or privacy.profile_href(value)):issues.append(problem("projection_identifiers",rid,"Projected content contains identifier patterns or personal locators."))
            if any(q and q in quote_text(value) for q in quotations):issues.append(problem("retained_quotation",rid,"Authored projection still contains a retained quotation."))
        return value
    out={k:copy.deepcopy(bundle[k]) for k in ("schema_version","bundle_id","permissions")};out["records"]={}
    for key in set(bundle)-set(out)-{"records"}:drop(None,"/"+key,"research_proof" if key=="research" else "unknown_field")
    for group,records in bundle["records"].items():
        result=[]
        for record in records:
            rid=record["id"]
            projected={}
            for k,v in record.items():
                if k not in ALLOW[group].split():
                    drop(rid,"/records/"+group+"/"+k,"raw_content" if k.casefold() in RAW else "personal_locator" if k in LOCATORS else "research_proof" if k in {"access","captures","flags","provenance","research_support_evidence_ids","research_context_evidence_ids","research_epistemic_status"} else "unknown_field")
                    continue
                purged_generic = group=="evidence" and record.get("epistemic_status")=="unknown" and record.get("summary")=="Evidence removed at retention expiry." or group=="claims" and record.get("statement")=="Evidence unavailable; claim requires new evidence." and any(rid in gap.get("affected_claim_ids",[]) for gap in bundle["research"]["gaps"])
                if k in AUTHORED and not record.get("research_tombstone") and not purged_generic:
                    att=attestations.get((rid,k))
                    if not att or att["content_sha256"]!=digest(v):issues.append(problem("summary_attestation",rid,"Authored summaries, statements and results need an attestation bound to their exact content."))
                    if k=="summary":summaries+=1
                projected[k]=copy.deepcopy(v)
            if group=="sources" and not record.get("research_tombstone"):
                if not record.get("summary"):issues.append(problem("missing_summary",rid,"Source needs a separately authored safe summary."))
                ref=projected["source_ref"]
                if ref.startswith(("http://","https://")):
                    parts=urlsplit(ref);host=parts.hostname or ""
                    if privacy.profile_href(privacy.origin_only(ref)):host=scope.site_of(host)
                    projected["source_ref"]=urlunsplit((parts.scheme,host+(":"+str(parts.port) if parts.port else ""),"","",""));urls+=1
            if group=="evidence" and not record.get("summary"):issues.append(problem("missing_summary",rid,"Evidence needs a separately authored safe summary."))
            if group=="claims" and projected.get("verification_status")=="verified" and projected.get("claim_kind") in {"prevalence","user_preference","real_user_preference","discomfort"}:
                evidence={e["id"]:e for e in bundle["records"]["evidence"]}
                if any(evidence[e]["evidence_type"]!="quantitative" or (evidence[e].get("denominator") or {}).get("interpretation")!="product_measure" for e in projected["evidence_ids"]):
                    projected.update(verification_status="unverified",epistemic_status="unknown");drop(rid,"/records/claims/verification_status","population_bound_not_loop_measure")
                else:projected["support_basis"]="measured_sample"
            projected=scrub(projected,rid,"/records/"+group)
            result.append(projected)
        out["records"][group]=sorted(result,key=lambda x:x["id"])
    out["minimized_from"]=dict(bundle_id=bundle["bundle_id"],bundle_input_sha256=gate["bundle_input_sha256"],gate_input_sha256=digest(gate),rules_version=gate["rules_version"],sanitizer_version=VERSION,mode=gate["mode"])
    for error in validate_bundle(out):issues.append(problem("projection_contract","bundle.min", "Projection does not satisfy the bundle graph contract.", "Correct authored inputs before minimizing."))
    manifest=dict(schema_version="ux-research-minimize.v1",result="fail" if issues else "pass",exit_code=1 if issues else 0,bundle_id=bundle["bundle_id"],bundle_input_sha256=gate["bundle_input_sha256"],gate_input_sha256=digest(gate),sanitizer_version=VERSION,output_file="bundle.min.json",dropped=sorted(dropped,key=canonical),summaries_kept=summaries,urls_reduced=urls,retained_hypothesis_ids=sorted(c["id"] for c in out["records"]["claims"] if c["verification_status"]!="verified"),warnings=[],issues=[__import__('json').loads(x) for x in sorted(set(canonical(x) for x in issues))])
    return out,manifest
