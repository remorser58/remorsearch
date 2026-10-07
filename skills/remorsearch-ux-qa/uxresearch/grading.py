"""Total source grading, independent units, counter decisions and exact values."""
from __future__ import annotations

import copy
import re
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from pathlib import Path
from urllib.parse import urlsplit

from scripts.validate_bundle import eligible_observations
from .canonical import EngineError, canonical, digest, input_bundle, loads, quote_text, timestamp
from .flags import HITS, combine
from .merge import problem

DATA = Path(__file__).resolve().parent / "data"
RULES = loads((DATA / "grading-rules.json").read_bytes())
GRADES = "ABCDE"
SUPPORTED = {"supported_high", "supported_medium"}
NUMERIC_KINDS = {"segment_share", "device_mix", "condition_share", "prevalence", "user_preference", "real_user_preference", "discomfort"}
WEIGHT_FIELDS = {"share", "age_bands", "devices", "grips", "familiarity", "left_hand_share"}
VALUE_KINDS = {("segment",k): {"segment_exists"} for k in ("name_ko","summary","role")}
VALUE_KINDS.update({("segment",k): {"segment_share"} for k in WEIGHT_FIELDS-{"devices"}})
VALUE_KINDS.update({("segment","devices"):{"device_mix"},("segment","orientation"):{"context_of_use"},
                    **{("task",k):{"task"} for k in ("goal_ko","jtbd","success_ko","frequency")},
                    ("task","concrete_data"):{"product_behavior","intended_behavior"},("task","criticality"):{"intended_behavior"},
                    **{("condition",k):{"condition_presence"} for k in ("presence","why","cause","stakes")},
                    ("condition","share"):{"condition_share"},("context","share"):{"segment_share"},
                    **{("context",k):{"context_of_use"} for k in ("mobility","lighting","one_handed","interruptions","time_pressure")},
                    ("pain_point","text"):{"pain_point","workaround"}})


def family(source):
    typ = source.get("source_type")
    expected = RULES["survey_vendor_family"] if typ == "survey" and source.get("producer_stake") == "vendor" else RULES["source_families"].get(typ)
    if expected is None or source.get("source_family") != expected:
        raise EngineError("source_family", "Source type and family do not match the pinned mapping.")
    return expected


def capture_source(source, evidence):
    for cap in source.get("captures", []):
        if cap["capture_ref"] == evidence.get("capture_ref"):
            return {**source, **cap["metadata"]}
    return source


def target_hash(decision, bundle, receipt):
    maps={k:{x["id"]:x for x in bundle["records"][k]} for k in ("sources","evidence","claims")}
    kind=decision["target_kind"]; identifier=decision["target_id"]
    target=maps[{"source":"sources","evidence":"evidence","claim":"claims"}[kind]].get(identifier)
    if target is None:
        raise EngineError("decision_target", "Verifier decision references an unknown target.")
    if kind=="claim":
        return digest(input_bundle({"records":{"claims":[target]}})["records"]["claims"][0])
    source=target if kind=="source" else maps["sources"][target["source_id"]]
    cap=next((x for x in source.get("captures",[]) if x["capture_ref"]==decision["capture_ref"]),None)
    if cap is None or (kind=="evidence" and target.get("capture_ref")!=decision["capture_ref"]):
        raise EngineError("decision_capture","Verifier decision does not name the target's exact capture.")
    proof=next((x for x in receipt["source_proofs"] if x["source_id"]==source["id"]),None)
    if not proof:
        raise EngineError("decision_target","Verifier target has no authoritative source proof.")
    return digest({"identity":proof["full_id_sha256"],"capture":cap,"evidence":target if kind=="evidence" else None})


class Decisions:
    def __init__(self,bundle,receipt,issues):
        self.items=[]; self.issues=issues
        maps={k:{x["id"]:x for x in bundle["records"][k]} for k in ("sources","evidence","claims")}
        seen=set()
        for decision in bundle["research"].get("verifier_decisions",[]):
            if decision["id"] in seen:
                raise EngineError("decision_id","Verifier decision IDs must be unique.")
            seen.add(decision["id"])
            if target_hash(decision,bundle,receipt)!=decision["target_sha256"]:
                raise EngineError("decision_hash","Verifier decision is stale for its target content.")
            target=maps[{"source":"sources","evidence":"evidence","claim":"claims"}[decision["target_kind"]]][decision["target_id"]]
            flag_ids={x["id"] for key in HITS for x in (capture_source(target,{"capture_ref":decision["capture_ref"]}) if decision["target_kind"]=="source" else target).get("flags",{}).get(key,[])}
            if set(decision["flag_ids"])-flag_ids:
                raise EngineError("decision_flag","Verifier decision names flags absent from its immutable target.")
            if decision["kind"]=="incentive" and decision["outcome"] in {"confirmed","not_confirmed"} and not decision["basis_evidence_ids"]:
                issues.append(problem("incentive_trace","verifier_decisions","An incentive decision needs an excerpt-specific event trace."))
            for old in self.items:
                if all(old[k]==decision[k] for k in ("kind","target_kind","target_id","capture_ref")) and (not old["flag_ids"] or not decision["flag_ids"] or set(old["flag_ids"])&set(decision["flag_ids"])) and old["outcome"]!=decision["outcome"]:
                    issues.append(problem("decision_conflict","verifier_decisions","Overlapping verifier decisions disagree."))
            self.items.append(decision)

    def outcomes(self,kind,source,evidence,claim=None):
        return [x for x in self.items if x["kind"]==kind and x["capture_ref"]==evidence.get("capture_ref") and ((x["target_kind"]=="source" and x["target_id"]==source["id"]) or (x["target_kind"]=="evidence" and x["target_id"]==evidence["id"])) and (kind!="polarity" or x.get("basis_claim_id")==claim["id"])]

    def source_cleared(self,source,evidence):
        flags=source.get("flags",{}).get("injection_flags",[])
        cleared={fid for x in self.items if x["kind"]=="injection" and x["target_kind"]=="source" and x["target_id"]==source["id"] and x["capture_ref"]==evidence.get("capture_ref") and x["outcome"]=="cleared" for fid in x["flag_ids"]}
        return all(x["id"] in cleared for x in flags)


def organization(value):
    if not value:
        return None
    value=quote_text(value).casefold().rstrip(".")
    aliases=loads((DATA/"organization-aliases.json").read_bytes())["aliases"]
    value=aliases.get(value,value)
    if re.fullmatch(r"(?:[a-z0-9-]+\.)+[a-z]{2,}",value):
        from .scope import registrable_domain
        value=registrable_domain(value)
    return aliases.get(value,value)


def identity(source):
    fam=source.get("source_family")
    if fam=="voice":
        if source.get("identity_status")=="attested" and source.get("author_key"):
            return "person:"+source["author_key"],"person",None
        if source.get("thread_key"):
            return "thread:"+source["thread_key"],"thread",None
        if source.get("identity_status")=="unknown" and source.get("provenance") and source.get("source_ref"):
            return "page:"+source["id"],"thread",None
        return None,None,None
    org=organization(source.get("org"))
    return ("org:"+org,"organisation",org) if org else (None,None,None)


def is_current(source,evidence,brief):
    release=brief.get("product",{}).get("release_date")
    version=brief.get("product",{}).get("current_version")
    evversion=evidence.get("scope",{}).get("version") or source.get("version")
    if evversion and evversion.casefold() in {"latest","current","new","now"}:
        return False
    if version and evversion:
        return evversion==version
    effective=source.get("valid_at") or (evidence.get("denominator") or {}).get("period_end") or source.get("published_at")
    return bool(release and effective and effective>=release)


def denominator_ok(evidence,source,now):
    den=evidence.get("denominator")
    if evidence.get("evidence_type") not in {"quantitative","statistic"} or not isinstance(den,dict):
        raise EngineError("denominator","Numeric support needs quantitative/statistic evidence and a neutral denominator.")
    fields=("population","period_start","period_end","product_relation","sampling_frame","method","unit","value_as_printed","interpretation")
    if any(not isinstance(den.get(k),str) or not den[k].strip() for k in fields) or not (den.get("n") is None or type(den.get("n")) is int and den["n"]>0):
        raise EngineError("denominator","Numeric denominator has incomplete fields or sample size.")
    try:
        start,end=date.fromisoformat(den["period_start"]),date.fromisoformat(den["period_end"])
    except ValueError as exc:
        raise EngineError("denominator_period","Numeric reference period is invalid.") from exc
    if start>end or end>now.date():
        raise EngineError("denominator_period","Numeric reference period is invalid or future.")
    frame=den["sampling_frame"].casefold()
    if any(x in frame for x in ("self-selected","self selected","review count","post count","star average","complaint count","likes")) or source.get("flags",{}).get("count_only"):
        raise EngineError("denominator_frame","Self-selected post/review counts are not a neutral sampling frame.")
    if den["n"] is None and not any(x in (frame+" "+den["method"].casefold()) for x in ("census","defined population")):
        raise EngineError("denominator_frame","A null sample size requires a defined census population.")
    scope=evidence.get("scope",{})
    if any(scope.get(k)!=den[k] for k in ("population","period_start","period_end","product_relation")):
        raise EngineError("denominator_scope","Denominator does not match captured evidence scope.")
    if den["product_relation"]=="general_population" and den["interpretation"]!="population_bound":
        raise EngineError("population_bound","General population statistics must remain a separate bound.")
    if den["interpretation"]=="product_measure" and den["product_relation"]!="product_users":
        raise EngineError("product_measure","Only target product users can supply a product measure.")
    if source.get("source_family")=="statistical":
        card=source.get("stat_card")
        if not card or organization(card.get("publisher"))!=organization(source.get("org")) or card.get("frame")!=den["sampling_frame"] or card.get("unit")!=den["unit"] or card.get("value_as_printed")!=den["value_as_printed"] or card.get("n")!=den["n"]:
            raise EngineError("stat_card","Statistical denominator does not match its publisher card.")
        if den["period_start"] not in card["reference_period"] or den["period_end"] not in card["reference_period"]:
            raise EngineError("stat_card_period","Statistical reference period does not match its card.")
    return den


def grade(evidence,source,claim,brief,decisions,issues,*,external=False,counter=False):
    fam=family(source); kind=claim["claim_kind"]
    if kind not in RULES["fit"]:
        raise EngineError("claim_kind","Unknown claim kind.")
    fit="E" if fam=="none" else RULES["fit"][kind][fam]
    level=GRADES.index(fit); reasons=[]
    flags=combine(source.get("flags"),evidence.get("flags"))
    for test,reason in ((not source.get("published_at"),"missing_publication_date"),(flags["secondhand"],"secondhand"),(flags["unclear_context"],"unclear_context"),(source.get("access_basis")=="authorised_member","member_access")):
        if test:level=min(4,level+1);reasons.append(reason)
    def cap(grade_,reason):
        nonlocal level
        level=max(level,GRADES.index(grade_));reasons.append(reason)
    if flags["lead_kind"]!="full_text":cap("D","lead_only_capture")
    if flags["community_modelled_demographics"]:cap("D","modelled_demographics")
    if source.get("retention_status") in {"withdrawn","deleted","redacted"} or (source.get("access") or {}).get("stop_class") not in {None,"none"} or fam=="none":cap("E","ineligible_source")
    unit,unit_kind,org=identity(source)
    if not unit:cap("D","unknown_identity")
    if not source.get("platform_family"):cap("D","unknown_channel")
    for kind_,key in (("promotion","promotion_hits"),("incentive","incentive_hits"),("virtual_person","virtual_person_hits")):
        applicable=decisions.outcomes(kind_,source,evidence,claim)
        reviewed={fid for x in applicable if x["outcome"]!="unresolved" for fid in x["flag_ids"]}
        candidates={x["id"] for x in flags[key]}
        if candidates-reviewed:
            issues.append(problem("verifier_required",claim["id"],"Support flag candidates need content-bound verifier review."))
        confirmed=any(x["outcome"]=="confirmed" for x in applicable)
        if confirmed and kind_=="promotion":cap("D","promotion")
        if confirmed and kind_=="virtual_person":cap("E","virtual_person")
        if confirmed and kind_=="incentive":
            if counter or kind in {"user_preference","real_user_preference","discomfort","prevalence"}:cap("D","incentive")
            elif kind in {"pain_point","workaround"}:cap("C","incentive")
    if flags["own_brand"] and not external:cap("D","own_brand")
    if source.get("flags",{}).get("injection_flags") and not decisions.source_cleared(source,evidence):cap("E","source_injection")
    ev_injection={x["id"] for x in evidence.get("flags",{}).get("injection_flags",[])}- {x["id"] for x in source.get("flags",{}).get("injection_flags",[])}
    ev_clear={fid for x in decisions.outcomes("injection",source,evidence,claim) if x["target_kind"]=="evidence" and x["outcome"]=="cleared" for fid in x["flag_ids"]}
    if ev_injection-ev_clear:cap("E","excerpt_injection")
    polarity=[x["outcome"] for x in decisions.outcomes("polarity",source,evidence,claim)]
    uncertain="uncertain" in polarity or flags["polarity_uncertain"] and not any(x in {"supportive","contrary","neutral"} for x in polarity)
    eligible=evidence.get("epistemic_status")=="observed" and level<=2 and bool(unit)
    if uncertain and (counter or kind in {"user_preference","real_user_preference"}):eligible=False;reasons.append("polarity_uncertain")
    if "contrary" in polarity and not counter:eligible=False;reasons.append("contrary_polarity")
    if claim.get("about_current_version") and not is_current(source,evidence,brief):eligible=False;reasons.append("not_current")
    if evidence.get("epistemic_status")!="observed":reasons.append("not_observed")
    if flags["count_only"] and kind in NUMERIC_KINDS:cap("E","count_only");eligible=False
    return dict(evidence_id=evidence["id"],capture_ref=evidence.get("capture_ref"),fit_grade=fit,final_grade=GRADES[level],eligible=eligible,unit_id=unit,reasons=sorted(set(reasons)))


class Components:
    def __init__(self,bundle):
        self.parent={};self.units={}; maps={x["id"]:x for x in bundle["records"]["sources"]}
        identity_members={};copies={}
        for ev in bundle["records"]["evidence"]:
            eid=ev["id"];self.parent[eid]=eid
            src=capture_source(maps[ev["source_id"]],ev)
            key,kind,org=identity(src);self.units[eid]=(key,kind,org)
            for mapping,k in ((identity_members,key),(copies,ev.get("copypaste_group"))):
                if k:
                    if k in mapping:self.union(eid,mapping[k])
                    else:mapping[k]=eid
    def find(self,x):
        while self.parent[x]!=x:
            self.parent[x]=self.parent[self.parent[x]];x=self.parent[x]
        return x
    def union(self,a,b):
        a,b=self.find(a),self.find(b)
        self.parent[max(a,b)]=min(a,b)


def units_for(grades,maps,components):
    grouped=defaultdict(list)
    for g in grades:
        if g["eligible"]:grouped[components.find(g["evidence_id"])].append(g)
    units=[]
    for key,items in sorted(grouped.items()):
        best=min(items,key=lambda x:(GRADES.index(x["final_grade"]),capture_source(maps["sources"][maps["evidence"][x["evidence_id"]]["source_id"]],maps["evidence"][x["evidence_id"]]).get("observed_at",""),x["evidence_id"]))
        ev=maps["evidence"][best["evidence_id"]];src=capture_source(maps["sources"][ev["source_id"]],ev)
        identity_,kind,org=components.units[ev["id"]]
        members=sorted(x for x in components.parent if components.find(x)==key)
        units.append(dict(unit_id="unit-"+digest(members)[:16],kind="copypaste" if len({components.units[x][0] for x in members})>1 else kind,
                          members=members,representative_evidence_id=ev["id"],grade=best["final_grade"],channel_family=src.get("platform_family"),org=org))
    return units


def support_status(units,maps):
    a=[u for u in units if u["grade"]=="A"];b=[u for u in units if u["grade"]=="B"];c=[u for u in units if u["grade"]=="C"]
    def src(u):return maps["sources"][maps["evidence"][u["representative_evidence_id"]]["source_id"]]
    if a:return "supported_high"
    if len(b)>=2 and (len({u["channel_family"] for u in b})>=2 or any(src(u)["source_family"] in {"measured","statistical"} for u in b)):return "supported_high"
    if len([u for u in b if src(u)["source_family"]=="voice"])>=2:return "supported_medium"
    if any(x["channel_family"]!=y["channel_family"] for x in b for y in c):return "supported_medium"
    if any(src(u)["source_family"]=="statistical" and u["org"] for u in b):return "supported_medium"
    if any(src(u)["source_family"]=="voice" for u in b):return "single_voice"
    return "lead_only"


def validate_caps(bundle,issues):
    sources={x["id"]:x for x in bundle["records"]["sources"]}; groups=defaultdict(lambda:{"sources":set(),"quotes":set()})
    per_resource=defaultdict(set)
    for ev in bundle["records"]["evidence"]:
        src=capture_source(sources[ev["source_id"]],ev);key,kind,_=identity(src)
        per_resource[src["id"]].add(ev.get("copypaste_group",digest(ev.get("summary"))))
        if key and kind in {"person","thread"}:
            groups[key]["sources"].add(src["id"]);groups[key]["quotes"].add((src["id"],ev.get("copypaste_group",digest(ev.get("summary")))))
    if any(len(x["sources"])>3 or len(x["quotes"])>5 for x in groups.values()):issues.append(problem("identity_cap","evidence","An author/thread exceeds three sources or five excerpts."))
    if any(len(x)>5 for x in per_resource.values()):issues.append(problem("resource_excerpt_cap","evidence","A resource exceeds five distinct excerpts."))


def scope_disjoint(a,b):
    if not isinstance(a,dict) or not isinstance(b,dict):return False
    if a.get("version") and b.get("version") and a["version"]!=b["version"] and all(x.casefold() not in {"current","latest","now"} for x in (a["version"],b["version"])):return True
    return bool(a.get("period_start") and a.get("period_end") and b.get("period_start") and b.get("period_end") and (a["period_end"]<b["period_start"] or b["period_end"]<a["period_start"]))


def resolution_valid(resolution,claim,maps,decisions):
    if resolution["claim_id"]!=claim["id"]:return False
    counters=set(resolution["counter_evidence_ids"])
    if not counters or not counters<=set(claim["counter_evidence_ids"]):return False
    if resolution["kind"]=="polarity_correction":
        return all(any(d["kind"]=="polarity" and d["target_id"]==eid and d.get("basis_claim_id")==claim["id"] and d["outcome"] in {"supportive","neutral"} and d["id"] in resolution["verifier_decision_ids"] for d in decisions.items) for eid in counters)
    prior=maps["claims"][resolution["prior_claim_id"]]
    old,new=prior["scope"],claim["scope"]
    changed={k for k in old if old[k]!=new[k]}
    if claim["id"]==prior["id"] or not changed or changed-{"version","period_start","period_end"} or resolution["restriction"]!=new:return False
    if not any(d["kind"]=="scope" and d["target_id"]==claim["id"] and d["resolution_id"]==resolution["id"] and d["outcome"]=="accepted" and d["id"] in resolution["verifier_decision_ids"] for d in decisions.items):return False
    return all(scope_disjoint(new,maps["evidence"][eid].get("scope")) for eid in counters)


def counters(claim,bundle,maps,query,decisions,issues):
    primary={x["segment_id"] for x in bundle["research"]["manifest"]["segments"] if x["priority"]=="primary"}
    use={s.get("priority") for s in bundle["records"]["scenarios"] if claim["id"] in s.get("motivation_claim_ids",[])}
    if use and not use<=set(claim.get("scenario_priorities",[])):
        issues.append(problem("scenario_priorities",claim["id"],"Scenario uses disagree with declared claim priorities."))
    required=claim["subject"].get("segment_id") in primary or claim.get("stakes")=="high" or bool({"P0","P1"}&(use|set(claim.get("scenario_priorities",[])))) or any(x["value"] is not None and x["join"]["field"] in WEIGHT_FIELDS for x in claim.get("audience_values",[]))
    cs=claim.get("counter_search"); linked=set(claim.get("counter_evidence_ids",[])); resolved=set()
    resolutions={x["id"]:x for x in bundle["research"].get("scope_resolutions",[])}
    if cs:
        calls={x["call_id"]:x for x in query["receipts"]}
        if any(x not in calls for x in cs["call_ids"]):raise EngineError("counter_call","Counter search references an unknown actual call.")
        if any(calls[x]["outcome"]!="completed" or calls[x]["phase"]!="counter_search" for x in cs["call_ids"]) or not cs["call_ids"]:
            issues.append(problem("counter_incomplete",claim["id"],"Counter search needs completed counter-search invocation receipts."))
        if set(cs["counter_evidence_ids"])-linked:raise EngineError("counter_links","Counter search evidence must remain linked as contrary evidence.")
        if cs["outcome"]=="contradicts" and not cs["counter_evidence_ids"]:raise EngineError("counter_result","Contradicts requires captured counter evidence.")
        if cs["outcome"]=="none_found" and linked:raise EngineError("counter_result","A none-found search cannot hide linked contrary evidence.")
        if cs["outcome"]=="qualifies":
            res=resolutions.get(cs["resolution_id"])
            if not res or not resolution_valid(res,claim,maps,decisions):issues.append(problem("counter_resolution",claim["id"],"Qualifying counter search needs a valid typed content-bound resolution."))
            else:resolved=set(res["counter_evidence_ids"])
        for eid in cs["counter_evidence_ids"]:
            ev=maps["evidence"][eid];src=capture_source(maps["sources"][ev["source_id"]],ev)
            flags=combine(src.get("flags"),ev.get("flags"))
            decisions_=decisions.outcomes("incentive",src,ev,claim)
            if flags["seller_managed"] or flags["polarity_uncertain"] or any(x["outcome"]=="confirmed" for x in decisions_):
                issues.append(problem("counter_biased",claim["id"],"Biased or uncertain material cannot qualify a counter-search outcome."))
    elif required:issues.append(problem("counter_required",claim["id"],"Primary, high-stakes, numeric or priority use requires a completed counter-search."))
    sticky=any(claim["id"] in gap.get("affected_claim_ids",[]) and gap.get("counter_gap") for gap in bundle["research"]["gaps"])
    if sticky and cs and cs.get("replaces_call_ids"):
        matching=[g for g in bundle["research"]["gaps"] if claim["id"] in g.get("affected_claim_ids",[]) and g.get("counter_gap")]
        if all(set(cs["replaces_call_ids"])==set(g.get("prior_call_ids",[])) and cs["call_ids"] and all(timestamp(next(x for x in query["receipts"] if x["call_id"]==cid)["called_at"])>timestamp(g["removed_at"]) for cid in cs["call_ids"]) for g in matching):sticky=False
    if sticky:
        issues.append(problem("counter_gap",claim["id"],"Expired contrary evidence requires a new completed replacement counter-search."))
    return required, bool(linked-resolved) or bool(cs and cs["outcome"]=="contradicts") or sticky


def scope_cycles(bundle):
    edges={}
    for res in bundle["research"].get("scope_resolutions",[]):
        if res["kind"]=="scope_change":
            if res["claim_id"] in edges and edges[res["claim_id"]]!=res["prior_claim_id"]:raise EngineError("scope_predecessor","Scope changes have conflicting predecessors.")
            edges[res["claim_id"]]=res["prior_claim_id"]
    for start in edges:
        seen=set();node=start
        while node in edges:
            if node in seen:raise EngineError("scope_cycle","Scope-change predecessor links contain a cycle.")
            seen.add(node);node=edges[node]


def numeric_components(value,pointer=""):
    if type(value) in (int,float):return {pointer:value}
    if isinstance(value,dict):
        out={}
        for k,v in value.items():out.update(numeric_components(v,pointer+"/"+k.replace("~","~0").replace("/","~1")))
        return out
    return {}


def value_valid(value,claim,row,maps,brief,now):
    join=value["join"];field=join["field"];kind=join["entity_kind"]
    if claim["claim_kind"] not in VALUE_KINDS.get((kind,field),set()) or join["segment_id"]!=claim["subject"]["segment_id"] or (kind=="segment" and join["entity_id"]!=join["segment_id"]):raise EngineError("value_join","Audience field does not match claim kind and subject.")
    target={"task":"task_id","condition":"condition_id","context":"context_id","pain_point":"pain_point_id"}.get(kind)
    if target and join["entity_id"]!=claim["subject"].get(target):raise EngineError("value_join","Audience entity does not match the claim's exact subject.")
    if field=="devices":
        from ergoqa.devices import get_device
        if not isinstance(value["value"],dict):raise EngineError("device_value","Device mix must be a catalog-ID weight map.")
        for identifier in value["value"]:
            try:get_device(identifier)
            except (ValueError,KeyError):raise EngineError("device_value","Device value does not identify a catalog device.") from None
    if field in WEIGHT_FIELDS:
        components=numeric_components(value["value"])
        if not components or any(not 0<=n<=1 for n in components.values()):raise EngineError("value_fraction","Shares and weights must be fractions.")
        if isinstance(value["value"],dict) and abs(sum(components.values())-1)>1e-9:raise EngineError("value_weights","Weight maps must sum to one without normalization.")
        checks={x["pointer"]:x for x in value["value_checks"]}
        if len(checks)!=len(value["value_checks"]) or set(checks)!=set(components):raise EngineError("value_checks","Every share or weight component needs exactly one printed-value check.")
        for ptr,number in components.items():
            check=checks[ptr];eid=check["evidence_id"]
            if eid not in row["counting_evidence_ids"] or eid not in value["denominator_evidence_ids"]:raise EngineError("value_evidence","Numeric check must reference eligible contributing evidence and denominator.")
            ev=maps["evidence"][eid];src=capture_source(maps["sources"][ev["source_id"]],ev);den=denominator_ok(ev,src,now)
            if den["interpretation"]=="population_bound":return False,["population_bound"]
            printed=check["value_as_printed"]
            if printed not in ev.get("excerpt",""):raise EngineError("printed_value","Printed numeric literal is absent from its captured excerpt.")
            try:
                if check["conversion"]=="identity":
                    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?",printed):raise ValueError()
                    expected=Fraction(Decimal(printed))
                    if not 0<=expected<=1 or check["numerator_as_printed"] is not None or check["denominator_as_printed"] is not None:raise ValueError()
                elif check["conversion"]=="percent_to_fraction":
                    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?%",printed):raise ValueError()
                    expected=Fraction(Decimal(printed[:-1]))/100
                    if check["numerator_as_printed"] is not None or check["denominator_as_printed"] is not None:raise ValueError()
                else:
                    a,b=check["numerator_as_printed"],check["denominator_as_printed"]
                    if not isinstance(a,str) or not isinstance(b,str) or not re.fullmatch(r"[0-9]+",a) or not re.fullmatch(r"[1-9][0-9]*",b) or a not in ev["excerpt"] or b not in ev["excerpt"] or int(b)!=den["n"]:raise ValueError()
                    expected=Fraction(int(a),int(b))
                if expected!=Fraction(Decimal(str(number))):raise ValueError()
            except (ValueError,InvalidOperation,TypeError) as exc:raise EngineError("value_mismatch","Proposed fraction differs from the printed numeric proof.") from exc
    elif field=="frequency":
        if not value["denominator_evidence_ids"]:raise EngineError("frequency_frame","Task frequency needs measured denominator evidence.")
        for eid in value["denominator_evidence_ids"]:
            ev=maps["evidence"][eid];src=capture_source(maps["sources"][ev["source_id"]],ev)
            if src["source_family"]!="measured":raise EngineError("frequency_frame","Task frequency requires target product measurement.")
            denominator_ok(ev,src,now)
    elif field=="concrete_data":
        if not isinstance(value["value"],dict) or not value["value"] or any(type(x) not in (str,int,float,bool,type(None)) for x in value["value"].values()):raise EngineError("task_data","Product task data must be a safe nonempty scalar map.")
        if value["value_checks"] or value["denominator_evidence_ids"]:raise EngineError("task_data","Task data must use observation or approved-brief proof, not proportion checks.")
        if claim["claim_kind"]=="product_behavior":
            proofs=[p for oid in row["observation_ids"] for p in maps["observations"][oid].get("product_values",[])]
            if not any(p["join"]==join and canonical(p["value"])==canonical(value["value"]) for p in proofs):
                raise EngineError("task_value_proof","Product task data must match an exact value recorded by a completed product observation.")
        if claim["claim_kind"]=="intended_behavior":
            approved=[p for eid in row["counting_evidence_ids"] if maps["sources"][maps["evidence"][eid]["source_id"]]["source_type"]=="product_brief" and maps["sources"][maps["evidence"][eid]["source_id"]]["access_basis"]=="team_provided" for p in maps["evidence"][eid].get("approved_values",[])]
            if not any(p["join"]==join and canonical(p["value"])==canonical(value["value"]) for p in approved):
                raise EngineError("approved_brief_required","Task data must match an exact value in the reviewed approved brief.")
    elif value["value_checks"]:raise EngineError("value_checks","Non-weight values do not take proportion checks.")
    return True,[]


def assess(bundle,brief,query,receipt,input_hash,now):
    issues=[];warnings=[];maps={k:{x["id"]:x for x in v} for k,v in bundle["records"].items()}
    decisions=Decisions(bundle,receipt,issues);components=Components(bundle);scope_cycles(bundle);validate_caps(bundle,issues)
    resolutions=bundle["research"].get("scope_resolutions",[])
    if len({x["id"] for x in resolutions})!=len(resolutions):
        raise EngineError("resolution_id","Scope-resolution IDs must be unique.")
    for resolution in resolutions:
        target=maps["claims"][resolution["claim_id"]]
        valid=resolution_valid(resolution,target,maps,decisions)
        if resolution["kind"]=="scope_change":
            prior=maps["claims"][resolution["prior_claim_id"]]
            valid=valid and not (set(prior["counter_evidence_ids"])-set(target["counter_evidence_ids"])) and prior["claim_kind"]==target["claim_kind"] and prior["subject"]==target["subject"]
        if not valid:issues.append(problem("scope_resolution_invalid",target["id"],"A scope resolution must be content-bound, structured and retain all predecessor counters."))
    rows=[]
    for claim in bundle["records"]["claims"]:
        support=claim.get("research_support_evidence_ids",claim["evidence_ids"])
        grades=[]
        initial=[]
        for eid in support:
            ev=maps["evidence"][eid];src=capture_source(maps["sources"][ev["source_id"]],ev)
            initial.append(grade(ev,src,claim,brief,decisions,issues))
        external=[g for g in initial if g["eligible"] and g["final_grade"] in {"A","B"} and not capture_source(maps["sources"][maps["evidence"][g["evidence_id"]]["source_id"]],maps["evidence"][g["evidence_id"]]).get("flags",{}).get("own_brand")]
        for old in initial:
            eid=old["evidence_id"];ev=maps["evidence"][eid];src=capture_source(maps["sources"][ev["source_id"]],ev)
            corroborated=any(components.find(g["evidence_id"])!=components.find(eid) and maps["sources"][maps["evidence"][g["evidence_id"]]["source_id"]]["platform_family"]!=src["platform_family"] for g in external)
            g=grade(ev,src,claim,brief,decisions,issues,external=corroborated)
            numeric=claim["claim_kind"] in NUMERIC_KINDS or any(x["join"]["field"] in WEIGHT_FIELDS|{"frequency"} for x in claim["audience_values"])
            if g["eligible"] and src["source_family"]=="statistical":denominator_ok(ev,src,now)
            if numeric and ev.get("epistemic_status")=="observed":
                if src["source_family"]=="voice":raise EngineError("voice_numeric", "Voice evidence cannot be counting input for numeric population values.")
                if g["eligible"]:denominator_ok(ev,src,now)
            grades.append(g)
        units=units_for(grades,maps,components);counting=sorted(u["representative_evidence_id"] for u in units)
        observations=eligible_observations(bundle,claim,require_scope=True) if claim["claim_kind"]=="product_behavior" else []
        if observations:
            product_url=brief.get("product",{}).get("url")
            good=[]
            for oid in observations:
                obs=maps["observations"][oid];run=maps["runs"][obs["run_id"]]
                if product_url and (not isinstance(run.get("surface_ref"),str) or urlsplit(run["surface_ref"]).netloc!=urlsplit(product_url).netloc):continue
                if claim["about_current_version"]:
                    version=brief.get("product",{}).get("current_version");release=brief.get("product",{}).get("release_date")
                    if not (version and (obs.get("version") or run.get("version"))==version or release and (run.get("started_at") or obs.get("observed_at") or "")[:10]>=release):continue
                good.append(oid)
            observations=good
        required,conflict=counters(claim,bundle,maps,query,decisions,issues)
        missing_release=claim["about_current_version"] and not brief.get("product",{}).get("release_date")
        if missing_release:issues.append(problem("release_date_required",claim["id"],"Current-version claims need the product release date."))
        stale=claim["about_current_version"] and (missing_release or not counting and not observations)
        if conflict:status="conflicting"
        elif stale:status="stale"
        elif claim["claim_kind"]=="product_behavior":status="supported_high" if observations else "needs_product_check"
        elif grades and all(g["final_grade"]=="E" for g in grades):status="unfit"
        else:status=support_status(units,maps)
        context=sorted((set(support)|set(claim.get("research_context_evidence_ids",[])))-set(counting))
        confidence={"supported_high":"high","supported_medium":"medium"}.get(status)
        row=dict(claim_id=claim["id"],input_sha256=input_hash,status=status,best_grade=min((g["final_grade"] for g in grades if g["eligible"]),default=None),grades=grades,counting_evidence_ids=counting,context_evidence_ids=context,counter_evidence_ids=sorted(claim.get("counter_evidence_ids",[])),observation_ids=observations,units=units,channel_families=sorted({u["channel_family"] for u in units if u["channel_family"]}),organisations=sorted({u["org"] for u in units if u["org"]}),reasons=[status],counter_search_required=required,confidence=confidence,share_basis="unknown",export_values=[])
        if counting:
            denoms=[maps["evidence"][x].get("denominator") for x in counting]
            if all(d and d["interpretation"]=="product_measure" for d in denoms):row["share_basis"]="measured"
            elif any(d and d["interpretation"]=="comparable_estimate" for d in denoms):row["share_basis"]="estimated"
        nonnews=[u for u in units if maps["sources"][maps["evidence"][u["representative_evidence_id"]]["source_id"]]["source_family"]!="secondary"]
        nonnews_ok=claim["claim_kind"]=="product_behavior" and bool(observations) or support_status(nonnews,maps) in SUPPORTED
        for v in claim["audience_values"]:
            ok,reasons=value_valid(v,claim,row,maps,brief,now)
            export_evidence=sorted(u["representative_evidence_id"] for u in nonnews)
            reasons+=[] if status in SUPPORTED else [status]
            if not nonnews_ok:reasons.append("secondary_required")
            restricted_quotes=[maps["evidence"][e].get("excerpt","") for e in export_evidence if maps["sources"][maps["evidence"][e]["source_id"]].get("access_basis") in {"authorised_member","official_api"}]
            def strings(value):
                if isinstance(value,str):return [value]
                if isinstance(value,dict):return [s for item in value.values() for s in strings(item)]
                if isinstance(value,list):return [s for item in value for s in strings(item)]
                return []
            if any(q and quote_text(q) in quote_text(text) for q in restricted_quotes for text in strings(v["value"])):reasons.append("shared_quotation")
            source_ids=sorted({maps["evidence"][eid]["source_id"] for eid in export_evidence})
            def evidence_kind(eid):
                src=maps["sources"][maps["evidence"][eid]["source_id"]];typ=src["source_type"];fam=src["source_family"]
                return "firsthand" if fam=="voice" or typ in {"interview","usability_test","support_tickets"} else "statistic" if fam in {"statistical","measured"} or fam=="estimate" and maps["evidence"][eid]["evidence_type"] in {"quantitative","statistic"} else "official" if fam=="intent" else "inference"
            row["export_values"].append(dict(**copy.deepcopy(v),eligible=ok and not reasons,reason_codes=sorted(set(reasons)),evidence_ids=export_evidence,source_ids=source_ids,observation_ids=observations,evidence_kinds=[dict(evidence_id=e,kind=evidence_kind(e)) for e in export_evidence]))
        rows.append(row)
    # Contradictory exact joins are withheld, never averaged.
    joined=defaultdict(list)
    for row in rows:
        for value in row["export_values"]:
            if value["eligible"]:joined[canonical(value["join"])].append(value)
    for values in joined.values():
        if len({canonical(x["value"]) for x in values})>1:
            for value in values:value["eligible"]=False;value["reason_codes"].append("value_conflict")
    return rows, [loads(x) for x in sorted(set(canonical(x) for x in issues))], warnings
