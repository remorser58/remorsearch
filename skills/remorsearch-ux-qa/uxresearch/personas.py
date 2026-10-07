"""Synthetic behavioral persona/scenario hypotheses for QA, linked to gated research.

This is a small export/validation path beside export-audience, for runs whose
population-grade audience stays empty: the agent authors hypothesis personas
from a starter built out of the gated bundle, and the export turns authored
entries into (a) a ux-evidence-bundle.v1 QA packet whose personas are
explicitly basis=synthetic and whose scenarios carry motivation_claim_ids,
exact gate status cards and falsifying tests, and (b) ergo-scenario.v1
skeletons when real task inputs exist. Nothing here observes, verifies or
measures anything: unsafe, stopped, withdrawn or injection-flagged material is
refused even as a prompt, and unknown distributions stay unknown.
"""
from __future__ import annotations

import copy

from .canonical import EngineError, canonical, digest, resource_url
from .grading import SUPPORTED, capture_source
from .merge import privacy_scan
from .privacy import mask_url
from .schema import Resolver, require

SCHEMA = "ux-research-persona-hypotheses.v1.schema.json"
ADAPTER = "uxresearch-personas/1"
UNSAFE_RETENTION = {"withdrawn", "deleted", "redacted"}
BLOCKED_STATUS = {"unfit"}
UNKNOWN_FIELDS = ("population_share", "market_share", "user_share", "device_share",
                  "frequency", "age_distribution", "gender_mix", "regional_mix")


def _issue(code, location, reason, next_step):
    return dict(code=code, location=location, reason=reason, next_step=next_step)


def _source_safe(source):
    if source.get("research_tombstone") or source.get("retention_status") in UNSAFE_RETENTION:
        return "withdrawn or deleted source"
    access = source.get("access") or {}
    if access.get("stop_class") not in {None, "none"}:
        return f"stopped source ({access.get('stop_class')})"
    return None


def _injection_safe(target, kind, capture_ref, decisions):
    flags = {x["id"] for x in target.get("flags", {}).get("injection_flags", [])}
    cleared = {fid for d in decisions if d["kind"] == "injection" and d["target_kind"] == kind
               and d["target_id"] == target["id"] and d["capture_ref"] == capture_ref
               and d["outcome"] == "cleared" for fid in d["flag_ids"]}
    return not flags - cleared


def _url_issue(url, location):
    if url is None:
        return None
    try:
        if not isinstance(url, str):
            raise ValueError()
        resource_url(url)
        if mask_url(url) != url or privacy_scan(url) or any(c.isspace() for c in url):
            raise ValueError()
    except (EngineError, ValueError, TypeError):
        return _issue("unsafe_url", location, "화면 URL이 잘못되었거나 인증 정보·개인 식별자를 포함합니다.",
                      "인증 정보와 개인 식별자가 없는 http(s) 화면 URL을 제공하세요.")
    return None


def claim_cards(bundle, gate):
    """One honest card per gated claim: status, counter outcome and exportability."""
    rows = {x["claim_id"]: x for x in gate["claims"]}
    sources = {x["id"]: x for x in bundle["records"]["sources"]}
    evidence_map = {x["id"]: x for x in bundle["records"]["evidence"]}
    decisions = bundle.get("research", {}).get("verifier_decisions", [])
    cards = []
    for claim in sorted(bundle["records"]["claims"], key=lambda x: x["id"]):
        row = rows.get(claim["id"])
        counter = claim.get("counter_search") or {}
        evidence = sorted({e for key in ("evidence_ids", "research_support_evidence_ids", "context_evidence_ids",
                                        "research_context_evidence_ids", "counter_evidence_ids")
                           for e in claim.get(key, [])} | set(counter.get("counter_evidence_ids", [])))
        source_ids = sorted({evidence_map[e]["source_id"] for e in evidence if e in evidence_map}
                            | set(counter.get("read_source_ids", [])))
        blocked = None
        if row is None:
            blocked = "claim is absent from the current gate"
        elif row["status"] in BLOCKED_STATUS:
            blocked = f"gate status {row['status']} (unfit material cannot motivate personas)"
        else:
            for sid in source_ids:
                source = sources.get(sid)
                reason = _source_safe(source) if source else "missing source reference"
                if reason:
                    blocked = f"{sid}: {reason}"
                    break
            for eid in evidence if blocked is None else []:
                ev = evidence_map.get(eid)
                if ev is None:
                    blocked = "missing evidence reference"
                    break
                src = capture_source(sources[ev["source_id"]], ev)
                if _source_safe(src) or not _injection_safe(sources[ev["source_id"]], "source", ev.get("capture_ref"), decisions) or not _injection_safe(src, "source", ev.get("capture_ref"), decisions) or not _injection_safe(ev, "evidence", ev.get("capture_ref"), decisions):
                    blocked = "stopped, withdrawn or unresolved injection-flagged capture"
                    break
            if blocked is None:
                for sid in counter.get("read_source_ids", []):
                    src = sources[sid]
                    if src.get("flags", {}).get("injection_flags") and not src.get("captures"):
                        blocked = "unsafe counter-search source"
                        break
                    for cap in src.get("captures", []):
                        view = {**src, **cap["metadata"]}
                        if _source_safe(view) or not _injection_safe(view, "source", cap["capture_ref"], decisions):
                            blocked = "unsafe counter-search capture"
                            break
                    if blocked:
                        break
            if blocked is None and not evidence:
                blocked = "no counting or context evidence in the gated bundle"
            if blocked is None and privacy_scan([claim["statement"], counter.get("summary")]):
                blocked = "claim text contains personal identifier patterns"
        if blocked:
            # This is an agent prompt: blocked cards expose no source content or locators.
            cards.append(dict(claim_id=claim["id"], gate_status=row["status"] if row else None,
                              exportable=False, blocked_reason=blocked))
            continue
        cards.append(dict(claim_id=claim["id"], claim_kind=claim["claim_kind"], statement=claim["statement"],
                          gate_status=row["status"], confidence=row["confidence"],
                          counter_search_required=row["counter_search_required"],
                          counter_outcome=counter.get("outcome"), counter_summary=counter.get("summary"),
                          counter_call_ids=list(counter.get("call_ids", [])),
                          counter_evidence_ids=sorted(claim.get("counter_evidence_ids", [])),
                          counter_source_ids=sorted(counter.get("read_source_ids", [])),
                          counting_evidence_ids=sorted(row["counting_evidence_ids"]),
                          context_evidence_ids=sorted(row["context_evidence_ids"]),
                          source_ids=source_ids, exportable=True, blocked_reason=None))
    return cards


def starter(bundle, gate, brief):
    """A useful authored-input starter: exact claim cards plus field-level diagnostics.

    The starter never generates personas or demographic attributes; authoring is
    the agent's responsibility. personas stays empty and authored stays false.
    """
    if gate["mode"] == "fixture":
        raise EngineError("fixture_export", "Fixture research cannot be exported as persona material.", 1)
    cards = claim_cards(bundle, gate)
    url_issue = _url_issue((brief or {}).get("product", {}).get("url"), "product.url")
    if url_issue:
        raise EngineError(**dict(code=url_issue["code"], location=url_issue["location"],
                                 reason=url_issue["reason"], next_step=url_issue["next_step"]))
    diagnostics = [dict(field="personas", reason="작성한 페르소나 가설이 없습니다.",
                        next_step="검사할 상황을 personas[i]에 작성하고 문서와 각 항목의 authored를 true로 지정하세요."),
                   dict(field="personas[i].motivation_claim_ids", reason="조사 근거와 검사용 가설을 연결해야 합니다.",
                        next_step="claim_cards에서 exportable=true인 정확한 CLM- ID를 인용하세요."),
                   dict(field="personas[i].assumptions_ko", reason="조사로 확인한 내용과 검사를 위해 정한 조건을 구분해야 합니다.",
                        next_step="첫 사용·한 손 사용 등 검사용 조건과 확인하지 못한 내용을 문장별로 적으세요."),
                   dict(field="personas[i].scenario.expected_behavior_ko", reason="시험할 행동과 결정을 작성해야 합니다.",
                        next_step="expected_behavior_ko와 expected_decision_ko에 제품에서 확인할 행동을 적으세요."),
                   dict(field="personas[i].scenario.falsifying_product_test_ko", reason="예상과 다른 결과가 나오면 가설을 수정할 수 있어야 합니다.",
                        next_step="가설을 반증할 제품 관찰과 falsifying_interview_question_ko의 인터뷰 질문을 적으세요."),
                   dict(field="personas[i].scenario.priority", reason="조사 뒤 새로 높은 우선순위를 부여하면 반례 검색 검증이 빠집니다.",
                        next_step="P0/P1은 해당 우선순위로 검증한 supported 주장과 완료한 반례 검색이 필요합니다. 탐색용 상황은 P2/P3로 작성하세요.")]
    product = (brief or {}).get("product", {})
    if not product.get("url"):
        diagnostics.append(dict(field="product.url",
                                reason="브리프에 제품 URL이 없습니다.",
                                next_step="brief.product.url 또는 personas[i].scenario.surface_url에 검사할 URL을 제공하세요. 없으면 실행용 시나리오 파일을 생성하지 않습니다."))
    diagnostics.append(dict(field="personas[i].scenario.concrete_data",
                            reason="조사 글에서 제품의 과제 입력값을 만들 수 없습니다.",
                            next_step="제품 관찰이나 승인된 브리프·검사용 데이터의 concrete_data를 제공하세요. 모르면 null로 두고 미검사 조건으로 유지하세요."))
    doc = dict(schema_version="ux-research-persona-hypotheses.v1", bundle_id=bundle["bundle_id"],
               gate_bundle_input_sha256=gate["bundle_input_sha256"], authored=False,
               claim_cards=cards, diagnostics=diagnostics,
               guidance=dict(unknown_fields=",".join(UNKNOWN_FIELDS),
                             policy="페르소나는 작성한 검사용 조건입니다. 내보내기로 실제 사용자의 행동이나 선호가 확인되는 것은 아닙니다.",
                             forbidden="커뮤니티 소속에서 인구 특성이나 선호를 추정하지 마세요. 비율과 빈도는 미확인으로 유지하고 검사용 상황의 가정을 밝히세요."),
               personas=[])
    require(doc, SCHEMA)
    return doc


def _packet_records(entry, card_map):
    scenario = entry["scenario"]
    motivation = [card_map[c] for c in entry["motivation_claim_ids"]]
    persona = dict(id=entry["persona_id"], basis="synthetic", label_ko=entry["label_ko"],
                   adapter_revision=ADAPTER,
                   schema_fingerprint=digest(entry),
                   seed=0, shard_or_config="persona-hypotheses",
                   max_scanned_rows=0, max_bytes_read=0, timeout_ms=0,
                   selected_record_ids=[],
                   filled_strata=["research_claim_motivation"],
                   unfilled_strata=list(UNKNOWN_FIELDS),
                   stop_reason="authored_synthetic_no_dataset",
                   original_attributes=dict(motivation_claim_ids=list(entry["motivation_claim_ids"]),
                                            situation_ko=entry["situation_ko"]),
                   scenario_assumptions=dict(situation_ko=entry["situation_ko"],
                                             assumptions_ko=list(entry["assumptions_ko"]),
                                             context_ko=scenario.get("context_ko"),
                                             device_ids=list(scenario.get("device_ids", [])),
                                             a11y_conditions=list(scenario.get("a11y_conditions", []))))
    record = dict(id=scenario["scenario_id"], persona_id=entry["persona_id"],
                  task=scenario["task_goal_ko"], task_id=None, segment_id=None, context_id=None,
                  priority=scenario["priority"], motivation_claim_ids=list(entry["motivation_claim_ids"]),
                  epistemic_status="inferred", verification_status="unverified", basis="synthetic",
                  context_ko=scenario.get("context_ko"), concrete_data=scenario.get("concrete_data"),
                  device_ids=list(scenario.get("device_ids", [])),
                  a11y_conditions=list(scenario.get("a11y_conditions", [])),
                  expected_behavior_ko=scenario["expected_behavior_ko"],
                  expected_decision_ko=scenario["expected_decision_ko"],
                  likely_failure_ko=scenario["likely_failure_ko"],
                  falsifying_product_test_ko=scenario["falsifying_product_test_ko"],
                  falsifying_interview_question_ko=scenario["falsifying_interview_question_ko"],
                  assumptions_ko=list(entry["assumptions_ko"]),
                  motivation=[dict(claim_id=m["claim_id"], gate_status=m["gate_status"], confidence=m["confidence"],
                                   counter_search_required=m["counter_search_required"],
                                   counter_outcome=m["counter_outcome"], counter_summary=m["counter_summary"],
                                   counter_call_ids=m["counter_call_ids"], counter_evidence_ids=m["counter_evidence_ids"],
                                   counter_source_ids=m["counter_source_ids"],
                                   counting_evidence_ids=m["counting_evidence_ids"],
                                   context_evidence_ids=m["context_evidence_ids"], source_ids=m["source_ids"])
                              for m in motivation],
                  unknowns=list(UNKNOWN_FIELDS))
    return persona, record


def scenario_markdown(packet):
    lines = [f"# 합성 페르소나 QA 시나리오 ({packet['bundle_id']})", "",
             "조사 근거를 바탕으로 작성한 검사용 가설입니다. 사람·집단을 대표하지 않으며 비율과 빈도는 알 수 없습니다.", ""]
    sources = {s["id"]: s for s in packet["records"]["sources"]}
    for scenario in packet["records"]["scenarios"]:
        if scenario.get("basis") != "synthetic" or "motivation" not in scenario:
            continue
        persona = next(p for p in packet["records"]["personas"] if p["id"] == scenario["persona_id"])
        lines += [f"## {scenario['id']} · {persona['label_ko']}", "",
                  f"검사 목표: {scenario['task']}",
                  f"상황: {scenario.get('context_ko') or '미제공'}",
                  f"검사용 기기: {', '.join(scenario['device_ids']) or '미제공'}",
                  f"과제 입력값: {canonical(scenario['concrete_data']).decode() if scenario['concrete_data'] else '미제공'}", "",
                  f"예상 행동: {scenario['expected_behavior_ko']}",
                  f"예상 결정: {scenario['expected_decision_ko']}",
                  f"실패 가능성: {scenario['likely_failure_ko']}",
                  f"가설을 검증할 제품 검사: {scenario['falsifying_product_test_ko']}",
                  f"인터뷰 질문: {scenario['falsifying_interview_question_ko']}", "", "검사를 위해 정한 가정:", ""]
        lines += [f"- {assumption}" for assumption in scenario["assumptions_ko"]]
        lines += ["", "근거와 반례 검색:", ""]
        for motivation in scenario["motivation"]:
            lines.append(f"- {motivation['claim_id']} · {motivation['gate_status']} · 반례 검색: {motivation['counter_outcome'] or '기록 없음'}")
            if motivation["counter_summary"]:
                lines.append(f"  요약: {motivation['counter_summary']}")
            refs = motivation["counting_evidence_ids"] + motivation["context_evidence_ids"] + motivation["counter_evidence_ids"]
            lines.append(f"  근거 ID: {', '.join(refs) or '없음'}")
            for sid in motivation["source_ids"]:
                src = sources[sid]
                lines.append(f"  출처: {sid} · {src['channel']} · {src.get('published_at') or '날짜 미확인'}")
        lines += ["", f"알 수 없는 분포와 빈도: {', '.join(scenario['unknowns'])}", ""]
    return "\n".join(lines) + "\n"


def ergo_stub(scenario, url):
    data = ", ".join(f"{k}={v}" for k, v in (scenario.get("concrete_data") or {}).items())
    return dict(schema_version="ergo-scenario.v1", scenario_id=scenario["id"],
                surface={"kind": "web", "url": url},
                task_goal_ko=f"{scenario['task']}" + (f" (사용할 값: {data})" if data else ""),
                device_ids=list(scenario["device_ids"]),
                targets={"primary": [], "destructive": [], "critical_message": [], "error_message": [],
                         "status": [], "navigation": [], "ad_like": [], "hud": [], "game_control": [], "timed": []},
                steps=[], timing_windows=[],
                motivation_claim_ids=list(scenario["motivation_claim_ids"]),
                audience_ref=dict(audience_id=None, segment_ids=[], claim_ids=list(scenario["motivation_claim_ids"]),
                                  basis="synthetic_exploratory",
                                  note="조사 근거로 작성한 검사용 가설이며 집단을 대표하지 않습니다."),
                todo=["실제 화면에서 요소 역할과 수행 단계를 지정하세요.", "시간 제약을 확인하세요.", "성공 조건을 지정하세요."])


def export(bundle, gate, brief, doc, audience_id, *, now):
    """Validate the authored hypotheses and build the QA packet and ergo stubs."""
    from scripts.validate_bundle import validate_bundle as qa_validate
    if gate["mode"] == "fixture":
        raise EngineError("fixture_export", "Fixture research cannot be exported as persona material.", 1)
    issues = []
    for error in Resolver().validate(doc, SCHEMA)[:20]:
        path, _, detail = error.partition(":")
        issues.append(_issue("hypotheses_schema", path.replace("$.", "", 1).replace("$", "<root>"),
                             "Authored hypotheses fail the pinned schema: " + detail.strip() + ".",
                             "Correct the field at this path (ux-research-persona-hypotheses.v1)."))
    if issues:
        return None, issues, []
    if not isinstance(audience_id, str) or not audience_id.strip() or privacy_scan(audience_id):
        issues.append(_issue("unsafe_value", "audience_id", "내보내기 ID가 비어 있거나 개인 식별자를 포함합니다.",
                             "개인 식별자가 없는 내보내기 ID를 제공하세요."))
    if doc["bundle_id"] != bundle["bundle_id"]:
        issues.append(_issue("bundle_id", "bundle_id", "Hypotheses were authored against a different bundle.",
                             "Regenerate the starter from the current committed bundle and gate."))
    if doc["gate_bundle_input_sha256"] != gate["bundle_input_sha256"]:
        issues.append(_issue("stale_gate", "gate_bundle_input_sha256",
                             "Hypotheses were authored against a stale gate.",
                             "Regenerate the starter after the current gate pass and re-author the deltas."))
    if gate["result"] != "pass":
        issues.append(_issue("failed_gate", "gate", "The current research gate did not pass.",
                             "Resolve the gate issues and rerun the gate before exporting personas."))
    url_issue = _url_issue((brief or {}).get("product", {}).get("url"), "product.url")
    if url_issue:
        issues.append(url_issue)
    if not doc.get("authored"):
        issues.append(_issue("not_authored", "authored",
                             "The document is an unmodified starter; authoring is required.",
                             "Author personas[i] entries and set authored=true at the top level."))
    if not doc.get("personas"):
        issues.append(_issue("no_personas", "personas",
                             "No persona hypothesis is present.",
                             "Author at least one entry citing an exportable claim from the starter's claim_cards."))
    if issues:
        return None, issues, []

    cards = {c["claim_id"]: c for c in claim_cards(bundle, gate)}
    known = {c["claim_id"] for c in cards.values()}
    existing_ids = {x["id"] for group in bundle["records"].values() for x in group}
    claims = {c["id"]: c for c in bundle["records"]["claims"]}
    seen = set()
    for i, entry in enumerate(doc["personas"]):
        where = f"personas[{i}]"
        if not entry.get("authored"):
            issues.append(_issue("not_authored", f"{where}.authored",
                                 "This entry was not authored; starter entries cannot export.",
                                 "Author the entry and set authored=true."))
        for j, cid in enumerate(entry["motivation_claim_ids"]):
            if cid not in known:
                issues.append(_issue("unknown_claim", f"{where}.motivation_claim_ids[{j}]",
                                     "Claim ID does not exist in the gated bundle.",
                                     "Use exact CLM- ids from the starter's claim_cards."))
                continue
            card = cards[cid]
            if not card["exportable"]:
                issues.append(_issue("unsafe_motivation", f"{where}.motivation_claim_ids[{j}]",
                                     f"{cid}: {card['blocked_reason']}.",
                                     "Unsafe, stopped, withdrawn or unfit material cannot motivate a persona; cite an exportable claim."))
                continue
            priority = entry["scenario"]["priority"]
            if priority in {"P0", "P1"}:
                claim = claims[cid]
                if card["gate_status"] not in SUPPORTED or priority not in claim.get("scenario_priorities", []) or not card["counter_search_required"] or not card["counter_call_ids"]:
                    issues.append(_issue("priority_prerequisites", f"{where}.scenario.priority",
                                         "P0/P1 requires a supported claim gated for that priority with a completed counter-search.",
                                         "Declare the priority in the source claim, perform counter-search and re-gate, or keep the exploratory scenario at P2/P3."))
        url_issue = _url_issue(entry["scenario"].get("surface_url"), f"{where}.scenario.surface_url")
        if url_issue:
            issues.append(url_issue)
        from ergoqa.devices import get_device
        for j, device_id in enumerate(entry["scenario"].get("device_ids", [])):
            try:
                get_device(device_id)
            except KeyError:
                issues.append(_issue("unknown_device", f"{where}.scenario.device_ids[{j}]",
                                     "검사할 기기 ID가 기존 ergonomics 기기 목록에 없습니다.",
                                     "ergo_qa.py devices에서 실제 지원하는 기기 ID를 선택하세요."))
        for key, value in (("persona_id", entry["persona_id"]), ("scenario_id", entry["scenario"]["scenario_id"])):
            if value in existing_ids or value in seen:
                location = f"{where}.scenario.scenario_id" if key == "scenario_id" else f"{where}.{key}"
                issues.append(_issue("duplicate_id", location,
                                     "Record ID collides with an existing or duplicate record.",
                                     "Choose a distinct PER-/SC- id."))
            seen.add(value)
    if issues:
        return None, issues, []

    personas, scenarios = [], []
    for i, entry in enumerate(doc["personas"]):
        persona, record = _packet_records(entry, cards)
        if privacy_scan(persona) or privacy_scan(record):
            issues.append(_issue("unsafe_value", f"personas[{i}]",
                                 "Authored persona or scenario text carries identifier patterns.",
                                 "Remove personal identifiers; personas use authored scrubbed descriptions only."))
            continue
        personas.append(persona)
        scenarios.append(record)
    if issues:
        return None, issues, []

    packet = copy.deepcopy(bundle)
    packet["bundle_id"] = "QAB-" + digest(dict(bundle_id=bundle["bundle_id"], audience_id=audience_id,
                                               personas=doc["personas"]))[:24]
    packet["records"] = copy.deepcopy(bundle["records"])
    packet["records"]["personas"] = list(bundle["records"]["personas"]) + personas
    packet["records"]["scenarios"] = list(bundle["records"]["scenarios"]) + scenarios
    packet["research"] = copy.deepcopy(bundle.get("research") or {})
    packet["persona_export"] = dict(audience_id=audience_id, adapter_revision=ADAPTER,
                                     gate_bundle_input_sha256=gate["bundle_input_sha256"],
                                     gate_process_input_sha256=gate["process_input_sha256"],
                                     source_bundle_id=bundle["bundle_id"], mode=gate["mode"],
                                     basis="synthetic_exploratory",
                                     unknowns=list(UNKNOWN_FIELDS),
                                     notes="페르소나와 시나리오는 작성한 검사용 조건입니다. 실제 행동·선호·비중과 검사 결과는 미확인입니다.")
    errors = qa_validate(packet, now=now)
    if errors:
        issues.append(_issue("packet_contract", "packet",
                             f"Produced QA packet fails validate_bundle: {errors[0]}",
                             "This is an internal contract mismatch; report it with the packet."))
        return None, issues, []

    stubs, warnings = [], []
    product_url = (brief or {}).get("product", {}).get("url")
    for entry in doc["personas"]:
        scenario = next(s for s in scenarios if s["id"] == entry["scenario"]["scenario_id"])
        url = entry["scenario"].get("surface_url") or product_url
        if url and scenario.get("concrete_data") and scenario.get("device_ids"):
            stubs.append(ergo_stub(scenario, url))
        else:
            missing = []
            if not url:
                missing.append("surface_url")
            if not scenario.get("concrete_data"):
                missing.append("concrete_data")
            if not scenario.get("device_ids"):
                missing.append("device_ids")
            warnings.append(dict(field=f"scenarios.{scenario['id']}",
                                 reason="제공하지 않은 과제 입력: " + ", ".join(missing) + ".",
                                 next_step="검사할 URL, 지원 기기와 승인된 과제 데이터를 제공하세요. 실제 화면의 수행 단계는 QA에서 작성하세요."))
    return dict(packet=packet, stubs=stubs), issues, warnings
