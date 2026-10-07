#!/usr/bin/env python3
"""Ablation and add-one experiments over recorded benchmark runs.

Runs are recorded once per scenario and device by ``scripts/ergo_bench.py``
(real Chromium input). Ergonomic models are pure functions of the recorded
screen and the profile, so every experiment here re-analyses the same runs
offline:

    python3 skills/remorsearch-ux-qa/scripts/ergo_experiments.py analyse --exp .ergo-bench/exp
    python3 skills/remorsearch-ux-qa/scripts/ergo_experiments.py run --exp .ergo-bench/exp --out docs/validation/experiments/ablation.json

``analyse`` evaluates every run under a one-factor-at-a-time profile pool
(each core grip x each single condition) plus the benchmark's own stratified
swarm and default persona, and caches the observations. ``run`` then scores
variants against each suite's answer key:

- check leave-one-out and category leave-one-out on the current swarm;
- condition and grip leave-one-out on the pool;
- swarm size discovery curves (random, stratified, and a greedy upper bound);
- model toggles that need re-analysis (touch multipliers, gaze);
- severity agreement per check.

Answer keys are read by this script only for scoring. Outputs name defects by
ID; do not use them to tune a held-out suite (the three suites analysed here
are development suites; the frozen held-out result is in docs/validation/).
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import pickle
import random
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Callable, Iterable

ROOT = Path(__file__).resolve().parents[1]  # skill folder
REPO = ROOT.parents[1]  # repository checkout (benchmarks are not shipped with the skill)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from ergoqa import analyze, bench, checks, params, swarm  # noqa: E402
from ergoqa.devices import get_device  # noqa: E402
from ergoqa.profiles import _finalise, _set_path, matches_condition  # noqa: E402

SUITES = ("mobile-commerce", "game-desktop", "heldout-mixed")

TOUCH_GRIPS = (
    ("one_hand_right", {"handedness": "right", "grip": "one_hand_right"}),
    ("one_hand_left", {"handedness": "left", "grip": "one_hand_left"}),
    ("cradle_right", {"handedness": "right", "grip": "cradle_right"}),
    ("two_thumbs", {"handedness": "right", "grip": "two_thumbs"}),
)
LANDSCAPE_TOUCH_GRIPS = (("two_thumbs", {"handedness": "right", "grip": "two_thumbs"}),
                         ("two_thumbs_left", {"handedness": "left", "grip": "two_thumbs"}))
POINTER_GRIPS = (
    ("mouse_right", {"handedness": "right", "grip": "mouse_right"}),
    ("mouse_left", {"handedness": "left", "grip": "mouse_left"}),
    ("keyboard_only", {"handedness": "right", "grip": "keyboard_only"}),
)
# One factor at a time around a 30s, no-impairment baseline.
CONDITIONS: tuple[tuple[str, dict[str, Any]], ...] = (
    ("baseline", {}),
    ("age_20s", {"age_band": "20s"}),
    ("age_50s", {"age_band": "50s", "vision.presbyopia": True}),
    ("presbyopia_60s", {"age_band": "60s", "vision.presbyopia": True}),
    ("age_70s_plus", {"age_band": "70s+", "vision.presbyopia": True}),
    ("cvd_deutan", {"vision.cvd": "deutan"}),
    ("cvd_protan", {"vision.cvd": "protan"}),
    ("cvd_tritan", {"vision.cvd": "tritan"}),
    ("low_vision", {"vision.acuity": "low"}),
    ("tremor_mild", {"motor.tremor": "mild"}),
    ("tremor_moderate", {"motor.tremor": "moderate"}),
    ("walking", {"context.mobility": "walking"}),
    ("transit", {"context.mobility": "transit"}),
    ("bright_sun", {"context.lighting": "bright_sun"}),
    ("dark", {"context.lighting": "dark"}),
    ("first_use", {"cognition.familiarity": "first_use"}),
    ("small_hand", {"hand_percentile": 5}),
    ("large_hand", {"hand_percentile": 95}),
)
# Which profile attribute values define a condition when filtering any profile.
CONDITION_MATCH: dict[str, dict[str, Any]] = {
    "age_20s": {"age_band": ["10s", "20s"]},
    "age_50s": {"age_band": "50s"},
    "presbyopia_60s": {"age_band": "60s"},
    "age_70s_plus": {"age_band": "70s+"},
    "cvd_deutan": {"vision.cvd": "deutan"},
    "cvd_protan": {"vision.cvd": "protan"},
    "cvd_tritan": {"vision.cvd": "tritan"},
    "low_vision": {"vision.acuity": "low"},
    "tremor_mild": {"motor.tremor": "mild"},
    "tremor_moderate": {"motor.tremor": "moderate"},
    "walking": {"context.mobility": "walking"},
    "transit": {"context.mobility": "transit"},
    "bright_sun": {"context.lighting": "bright_sun"},
    "dark": {"context.lighting": "dark"},
    "first_use": {"cognition.familiarity": "first_use"},
    "small_hand": {"hand_percentile": 5},
    "large_hand": {"hand_percentile": 95},
}


# ---------------------------------------------------------------------------
# Loading


def load_suite(suite: str, exp: Path) -> dict[str, Any]:
    suite_dir = REPO / "benchmarks" / suite
    work = exp / suite
    scenarios = {}
    for f in sorted((suite_dir / "scenarios").glob("*.json")):
        doc = json.loads(f.read_text(encoding="utf-8"))
        scenarios[doc["scenario_id"]] = doc
    key = json.loads((suite_dir / "answer_key.json").read_text(encoding="utf-8"))
    swarm_profiles = json.loads((work / "profiles.json").read_text(encoding="utf-8"))["profiles"]
    runs = sorted(p for p in (work / "runs").iterdir() if (p / "run.json").is_file())
    return {"suite": suite, "scenarios": scenarios, "key": key, "swarm_profiles": swarm_profiles, "runs": runs, "work": work}


def group_key(profile: dict[str, Any]) -> str:
    a = profile["attributes"]
    return f"{a['device_id']}|{a['orientation']}"


def pool_for(device_id: str, orientation: str) -> list[dict[str, Any]]:
    """One-factor-at-a-time pool: every core grip x every single condition."""
    from ergo_bench import default_profile

    device = get_device(device_id)
    if device.input == "touch":
        grips = LANDSCAPE_TOUCH_GRIPS if orientation == "landscape" else TOUCH_GRIPS
    else:
        grips = POINTER_GRIPS
    out = []
    for grip_name, grip in grips:
        for cond_name, cond in CONDITIONS:
            profile = default_profile(device_id, orientation)
            attrs = profile["attributes"]
            for k, v in {**grip, **cond}.items():
                _set_path(attrs, k, v)
            if grip["grip"].startswith("one_hand"):
                attrs["context"]["free_hands"] = 1
            # _finalise fills derived values only when they are empty.
            attrs["motor"]["touch_sigma_multiplier"] = 1.0
            attrs["cognition"]["reading_wpm_ko"] = 0
            attrs["reaction_time_ms"] = 0
            attrs["vision"]["viewing_distance_mm"] = 0
            profile["profile_id"] = f"XP-{grip_name}-{cond_name}@{device_id}-{orientation[0]}"
            profile["origin"] = "experiment_pool"
            profile["pool"] = {"grip": grip_name, "condition": cond_name}
            out.append(_finalise(profile, device))
    return out


# ---------------------------------------------------------------------------
# Analysis cache

LEAN_PASSED = ("check_id", "element_key", "profile_id", "passed", "run_id")


def _lean(obs: dict[str, Any]) -> dict[str, Any]:
    if obs["passed"]:
        return {k: obs[k] for k in LEAN_PASSED}
    keep = dict(obs)
    keep.pop("refs", None)
    keep.pop("message_en", None)
    return keep


def analyse(exp: Path, suites: Iterable[str], extra_profiles: Callable[[dict[str, Any]], list[dict[str, Any]]] | None = None,
            tag: str = "pool", checkpoint: Path | None = None) -> dict[str, Any]:
    """Analyse every run under the pool. With ``checkpoint``, finished runs are saved
    after each run and skipped on the next call (the container can restart mid-way).
    Delete the checkpoint when the detector changes."""
    cache: dict[str, Any] = {}
    done: dict[str, dict[str, Any]] = {}
    from ergo_bench import provenance

    code = provenance()["code_sha256"]
    if checkpoint is not None and checkpoint.is_file():
        with checkpoint.open("rb") as fh:
            saved = pickle.load(fh)
        if saved.get("__code__") == code:
            done = saved
            print(f"  resuming: {sum(len(v) for k, v in done.items() if k != '__code__')} runs already analysed", flush=True)
        else:
            print("  checkpoint from other detector code ignored", flush=True)
    done["__code__"] = code
    for suite in suites:
        data = load_suite(suite, exp)
        profiles_by_group: dict[str, list[dict[str, Any]]] = {}
        for p in data["swarm_profiles"]:
            profiles_by_group.setdefault(group_key(p), []).append(p)
        analyses = []
        all_profiles: dict[str, dict[str, Any]] = {p["profile_id"]: p for p in data["swarm_profiles"]}
        started = time.time()
        for run_dir in data["runs"]:
            run_doc = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            own = all_profiles[run_doc["profile_id"]]
            gk = group_key(own)
            device_id, orientation = gk.split("|")
            from ergo_bench import default_profile

            base = default_profile(device_id, orientation)
            pool = pool_for(device_id, orientation)
            extra = extra_profiles(data) if extra_profiles else []
            evaluated = [own] + [p for p in profiles_by_group[gk] if p is not own] + [base] + pool + extra
            for p in evaluated:
                all_profiles[p["profile_id"]] = p
            if run_dir.name in done.get(suite, {}):
                analyses.append(done[suite][run_dir.name])
                continue
            result = analyze.analyze_run(run_dir, evaluated, data["scenarios"].get(run_doc["scenario_id"]), cross_profile=True)
            result["observations"] = [_lean(o) for o in result["observations"]]
            result.pop("coverage", None)
            analyses.append(result)
            if checkpoint is not None:
                done.setdefault(suite, {})[run_dir.name] = result
                tmp = checkpoint.with_suffix(".tmp")
                with tmp.open("wb") as fh:
                    pickle.dump(done, fh)
                tmp.replace(checkpoint)
            print(f"  {suite} {run_dir.name}: {len(result['profiles_evaluated'])} profiles, {len(result['observations'])} obs, {time.time() - started:.0f}s", flush=True)
        cache[suite] = {"analyses": analyses, "profiles": all_profiles, "key": data["key"], "swarm_ids": [p["profile_id"] for p in data["swarm_profiles"]]}
    return cache


# ---------------------------------------------------------------------------
# Variant scoring


def evaluate(entry: dict[str, Any], profile_ids: set[str] | None = None, check_filter: Callable[[str], bool] | None = None,
             basis: str | None = None, obs_filter: Callable[[dict[str, Any]], bool] | None = None) -> dict[str, Any]:
    analyses = []
    for a in entry["analyses"]:
        obs = a["observations"]
        if obs_filter is not None:
            obs = [o for o in obs if o["passed"] or obs_filter(o)]
        if profile_ids is not None:
            obs = [o for o in obs if o["profile_id"] in profile_ids]
        if check_filter is not None:
            obs = [o for o in obs if check_filter(o["check_id"])]
        if basis is not None:
            obs = [o for o in obs if checks.CATALOG[o["check_id"]].basis == basis]
        evaluated = [pid for pid in a.get("profiles_evaluated", []) if profile_ids is None or pid in profile_ids]
        analyses.append({"scenario_id": a["scenario_id"], "run_id": a.get("run_id"), "profiles_evaluated": evaluated, "observations": obs})
    used = [p for pid, p in entry["profiles"].items() if profile_ids is None or pid in profile_ids]
    findings = [f for f in swarm.aggregate(analyses, used) if f.get("tier") != "hypothesis"]
    score = bench.score(entry["key"], findings, used)
    clean_ids = {f["id"] for f in score["clean_findings"]}
    exact = bench.score(entry["key"], findings, used, exact_viewport=True)
    return {
        "units": score["units"],
        "clean_units": score["clean_control_units"],
        "strict_exact": {d["id"] for d in exact["per_defect"] if d["detected_strict"]},
        "elements_flagged": len({(f["scenario_id"], f["element_key"]) for f in findings}),
        "clean_elements_flagged": len({(f["scenario_id"], f["element_key"]) for f in findings if f["id"] in clean_ids}),
        "strict": {d["id"] for d in score["per_defect"] if d["detected_strict"]},
        "lenient": {d["id"] for d in score["per_defect"] if d["detected_lenient"]},
        "severity_ok": {d["id"] for d in score["per_defect"] if d["severity_ok"]},
        "findings": len(findings),
        "clean": score["clean_control_findings"],
        "clean_by_severity": score["clean_control_by_severity"],
        "decoys": score["decoys_flagged"],
        "unlabeled": score["unlabeled_findings_in_defect_variants"],
        "per_defect": score["per_defect"],
        "clean_findings": score["clean_findings"],
        "unlabeled_list": score["unlabeled"],
        "findings_list": findings,
    }


def combine(results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    out = {"strict": set(), "lenient": set(), "severity_ok": set(), "strict_exact": set(), "findings": 0, "clean": 0, "decoys": 0, "unlabeled": 0,
           "elements_flagged": 0, "clean_elements_flagged": 0, "units": 0, "clean_units": 0}
    for suite, r in results.items():
        out["strict"] |= {f"{suite}:{d}" for d in r["strict"]}
        out["lenient"] |= {f"{suite}:{d}" for d in r["lenient"]}
        out["severity_ok"] |= {f"{suite}:{d}" for d in r["severity_ok"]}
        out["strict_exact"] |= {f"{suite}:{d}" for d in r["strict_exact"]}
        for k in ("findings", "clean", "decoys", "unlabeled", "elements_flagged", "clean_elements_flagged", "units", "clean_units"):
            out[k] += r[k]
    return out


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value on b and c discordant pairs."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(0, k + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (round(max(0.0, centre - half), 3), round(min(1.0, centre + half), 3))


def summarise(name: str, combined: dict[str, Any], baseline: dict[str, Any] | None, n_defects: int) -> dict[str, Any]:
    row = {
        "variant": name,
        "recall_strict": round(len(combined["strict"]) / n_defects, 3),
        "recall_strict_ci95": wilson(len(combined["strict"]), n_defects),
        "recall_lenient": round(len(combined["lenient"]) / n_defects, 3),
        "severity_agreement": round(len(combined["severity_ok"]) / n_defects, 3),
        "findings": combined["findings"],
        "clean_control_findings": combined["clean"],
        "decoys_flagged": combined["decoys"],
        "unlabeled": combined["unlabeled"],
        "elements_flagged": combined["elements_flagged"],
        "clean_elements_flagged": combined["clean_elements_flagged"],
        "units": combined["units"],
        "clean_control_units": combined["clean_units"],
        "recall_strict_exact_viewport": round(len(combined["strict_exact"]) / n_defects, 3),
    }
    if baseline is not None:
        lost = sorted(baseline["strict"] - combined["strict"])
        gained = sorted(combined["strict"] - baseline["strict"])
        row.update({
            "lost_strict": lost,
            "gained_strict": gained,
            "mcnemar_p": round(mcnemar_exact(len(lost), len(gained)), 4),
            "delta_findings": combined["findings"] - baseline["findings"],
            "delta_clean": combined["clean"] - baseline["clean"],
            "delta_decoys": combined["decoys"] - baseline["decoys"],
            "delta_unlabeled": combined["unlabeled"] - baseline["unlabeled"],
            "delta_elements_flagged": combined["elements_flagged"] - baseline["elements_flagged"],
            "delta_clean_elements_flagged": combined["clean_elements_flagged"] - baseline["clean_elements_flagged"],
            "delta_units": combined["units"] - baseline["units"],
            "delta_clean_units": combined["clean_units"] - baseline["clean_units"],
        })
    return row


# ---------------------------------------------------------------------------
# Experiments


def pool_ids(entry: dict[str, Any]) -> set[str]:
    return {pid for pid, p in entry["profiles"].items() if p.get("origin") == "experiment_pool"}


def default_ids(entry: dict[str, Any]) -> set[str]:
    return {pid for pid in entry["profiles"] if pid.startswith("EP-BASE-")}


def run_variant(cache, name, profile_sel, check_filter=None, basis=None, baseline=None, n_defects=0, obs_filter=None):
    per_suite = {s: evaluate(e, profile_sel(e), check_filter, basis, obs_filter) for s, e in cache.items()}
    return per_suite, summarise(name, combine(per_suite), baseline, n_defects)


def matches(profile: dict[str, Any], condition: str) -> bool:
    return matches_condition(profile, CONDITION_MATCH[condition])


def experiments(cache: dict[str, Any], seed: int, resamples: int) -> dict[str, Any]:
    n_defects = sum(len(e["key"]["defects"]) for e in cache.values())
    swarm_sel = lambda e: set(e["swarm_ids"])  # noqa: E731
    out: dict[str, Any] = {"n_defects": n_defects, "suites": {s: len(e["key"]["defects"]) for s, e in cache.items()}}

    configs = {}
    base_suites, base_row = run_variant(cache, "swarm (current, 14 stratified per touch device)", swarm_sel, n_defects=n_defects)
    base = combine(base_suites)
    configs["swarm"] = base_row
    _, configs["single_default"] = run_variant(cache, "single default persona", default_ids, baseline=base, n_defects=n_defects)
    _, configs["measured_only"] = run_variant(cache, "measured checks, default persona", default_ids, basis="measured", baseline=base, n_defects=n_defects)
    pool_suites, configs["pool"] = run_variant(cache, "full OFAT pool", pool_ids, baseline=base, n_defects=n_defects)
    pool = combine(pool_suites)
    _, configs["pool_plus_swarm"] = run_variant(cache, "pool + swarm", lambda e: pool_ids(e) | set(e["swarm_ids"]), baseline=base, n_defects=n_defects)
    out["configs"] = configs

    # Which checks and profiles produce each detected defect (current swarm).
    attribution = {}
    for s, r in base_suites.items():
        for d in r["per_defect"]:
            if d["detected_strict"]:
                fids = set(d["matched_findings"])
                matched = [f for f in r["findings_list"] if f["id"] in fids and f["category"] == d["category"]]
                attribution[f"{s}:{d['id']}"] = {
                    "checks": sorted({f["check_id"] for f in matched}),
                    "category": d["category"],
                    "profile_condition": d["profile_condition"],
                }
    out["attribution"] = attribution

    # E1: check leave-one-out on the current swarm.
    present = sorted({o["check_id"] for e in cache.values() for a in e["analyses"] for o in a["observations"] if not o["passed"]})
    loo = []
    for cid in present:
        _, row = run_variant(cache, f"without {cid}", swarm_sel, check_filter=lambda c, cid=cid: c != cid, baseline=base, n_defects=n_defects)
        row["check_id"] = cid
        row["category"] = checks.CATALOG[cid].category
        row["basis"] = checks.CATALOG[cid].basis
        own_suites = {s: evaluate(e, swarm_sel(e), lambda c, cid=cid: c == cid) for s, e in cache.items()}
        own = combine(own_suites)
        row["alone_strict"] = sorted(own["strict"])
        row["alone_findings"] = own["findings"]
        row["alone_clean"] = own["clean"]
        row["alone_clean_by_severity"] = {k: sum(r["clean_by_severity"][k] for r in own_suites.values()) for k in ("P0", "P1", "P2", "P3")}
        row["alone_unlabeled"] = own["unlabeled"]
        row["alone_decoys"] = own["decoys"]
        loo.append(row)
    out["check_leave_one_out"] = loo

    # E2: category leave-one-out.
    cats = sorted({checks.CATALOG[c].category for c in present})
    out["category_leave_one_out"] = [
        run_variant(cache, f"without category {cat}", swarm_sel, check_filter=lambda c, cat=cat: checks.CATALOG[c].category != cat, baseline=base, n_defects=n_defects)[1]
        for cat in cats
    ]

    # E3: condition / grip leave-one-out on the pool (baseline = full pool).
    cond_rows = []
    for cond in CONDITION_MATCH:
        sel = lambda e, cond=cond: {pid for pid in pool_ids(e) if not matches(e["profiles"][pid], cond)}  # noqa: E731
        _, row = run_variant(cache, f"pool without {cond}", sel, baseline=pool, n_defects=n_defects)
        row["condition"] = cond
        cond_rows.append(row)
    grips = sorted({e["profiles"][pid]["pool"]["grip"] for e in cache.values() for pid in pool_ids(e)})
    for grip in grips:
        sel = lambda e, grip=grip: {pid for pid in pool_ids(e) if e["profiles"][pid]["pool"]["grip"] != grip}  # noqa: E731
        _, row = run_variant(cache, f"pool without grip {grip}", sel, baseline=pool, n_defects=n_defects)
        row["grip"] = grip
        cond_rows.append(row)
    out["condition_leave_one_out"] = cond_rows

    # E3b: condition leave-one-out on the current swarm.
    swarm_rows = []
    for cond in CONDITION_MATCH:
        sel = lambda e, cond=cond: {pid for pid in e["swarm_ids"] if not matches(e["profiles"][pid], cond)}  # noqa: E731
        _, row = run_variant(cache, f"swarm without {cond}", sel, baseline=base, n_defects=n_defects)
        row["condition"] = cond
        row["profiles_removed"] = sum(1 for e in cache.values() for pid in e["swarm_ids"] if matches(e["profiles"][pid], cond))
        swarm_rows.append(row)
    for side in ("one_hand_left", "one_hand_right"):
        sel = lambda e, side=side: {pid for pid in e["swarm_ids"] if e["profiles"][pid]["attributes"]["grip"] != side}  # noqa: E731
        _, row = run_variant(cache, f"swarm without grip {side}", sel, baseline=base, n_defects=n_defects)
        row["grip"] = side
        swarm_rows.append(row)
    out["swarm_condition_leave_one_out"] = swarm_rows

    # E4: discovery curves. N profiles per device group.
    rng = random.Random(seed)
    curve = []
    sizes = (1, 2, 3, 4, 6, 8, 10, 14, 20, 28, 40)
    for n in sizes:
        recalls, cleans, findings = [], [], []
        for _ in range(resamples):
            def sel(e, n=n):
                chosen: set[str] = set()
                groups: dict[str, list[str]] = {}
                for pid in sorted(pool_ids(e)):
                    groups.setdefault(group_key(e["profiles"][pid]), []).append(pid)
                for pids in groups.values():
                    chosen |= set(rng.sample(pids, min(n, len(pids))))
                return chosen
            per = {s: evaluate(e, sel(e)) for s, e in cache.items()}
            comb = combine(per)
            recalls.append(len(comb["strict"]) / n_defects)
            cleans.append(comb["clean"])
            findings.append(comb["findings"])
        curve.append({"n_per_device": n, "strategy": "random_pool", "recall_mean": round(statistics.mean(recalls), 3),
                      "recall_sd": round(statistics.pstdev(recalls), 3), "clean_mean": round(statistics.mean(cleans), 1),
                      "findings_mean": round(statistics.mean(findings), 1)})
        # Stratified: core grips first, then single conditions in the coverage order.
        def strat(e, n=n):
            chosen: set[str] = set()
            groups: dict[str, list[dict[str, Any]]] = {}
            for pid in sorted(pool_ids(e)):
                groups.setdefault(group_key(e["profiles"][pid]), []).append(e["profiles"][pid])
            order_conds = ["baseline", "cvd_deutan", "presbyopia_60s", "tremor_mild", "walking", "bright_sun", "first_use",
                           "cvd_protan", "age_70s_plus", "small_hand", "large_hand", "tremor_moderate", "transit", "age_50s",
                           "cvd_tritan", "dark", "age_20s"]
            for profs in groups.values():
                grips_here = sorted({p["pool"]["grip"] for p in profs}, key=lambda g: ["one_hand_right", "one_hand_left", "two_thumbs", "cradle_right", "mouse_right", "mouse_left", "keyboard_only", "two_thumbs_left"].index(g))
                ordered = []
                for g in grips_here:
                    ordered.append(next(p for p in profs if p["pool"] == {"grip": g, "condition": "baseline"}))
                one_hand = ([g for g in grips_here if g.startswith("one_hand")]
                            or [g for g in grips_here if g.startswith("mouse")]
                            or grips_here)
                i = 0
                for cond in order_conds[1:]:
                    g = one_hand[i % len(one_hand)]
                    i += 1
                    ordered.append(next(p for p in profs if p["pool"] == {"grip": g, "condition": cond}))
                rest = [p for p in profs if p not in ordered]
                ordered += rest
                chosen |= {p["profile_id"] for p in ordered[:n]}
            return chosen
        per = {s: evaluate(e, strat(e)) for s, e in cache.items()}
        comb = combine(per)
        curve.append({"n_per_device": n, "strategy": "stratified_pool", "recall_mean": round(len(comb["strict"]) / n_defects, 3),
                      "recall_sd": 0.0, "clean_mean": comb["clean"], "findings_mean": comb["findings"]})
    out["discovery_curve"] = curve

    # Greedy upper bound: which pool profiles are needed to reach the pool's recall.
    greedy = []
    chosen: dict[str, set[str]] = {s: set() for s in cache}
    remaining = set(pool["strict"])
    candidates = {s: sorted(pool_ids(e)) for s, e in cache.items()}
    detect_by_profile: dict[tuple[str, str], set[str]] = {}
    for s, e in cache.items():
        for pid in candidates[s]:
            r = evaluate(e, {pid})
            detect_by_profile[(s, pid)] = {f"{s}:{d}" for d in r["strict"]}
    covered: set[str] = set()
    while True:
        best = max(detect_by_profile.items(), key=lambda kv: len(kv[1] - covered), default=None)
        if not best or not (best[1] - covered):
            break
        (s, pid), dets = best
        new = dets - covered
        covered |= dets
        greedy.append({"suite": s, "profile": pid, "new_defects": sorted(new), "cumulative_recall": round(len(covered) / n_defects, 3)})
    out["greedy_single_profile_cover"] = greedy
    out["pool_defects_needing_combined_profiles"] = sorted(pool["strict"] - covered)

    # E6: severity agreement per check on the current swarm.
    sev = {}
    for s, r in base_suites.items():
        for d in r["per_defect"]:
            if not d["detected_strict"]:
                continue
            for cid in attribution[f"{s}:{d['id']}"]["checks"]:
                row = sev.setdefault(cid, {"n": 0, "ok": 0, "under": 0, "pairs": []})
                row["n"] += 1
                ok = d["severity_ok"]
                row["ok"] += int(ok)
                row["under"] += int(not ok)
                row["pairs"].append(f"{s}:{d['id']} expected>={d['severity_expected_min']} found={d['severity_found']}")
    out["severity_by_check"] = sev
    return out


# ---------------------------------------------------------------------------
# Rule variants (CHANGE candidates) on the current swarm


def _tier(o: dict[str, Any]) -> str | None:
    return (o.get("measurement") or {}).get("tier")


RULE_VARIANTS: dict[str, dict[str, Any]] = {
    "PC-04 without critical-print-size P3": {"obs": lambda o: not (o["check_id"] == "PC-04" and _tier(o) == "critical_print_size")},
    "PC-04 without platform-minimum P3": {"obs": lambda o: not (o["check_id"] == "PC-04" and _tier(o) == "platform_minimum" and o["severity"] == "P3")},
    "PT-02 without one-hand 9.2 mm P3": {"obs": lambda o: not (o["check_id"] == "PT-02" and o["severity"] == "P3")},
    "RH-01 without P3": {"obs": lambda o: not (o["check_id"] == "RH-01" and o["severity"] == "P3")},
    "GZ-02 without P3": {"obs": lambda o: not (o["check_id"] == "GZ-02" and o["severity"] == "P3")},
    "PT-04 profile-only findings removed": {"obs": lambda o: not (o["check_id"] == "PT-04" and ((o.get("measurement") or {}).get("baseline_miss_probability") or 0) < params.MISS_PROBABILITY_SEVERITY[-1][0])},
    "without GZ-01, GZ-04, PC-05": {"check": lambda c: c not in ("GZ-01", "GZ-04", "PC-05")},
    "swarm without bright_sun profiles": {"profiles": "no_bright_sun"},
}


def rule_variants(cache: dict[str, Any], names: Iterable[str] | None = None, lean: Iterable[str] = ()) -> list[dict[str, Any]]:
    n_defects = sum(len(e["key"]["defects"]) for e in cache.values())
    base_suites = {s: evaluate(e, set(e["swarm_ids"])) for s, e in cache.items()}
    base = combine(base_suites)
    rows = [summarise("swarm (current)", base, None, n_defects)]

    def selector(kind: str | None):
        if kind == "no_bright_sun":
            return lambda e: {pid for pid in e["swarm_ids"] if not matches(e["profiles"][pid], "bright_sun")}
        return lambda e: set(e["swarm_ids"])

    chosen = list(names) if names else list(RULE_VARIANTS)
    for name in chosen:
        v = RULE_VARIANTS[name]
        _, row = run_variant(cache, name, selector(v.get("profiles")), check_filter=v.get("check"), baseline=base, n_defects=n_defects, obs_filter=v.get("obs"))
        rows.append(row)
    lean = list(lean)
    if lean:
        obs_filters = [RULE_VARIANTS[n]["obs"] for n in lean if "obs" in RULE_VARIANTS[n]]
        check_filters = [RULE_VARIANTS[n]["check"] for n in lean if "check" in RULE_VARIANTS[n]]
        profile_kind = next((RULE_VARIANTS[n]["profiles"] for n in lean if "profiles" in RULE_VARIANTS[n]), None)
        _, row = run_variant(cache, "lean: " + " + ".join(lean), selector(profile_kind),
                             check_filter=(lambda c: all(f(c) for f in check_filters)) if check_filters else None,
                             baseline=base, n_defects=n_defects,
                             obs_filter=(lambda o: all(f(o) for f in obs_filters)) if obs_filters else None)
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Model toggles (need re-analysis on the current swarm only)


def toggles(exp: Path, suites: Iterable[str]) -> list[dict[str, Any]]:
    variants: list[tuple[str, Callable[[], None], Callable[[], None]]] = []
    saved_mult = dict(params.TOUCH_SIGMA_MULT)

    def mult_off() -> None:
        for k in params.TOUCH_SIGMA_MULT:
            params.TOUCH_SIGMA_MULT[k] = 1.0

    def mult_restore() -> None:
        params.TOUCH_SIGMA_MULT.clear()
        params.TOUCH_SIGMA_MULT.update(saved_mult)

    variants.append(("touch_multipliers_off", mult_off, mult_restore))
    rows = []
    loaded = {s: load_suite(s, exp) for s in suites}
    n_defects = sum(len(d["key"]["defects"]) for d in loaded.values())

    def score_all(gaze_enabled: bool = True) -> dict[str, Any]:
        checks._FIXATION_CACHE.clear()
        analyze._CONSPICUITY_CACHE.clear()
        per = {}
        for s, data in loaded.items():
            analyses = []
            profiles = data["swarm_profiles"]
            fresh = copy.deepcopy(profiles)
            by_id = {p["profile_id"]: p for p in fresh}
            for p in fresh:
                device = get_device(p["attributes"]["device_id"])
                p["attributes"]["motor"]["touch_sigma_multiplier"] = 1.0
                _finalise(p, device)
            for run_dir in data["runs"]:
                run_doc = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
                analyses.append(analyze.analyze_run(run_dir, fresh, data["scenarios"].get(run_doc["scenario_id"]), cross_profile=True, gaze_enabled=gaze_enabled))
            entry = {"analyses": analyses, "profiles": by_id, "key": data["key"], "swarm_ids": list(by_id)}
            per[s] = evaluate(entry)
        return per

    baseline = combine(score_all())
    rows.append(summarise("swarm (re-analysed)", baseline, None, n_defects))
    for name, apply, restore in variants:
        apply()
        try:
            rows.append(summarise(name, combine(score_all()), baseline, n_defects))
        finally:
            restore()
    rows.append(summarise("gaze_disabled (no conspicuity map)", combine(score_all(gaze_enabled=False)), baseline, n_defects))
    return rows


# ---------------------------------------------------------------------------
# Touch-model variants (situational brief SIT-01..03; re-analysis of the swarm)

# Values before SIT-03 (commit f186f57).
TOUCH_MULT_BEFORE_SIT03 = {"mobility_walking": 1.4, "mobility_transit": 1.4, "tremor_mild": 1.5, "tremor_moderate": 2.25,
                           "age_60s": 1.15, "age_70s+": 1.3}


def _touch_variant_specs() -> list[tuple[str, dict[str, Any]]]:
    current = dict(params.TOUCH_SIGMA_MULT)
    before = {**current, **TOUCH_MULT_BEFORE_SIT03}

    def shift(values: dict[str, float], delta: float) -> dict[str, float]:
        return {k: (round(v + delta, 3) if v > 1.0 else v) for k, v in values.items()}

    off = {k: 1.0 for k in current}
    mm = params.TOUCH_TARGET_MIN_MM
    return [
        ("before", {"mult": before, "combine": "multiplicative", "p3_mm": None}),
        ("sit03", {"mult": current, "combine": "multiplicative", "p3_mm": None}),
        ("sit03_minus_0.1", {"mult": shift(current, -0.1), "combine": "multiplicative", "p3_mm": None}),
        ("sit03_plus_0.1", {"mult": shift(current, 0.1), "combine": "multiplicative", "p3_mm": None}),
        ("sit01_sit03", {"mult": current, "combine": "multiplicative", "p3_mm": mm}),
        ("sit01_sit02_sit03", {"mult": current, "combine": "additive", "p3_mm": mm}),
        ("sit02_sit03", {"mult": current, "combine": "additive", "p3_mm": None}),
        ("multipliers_off", {"mult": off, "combine": "multiplicative", "p3_mm": None}),
    ]


def _touch_variant(job: tuple[str, dict[str, Any], str, list[str], str]) -> str:
    """Score one variant in its own process (params are module globals)."""
    name, spec, exp_s, suites, out_s = job
    out = Path(out_s) / f"{name}.pickle"
    if out.is_file():
        return f"{name}: cached"
    params.TOUCH_SIGMA_MULT.clear()
    params.TOUCH_SIGMA_MULT.update(spec["mult"])
    params.TOUCH_SIGMA_COMBINE = spec["combine"]
    params.TOUCH_PROFILE_ONLY_P3_MIN_MM = spec["p3_mm"]
    checks._FIXATION_CACHE.clear()
    analyze._CONSPICUITY_CACHE.clear()
    started = time.time()
    per: dict[str, Any] = {}
    p_miss: dict[tuple[str, ...], float] = {}
    for s in suites:
        data = load_suite(s, Path(exp_s))
        fresh = copy.deepcopy(data["swarm_profiles"])
        for p in fresh:
            _finalise(p, get_device(p["attributes"]["device_id"]))
        by_id = {p["profile_id"]: p for p in fresh}
        analyses = []
        raw = {"pt04_fail": 0, "pt04_profile_only": 0, "pt04_profile_only_p2": 0, "pt03_fail": 0, "pt03_profile_only_p3": 0}
        for run_dir in data["runs"]:
            run_doc = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            result = analyze.analyze_run(run_dir, fresh, data["scenarios"].get(run_doc["scenario_id"]), cross_profile=True)
            for o in result["observations"]:
                if o["check_id"] == "PT-04":
                    m = o["measurement"]
                    p_miss[(s, run_dir.name, o["profile_id"], str(o.get("snapshot_id")), o["element_key"])] = m["value"]
                    if not o["passed"]:
                        raw["pt04_fail"] += 1
                        if m.get("profile_only"):
                            raw["pt04_profile_only"] += 1
                            raw["pt04_profile_only_p2"] += o["severity"] in ("P0", "P1", "P2")
                elif o["check_id"] == "PT-03" and not o["passed"]:
                    raw["pt03_fail"] += 1
            analyses.append(result)
        entry = {"analyses": analyses, "profiles": by_id, "key": data["key"], "swarm_ids": list(by_id)}
        r = evaluate(entry)
        used = list(by_id.values())
        sc = bench.score(data["key"], r["findings_list"], used)
        per[s] = {
            "strict": r["strict"], "severity_ok": r["severity_ok"],
            "p0_p2": {d["id"] for d in sc["per_defect"] if d["detected_strict"] and d["severity_found"] in ("P0", "P1", "P2")},
            "attributed": {d["id"] for d in sc["per_defect"] if d["detected_strict"] and (not d["profile_condition"] or d["differential_matches_condition"])},
            "findings": r["findings"], "units": r["units"], "clean_units": r["clean_units"],
            "clean_units_by_severity": sc["clean_control_units_by_severity"],
            "clean_findings_by_severity": r["clean_by_severity"],
            "pt04_findings": sum(1 for f in r["findings_list"] if f["check_id"] == "PT-04"),
            "pt03_findings": sum(1 for f in r["findings_list"] if f["check_id"] == "PT-03"),
            "clean_touch_units": sorted({(f["scenario_id"], f["element_key"], f["severity"]) for f in r["findings_list"]
                                         if f["check_id"] in ("PT-03", "PT-04") and f["id"] in {c["id"] for c in r["clean_findings"]}}),
            "n_defects": len(data["key"]["defects"]),
            **raw,
        }
    tmp = out.with_suffix(".tmp")
    with tmp.open("wb") as fh:
        pickle.dump({"name": name, "spec": spec, "per": per, "p_miss": p_miss, "seconds": round(time.time() - started)}, fh)
    tmp.replace(out)
    return f"{name}: {time.time() - started:.0f}s"


def _kendall_tau_b(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    conc = disc = tx = ty = 0
    for i in range(n):
        for j in range(i + 1, n):
            dx, dy = xs[i] - xs[j], ys[i] - ys[j]
            if dx == 0 and dy == 0:
                continue
            if dx == 0:
                tx += 1
            elif dy == 0:
                ty += 1
            elif (dx > 0) == (dy > 0):
                conc += 1
            else:
                disc += 1
    denom = math.sqrt((conc + disc + tx) * (conc + disc + ty))
    return round((conc - disc) / denom, 4) if denom else None


def touch_variants(exp: Path, suites: list[str], out_dir: Path, workers: int = 3) -> list[dict[str, Any]]:
    """SIT-01..03 on the dev recordings. Each variant is saved as it finishes, so a
    restarted container resumes where it stopped (delete out_dir when the detector changes)."""
    from concurrent.futures import ProcessPoolExecutor

    out_dir.mkdir(parents=True, exist_ok=True)
    specs = _touch_variant_specs()
    jobs = [(name, spec, str(exp), suites, str(out_dir)) for name, spec in specs]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for msg in pool.map(_touch_variant, jobs):
            print(f"  {msg}", flush=True)
    loaded = {}
    for name, _ in specs:
        with (out_dir / f"{name}.pickle").open("rb") as fh:
            loaded[name] = pickle.load(fh)

    def total(v: dict[str, Any], key: str) -> Any:
        vals = [v["per"][s][key] for s in suites]
        if isinstance(vals[0], set):
            return set().union(*({f"{s}:{d}" for d in v["per"][s][key]} for s in suites))
        if isinstance(vals[0], dict):
            return {k: sum(x[k] for x in vals) for k in vals[0]}
        if isinstance(vals[0], list):
            return [[s, *u] for s in suites for u in v["per"][s][key]]
        return sum(vals)

    n_defects = sum(loaded["before"]["per"][s]["n_defects"] for s in suites)
    ref = loaded["before"]
    rng = random.Random(11)
    rows = []
    for name, spec in specs:
        v = loaded[name]
        row: dict[str, Any] = {"variant": name, "spec": spec, "seconds": v["seconds"]}
        for key in ("strict", "p0_p2", "attributed", "severity_ok"):
            got = total(v, key)
            row[f"recall_{key}"] = round(len(got) / n_defects, 3)
            row[f"lost_{key}_vs_before"] = sorted(total(ref, key) - got)
            row[f"gained_{key}_vs_before"] = sorted(got - total(ref, key))
        for key in ("findings", "units", "clean_units", "pt04_findings", "pt03_findings", "pt04_fail", "pt04_profile_only",
                    "pt04_profile_only_p2", "pt03_fail", "clean_units_by_severity", "clean_findings_by_severity", "clean_touch_units"):
            row[key] = total(v, key)
        common = sorted(set(ref["p_miss"]) & set(v["p_miss"]))
        sample = rng.sample(common, min(2500, len(common))) if common else []
        row["kendall_tau_b_p_miss_vs_before"] = _kendall_tau_b([ref["p_miss"][k] for k in sample], [v["p_miss"][k] for k in sample])
        rows.append(row)
    # SIT-02 is judged between the multiplicative and additive structures with the same cap.
    by = {r["variant"]: r for r in rows}
    for a, c in (("sit01_sit03", "sit01_sit02_sit03"), ("sit03", "sit02_sit03")):
        va, vc = loaded[a], loaded[c]
        common = sorted(set(va["p_miss"]) & set(vc["p_miss"]))
        sample = rng.sample(common, min(2500, len(common))) if common else []
        by[c][f"kendall_tau_b_p_miss_vs_{a}"] = _kendall_tau_b([va["p_miss"][k] for k in sample], [vc["p_miss"][k] for k in sample])
        by[c][f"pt04_findings_change_vs_{a}"] = round(by[c]["pt04_findings"] / by[a]["pt04_findings"] - 1, 3) if by[a]["pt04_findings"] else None
        by[c][f"pt04_profile_only_change_vs_{a}"] = round(by[c]["pt04_profile_only"] / by[a]["pt04_profile_only"] - 1, 3) if by[a]["pt04_profile_only"] else None
        by[c][f"lost_strict_vs_{a}"] = sorted(total(va, "strict") - total(vc, "strict"))
    return rows


# ---------------------------------------------------------------------------


def _jsonable(obj: Any) -> Any:
    if isinstance(obj, set):
        return sorted(obj)
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    return obj


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("analyse")
    a.add_argument("--exp", type=Path, required=True)
    a.add_argument("--suites", default=",".join(SUITES))
    r = sub.add_parser("run")
    r.add_argument("--exp", type=Path, required=True)
    r.add_argument("--out", type=Path, required=True)
    r.add_argument("--seed", type=int, default=5)
    r.add_argument("--resamples", type=int, default=60)
    r.add_argument("--toggles", action="store_true", help="also run model toggles (re-analysis)")
    v = sub.add_parser("variants", help="rule CHANGE candidates on the current swarm")
    v.add_argument("--exp", type=Path, required=True)
    v.add_argument("--out", type=Path, required=True)
    v.add_argument("--lean", default="", help="'|'-separated variant names to combine")
    t = sub.add_parser("touch-variants", help="SIT-01..03 touch-model variants (re-analysis of the swarm)")
    t.add_argument("--exp", type=Path, required=True)
    t.add_argument("--out", type=Path, required=True)
    t.add_argument("--work", type=Path, default=None, help="per-variant results (default: <exp>/touch-variants)")
    t.add_argument("--suites", default=",".join(SUITES))
    t.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    exp = args.exp.resolve()
    cache_path = exp / "pool-cache.pickle"
    if args.cmd == "touch-variants":
        from ergo_bench import provenance

        rows = touch_variants(exp, [x for x in args.suites.split(",") if x], (args.work or exp / "touch-variants").resolve(), args.workers)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        doc = {"provenance": provenance(), "recordings": str(exp.relative_to(REPO)) if exp.is_relative_to(REPO) else str(exp), "variants": rows}
        args.out.write_text(json.dumps(_jsonable(doc), ensure_ascii=False, indent=1), encoding="utf-8")
        for row in rows:
            print(json.dumps({k: row.get(k) for k in ("variant", "recall_strict", "recall_p0_p2", "recall_attributed", "lost_strict_vs_before",
                                                      "findings", "units", "clean_units", "clean_units_by_severity", "pt04_findings", "pt04_profile_only",
                                                      "pt04_profile_only_p2", "kendall_tau_b_p_miss_vs_before")}, ensure_ascii=False))
        return 0
    if args.cmd == "analyse":
        checkpoint = exp / "pool-cache.partial.pickle"
        cache = analyse(exp, [s for s in args.suites.split(",") if s], checkpoint=checkpoint)
        with cache_path.open("wb") as fh:
            pickle.dump(cache, fh)
        checkpoint.unlink(missing_ok=True)
        print(f"cached {cache_path}")
        return 0
    with cache_path.open("rb") as fh:
        cache = pickle.load(fh)
    if args.cmd == "variants":
        rows = rule_variants(cache, lean=[n for n in args.lean.split("|") if n])
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(_jsonable(rows), ensure_ascii=False, indent=1), encoding="utf-8")
        for row in rows:
            print(json.dumps({k: row.get(k) for k in ("variant", "recall_strict", "recall_strict_exact_viewport", "severity_agreement", "findings", "clean_control_findings", "units", "clean_control_units", "lost_strict", "gained_strict", "delta_findings", "delta_clean", "delta_clean_units")}, ensure_ascii=False))
        return 0
    result = experiments(cache, args.seed, args.resamples)
    if args.toggles:
        result["model_toggles"] = toggles(exp, list(cache))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(_jsonable(result), ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(_jsonable(result["configs"]), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
