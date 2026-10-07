"""W3C ACT rule examples as a precision gate for the semantics and layout checks.

ACT rules (https://www.w3.org/WAI/standards-guidelines/act/rules/) ship
human-written examples labelled Passed, Failed and Inapplicable. An
implementation is correct for a rule when no Passed or Inapplicable example is
reported as failing (ACT "Mapping to rule"). This script opens every example of the
mapped rules in the real web driver, analyses it with the default persona, and
reports per rule:

- false alarms: Passed or Inapplicable examples where the mapped check fired
  (the gate: any false alarm fails the run, exit 1);
- detection: Failed examples where the mapped check fired (reported only).

    python3 skills/remorsearch-ux-qa/scripts/ergo_act.py --out .ergo-bench/act
    python3 skills/remorsearch-ux-qa/scripts/ergo_act.py --out .ergo-bench/act-640 --viewport 640x512

59br37 is defined at a 640 x 512 viewport (1280 x 1024 zoomed 200 %); --viewport
runs the examples on a mouse desktop of that size instead of a catalog device. LY-01
findings the page marks as cut cleanly (act_59br37 "passed": 59br37's own
exceptions, reported at P3 as truncation notes) are listed as notes, not false alarms.

The rule files and their test assets are downloaded from
https://github.com/act-rules/act-rules.github.io at a pinned commit (ACT_REF) into
the output folder; nothing is vendored into this repository. Use --rules-dir to run
on a local copy instead. The examples are written by the ACT task force, not by
this tool's authors, so this is an external check of precision that the
Claude-written benchmarks cannot give.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from ergoqa import analyze  # noqa: E402

from ergo_bench import default_profile, static_server  # noqa: E402

# ACT rule id -> (checks that implement it, counts toward the gate)
RULES: dict[str, tuple[tuple[str, ...], bool]] = {
    "97a4e1": (("SM-01",), True),   # Button has non-empty accessible name
    "c487ae": (("SM-01",), True),   # Link has non-empty accessible name
    "e086e5": (("SM-03",), True),   # Form field has non-empty accessible name
    "2ee8b8": (("SM-02",), True),   # Visible label is part of accessible name
    "59br37": (("LY-01",), True),   # Zoomed text node is not clipped with CSS overflow
    "oj04fd": (("SM-05",), True),   # Element in sequential focus order has visible focus
    "36b590": (("SM-04",), False),  # Error message describes invalid form field value (informational)
}
HEADING = re.compile(r"^#### (Passed|Failed|Inapplicable) Example (\d+)\s*$")
ACT_REPO = "act-rules/act-rules.github.io"
ACT_REF = "7e46818df12a867b094514f82199cc88dcaae6c0"  # develop, 2026-09-28
RULE_FILES = {
    "97a4e1": "button-non-empty-accessible-name-97a4e1.md",
    "c487ae": "link-non-empty-accessible-name-c487ae.md",
    "e086e5": "form-field-non-empty-accessible-name-e086e5.md",
    "2ee8b8": "visible-label-in-accessible-name-2ee8b8.md",
    "59br37": "zoom-text-no-overflow-clipping-59br37.md",
    "oj04fd": "sequentially-focusable-element-has-visible-focus-oj04fd.md",
    "36b590": "invalid-form-field-value-36b590.md",
}


def _raw(path: str) -> bytes | None:
    import urllib.request

    url = f"https://raw.githubusercontent.com/{ACT_REPO}/{ACT_REF}/{path}"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            return resp.read()
    except Exception:  # noqa: BLE001 - a missing asset is reported, not fatal
        return None


def fetch_rules(dest: Path, rule_ids: list[str]) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    for rid in rule_ids:
        f = dest / RULE_FILES[rid]
        if not f.is_file():
            data = _raw(f"_rules/{RULE_FILES[rid]}")
            if data is None:
                raise SystemExit(f"cannot download _rules/{RULE_FILES[rid]} at {ACT_REF}")
            f.write_bytes(data)
    return dest


def fetch_assets(html: str, site: Path, cache: Path) -> None:
    """Download the /test-assets/... files an example references (images, styles)."""
    for path in set(re.findall(r"""["'(](/test-assets/[^"')\s]+)""", html)):
        target = site / path.lstrip("/")
        if target.exists():
            continue
        cached = cache / path.lstrip("/")
        if not cached.exists():
            data = _raw(path.lstrip("/"))
            if data is None:
                continue
            cached.parent.mkdir(parents=True, exist_ok=True)
            cached.write_bytes(data)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(cached.read_bytes())


def parse_rule(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    rule_id = re.search(r"^id:\s*(\S+)", text, re.M).group(1)
    examples, current, block, lang = [], None, None, None
    for line in text.splitlines():
        m = HEADING.match(line)
        if m:
            current = {"kind": m.group(1).lower(), "n": int(m.group(2)), "html": None}
            examples.append(current)
            continue
        if block is None and current is not None and current["html"] is None and line.startswith("```"):
            lang = line[3:].strip()
            block = []
            continue
        if block is not None:
            if line.startswith("```"):
                if current is not None and lang in ("html", ""):
                    current["html"] = "\n".join(block)
                block = None
            else:
                block.append(line)
    return {"id": rule_id, "file": path.name, "sha256": hashlib.sha256(text.encode()).hexdigest(),
            "examples": [e for e in examples if e["html"]]}


def page_for(html: str) -> str:
    if re.search(r"<html[\s>]", html, re.I):
        return html
    return f'<!doctype html>\n<html lang="en">\n<head><meta charset="utf-8"><title>ACT example</title></head>\n<body>\n{html}\n</body>\n</html>\n'


def run_example(work: Path, base: str, device: str, name: str, device_json: Path | None = None) -> dict[str, Any]:
    scenario = {"schema_version": "ergo-scenario.v1", "scenario_id": f"SC-act-{name}", "surface": {"kind": "web", "url": f"{{BASE}}/site/{name}.html"},
                "task_goal_ko": "ACT 예제를 연다", "device_ids": [device], "targets": {}, "steps": [{"action": "wait", "ms": 150}],
                "success": {"url_contains": name}}
    sc_path = work / "scenarios" / f"{name}.json"
    sc_path.write_text(json.dumps(scenario, ensure_ascii=False), encoding="utf-8")
    profile = default_profile(device, "landscape" if device in ("desktop-1920", "laptop-1440") else "portrait")
    profile["profile_id"] = f"EP-ACT-{device}"
    p_path = work / "profiles" / f"{device}.json"
    if not p_path.exists():
        p_path.write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")
    cmd = ["node", str(ROOT / "drivers/web/ergo_drive.mjs"), "run", "--scenario", str(sc_path), "--profile", str(p_path),
           "--out", str(work / "runs"), "--run-id", f"R-{name}", "--base", base, "--focus-walk", "--timeout-s", "120"]
    if device_json is not None:
        cmd += ["--device-json", str(device_json)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    run_dir = work / "runs" / f"R-{name}"
    if not (run_dir / "run.json").is_file():
        return {"name": name, "error": f"driver exit {proc.returncode}: {proc.stderr[-300:]}"}
    try:
        result = analyze.analyze_run(run_dir, [profile], scenario, cross_profile=False)
    except Exception as err:  # noqa: BLE001
        return {"name": name, "error": f"analysis: {err}"}
    failing = [o for o in result["observations"] if not o["passed"]]
    clean = [o for o in failing if o["check_id"] == "LY-01" and (o.get("measurement") or {}).get("act_59br37") == "passed"]
    fired = sorted({(o["check_id"], o["element_key"], o["severity"]) for o in failing if o not in clean})
    notes = sorted({(o["check_id"], o["element_key"], o["severity"]) for o in clean})
    return {"name": name, "fired": fired, "notes": notes}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rules-dir", type=Path, default=None, help="local folder with ACT rule .md files (default: download at ACT_REF)")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--device", default="desktop-1920")
    ap.add_argument("--viewport", default=None, help="WxH: a mouse desktop of this CSS size instead of --device (59br37: 640x512)")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--rules", default=",".join(RULES), help="comma-separated ACT rule ids")
    args = ap.parse_args()
    wanted = [r for r in args.rules.split(",") if r in RULES]
    args.out.mkdir(parents=True, exist_ok=True)
    rules_dir = args.rules_dir or fetch_rules(args.out / f"act-rules-{ACT_REF[:7]}", wanted)
    rules = []
    for f in sorted(rules_dir.glob("*.md")):
        head = f.read_text(encoding="utf-8")[:400]
        m = re.search(r"^id:\s*(\S+)", head, re.M)
        if m and m.group(1) in wanted:
            rules.append(parse_rule(f))
    if not rules:
        print("no mapped ACT rule files found", file=sys.stderr)
        return 2
    args.out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ergo-act-") as tmp:
        work = Path(tmp)
        for sub in ("site", "scenarios", "profiles", "runs"):
            (work / sub).mkdir()
        jobs = []
        for rule in rules:
            for ex in rule["examples"]:
                name = f"{rule['id']}-{ex['kind']}-{ex['n']}"
                (work / "site" / f"{name}.html").write_text(page_for(ex["html"]), encoding="utf-8")
                fetch_assets(ex["html"], work, args.out / "assets-cache")
                jobs.append((rule, ex, name))
        device_json = None
        if args.viewport:
            m = re.fullmatch(r"(\d+)x(\d+)", args.viewport)
            if not m:
                print("--viewport must look like 640x512", file=sys.stderr)
                return 2
            device_json = work / "profiles" / "viewport-device.json"
            device_json.write_text(json.dumps({"id": f"act-{args.viewport}", "form_factor": "desktop", "viewport_css": [int(m.group(1)), int(m.group(2))],
                                               "dpr": 1.0, "input": "mouse", "playwright_device": None}), encoding="utf-8")
        with static_server(work) as base, ThreadPoolExecutor(max_workers=args.workers) as pool:
            results = list(pool.map(lambda j: run_example(work, base, args.device, j[2], device_json), jobs))
    by_name = {r["name"]: r for r in results}
    report: dict[str, Any] = {"device": args.device, "viewport": args.viewport, "act_ref": ACT_REF if args.rules_dir is None else None, "rules": {}, "gate_failures": 0, "errors": []}
    for rule in rules:
        checks_, gate = RULES[rule["id"]]
        row = {"file": rule["file"], "sha256": rule["sha256"], "checks": list(checks_), "gate": gate,
               "passed": 0, "inapplicable": 0, "failed": 0, "false_alarms": [], "detected": [], "missed": [], "notes": []}
        for ex in rule["examples"]:
            name = f"{rule['id']}-{ex['kind']}-{ex['n']}"
            res = by_name[name]
            row[ex["kind"]] += 1
            if "error" in res:
                report["errors"].append(res)
                continue
            hits = [f for f in res["fired"] if f[0] in checks_]
            if res.get("notes"):
                row["notes"].append({"example": name, "notes": res["notes"]})
            if ex["kind"] in ("passed", "inapplicable") and hits:
                row["false_alarms"].append({"example": name, "fired": hits})
            elif ex["kind"] == "failed":
                (row["detected"] if hits else row["missed"]).append(name)
        if gate:
            report["gate_failures"] += len(row["false_alarms"])
        report["rules"][rule["id"]] = row
    (args.out / "act-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    for rid, row in report["rules"].items():
        print(f"{rid} {','.join(row['checks'])}: false alarms {len(row['false_alarms'])}/{row['passed'] + row['inapplicable']}, "
              f"detected {len(row['detected'])}/{row['failed']}" + (f", truncation notes {len(row['notes'])}" if row["notes"] else "")
              + ("" if row["gate"] else " (informational)"))
        for fa in row["false_alarms"]:
            print(f"   FALSE ALARM {fa['example']}: {fa['fired']}")
    if report["errors"]:
        print(f"errors: {len(report['errors'])}")
    print(f"gate: {'FAIL' if report['gate_failures'] else 'pass'} ({report['gate_failures']} false alarms)")
    return 1 if report["gate_failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
