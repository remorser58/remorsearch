# Improve an existing product

Improve a working product from its URL or repository. Narrow research/review keeps its scope. The host uses available tools and the four components.

## Start from the product and preserve intent

Open the URL, or inspect the repository's start command and current build. Confirm the user's URL matches the tested build before relying on a local endpoint. Identify tasks, users, screens, tools, safe fixtures and existing grants. State scope and finite limits; reuse supplied limits. Otherwise begin with up to three primary tasks and two improvement rounds. Do not require a problem list or mode choice.

Read relevant `AGENTS.md`, README, PRD, decision records, accessible Claude/Codex sessions and intent memory, commits and Figma history. Search by this product, task and decision; do not collect unrelated personal records or make another installed skill a prerequisite. Record each preserved decision's source, authored/checked dates, version, affected task/screen and reason. Mark missing or stale material explicitly. Current implementation shows behavior; it does not establish why it was chosen.

Apply the latest explicit user instruction, currently confirmed project decisions, then older memory. Compare old records with current documents/screens/changes; a newer commit alone does not revoke a decision. Preserve intentional confirmation, business rules, access, feature order, terminology and brand experience. Missing memory permits neither arbitrary changes nor a blanket stop. Ask about unresolved material conflicts only for affected changes; continue other work. Save intent in task artifacts; do not update global memory.

## Observe first, then ask research questions

Enter persona-qa with `references/persona-qa/workflow.md`. Use the real product to establish a baseline before research. Derive scenarios from actual tasks: completion, input retention after back/errors/return, failure and recovery, empty/loading/stale states, keyboard/focus/reading order, relevant screen sizes and interruption. Keep build, start state, safe data, device and input in each trace. Preserve tabs, accounts, filters and real records; writes use owned synthetic fixtures.

Ask where the task stopped, what the UI implied, what workaround was available and when it worked. Separate unknown causes from reproduced behavior. Test unfamiliar/returning, interrupted, touch/keyboard and other relevant synthetic conditions, without claiming real participants or population estimates. Ergonomics remains experimental screening; emulation/models cannot establish real-device, assistive-technology or human accuracy.

Load `references/research/workflow.md` and its access/evidence cards when research starts. Plan questions from the baseline and inspect relevant counterexamples. These six sources are fixed candidates, selected for useful task context; there is no requirement to scrape all six or assign empty priority scores:

| Candidate | Context to seek |
| --- | --- |
| 당근 (Karrot) | Relevant local, transaction or service task; original post and comments |
| 디시인사이드 (DC Inside) | Relevant gallery, original conditions, replies and alternatives tried |
| 유튜브 댓글 (YouTube comments) | Video topic/time, referenced scene or feature, comments and replies |
| X | Original post, conversation, quote/reply target and experience conditions |
| 인스타그램 (Instagram) | Post/video caption, related comments and the question or problem context |
| Threads(쓰레드) | Original post, connected replies, prior statement and follow-up explanation |

Supplement with relevant Naver Cafes, reviews, Reddit or official sources. Selection does not imply access. Discover URLs, then invoke bundled insane-search under the research card's access/privacy rules and permitted adapters. Unsupported output stays a lead; unread content stays a gap. Retain actual calls, source URL, checked/published dates, version, summary, read scope, firsthand/promotion/inference distinctions, counters and duplicates. A blocked platform does not stop other research or product QA. Never invent callback receipts outside supported capture paths.

Convert scrubbed research into hypotheses and rerun related tasks. Unreproduced complaints stay hypotheses; check version/context differences. Sparse community evidence does not block reproduced defects. Report optional source gaps separately from missing required product QA. Use existing plan, gate and bundle contracts; never fabricate statuses or receipts to pass.

## Fix and verify in the same scope

Record the improvement request, actor and scope as authority for ordinary reversible fixes; do not ask again at a CLI permission stop. Review paths and concurrent edits before applying a minimal fix. Unresolved intent conflicts, scope expansion, deployment, publication and real account/customer changes need their own decision or authority.

Create screen composition and UX changes in editable Figma first. Preserve existing design; record actual file URL, nodes, version and readback before implementing. No side accent bars or side-tab cards. If Figma is unavailable, leave affected design/implementation blocked, identify the missing connection and continue possible investigation/QA. A screenshot or local plan does not fulfil this requirement.

Use `references/loop/workflow.md` for bounded patch/replay records and look up `references/loop/provider-contract.md` by section for exact packet fields. Host browser and Figma tools perform actual actions. The CLI validates imported evidence and applies authorized local text patches; it does not drive a browser, design or build. When it stops for missing receipts, continue the feasible collection in the host and resume with appended evidence. Do not end an authorized improvement request at a report or CLI handoff.

Rebuild with project tools and replay on the current build with matching start state, fixture, viewport and input. Check task completion, values, recovery, accessibility, adjacent regressions, Figma and each preserved decision. Failed/missing/stale checks prevent completion; correct within the remaining rounds and retain prior evidence. Do not expand indefinitely or restart budgets.

## Example request and operational checklist

`우리 앱 UX 개선해줘. URL: https://app.example.test 또는 저장소: /path/to/product`

1. Inspect that target and relevant intent sources. Save product/build identity, task scope, preserved decisions and unknowns in the task artifacts; exercise baseline QA and retain actual traces.
2. Author `brief.json` and `plan.draft.json` from observed questions. From the installed skill folder, run `python3 scripts/ux_research.py start --brief brief.json`, then `python3 scripts/ux_research.py plan --run RUN --manifest plan.draft.json`. Use the returned run path. Perform permitted searches/captures, merge/gate as the research card specifies, and retain gaps.
3. Author related scenarios and collect real QA evidence. Run `python3 scripts/validate_bundle.py QA_BUNDLE.json`. Prioritize reproduced task harm and intent-compatible fixes; complete actual Figma work for the affected UX changes.
4. Bind `goal.product_context_artifact_id` to the inspected context (sources, dates, constraints, conflicts, `path_scenarios`); see provider-contract section 6. Record specific operator intent decisions separately with `--intent-decisions` when needed; generic grants and provider actors cannot settle intent. Assemble real loop evidence and check `python3 scripts/ux_loop.py validate packet.json --evidence-root EVIDENCE`. Run `python3 scripts/ux_loop.py improve packet.json --workspace PRODUCT --evidence-root EVIDENCE --checkpoint CHECKPOINT --grant code_write --actor OPERATOR --reason 'Existing UX improvement request; reviewed reversible scope'`. Use actual paths/operator and reviewed scope. Collect missing evidence; `resume --input` appends it. Never treat examples as observations.
5. Link each replay to `intent_review_artifact_id`, covering every scoped constraint/scenario, including unchanged constraints (`fix_id: null`) in no-edit runs. `intent_verified` must be true for acceptance; legacy `run` without context does not check intent. Deliver changed product/code/design locations, resolved findings with before/after evidence, preserved-intent results, regression coverage and remaining gaps. Link the bundle and loop report where used.

Declare improvement complete only after original failures, adjacent regressions, preserved intent and required design checks pass on the current scoped build, with no known material in-scope issue or required evidence gap. An exhausted limit yields a partial result. If scoped QA finds no reproducible change to make, report a completed inspection with no changes and its evidence/coverage. Do not manufacture a fix or claim measured satisfaction, conversion, time savings or human accuracy.
