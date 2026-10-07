<!-- Mode: persona-qa. Entry point: `SKILL.md`. -->
# Persona QA mode

Test task completion and input preservation. Synthetic scenarios define conditions; product traces establish failures. Integrated improvement includes task-linked research; standalone QA adds it only when requested.

## Phase 0 recap

Use `SKILL.md` Phase 0. Discover tasks from the product; record URL/build, device/viewport/input, constraints, intent, Figma version, grants and synthetic fixtures. Begin baseline QA without a prepared audience or problem list. Ask only for missing material access; preserve existing grants.

Disclose Chromium emulation limits: real device/grip/keyboard occlusion/safe area/screen reader remain untested. Korean product: `references/persona-qa/kwcag-card.md`; report language changes wording only. Outside-product pages: `references/shared/access-card.md` in operator/verifier prompts. Host browser first; preserve user state.

## 1. Build the priority-task matrix

For every priority task, require all these rows on each device in scope:

| Path | Required checks |
| --- | --- |
| Happy path | Enter all choices/values; compare with final state/payload |
| Required omissions | Leave each required choice or field out separately |
| Validation | Exercise each validation error with safe test data |
| Recovery | Back, return, rerender and each coupon/address/error transition |
| Keyboard only | Whole primary task, including intermediate choices and recovery |
| Reading order | Each intermediate screen's meaningful sequence and focus order |

After every step, verify prior values/choices. Author `success.task_checks` for material fields after error/coupon/address/recovery transitions and at completion (`drivers/web/README.md`). Use explicit expected reset/normalized values; `from_step` reuses an authored input, `type.redact:true` protects its recorded text. Failed submit: first-invalid focus, invalid state and error association. Success requires final options/quantities/amounts/notes to match. Each row: pass/partial/fail/untested with reason.

Scenario: ID/task/goal/safe data, basis/brief condition, context/constraints/device/input/start, expected decision/integrity/risk, claim IDs and omissions. Audience rows cite audience_id/segment_id/task_id/facet and gate-supported motivations. Without an audience, choose task-changing strata: new/returning, touch/keyboard, interruption, delay, empty/stale/edge data. Do not add demographic decoration or stereotype behavior.

Optional dataset: exact source/revision/schema, bounded/streaming sample; record adapter/schema fingerprint/seed/config/shard/read-byte-time bounds/IDs/strata/stop. Separate original attributes/assumptions. Scenario detail: `references/persona-qa/persona-scenario-design.md` by section.

## 2. Exercise and capture

Exercise actual product/input/start state; capture decisions/recovery, console/network/runtime errors, keyboard/focus/semantics and feedback. Screenshots support the trace; available interactions require flow evidence.

Bundled fallback (Node.js 22; detect installed dependencies first):

기록과 분석에 같은 프로필을 사용합니다. 아래 예시는 기존 `bundle.json`의 `scenario-1`에 `EP-01`을 연결합니다. 제품 URL·빌드 ID와 안전한 데이터·성공 조건을 먼저 지정합니다.

```sh
: "${PRODUCT_URL:?검사할 제품 URL을 지정하세요}"
: "${PRODUCT_BUILD_ID:?실제 커밋, 버전, 배포 ID 또는 페이지 소스 해시를 지정하세요}"
node drivers/web/ergo_drive.mjs devices
python3 scripts/ergo_qa.py profiles --count 1 --seed 7 --devices galaxy-s24 --out work/profiles.json
python3 - <<'PY'
import json
from pathlib import Path
profiles = json.loads(Path("work/profiles.json").read_text())
profile = next(p for p in profiles["profiles"] if p["profile_id"] == "EP-01")
Path("work/EP-01.json").write_text(json.dumps(profile, ensure_ascii=False))
PY
node drivers/web/ergo_drive.mjs init --url "$PRODUCT_URL" --device galaxy-s24 --task '입력한 값이 최종 결과에 유지되는지 확인' --out sc.json
node drivers/web/ergo_drive.mjs serve --scenario sc.json --profile work/EP-01.json \
  --build-id "$PRODUCT_BUILD_ID" --agent-json agent.json --out runs/ --run-id R-persona-01 --port 9477
node drivers/web/drive_client.mjs --port 9477 observe
node drivers/web/drive_client.mjs --port 9477 act '{"action":"tap","target":"#control"}'
node drivers/web/drive_client.mjs --port 9477 note '{"intent":"Complete the task","expected":"Entered values survive","observed":"Describe the screen","confusion":false}'
# 실제 입력값과 최종 상태를 대조한 후 성공 여부를 기록합니다.
node drivers/web/drive_client.mjs --port 9477 finish '{"success":true}'
python3 scripts/ergo_qa.py analyze --runs runs/R-persona-01 --profiles work/profiles.json --scenario sc.json --out work/analysis.json
```

Use real targets/outcome; agent.json records actual operator/model/input_channel. **Blind touch:** screenshot-only decisions before DOM/source/run data. Then separate a11y or screenshot+a11y technical auditor reproduces transitions with provenance. After each step/failed submit:

```sh
node drivers/web/drive_client.mjs --port 9477 inspect
```

Inspect returns values/choices/invalid/error association/focus/reading order; link receipt to screen/step. Screenshot channel refuses inspect; no DOM knowledge in blind pass. Programmatic evidence cannot stand for assistive-tech speech. Scripted replay: `node drivers/web/ergo_drive.mjs run --scenario sc.json --profile work/EP-01.json --build-id "$PRODUCT_BUILD_ID" --out replay/ --run-id R-persona-replay`, recorded steps/integrity criteria. Driver success cannot override data loss.

Budget a bounded task matrix, no population download; driver run/idle default 900 s. Stop missing access/unsafe action. Separate authorization for posting/purchase/signup/account/data changes. Production identity/SMS/CAPTCHA/security-keypad/certificate/payment gates stop; only approved staging mocks/test payment can complete. No real government/contact/payment/account inputs. Team-approved origins govern widgets; unavailable iframe/popup/app-switch evidence is untested. Lookup `drivers/web/README.md` options/sandbox by section; no installation to pass blocks.

Write a receipt beside **each capture during the run**:

```text
{artifact_path, sha256, captured_at, surface_url, build_id, device, quoted_ui_text}
```

빌드 ID는 커밋·버전·배포 ID 또는 페이지 소스 해시입니다. `--build-id`/`scenario.surface.build_id`는 제공자 지정 정보로 남습니다. PNG 해시는 캡처 무결성만 확인합니다. `unknown` 결과는 미검증이며 같은 빌드 재현에 쓰지 않습니다. 개인정보를 가리고 화면 문구를 그대로 인용합니다. 캡처 시각은 실행 시작과 종료 사이여야 합니다.

## 3. Conditional evidence and intended experience

Task-linked research during improvement, or separately requested research, enters `references/research/workflow.md` with access/evidence cards. Use `references/persona-qa/community-to-test.md` by section; supported_high/medium may motivate P0/P1, single_voice/lead_only stay exploratory. Missing gate leaves community motivation unverified; reproduced product harm keeps impact-based severity. Personas receive scrubbed summaries only.

Inspect Figma/spec entry/journey/hierarchy/content/units/variants/tokens/critical states/responsive/input. Record file/branch/baseline/readback/nodes/time/artifact. Differences need task/comprehension/trust/accessibility/maintainability impact. Separate implementation_defect/design_defect/spec_conflict/approved_deviation; unresolved conflict blocks code acceptance, missing source limits comparison. Proposals: no side accent bars, attached side tabs or decorative rails; existing product bars require task harm.

## 4. Grade, trace and second-pass

Severity: `references/persona-qa/evidence-and-severity.md` by section, impact-based. Reproduced input loss/inaccessible required control can be P0/P1 for blocked/corrupted task. Synthetic confusion stays P2/P3 under caps; preference stays hypothesis. No audience/gate downgrade of observed harm.

Finding: ID/severity/rationale; build/screen/device/viewport/input; persona or scenario/task; steps from start URL; expected and observed with visible UI quotes; capture receipt; user/product impact; verified/inferred cause; fix layer/change/trade-off; standards for accessibility only; second pass; confidence. Consult `references/shared/causal-chain.md` for every P0/P1; unknown organizational constraints remain unknown. Never use as any, @ts-ignore or @ts-expect-error in remediation.

Every P0/P1 requires a second pass over only its capture and text dump, without the draft (at most three priority scenarios):

```text
{finding_id, reviewer: subagent|self, task_completed, control_name,
 omitted, severity: agree|disagree, inconclusive}
```

Without subagents, run a labelled self-pass; it is not independent review. Resolve every disagreement in writing before finalization. Unreadable artifacts require recapture or inconclusive status. Korean accessibility findings have separate KWCAG 2.2 and WCAG 2.2 item/status/coverage; lookup mappings in `references/persona-qa/kwcag-2.2.md` by ID.

## 5. Remediate, replay and report

Fix the reproduced cause with a minimal intent-compatible change. State expected behavior, trade-off and validation; benefit claims need measurements. Reuse the improvement request's scoped grants; standalone review remains read-only. Create UX changes in Figma first with actual nodes/version/readback. Missing design blocks affected implementation only. Replay the original scenario/data/build scope/device/input, primary task, recovery, adjacent states, Figma and accessibility. Explicitly recheck preserved decisions; retain baseline/change/replay evidence. Acceptance requires passing replay, regression and intent checks.

Use `references/persona-qa/qa-report-template.md` by section. First heading after title is Decision/결론: verdict/reason naming build; up to three actions, each at most 25 words with behavior, finding IDs and confirming state; one line untested. Verdict rules:

- hold: verified current P0, primary task completed by no scenario, or primary P1 without workaround.
- ship after fixes: no P0; primary task completes; P1s have concrete fixes.
- ship: primary and recovery exercised on every scoped device/current build, no P0/P1 left.
- inconclusive: unavailable surface, production gate, coverage minimum missing or stale evidence. No findings alone never means ship.

Then matrix/basis, ranked cards, P0/P1 causes, recommendations, Figma/artifacts/replay/unverified/next evidence. Community/access annex only if run; omit zero stops. Emulation/AT/identity/payment limits explicit; language adds no research administration. Reusable artifacts: `references/research/evidence-bundle-contract.md` by section (persona copy exists); verified findings link observed observations/completed runs/scenarios. Record separate read/write/blocked reasons.

```sh
python3 scripts/validate_bundle.py bundle.json
```

`--bind scenario-1=EP-01`은 위 프로필과 기존 QA 시나리오를 연결합니다. 기기·방향과 모든 캡처 시각을 확인하며 정상 실행도 보존합니다. `--cross-profile`은 분석 대조군입니다. 출력과 사본은 입력·실행 폴더 밖의 새 경로를 사용합니다.

```sh
python3 scripts/ergo_qa.py attach --bundle bundle.json --runs runs/R-persona-01 --profiles work/profiles.json \
  --scenario sc.json --bind scenario-1=EP-01 --receipts-dir receipts/ --out bundle.ergo.json
python3 scripts/validate_bundle.py bundle.ergo.json --artifacts-root receipts/
```

P0/P1은 정확한 `finding_id`의 캡처·텍스트 재검토 기록을 `--second-pass`로 제출합니다. 완료된 값 불일치는 `TI-01`과 캡처로 연결하며 `task_success:false`를 보존합니다. 누락·미도달 검사는 미확인입니다. 기존 증거를 보존하고 익명 검토 기록을 복제하지 않습니다.

`--device galaxy-s24` 기록은 `analyze`/`swarm --cross-profile`에서 분석용으로 평가합니다. QA 페르소나의 실행으로 연결하지 않습니다.

## Failure ladder

| Missing/failing | Next step; ask boundary |
| --- | --- |
| Browser/build | Highest available fallback; if denied/unavailable, named blocker and inconclusive. Ask only for access needed to exercise the task. |
| Dataset/audience | Brief-derived synthetic conditions; continue QA, no invented participants. |
| Community source/key | When research is active: obey final stops, continue eligible sources and QA; ask for an environment key only if material and not declined. |
| Figma/verifier | Conditional comparison; labelled self-pass. Ask for missing required design decision or independent/human verification. |
| Coverage/time | Finish bounded rows, list untested ones; minimum unmet means inconclusive. |

## Anti-patterns

| What goes wrong | Why | Fix |
| --- | --- | --- |
| Success banner passes | Input may be corrupted | Compare entered values to final state |
| One generic recovery row | Misses distinct omissions/errors | Required matrix, checks after every step |
| Touch looks accessible | Keyboard/order/error association differ | Whole keyboard task and auditor pass |
| Persona says “confused”, graded P0 | Judgment cannot prove harm | Separate reproduced behavior and capped judgment |
| Korean QA loads channel atlas | Unrequested research | KWCAG card only |

## Done when

Surface exercised or exact blocker stated; matrix meets coverage or verdict is inconclusive; synthetic/real evidence and blind/auditor provenance are separate; every priority finding has fresh reproduction evidence, impact rationale and labelled cause; every P0/P1 has second-pass record and resolved disagreement. Community motivation is gate-supported or exploratory, tools/context authorized; critical states/accessibility considered; Korean standards/status/coverage and untested gates separate. Reusable bundle validates; report names build, limits, untested scope and replay outcome. No unauthorized side effect occurred.
