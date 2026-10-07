"""Honest incomplete drafts and exact field provenance for completed audiences."""
from __future__ import annotations

import copy
from collections import defaultdict
from pathlib import Path

from .canonical import EngineError, canonical, digest
from .grading import SUPPORTED
from .merge import privacy_scan, problem
from .schema import Resolver, require


def field_path(join):
    if join["entity_kind"]=="segment":return join["field"]
    collection={"task":"tasks","condition":"conditions","context":"contexts","pain_point":"pain_points"}[join["entity_kind"]]
    return collection+"/"+join["entity_id"]+"/"+join["field"]


def provenance(join,value,bundle_id,basis="research_claim",claims=(),evidence=(),sources=(),observations=(),hashes=None,decision=None,reason="Supported exact claim value."):
    return dict(join=copy.deepcopy(join),value=copy.deepcopy(value),basis=basis,bundle_id=bundle_id,claim_ids=sorted(claims),evidence_ids=sorted(evidence),source_ids=sorted(sources),observation_ids=sorted(observations),input_sha256s=hashes or {},decision_ref=decision,reason=reason)


def make_draft(bundle,gate,brief,audience_id,*,diagnostic=False):
    if gate["mode"]=="fixture" and not diagnostic:raise EngineError("fixture_export","Fixture research cannot be exported as real audience data.")
    source_map={x["id"]:x for x in bundle["records"]["sources"]};claims={x["id"]:x for x in bundle["records"]["claims"]}
    parents=defaultdict(list)
    for row in gate["claims"]:
        claim=claims[row["claim_id"]]
        if row["status"] in SUPPORTED and claim["claim_kind"]=="segment_exists" and any(x["eligible"] for x in row["export_values"]):parents[claim["subject"]["segment_id"]].append(row["claim_id"])
    segments={sid:dict(segment_id=sid,existence_claim_ids=sorted(ids),values={}) for sid,ids in parents.items() if sid is not None}
    values=[];withheld=[];bounds=[];used_sources=set();joined=defaultdict(list)
    for row in gate["claims"]:
        claim=claims[row["claim_id"]]
        for value in row["export_values"]:
            join=value["join"]
            reasons=value["reason_codes"][:]
            if join["segment_id"] not in segments:reasons.append("missing_parent")
            if not value["eligible"] or reasons:
                withheld.append(dict(claim_id=row["claim_id"],join=join,reason_codes=sorted(set(reasons))))
                if "population_bound" in reasons:
                    for eid in value["denominator_evidence_ids"]:
                        ev=next(x for x in bundle["records"]["evidence"] if x["id"]==eid);den=ev.get("denominator")
                        if den and den["interpretation"]=="population_bound":bounds.append(dict(join=join,value=den["value_as_printed"],claim_ids=[row["claim_id"]],evidence_ids=[eid],denominator=den,reason="General population bound, separate from product user share."))
                continue
            joined[canonical(join)].append((row,value))
        if not row["export_values"] and row["status"] not in SUPPORTED:withheld.append(dict(claim_id=row["claim_id"],join=None,reason_codes=[row["status"]]))
    for items in joined.values():
        row,value=items[0];join=value["join"]
        segments[join["segment_id"]]["values"][field_path(join)]=value["value"]
        cids=[r["claim_id"] for r,v in items];eids=set(e for r,v in items for e in v["evidence_ids"]);sids=set(s for r,v in items for s in v["source_ids"]);oids=set(o for r,v in items for o in v["observation_ids"])
        values.append(provenance(join,value["value"],bundle["bundle_id"],claims=cids,evidence=eids,sources=sids,observations=oids,hashes={r["claim_id"]:r["input_sha256"] for r,v in items}))
        used_sources|=sids
    todos=[]
    for sid,seg in segments.items():
        if "share" not in seg["values"]:
            seg["values"]["share"]=dict(value=None,basis="unknown",source_ids=[])
            values.append(provenance(dict(segment_id=sid,entity_kind="segment",entity_id=sid,field="share"),None,bundle["bundle_id"],"unknown",reason="No supported product share."))
        plan=next((x for x in bundle["research"]["manifest"]["segments"] if x["segment_id"]==sid),None)
        if plan:
            seg["values"]["priority"]=plan["priority"]
            values.append(provenance(dict(segment_id=sid,entity_kind="segment",entity_id=sid,field="priority"),plan["priority"],bundle["bundle_id"],"owner_decision",decision=plan["decision_ref"],reason=plan["summary"]))
        for field in ("name_ko","age_bands","devices","priority"):
            if field not in seg["values"]:todos.append(dict(segment_id=sid,join=dict(segment_id=sid,entity_kind="segment",entity_id=sid,field=field),reason="Required audience value is missing.",completion_sources=["new graded evidence"] if field!="priority" else ["owner product decision"]))
        tasks={p.split('/')[1] for p in seg["values"] if p.startswith("tasks/")}
        for task in tasks or {"*"}:
            for field in ("goal_ko","concrete_data","frequency","criticality"):
                if "tasks/"+task+"/"+field not in seg["values"]:todos.append(dict(segment_id=sid,join=dict(segment_id=sid,entity_kind="task",entity_id=task,field=field),reason="Task value is missing.",completion_sources=["completed product observation","approved brief value"] if field=="concrete_data" else ["owner product decision"] if field=="criticality" else ["new graded evidence"]))
    if not segments:todos.append(dict(segment_id=None,join=dict(segment_id=None,entity_kind="audience",entity_id=audience_id,field="method"),reason="No supported segment parent; acquire segment evidence.",completion_sources=["new graded segment_exists evidence"]))
    sources=[]
    for sid in sorted(used_sources):
        src=source_map[sid]
        url=None if src["source_family"]=="voice" or src["platform_family"] in {"blog","microblog","community","commerce_reviews","app_store_reviews","qna","video"} or src["access_basis"] in {"authorised_member","official_api","team_provided"} else src["source_ref"]
        sources.append(dict(source_id=sid,type=src["source_type"],title=src["title"],url=url,accessed_at=src["observed_at"],bundle_ref=sid))
    product={k:v for k,v in brief.get("product",{}).items() if k in {"name","surface","locale","category","url"} and v is not None}
    draft=dict(schema_version="ux-audience-draft.v1",completion="incomplete",audience_id=audience_id,product=product,bundle_id=bundle["bundle_id"],gate_bundle_input_sha256=gate["bundle_input_sha256"],gate_process_input_sha256=gate["process_input_sha256"],sources=sources,segments=[segments[k] for k in sorted(segments)],value_provenance=sorted(values,key=lambda x:canonical(x["join"])),bounds=sorted(bounds,key=canonical),withheld=sorted(withheld,key=canonical),todos=sorted(todos,key=canonical),mode=gate["mode"])
    require(draft,"ux-audience-draft.v1.schema.json")
    if privacy_scan(draft,skip=frozenset({"url"})):raise EngineError("unsafe_value","Audience contains unsafe identifier patterns.",1)
    return draft


def todo_markdown(draft):
    return "# Audience completion\n\n"+"\n".join("- "+x["reason"]+" Target: "+str(x["segment_id"] or "audience")+" / "+x["join"]["entity_kind"]+" / "+x["join"]["entity_id"]+" / "+x["join"]["field"]+". Use: "+", ".join(x["completion_sources"])+"." for x in draft["todos"])+"\n"


def completed_values(doc):
    values=[]
    def add(sid,kind,eid,field,value):values.append((dict(segment_id=sid,entity_kind=kind,entity_id=eid,field=field),value))
    for field in ("method","floors","exclusions"):
        if field in doc:add(None,"audience",doc["audience_id"],field,doc[field])
    for seg in doc["segments"]:
        sid=seg["segment_id"]
        for field in ("name_ko","summary","role","priority","age_bands","devices","grips","familiarity","left_hand_share","orientation"):
            if field in seg:add(sid,"segment",sid,field,seg[field])
        if "share" in seg:add(sid,"segment",sid,"share",seg["share"]["value"])
        for task in seg.get("tasks",[]):
            for field in ("goal_ko","jtbd","success_ko","frequency","criticality","concrete_data"):
                if field in task:add(sid,"task",task["task_id"],field,task[field])
        for condition in seg.get("conditions",[]):
            add(sid,"condition",condition["condition"],"presence",True)
            for field in ("why","cause","stakes","share"):
                if field in condition:add(sid,"condition",condition["condition"],field,condition[field])
        for context in seg.get("contexts",[]):
            for field in ("mobility","lighting","one_handed","interruptions","time_pressure","share"):
                if field in context:add(sid,"context",context["context_id"],field,context[field])
        for pain in seg.get("pain_points",[]):
            if isinstance(pain,dict):add(sid,"pain_point",pain["pain_point_id"],"text",pain["text"])
    return values


def check_audience(doc,bundle,gate,brief,*,draft=False):
    errors=[];warnings=[]
    def error(code,location,reason,join=None):errors.append(dict(join=join,location=location,code=code,reason=reason,next_step="Correct the audience or add evidence and rerun gate."))
    if draft:
        schema_errors=Resolver().validate(doc,"ux-audience-draft.v1.schema.json")
        if schema_errors:error("draft_schema",schema_errors[0],"Draft schema is invalid.")
        else:
            expected=make_draft(bundle,gate,brief,doc["audience_id"],diagnostic=True)
            if canonical(doc)!=canonical(expected):error("draft_values","audience","Draft joins, values, todos or provenance differ from the current gate.")
    else:
        from ergoqa.audience import validate_audience
        for item in validate_audience(doc):error("audience_shape","audience",item)
        if doc.get("schema_version")=="ux-audience-draft.v1":error("draft_incomplete","audience","Incomplete drafts cannot compose personas.")
        if not errors:
            proofs=doc.get("value_provenance")
            if not isinstance(proofs,list):error("value_provenance","audience","Completed research audience needs exact value provenance.")
            else:
                expected=make_draft(bundle,gate,brief,doc["audience_id"],diagnostic=True)
                allowed={canonical(x["join"]):x for x in expected["value_provenance"]}
                actual={}
                for proof in proofs:
                    errs=Resolver().validate(proof,"ux-audience-draft.v1.schema.json","valueProvenance")
                    if errs:error("provenance_shape",errs[0],"Value provenance is invalid.");continue
                    key=canonical(proof["join"])
                    if key in actual:error("duplicate_join","value_provenance","Each material join needs one proof.",proof["join"])
                    actual[key]=proof
                present=completed_values(doc)
                present_keys={canonical(j) for j,v in present}
                if set(actual)-present_keys:error("unused_provenance","value_provenance","Provenance must correspond to present material fields.")
                for join,value in present:
                    key=canonical(join);proof=actual.get(key)
                    if not proof or canonical(proof["value"])!=canonical(value):error("value_mismatch","value_provenance","Material value has missing or mismatched exact provenance.",join);continue
                    if proof["bundle_id"]!=bundle["bundle_id"]:error("bundle_id","value_provenance","Value points to another bundle.",join)
                    if proof["basis"]=="research_claim":
                        if key not in allowed or canonical(proof)!=canonical(allowed[key]):error("claim_value","value_provenance","Value does not match eligible exact contributing claims and closure.",join)
                    elif proof["basis"]=="unknown":
                        if join["field"]!="share" or value is not None or key not in allowed or allowed[key]["basis"]!="unknown":error("unknown_value","value_provenance","Unknown provenance is allowed only for unknown shares.",join)
                    else:
                        choice=join["entity_kind"]=="audience" and join["field"] in {"method","floors","exclusions"} or join["entity_kind"]=="task" and join["field"] in {"criticality","concrete_data"}
                        if join["field"]=="priority":
                            if key not in allowed or canonical(proof)!=canonical(allowed[key]):error("owner_priority","value_provenance","Priority must match the manifest owner decision.",join)
                        elif not choice:error("owner_empirical","value_provenance","Owner decisions cannot provide empirical shares, weights, presence or frequency.",join)
                rows={x["claim_id"]:x for x in gate["claims"]};segments={x["segment_id"]:x for x in expected["segments"]};source_map={x["id"]:x for x in bundle["records"]["sources"]};ev_map={x["id"]:x for x in bundle["records"]["evidence"]}
                for src in doc["sources"]:
                    source=source_map.get(src["source_id"])
                    if not source or src.get("bundle_ref")!=src["source_id"] or src["type"]!=source["source_type"]:error("source_receipt","sources","Audience source IDs, types and string bundle_ref must match the receipt.")
                for segment in doc["segments"]:
                    sid=segment["segment_id"]
                    if sid not in segments:error("segment_parent","segments","Segment lacks supported segment_exists parent.");continue
                    confidence=min((rows[x]["confidence"] for x in segments[sid]["existence_claim_ids"]),key=lambda x:{"medium":0,"high":1}[x])
                    if segment["confidence"]!=confidence:error("confidence","segments","Segment confidence must equal its contributing existence gate confidence.")
                    share=next((x for x in expected["value_provenance"] if x["join"]==dict(segment_id=sid,entity_kind="segment",entity_id=sid,field="share")),None)
                    share_basis="unknown" if not share or share["basis"]=="unknown" else "measured" if all(rows[x]["share_basis"]=="measured" for x in share["claim_ids"]) else "estimated"
                    if segment["share"]["basis"]!=share_basis or sorted(segment["share"].get("source_ids",[]))!=(share["source_ids"] if share else []):error("share_basis","segments","Share basis and sources must match exact contributing value proofs.")
                    for ev in segment["evidence"]:
                        candidates=[(row,value) for row in gate["claims"] for value in row["export_values"] if value["eligible"] and value["join"]["segment_id"]==sid and ev["source_id"] in value["source_ids"]]
                        matching=[]
                        for row,value in candidates:
                            for ek in value["evidence_kinds"]:
                                e=ev_map[ek["evidence_id"]]
                                if e["source_id"]==ev["source_id"] and ev["kind"]==ek["kind"] and ev["claim"]==next(c["statement"] for c in bundle["records"]["claims"] if c["id"]==row["claim_id"]) and ev.get("quote")==e.get("excerpt") and ev.get("quote_basis")==("document" if source_map[ev["source_id"]]["access_basis"]=="team_provided" else "page"):matching.append(e)
                        if not matching:error("evidence_receipt","segments.evidence","Evidence statement, kind, quote and basis must match contributing claim/capture.")
    if privacy_scan(doc,skip=frozenset({"url"})):error("unsafe_value","audience","Audience contains identifier patterns.")
    return dict(schema_version="ux-audience-check.v1",mode="draft" if draft else "completed",result="fail" if errors else "pass",exit_code=1 if errors else 0,audience_id=doc.get("audience_id"),bundle_id=bundle["bundle_id"],checked_values=len(doc.get("value_provenance",[])),warnings=warnings,errors=errors)
