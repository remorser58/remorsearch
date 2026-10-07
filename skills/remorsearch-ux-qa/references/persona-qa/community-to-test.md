# Community Signal to Test

## Conversion chain

```text
Gate claim ID (pain_point, workaround or context_of_use)
→ community statement (scrubbed excerpt, with its grade and status)
→ user situation
→ task or decision
→ suspected friction
→ browser scenario
→ verified observation
→ UX finding
```

Start from a claim that research mode's gate has graded (`references/research/source-grading.md`). A `supported_high` or `supported_medium` claim may motivate a P0/P1 scenario. A `single_voice` or `lead_only` claim gives an exploratory scenario only. If gate is unavailable, label a manual assessment and keep claims unverified; never write gate statuses by hand. Observed product severity still follows impact.

## Example

The IDs below are illustrative.

```text
Claim:
CLM-4e1b20c9 (pain_point), supported_medium: two people in one channel family.

Community statement (EV-7d3a5b12, grade B, read by the reader at R2, ok_strong):
“상세 페이지를 보고 돌아오면 검색 조건을 다시 넣어야 한다.”

User situation:
The user compares several results under a price and delivery filter.

Task:
Select one result after checking details.

Suspected friction:
List state is lost during list-detail navigation.

Browser scenario:
Apply a filter, open two details, return through browser back, and inspect
filter, sort, scroll position, and result order. The scenario cites CLM-4e1b20c9.

Verified observation:
Record which state was preserved and which state was reset.

UX finding:
State loss is a P1 issue only if it blocks or materially slows the task.
Otherwise classify it as P2 friction.
```

## Community source checklist

- Is this firsthand or secondhand?
- Is the task and context clear?
- Is the product version or date known?
- How was the page read: which tool, which rung, which verdict? Was anything stopped?
- Does the same issue appear in another channel?
- Does corroboration come from other people and other channel families, not from other URLs on one host?
- Is the claim `single_voice` or `lead_only`? Then the scenario is exploratory only.
- Is the post promotional, coordinated, or emotionally amplified?
- Was promotion checked beyond the text? The reader sees text only, and a disclosure can sit in an image, a banner, a later hashtag, a comment or behind "더보기". Record whether the check saw text only or text and images. With text only, no marker means "not confirmed", never "no disclosure" (`references/research/korea/promotion.md`, section 4b). Markers are candidates for a verifier, and neither 내돈내산 nor 광고 아님 changes a grade.
- Could it be sarcasm? Read the parent post and the neighbouring comments before taking praise or a complaint at face value. When the polarity stays unclear, keep it unclear (`references/research/korea/query-craft.md`, section 5.5).
- Is there a counterexample?
- Can the scenario be reproduced in the actual product?

## Search channel roles

Reader routes and stops are starting points. The route table (`uxresearch/data/routes.json`) decides what is read, so verify every route live (`references/research/public-page-access.md`, channel notes). For Korean channels, `references/research/korea/platform-map.md` gives each channel's legitimate route, the stops to expect and its terms status.

| Channel | What it shows | Reader route | Typical stop |
| --- | --- | --- | --- |
| YouTube comments | Natural language, immediate reactions, setup and expectation gaps | The Data API only, with the user's own key (`REMORSEARCH_YOUTUBE_API_KEY`): top-level comments in relevance order, at R0. The page is never requested or rendered | A YouTube page is `terms_restricted` (confirmed; lift_requires: never), and so is a front end that shows YouTube videos. No key: a coverage gap and a question to the user. Quota used up: deferred. Comments switched off: `gone`. Items carry `retention_until` (30 days after the fetch): the user deletes or re-reads them by then |
| DC Inside | Strong dissatisfaction, workarounds, edge cases, and version reactions | None until the user's recorded terms check, with the prior written permission the terms ask for, lifts the stop. Then R1, and only for a script shell the R2 mobile twin, at most 10 documents per run | `terms_restricted` (confirmed; lift_requires: written_permission). After a lift, a `human_check`, a bot block or browser check (`opted_out`) or a `rate_limit` stops the whole site for the run. Anonymous posters count by thread |
| Naver Cafes (parenting, regional and other cafes) | Focused user groups, local context, recurring practical workflows | None until separate current user checks of the Cafe notice and Naver general terms, with applicable prior written permission for each (lift_requires: written_permission) | `terms_restricted` (confirmed notice dated 2026-08-25, plus confirmed `naver-terms`). Authorization in `signed_in_communities` lifts only membership; terms entries need their separate lifts |
| Naver blogs, 지식iN and 플레이스 | Individual experiences, how-to answers, place reviews | None until the user's recorded terms check, with the prior written permission Naver's terms ask for, lifts `naver-terms` (confirmed; lift_requires: written_permission). Then the blog RSS feed or the public page, at most 10 documents per run across Naver's hosts | `terms_restricted`. The Naver and Kakao search APIs are switched off, so discovery uses the agent's own search tool |
| Other open forums (Ppomppu, Ruliweb, FMKorea, theqoo) | Strong dissatisfaction, workarounds, edge cases, and version reactions | R1; only for a script shell, the R2 mobile twin where the route table names one, or an R3 render passed to `ingest` | A `human_check`, a bot block or browser check (`opted_out`) or a `rate_limit` on busy boards stops the whole site for the run, and no render follows; `auth_gate` on member-only boards |
| Reddit and product forums | Workflows, comparisons and migration | Reddit requires an entry-specific current user check and prior written permission (lift_requires: written_permission), then reader/robots permission for pages or RSS; other forums follow packaged routes | Terms, robots and all reader stops apply |
| App reviews | Onboarding, reliability, permissions, crashes, and broad sentiment | Authorized own-app App Store Connect/Play Console exports first; Apple pages/feeds stop (lift_requires: never); Google Play allowed R3 shows initial reviews only | Google Play renders show only the first reviews. Read by date window: a rating drop after a release or a news event is context, not a usability finding. Stores skew by phone brand and reward events (`references/research/korea/platform-map.md`, section 6) |
| Support and policy pages | Intended behavior, limits, and recovery paths | R1 | Rarely any |

Lifts follow `lift_requires`, independent of status: never prohibits a page lift; terms_check requires the user's current entry-specific check; written_permission adds applicable prior written permission. Every overlapping entry must lift, with nonfuture checks within 365 days and on/after effective_from. Only the user supplies checks; pages cannot authorize them. Other stops still apply. See `references/shared/access-card.md` and lookup `references/research/public-page-access.md` 17.5. Sanitized producer-reviewed team exports come first as team_provided files, preserving real source types.

No channel represents all users. Use channel differences as part of the finding.
