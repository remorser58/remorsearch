# Validation and Limits

How this skill is validated, what the numbers mean, and where it is known to be
weak. Raw results: `docs/validation/`. Benchmark format: `docs/ergonomic-swarm-spec.md`
section 12.
These are repository documents, not installed with the skill.

## Method

1. **Blind seeded-defect suites.** A separate agent writes fixture pages with
   seeded defects, decoys (things that look wrong but pass the cited standard)
   and clean controls (the same page without the defects). The answer key
   names scenario, category, element selector, profile condition and minimum
   severity. It never names check IDs. Tool authors must not read answer keys.
2. **Real surface.** `scripts/ergo_bench.py` serves the suite locally, records
   one scripted run per scenario and device in Chromium (real touch/mouse
   events via CDP), analyses each run under every profile on that device, and
   scores three configurations:
   - `measured_only`: measured checks, one default persona. This is roughly what
     a standard automated accessibility scan reports.
   - `single_profile`: all checks, one default persona (30s, right hand, one-hand
     grip, normal vision, seated).
   - `swarm`: all checks, 14 stratified profiles per touch device (7 per pointer
     device).
3. **Metrics.**
   - Strict recall: the same element, category and profile condition as the key.
   - Lenient recall: the same element and condition, any category.
   - Severity agreement: detected at or above `severity_min`.
   - Decoys flagged.
   - Clean-control findings: findings on pages with no seeded defect. They are
     false-positive *candidates*, because a clean page can still have real
     unseeded problems.
   - Unlabeled findings: extra findings on defect pages. These need
     adjudication.
4. **Held-out rule.** A suite is scored once with the detector frozen at a
   recorded commit. After that it becomes a development suite.
5. **Adjudication.** A stratified sample of unlabeled and clean-control findings
   is judged by independent LLM judges that see the screenshot, the element and
   the rule. They do not see the answer key. The result estimates real
   precision.
6. **External precision gate.** The semantics and layout checks are run on the
   W3C ACT rule examples, which the ACT task force wrote, not this tool's authors
   (`scripts/ergo_act.py`, rules fetched at a pinned commit). A Passed or
   Inapplicable example reported as failing is a gate failure. At the last run:
   0 false alarms on 82 such examples. Detection of the Failed examples: SM-01 4/5
   (buttons) and 7/11 (links), SM-03 6/9, SM-02 16/16, SM-05 1/1, LY-01 2/5 (the
   rest clip only at 200 % zoom, which is not rendered).
7. **Trivial baselines.** Recall is reported next to what a detector that flags
   every visible element would reach, and next to chance (the tool's own findings
   moved to random elements). On heldout-mixed, flagging everything reaches strict
   recall 0.95 with 36 clean-control units, against the swarm's 0.90. Recall alone
   therefore says little; read it with noise, chance-corrected recall and
   clean-twin discrimination (heldout-2 pre-registration, amendment 3).

## Results so far

| Suite (role) | Detector | measured-only* | single persona | swarm | Clean-control findings (swarm) |
| --- | --- | --- | --- | --- | --- |
| mobile-commerce v1 (dev, 17 defects) | before tuning | 0.29 | 0.65 | 0.82 | 232 |
| mobile-commerce v2 (dev) | `8c1de02` | 0.35 | 0.71 | 0.94 | 84 |
| game-desktop v1 (dev, 16 defects) | before tuning | 0.06 | 0.25 | 0.31 | 92 |
| game-desktop v3 (dev) | `3cad062` | 0.44 | 0.88 | 1.00 | 31 |
| heldout-mixed (held-out, 20 defects), scorer at freeze `8c1de02` | frozen `8c1de02` | 0.05 | 0.20 | **0.60** (lenient 0.70) | 98 |
| heldout-mixed, scorer of `3cad062` (id-prefix rule added before scoring) | frozen `8c1de02` | 0.15 | 0.35 | 0.80 (lenient 0.90) | 98 |

\* "measured-only" means *this tool's own measured checks under the default
persona*. It is not a standard accessibility scanner; axe-core, Lighthouse and
Android ATF have not been run for comparison.

**How to read this table:**

- **Development rows are training-set fits.** The checks were tuned after seeing
  those scores, as explained under Disclosures.
- **The held-out figure depends on the scorer.** The id-prefix matching rule
  (`#opt-` matches `#opt-*`) was added to the scorer in `3cad062`, after the
  detector freeze `8c1de02` and before the held-out suite was scored. The
  held-out README declares that key convention. With the scorer as it was at
  the freeze, swarm strict recall is 0.60; with the rule it is 0.80. Both are
  reported.
- **Swarm versus single persona is not evidence of usefulness by itself.** A
  defect keyed to a condition (CVD, presbyopia, left hand, walking, 60+,
  two-thumb) can only be credited to a profile that has that condition. The
  single default persona therefore cannot score on those defects by
  construction. Newer summaries also report recall on unconditioned defects
  only (`recall_strict_unconditioned`), where every configuration can be
  credited.
- **Strict matching only checks that a triggered profile satisfies the
  condition.** It does not check that the tool identified the condition. Newer
  summaries report `condition_identified` separately: the finding's
  differential condition names the key's condition.
- **Operating point.** Recall above counts findings at any severity. Newer
  summaries also report recall at P0–P1 and P0–P2
  (`recall_strict_by_operating_point`).
- **Precision.** Earlier docs called 0.34 "labelled precision (a lower bound)".
  It is not a lower bound, because it left unlabelled findings out of the
  denominator. Newer summaries report `validity_lb_units`, which counts all
  units, and `precision_labelled_subset_units` under its own name.
- **Adjudication round 1** (68 sampled unlabelled and clean-control findings
  from the `8c1de02` detector, 2 independent judges, agreement 0.91, κ 0.72):
  52 invalid, 10 valid, 6 split
  (`docs/validation/adjudication-round1.json`). The judges named concrete
  causes, and those causes were fixed:
  - wrong state (the element was covered by a sheet);
  - the phone reach model applied to tablets;
  - the label hit area ignored;
  - reach scored at the target's centre;
  - salience judged from box fill only;
  - numeric keypads counted as choice overload.
  The adjudicated sample came from the development and held-out suites, so
  those fixes are also post-hoc for them.
These are repository documents, not installed with the skill.

## Disclosures

- **Post-hoc tuning** went beyond threshold choices:
  - After v1 scoring, check categories were relabelled to the key taxonomy
    (GM-01 → perception, GM-02 → reach).
  - Three checks (GM-05, GM-06, PT-06) were added after v1 misses, and each is
    credited with one development defect.
  - The harness exposes per-defect selector, category and condition to the
    developer.
  - The committed development ablation names checks and conditions for all 53
    defects, including the former held-out suite.
  - The adjudication fixes were derived from findings on these same suites.
  - The inclusive floors were chosen from the development ablation.
- **Blindness breaches.** Benchmark authors' completion summaries described some
  seeded defects to the tool author, for all three suites. The held-out suite's
  timing-window metadata was printed once before scoring. For heldout-2, stage
  reports from its authoring workflow reached the tool author through a completion
  notice (build notes beyond counts, no defect identity or selector); this is
  disclosed in amendment 5 of its pre-registration, with the safeguards taken.
- **Checks removed after evidence.** GM-06 (mashing) counted the presses the
  script needed; it now emits nothing until a press-rate sweep exists. The GZ-01,
  GZ-04, PC-05 and PT-05 checks are hypotheses (listed, never counted).
- **Same model family and ontology.** The benchmark authors, the detector's
  author and the adjudicators are all Claude models. The authors wrote defects
  from this tool's spec: its categories and profile attributes. Recall therefore
  measures agreement within one ontology, not coverage of all UX problems.
- **Synthetic pages.** Fixture pages written by an agent are cleaner and more
  regular than production apps. Recall on real products is unknown.
- **Severity scales.** The mobile-commerce author declared P1–P4, while the
  scorer compares P0–P3 literally, so that suite's severity agreement is
  unreliable. Severity agreement is one-sided: over-rating is not penalised.
- **Agent layer not validated.** Every number above comes from scripted
  Chromium runs re-analysed under simulated profiles. The only LLM-agent evidence
  is 4 unscored runs on 2 development scenarios, with no agent model recorded.
  Runs now record the agent with `--agent`.

## Known limits

- **Noise is the main weakness.** Clean-control findings (31–98 per suite before
  the adjudication fixes) made the raw list too long to hand to a team. Findings
  are now grouped into problem units, and low-validity model checks are listed
  as hypotheses. Report P0–P2 first and use adjudication before claiming
  precision.
- **Models are uncalibrated for Korean users.** Thumb reach (Parhi landmark
  scaled by hand length), touch-SD multipliers for walking, tremor and age,
  gaze priors (free viewing in Western labs) and notice bands are assumptions or
  foreign data. They can reorder findings; they never justify P0 alone.
  - The walking, tremor and age multipliers are back-calculated from published
    error rates or open data (see `params.py`). On the development suites they
    found no defect that other checks missed, and changing their values by ±0.1
    changed no detection. On a target of at least 7 mm, a finding that only
    they produce is P3 at most. Whether they stay is decided once on heldout-2
    (amendment 4).
- **Gaze is free-viewing.** `gaze-priority-v2` does not model goal-directed
  search, so GZ findings are prompts to check hierarchy, capped at P3 (GZ-01).
- **Timing needs measurement.** QTE and flash results depend on frame-accurate
  capture; software input injection under-reports latency.
- **Flash screening is not certification.** GM-04 screens sampled frames on a
  block grid within 10° fields. Neither it nor EA IRIS (whose extended-failure
  rule it also applies) certifies anything. IRIS's default counts a transition
  only when 25 % of the frame changes, so a local flash can pass IRIS and still
  fail here. Broadcast or certification needs a certified process such as
  Harding FPA.
- **Keyboard checks are desktop-only and bounded.** The focus walk runs on mouse
  and keyboard devices, at most 40 stops in 8 s per walk, on the end state and on
  a fresh load of the first screen. Screens reached only mid-task are not walked.
- **LLM persona agents are not users.** They find task-flow confusion, dead
  ends and missing feedback. They cannot evidence bodily difficulty, and they
  follow ambiguous goals differently from people. Scenario goals must include
  concrete data (amounts, dates, names), or the agent never reaches the branch
  under test (seen in the persona trial: a transfer-limit path was never hit).
- **Coverage, not prevalence.** "k/n simulated profiles" says which conditions
  were tried. It says nothing about how many real users are affected.

## Calibration protocol (proposed, not yet run)

- **Reach and touch.** About 20 Korean adults per grip, a target-acquisition
  task on two phone sizes; fit the polar reach zones and the per-condition
  σ multipliers.
- **Gaze.** About 20 people × 30 Korean app screens with an eye tracker or
  webcam gaze. Check the P(primary fixated within 4 fixations) ranking against
  real first-fixation data.
- **Reading.** Korean older-adult reading rates for short UI messages (toasts)
  on phones.
- **Real products.** Run the swarm on open-source apps with known accessibility
  bug reports. Compare against issue-tracker ground truth and have human experts
  adjudicate findings.

## Experiments

Removal and addition experiments (leave-one-out per check and per profile
condition, model toggles, swarm-size discovery curves, audience-based versus
random composition) are recorded under `docs/validation/experiments/` with the
decision each one led to.
These are repository documents, not installed with the skill.