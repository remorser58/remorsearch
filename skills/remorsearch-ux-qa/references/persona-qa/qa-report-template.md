# Persona QA report — [product]

## Decision

**Verdict: [ship | ship after fixes | hold | inconclusive].** [One sentence naming the tested build, the user outcome and the rule that determines this verdict.]

1. [Change a behaviour; cite finding IDs; name the screen state that proves success.]
2. [Include only if needed.]
3. [Include only if needed.]

**Not tested:** [One line naming the consequential gaps.]

Writer guidance: keep at most three actions, each at most 25 words. Remove unused action slots. Apply these rules to the current build:

| Verdict | Rule |
| --- | --- |
| `hold` | A P0 is verified on the current build; or no scenario could complete the primary task; or a P1 on the primary task has no workaround. |
| `ship after fixes` | No P0; the primary task can be completed; P1 findings have concrete fixes. |
| `ship` | The primary task and at least one recovery path were exercised on the current build on every device in scope, and no P0 or P1 remains. |
| `inconclusive` | The surface could not be exercised, the coverage minimum was not met, or evidence is stale. Name the blocker: browser failure, production gate, missing build access or missing current evidence. |

Check evidence and coverage first. Where they cannot support a release decision, use `inconclusive`. An empty findings list requires the same coverage proof as any other `ship` verdict. State remaining P2/P3 findings.

For Korean reports keep this QA structure. Use 결론, 발견, 수정 전후, 시나리오와 점검 범위, 조사 방법, 부록 and 완료 점검. Verdict labels are 출시 가능 (`ship`), 수정 후 출시 (`ship after fixes`), 보류 (`hold`), 판단 불가 (`inconclusive`). Use the Korean research template's wording self-check and quoting rules when community evidence was requested.

## Findings

Order cards by P0, P1, P2, P3, then high, medium, low confidence within each severity. Include verified current-build observations here. Put unreproduced, stale or unverified cards in the annex and state the missing evidence. Severity follows user impact; confidence follows evidence quality. Research gate statuses govern community-derived scenario motivation; they never reduce the severity of an observed product failure.

| ID | Severity and impact rationale | Confidence | Scenario/task | Verification |
| --- | --- | --- | --- | --- |
| [F-01] | [P1 — user consequence] | [high/medium/low] | [scenario; task] | [current build; receipt] |

### [F-01] · [P0–P3] · [one-line impact rationale]

- **Where:** build [commit/version/deploy ID/page hash]; screen [state]; device [ID], viewport [width × height CSS px, DPR], input [touch/keyboard/etc.].
- **Who:** persona or scenario [ID, brief-derived synthetic condition or supported basis]; task [completion condition].
- **Steps:** 1. Open [start URL] in [starting state]. 2. [Action/input]. 3. [Action that exposes the failure]. Number every step needed to reproduce it.
- **Expected:** [Intended behaviour; quote the relevant visible control/label. Mark proposed wording as proposed.]
- **Observed:** [What happened after which action; quote the exact visible UI text. Distinguish a success banner from an intact completed task.]
- **Evidence:** [Capture link and adjacent receipt; corresponding text-dump link; supporting trace/observation IDs.]

```json
{
  "artifact_path": "captures/[capture].png",
  "sha256": "[64 hexadecimal characters]",
  "captured_at": "[ISO timestamp with timezone]",
  "surface_url": "[captured URL]",
  "build_id": "[tested build identity]",
  "device": "[device ID and viewport]",
  "quoted_ui_text": "[exact visible text in the capture and text dump]"
}
```

- **Why it matters:** [User consequence and task affected; label possible product effects as inference.]
- **Cause:** [Verified observation or inferred cause, with evidence IDs. For every P0/P1 connect the screen state → interaction/state mechanism → user consequence. Keep deeper hypotheses in the annex; unknown implementation or business constraints stay unknown.]
- **Fix:** layer [copy/interaction/information architecture/service rule/data system]; change [specific behaviour]; trade-off [cost or competing need]; acceptance state [what the replay must show].
- **Standards:** [Accessibility findings only; use the independent columns below.]

| KWCAG 2.2 item | KWCAG status and evidence | WCAG 2.2 success criterion | WCAG status and evidence |
| --- | --- | --- | --- |
| [number and title, or no counterpart] | [observed pass/failure, partial, untested, unconfirmed, or no counterpart; reason] | [number and title, or no counterpart] | [its own status; reason] |

For a Korean product assess both standards separately. State applicability elsewhere. Confirm each number/title against its own official text; otherwise mark it `unconfirmed` (`미확인`). A stopped or unexercised check is `untested` (`미검사`). A result in one column supplies no result for the other. Repository check IDs belong in evidence. State screen-level observations and coverage; certification or legal compliance needs separate evidence.

- **Second pass:** [Record below for every P0/P1; for P2/P3 state whether performed.]

```json
{
  "finding_id": "F-01",
  "reviewer": "self",
  "task_completed": null,
  "control_name": "[visible name]",
  "omitted": "[missing information or nothing omitted]",
  "severity": "agree",
  "inconclusive": true
}
```

- **Confidence:** [high/medium/low; why, including reproduction and receipt limits].

Write each capture receipt during the run next to its artifact. Record run start in Method. A P0/P1 without a receipt newer than run start stays unverified; a later copy timestamp or a newly calculated hash cannot restore that missing provenance.

Use at most three priority scenario packets to cover every P0/P1. A separate reader sees only the captures and their text dumps, without the draft. Freeze their task/control/omission and severity assessment before comparing it with the first pass to record agree/disagree. `reviewer` is `subagent` or `self`; `task_completed` is a boolean, or null when unknown; `severity` is `agree` or `disagree`; `inconclusive` is a boolean. Hosts without subagents use a labelled self-pass under the same capture-only procedure; disclose its lack of independence. Write the resolution of every disagreement before finalising. Missing or unreadable evidence leaves the finding unverified.

## Accepted fixes: before and after

Include this table only for fixes actually accepted and replayed. If none, say “No accepted fixes; post-fix replay was not performed.”

| Finding | Baseline artifact, receipt and build | Accepted change and trade-off | Replay artifact, receipt and build | Same scenario/device outcome; regressions; status |
| --- | --- | --- | --- | --- |
| [F-01] | [original failure] | [implemented behaviour] | [fresh capture after the change] | [resolved/open; evidence] |

An A/B candidate comparison is a comparison between builds. A planned validation is a next test. Accepted-fix evidence must show the actual change and its replay. Update the verdict against the replayed build and repeat the P0/P1 second pass on its captures.

## Scenarios and coverage

Count executed scenarios even when the task failed. Give completion separately. Define each denominator from the agreed plan; if the plan or build identity is missing, write unknown and use `inconclusive` where the minimum cannot be proved.

| Scenario | Persona/basis and claim gate status, if used | Task | Build | Device, viewport, input | Happy/recovery path | Run/planned | Task outcome and artifact |
| --- | --- | --- | --- | --- | --- | --- | --- |
| [S-01] | [synthetic brief condition, or claim ID + gate status] | [intact completion criterion] | [ID] | [configuration] | [path] | [k/n] | [completed/failed/partial/not run; link] |

| Coverage dimension | Exercised/planned on current build | Completed | Gap |
| --- | --- | --- | --- |
| Scenarios | [k/n] | [k/n exercised] | [missing scenarios] |
| Devices | [k/n named devices] | [primary task per device] | [missing devices] |
| Happy paths | [k/n planned device/task combinations] | [k/n] | [missing paths] |
| Recovery paths | [k/n planned device/task combinations] | [k/n] | [at least one per device for ship] |
| Accessibility checks | [k/n planned checks; standards apart] | [pass/fail/partial counts] | [keyboard, assistive technology, etc.] |

## Method and limits

- Product, start URL, current build ID, run start/end, report date, scope and primary task.
- Actual browser/engine, viewport emulation or physical device, input channels, tools used and fallbacks.
- Permitted fixture/test-data changes; production authentication/payment gates left untested; unavailable surfaces and their blockers.
- Accessibility coverage: checks exercised, actual assistive-technology use, official texts checked, and limits for each standard.
- Community research appears only when requested. Record the access card read before the first external page, source IDs and matching gate record. Every reader, persona and verifier task carries its applicable evidence/access card in its instructions. Cite community sources by channel/date/source ID; post URLs stay in the bundle. Names and handles are omitted.
- If external reading occurred, append pages read, stops with a non-zero count (`terms_restricted` separately), closed channels, unread pages/untried rungs and missing keys. Use the access policy's recorded stop scope. Keep zero stop counts in the bundle.

When the browser could not run, open with `inconclusive`, name the failed browser operation and blocker, report 0/n executed coverage, and give the evidence needed to resume. Keep any supplied screenshots or reports as archived/unverified material in the annex. Do not invent a reproduction or a capture-time receipt.

## Annex: hypotheses, unverified findings and access gaps

| ID | Hypothesis/unsupported claim/access gap | Status | Supporting material and limit | Next evidence or test |
| --- | --- | --- | --- | --- |
| [H-01] | [specific statement] | [inferred/unverified/gate status/stop code] | [artifact/source; missing proof] | [concrete evidence] |

Put unsupported research claims (`single_voice`, `lead_only`, `conflicting`, `stale`, `needs_product_check`, `unfit`) only here. Preserve full unverified finding cards when they will guide a replay. Separate inferred causes from verified observations. Use optional Figma comparisons only when requested and actual version/readback evidence exists.

## Writer self-check

- Decision first; verdict rule/build, at most three actions of at most 25 words, one not-tested line.
- Every verified P0/P1 has a same-run receipt newer than run start, a capture-only second pass and a written disagreement resolution.
- Every cited research claim has its gate status; unsupported empirical claims and unverified findings stay in the annex.
- Cards quote visible UI text, give reproducible steps and causes; accepted fixes have baseline/change/replay evidence.
- Coverage has denominators and current build; KWCAG 2.2 and WCAG 2.2 have separate statuses; no names or handles; what was not tested is stated.
