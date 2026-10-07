"""Pre-registered evaluation of a v2 benchmark suite (heldout-2 layout).

A v2 suite has one folder per concern and one answer key per product:

    <suite>/products/<slug>/brief.md      product brief (Stage 0 input)
    <suite>/site/<slug>/...               pages (defect and clean variants)
    <suite>/scenarios/*.json              ergo-scenario.v1
    <suite>/keys/<slug>.json              defects, decoys, clean controls (spec 12.1)
    <suite>/audience/<slug>.audience.json Stage-0 output (written blind to defects)

Configurations (docs/validation/experiments/heldout-2-preregistration.md):

- C1 measured-only: measured checks, default persona per device group;
- C2 single persona: all checks, default persona;
- C3 stratified: ``sample_profiles`` stratified coverage, 14 per touch device and
  7 per pointer device;
- C4 audience-composed: ``audience.compose`` per product at each budget;
- C5 random: ``sample_profiles(strategy="base_rate_sample")`` at the same budgets,
  20 seeds.

Every scenario is recorded once per device group that any configuration needs
(real Chromium input, the default persona as recorder), then analysed offline
under the union of all configurations' profiles, and each configuration is
scored on the same recordings.

    python3 skills/remorsearch-ux-qa/scripts/ergo_eval.py record  --suite benchmarks/heldout-2 --out .ergo-bench/h2
    python3 skills/remorsearch-ux-qa/scripts/ergo_eval.py analyse --suite benchmarks/heldout-2 --out .ergo-bench/h2
    python3 skills/remorsearch-ux-qa/scripts/ergo_eval.py score   --suite benchmarks/heldout-2 --out .ergo-bench/h2

Custody: ``score`` prints and writes aggregate metrics only (``aggregate.json``).
Per-defect results go to ``<out>/sealed/`` and are opened only after the
aggregate report is committed. ``--open`` also prints per-defect misses; use it
for development suites only.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import pickle
import random
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]  # skill folder
REPO = ROOT.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from ergoqa import analyze, audience, bench, checks, params, swarm  # noqa: E402
from ergoqa.devices import get_device  # noqa: E402
from ergoqa.profiles import _finalise, sample_profiles  # noqa: E402

from ergo_bench import default_profile, provenance, static_server  # noqa: E402

BUDGETS = (6, 10, 14)
PLACEBO_BUDGETS = (10, 14)  # EVD-06 swap and floors-only arms
C5_SEEDS = 20
C3_TOUCH, C3_POINTER = 14, 7
BOOTSTRAP = 2000
LEAN_PASSED = ("check_id", "element_key", "profile_id", "passed", "run_id")


# ---------------------------------------------------------------------------
# Suite


def load_suite(suite: Path) -> dict[str, Any]:
    scenarios, paths = {}, {}
    for f in sorted((suite / "scenarios").glob("*.json")):
        doc = json.loads(f.read_text(encoding="utf-8"))
        scenarios[doc["scenario_id"]] = doc
        paths[doc["scenario_id"]] = f
    keys = {}
    for f in sorted((suite / "keys").glob("*.json")):
        doc = json.loads(f.read_text(encoding="utf-8"))
        keys[doc.get("product") or f.stem] = doc
    product_of: dict[str, str] = {}
    for slug, key in keys.items():
        for item in key.get("defects", []) + key.get("decoys", []) + key.get("clean_controls", []):
            product_of[item["scenario_id"]] = slug
    for sid in scenarios:
        if sid not in product_of:
            m = re.match(r"SC-[a-z0-9]+-([a-z0-9]+)-", sid)
            product_of[sid] = m.group(1) if m else sid
    audiences = {}
    for f in sorted((suite / "audience").glob("*.audience.json")) if (suite / "audience").is_dir() else []:
        audiences[f.name.split(".")[0]] = json.loads(f.read_text(encoding="utf-8"))
    merged = {"suite": suite.name, "defects": [], "decoys": [], "clean_controls": []}
    for key in keys.values():
        for part in ("defects", "decoys", "clean_controls"):
            merged[part].extend(key.get(part, []))
    return {"suite": suite, "scenarios": scenarios, "paths": paths, "keys": keys, "key": merged, "product_of": product_of, "audiences": audiences}


def _group(profile: dict[str, Any]) -> str:
    a = profile["attributes"]
    return f"{a['device_id']}|{a['orientation']}"


def _scenario_groups(scenario: dict[str, Any]) -> list[str]:
    out = []
    for device_id in scenario["device_ids"]:
        out.append(f"{device_id}|{scenario.get('orientation') or get_device(device_id).orientation}")
    return out


def _canonical(profile: dict[str, Any]) -> str:
    """Profiles with identical attributes are one profile (C5 seeds often repeat draws)."""
    digest = hashlib.sha1(json.dumps(profile["attributes"], sort_keys=True).encode()).hexdigest()[:10]
    a = profile["attributes"]
    return f"EV-{digest}@{a['device_id']}-{a['orientation'][0]}"


def _base(gk: str) -> dict[str, Any]:
    device_id, orientation = gk.split("|")
    p = default_profile(device_id, orientation)
    p["profile_id"] = f"EP-BASE-{device_id}-{orientation[0]}"
    return p


def neutral_audience(devices: list[str]) -> dict[str, Any]:
    """Placebo audience (EVD-06): one general adult segment on the product's own devices,
    no conditions, so composition adds only the inclusive floors and one-facet variations."""
    return {"schema_version": "ergo-audience.v1", "audience_id": "AU-neutral",
            "product": {"name": "neutral", "category": "placebo", "surface": "web", "locale": "ko-KR"},
            "sources": [{"source_id": "SRC-neutral", "type": "expert_judgment", "title": "Neutral placebo audience (EVD-06)"}],
            "segments": [{"segment_id": "SEG-general", "name_ko": "일반 성인 사용자", "priority": "primary", "confidence": "low",
                          "share": {"value": None, "basis": "unknown"},
                          "evidence": [{"source_id": "SRC-neutral", "claim": "placebo arm", "kind": "inference"}],
                          "age_bands": {"20s": 0.2, "30s": 0.2, "40s": 0.2, "50s": 0.2, "60s": 0.2},
                          "devices": {d: 1.0 / len(devices) for d in devices},
                          "tasks": [{"task_id": "T-main", "goal_ko": "주요 과업", "concrete_data": {"값": "시나리오 참조"},
                                     "frequency": "weekly", "criticality": "convenience", "source_ids": ["SRC-neutral"]}]}]}


def swapped_audience(donor: dict[str, Any], devices: list[str]) -> dict[str, Any]:
    """Another product's audience with its device mix replaced by this product's devices
    (EVD-06 swap arm): segments, ages, conditions and contexts from the wrong product."""
    doc = json.loads(json.dumps(donor))
    for seg in doc["segments"]:
        seg["devices"] = {d: 1.0 / len(devices) for d in devices}
    return doc


def configurations(data: dict[str, Any]) -> tuple[dict[str, dict[str, set[str]]], dict[str, dict[str, Any]], dict[str, set[str]], list[str]]:
    """Profile sets per configuration and product, the profile registry, device groups per
    scenario, notes.

    Membership is per product: the pre-registered budgets are per product, so a run of
    product B is scored only with the profiles composed or sampled for product B, even
    when product A shares its device group (review 2026-09-28, E1).
    """
    registry: dict[str, dict[str, Any]] = {}
    configs: dict[str, dict[str, set[str]]] = {}
    notes: list[str] = []

    def add(config: str, product: str, profile: dict[str, Any], canonical: bool = True) -> None:
        pid = _canonical(profile) if canonical else profile["profile_id"]
        if pid not in registry:
            keep = dict(profile)
            keep["profile_id"] = pid
            registry[pid] = keep
        configs.setdefault(config, {}).setdefault(product, set()).add(pid)

    groups_of: dict[str, set[str]] = {sid: set(_scenario_groups(sc)) for sid, sc in data["scenarios"].items()}
    products: dict[str, list[str]] = {}
    for sid, slug in data["product_of"].items():
        if sid in data["scenarios"]:
            products.setdefault(slug, []).append(sid)
    for slug, sids in sorted(products.items()):
        product_groups = sorted({g for sid in sids for g in groups_of[sid]})
        for gk in product_groups:
            base = _base(gk)
            add("C1", slug, base, canonical=False)
            add("C2", slug, base, canonical=False)
            device_id, orientation = gk.split("|")
            count = C3_TOUCH if get_device(device_id).input == "touch" else C3_POINTER
            for p in sample_profiles(count, 11, [device_id], orientation=orientation):
                add("C3", slug, p)
        doc = data["audiences"].get(slug)
        if doc is None:
            notes.append(f"{slug}: no audience file, C4 not run")
        devices = sorted({g.split("|")[0] for g in product_groups})
        slugs = sorted(s for s in data["audiences"] if s in products)
        donor = data["audiences"].get(slugs[(slugs.index(slug) + 1) % len(slugs)]) if slug in slugs and len(slugs) > 1 else None
        for budget in BUDGETS:
            if doc is not None:
                plan = audience.compose(doc, budget)
                for p in plan["profiles"]:
                    add(f"C4@{budget}", slug, p)
                    for sid in sids:
                        groups_of[sid].add(_group(p))
            if budget in PLACEBO_BUDGETS:
                arms = [("C4-floors", neutral_audience(devices))] + ([("C4-swap", swapped_audience(donor, devices))] if donor else [])
                for arm, arm_doc in arms:
                    for p in audience.compose(arm_doc, budget)["profiles"]:
                        add(f"{arm}@{budget}", slug, p)
                        for sid in sids:
                            groups_of[sid].add(_group(p))
            for seed in range(C5_SEEDS):
                for p in sample_profiles(budget, 1000 + seed, devices, strategy="base_rate_sample"):
                    add(f"C5@{budget}#{seed}", slug, p)
                    for sid in sids:
                        groups_of[sid].add(_group(p))
    return configs, registry, groups_of, notes


# ---------------------------------------------------------------------------
# Record and analyse


def record(data: dict[str, Any], out: Path) -> None:
    _, _, groups_of, notes = configurations(data)
    for n in notes:
        print(f"note: {n}", flush=True)
    runs_dir = out / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    (out / "profiles").mkdir(exist_ok=True)
    log = []
    with static_server(data["suite"].parent) as base_url:
        for sid, sc in sorted(data["scenarios"].items()):
            for gk in sorted(groups_of[sid]):
                device_id, orientation = gk.split("|")
                recorder = _base(gk)
                run_id = f"R-{sid}-{device_id}-{orientation[0]}"
                if (runs_dir / run_id / "run.json").is_file():
                    continue
                ppath = out / "profiles" / f"{recorder['profile_id']}.json"
                ppath.write_text(json.dumps(recorder, ensure_ascii=False), encoding="utf-8")
                cmd = ["node", str(ROOT / "drivers/web/ergo_drive.mjs"), "run", "--scenario", str(data["paths"][sid]), "--profile", str(ppath),
                       "--out", str(runs_dir), "--run-id", run_id, "--base", base_url, "--continue-on-error"]
                if sc.get("surface", {}).get("kind") == "game":
                    cmd += ["--flash-sample-ms", "1500"]
                started = time.time()
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1200)
                entry = {"run_id": run_id, "scenario_id": sid, "group": gk, "exit": proc.returncode, "seconds": round(time.time() - started, 1)}
                log.append(entry)
                print(f"recorded {run_id}: exit {proc.returncode} in {entry['seconds']}s", flush=True)
    previous = json.loads((out / "record-log.json").read_text(encoding="utf-8")) if (out / "record-log.json").is_file() else []
    (out / "record-log.json").write_text(json.dumps(previous + log, indent=1), encoding="utf-8")


def _lean(obs: dict[str, Any]) -> dict[str, Any]:
    if obs["passed"]:
        return {k: obs[k] for k in LEAN_PASSED}
    keep = dict(obs)
    keep.pop("refs", None)
    keep.pop("message_en", None)
    return keep


# Amendment 4 (SIT-04): the condition multipliers whose cut is decided on heldout-2.
# one_hand_thumb stays (grip changes the finger position and is a floor).
CONDITION_MULTIPLIERS = ("mobility_", "tremor_", "age_", "encumbered")
VARIANTS = {"condition-multipliers-off": "analysis-cache.cond-mult-off.pickle"}


def _variant_registry(registry: dict[str, dict[str, Any]], variant: str | None) -> dict[str, dict[str, Any]]:
    """Profiles re-finalised under a model variant (same ids; params patched by the caller)."""
    if variant is None:
        return registry
    fresh = {}
    for pid, prof in registry.items():
        q = copy.deepcopy(prof)
        _finalise(q, get_device(q["attributes"]["device_id"]))
        fresh[pid] = q
    return fresh


def analyse_all(data: dict[str, Any], out: Path, variant: str | None = None) -> dict[str, Any]:
    if variant is not None:
        if variant not in VARIANTS:
            raise SystemExit(f"unknown variant {variant}")
        saved = dict(params.TOUCH_SIGMA_MULT)
        try:
            for k in params.TOUCH_SIGMA_MULT:
                if k.startswith(CONDITION_MULTIPLIERS):
                    params.TOUCH_SIGMA_MULT[k] = 1.0
            return _analyse_all(data, out, variant)
        finally:
            params.TOUCH_SIGMA_MULT.clear()
            params.TOUCH_SIGMA_MULT.update(saved)
    return _analyse_all(data, out, None)


def _analyse_all(data: dict[str, Any], out: Path, variant: str | None) -> dict[str, Any]:
    configs, registry, _, _ = configurations(data)
    registry = _variant_registry(registry, variant)
    of_product: dict[str, set[str]] = {}
    for by_product in configs.values():
        for product, ids in by_product.items():
            of_product.setdefault(product, set()).update(ids)
    analyses, health = [], []
    started = time.time()
    for run_dir in sorted(p for p in (out / "runs").iterdir() if (p / "run.json").is_file()):
        run_doc = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        dev = run_doc.get("device") or {}
        gk = f"{dev.get('id')}|{dev.get('orientation')}"
        product = data["product_of"].get(run_doc["scenario_id"])
        # The recorder is the default persona; groups that only C4/C5 need are not in
        # C1/C2, so the recorder is evaluated but belongs to no configuration there.
        own = registry.get(run_doc["profile_id"]) or {**_base(gk), "profile_id": run_doc["profile_id"]}
        mine = [registry[pid] for pid in sorted(of_product.get(product, set())) if _group(registry[pid]) == gk]
        evaluated = [own] + [p for p in mine if p["profile_id"] != own["profile_id"]]
        try:
            result = analyze.analyze_run(run_dir, evaluated, data["scenarios"].get(run_doc["scenario_id"]), cross_profile=True)
        except Exception as err:  # noqa: BLE001 - one broken run must not stop the evaluation
            health.append({"run_id": run_doc.get("run_id"), "status": "failed", "error": str(err)[:200]})
            print(f"  {run_dir.name}: analysis failed: {err}", flush=True)
            continue
        health.append({"run_id": result.get("run_id"), "status": result.get("health")})
        result["observations"] = [_lean(o) for o in result["observations"]]
        result.pop("coverage", None)
        analyses.append(result)
        print(f"  {run_dir.name}: {len(result['profiles_evaluated'])} profiles, {len(result['observations'])} obs, {time.time() - started:.0f}s", flush=True)
    cache = {"analyses": analyses, "registry": registry, "configs": {c: {prod: sorted(ids) for prod, ids in v.items()} for c, v in configs.items()},
             "product_of": data["product_of"], "health": health, "provenance": provenance(), "variant": variant}
    with (out / (VARIANTS[variant] if variant else "analysis-cache.pickle")).open("wb") as fh:
        pickle.dump(cache, fh)
    return cache


# ---------------------------------------------------------------------------
# Scoring


def _findings(cache: dict[str, Any], ids_by_product: dict[str, list[str]], basis: str | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    analyses = []
    all_ids: set[str] = set()
    for a in cache["analyses"]:
        profile_ids = set(ids_by_product.get(cache["product_of"].get(a["scenario_id"]), []))
        all_ids |= profile_ids
        obs = [o for o in a["observations"] if o["profile_id"] in profile_ids]
        if basis is not None:
            obs = [o for o in obs if checks.CATALOG[o["check_id"]].basis == basis]
        evaluated = [pid for pid in a.get("profiles_evaluated", []) if pid in profile_ids]
        if evaluated:
            analyses.append({"scenario_id": a["scenario_id"], "run_id": a.get("run_id"), "profiles_evaluated": evaluated, "observations": obs})
    used = [cache["registry"][pid] for pid in sorted(all_ids)]
    return swarm.aggregate(analyses, used), used


def score_config(cache: dict[str, Any], key: dict[str, Any], config: str) -> dict[str, Any]:
    findings, used = _findings(cache, cache["configs"][config], basis="measured" if config == "C1" else None)
    sc = bench.score(key, findings, used, exact_viewport=True, include_hypotheses=False)
    sc["_findings"], sc["_profiles"] = findings, used
    return sc


# ---------------------------------------------------------------------------
# Amendment-3 analyses (evaluating-qa-detectors.md EVD-01..06)

CATEGORIES = ("reach", "pointing", "gaze", "perception", "cognition", "game", "semantics", "layout", "heuristic")


def twins(key: dict[str, Any], product_of: dict[str, str]) -> dict[str, str]:
    """Defect scenario -> the clean scenario of the same product."""
    clean_by_product: dict[str, str] = {}
    for c in key.get("clean_controls", []):
        clean_by_product.setdefault(product_of.get(c["scenario_id"]), c["scenario_id"])
    return {d["scenario_id"]: clean_by_product[product_of.get(d["scenario_id"])]
            for d in key.get("defects", []) if product_of.get(d["scenario_id"]) in clean_by_product}


def element_pool(out: Path) -> dict[str, list[dict[str, Any]]]:
    """Visible DOM elements per scenario over all recorded snapshots (selector, context)."""
    pool: dict[str, dict[str, dict[str, Any]]] = {}
    for run_dir in sorted(p for p in (out / "runs").iterdir() if (p / "run.json").is_file()):
        run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        per = pool.setdefault(run["scenario_id"], {})
        for snap in run.get("snapshots") or []:
            f = run_dir / snap["path"]
            if not f.is_file():
                continue
            for e in json.loads(f.read_text(encoding="utf-8")).get("elements") or []:
                if e.get("visible") is False or not e.get("selector"):
                    continue
                per.setdefault(e["selector"], {"selector": e["selector"], "context": [f"#{a}" for a in e.get("ancestor_ids") or []]})
    return {sid: list(v.values()) for sid, v in pool.items()}


def flag_all(key: dict[str, Any], pool: dict[str, list[dict[str, Any]]], profile_ids: dict[str, list[str]],
             product_of: dict[str, str]) -> list[dict[str, Any]]:
    """EVD-01 trivial detector: every visible element in every category, all profiles, P0."""
    out = []
    for sid, elements in pool.items():
        trig = profile_ids.get(product_of.get(sid), [])
        items = elements + [{"selector": "viewport", "context": []}]
        for e in items:
            for cat in CATEGORIES:
                out.append({"id": f"FA-{len(out)}", "scenario_id": sid, "check_id": f"BASE-{cat}", "category": cat,
                            "element_key": f"{e['selector']}|flash" if e["selector"] == "viewport" else f"{e['selector']}|",
                            "selectors": [e["selector"]] if e["selector"] != "viewport" else [], "context_selectors": e["context"],
                            "severity": "P0", "tier": "finding", "basis": "measured", "title_ko": "flag_all baseline",
                            "triggered_profiles": trig, "tested_profiles": trig, "profile_specific": {},
                            "run_ids": [], "instances": []})
    return out


def strict_hits(defects: list[dict[str, Any]], findings: list[dict[str, Any]], profiles_by_id: dict[str, Any]) -> list[bool]:
    by_sid: dict[str, list[dict[str, Any]]] = {}
    for f in findings:
        by_sid.setdefault(f["scenario_id"], []).append(f)
    return [any(f["category"] == d["category"] and bench._selector_matches(f, d.get("element_selector", ""), True)
                and bench._profile_ok(f, d.get("profile_condition") or {}, profiles_by_id) for f in by_sid.get(d["scenario_id"], []))
            for d in defects]


def chance_recall(key: dict[str, Any], sc: dict[str, Any], pool: dict[str, list[dict[str, Any]]], reps: int = 1000, seed: int = 11) -> dict[str, Any]:
    """EVD-01 chance level: the tool's own findings moved to random elements of the same
    scenario (category, severity, profiles and count kept), scored strictly."""
    findings = [f for f in sc["_findings"] if f.get("tier") != "hypothesis"]
    profiles_by_id = {p["profile_id"]: p for p in sc["_profiles"]}
    defects = key["defects"]
    rng = random.Random(seed)
    recalls = []
    for _ in range(reps):
        moved = []
        for f in findings:
            elems = pool.get(f["scenario_id"]) or []
            if not elems:
                continue
            e = rng.choice(elems)
            moved.append({**f, "element_key": f"{e['selector']}|", "selectors": [e["selector"]], "context_selectors": e["context"]})
        hits = strict_hits(defects, moved, profiles_by_id)
        recalls.append(sum(hits) / (len(defects) or 1))
    recalls.sort()
    mean = statistics.fmean(recalls) if recalls else 0.0
    real = sc["recall_strict"]
    return {"recall_chance_mean": round(mean, 3), "recall_chance_p95": round(recalls[int(0.95 * len(recalls)) - 1], 3) if recalls else None,
            "recall_above_chance": round(real - mean, 3), "kappa_recall": round((real - mean) / (1 - mean), 3) if mean < 1 else None, "reps": reps}


def cluster_recall(per_defect: list[dict[str, Any]], product_of: dict[str, str], reps: int = BOOTSTRAP, seed: int = 13) -> dict[str, Any]:
    """EVD-04: two-stage product bootstrap, leave-one-product-out range and per-product recall."""
    by_prod: dict[str, list[bool]] = {}
    for d in per_defect:
        by_prod.setdefault(product_of.get(d["scenario_id"], "?"), []).append(bool(d["detected_strict"]))
    prods = sorted(by_prod)
    rng = random.Random(seed)
    boots = []
    for _ in range(reps):
        vals = []
        for _p in prods:
            hits = by_prod[rng.choice(prods)]
            vals += [rng.choice(hits) for _ in hits]
        boots.append(sum(vals) / len(vals) if vals else 0.0)
    boots.sort()
    lopo = []
    for p in prods:
        rest = [h for q in prods if q != p for h in by_prod[q]]
        if rest:
            lopo.append(sum(rest) / len(rest))
    return {"n_products": len(prods), "per_product": {p: _rate(sum(v), len(v)) for p, v in by_prod.items()},
            "recall_cluster_ci95": [round(boots[int(0.025 * reps)], 3), round(boots[int(0.975 * reps) - 1], 3)] if boots else [None, None],
            "recall_lopo_range": [round(min(lopo), 3), round(max(lopo), 3)] if lopo else [None, None],
            "note": "descriptive: fewer than 10 products"}


def noise_gate(sc: dict[str, Any], clean_scenarios: int) -> dict[str, Any]:
    """EVD-05: effective false-alarm gate and an FROC-style table by severity threshold."""
    by = sc["clean_control_units_by_severity"]
    rows = {}
    for name, sev in (("p0", ("P0",)), ("p0_p1", ("P0", "P1")), ("p0_p2", ("P0", "P1", "P2")), ("all", ("P0", "P1", "P2", "P3"))):
        k = sum(by[x] for x in sev)
        rows[name] = {"clean_units": k, "per_clean_scenario": round(k / clean_scenarios, 3) if clean_scenarios else None,
                      "poisson_upper95_per_scenario": bench.poisson_upper(k, clean_scenarios),
                      "recall_strict_at_threshold": sc["recall_strict_by_operating_point"].get(name if name != "p0" else "p0_p1")}
    # With few clean scenarios the Poisson upper bound cannot fall below 1.0 unless there
    # is no P0-P2 unit at all (4 scenarios, 1 unit -> 1.39), so it is reported, not gated.
    ok = clean_scenarios > 0 and rows["p0_p1"]["clean_units"] == 0 and rows["p0_p2"]["per_clean_scenario"] <= 0.35
    return {"table": rows, "verdict": ("pass" if ok else "fail") if clean_scenarios else "not_run"}


def _rate(k: int, n: int) -> dict[str, Any]:
    lo, hi = bench.wilson(k, n) if n else (None, None)
    return {"k": k, "n": n, "rate": round(k / n, 3) if n else None, "ci95": [lo, hi]}


def breakdown(per_defect: list[dict[str, Any]], defects: list[dict[str, Any]]) -> dict[str, Any]:
    meta = {d["id"]: d for d in defects}
    out: dict[str, Any] = {}
    for field in ("category", "detectable_by", "audience_relevance"):
        groups: dict[str, list[bool]] = {}
        for d in per_defect:
            value = meta[d["id"]].get(field)
            for v in value if isinstance(value, list) else [value]:
                groups.setdefault(str(v), []).append(d["detected_strict"])
        out[field] = {g: _rate(sum(v), len(v)) for g, v in sorted(groups.items())}
    return out


def aggregate(sc: dict[str, Any], key: dict[str, Any]) -> dict[str, Any]:
    clean_n = len({c["scenario_id"] for c in key.get("clean_controls", [])}) or 1
    by_sev = sc["clean_control_units_by_severity"]
    detected = sum(d["detected_strict"] for d in sc["per_defect"])
    return {
        "recall_strict": _rate(detected, len(sc["per_defect"])),
        "recall_strict_by_operating_point": sc["recall_strict_by_operating_point"],
        "recall_strict_unconditioned": sc["recall_strict_unconditioned"],
        "condition_identified": sc["condition_identified"],
        "recall_condition_attributed": sc["recall_condition_attributed"],
        "conditioned_defects": sc["conditioned_defects"],
        "recall_lenient": sc["recall_lenient"],
        "severity_agreement": sc["severity_agreement"],
        "by": breakdown(sc["per_defect"], key["defects"]),
        "units": sc["units"],
        "matched_units": sc["matched_units"],
        "validity_lb_units": sc["validity_lb_units"],
        "precision_labelled_subset_units": sc["precision_labelled_subset_units"],
        "clean_control_units": sc["clean_control_units"],
        "clean_control_units_by_severity": by_sev,
        "clean_units_per_clean_scenario": {
            "p0_p1": round((by_sev["P0"] + by_sev["P1"]) / clean_n, 2),
            "p0_p2": round((by_sev["P0"] + by_sev["P1"] + by_sev["P2"]) / clean_n, 2),
            "all": round(sc["clean_control_units"] / clean_n, 2),
        },
        "decoy_units": sc["decoy_units"],
        "decoys_flagged": sc["decoys_flagged"],
        "unlabeled_units": sc["unlabeled_units"],
        "hypotheses_excluded": sc["hypotheses_excluded"],
    }


def _paired_diff(a: dict[str, float], b: dict[str, float], ids: list[str], seed: int = 7) -> dict[str, Any]:
    """Mean of a[d] - b[d] over defects with a paired bootstrap 95 % interval (resampling defects)."""
    if not ids:
        return {"diff": None, "ci95": [None, None], "n": 0}
    diffs = [a[i] - b[i] for i in ids]
    rng = random.Random(seed)
    boots = sorted(statistics.fmean(rng.choice(diffs) for _ in diffs) for _ in range(BOOTSTRAP))
    return {"diff": round(statistics.fmean(diffs), 3), "ci95": [round(boots[int(0.025 * BOOTSTRAP)], 3), round(boots[int(0.975 * BOOTSTRAP) - 1], 3)], "n": len(ids)}


def _verdict(point: float | None, ci: list[float | None], threshold: float) -> str:
    """Pre-registered rule: inconclusive when the interval overlaps the threshold."""
    if point is None or ci[0] is None:
        return "not_run"
    if ci[0] >= threshold:
        return "pass"
    if ci[1] < threshold:
        return "fail"
    return "inconclusive"


def hypotheses(scores: dict[str, dict[str, Any]], key: dict[str, Any]) -> dict[str, Any]:
    defects = key["defects"]
    ids = [d["id"] for d in defects]
    primary = [d["id"] for d in defects if d.get("audience_relevance") == "primary"]
    unconditioned = [d["id"] for d in defects if not d.get("profile_condition")]
    hit = {c: {d["id"]: float(d["detected_strict"]) for d in s["per_defect"]} for c, s in scores.items()}
    out: dict[str, Any] = {}

    semantic = [d["id"] for d in defects if d.get("category") in ("semantics", "layout")]
    out["H1"] = {c: _rate(int(sum(hit[c][i] for i in semantic)), len(semantic)) for c in ("C3", "C4@14") if c in hit}
    out["H1"].update({f"{c}_lenient": _rate(sum(1 for d in scores[c]["per_defect"] if d["id"] in semantic and d["detected_lenient"]), len(semantic))
                      for c in ("C3", "C4@14") if c in scores})
    out["H1"]["verdict"] = "reported"

    c5 = [c for c in hit if c.startswith("C5@10#")]
    if "C4@10" in hit and c5:
        c5_mean = {i: statistics.fmean(hit[c][i] for c in c5) for i in ids}
        prim = _paired_diff(hit["C4@10"], c5_mean, primary)
        overall = _paired_diff(hit["C4@10"], c5_mean, ids)
        v1 = _verdict(prim["diff"], prim["ci95"], 0.10)
        v2 = _verdict(overall["diff"], overall["ci95"], 0.0)
        verdict = "pass" if v1 == v2 == "pass" else ("fail" if "fail" in (v1, v2) else "inconclusive")
        out["H2"] = {"primary_minus_c5_mean": prim, "overall_minus_c5_mean": overall, "parts": [v1, v2], "verdict": verdict}
    else:
        out["H2"] = {"verdict": "not_run"}

    clean_scenarios = len({c["scenario_id"] for c in key.get("clean_controls", [])})
    if "C4@14" in hit and "C3" in hit:
        d = _paired_diff(hit["C4@14"], hit["C3"], ids)
        out["H3"] = {"c4_14_minus_c3": d, "verdict": _verdict(d["diff"], d["ci95"], -0.05)}
    else:
        out["H3"] = {"verdict": "not_run"}
    if "C4@14" in scores and clean_scenarios:
        by_sev = scores["C4@14"]["clean_control_units_by_severity"]
        p01 = (by_sev["P0"] + by_sev["P1"]) / clean_scenarios
        p02 = (by_sev["P0"] + by_sev["P1"] + by_sev["P2"]) / clean_scenarios
        out["H4"] = {"p0_p1_per_clean_scenario": round(p01, 2), "p0_p2_per_clean_scenario": round(p02, 2),
                     "verdict": "pass" if p01 <= 1 and p02 <= 5 else "fail"}
    else:
        out["H4"] = {"verdict": "not_run"}

    h5 = {}
    for c in ("C3", "C4@14"):
        if c not in scores:
            continue
        cond = [d for d in scores[c]["per_defect"] if d["profile_condition"]]
        if not cond:
            continue
        k = sum(1 for d in cond if d["differential_matches_condition"])
        r = _rate(k, len(cond))
        r["verdict"] = _verdict(r["rate"], r["ci95"], 0.5)
        h5[c] = r
    out["H5"] = h5
    out["H5"]["verdict"] = ("pass" if all(v["verdict"] == "pass" for v in h5.values()) else
                           "fail" if any(v["verdict"] == "fail" for v in h5.values()) else "inconclusive") if h5 else "not_run"

    if "C3" in hit and "C2" in hit and unconditioned:
        d7 = _paired_diff(hit["C3"], hit["C2"], unconditioned)
        out["H7"] = {"c3_minus_c2_unconditioned": d7, "verdict": _verdict(d7["diff"], d7["ci95"], 0.0)}
    else:
        out["H7"] = {"verdict": "not_run"}
    out["H6"] = {"verdict": "scored separately (persona agents, C6)"}
    return out


def confirmatory(scores: dict[str, dict[str, Any]], key: dict[str, Any], clean_n: int) -> dict[str, Any]:
    """EVD-03 fixed-sequence family (one-sided 0.025 each, via two-sided 95 % intervals):
    N -> H7' -> HA -> H3' -> H2'. Testing stops at the first hypothesis that does not
    pass; the rest are reported as descriptive."""
    defects = key["defects"]
    ids = [d["id"] for d in defects]
    det = {c: {d["id"]: bool(d["detected_strict"]) for d in sc["per_defect"]} for c, sc in scores.items()}
    steps: list[tuple[str, dict[str, Any]]] = []

    if "C4@14" in scores:
        steps.append(("N", noise_gate(scores["C4@14"], clean_n)))
    else:
        steps.append(("N", {"verdict": "not_run"}))

    uncond = [d["id"] for d in defects if not d.get("profile_condition")]
    if "C3" in det and "C2" in det and uncond:
        r = bench.newcombe_paired([det["C3"][i] for i in uncond], [det["C2"][i] for i in uncond])
        steps.append(("H7'", {**r, "rule": "lower >= -0.15 (margin set by power: n~22, no discordance -> 99 %)",
                              "verdict": "pass" if r["ci95"][0] is not None and r["ci95"][0] >= -0.15 else "fail"}))
    else:
        steps.append(("H7'", {"verdict": "not_run"}))

    if "C4@14" in scores:
        cond = [d for d in scores["C4@14"]["per_defect"] if d["profile_condition"] and d["detected_strict"]]
        k = sum(1 for d in cond if d["differential_matches_condition"])
        r = _rate(k, len(cond))
        steps.append(("HA", {**r, "rule": "Wilson lower >= 0.30 (condition identified among detected conditioned defects)",
                             "verdict": ("pass" if r["ci95"][0] >= 0.30 else "fail") if cond else "not_run"}))
    else:
        steps.append(("HA", {"verdict": "not_run"}))

    if "C4@14" in det and "C3" in det:
        r = bench.newcombe_paired([det["C4@14"][i] for i in ids], [det["C3"][i] for i in ids])
        steps.append(("H3'", {**r, "rule": "lower >= -0.20 (margin set by power: n~45, 10 % discordance each way -> 84 %)",
                              "verdict": "pass" if r["ci95"][0] is not None and r["ci95"][0] >= -0.20 else "fail"}))
    else:
        steps.append(("H3'", {"verdict": "not_run"}))

    primary = [d["id"] for d in defects if d.get("audience_relevance") == "primary"]
    if "C4@10" in det and "C4-swap@10" in det and primary:
        r = bench.newcombe_paired([det["C4@10"][i] for i in primary], [det["C4-swap@10"][i] for i in primary])
        ok = r["ci95"][0] is not None and r["ci95"][0] > 0 and r["diff"] >= 0.10
        floors = bench.newcombe_paired([det["C4@10"][i] for i in primary], [det["C4-floors@10"][i] for i in primary]) if "C4-floors@10" in det else None
        steps.append(("H2'", {**r, "vs_floors": floors, "rule": "C4@10 - C4-swap@10 on primary defects: lower > 0 and point >= +0.10",
                              "verdict": "pass" if ok else "fail"}))
    else:
        steps.append(("H2'", {"verdict": "not_run"}))

    out: dict[str, Any] = {}
    stopped = False
    for name, res in steps:
        if stopped:
            res = {**res, "confirmatory_status": "descriptive (sequence stopped earlier)"}
        else:
            res = {**res, "confirmatory_status": "tested"}
            stopped = res.get("verdict") != "pass"
        out[name] = res
    return out


SIT04_CONDITIONS = {"context.mobility": ("walking",), "motor.tremor": ("mild", "moderate"), "age_band": ("60s", "70s+")}


def _sit04_defect(d: dict[str, Any]) -> bool:
    for path, values in (d.get("profile_condition") or {}).items():
        allowed = SIT04_CONDITIONS.get(path)
        if allowed and any(v in allowed for v in (values if isinstance(values, list) else [values])):
            return True
    return False


def _only_on_units(on: dict[str, Any], off: dict[str, Any], clean_ids: set[str]) -> list[str]:
    """Clean-control units none of whose elements is flagged by the same check without the multipliers."""
    flagged_off = {(f["scenario_id"], f["check_id"], f["element_key"]) for f in off["_findings"] if f.get("tier") != "hypothesis"}
    return [u["id"] for u in swarm.units([f for f in on["_findings"] if f.get("tier") != "hypothesis"])
            if u["scenario_id"] in clean_ids and not any((u["scenario_id"], u["check_id"], e) in flagged_off for e in u["elements"])]


def sit04(scores: dict[str, dict[str, Any]], off_scores: dict[str, dict[str, Any]], key: dict[str, Any]) -> dict[str, Any]:
    """Amendment 4 (SIT-04), exploratory: cut the condition multipliers when, in both C3
    and C4@14, no defect conditioned on walking, tremor or age 60+ is detected with its
    condition named through PT-03/PT-04, and at least 3 clean-control units exist only
    with the multipliers on."""
    clean_ids = {c["scenario_id"] for c in key.get("clean_controls", [])}
    meta = {d["id"]: d for d in key["defects"]}
    out: dict[str, Any] = {"conditions": {k: list(v) for k, v in SIT04_CONDITIONS.items()}, "configs": {}}
    verdicts = []
    for c in ("C3", "C4@14"):
        if c not in scores or c not in off_scores:
            continue
        attributed = [d["id"] for d in scores[c]["per_defect"] if _sit04_defect(meta[d["id"]]) and d["detected_strict"]
                      and d["differential_matches_condition"] and set(d["matched_checks"]) & {"PT-03", "PT-04"}]
        only_on = _only_on_units(scores[c], off_scores[c], clean_ids)
        lost = [d["id"] for d, e in zip(scores[c]["per_defect"], off_scores[c]["per_defect"]) if d["detected_strict"] and not e["detected_strict"]]
        cut = not attributed and len(only_on) >= 3
        verdicts.append(cut)
        out["configs"][c] = {"conditioned_defects": sum(1 for d in key["defects"] if _sit04_defect(d)),
                             "attributed_via_pt03_pt04": len(attributed), "clean_units_only_with_multipliers": len(only_on),
                             "defects_lost_without_multipliers": len(lost), "cut_rule_holds": cut}
    out["verdict"] = ("cut" if verdicts and all(verdicts) else "keep") if verdicts else "not_run"
    return out


def score_all(data: dict[str, Any], out: Path, show_open: bool) -> dict[str, Any]:
    with (out / "analysis-cache.pickle").open("rb") as fh:
        cache = pickle.load(fh)
    key = data["key"]
    scores = {c: score_config(cache, key, c) for c in sorted(cache["configs"])}
    agg: dict[str, Any] = {"suite": data["suite"].name, "defects": len(key["defects"]), "decoys": len(key["decoys"]),
                           "clean_scenarios": len({c["scenario_id"] for c in key.get("clean_controls", [])}),
                           "products": sorted(data["keys"]), "provenance_analysis": cache["provenance"], "provenance_score": provenance(),
                           "run_health": {s: sum(1 for h in cache["health"] if h["status"] == s) for s in {h["status"] for h in cache["health"]}},
                           "configs": {}}
    for c, sc in scores.items():
        if c.startswith("C5@"):
            continue
        agg["configs"][c] = aggregate(sc, key)
    for budget in BUDGETS:
        seeds = [scores[c] for c in scores if c.startswith(f"C5@{budget}#")]
        if not seeds:
            continue
        rec = sorted(s["recall_strict"] for s in seeds)
        clean = [s["clean_control_units"] for s in seeds]
        lo = rec[int(0.025 * len(rec))]
        hi = rec[max(0, math.ceil(0.975 * len(rec)) - 1)]
        agg["configs"][f"C5@{budget}"] = {"seeds": len(seeds), "recall_strict_mean": round(statistics.fmean(rec), 3),
                                          "recall_strict_p2_5_p97_5": [round(lo, 3), round(hi, 3)],
                                          "recall_strict_min_max": [round(rec[0], 3), round(rec[-1], 3)],
                                          "clean_control_units_mean": round(statistics.fmean(clean), 2)}
    agg["hypotheses"] = hypotheses(scores, key)
    # Amendment 3 (EVD-01..06): baselines, twin discrimination, product clusters, noise
    # gate and the fixed-sequence confirmatory family. The original H1-H7 stay above.
    product_of = cache["product_of"]
    twin_of = twins(key, product_of)
    clean_n = agg["clean_scenarios"]
    for c, sc in scores.items():
        if c.startswith("C5@"):
            continue
        disc = bench.discrimination(key, sc["_findings"], sc["_profiles"], twin_of)
        agg["configs"][c]["discrimination"] = {k: v for k, v in disc.items() if k != "per_defect"}
        agg["configs"][c]["clusters"] = cluster_recall(sc["per_defect"], product_of)
        agg["configs"][c]["noise_gate"] = noise_gate(sc, clean_n)
        sc["_discrimination"] = disc
    pool = element_pool(out)
    baselines = {}
    if "C3" in scores:
        fa = flag_all(key, pool, cache["configs"]["C3"], product_of)
        fa_score = bench.score(key, fa, scores["C3"]["_profiles"], exact_viewport=True)
        baselines["flag_all"] = {"recall_strict": fa_score["recall_strict"], "recall_lenient": fa_score["recall_lenient"],
                                 "unreachable_defects": sum(1 for d in fa_score["per_defect"] if not d["detected_lenient"]),
                                 "clean_control_units": fa_score["clean_control_units"]}
        for c in ("C3", "C4@14"):
            if c in scores:
                baselines[f"chance_{c}"] = chance_recall(key, scores[c], pool)
    agg["baselines"] = baselines
    agg["confirmatory"] = confirmatory(scores, key, clean_n)
    off_path = out / VARIANTS["condition-multipliers-off"]
    if off_path.is_file():
        with off_path.open("rb") as fh:
            off_cache = pickle.load(fh)
        off_scores = {c: score_config(off_cache, key, c) for c in ("C3", "C4@14") if c in off_cache["configs"]}
        agg["sit04"] = sit04(scores, off_scores, key)
    (out / "aggregate.json").write_text(json.dumps(agg, ensure_ascii=False, indent=1), encoding="utf-8")
    sealed = out / "sealed"
    sealed.mkdir(exist_ok=True)
    for c, sc in scores.items():
        keep = {k: v for k, v in sc.items() if not k.startswith("_")}
        if "_discrimination" in sc:
            keep["discrimination_per_defect"] = sc["_discrimination"]["per_defect"]
        (sealed / f"score-{c.replace('#', '-s').replace('@', '-b')}.json").write_text(json.dumps(keep, ensure_ascii=False, indent=1), encoding="utf-8")
    if show_open:
        for c in ("C3", "C4@14"):
            if c in scores:
                missed = [d["id"] for d in scores[c]["per_defect"] if not d["detected_strict"]]
                agg.setdefault("open_missed", {})[c] = missed
    return agg


def _listify(value: Any) -> list[Any]:
    return value if isinstance(value, list) else [value]


def score_agents(data: dict[str, Any], agent_dir: Path) -> dict[str, Any]:
    """C6: persona-agent runs (serve mode) scored on ``agent_judgment`` defects.

    ``agent_dir`` holds ``runs/<run_id>/run.json`` and ``profiles.json`` (the composed
    operator profiles). Each run is analysed under its own profile only. PJ-01 units
    are hypotheses unless runs on another model family or input channel noted the
    same anchor (computed in swarm.aggregate). A judgment note has no category, so
    matching is lenient (scenario, selector, condition); strict matching is reported
    too. Aggregates only.
    """
    profiles = json.loads((agent_dir / "profiles.json").read_text(encoding="utf-8"))["profiles"]
    by_id = {p["profile_id"]: p for p in profiles}
    analyses, runs = [], []
    for run_dir in sorted(p for p in (agent_dir / "runs").iterdir() if (p / "run.json").is_file()):
        run_doc = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        own = by_id.get(run_doc["profile_id"])
        if own is None:
            continue
        try:
            result = analyze.analyze_run(run_dir, [own], data["scenarios"].get(run_doc["scenario_id"]), cross_profile=False)
        except Exception as err:  # noqa: BLE001 - a run that never took a snapshot is counted, not fatal
            runs.append({"success": False, "steps": 0, "health": "failed", "channel": (run_doc.get("agent") or {}).get("input_channel"),
                         "model": (run_doc.get("agent") or {}).get("model"), "notes": 0, "confusion": 0,
                         "failure_class": {c: 0 for c in ("ux_issue", "agent_limitation", "environment", "unknown")}, "error": str(err)[:200]})
            continue
        result["observations"] = [_lean(o) for o in result["observations"]]
        analyses.append(result)
        notes = run_doc.get("persona_notes") or []
        runs.append({"success": run_doc.get("success"), "steps": len(run_doc.get("steps") or []), "health": result.get("health"),
                     "channel": (run_doc.get("agent") or {}).get("input_channel"), "model": (run_doc.get("agent") or {}).get("model"),
                     "notes": len(notes), "confusion": sum(1 for n in notes if n.get("confusion")),
                     "failure_class": {c: sum(1 for n in notes if n.get("confusion") and n.get("failure_class") == c)
                                       for c in ("ux_issue", "agent_limitation", "environment", "unknown")}})
    findings = swarm.aggregate(analyses, profiles)
    key = data["key"]
    covered = {a["scenario_id"] for a in analyses}
    products = {data["product_of"].get(sid) for sid in covered}
    judgment = [d for d in key["defects"] if "agent_judgment" in _listify(d.get("detectable_by")) and data["product_of"].get(d["scenario_id"]) in products]
    subkey = {**key, "defects": judgment, "clean_controls": [c for c in key.get("clean_controls", []) if c["scenario_id"] in covered],
              "decoys": [d for d in key.get("decoys", []) if data["product_of"].get(d["scenario_id"]) in products]}
    pj = [f for f in findings if f["check_id"] == "PJ-01"]
    out: dict[str, Any] = {"runs": len(runs), "products": sorted(p for p in products if p), "agent_judgment_defects": len(judgment),
                           "by_model_channel": {f"{m}/{c}": sum(1 for r in runs if r.get("model") == m and r.get("channel") == c)
                                                for m in ("opus", "sonnet") for c in ("screenshot", "screenshot+a11y")},
                           "task_success_rate": round(sum(1 for r in runs if r["success"]) / len(runs), 3) if runs else None,
                           "steps_mean": round(statistics.fmean(r["steps"] for r in runs), 1) if runs else None,
                           "confusion_notes": sum(r["confusion"] for r in runs),
                           "confusion_by_class": {c: sum(r["failure_class"][c] for r in runs) for c in ("ux_issue", "agent_limitation", "environment", "unknown")},
                           "run_health": {s: sum(1 for r in runs if r["health"] == s) for s in {r["health"] for r in runs}}}
    for name, fs, include in (("pj_corroborated", pj, False), ("pj_including_hypotheses", pj, True), ("all_checks_on_agent_runs", findings, False)):
        sc = bench.score(subkey, fs, profiles, exact_viewport=True, include_hypotheses=include)
        lenient = sum(d["detected_lenient"] for d in sc["per_defect"])
        strict = sum(d["detected_strict"] for d in sc["per_defect"])
        clean_n = len({c["scenario_id"] for c in subkey.get("clean_controls", [])}) or 1
        out[name] = {"recall_lenient": _rate(lenient, len(judgment)), "recall_strict": _rate(strict, len(judgment)),
                     "units": sc["units"], "clean_control_units": sc["clean_control_units"],
                     "clean_units_per_clean_scenario": round(sc["clean_control_units"] / clean_n, 2), "unlabeled_units": sc["unlabeled_units"]}
    hyp = out["pj_corroborated"]["recall_lenient"]
    out["H6"] = {"threshold": 0.30, "verdict": _verdict(hyp["rate"], hyp["ci95"], 0.30),
                 "note": "the clean-scenario part (<= 1 invalid corroborated PJ-01 unit per clean scenario) needs round-2 adjudication"}
    sealed = agent_dir / "sealed"
    sealed.mkdir(exist_ok=True)
    (sealed / "c6-findings.json").write_text(json.dumps({"findings": findings}, ensure_ascii=False, indent=1), encoding="utf-8")
    (agent_dir / "aggregate-c6.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def agents_plan(data: dict[str, Any], agent_dir: Path, budget: int, sessions_per_profile: str = "both") -> dict[str, Any]:
    """Operator profiles and sessions for C6 (persona agents in serve mode).

    Profiles come from ``audience.compose`` (budget per product), or, for a product
    without an audience file, from stratified sampling on the scenarios' devices.
    Input channels alternate (screenshot, screenshot+a11y) so notes can be
    corroborated across channels under a one-family rule; operator models alternate
    between Opus and Sonnet in pairs. Every profile runs every
    scenario of its product in a separate session. Writes ``profiles.json``,
    ``agents/*.json`` and ``sessions.json``; no scenario content is read here
    beyond ids and devices.
    """
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "agents").mkdir(exist_ok=True)
    (agent_dir / "profiles").mkdir(exist_ok=True)
    products: dict[str, list[str]] = {}
    for sid, slug in data["product_of"].items():
        if sid in data["scenarios"]:
            products.setdefault(slug, []).append(sid)
    profiles, sessions = [], []
    port = 9500
    for slug, sids in sorted(products.items()):
        doc = data["audiences"].get(slug)
        if doc is not None:
            chosen = audience.compose(doc, budget)["profiles"]
            origin = "audience"
        else:
            devices = sorted({d for sid in sids for d in data["scenarios"][sid]["device_ids"]})
            chosen = sample_profiles(budget, 11, devices)
            origin = "stratified"
        for i, prof in enumerate(chosen):
            prof = dict(prof)
            prof["profile_id"] = f"OP-{slug}-{i + 1:02d}@{prof['attributes']['device_id']}"
            # Channels alternate every profile, models every two profiles, so four
            # profiles cover {opus, sonnet} x {screenshot, screenshot+a11y}. Both models
            # are one family: corroboration still needs another input channel.
            channel = "screenshot" if i % 2 == 0 else "screenshot+a11y"
            model = "opus" if (i // 2) % 2 == 0 else "sonnet"
            # The operator workflow runs every session at effort max; the record says so,
            # so reports name the model and effort actually used.
            agent = {"model_family": "claude", "model": model, "effort": "max", "input_channel": channel, "persona_arm": "full", "seed": i + 1,
                     "description": f"C6 operator {slug} {i + 1} ({origin})"}
            (agent_dir / "profiles" / f"{prof['profile_id']}.json").write_text(json.dumps(prof, ensure_ascii=False), encoding="utf-8")
            (agent_dir / "agents" / f"{prof['profile_id']}.json").write_text(json.dumps(agent, ensure_ascii=False), encoding="utf-8")
            profiles.append(prof)
            for sid in sorted(sids):
                sessions.append({"product": slug, "scenario_id": sid, "scenario_path": str(data["paths"][sid]),
                                 "profile_path": str(agent_dir / "profiles" / f"{prof['profile_id']}.json"),
                                 "agent_json": str(agent_dir / "agents" / f"{prof['profile_id']}.json"),
                                 "run_id": f"R-{sid}-{prof['profile_id'].split('@')[0]}", "port": port, "channel": channel, "model": model,
                                 "label_ko": prof.get("label_ko") or ""})
                port += 1
    (agent_dir / "profiles.json").write_text(json.dumps({"profiles": profiles}, ensure_ascii=False, indent=1), encoding="utf-8")
    (agent_dir / "sessions.json").write_text(json.dumps(sessions, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"profiles": len(profiles), "sessions": len(sessions), "by_channel": {c: sum(1 for x in sessions if x["channel"] == c) for c in ("screenshot", "screenshot+a11y")},
            "by_model": {m: sum(1 for x in sessions if x["model"] == m) for m in ("opus", "sonnet")}}


def main() -> int:
    global C5_SEEDS
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("record", "analyse", "score", "plan", "score-agents", "agents-plan"):
        p = sub.add_parser(name)
        p.add_argument("--suite", required=True, type=Path)
        p.add_argument("--out", required=True, type=Path, help="work folder (score-agents: the agent-run folder with runs/ and profiles.json)")
        p.add_argument("--c5-seeds", type=int, default=C5_SEEDS, help="pre-registered: 20; fewer only for pipeline tests")
        if name == "score":
            p.add_argument("--open", action="store_true", help="also list per-defect misses (development suites only)")
        if name == "agents-plan":
            p.add_argument("--budget", type=int, default=4, help="operator profiles per product (pre-registered: 4)")
        if name == "analyse":
            p.add_argument("--variant", choices=sorted(VARIANTS), help="re-analyse under a model variant (amendment 4: condition-multipliers-off)")
    args = parser.parse_args()
    C5_SEEDS = args.c5_seeds
    data = load_suite(args.suite.resolve())
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    if args.cmd == "plan":
        configs, registry, groups_of, notes = configurations(data)
        print(json.dumps({"configs": {c: {prod: len(ids) for prod, ids in v.items()} for c, v in configs.items() if not c.startswith("C5@") or c.endswith("#0")},
                          "distinct_profiles": len(registry), "recordings": sum(len(g) for g in groups_of.values()), "notes": notes}, indent=1))
    elif args.cmd == "record":
        record(data, out)
    elif args.cmd == "analyse":
        analyse_all(data, out, args.variant)
    elif args.cmd == "agents-plan":
        print(json.dumps(agents_plan(data, out, args.budget), indent=1))
    elif args.cmd == "score-agents":
        print(json.dumps(score_agents(data, out), ensure_ascii=False, indent=1))
    else:
        agg = score_all(data, out, args.open)
        print(json.dumps({k: v for k, v in agg.items() if k not in ("provenance_analysis", "provenance_score")}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
