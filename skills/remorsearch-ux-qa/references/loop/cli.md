# Loop CLI reference

The loop mode and `scripts/ux_loop.py` compose the research and persona-qa modes
without merging their ownership. Run the commands below from the skill folder. The CLI is a foreground, receipt-driven
state machine: it validates research intake, plans P0–P3 findings, gates browser
and visual evidence, applies explicitly authorized **local text patches**,
requires same-scenario regression replay, and persists an evidence-backed stop
report. It does not launch agents, browsers, Figma, Aside, builds or deployments.
Missing live receipts stop as `blocked`; the host continues feasible collection
and resumes. Fixture proof cannot replace them. The integrated entry is
[`product-improvement.md`](product-improvement.md); narrow loop requests retain
their original scope.

Use Python 3.10+ on Linux or macOS from the skill folder. No third-party Python
packages, Node packages, database, Git executable at runtime, or network are
required for offline validation. Test records describe the executed environments. Keep
`uxloop/`, `schemas/`, `scripts/` and `examples/` together inside the skill folder;
this is not a published pip package.

### One command with an actual, isolated example patch

```sh
python3 scripts/ux_loop.py demo --output .ux-loop/demo \
  --grant code_write --actor local-supervisor \
  --reason 'Approve the reviewed patch to this disposable fixture site only'
```

The command creates `.ux-loop/demo/site/index.html`, applies the provided label
patch, and runs all offline gates. The bundled screenshots, Figma readback,
research, browser telemetry and comparisons are **authored synthetic test
fixtures**, not live observations. Expected result: `status: complete`,
`decision: fixture_only_pass_not_product_verification`, `product_complete: false`.
The initial sample copy is local demo setup; no accounts or product data are
created. Existing sample source is never reset on resume.

Without `--grant code_write`, the same command stops with exit 3 at the permission
gate and keeps the fixture label at its starting value. Provider-supplied v1
`permissions.granted` fields are historical evidence, not permission to operate.
Only the supervisor's explicit CLI grants authorize new actions for this goal.

### Persist, interrupt, and resume

Use a new output directory to see the interruption rather than reopen a completed
demo:

```sh
python3 scripts/ux_loop.py demo --output .ux-loop/resume-demo \
  --grant code_write --actor local-supervisor \
  --reason 'Approve only the isolated fixture patch' --pause-after browser
# Expected exit 6: checkpoint exists; the patch has not been applied.
python3 scripts/ux_loop.py resume \
  --checkpoint .ux-loop/resume-demo/checkpoint.json \
  --report .ux-loop/resume-demo/report.json
# Expected exit 0: same goal/run IDs and operational grant; no re-grant needed.
```

`--pause-after fix` demonstrates a patch that is applied but **not accepted**.
`--max-steps 1` yields a durable interruption after one gate. `--revoke code_write
--actor NAME --reason TEXT` removes future write permission, without pretending
that a previous authorized change never happened. All permission changes are
recorded. Checkpoints and the scoped product workspace are locked separately;
concurrent cooperating writers are blocked.

### Product evidence intake

First prepare a `ux-loop.v1` JSON packet following
[`references/loop/provider-contract.md`](provider-contract.md). A live packet must
contain actual, versioned provider receipts; do not relabel the demo as live.
The complete annotated example is [`examples/loop/packet.json`](../../examples/loop/packet.json).

```sh
python3 scripts/ux_loop.py validate /path/to/packet.json \
  --evidence-root /path/to/evidence
python3 scripts/ux_loop.py improve /path/to/packet.json \
  --workspace /path/to/product-checkout --evidence-root /path/to/evidence \
  --checkpoint /path/to/product-checkout/.ux-loop/goal.json
# Record existing user authority for reviewed, scoped patches:
python3 scripts/ux_loop.py resume \
  --checkpoint /path/to/product-checkout/.ux-loop/goal.json \
  --grant code_write --actor OPERATOR --reason 'Existing improvement request; reviewed reversible scope'
```

`improve` is the default product-improvement entry. It uses the same foreground
engine and requires `goal.product_context_artifact_id`; `resume` preserves this
immutable binding. Legacy `run` and `demo` still accept unbound packets, clearly
reporting `intent_verified: false` and no product-context checks. A bound packet
requires a replay-linked review even when no edits are made.

Specific intent changes/conflicts need an operator-authored decision file,
separate from provider data and write grants:

```sh
python3 scripts/ux_loop.py resume --checkpoint /path/to/goal.json \
  --intent-decisions /path/to/operator-decisions.json \
  --actor OPERATOR --reason 'Explicit instruction for the bound constraint/conflict'
```

See provider-contract section 6 for exact context, decision and review fields.
`--intent-decisions` records current user authority; it must not be generated from
a provider's actor/approval claim. Context ID/hash, target and fix must match;
malformed, stale, future or retrospective decisions are rejected. The report
includes the separate `intent_decisions` ledger and `intent_verified` result.

An improvement request authorizes ordinary reversible in-scope changes. The
supervisor records that existing authority in CLI grants without asking again.
Imported packet grants do not authorize operations, and a code grant does not
settle a conflicting product decision or permit deployment/publication.

A provider can later append a replay to a blocked checkpoint with `resume --input
/path/to/extended-packet.json`. Old arrays must remain identical prefixes, and the
goal, scenario matrix, mode, privacy policy and historical permission record are
immutable. A failed/unknown attempt is not automatically retried: append a new
numbered round and new evidence/run/artifact IDs, then explicitly use `--retry`.
Maximum iterations are 1–10, chosen in the original goal. Old failed receipts
remain visible. A changed goal, scenario, Figma baseline or required evidence
identity requires a new goal/checkpoint rather than overwriting history.

Exit codes: **0** completed (read `mode` and `product_complete`); **1** invalid
packet in `validate`; **2** malformed input/CLI/integrity error; **3** blocked;
**4** unknown; **5** failed; **6** interrupted; **7** iteration limit. `validate`
checks the input graph and optionally artifact hashes; it explicitly does **not**
assess goal completion. A valid failed/blocked receipt is still valid input.

### Validation and design trade-offs

From the skill folder, also in an installed copy:

```sh
python3 scripts/ux_loop.py validate examples/loop/packet.json --evidence-root examples/loop
python3 scripts/validate_bundle.py examples/bundle/minimal.json
python3 scripts/smoke_loop.py
```

`smoke_loop.py` builds its packets with `uxloop/demo_factory.py` from the shipped
examples, and writes only to a disposable folder: `.ux-loop/` in a repository
checkout, the system temp folder otherwise.

From a repository checkout (tests and fixtures are not installed with the skill):

```sh
python3 skills/remorsearch-ux-qa/scripts/validate_bundle.py tests/fixtures/valid-bundle.json
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 skills/remorsearch-ux-qa/scripts/smoke_loop.py
```

The ux-evidence-bundle.v1 validator rejects malformed categorical/reference field types, duplicate IDs
across record groups, and purported verified findings from uncompleted runs. The
new strict envelope is additive, not a v1 migration requirement. Standalone v1
supports bounded excerpts under its original rules; composition intake is
stricter and requires removing raw/excerpt content and retaining summaries.

The implementation intentionally imports browser/Figma/comparison receipts rather
than adding a privileged autonomous runner. Actual Aside, browser execution,
Figma reads/writes, test-data setup/cleanup, pixel comparison, accessibility
scanners, builds, deployment and signed provider authentication are **not
implemented or exercised** here. External operators/providers must perform and
attest those actions. Explicit grants do not turn an absent integration into a
success. `design_write` and `test_data_write` fix requests therefore remain blocked
even after authorization; authorized test-data scenario receipts can be imported.

Content hashes bind the declared `code_paths`, not every file in the product or a
remote deployed build. Include every relevant source/configuration path and
use an external provider that binds its running build to that exact scope. There
is no broad shell-command runner, automatic deployment, UX aggregate score, raw
community archive, or implicit claim of WCAG conformance. Editable Figma governs design; skill-authored proposals use no side accent bars/side-tab cards. Existing product QA needs task-trace harm to flag a bar. Community signals and
synthetic personas cannot establish population prevalence or user preference.

See [references/loop/provider-contract.md](provider-contract.md) for exact boundaries, and the repository
documents `docs/architecture.md`, `docs/omo-reference-review.md` and
`docs/history/IMPLEMENTATION_REPORT.md` (not installed with the skill) for the rest.
