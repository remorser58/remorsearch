# Evidence Bundle Contract

Research and QA share ux-evidence-bundle.v1. This graph records provenance, not
representative sampling. Copies in research/ and persona-qa/ stay byte-identical.
Commands are the engine contract; check help. If unavailable, keep research
unverified with labelled manual assessment; do not author a gate pass.

## Permissions and graph

permissions has requested, granted and blocked [{capability, reason}]. Capabilities
are read_only/design_write/test_data_write/code_write. Each requested capability
is granted or blocked, never both; proposals cannot lift a block.

records has ten arrays: sources, evidence, claims, personas, scenarios, runs,
observations, findings, proposals, figma. IDs are globally unique. Links are:
source_id, evidence_ids, persona_id, scenario_id, run_id, observation_ids,
finding_ids, claim_ids, figma_id. Optional claim counter_evidence_ids,
context_evidence_ids and original research support/context IDs are also validated,
as are counter-search source/evidence, audience and scenario motivation links.
Present optional lists may be empty; nonempty required support is checked by kind.

Evidence/claims/observations/findings use epistemic_status observed/inferred/unknown.
Verified requires eligible observed support, never inference alone. A research
product_behavior can have evidence_ids empty with observed same-scope observations
from completed runs; missing product observations yields needs_product_check.
Other research candidates can be empty/unverified, yielding lead_only. No dummy
source. Existing QA bundles keep legacy checks; their structural validity cannot
bypass the research gate. Optional fields are checked even in legacy records.

## Source provenance and privacy

Sources require channel/source_ref/access_basis/access_method/public_scope/
retention_status. Research adds source_type/family/channel family, producing org,
salted author/thread identities (nullable), published_at/observed_at/valid_at/
version, privacy_class, flags, promo_check and provenance. Reader provenance has
fetch_id/content_sha256 and access rung/presentation/verdict/stop/fetched_at/
robots/context/terms; it must match a successful authoritative capture and quote.
A known fetch ID alone is insufficient. Every excerpt keeps its actual capture,
not a later header's more convenient flags/dates.

Research access bases: public_anonymous/public_teaser/official_api/team_provided/
authorised_member/fixture. Older QA can say public. Import provenance has
import_id/content_sha256, sanitized artifact and app/product/territory/date/
permission provenance; never fake fetch_id. Automatic raw-export scrubbing is
outside this contract: producer supplies sanitized, reviewed text; unsafe imports
are refused. Source types/families/grades follow source-grading.md. Statistical
size support needs stat_card frame/reference_period and neutral denominator.

Terms lift_requires controls never/written_permission/terms_check; reported/
confirmed status is evidence quality only. No source field authorizes a lift.
Leads/stops/withdrawn/deleted/redacted/LLM/synthetic cannot count as verified support.
Official_api needs authoritative retention_until. Recheck at consumption; expiry
purges content and repairs claims with gaps. Non-content deleted tombstones are
allowed; deleted status with an excerpt is not a waiver. Expired counters require
new counter-search, not silent removal. New captures must recheck their quotes.

Quotes come from scrubbed text, max 300 normalized characters/five per source.
Placeholders remain. Never retain handles/profiles/IPs/contact/identifier numbers.
Protected cues cannot link to an author/thread via any source/locator/alias or
reverse reference. Remove the entire personal component or seek actual aggregate
evidence; an unlinked segment hypothesis remains unsupported. Salted keys are
still identities. Skip apparent minors. Shared member/API and sensitive-channel
content is authored summary only without personal locators or quotes.

## Claims and gate

claim_kind uses source-grading.md. Research claims have typed subject/scope,
about_current_version, stakes, scenario_priorities, audience_values, support/
context/counter/observation links and counter_search receipts. Original
research_support_evidence_ids/research_context_evidence_ids and
research_epistemic_status survive regrade. Do not manually partition to obtain
support. Verifier decisions bind kind/target/capture/content hash; no free-text
promotion/injection/polarity or contradiction clearance. Typed scope change
creates a new claim and preserves the old conflict.

```sh
python3 scripts/ux_research.py gate --run RUN --bundle RUN/bundle.json
python3 scripts/ux_research.py gate --run RUN --bundle RUN/bundle.json --write-bundle
python3 scripts/validate_bundle.py RUN/bundle.json
```

Gate alone writes verification. Pass may retain unsupported claims. Conflict/
currency precede observations/support. Gate exits 0 pass/1 process/2 integrity/
3 contention; failure invalidates gate.json and writes gate_failed.json.
Standalone validator exits 0 valid/1 contract error/2 usage-I/O. Schema owns
shape, validator owns links/observations/retention, gate owns grading/independence/
process/denominators/currency/export eligibility. Validator success is not a gate.

Research root envelope and external merge receipt bind run/manifest/log/rules
and provenance. Removing the envelope or marking a bundle legacy cannot bypass
fresh gate checks. Consumers recompute supporting/context/counter source,
observation/run, brief/version, rule, independence and verifier inputs in one
whole-bundle hash.
Status writes do not change input hashes. Regrade is idempotent; live retention
still applies even when hashes match. Interrupted/competing writes cannot publish
an accepted mixed bundle/gate generation.

## Audience and synthetic boundary

Export is ux-audience-draft.v1, incomplete/non-composable. No invented age/devices/
tasks/data/frequency/criticality. bundle_ref is a source-ID string; typed segment/
entity/field value_provenance carries claim IDs/the common input hash/eligible contributing records. News is
withheld from automatic export; official population bounds stay bounds. Completed
research audiences need audience-check --gate --bundle --run, comparing exact
values and joins, not a supported source somewhere.

Synthetic personas require adapter_revision/schema_fingerprint/seed/shard_or_config,
max_scanned_rows/max_bytes_read/timeout_ms, selected_record_ids/filled_strata/
unfilled_strata/stop_reason/original_attributes/scenario_assumptions. Keep original
attributes separate from test assumptions. They do not support real-user preference,
prevalence or discomfort. Audience-composed personas remain basis synthetic and
carry audience_ref {audience_id, segment_id, facet, claim_ids}; claims must exist.
Findings may list segments_affected, never inferred shares of users affected.

## Loop hand-off and Figma

```sh
python3 scripts/ux_research.py minimize --run RUN --bundle RUN/bundle.json --gate RUN/gate.json
```

Writes bundle.min.json/minimize.json with safe authored summaries/required graph,
no nested excerpt/raw/body/text/quote or personal locators. Missing summary refuses.
Projection keeps permissions, cannot regrade/export and cannot relabel population
bounds as measured users. Exits 0 success/1 unsafe or missing summary/2 stale gate,
expiry or integrity/3 contention. Loop intake rejects excerpts; use the projection.

Figma comparison records file_key/branch_key/baseline_version/node_ids/read_at/
readback_artifact_ref/design_status. Defect class: implementation_defect,
design_defect, spec_conflict, approved_deviation. Baseline/readback conflict stays
unverified until resolved.

Claim identity includes only joins and values, never their proofs. Gate hashes the
whole normalized input bundle with process/rules inputs and regrades every claim.
There is one writer lock and a manifest pointing at the committed snapshot;
consumers read that snapshot. No journal, mirror recovery or compare-and-swap.

Without capture-bound item/author attestation, identity is unknown and the whole
page/thread is one independence unit. `[author]` and `---` are hints only.

Proportion proof applies only to shares/weights. Task amounts, counts and durations
may be any safe scalar proved by completed product observations or approved brief values.

Shared community/review/social citations use channel, date and source ID; report
bodies may not contain their URLs. Official/statistical URLs remain allowed.

Minimize checks field allowlists, identifier patterns and retained quotations.
Authored summaries/statements/results need a content-bound reviewer attestation;
a mechanical pass does not prove authorship.

Legacy product verification without completed observed runs remains structurally
valid with a plain-validator warning; research consumers refuse it.

Mobile spelling alone never merges resources. Proven capture trails establish
final URLs; exact copied text counts once even when resource aliases stay separate.
The engine uses an atomic manifest and one writer lock; its tests cover injected
commit interruptions and lock contention, not an exhaustive process-kill matrix.
