# Ergonomics screening report — [product/screen]

## Decision

**Screening result:** [What the screening found, the behaviour/condition affected and the next test or change; name the build.]

**Severity boundary:** [Highest reported severity and its evidence basis.] An uncalibrated reach model alone is capped at P2; gaze heuristics at P3; a single qualitative judgment at P3, or P2 when replicated under the protocol. Model prediction alone cannot justify P0; P0 needs measured evidence. Apply each check's documented cap and corroboration rule.

**Coverage:** [k of n planned profiles, k/n scenarios and named device/input conditions exercised on the build]. Profile coverage describes simulated conditions; population prevalence requires a fitting study.

**Model limits:** [Calibration/domain limits, heuristic assumptions, agent input limits and missing observations]. **Not tested:** [One line of consequential physical-device, grip, assistive-technology or other gaps].

1. [At most three next actions: behaviour to change/test, finding IDs, and the observable state that would show success.]

For Korean reports use 결론, 발견, 수정 전후, 실행과 점검 범위, 판단 검토, 조사 방법과 한계, 부록, 완료 점검. This is a screening decision. If a release verdict is requested, also apply [the persona-QA verdict rules](../persona-qa/qa-report-template.md): 출시 가능 (`ship`), 수정 후 출시 (`ship after fixes`), 보류 (`hold`), 판단 불가 (`inconclusive`). An unexercised surface, stale evidence or missing minimum coverage requires `inconclusive`; name the blocker and report 0/n for unrun coverage.

## Findings

Sort P0 → P1 → P2 → P3, then confidence high → medium → low. Every card uses [the persona-QA finding fields](../persona-qa/evidence-and-severity.md#finding-card): impact rationale; build/screen/device/viewport/input; profile or scenario and task; steps from start URL; expected/observed with visible UI quotes; capture receipt; why it matters; verified/inferred cause; fix layer/change/trade-off; separate KWCAG 2.2 and WCAG 2.2 item/status columns for accessibility; second pass; confidence.

Add the ergonomics evidence boundaries to each card:

| Finding | Severity/cap and confidence | Evidence kind | Check/model/version | Measurement and threshold, or model inputs/output | Profiles affected/evaluated | Difference condition |
| --- | --- | --- | --- | --- | --- | --- |
| [F-01] | [P2; reach-only cap; medium] | [measured/model/judgment] | [check ID; version] | [value/unit/reference or assumptions] | [k/n within stated conditions] | [e.g. one-hand left grip, device] |

- **Measured (`observed`):** captured geometry, actual input behaviour or recorded physical measurement; artifact/observation IDs and instrument limits.
- **Model (`inferred`):** model ID/version, input conditions, output, calibration status and severity cap. Model output alone establishes a screening condition.
- **Judgment (`inferred`):** expectation versus observed screen state, evaluator input channel, reasoning and replication status. Keep uncorroborated preference/comprehension claims as annex hypotheses.
- **Cause:** for every P0/P1, state the observed screen condition → interaction mechanism → task consequence; label inferred implementation/service causes and unknown constraints.
- **References:** use the check's model/threshold literature when it supports this condition; distinguish measured outcomes from inferred consequences.

Write receipts during the run next to captures with `{artifact_path, sha256, captured_at, surface_url, build_id, device, quoted_ui_text}`. A P0/P1 without a receipt newer than run start stays unverified in the annex. Each P0/P1 needs a capture-and-text-only second pass without the draft, covering at most three priority scenarios, with `{finding_id, reviewer: subagent|self, task_completed, control_name, omitted, severity: agree|disagree, inconclusive}`. Hosts without subagents use a labelled self-pass; disclose its lack of independence. Freeze the capture assessment before comparing severity; resolve disagreements in writing. Static screenshots may leave task completion unknown.

## Accepted fixes: before and after

If none, state that no fix was accepted and no post-fix replay ran. Otherwise:

| Finding | Baseline artifact/receipt/build | Actual change and trade-off | Replay artifact/receipt/build | Same scenario/device/profile result; regressions |
| --- | --- | --- | --- | --- |
| [F-01] | [failure] | [change] | [fresh post-change evidence] | [resolved/open/unknown] |

Repeat the P0/P1 second pass on replay captures. Keep next-test plans separate from accepted-fix results.

## Runs and coverage

| Run/scenario | Build | Device/viewport/input | Happy/recovery path | Run/planned | Task result | Profiles evaluated/planned | Agent model/input channel/method |
| --- | --- | --- | --- | --- | --- | --- | --- |
| [R-01/S-01] | [ID] | [configuration] | [path] | [k/n] | [completed/failed/partial] | [k/n] | [actual setup] |

| Profile ID | Scenario assumption | Device/grip/condition | Sampling basis/coverage stratum | Dataset revision, if used |
| --- | --- | --- | --- | --- |
| [P-01] | [task condition] | [specific inputs] | [coverage choice; supported source if any] | [revision or none] |

Give total scenarios run/planned, devices exercised/planned, happy and recovery paths exercised/planned, and profiles evaluated/planned. Report success separately from execution. List omitted strata and unknown base rates; avoid extrapolating profile k/n into a user share.

## Judgment review

Include only checks actually performed: relevant accessibility exceptions (KWCAG/WCAG separately), reversibility, hierarchy, advertising resemblance, expected versus actual behaviour, or a separate dark-pattern pass. Record measured observations, inferred judgments and unresolved hypotheses apart. Optional synthetic discussion is labelled “시뮬레이션 · 합성 담론”; use it to propose questions/tests, with no real-user quotes or prevalence claims.

## Method and limits

- Surface/start URL/build, run start/end, actual tools, physical versus emulated devices and capture/measurement method.
- Models, calibration populations, heuristics and supported input domain; agent and environment limits.
- Platforms, grips, conditions, ages, assistive technology, network states and complete tasks left untested.
- Before any external page, record the access card used. Every reader/persona/verifier task carries the applicable card in its instructions. Community research requires the user's request; cited claims need matching gate statuses. External coverage, if any: pages read, non-zero stops, closed channels and missing keys; zero stops stay in the bundle.
- Next verification: P0/P1 and model-based P2 need a task test under the affected real conditions; accepted changes need the same scenario/device/profile replay. Claiming satisfaction, conversion or prevalence needs an actual measurement design.

## Annex: hypotheses and access gaps

| ID | Unverified finding/hypothesis/gap | Status and evidence limit | Next measurement/source/test |
| --- | --- | --- | --- |
| [H-01] | [condition] | [model/judgment/unverified/gate status] | [specific test] |

Unsupported research claims and stale/unverified product cards stay here. Preserve model-only limits and unresolved severity disagreements.

## Writer self-check

- Decision first: screening result/build, capped severity, k/n profile coverage, model limits and what was not tested.
- Every verified P0/P1 has a same-run receipt and capture-only second pass; disagreements have written resolutions.
- Measured, model and judgment evidence remain distinct; causes and proposals show their inference status.
- Every research claim cited has a gate status; unsupported empirical claims stay in the annex; no names or handles.
- Fixes have baseline/change/replay; coverage denominators and separate standards statuses are stated; gaps and next real-condition tests are explicit.
