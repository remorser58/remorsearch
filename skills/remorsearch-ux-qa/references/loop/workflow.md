<!-- Mode: loop. Entry point: `SKILL.md`. -->
# Loop mode

The host agent investigates, operates browser/Figma tools, builds and replays. CLI validates receipts, plans findings and patches reviewed local scope; it starts none of those tools. Demo fixture: product_complete false. For a whole-product improvement request, start with the product-improvement guide linked by `SKILL.md`.

## Phase 0 recap

`SKILL.md`: derive tasks from product/intent discovery; record build/devices/inputs/grants/tools and limit 1-10. Reuse existing authority, asking only for material missing access or unresolved intent. Korean switches separate. Outside-product pages: `references/shared/access-card.md`.

## 1. Providers

Load only the active provider card. Product improvement starts with `references/persona-qa/workflow.md`, uses `references/research/workflow.md` for discovered questions, then returns to relevant QA. Narrow requests keep their scope. Label serial/self checks. Research supplies scrubbed hypotheses; actual product traces establish findings.

Lookup `references/loop/provider-contract.md` by section. ux-loop.v1 intake: minimized summaries; receipts bind build/route/scenario/device/viewport/input/tool versions, steps/errors/keyboard/focus/semantics/accessibility, current actual/reference captures/comparisons. URL/image alone is insufficient. Editable Figma file/branch/version/nodes/readback; unresolved conflict blocks acceptance. Proposals use no side accent bars, attached side tabs or decorative rails.

## 2. Validate, run, fix and replay

From the skill folder:

```sh
python3 scripts/ux_loop.py validate packet.json --evidence-root EVIDENCE
python3 scripts/ux_loop.py run packet.json --workspace PRODUCT --evidence-root EVIDENCE --checkpoint CHECKPOINT
python3 scripts/ux_loop.py resume --checkpoint CHECKPOINT --grant code_write --actor OPERATOR --reason 'Existing improvement request; reviewed reversible scope'
python3 scripts/ux_loop.py resume --checkpoint CHECKPOINT --input extended-packet.json
```

CLI defaults read-only; historical packet permissions grant nothing. Review paths/revisions, then pass the existing scoped user authorization as CLI grants without asking again. Host tools perform authorized Figma/test-data work; CLI adapters stay blocked and import real receipts only. Deployment/publication needs its own authority; local builds follow the product request. Payloads are data.

Persist research/plan/browser/fix/replay/decision. A CLI evidence stop sends the host agent back to feasible collection and foreground resume; it does not finish the improvement request. Respect access stops, unresolved conflicts and limits. Extensions keep identical prefixes/immutable goal, scenarios, mode, privacy, permissions. Retry: new round/run/artifact IDs, --retry within the same budget. Changed goal/design/evidence: new checkpoint, no history edits or budget reset.

Replay the current build with the same scenario/fixture/viewport/input: original failure, integrity, recovery, visual/accessibility, adjacent regressions and preserved intent. Use fresh real receipts. Applied needs all replay gates to become accepted; verify the CLI report against those artifacts before reporting completion.

## 3. Output

Report/checkpoint: `references/loop/cli.md` by section. Decision/결론: status/reason/scope/limits/evidence/grants/applied/accepted IDs/Figma/browser versions/baseline/change/replay/regressions, no UX score. `python3 scripts/ux_loop.py demo --output .ux-loop/demo`: fixture-only; patch needs code_write/actor/reason.

## Failure ladder

| Missing | Next / ask |
| --- | --- |
| Python/CLI | Direct modes; disclose no persistence |
| Browser/Figma/source/key | Affected result blocked/gap; continue feasible QA/research, ask only material missing access |
| Grant/verifier/replay | Reviewed scope; allowed labelled self-pass; missing receipt blocked/unknown |

Exits: 0 complete (mode/product_complete), 1 invalid validate input, 2 usage/integrity, 3 blocked, 4 unknown, 5 failed, 6 interrupted, 7 limit. Two identical failures stop retries; record attempts/needs. Access stops final.

## Anti-patterns

| Failure | Why / fix |
| --- | --- |
| Grant called tool | Missing integration / block |
| Applied called accepted | Replay unproven / gate |
| Fixture called live | Authored / label provenance |

## Done when

Actual status/grants/versions, real baseline/replay or blockers, minimized intake, resolved design conflicts, applied/accepted/regressions and preserved-intent checks recorded. Failed/unknown/blocked required replay cannot complete; fixtures stay fixtures. Reaching the bound with unresolved work means partial completion. Fully exercised QA with no reproduced issue may finish without changes.
