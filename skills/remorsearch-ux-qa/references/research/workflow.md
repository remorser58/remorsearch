<!-- Mode: research. Entry point: `SKILL.md`. -->
# Research mode

Scoped claims/causes/tests from reported experience. In product improvement, use baseline QA to discover questions; standalone research uses the request. Preserve unknowns.

## Phase 0 recap

`SKILL.md` Phase 0; read `references/shared/access-card.md` and `references/shared/evidence-card.md` before search. Korean channels/users: `references/research/korea/overview.md`; language alone: headings. Derive tasks/questions from supplied context and product observations; ask only for material missing access. Reuse grants; label self-checks.

| Depth | Axes / distinct queries | Search-tool calls | Page reads | EXPAND |
| --- | --- | --- | --- | --- |
| quick: quick, brief, 간단히 | 1-2 axes | at most 12 | at most 15 | none |
| standard: default | needed axes, at most 4; at least 4 queries/axis | at most 40 | at most 40, 10/host | 1 round |
| deep: deep, thorough, 깊게, 철저히 | all default axes; at least 8 queries/axis | at most 120 | at most 200, 30/host | up to 2 rounds |

Quick wins; smaller user budgets apply, unmet minima are gaps. **Query**: search string. **Search-tool call**: invocation (batch/retry/failure/pagination). **Page read**: document request (escalation/redirect/API/render). Robots: policy traffic. Log strings/call IDs; batch counts once. Host search discovers leads.

## 1. Start and plan

Run from the skill folder. brief.json: product/url/locale/release/questions/languages/channels/windows/report/budgets/access_policy; validation fields: `schemas/ux-research-brief.v1.schema.json`. First command:

```sh
python3 scripts/ux_research.py start --brief brief.json
```

RUN/runtime/UA/key availability/terms, no key values; missing runtime: interpreter version. Then `python3 scripts/ux_research.py --help`; missing features use failure ladder.

Before dispatch: axes.json/axis-acknowledgements.json/search-ledger.jsonl in RUN (`references/research/audience-pipeline.md` by ID). Create them together before the first search; the command validates every companion first and never writes search receipts:

```sh
python3 scripts/ux_research.py plan --run RUN --manifest plan.draft.json [--acknowledgements ack.json]
```

Assignment rounds index the search stage: discovery only at round 0; expansion only at rounds 1-2 (the two EXPAND rounds); counter_search at rounds 0-2, because required counters arise from initial or expanded findings and run inside the same budgets. Reviewed sanitized team data first, real types. Three source types when available/independent families/segment and counter queries/two changed-version windows; explain omissions.

## 2. Search, pre-read and capture

Task/failure/consequence/competitor/counter queries; log calls/failures. Korean dictionary optional; lexicon.json observed terms. Snippets/summaries: leads.

After discovery, invoke the bundled insane-search toolkit for each selected source. Read its routing body and the linked platform method by section before acquisition:

```sh
python3 scripts/ref.py references/insane-search/SOURCE.md phase-0-특수-엔드포인트-인덱스
python3 scripts/ref.py references/insane-search/references/public-api.md stack-exchange-v23
```

The second command is a platform example; choose the method for the actual URL. Without a section ID, `ref.py` lists IDs only: use a listed ID to load the method body. Resolve SOURCE.md links from `references/insane-search/`; its `references/public-api.md` therefore resolves to `references/insane-search/references/public-api.md`. Links inside a method resolve from that method's directory. Keep the original toolkit intact, including fallback references; load only the needed sections and never redispatch its frontmatter as a skill.

Before invoking the selected method with available tools, apply the access card and pre-read below. Use permitted public routes and the recorded tool capability; a missing tool is a gap. The toolkit does not lift terms, robots, privacy or authorization controls. Stop at unauthorized login, private or paywalled content and human checks; existing site/run stops forbid every alternate method. Automatic installs, identity spoofing, cookie transfer and other methods barred by the access card remain unavailable.

Capture actual output and request provenance. Supported outputs pass through `read` or `ingest` and the existing privacy/provenance checks. Unsupported API/media/CLI output remains a lead until its source is captured through a supported reader path; a summary, snippet or successful command is not a fetch receipt. Never invent fetch IDs, adapter attestations or evidence from missing captures. Log actual requests and failures against the same budgets. Audience research uses this identical acquisition stage before merge, gate and export.

`read` performs all policy checks; `robots` is an optional preflight:

```sh
python3 scripts/ux_research.py robots --run RUN URL
```

Branch: 0 pre-read; 2 correct permitted input; 3 stop, no read/render; 4 gap/no browser; 5 defer, another host then allowed retry. No stop-to-read chain.

```sh
python3 scripts/ux_research.py read --run RUN URL --expect PRODUCT
```

Read: 0 evidence, 2 refusal, 3 stop, 4 allowed untried R3, 5 defer; access-card scope/context/budget. Render: host first or Node.js 22:

```sh
node drivers/web/read_page.mjs URL --out CAPTURE.json
python3 scripts/ux_research.py ingest --run RUN --url URL --context anonymous CAPTURE.json
python3 scripts/ux_research.py author-key --run RUN --platform PLATFORM --handle-stdin
python3 scripts/ux_research.py author-key --run RUN --platform PLATFORM --thread-url URL
```

Thread-key default/partial-IP nicknames; access-card member/cleanup rules. Record fetch/item/capture/type/tool/rung/verdict/context/dates/excerpt/summary/firsthand/flags/scope/denominator. No protected-person link; prompts carry cards/assignments.

EXPAND dedupes leads; stops at depth caps/no leads/two empty rounds. No cap raise/exhaustive claim; record skips/stops/rungs.

## 3. Merge, verify and gate

For recovery, see audience-pipeline.md: Repair a recorded run.

Use sanitized producer imports only. These contract commands require shipped support:

```sh
python3 scripts/ux_research.py merge --run RUN --manifest RUN/axes.json --acknowledgements RUN/axis-acknowledgements.json --search-ledger RUN/search-ledger.jsonl --imports RUN/sanitized-imports.json --returns RUN/returns/stats.json RUN/returns/reviews.json
python3 scripts/ux_research.py gate --run RUN --bundle RUN/bundle.json
python3 scripts/ux_research.py gate --run RUN --bundle RUN/bundle.json --write-bundle
```

Use actual filenames; empty imports/acknowledgements optional. Merge checks quotes/provenance/harvest/budgets; no invented import fetch IDs. Content-bound promotion/incentive/injection/polarity/scope reviews; keep counters, cluster friction. Evidence card; detail: `references/research/source-grading.md` by ID.

Engine: 0 process pass (unsupported allowed), 1 process violation, 2 integrity/schema/provenance/expiry, 3 lock/CAS. Repair or coordinate, no overwrite/failed rows. Annotate, never set status; re-gate changes, recheck hashes/retention.

## 4. Causes, proposals and conditional design

Priority: `references/shared/causal-chain.md`, cause/hypothesis/next evidence, unknown organization allowed; proposal layer/behavior/trade-off/validation/critical states/accessibility. Benefits need measurement.

Authorized design, including product improvement: Figma first for flow/states/hierarchy/variants/tokens/content/accessibility; record grant and actual file URL/branch/version/nodes/readback. Missing Figma blocks affected design, while research/QA continues. IDs/artifacts: `references/research/evidence-bundle-contract.md`.

## 5. Report, hand off and close

`references/research/output-template.md` by section. Decision: up to three findings (ID/status/source quote or number, `Counter: <outcome> - <summary>`), three next steps, coverage; problems/causes/proposals/validation/annex. Unsupported citations: Unverified/Annex/미확정/확인 필요/부록 only. Zero stops omitted; terms/private/planned gaps separate. Dates/statistic cards/tools/rungs/counts/model region/storage/training; semantic review required.

```sh
python3 scripts/ux_research.py report-check --run RUN --bundle RUN/bundle.json --gate RUN/gate.json --report report.md --statements report-claims.json
python3 scripts/ux_research.py export-audience --run RUN --bundle RUN/bundle.json --gate RUN/gate.json --audience-id AU-product-202610
python3 scripts/ux_research.py persona-starter --run RUN --bundle RUN/bundle.json --gate RUN/gate.json
python3 scripts/ux_research.py export-personas --run RUN --bundle RUN/bundle.json --gate RUN/gate.json --hypotheses persona.hypotheses.json --audience-id AU-product-202610
python3 scripts/ux_research.py persona-intake --run RUN --bundle RUN/bundle.json --gate RUN/gate.json
python3 scripts/ergo_qa.py audience-check RUN/audience.draft.json --draft --gate RUN/gate.json --bundle RUN/bundle.json --run RUN
python3 scripts/ux_research.py minimize --run RUN --bundle RUN/bundle.json --gate RUN/gate.json
python3 scripts/validate_bundle.py RUN/bundle.json
python3 scripts/validate_bundle.py QA_PACKET_FROM_QA_INTAKE
python3 scripts/ux_research.py close --run RUN
```

Requested export only; draft cannot compose, no invented weights. When the audience stays empty but gated claims exist, `persona-starter` supplies scrubbed claim cards and field diagnostics. Blocked cards expose only ID/status/reason. The agent authors the behavioral hypothesis with explicit assumptions, expected behavior/decision and falsifying tests; shares/frequency stay unknown. `export-personas` returns an explicitly synthetic QA packet and ergo-scenario templates in `qa_intake.packet`/`qa_intake.scenario_files`, only with provided safe task inputs. Use those returned verified paths for `validate_bundle.py` and the existing QA `--scenario` option. `persona-intake` retrieves the current paths immediately before QA and works after `close` while the gate remains valid. The review copies at RUN/qa-scenarios may lag after an interrupted write. Author actual steps in the QA task's own copied input, validate it and retain its packet/gate/claim IDs; no selector or run is fabricated. See audience-pipeline.md for edit and invalidation rules. Unsafe/stopped/withdrawn/injection material never enters persona prompts. Minimize loop intake. **Retention:** close after quote checks even on failure; deletes pages/salt, reduces URLs. Keep closed scrubbed run/receipts until owner cleanup/retention; API deadlines bind outputs/generations. Identical checked quotes survive close; edits need capture.

## Failure ladder

| Missing/failing | Next step / ask boundary |
| --- | --- |
| Browser/source | Reader/allowed R3 or gap; eligible family, no recovery of withheld content. Ask required access. |
| Key | Supplied no-key answer holds; required environment setting only, no chat secret. Other axes continue. |
| Verifier | Serial/labelled self-check; unresolved flags cannot support. Ask required human/independent review. |
| Engine | Manual unverified assessment; no invented statuses/pass/composable audience. Name missing commands. |

## Anti-patterns

| Failure | Why / fix |
| --- | --- |
| Default eight queries/axis | Deep scope / standard limits |
| Stop then render | Final refusal / branch first |
| URL count corroborates | Repeated people/copies / independent units |
| Complaints set shares | No denominator / unknown or measured frame |
| Gate called truth | Process only / scope review |
| Narrow research becomes a redesign | Preserve request scope; improvement grants stay scoped |

## Done when

Boundary/depth/grants/coverage and traceable labelled evidence; priority cause or labelled hypothesis; proposal behavior/trade-off/critical states/accessibility/validation. Gate/report-check pass or missing-command unverified assessment. Host tools/terms/lifts/reads/stops/rungs, source cards/counters/budgets, authorized membership/API deadlines, valid bundle, close cleanup, requested Figma artifact/readback or blocker. No unauthorized action.
