# Source Grading

A grade belongs to a source and claim kind, not to a URL alone. Research, persona
QA and ergonomics use these rules. Commands below are the engine contract; check
help before using them. If unavailable, label the assessment “graded by hand;
no gate” and keep research verification unverified. Never author a gate pass.

## 1. Claim kinds and fit

A: direct fit, one suffices. B: needs independent corroboration except the single
statistical bound rule. C: can back a B from another channel, never lift alone.
D: context/lead. E: unfit, never support. None-family sources are always E.

| Claim kind | measured | statistical | estimate | intent | voice | secondary | expert_judgment |
| --- | --- | --- | --- | --- | --- | --- | --- |
| segment_exists | A | B | C | C | B | C | D |
| segment_share | A | B | C | E | E | D | E |
| device_mix | A | B | C | E | E | D | E |
| condition_presence | A | B | C | D | B | C | D |
| condition_share | A | B | C | E | E | D | E |
| context_of_use | A | C | C | D | B | C | D |
| task | A | D | C | C | B | C | D |
| pain_point | A | C | C | E | B | C | D |
| workaround | A | E | D | D | B | C | D |
| product_behavior | D | E | D | D | D | D | D |
| intended_behavior | D | E | D | A | D | C | D |
| prevalence | A | B | C | E | E | D | E |
| user_preference | A | B | C | E | E | D | E |
| real_user_preference | A | B | C | E | E | D | E |
| discomfort | A | B | C | E | E | D | E |

segment_exists, condition_presence, context_of_use, task, pain_point and workaround
establish existence. Shares/device_mix establish size. Preference, prevalence
and discomfort are population claims needing measured support. Use pain_point
for “some users report X”. product_behavior needs product observations;
intended_behavior establishes intent only.

## 2. Source families

| Family | source_type |
| --- | --- |
| measured | product_analytics, non-vendor survey, interview, usability_test, support_tickets |
| statistical | official_statistics, research_paper |
| estimate | market_report, competitor, vendor-stake survey |
| intent | official_docs, product_brief |
| voice | community, app_store_reviews |
| secondary | news |
| expert_judgment | expert_judgment |
| none | llm_output, synthetic |

Korean approved/admin statistics use official_statistics; stated-n institute
surveys research_paper; app/traffic/ad panels market_report; agency documents
with counts official_docs. Case/complaint/monitoring counts are count_only:
existence, never size. Use the cards in `references/research/korea/statistics.md`.
A curated team review export remains voice. producer_stake is official/independent/vendor; vendor surveys are estimate.

## 3. Downgrades and verifier decisions

Apply independent one-grade steps first, clamped at E, then every cap; lowest
wins. Never raise a grade to compensate for another flag.

| Condition | Effect |
| --- | --- |
| Missing published_at; secondhand; unclear context; authorized member content | One step for each |
| Confirmed promotion/affiliate/seller tie | At most D |
| Confirmed review incentive: satisfaction/preference, counter result, star average | At most D |
| Confirmed incentive: pain_point/workaround | Voice B caps C; does not push existing C further or raise D/E |
| Seller event notice/platform-wide points | Candidate only; reviewer’s own trace required, no whole-page cap |
| Confirmed disclosed virtual person | E |
| Platform own-brand review | At most D until independent A/B from another channel; then remove only this cap |
| Seller-managed board | Grade unchanged; absence of complaints is not counter evidence |
| Uncertain polarity/sarcasm | No satisfaction/preference or qualifying counter use |
| Snippet/teaser/model-written summarizing fetch | At most D |
| Injection uncleared for its exact capture | E |
| Stopped/deleted/withdrawn/LLM/synthetic | E |
| Copy-paste text | One independence unit |
| Missing capture independence provenance, institutional producer or channel identity | At most D; do not invent units |
| Community modelled demographics | At most D; never attributes of a poster/persona |

Flags are candidates. A verifier records typed promotion, incentive, virtual_person,
polarity, injection or scope decisions with target ID, capture/content hash and
reviewer role. Incentive/polarity are excerpt-specific; source promotion/injection
clearance applies only to that capture. Excerpt clearance cannot override source
injection. Unresolved promotion/incentive/virtual candidates used for support need
review (exit 1). Conflicting decisions cannot be resolved by choosing the newest.

Complete disclosure/label forms matter, not isolated words. Negated, quoted or
questioned mentions are not disclosures. “Too many ads” is a complaint.
Self-declarations (“not an ad”, 내돈내산) have no weight. With promo_check text_only,
say “disclosure not checked”, not “no disclosure”. Record wording/position but
relationship caps do not depend on position. Apply Korean disclosure rules in
force at published_at (2020-09-01, 2024-12-01, 2026-06-01); unknown date permits
checking presence only, not judging position. See promotion.md and markers.json.

## 4. Independence and denominators

Count voice by a capture-attested salted author key, otherwise an attested thread key.
Without item/author attestation use one captured page/thread unit, identity unknown.
Default anonymous names and partial-IP handles are not person identities.
Blogs hosted by path/subdomain count by author, not portal. Institutions count
by producing organization; statistics portal tables use their producing agency.
Normalized aliases count once. Two organizations on KOSIS can be independent.
A Naver blog and Tistory blog are two people/one blog family; a blog and App Store
review are two families. DCInside and Naver Cafe are one community family.
Commerce reviews are one family. Copied press releases count once.

- Repeated: at least two people.
- Corroborated: at least two independent units across two channel families, or
  two units with one measured/statistical B. One measured A is sufficient.
- One statistical B with producer: medium bound, not corroborated. A lone B from
  another institution is lead_only.
- Per author/thread per run: three sources and five excerpts maximum, including
  context. Exceeding either is exit 1. No cross-run identity joins.

Size/population/weight/frequency support needs a neutral population, period,
product relation, sampling frame, n (or defined census), method and printed unit/
value. Posts/reviews/likes/complaint counts and star averages are never denominators.
Voice counting support for a numeric value is exit 2, even with measured support.
Voice context is allowed. Each exported share/weight component needs value_checks
tied to the printed number; no guessed percentage or automatic normalization.
Statistical general-population values stay bounds, never the product user share; export keeps them separately. Comparable estimates
name the comparable product/date. Device mentions are leads, never device_mix.

## 5. Currency and status order

published_at is publication; observed_at is read time; valid_at/version/reference
period describes when content was true. Current claims need brief release_date.
Missing release date is stale plus exit 1. Unknown/old effective dates cannot
count as current; a later reread does not update truth. Split platform-policy
changes into separate windows; do not compare numbers across them.

First matching rule wins:

| Status | Rule |
| --- | --- |
| conflicting | Unresolved counter evidence/result or expired-counter gap |
| stale | about_current_version && (missing_release_date || no_current_potential_support); historical claims are not stale for this reason |
| needs_product_check | product_behavior without observed same-scope completed-run observations |
| supported_high | product_behavior with those observations and no earlier blocker |
| unfit | Non-product, nonempty support, all E |
| lead_only | Empty support or no eligible A/B |
| supported_high | One A; or two B units corroborated above |
| supported_medium | Two B voice units (people/threads) one channel; B+C independent other channel; or single statistical B |
| single_voice | One B voice person/thread |
| lead_only | Remaining cases, including lone non-statistical institutional B |

Only supported_high/medium becomes verified, epistemic observed, confidence
high/medium, and can motivate P0/P1. Others are unverified/exploratory and withheld
from audience export. Observing product behavior never upgrades a population
claim. gate --write-bundle preserves original support inputs while partitioning
non-counting evidence into context. Counters remain visible.

## 6. Counter-search and consumption

Required when subject joins a primary segment, stakes high, any share/weight is
set, or claim motivates P0/P1 (typed scenario joins also count). Record
counter_search `{call_ids, read_source_ids, counter_evidence_ids, outcome,
summary, resolution_id, replaces_call_ids}` (last field optional). Calls must be completed logged counter-searches;
all source/evidence IDs must exist and be read. Outcome none_found/qualifies/
contradicts. Contradicts needs contrary excerpts; qualifies needs typed scope
resolution. Free-text resolution cannot erase contrary evidence. A verified
strict version/period scope change creates a new claim, preserves the old conflicting one and
shows why each contrary item is disjoint. Unknown scope is not a resolution.

```sh
python3 scripts/ux_research.py gate --run RUN --bundle RUN/bundle.json
python3 scripts/ux_research.py gate --run RUN --bundle RUN/bundle.json --write-bundle
```

Exit 0 process pass (unsupported claims can remain); 1 process violation; 2
integrity/size/reference error; 3 lock/write conflict. Failure invalidates gate.json
and writes gate_failed.json. Only gate writes research verification. Consumers
require the committed gate, the common whole-input hash and live retention checks.
Read-only expiry refuses; --write-bundle purges and repairs dependent claims with
a gap. Expired contrary evidence stays blocking until a new counter-search.

Export evidence kinds: voice/interview/usability/tickets firsthand; analytics/
survey/statistics statistic; intent official; estimate statistic with printed
number, otherwise inference; expert inference. News is withheld from automatic
export; a value that needs news to reach support is withheld too. Measured product shares map measured, qualifying estimates estimated;
no share maps unknown/null. Official population bounds remain separate.

## 7. Credit

Computed claim status, independence, data-flow checking and annex placement were
informed by studying insane-research (github.com/fivetaku/insane-research, MIT,
Copyright 2026 fivetaku). No code or text was copied. Grades depend on claim kind;
voice independence counts people/threads rather than portals.

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

Mobile spelling alone never merges resources. Proven capture trails establish
final URLs; exact copied text counts once even when resource aliases stay separate.
The engine uses an atomic manifest and one writer lock; its tests cover injected
commit interruptions and lock contention, not an exhaustive process-kill matrix.
