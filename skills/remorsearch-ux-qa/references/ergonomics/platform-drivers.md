# Platform Drivers

Every finding must come from the real surface. Drivers measure; they never score
ergonomics or role-play a user. All of them emit `ergo-snapshot.v1` /
`ergo-run.v1` (`docs/ergonomic-swarm-spec.md`), so `scripts/ergo_qa.py` analyses
them the same way.
These are repository documents, not installed with the skill.

| Surface | Path | What is real | What is not exercised here |
| --- | --- | --- | --- |
| Web, mobile web, browser games (canvas/WebGL) | `drivers/web/ergo_drive.mjs` (Node 22 + Playwright/Chromium) | Real touch/mouse/keyboard input (CDP), device-emulated viewport/DPR/touch, screenshots, DOM geometry and composited colours, feedback latency, 16 ms timing-window polling, flash sampling, off-origin network blocking | WebKit/Safari, real phones, on-screen keyboards, browser chrome, iframes/closed shadow roots |
| Android apps | `adb exec-out uiautomator dump` + `adb exec-out screencap -p` → `scripts/ergo_qa.py android-snapshot`; inputs via `ergoqa/drivers/android.py` argv builders | Real device geometry (bounds in px → dp) and screenshots when run against a device/emulator | Live device execution is not exercised in this repository (fixture-tested only) |
| iOS apps, desktop apps, engine-rendered games | Platform screenshot + vision/human annotation → `ergoqa/drivers/annotation.py` | Screenshots from the real device | Geometry is estimated (`source: vision`), so every geometry-based observation is `inferred` |

## Web driver quick reference

```sh
# Scripted scenario
node drivers/web/ergo_drive.mjs run --scenario sc.json --profile ep.json --out runs/ \
  --base http://127.0.0.1:8765 [--flash-sample-ms 1500]

# Interactive session for a persona agent (127.0.0.1 only)
node drivers/web/ergo_drive.mjs serve --scenario sc.json --profile ep.json --agent-json agent.json --out runs/ --port 9477
curl -s localhost:9477/snapshot
curl -s -X POST localhost:9477/act  -d '{"action":"tap","target":"#pay"}'
curl -s -X POST localhost:9477/note -d '{"step_index":1,"intent":"…","expected":"…","observed":"…","confusion":false,"failure_class":"ux_issue"}'
curl -s -X POST localhost:9477/finish -d '{"success":true}'

# Self-test (~1 minute)
node drivers/web/selftest.mjs
```

Scenario notes:

- `surface.kind` is `web` or `game` (browser game). Canvas controls are exposed
  with `scenario.hotspots` or `window.__ergoqa__.hotspots()`; roles such as
  `game_control`, `hud`, `timed` come from the scenario, never guessed.
- Declare `timing_windows` with `kind: "transient_text"` (toasts) or
  `kind: "qte"` (timed inputs). Undeclared kinds are inferred: a window the run
  acted on, or a short interactive/timed game prompt, is a timed input; a window
  with a readable message is transient text; others are decorative. Windows
  that toggle repeatedly are screened as flash sources (WCAG 2.3.1) from the
  16 ms DOM poll, because frame sampling (~30 fps) aliases fast flashes.
- Each snapshot also stores a CSS-scale copy of the screenshot
  (`screenshot.css`) for fast analysis, and each element lists up to three
  ancestor ids (`ancestor_ids`) so grouped controls (toolbars, chip rows) can be
  reported by their container.

Full option list, measured fields and limitations: `drivers/web/README.md`.

## Real devices and games

- Timing-critical game checks need frame-accurate capture: a capture card or
  engine-side capture (EA IRIS UE5 plugin), and hardware input injection when
  end-to-end latency matters; software injection under-reports latency.
- Run LLM persona agents paused or frame-stepped for games; timing windows are
  judged from measurements, never from the agent failing in real time.
- Physical device size and pixel pitch always come from `ergoqa/devices.py`;
  add a device there (with its source) before testing it.
