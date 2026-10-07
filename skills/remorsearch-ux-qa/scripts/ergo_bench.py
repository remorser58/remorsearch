#!/usr/bin/env python3
"""Run a benchmark suite end to end on the real browser and score it blind.

    python3 skills/remorsearch-ux-qa/scripts/ergo_bench.py --suite benchmarks/mobile-commerce --out .ergo-bench/mobile

For each scenario and device the web driver records one scripted run in
Chromium (real touch/mouse events). The run is analysed under every ergonomic
profile on that device (cross-profile), findings are aggregated, and the suite's
answer key is used only for scoring. Three configurations are compared:

- ``measured_only``: only measured checks (what a standard automated
  accessibility/QA scan reports);
- ``single_profile``: one default persona (30s, right-handed, one-hand grip,
  normal vision, seated) with all checks;
- ``swarm``: the stratified-coverage profile swarm with all checks.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import functools
import http.server
import json
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ergoqa import analyze, bench, checks, report, swarm  # noqa: E402
from ergoqa.devices import get_device  # noqa: E402
from ergoqa.profiles import _finalise, label_ko, sample_profiles  # noqa: E402


def _free_port() -> int:
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextlib.contextmanager
def static_server(directory: Path):
    port = _free_port()
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))

    class Quiet(handler.func):  # type: ignore[misc,valid-type]
        def log_message(self, *args: Any) -> None:  # noqa: D401
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), functools.partial(Quiet, directory=str(directory)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()


def default_profile(device_id: str, orientation: str) -> dict[str, Any]:
    device = get_device(device_id)
    touch = device.input == "touch"
    grip = ("two_thumbs" if orientation == "landscape" else "one_hand_right") if touch else ("mouse_right" if device.input == "mouse" else "keyboard_only")
    profile = {
        "schema_version": "ergo-profile.v1",
        "profile_id": f"EP-BASE-{device_id}",
        "origin": "manual",
        "persona_ref": None,
        "label_ko": "",
        "attributes": {
            "age_band": "30s", "handedness": "right", "grip": grip, "thumb_length_mm": 0, "hand_percentile": 50,
            "device_id": device_id, "orientation": orientation,
            "vision": {"acuity": "normal", "presbyopia": False, "cvd": "none", "cvd_severity": 1.0, "viewing_distance_mm": 0},
            "motor": {"tremor": "none", "touch_sigma_multiplier": 1.0, "touch_sigma_mm": 0.0},
            "context": {"mobility": "seated", "lighting": "indoor", "free_hands": 1 if touch else 2, "interruptions": False},
            "cognition": {"familiarity": "returning", "time_pressure": "low", "reading_wpm_ko": 0},
            "reaction_time_ms": 0,
        },
        "assumption_fields": [],
        "base_rate_refs": {},
    }
    return _finalise(profile, device)


def record(scenario_path: Path, scenario: dict[str, Any], profile: dict[str, Any], runs_dir: Path, base: str, work: Path) -> dict[str, Any]:
    run_id = f"R-{scenario['scenario_id']}-{profile['attributes']['device_id']}"
    profile_path = work / "profiles" / f"{profile['profile_id']}-{profile['attributes']['device_id']}.json"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")
    cmd = ["node", str(ROOT / "drivers/web/ergo_drive.mjs"), "run", "--scenario", str(scenario_path), "--profile", str(profile_path),
           "--out", str(runs_dir), "--run-id", run_id, "--base", base, "--continue-on-error"]
    if scenario.get("surface", {}).get("kind") == "game":
        cmd += ["--flash-sample-ms", "1500"]
    started = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1200)
    return {"run_id": run_id, "scenario_id": scenario["scenario_id"], "exit": proc.returncode, "seconds": round(time.time() - started, 1),
            "stderr_tail": proc.stderr[-600:], "run_dir": str(runs_dir / run_id)}


def evaluate(run_records: list[dict[str, Any]], profiles: list[dict[str, Any]], scenarios: dict[str, dict[str, Any]],
             key: dict[str, Any], mode: str, bases: dict[str, dict[str, Any]]) -> dict[str, Any]:
    analyses = []
    for rec in run_records:
        run_dir = Path(rec["run_dir"])
        if not (run_dir / "run.json").is_file():
            continue
        run_doc = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        scenario = scenarios.get(run_doc["scenario_id"])
        if mode == "swarm":
            analyses.append(analyze.analyze_run(run_dir, profiles, scenario, cross_profile=True))
        else:
            own = next(p for p in profiles if p["profile_id"] == run_doc["profile_id"])
            base = bases[f"{own['attributes']['device_id']}|{own['attributes']['orientation']}"]
            result = analyze.analyze_run(run_dir, [own, base], scenario, cross_profile=True)
            result["observations"] = [o for o in result["observations"] if o["profile_id"] == base["profile_id"]]
            if mode == "measured_only":
                result["observations"] = [o for o in result["observations"] if o["basis"] == "measured"]
            result["profiles_evaluated"] = [base["profile_id"]]
            analyses.append(result)
    used = profiles if mode == "swarm" else list(bases.values())
    findings = swarm.aggregate(analyses, used)
    scored = bench.score(key, findings, used) if key else None
    return {"analyses": analyses, "findings": findings, "score": scored, "profiles": used}


def provenance() -> dict[str, Any]:
    """Detector/scorer identity: commit, dirty flag and a hash of the code that scored."""
    import hashlib

    def git(*args: str) -> str:
        try:
            return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=20).stdout.strip()
        except Exception:  # noqa: BLE001 - provenance is best effort
            return ""

    digest = hashlib.sha256()
    for path in sorted((ROOT / "ergoqa").rglob("*.py")) + [ROOT / "scripts" / "ergo_bench.py"]:
        digest.update(path.relative_to(ROOT).as_posix().encode())
        digest.update(path.read_bytes())
    return {"commit": git("rev-parse", "HEAD"), "dirty": bool(git("status", "--porcelain", "--", "ergoqa", "scripts", "drivers")),
            "code_sha256": digest.hexdigest()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--suite", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--profiles-per-device", type=int, default=14)
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument("--reuse-runs", action="store_true", help="skip recording when run.json already exists")
    args = parser.parse_args()

    suite = args.suite.resolve()
    work = args.out.resolve()
    runs_dir = work / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    scenario_files = sorted((suite / "scenarios").glob("*.json"))
    scenarios = {}
    paths = {}
    for f in scenario_files:
        doc = json.loads(f.read_text(encoding="utf-8"))
        scenarios[doc["scenario_id"]] = doc
        paths[doc["scenario_id"]] = f
    key_path = suite / "answer_key.json"
    key = json.loads(key_path.read_text(encoding="utf-8")) if key_path.is_file() else None

    groups: dict[str, list[dict[str, Any]]] = {}
    bases: dict[str, dict[str, Any]] = {}
    profiles: list[dict[str, Any]] = []
    for sid, sc in scenarios.items():
        for device_id in sc["device_ids"]:
            orientation = sc.get("orientation") or get_device(device_id).orientation
            gk = f"{device_id}|{orientation}"
            if gk not in groups:
                device = get_device(device_id)
                count = args.profiles_per_device if device.input == "touch" else max(6, args.profiles_per_device // 2)
                sampled = sample_profiles(count, args.seed, [device_id], orientation=orientation)
                prefix = f"{device_id}-{orientation[0]}"
                for p in sampled:
                    p["profile_id"] = f"{p['profile_id']}@{prefix}"
                groups[gk] = sampled
                profiles.extend(sampled)
                bases[gk] = default_profile(device_id, orientation)
    (work / "profiles.json").write_text(json.dumps({"profiles": profiles}, ensure_ascii=False, indent=1), encoding="utf-8")

    run_records = []
    with static_server(suite.parent) as base:
        for sid, sc in scenarios.items():
            for device_id in sc["device_ids"]:
                orientation = sc.get("orientation") or get_device(device_id).orientation
                recorder = groups[f"{device_id}|{orientation}"][0]
                run_id = f"R-{sid}-{device_id}"
                if args.reuse_runs and (runs_dir / run_id / "run.json").is_file():
                    run_records.append({"run_id": run_id, "scenario_id": sid, "exit": None, "run_dir": str(runs_dir / run_id), "reused": True})
                    continue
                if (runs_dir / run_id).exists():
                    import shutil
                    shutil.rmtree(runs_dir / run_id)
                rec = record(paths[sid], sc, recorder, runs_dir, base, work)
                print(f"recorded {run_id}: exit {rec['exit']} in {rec['seconds']}s", flush=True)
                run_records.append(rec)

    results = {}
    for mode in ("measured_only", "single_profile", "swarm"):
        res = evaluate(run_records, profiles, scenarios, key, mode, bases)
        results[mode] = res
        (work / f"findings-{mode}.json").write_text(json.dumps({"findings": res["findings"]}, ensure_ascii=False, indent=1), encoding="utf-8")
        if res["score"]:
            (work / f"score-{mode}.json").write_text(json.dumps(res["score"], ensure_ascii=False, indent=1), encoding="utf-8")
    swarm_res = results["swarm"]
    (work / "report.md").write_text(report.render(swarm_res["findings"], profiles, swarm_res["analyses"], title=f"벤치마크 {suite.name}"), encoding="utf-8")

    summary = {"suite": suite.name, "provenance": provenance(), "runs": [{k: v for k, v in r.items() if k != "stderr_tail"} for r in run_records],
               "run_failures": [r for r in run_records if r.get("exit") not in (0, 3, None)]}
    for mode, res in results.items():
        sc = res["score"] or {}
        summary[mode] = {k: v for k, v in sc.items() if not isinstance(v, (list, dict))}
        summary[mode]["findings"] = len(res["findings"])
        summary[mode]["severity_counts"] = swarm.severity_counts(res["findings"])
    if key:
        single = {d["id"] for d in results["single_profile"]["score"]["per_defect"] if d["detected_strict"]}
        swarm_detected = {d["id"] for d in results["swarm"]["score"]["per_defect"] if d["detected_strict"]}
        measured = {d["id"] for d in results["measured_only"]["score"]["per_defect"] if d["detected_strict"]}
        summary["swarm_gain_over_single"] = sorted(swarm_detected - single)
        summary["swarm_gain_over_measured"] = sorted(swarm_detected - measured)
        summary["missed_by_swarm"] = sorted({d["id"] for d in results["swarm"]["score"]["per_defect"]} - swarm_detected)
    (work / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "runs"}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
