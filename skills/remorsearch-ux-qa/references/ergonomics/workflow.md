<!-- Mode: ergonomics, experimental. Entry point: `SKILL.md`. -->
# Ergonomics mode

Default to a stratified detector run on the real surface: one recorded flow per device/orientation, analyzed across profiles. It needs no subagents. Persona agents, interviews and simulated experience boards are opt-in. Reports can be English or Korean.

## Phase 0 recap

Use `SKILL.md` Phase 0: scope/build/tasks, devices/orientations, input, supplied data, grants and tools. Choose detector coverage or requested persona-agent behavior. Missing audience research takes the stratified path; explain it. Korean product QA reads `references/persona-qa/kwcag-card.md`; Korean research users/channels open `references/research/korea/overview.md` only when research runs. Before an external page, including a later lead, carry `references/shared/access-card.md` and use research's evidence card. Ask at most one grouped question for necessary missing inputs.

Keep basis visible: **measured** is surface observation against a fixed standard; **model** applies a published model to measured inputs and is inferred; **judgment** is human/LLM inference. Only measured observations from completed runs can be verified. Counts are k/n **simulated-profile coverage**; never real prevalence, preference, discomfort or forecast. Do not role-play pain or seeing difficulty as measurements. The uncalibrated thumb model alone is capped at P2. Model prediction alone cannot reach P0; P0 needs measured safety failure or a declared irreversible action with a computed misfire path. Every P0/P1 needs measured basis or corroborating task trace.

## 1. Frame the scenario

Record actual URL/app/build, task/data, platform/device/orientation and data-mutation risk. Declare roles: primary, destructive, irreversible (only after sandbox confirmation of no confirm/undo), critical_message, error_message, status, hud, game_control, timed, ad_like. Declare transient_text and qte windows. Use the shipped driver init/schema; consult `references/ergonomics/platform-drivers.md` by section for a non-web transport. Repository specification `docs/ergonomic-swarm-spec.md` is not installed with the skill.

```sh
node drivers/web/ergo_drive.mjs devices
node drivers/web/ergo_drive.mjs init --url URL --device DEVICE --task TASK --out sc.json
python3 scripts/ergo_qa.py catalog
```

Use safe steps and authored `success.task_checks` for material values/choices after recovery transitions and at completion; exact payloads, 1-based steps, intentional reset/normalization and `type.redact:true` are in `drivers/web/README.md`. Read-only defaults and separate write grants apply. Production verification/payment, human checks or missing access stop the path. Emulation covers Chromium viewport/DPR/input; real device, grip, keyboard occlusion, safe area and screen reader remain untested.

## 2. Compose profiles

Default stratified coverage:

```sh
python3 scripts/ergo_qa.py profiles --count 16 --seed 7 --devices galaxy-s24,iphone-15 --out work/profiles.json
```

Cover per device right/left one-hand, two-thumb and cradled grips; pointer devices use mouse right/left and keyboard-only. Include condition strata: deutan, presbyopia 60s, mild tremor, walking, low vision, 70s+, small hand; alternate hands. Pointer devices skip walking/small-hand/tremor because only the touch model reads them. Base rates fill remaining slots, never measure this product's audience. Record assumptions, seed, sampled and unfilled facets.

If a completed evidence-backed ergo-audience.v1 was supplied/requested, consult `references/ergonomics/audience-research.md` by section, validate it, then:

```sh
python3 scripts/ergo_qa.py audience-check audience.json
python3 scripts/ergo_qa.py personas --audience audience.json --budget 12 --plan work/persona-plan.md --out work/profiles.json
python3 scripts/ergo_qa.py scenario-stubs --audience audience.json --out scenarios/
```

Research-origin audiences also require the supported gate/bundle/run checks described in `references/research/workflow.md`. Drafts cannot compose; unknown shares stay unknown. Audience composition chooses typical members, weighted one-facet variants and inclusive floors; the plan explains every profile and uncovered facet. Extra conditions follow the audience. A linked narrative dataset needs exact revision/schema/bounded sampling; it has no measured ergonomic attributes. Synthetic/LLM output never supplies audience evidence.

## 3. Record real runs

Use the host browser first or Node.js 22 fallback with installed dependencies:

```sh
node drivers/web/ergo_drive.mjs run --scenario sc.json --device DEVICE --out runs/
python3 scripts/ergo_qa.py analyze --runs runs/ --profiles work/profiles.json --scenario sc.json --cross-profile --out analysis.json
```

One real scripted trace per device/orientation can serve all profiles there. Keep screenshots, geometry/colors/timing before/after each step, actual outcomes and collector versions. Bundled run/idle default limit is 900 seconds. Android uses adb capture plus `android-snapshot`; iOS/desktop/engine-rendered games use platform captures and annotations (vision geometry is inferred); look up `references/ergonomics/platform-drivers.md` for exact options. A blocked transport stays untested.

Opt-in persona agents use serve and `references/ergonomics/persona-agent-protocol.md`, plus `references/agent-setup.md` if spawning is authorized. Each agent receives applicable cards and sees screenshots before touch decisions. Separate runs per agent when behavior matters; later technical/a11y inspection records its provenance. Notes/expectation/confusion remain judgment. Optional `references/ergonomics/swarm-and-social-layer.md` boards/interviews cite run/step/observation IDs; ungrounded answers are speculative and simulated discourse only generates research hypotheses.

## 4. Analyze, judge and aggregate

```sh
python3 scripts/ergo_qa.py swarm --runs runs/ --profiles work/profiles.json --scenario sc.json --cross-profile --bundle --out report/
python3 scripts/validate_bundle.py report/bundle.json
```

기록된 프로필의 실행은 기존 QA 증거 묶음에 연결할 수 있습니다. `references/persona-qa/workflow.md`의 예시는 `work/EP-01.json`을 생성하고 같은 프로필과 빌드 ID로 `R-persona-01`을 기록합니다. 기기만 기록한 위의 `--device` 예시는 분석용 대조에 사용합니다. QA 연결에는 아래처럼 `--profile`을 사용합니다. 제품의 실제 빌드 ID를 넘기면 실행과 모든 캡처에 제공자 지정 정보로 남습니다. 빌드 정보가 없는 결과는 미검증 상태이며 같은 빌드 재현을 주장할 수 없습니다.

```sh
node drivers/web/ergo_drive.mjs run --scenario sc.json --profile work/EP-01.json \
  --build-id "$PRODUCT_BUILD_ID" --out runs/ --run-id R-persona-01
python3 scripts/ergo_qa.py analyze --runs runs/R-persona-01 --profiles work/profiles.json --scenario sc.json --out analysis.json
python3 scripts/ergo_qa.py attach --bundle qa/bundle.json --runs runs/R-persona-01 --profiles work/profiles.json \
  --scenario sc.json --bind scenario-1=EP-01 --receipts-dir receipts/ --out qa/bundle.ergo.json
python3 scripts/validate_bundle.py qa/bundle.ergo.json --artifacts-root receipts/
```

P0/P1은 정확한 `finding_id`의 캡처·텍스트 재검토 기록을 `--second-pass`로 제출합니다. 완료된 값 불일치는 `TI-01` 증거로 연결되며 과업 실패 상태를 유지합니다. 정상 실행도 검사 범위·캡처가 남습니다. 기기·방향·실행 중 캡처 시각과 reflow/focus의 뷰포트·DPR·문맥을 보존합니다. `--out`은 입력·실행 폴더 밖의 새 파일입니다.

Add `--audience audience.json` only for a completed audience. Use the emitted bundle path if this version names it differently. Outputs: findings.json, analyses.json, report.md and an evidence bundle. Segment groups/segments_affected describe triggered profiles, never user shares. Record model IDs and differential conditions (shared by triggered profiles and no untriggered profile). Use `python3 scripts/ergo_qa.py heatmap --help` for reach/gaze review options.

Lookup fired check IDs in `references/ergonomics/human-factors-checks.md`: reach, pointing/Fitts/misfire, gaze, contrast/CVD/visual angle/bright light, choice/reading/latency, game reaction/flash, names/labels/errors/focus/clipping/reflow. Formulas and validity limits are in `ergoqa/params.py`; repository briefs `docs/human-factors/` are not installed. A detector alone cannot decide WCAG size exceptions, irreversible actions, destructive-primary styling, ad-like information, game intent, left-handed options or heuristic fit: record screenshot/step-backed judgment and its limit. ACT examples gate covered checks; a screening result never certifies standards compliance.

## 5. Report, fix and replay

시선·글자 지표·화면 크기 대응은 `references/ergonomics/visual-science.md`의 해당 절을
조회합니다. 과제에 따른 주의, 물리적 기하, 글리프 지표와 실제 내용 손실을 모델의 가정과
구분합니다. RF-02 간격 검사와 RF-03 짧은 창 검사는 기록한 조건에만 적용합니다.
정적 복제 화면은 JavaScript의 실제 크기 변경 동작을 검증하지 못합니다.

Use `references/ergonomics/report-template.md` by section. Decision first, findings ordered by severity/confidence, measured/model/judgment separated, differential conditions and k/n coverage, assumptions and untested platform/device/grip/condition list. Cite source/model limits; benefit claims require measurement. Propose the smallest fix at the deepest confirmed cause (`references/shared/causal-chain.md`). Figma is the design source of truth when present; record version/readback. Skill-authored proposals use no side accent bars, attached side tabs or decorative rails; existing product QA requires task harm.

Writes need design/test-data/code grants separately. Replay identical scenario/device/profiles after a fix; compare baseline/change/replay and adjacent states. For P0/P1 use persona-qa's fresh capture receipt and second-pass rules. Generated report wording can be English or Korean without changing measured outputs.

## Failure ladder

| Missing/failing | Next step; ask boundary |
| --- | --- |
| Audience | Stratified default with reason/untested facets; do not block screening |
| Browser/platform | Available host transport, then driver; deny/unavailable means real-surface blocker. Ask only for needed access. |
| Source/key | Only requested audience research: card stop, other source family; key set in environment if necessary |
| Verifier | Serial labelled self-pass; unresolved exceptions/flags stay inconclusive. Ask for required human verification. |
| Model input | No guess of geometry/timing; measured or explicitly inferred input, otherwise untested |

## Anti-patterns

| What goes wrong | Why | Fix |
| --- | --- | --- |
| Spawn 16 agents by default | Screening only needs traces/profiles | Detector default; agents opt-in |
| “My thumb hurts” | Synthetic role-play | Computed model, validity cap |
| k/n becomes market percent | Profiles are sampling coverage | State denominator and omissions |
| Thumb model rated P0 | Uncalibrated reach cannot prove harm | P2 cap, measured/task corroboration |
| Vision boxes called measured | Geometry is inferred | Record annotation provenance |

## Done when

Evidence-backed audience or explicit stratified reason; real-surface runs or exact blockers; assumptions/sampling/untested facets recorded; measured/model/judgment separated with model IDs; P0/P1 has measured basis or trace corroboration and fresh receipt/second pass; severity caps hold; counts are simulated coverage; bundle validates when produced; report language, limitations and replay outcome explicit; no unauthorized side effect.
