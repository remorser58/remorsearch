# UX research report — [product]

## Decision

Include at most three supported findings, then at most three next steps, then one coverage line. Use product-team language and the claim's actual scope. Each finding has this form:

1. **[Claim ID] · [gate status].** [One sentence describing the task, situation and supported finding.] [One short quote or number; source: channel/date/source ID or a direct official-source link.]
   Counter: [none_found | qualifies | contradicts] - [outcome summary; query and source/record ID].

**Next steps**

1. [What to change or test; claim IDs; the observation or measure that would raise confidence.]
2. [Only if needed.]
3. [Only if needed.]

**Coverage:** [Pages read; main non-zero stops; what could not be seen or tested.]

Remove unused slots. Supported statuses are `supported_high` and `supported_medium`. Copy each status and counter outcome from the matching gate record; identify the record and input version in the evidence map. Unsupported claims belong in the annex. If the gate is unavailable, name that blocker and retain candidates there; do not claim a gate run. Label invented example inputs and illustrative gate outputs as fixture data, with execution explicitly false. Fixture outputs illustrate report fields; synthetic content cannot support live research claims.

For Korean reports use [the Korean template](korea/report-template.md), with the same order.

## Findings

Explain the decision findings in task terms: what the evidence establishes, its boundaries and the test it motivates. Cite the same claim IDs and statuses. Distinguish a report of an experience from a reproduced current-product failure. Reported existence establishes neither prevalence nor cause. Keep optional detail only when it changes the test agenda.

## Evidence map

Gate record: [artifact/link, input version or hash, rules version, generated time; executed or illustrative fixture].

| Claim ID and scoped statement | Gate status | Sources and supporting excerpt/number | Fit/grade and independent units | Published / observed / valid at | Counter-search outcome, summary, query and record |
| --- | --- | --- | --- | --- | --- |
| [C-01 — statement] | [supported_high/medium] | [source IDs; channel/date; short evidence] | [claim-kind grade; units/families] | [dates; unknown where missing] | [outcome; summary; query; evidence ID] |

Copy grades/statuses from the gate; retain their scope and qualification. Cite official/product sources directly when usable links exist. Shared reports cite community sources by channel/date/source ID; post URLs stay in the bundle. Paraphrase first, add only a short verbatim fragment, and attribute it as the author's unverified statement. Keep scrub placeholders unchanged. No names, handles or profile links. Sensitive or authorised-member material uses summaries under its access rules. Add API retention dates only when applicable.

## Segments

Create interview-ready cards organised by situation and task. Segments may overlap. Each empirical field links to a supported claim and its gate status. Leave shares `null` unless a fitting measured/statistical source supplies the population, denominator, period and product relationship. Posts, reviews, likes and profile coverage supply no population share.

### [Segment ID] · [behaviour-based description]

- **Situation:** [Trigger and use context; claim ID + status.]
- **Task:** [What the person is trying to finish; claim ID + status.]
- **Pain:** [Reported effort/failure and its scope; claim ID + status.]
- **Evidence status:** [Claim IDs, gate statuses, sources and transfer limits.]
- **Share:** `null` [or value with fitting source, n, population and reference date].
- **Unknown:** [Product transfer, frequency, device/input or condition fields lacking evidence.]
- **Interview recruitment:** [Observable screening question about the situation; avoid inferred demographics.]
- **Interview prompts:** [Recent concrete episode; actions before/after the friction; recovery or counterexample.]

## Cause hypotheses

Label every cause as a hypothesis unless independently verified. Ground it in supported findings; preserve unsupported empirical premises in the annex.

| Hypothesis | Supported observations and claim statuses | Proposed mechanism | Alternative/counterevidence | What remains unknown | Test that could reject it |
| --- | --- | --- | --- | --- | --- |
| [H-01 — inferred] | [C-01; status] | [screen/information → behaviour → consequence] | [plausible competing account] | [implementation/organisation constraints] | [observable disconfirming result] |

## Proposals and test agenda

| Proposal | Problem and claim statuses | Layer and change/test | Intended behaviour change | Trade-off | Owner, order/timebox | Evidence that raises confidence; acceptance observation |
| --- | --- | --- | --- | --- | --- | --- |
| [T-01] | [C-01; status] | [copy/interaction/information architecture/service rule/data system] | [what the user could do differently] | [cost or competing need] | [role; next slot] | [task, measure, success and disconfirming result] |

Specify the scenario, recruitment condition, test data, happy/recovery states and measurement needed to schedule each test. Treat expected benefits as hypotheses. Record approval or operational dependencies when they affect scheduling. Research recommendations do not constitute a release verdict or an observed product severity.

## Figma flow — include only when the user requested a design change

Remove this entire section for other requests. When included: file URL; version/readback; page/node IDs; flow; components/tokens; loading, empty, error, permission and success states relevant to the change; responsive/accessibility behaviour; implementation acceptance criteria. If the requested design handoff is blocked, name the missing file/version/access. A research-only request needs no empty Figma section.

## Coverage appendix

Scope and method follow findings, segments and proposals.

- Question, product/surface, research dates, depth, active/skipped axes and time window.
- Searches and page reads against budgets; EXPAND rounds; host page counts. Count page reads, unique URLs and repeated/preflight calls separately.
- Tools actually used, access card read before the first search, browser context, and available tools that could not run. Each reader/verifier task carries the applicable evidence/access card in its instructions.
- Channels read; official/team-provided sources; under-covered situations; untested current-product behaviour.

Depth limits: quick has 1–2 axes, ≤12 searches, ≤15 page reads, no EXPAND; standard has at most 4 relevant axes, ≥4 queries per axis, ≤40 searches, ≤40 reads/10 per host, 1 EXPAND; deep uses every default axis, ≥8 queries per axis, ≤120 searches, ≤200 reads/30 per host, up to 2 EXPAND rounds. Record the chosen plan and actual counts.

| Host/channel | Pages read | Access rung/tools/context | Unread and untried rungs | Closed channel or access gap |
| --- | --- | --- | --- | --- |
| [channel] | [n] | [actual method] | [n; reason] | [recorded scope and reason] |

Report only stop classes with a non-zero count; keep zero counts in the bundle. Distinguish unique stopped pages from repeat attempts. Show `terms_restricted` separately. Follow the access policy's recorded scope and `lift_requires`; status alone supplies no lift permission. Closed channels without requests are planned gaps, and private channels/refused discovery routes are out of scope. Do not fetch withheld material by another route.

| Stop class | Count and unit | Host/channel | Reason code and stop scope | Next evidence |
| --- | --- | --- | --- | --- |
| [non-zero class] | [URLs or attempts; specify] | [channel] | [record] | [allowed independent source/team data/interview] |

**Keys missing:** [None, or environment variable, official route and affected coverage; no alternate route.] Include real API usage/retention, signed-in authorisation, user terms checks, out-of-scope counts, and processing/ethics constraints only when relevant to this run. Legal questions appear only if the brief/run raised one; put unresolved legal application in an optional counsel annex.

## Annex: unsupported claims and next evidence

Keep `single_voice`, `lead_only`, `conflicting`, `stale`, `needs_product_check` and `unfit` claims only here. Explain contradictions on both sides. Keep speculative demographics, unsupported sizes and untested product assertions here too.

| Claim ID | Statement | Gate status or gate unavailable | Why unsupported | Next evidence/test |
| --- | --- | --- | --- | --- |
| [C-02] | [statement] | [status] | [scope/provenance gap] | [specific source or product replay] |

## Writer self-check

- Decision first: ≤3 findings with ID/status, sourced quote/number and `Counter: <outcome> - <summary>`; ≤3 next steps; one coverage line.
- Every claim cited has its gate status and matching source; unsupported empirical claims stay in the annex; hypotheses/proposals are labelled.
- Any observed P0/P1 imported from QA has its capture receipt and second pass; research-only reports mark that check inapplicable.
- Segments are interview-ready; shares remain null without fitting sources; proposals state behaviour, trade-off and the confidence-raising test.
- Only non-zero stop rows; Figma/legal detail is conditional; no names or handles; what was not tested is stated.
