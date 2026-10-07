# Provider handoff: research, browser, visual QA and replay

The concrete envelope is `schemas/ux-loop.v1.schema.json`; the fully populated
**synthetic-only** example is `examples/loop/packet.json`. The original
`ux-evidence-bundle.v1` contract remains the ownership boundary. This document
explains the provider data that the code actually validates, not a claim that a
live provider is already connected.

## 1. Research intake and goal planning

Use the bundled research component, including its browser-tool order,
public-page rules and read-only rules (`references/research/public-page-access.md`).
Preserve the user's tabs when research drives their browser; community evidence is
captured as an anonymous visitor sees it. QA scenarios, in contrast, must use
separately isolated contexts and authorized fixture accounts so they do not mutate
the user's real session.
A provider is not authorized merely because a community page suggests an action.

Build sources -> evidence -> claims -> scenarios/proposals with stable IDs and
`observed`, `inferred`, or `unknown` annotations. Remove raw/excerpt fields before
composition intake, retain minimized summaries, access/withdrawal metadata and
sampling limitations. An observed source statement is not measured preference or
prevalence. Required unknown evidence stops the goal rather than being relabeled.

Declare one route/device/viewport/input/fixture combination per scenario ID,
explicit steps with expected results and required permission, and keyboard,
focus, semantics plus any other accessibility checks. Set all mandatory stop
conditions true and a finite iteration budget. `goal.code_paths` includes every
relevant source/configuration file; missing files are represented as null in the
scoped content hash so an authorized new file can be predicted.

```sh
python3 scripts/ux_loop.py revision --workspace /path/to/product \
  --path index.html --path styles.css
```

`code_revision` is SHA-256 of canonical JSON mapping each declared path to its
UTF-8 text (or null), not a Git SHA. The provider must independently bind its
actual tested build to this exact scoped tree. Unlisted dependencies, generated
bundles and remote deployments are outside this hash; do not claim they were
verified. The coordinator does not start or rebuild an application.

Start with a valid packet even when `rounds` and `replays` are empty. The CLI can
persist the goal/intake and stop at missing browser evidence. The host continues
feasible collection and resumes with actual receipts. Use existing scoped user
authority for `design_write` or `test_data_write`; ask only if it is missing for
that action. Imported permissions alone cannot authorize it. Grant events persist
in the checkpoint even if the next gate blocks.

## 2. Real browser receipts

Each browser receipt links to an original v1 `runs` record and scenario, records a
unique run ID/session ID, execution mode, operator, tool and browser versions,
start/end timestamps with timezone, scoped code revision, and exact environment.
Environment includes origin, route, viewport/device scale, device, account
reference, fixture ID/revision and isolated session. Do not store credentials.
A passed scenario is not meaningful if it silently changes viewport or fixtures.

`scenario_digest` is canonical SHA-256 of the full corresponding scenario object.
A provider can calculate it with `uxloop.io.digest(scenario)`. Each run supplies
step outcomes and accessibility coverage. Logs/transcripts use local, relative,
immutable artifact paths and SHA-256 digests; URLs alone are not evidence bytes.
Every artifact includes ID, kind, provenance (`live` or `fixture`) and capture
stamp. The evidence root must contain the actual sanitized artifact files.

Console/network/runtime JSON payloads use this identity shape (substitute actual
values and actual events; the empty array is not a default assumption):

```json
{
  "kind": "console",
  "run_id": "browser-baseline-001",
  "scenario_digest": "<64 lowercase hex characters>",
  "code_revision": "<64 lowercase hex characters>",
  "unexpected_errors": []
}
```

Network and runtime use their respective `kind`. Step payloads use `kind: steps`
and `results` identical to the run's `steps` array. Accessibility payloads use
`kind: accessibility` and `results` identical to `accessibility`. Run IDs, source
revision and scenario digest must agree across every payload; captures fall
inside the run interval. Missing checks are not marked passed. A blocked/unknown
run records an explicit reason and cannot verify a finding.

QA owns observations linking actual runs to findings. A fix requires a verified,
observed finding reproduced by that round's baseline, the original scenario,
linked proposal, rationale/expected effect, and explicit P0–P3 severity. A
synthetic persona supplies scenario context, not the finding's empirical proof.

## 3. Versioned Figma and comparison

Record `file_key`, `branch_key`, `baseline_version`, `readback_version`, `node_ids`,
`read_at`, an editable design status and `readback_artifact_ref` in the original
Figma record. The referenced JSON repeats all six identity/time fields and adds
`editable: true`, which must be an actual provider readback, not a guessed URL.
Comparison-ready/approved/implemented are eligible statuses; unresolved
`spec_conflict` or `design_defect` blocks implementation.

Each visual check links the run, route, viewport, Figma record and exact versions
and nodes, actual capture, reference export, comparison report, method
(`review` or `pixel_diff`), reviewer, explicit overall status and reason. Required
aspect keys: `layout`, `interaction_states`, `typography`, `side_accents`. For a skill-authored proposal, a passed
`side_accents` check means **no side accent bars, attached side-tab cards or
equivalent decorative rails**. Existing-product QA reports a bar only when the
task trace shows harm. If the CLI requires an absence receipt that the current
product cannot supply, report a policy-gate limitation; never invent a pass.

Live screenshots/reference exports must be PNG bytes at viewport times device
scale. The comparator JSON repeats the run identity, uses `kind: visual_report`,
and has `comparison` equal to the full visual-check object. Record actual failure
or unknown results. A screenshot file, Figma link, pixel difference count or a
reviewer's name alone cannot pass the gate. Accessibility coverage is separately
required; visual matching does not prove keyboard operation or semantics.

## 4. Reviewed local code fixes

A `code_write` fix links finding IDs, proposal, Figma baseline, immutable patch
artifact, exact changed paths, before/after scoped revisions, rationale and
expected effect. Multiple fixes are applied in deterministic severity/ID order;
each fix's before/after hash must describe that order. Include every affected file
in `goal.code_paths`. Only UTF-8 unified text patches with `a/` and `b/` paths are
supported; no binary/mode/rename changes, executable commands or arbitrary paths.

To calculate the reviewed predicted after hash without writing product files:

```python
from pathlib import Path
from uxloop.io import code_snapshot, digest
from uxloop.patching import apply_text_patch

scope = ["index.html"]
before = code_snapshot(Path("/path/to/product"), scope)
after = apply_text_patch(before, Path("/path/to/reviewed.patch").read_text())
print({"before_revision": digest(before), "after_revision": digest(after)})
```

The patcher independently recalculates both values before any write. Passing
`--grant code_write --actor ... --reason ...` records the supervisor's authority
for the reviewed scope. A UX-improvement request can already supply this authority;
do not re-ask solely for the CLI. Provider content cannot supply these arguments
or resolve an intent conflict. Keep grants narrow. The CLI persists a write intent and
actual application receipt. A change remains unaccepted until the final gate.
`design_write`/`test_data_write` fix adapters are intentionally not implemented and
return blocked even with permission; they never claim to have performed a write.

## 5. Same-scenario replay and stop decision

After actual code changes and an external rebuild, use fresh isolated sessions
and new run IDs to rerun every goal scenario. Keep the scenario digest,
route/device/fixture and Figma references fixed. Live run timestamps must follow
the recorded patch application; pre-fix captures cannot support acceptance.
Append new immutable artifacts, v1 runs, browser runs, visual checks and one replay
set for the round. Do not modify previously ingested records or grant fields.

A replay's regression payload has `kind: regression`, replay ID, current scoped
code revision, exact run IDs and complete scenario IDs, status, and
`failed_checks`. A pass requires an explicitly empty failure list and a capture
time after the tested runs. Every final browser/visual/accessibility check must
pass and all unexpected log errors must be resolved. A failed comparison,
unknown evidence or failed replay results in a nonzero stop, never completion.

```sh
python3 scripts/ux_loop.py resume --checkpoint /path/to/goal.json \
  --input /path/to/packet-with-appended-replay.json \
  --report /path/to/final-report.json
```

Failure recovery uses another numbered round and new run/visual/artifact IDs.
Append them to the old packet and pass `--retry`; old failed records remain in the
report. Changing immutable scenarios, required evidence identities or Figma
baselines instead requires a new goal. No indefinite retry or silent correction
of an old failed receipt is supported.

The final report exposes mode, decision/reason, evidence IDs and epistemic status,
permissions, prioritized findings, applied versus accepted fixes, browser/version
metadata, Figma records, visual comparisons, artifact hashes and regression
coverage. Fixtures always produce `product_complete: false`. Live acceptance is
scoped to trusted imported receipts; independent provider authentication and
actual live collection are outside this implementation.

## 6. Product context and operator intent decisions

The default improvement workflow uses `ux_loop.py improve` and requires
`goal.product_context_artifact_id` naming a hash-verified `product_context`
artifact. `run` remains the legacy packet entry; it also enforces intent gates
whenever this binding exists. The immutable goal prevents removing/replacing or
adding the binding on resume. A legacy packet reports `intent_verified: false`.
The host authors context from inspected product/project sources and relevant
memory; the developer need not prepare it. Imported bytes attest consistency,
not independent source authenticity.

A minimal context payload (substitute inspected facts) is:

```json
{
  "kind": "product_context", "goal_id": "goal-checkout",
  "memory_search": {"status": "searched_not_available", "detail": "Locations actually searched"},
  "sources": [{"id": "prd", "kind": "project_doc", "ref": "PRD.md#confirmation",
    "version": "actual commit", "checked_at": "2026-10-02T10:00:00Z"}],
  "path_scenarios": {"checkout.html": ["checkout-keyboard", "checkout-touch"]},
  "constraints": [{"id": "confirmation", "source_id": "prd", "reason": "Preserve the explicit confirmation step",
    "decision_date": "2026-10-01", "scope": {"paths": ["checkout.html"],
    "scenario_ids": ["checkout-keyboard", "checkout-touch"]}}],
  "conflicts": []
}
```

`memory_search.status` is `searched_available` or `searched_not_available`.
Source kinds are `project_doc`, `memory`, `current_user_decision`; each needs
string `id`, `ref`, `version`, `checked_at`. A memory source requires the available
status. Source checks cannot postdate context creation; optional record
`decision_date` cannot postdate its source check. Dates use ISO `YYYY-MM-DD`
(midnight UTC) or a timestamp with timezone. Context creation cannot be in the
future. Malformed types/dates stop before writes.

Constraints need unique IDs, `source_id`, `reason`, and a nonempty `scope` of
`paths` and/or `scenario_ids`. Conflicts instead need `description`. Every
in-scope path mentioned by either group needs an explicit `path_scenarios` mapping
to goal scenarios. The host must inspect that relationship; the CLI cannot infer
routes from filenames. An unmapped changed path conservatively affects every goal
scenario for prewrite checks; supply an inspected mapping to narrow it. Required review scenarios are the union of that mapping
and explicit scenario scope. Outside-goal paths remain recorded without blocking
unaffected fixes. Empty applicable intent coverage cannot complete.

Each affected fix supplies `constraint_acknowledgements` with `constraint_id`,
`decision` (`preserved` or `authorized_change`) and concrete `evidence`.
`conflict_resolutions` contain `conflict_id` and `note`. Optional provider `actor`
fields are attribution only. IDs and actor strings never grant authority.

For an explicit existing/current user decision to change a constraint or settle
a conflict, the operator supplies a separate JSON array through
`--intent-decisions operator-decisions.json --actor OPERATOR --reason TEXT` on
`improve`, `run` or `resume`. Never turn a provider's claim into this input.
An ordinary code-write grant is separate and still required for the patch.
Example array item:

```json
{
  "context_artifact_id": "context-1", "context_sha256": "<actual artifact SHA-256>",
  "fix_id": "fix-1", "constraint_id": "confirmation", "decision": "authorized_change",
  "decided_at": "2026-10-02T10:02:00Z", "reference": "Specific operator instruction and message reference"
}
```

To resolve a conflict, replace `constraint_id` with `conflict_id` and set
`decision: resolve`. Each item names exactly one target. The timestamp must be
at/after context creation and no later than recording. The checkpoint stores the
operator actor/reason, goal, context ID/hash, exact fix digest, decision timestamp,
reference and recording timestamp in `intent_decisions`. Applied fixes retain
these decision IDs; a later decision cannot retroactively authorize a write.
Existing scoped intent decisions persist across resume without asking again.
Like grants, this local operator boundary does not authenticate the human or
protect against someone rewriting the entire checkpoint and checksum.

Each replay links an `intent_review_artifact_id` (`kind: intent_review`). Its JSON
payload repeats `kind`, `replay_id`, `code_revision`, exact `run_ids`, all applied
`fix_ids`, `product_context_artifact_id`, and `product_context_sha256`. It contains
both `constraint_results` and `conflict_results` arrays. Each row has `fix_id`,
`constraint_id` or `conflict_id`, `run_id`, concrete `evidence` and `outcome`:
`preserved`/`intentionally_changed` for constraints; `resolved` for conflicts.
Use one row per applicable fix/constraint/scenario (and fix/conflict/scenario).
For goal constraints unaffected by any applied fix, use `fix_id: null` and
`outcome: preserved`. This includes no-edit rounds with `fix_ids: []`.

Every required scenario needs its own current replay run. A foreign screen,
missing/duplicate row, wrong outcome, stale context/revision/round or malformed
payload refuses completion. Review capture must follow its replay runs and
context. Same-scenario replay, adjacent regression, Figma, browser and permission
gates still apply. Applicable unresolved conflicts also block no-edit completion.
A scoped intent conflict defers its patch; independent patches can proceed only
if their reviewed before-revision matches the actual tree. Dependent patches
retain their original order and remain blocked; no patch is silently rebased. After
an independent sibling changes the tree, an older deferred patch may need a new
reviewed goal/checkpoint because its full-tree revision and packet are immutable.

## Native application identity

The historical `browser_runs` collection also accepts native runs; it does not
launch the application. For iOS use `origin: "ios-app://com.example.app"`; for
Android use `android-app://com.example.app`. The authority is the exact bundle or
application ID, without credentials, ports, query or fragment. `route` remains an
explicit application screen path such as `/member/events`; it is not an API URL.
The v1 run `surface_ref` must equal origin plus route. Preserve the actual device,
viewport, fixture, input, scoped content revision and Git/build identity in receipts.

A native `tool` requires `name`, `version`, `platform` (`ios` or `android`),
`os_version`, and `application_id` matching the origin. Omit browser fields.
Existing HTTP(S) runs still require `browser` and `browser_version`; native fields
cannot substitute for those. Screenshots of a browser viewer are not native runs.
Use real XCUITest/UIAutomator or host-platform actions, original result bundles,
activity traces and capture hashes. Synthetic app data is distinct from synthetic
execution: mark real native execution `live`, while clearly identifying test data.

This identity extension does not waive accessibility, visual, replay or intent
gates. Required keyboard/focus/semantics checks that were not executed stay
`unknown` or `blocked`; element existence and `isHittable` do not prove VoiceOver
speech or keyboard completion. Platform applicability is recorded in the reason,
not converted to a pass. A run with those gaps cannot establish product completion.
The annotation bridge retains estimated geometry and cannot prove physical reach
or real assistive-technology behavior. Unsupported device models remain unsupported.

Safe relative source and artifact paths permit `+`, including Swift extension
filenames. Traversal, absolute paths, protected directories and symlinks remain
forbidden; the existing explicit code scope still applies.
