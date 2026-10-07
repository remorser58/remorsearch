"""Korean Markdown report for an ergonomic persona-swarm run."""

from __future__ import annotations

from typing import Any, Iterable

from . import checks
from .profiles import CONDITION_STRATA, TOUCH_ONLY_STRATA
from .swarm import severity_counts

BASIS_KO = {
    "measured": "실측(화면에서 측정, observed)",
    "model": "모델 예측(inferred)",
    "judgment": "판단(LLM/사람, inferred)",
}


def _fmt_measure(measurement: dict[str, Any]) -> str:
    if measurement.get("id") and measurement.get("checkpoint") is not None:
        return (f"검사 {measurement['id']} · {measurement['property']} · 시점 {measurement['checkpoint']} · "
                f"결과 {measurement['result']} · step {measurement['step_index']} · 캡처 {measurement['snapshot_id']} (값 비공개)")
    value = measurement.get("value")
    unit = measurement.get("unit", "")
    threshold = measurement.get("threshold")
    comparator = measurement.get("comparator", "")
    return f"{measurement.get('name')}={value} {unit} (기준 {comparator} {threshold})"


def render(
    findings: list[dict[str, Any]],
    profiles: Iterable[dict[str, Any]],
    analyses: Iterable[dict[str, Any]],
    title: str = "인간공학 페르소나 스웜 QA 보고서",
    limitations: Iterable[str] = (),
    audience: dict[str, Any] | None = None,
    plan: dict[str, Any] | None = None,
) -> str:
    profiles = list(profiles)
    composed = any(p.get("audience_ref") for p in profiles)
    from .swarm import units as make_units

    hypotheses = [f for f in findings if f.get("tier") == "hypothesis"]
    findings = [f for f in findings if f.get("tier") != "hypothesis"]
    problem_units = make_units(findings)
    ucounts = severity_counts(problem_units)
    analyses = list(analyses)
    counts = severity_counts(findings)
    lines: list[str] = [f"# {title}", ""]
    lines += [
        "## 1. 범위와 증거 경계",
        "",
        f"- 실행(run) {len(analyses)}건, 시뮬레이션 프로필 {len(profiles)}개. 문제 단위 {len(problem_units)}건 "
        f"(P0 {ucounts['P0']} · P1 {ucounts['P1']} · P2 {ucounts['P2']} · P3 {ucounts['P3']}), 요소별 발견 {len(findings)}건 "
        f"(P0 {counts['P0']} · P1 {counts['P1']} · P2 {counts['P2']} · P3 {counts['P3']}).",
        "- 문제 단위는 같은 시나리오·같은 체크·같은 차이 조건의 발견을 하나로 묶은 것입니다(예: 한 화면의 작은 본문 글자 여러 개 = 1건).",
        "- 모든 조작은 드라이버가 실제 화면(브라우저/기기)에서 수행한 기록을 분석했습니다. 인간공학 수치는 결정론적 모델이 계산했고, LLM 페르소나가 연기하지 않았습니다.",
        "- 'k/n 시뮬레이션 프로필'은 **커버리지**이며 실제 사용자 비율(유병률·선호)을 뜻하지 않습니다.",
        "- 실측(observed)과 모델 예측(inferred)을 분리해 표기했습니다. 모델 예측은 실제 사용자 테스트로 확인해야 하는 가설입니다.",
        "- 엄지 도달 모델은 보정 전 휴리스틱(thumb-reach-v3-uncalibrated)이므로 단독으로 P2를 넘기지 않습니다.",
        "",
    ]
    unhealthy = [a for a in analyses if a.get("health") in ("failed", "degraded")]
    if unhealthy:
        lines.append(f"- **실행 상태 경고:** {len(unhealthy)}개 실행이 실패했거나 불완전합니다. 해당 실행의 '발견 없음'은 통과가 아닙니다.")
    for a in analyses:
        for note in a.get("limitations", []):
            lines.append(f"- {note}")
    for item in limitations:
        lines.append(f"- {item}")
    if limitations or unhealthy or any(a.get("limitations") for a in analyses):
        lines.append("")
    lines += ["## 2. 실행 목록", "", "| run | 시나리오 | 기기 | 실행 상태 | 과업 성공 | 평가 프로필 |", "|---|---|---|---|---|---|"]
    for a in analyses:
        lines.append(f"| {a['run_id']} | {a.get('scenario_id')} | {a.get('device_id')} ({a.get('orientation')}) | {a.get('run_status')} | {a.get('run_success')} | {', '.join(a['profiles_evaluated'])} |")
    lines += ["", "## 3. 시뮬레이션 프로필 (시나리오 가정)", "", "| ID | 설명 | 기기 | 표본 방식 |", "|---|---|---|---|"]
    for p in profiles:
        a = p["attributes"]
        origin = p.get("origin", "")
        if p.get("coverage_stratum"):
            origin += f" ({p['coverage_stratum']})"
        lines.append(f"| {p['profile_id']} | {p.get('label_ko', '')} | {a.get('device_id')} | {origin} |")
    devices = sorted({p["attributes"]["device_id"] for p in profiles})
    lines += ["", f"- 테스트한 기기: {', '.join(devices)}"]
    if composed:
        names = {s["segment_id"]: s["name_ko"] for s in (audience or {}).get("segments", [])}
        lines.append("- 프로필은 대상 사용자 리서치(ergo-audience.v1)의 세그먼트에서 구성했습니다. 세그먼트 비중은 배분에만 썼고 실제 사용자 비율이 아닙니다.")
        for p in profiles:
            ref = p.get("audience_ref") or {}
            if ref:
                lines.append(f"  - {p['profile_id']}: {names.get(ref.get('segment_id'), ref.get('segment_id'))} — {'; '.join(ref.get('reasons', []))}")
        untested = (plan or {}).get("untested", [])
        if untested:
            lines.append("- 예산 밖이라 시험하지 않은 조건: " + "; ".join(f"{names.get(u['segment_id'], u['segment_id'])}: {u['reason']}" for u in untested))
    else:
        from .devices import get_device
        from .profiles import core_strata

        covered = {p.get("coverage_stratum") for p in profiles}
        groups = {(p["attributes"]["device_id"], p["attributes"].get("orientation")) for p in profiles}
        wanted = []
        for device_id, orientation in sorted(groups):
            wanted += [name for name, _ in core_strata(get_device(device_id), orientation) if name not in wanted]
        touch = any(get_device(device_id).input == "touch" for device_id, _ in groups)
        wanted += [name for name, _ in CONDITION_STRATA if touch or name not in TOUCH_ONLY_STRATA]
        missing = [name for name in wanted if name not in covered]
        lines.append(f"- 이번 실행에서 다루지 않은 커버리지 층: {', '.join(missing) if missing else '없음'}")
    lines.append("- 페르소나 데이터셋에 없는 인간공학 속성(손잡이·파지·손 크기·시력·운동·기기)은 모두 시나리오 가정입니다.")
    lines += ["", "## 4. 문제 단위 (분류·수정 우선순위용)", "", "| ID | 심각도 | 체크 | 시나리오 | 조건 | 요소 수 | 발견 ID |", "|---|---|---|---|---|---|---|"]
    for u in problem_units:
        lines.append(f"| {u['id']} | {u['severity']} | {u['check_id']} {u['title_ko']} | {u['scenario_id']} | {u['condition']} | {len(u['instances'])} | {', '.join(u['instances'][:6])}{' …' if len(u['instances']) > 6 else ''} |")
    lines += ["", "### 요소별 발견 요약", "", "| ID | 심각도 | 범주 | 근거 | 대상 | 커버리지 | 차이 조건 |", "|---|---|---|---|---|---|---|"]
    for f in findings:
        diff = ", ".join(f"{k}={v}" for k, v in f["profile_specific"].items()) or "-"
        target = f["element_key"].replace("|", " / ")[:48]
        lines.append(f"| {f['id']} | {f['severity']} | {f['category']} | {BASIS_KO[f['basis']].split('(')[0]} | {target} | {f['coverage_label'].split(' (')[0]} | {diff} |")
    if composed:
        names = {s["segment_id"]: s["name_ko"] for s in (audience or {}).get("segments", [])}
        seg_ids = sorted({(p.get("audience_ref") or {}).get("segment_id") for p in profiles} - {None})
        lines += ["", "### 세그먼트별 발견", "", "| 세그먼트 | P0 | P1 | P2 | P3 | 이 세그먼트에서만 발생 |", "|---|---|---|---|---|---|"]
        for sid in seg_ids:
            hits = [f for f in findings if sid in f.get("segments_affected", [])]
            only = [f["id"] for f in hits if f.get("segments_affected") == [sid]]
            sev = {k: sum(1 for f in hits if f["severity"] == k) for k in ("P0", "P1", "P2", "P3")}
            lines.append(f"| {names.get(sid, sid)} ({sid}) | {sev['P0']} | {sev['P1']} | {sev['P2']} | {sev['P3']} | {', '.join(only[:8]) or '-'}{' …' if len(only) > 8 else ''} |")
    lines += ["", "## 5. 발견 상세", ""]
    for f in findings:
        lines += [
            f"### {f['id']} [{f['severity']}] {f['title_ko']}",
            "",
            f"- 체크: `{f['check_id']}` · 범주: {f['category']} · 근거: {BASIS_KO[f['basis']]}" + (f" · 모델: `{f['model']}`" if f.get("model") else ""),
            f"- 시나리오: `{f['scenario_id']}` · 대상: `{f['element_key']}`",
            f"- 관찰: {f['summary_ko']}",
            f"- 측정: {_fmt_measure(f['measurement'])}",
            f"- 커버리지: {f['coverage_label']} — 발생 {', '.join(f['triggered_profiles'])}",
        ]
        if f["profile_specific"]:
            lines.append("- 차이 조건(발생 프로필에만 공통): " + ", ".join(f"`{k}={v}`" for k, v in f["profile_specific"].items()))
        if f.get("segments_affected"):
            lines.append("- 영향 세그먼트(구성 프로필 기준, 비율 아님): " + ", ".join(f["segments_affected"]))
        lines += [
            f"- 권장 수정({f['fix_layer']}): {f['recommendation_ko']}",
            f"- 근거 문헌: {', '.join(f['refs'])}",
            f"- 증거 ID: {', '.join(f['observation_ids'][:6])}" + (" …" if len(f["observation_ids"]) > 6 else ""),
            "",
        ]
    if hypotheses:
        lines += ["## 5-1. 검토용 가설 (결함으로 세지 않음)", "",
                  "검증에서 고유 탐지가 없고 판정 타당도가 낮았던 모델 체크입니다(GZ-01, GZ-04, PC-05). 디자인 검토의 단서로만 쓰세요.", ""]
        for u in make_units(hypotheses):
            lines.append(f"- {u['check_id']} {u['title_ko']} · {u['scenario_id']} · 조건 {u['condition']} · 요소 {len(u['instances'])}개 ({', '.join(e.split('|')[0] for e in u['elements'][:4])})")
        lines.append("")
    lines += [
        "## 6. 자동화하지 않은 판단 (사람/비전 LLM 확인 필요)",
        "",
        "- WCAG 2.5.8 예외(인라인·동등 대안·필수) 해당 여부, 동작의 비가역성, 시각적 위계가 실제로 주요 버튼처럼 읽히는지.",
        "- 실제 파지 습관·파지 전환, 손에 가려진 메시지를 실제로 놓쳤는지, 피로·통증.",
        "- 게임 의도(QTE·연타가 설계 의도인지), 좌우 반전 HUD의 품질, 광고처럼 보이는지(배너 블라인드니스).",
        "",
        "## 7. 다음 검증",
        "",
        "- P0/P1 및 모델 기반 P2는 해당 조건의 실제 사용자(예: 왼손 한 손 파지, 노안, 색각이상) 과제 테스트로 확인하세요.",
        "- 커뮤니티 리서치(aside-community-ux-research)로 같은 문제의 실제 사용자 언급을 교차 확인하세요.",
        "- 수정 후 같은 시나리오·기기·프로필로 재실행해 회귀를 확인하세요.",
        "",
    ]
    return "\n".join(lines)


def catalog_markdown() -> str:
    lines = ["| ID | 범주 | 근거 | 이름 | 문헌 |", "|---|---|---|---|---|"]
    for spec in checks.iter_catalog():
        lines.append(f"| {spec.check_id} | {spec.category} | {spec.basis} | {spec.title_ko} | {', '.join(spec.refs)} |")
    return "\n".join(lines)
