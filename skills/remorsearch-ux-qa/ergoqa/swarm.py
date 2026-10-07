"""Aggregate per-profile observations into swarm findings.

The swarm borrows MiroFish's structure (many persona agents -> shared record ->
report) but not its claims: counts are coverage over *simulated* profiles, never
a prevalence estimate, and the "differential condition" (which profile
attributes separate triggered from untriggered profiles) is computed, not
narrated by an LLM.
"""

from __future__ import annotations

from typing import Any, Iterable

from . import checks
from .hf import reach
from .profiles import _get_path

DIFFERENTIAL_ATTRIBUTES = (
    "handedness", "grip", "age_band", "device_id", "orientation",
    "vision.cvd", "vision.presbyopia", "vision.acuity", "motor.tremor", "context.mobility",
    "context.lighting", "cognition.familiarity", "cognition.time_pressure", "hand_percentile",
)

# Derived advice (research brief SIT-05): PT-02/PT-04/RH-01 findings quote the
# supporting observations' own measurements instead of only the catalog's static
# text, so each recommendation carries the estimated geometry and the exact
# failed criterion. The advice is text only: pass/fail, severity, tiers and
# thresholds stay computed in checks.py and are never changed here. Numbers that
# come from a model are labelled as model output, separated from the defect
# grade. A same-severity group can hold distinct per-profile evidence, so every
# derived segment is labelled with the profile id(s) it was measured for — one
# profile's numbers are never presented as another's (the aggregate text and the
# per-profile attach proposals both follow this rule).

_GRIP_KO = {"one_hand_right": "오른손 한 손(엄지) 파지", "one_hand_left": "왼손 한 손(엄지) 파지", "two_thumbs": "양손 두 엄지 파지"}

_PT02_CRITERION_KO = {
    "platform_floor": "플랫폼 최소 하한(iOS HIG 28pt 유래)",
    "platform_min": "플랫폼 권장 최소(44pt/48dp 상당)",
    "one_hand_reference": "한 손 엄지 조작 기준(Parhi 2006)",
}


def _num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _severity_rank(obs: dict[str, Any]) -> int:
    return checks.SEVERITY_ORDER.get(obs.get("severity") or "P3", 3)


def _pt02_segment(measurement: dict[str, Any]) -> str:
    value, threshold = measurement.get("value"), measurement.get("threshold")
    criterion = _PT02_CRITERION_KO.get(measurement.get("criterion"))
    if not (isinstance(value, (list, tuple)) and len(value) == 2 and all(_num(v) for v in value)
            and _num(threshold) and criterion):
        return ""
    w, h = float(value[0]), float(value[1])
    side = min(w, h)
    return (f"기록된 타깃 상자를 기기 카탈로그 밀도로 환산하면 {w:.1f}×{h:.1f}mm(짧은 변 {side:.1f}mm)이며 {criterion} {threshold:g}mm에 미달했습니다. "
            f"짧은 변을 {threshold:g}mm 이상으로 키우세요(현재 {side:.1f}mm, {threshold - side:.1f}mm 이상 증가). "
            "mm 값은 카탈로그 밀도로 환산한 추정치이며 44pt/48dp와 정확히 일치하는 단위 환산이 아니므로 플랫폼 도구에서는 pt/dp 권장을 그대로 적용하세요.")


def _pt04_segment(measurement: dict[str, Any]) -> str:
    same = measurement.get("same_error_square")
    if not isinstance(same, dict):
        return ""
    k, ref = same.get("sigma_multiplier"), same.get("reference_mm")
    p_base, p_miss, p_ref = measurement.get("baseline_miss_probability"), measurement.get("value"), same.get("reference_miss_probability")
    if not (_num(k) and _num(ref) and _num(p_base) and _num(p_miss) and _num(p_ref)):
        return ""
    target = measurement.get("target_mm")
    head = f"이 타깃({target[0]:.1f}×{target[1]:.1f}mm)의 " if isinstance(target, (list, tuple)) and len(target) == 2 and all(_num(v) for v in target) else "이 타깃의 "
    text = (f"{head}예측 놓침 확률(이중 가우시안, Bi & Zhai 2016): 기준 모델(k=1) {p_base * 100:.1f}% → 이 조건 {p_miss * 100:.1f}%(σ배수 {k:.2f}, 선언된 가정). "
            f"모델 동등 크기 비교: 기준 모델의 {ref:g}mm 정사각형은 예측 놓침 {p_ref * 100:.2f}%입니다. 이 조건에서 같은 적중 확률이 되는 크기를 계산했습니다. ")
    if same.get("found_within_search_bound") and _num(same.get("equivalent_square_mm")):
        text += f"계산 결과는 최소 {same['equivalent_square_mm']:.1f}mm 정사각형입니다(보정 전 모델의 검토용 비교값, 접근성 요구치 아님)."
    else:
        bound = same.get("search_bound_mm")
        bound_text = f"{bound:g}mm" if _num(bound) else "탐색 상한"
        text += f"{bound_text} 탐색 범위 안에서는 해당 크기를 찾지 못했습니다. 범위 밖의 값은 미확인입니다."
    return text


def _rh01_segment(measurement: dict[str, Any], worst: dict[str, Any]) -> str:
    grip, zone, difficulty = measurement.get("grip"), measurement.get("zone"), measurement.get("value")
    if not (zone and _num(difficulty)):
        return ""
    point = (worst.get("extra") or {}).get("point_mm")
    where = f", 대표 지점 {point[0]:.0f},{point[1]:.0f}mm" if isinstance(point, (list, tuple)) and len(point) == 2 and all(_num(v) for v in point) else ""
    return (f"도달 모델 예측({reach.MODEL_ID}, 비보정): {_GRIP_KO.get(grip, grip or '알 수 없는 파지')}, "
            f"구역 '{checks.ZONE_KO.get(zone, zone)}', 난이도 {difficulty:.2f}{where}.")


def _advice_segment(check_id: str, worst: dict[str, Any]) -> str:
    """Derived sentences for one observation; '' when it carries no advice data."""
    measurement = worst.get("measurement") or {}
    if check_id == "PT-02":
        return _pt02_segment(measurement)
    if check_id == "PT-04":
        return _pt04_segment(measurement)
    if check_id == "RH-01":
        return _rh01_segment(measurement, worst)
    return ""


def _worst_by_profile(failed: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_profile: dict[str, dict[str, Any]] = {}
    for obs in failed:
        pid = str(obs.get("profile_id") or "?")
        current = by_profile.get(pid)
        if current is None or _severity_rank(obs) < _severity_rank(current):
            by_profile[pid] = obs
    return by_profile


def _derived_recommendation(check_id: str, spec: Any, failed: list[dict[str, Any]]) -> str:
    """Catalog text, plus per-profile labelled advice for distinct supported observations.

    Same-severity observations from different profiles can carry different
    advice data (e.g. seated k=1.3 → 15.0 mm equivalent square, walking k=1.82 →
    none within the search bound). Each distinct segment is labelled with the
    profile id(s) whose measurement supports it, in sorted order, so the text is
    order-independent and one profile's numbers are never read as another's.
    """
    base = spec.recommendation_ko
    by_content: dict[str, list[str]] = {}
    for pid, obs in sorted(_worst_by_profile(failed).items()):
        segment = _advice_segment(check_id, obs)
        if segment:
            by_content.setdefault(segment, []).append(pid)
    if not by_content:
        return base
    labelled = [f"{', '.join(pids)} 조건: {segment}" for segment, pids in by_content.items()]
    return " ".join(labelled) + " " + base


def recommendation_for_profile(check_id: str, observations: list[dict[str, Any]], profile_id: str) -> str | None:
    """Advice derived from this profile's own observations, for attach proposals.

    Narrow companion to :func:`_derived_recommendation`: a QA-bundle proposal
    quotes the profile's own worst observation (labelled with its id) instead of
    a copy of the aggregate text, so a same-severity group never hands one
    persona another persona's numbers. Returns None when the observations carry
    no advice data; the caller then falls back to the aggregate recommendation.
    """
    if not observations:
        return None
    worst = min(observations, key=_severity_rank)
    segment = _advice_segment(check_id, worst)
    if not segment:
        return None
    return f"{profile_id} 조건: {segment} " + checks.CATALOG[check_id].recommendation_ko


def _differential(triggered: list[dict[str, Any]], untriggered: list[dict[str, Any]]) -> dict[str, Any]:
    """Attribute values shared by every triggered profile and by no untriggered one."""
    if not triggered or not untriggered:
        return {}
    out: dict[str, Any] = {}
    for attr in DIFFERENTIAL_ATTRIBUTES:
        values = {repr(_get_path(p["attributes"], attr)) for p in triggered}
        if len(values) != 1:
            continue
        value = _get_path(triggered[0]["attributes"], attr)
        if all(_get_path(p["attributes"], attr) != value for p in untriggered):
            out[attr] = value
    return out


def _segments(profile_ids: list[str], profiles_by_id: dict[str, dict[str, Any]]) -> list[str]:
    """Audience segments (ergo-audience.v1) whose composed profiles triggered the finding."""
    found = {((profiles_by_id.get(pid) or {}).get("audience_ref") or {}).get("segment_id") for pid in profile_ids}
    return sorted(s for s in found if s)


def _device_of(profile: dict[str, Any]) -> Any:
    from .devices import get_device, rotate

    attrs = profile.get("attributes", {})
    device = get_device(attrs.get("device_id"))
    if attrs.get("orientation") == "landscape" and device.orientation != "landscape":
        device = rotate(device, "landscape")
    return device


def aggregate(analyses: Iterable[dict[str, Any]], profiles: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    profiles_by_id = {p["profile_id"]: p for p in profiles}
    groups: dict[tuple[str, str, str], dict[str, Any]] = {}
    evaluated_by_run: dict[str, list[str]] = {}
    devices: dict[str, Any] = {}
    for analysis in analyses:
        scenario_id = analysis.get("scenario_id") or "?"
        run_id = analysis.get("run_id")
        if run_id and analysis.get("profiles_evaluated"):
            evaluated_by_run.setdefault(run_id, [])
            evaluated_by_run[run_id] += [p for p in analysis["profiles_evaluated"] if p not in evaluated_by_run[run_id]]
        for obs in analysis["observations"]:
            if (obs.get("extra") or {}).get("verdict") == "inconclusive":
                continue  # retained in raw observations and analysis limitations
            # Group by the element's selector, not its current text: a countdown or score
            # whose text changes every snapshot is one element (cross-review 2026-09-28).
            key = (scenario_id, obs["check_id"], obs["element_key"].split("|", 1)[0])
            group = groups.setdefault(key, {"tested": set(), "triggered": set(), "failed": [], "runs": set()})
            group["tested"].add(obs["profile_id"])
            group["runs"].add(obs["run_id"])
            if not obs["passed"]:
                group["triggered"].add(obs["profile_id"])
                group["failed"].append(obs)
    findings: list[dict[str, Any]] = []
    for (scenario_id, check_id, _selector), group in sorted(groups.items()):
        if not group["failed"]:
            continue
        element_key = group["failed"][0]["element_key"]
        spec = checks.CATALOG[check_id]
        if check_id != "PJ-01":
            # Denominator: every evaluated profile the check applies to, not only the ones
            # that happened to emit an observation.
            for run_id in group["runs"]:
                for pid in evaluated_by_run.get(run_id, []):
                    profile = profiles_by_id.get(pid)
                    if profile is None:
                        continue
                    if pid not in devices:
                        devices[pid] = _device_of(profile)
                    if checks.applicable(check_id, profile, devices[pid]):
                        group["tested"].add(pid)
        worst = min(group["failed"], key=lambda o: checks.SEVERITY_ORDER.get(o["severity"] or "P3", 3))
        if check_id == "PJ-01":
            # Corroboration is computed, never taken from the agent (LAT-03): notes at the
            # same anchor from runs whose operators differ in model family or input channel.
            agents = {(((o.get("extra") or {}).get("agent") or {}).get("model_family"), ((o.get("extra") or {}).get("agent") or {}).get("input_channel"))
                      for o in group["failed"]}
            families = {a[0] for a in agents if a[0]}
            channels = {a[1] for a in agents if a[1]}
            basis = "family" if len(families) >= 2 else "channel" if len(channels) >= 2 else None
            corroboration = {"corroborated": basis is not None, "basis": basis, "runs": len(group["runs"]),
                             "agents": sorted(f"{a[0]}/{a[1]}" for a in agents)}
            worst = dict(worst)
            worst["measurement"] = {**worst["measurement"], "corroborated": basis is not None, "corroboration": corroboration}
            worst["severity"] = "P2" if basis else "P3"
        tested = sorted(group["tested"])
        triggered = sorted(group["triggered"])
        # The differential is computed over every profile evaluated on the run's device,
        # counting profiles outside the check's scope as not triggered, so a CVD-only or
        # bright-sun-only finding names its condition (AP-05) instead of reading "k/k".
        evaluated = {pid for run_id in group["runs"] for pid in evaluated_by_run.get(run_id, [])} | set(tested)
        untriggered = [profiles_by_id[p] for p in sorted(evaluated) if p not in group["triggered"] and p in profiles_by_id]
        differential = {} if check_id == "TI-01" else _differential([profiles_by_id[p] for p in triggered if p in profiles_by_id], untriggered)
        findings.append({
            "check_id": check_id,
            "tier": checks.tier(check_id, worst.get("measurement")),
            "category": spec.category,
            "scenario_id": scenario_id,
            "element_key": element_key,
            "severity": worst["severity"],
            "basis": spec.basis,
            # Measured on estimated geometry (vision annotation) is still inferred.
            "epistemic_status": "observed" if spec.basis == "measured" and not any(o.get("epistemic_status") == "inferred" for o in group["failed"]) else "inferred",
            "model": worst.get("model"),
            "triggered_profiles": triggered,
            "tested_profiles": tested,
            "coverage_label": ("profile-independent (measured on the screen; coverage, not prevalence)" if check_id in checks.PROFILE_INVARIANT_CHECKS
                               else f"{len(triggered)}/{len(tested)} simulated profiles (coverage, not prevalence)"),
            "profile_specific": differential,
            "segments_affected": _segments(triggered, profiles_by_id),
            "observation_ids": [o["id"] for o in group["failed"]],
            "run_ids": sorted(group["runs"]),
            "selectors": sorted({sel for o in group["failed"] for sel in o.get("selectors", [])}),
            "context_selectors": sorted({sel for o in group["failed"] for sel in o.get("context_selectors", [])}),
            "measurement": worst["measurement"],
            "title_ko": spec.title_ko,
            "summary_ko": worst["message_ko"],
            "fix_layer": spec.fix_layer,
            "recommendation_ko": _derived_recommendation(check_id, spec, group["failed"]),
            "refs": list(spec.refs),
        })
    findings.sort(key=lambda f: (checks.SEVERITY_ORDER.get(f["severity"] or "P3", 3), f["category"], f["scenario_id"], f["element_key"]))
    for index, finding in enumerate(findings, 1):
        finding["id"] = f"EF-{index:03d}"
    return findings


def severity_counts(findings: Iterable[dict[str, Any]]) -> dict[str, int]:
    counts = {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
    for finding in findings:
        if finding.get("severity") in counts:
            counts[finding["severity"]] += 1
    return counts


def _differential_key(finding: dict[str, Any]) -> str:
    diff = finding.get("profile_specific") or {}
    return ";".join(f"{k}={diff[k]}" for k in sorted(diff)) or "all tested profiles"


def units(findings: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group findings into problem units: one (scenario, check, differential condition).

    A systemic problem (small body text across a page for presbyopic profiles, five
    targets under 24 px) is one unit with its elements as instances, as accessibility
    scanners report one rule with many nodes. Counting units instead of findings is
    the standard merge step before counting problems (UEM-02).
    """
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for f in findings:
        groups.setdefault((f["scenario_id"], f["check_id"], _differential_key(f)), []).append(f)
    out = []
    for (scenario_id, check_id, diff), members in groups.items():
        worst = min(members, key=lambda f: checks.SEVERITY_ORDER.get(f["severity"] or "P3", 3))
        triggered = sorted({p for f in members for p in f["triggered_profiles"]})
        tested = sorted({p for f in members for p in f["tested_profiles"]})
        out.append({
            "scenario_id": scenario_id,
            "check_id": check_id,
            "tier": worst.get("tier", checks.tier(check_id)),
            "category": worst["category"],
            "basis": worst["basis"],
            "severity": worst["severity"],
            "condition": diff,
            "profile_specific": worst.get("profile_specific") or {},
            "instances": [f["id"] for f in members],
            "elements": [f["element_key"] for f in members],
            "triggered_profiles": triggered,
            "tested_profiles": tested,
            "segments_affected": sorted({s for f in members for s in f.get("segments_affected", [])}),
            "title_ko": worst["title_ko"],
        })
    out.sort(key=lambda u: (checks.SEVERITY_ORDER.get(u["severity"] or "P3", 3), u["category"], u["scenario_id"], u["check_id"]))
    for i, u in enumerate(out, 1):
        u["id"] = f"EU-{i:03d}"
    return out
