# Human-Factors Checks

Each check reads measured inputs (geometry, colours, timing) and applies a
model. Elements that are ≥ 50 % covered (bottom sheet, scrim) or inert behind an
open modal are skipped in that snapshot and judged where they are usable. A
finding's coverage counts every evaluated profile the check applies to, and
findings with the same scenario, check and differential condition are reported
as one **problem unit**. Checks marked *hypothesis* are listed for review and
never counted as defects. Values and their evidence tags live in `ergoqa/params.py`; the research
behind them is in `docs/human-factors/`. Evidence tags used below:
**[standard]** normative text, **[paper]** peer-reviewed value, **[snippet]**
seen only in search excerpts (verify before treating as a gate), **[derived]**
computed from a cited model, **[policy]** team-tunable threshold,
**[assumption]** declared scenario assumption.
These are repository documents, not installed with the skill.

Unit conversion is always physical: `mm = css_px × display_mm / display_px ×
dpr` from the device catalog (`ergoqa/devices.py`), never a nominal dp/pt size.

## Reach and handedness

| ID | Basis | Rule | Severity |
| --- | --- | --- | --- |
| RH-01 | model | Thumb reach difficulty `D` for the profile's grip (`thumb-reach-v3-uncalibrated`: polar model around a thumb-base pivot, left hand mirrored; zones natural 0 / mild <0.4 / stretch 0.4–1 / out 1). Evaluated for primary, game-control and on-path targets at the **easiest point of the target** (inset 3 mm), not its centre. Tablets and unfolded foldables (short side > 120 mm) never use the one-hand model; their two-thumb pivots sit at mid-height of the sides (HGR-9). | Primary/game control: out → P2, stretch → P2 (D ≥ 0.6) else P3, small target in the cramped near-palm zone → P3. Other on-path controls (fields, tabs): out → P3 only. Never above P2 from the model alone. |
| RH-02 | model | Destructive action declared `irreversible` (no confirmation or undo), not on the task path, sits in the natural zone. A destructive link that opens a confirmation dialog is not flagged. | P3 |
| GM-02 (reach) | model | Landscape two-thumb games, gameplay controls (not secondary controls named pause, menu, settings, options, help, close, back or their Korean equivalents): travel from the nearest thumb rest point (assumed 25 × 22 mm inset from lower corners) and top-band placement (Apple HIG: frequent controls near thumbs, secondary controls such as pause and menus at the top, so those are not flagged; a scripted run's tap counts do not decide this). | top band → P2; travel > 35 mm → P3 |

Sources: Parhi, Karlson & Bederson 2006 [paper]; Bergstrom-Lehtovirta &
Oulasvirta 2014 (coefficients not retrieved); Trudeau et al. 2012/2014 [snippet];
Xiong & Muraki 2016 [snippet]; Hoober 2013 grip shares [snippet]. Thumb length L
uses Parhi's landmark (US mean 115 mm); Korean values are scaled by hand length
and are assumptions until calibrated (handedness-grip-reach.md §4.5).

The differential condition (`profile_specific`) shows whether a reach finding is
left- or right-hand specific. Korea has low left-handedness (5.8 % left + 7.9 %
mixed, 2009; 7 % in 2025 with 12–13 % in teens/20s) but ~33–37 % of one-handed
phone use is left-thumb, so always keep a left-grip profile.

## Pointing

| ID | Basis | Rule | Severity |
| --- | --- | --- | --- |
| PT-01 | measured | WCAG 2.2 SC 2.5.8: ≥ 24 × 24 CSS px, or the 24 px spacing-circle exception, over the whole rendered page. The target includes an associated `<label>` (it accepts the same click). Inline/equivalent/essential exceptions need judgment. | P1 on primary/destructive/path targets, else P2 |
| PT-02 | measured | Physical size (label-extended target) of controls the task depends on (primary, destructive, on-path): < 4.4 mm (iOS 28 pt floor) → P1; < 7 mm (44 pt / 48 dp / Windows 7.5 mm) → P2; one-hand grip with a side < 9.2 mm **and** harder to hit than a 9.2 mm square (Parhi) → P3, so a full-width 60 × 8.8 mm field passes. Small secondary targets are left to PT-01. | as rule |
| PT-04 | model | Dual-Gaussian tap success (Bi & Zhai 2016): σx² = 0.0075·W² + 1.68, σy² = 0.0108·W² + 1.33 (mm²); P(hit) = erf(Wx/2√2σx)·erf(Wy/2√2σy), on the label-extended target. Severity from the baseline model (k = 1). Profile multipliers (one-hand thumb 1.3, walking 1.4, tremor 1.3/1.8, 60s 1.10, 70s+ 1.3; multiplied; derived or declared assumptions, see `params.py`) add findings only for targets harder to hit than a 9.2 mm square; profile-only severity is at most P2 for the primary action or a control the task used, otherwise P3 (MP-02), and P3 for any target of at least 7.0 mm (SIT-01: walking and tremor studies find such targets usable; critical targets below 7.0 mm already get P2 from PT-02). | baseline miss ≥ 10 % P1, ≥ 5 % P2, ≥ 3 % P3; profile-only ≤ P2 (path/primary, < 7.0 mm) or P3 |
| PT-03 | model | Misfire: probability that a tap aimed at a primary/path target lands in a destructive neighbour (same Gaussian integrated over the neighbour box), plus gap. Same baseline/profile split as PT-04. | baseline ≥ 1 % and neighbour declared `irreversible` → P0; ≥ 5 % → P1; ≥ 1 % → P2; profile-only ≤ P2 (≤ P3 when the aimed target is at least 7.0 mm and the neighbour is not `irreversible`); gap < 8 dp (1.27 mm) → P3 |
| PT-06 | measured | Pointer devices: a destructive control within 8 CSS px of a primary/path control (Material 8 dp; Win32 separation of destructive commands). | P2 |
| PT-05 | model | Fitts ID between consecutive pointer steps (mouse MT = −107 + 223·ID ms, MacKenzie, Sellen & Buxton 1991). Relative comparison only. | ID > 6 bits → P3 |

Reference values (derived): 3.8 mm (≈ 24 CSS px on a phone) → P(hit) 0.74;
7 mm → 0.975; 9.6 mm → 0.997. Passing WCAG never implies ergonomic adequacy.

Derived advice (SIT-05): PT-02/PT-04/RH-01 findings append sentences derived
from the supporting observations' own measurements to the catalog
recommendation. PT-02 names the recorded target's w × h mm (converted through the
device catalogue's density; retain the input's measured or estimated geometry basis) and the
exact criterion missed (the 4.4 / 7.0 / 9.2 mm tier). PT-04, for the failed
primary/taskpath targets it already flags in the 7.0–9.2 mm band, records
`same_error_square`: the smallest square whose dual-Gaussian hit probability at
the profile's σ multiplier equals the 9.2 mm reference square at k = 1. The
reference square's own miss probability at k = 1 is stored explicitly as
`reference_miss_probability` (≈ 0.46%) and stays distinct from
`baseline_miss_probability`, which is the *actual target's* miss at k = 1 — the
two are never conflated into one "same error" claim. The equivalent size is
rounded **up** to 0.1 mm, because the text words it as a minimum and the printed
bound must not under-shoot the model reference (k = 1.5 solves at 24.148…
→ 24.2). The search is a bounded monotone bisection; `found_within_search_bound:
false` only means no matching square was found inside the 40 mm search bound —
a match may exist beyond it or not at all, so the advice says the bounded
comparison is unavailable (unknown within the bound) and keeps the alternative
guidance instead of claiming size can never help or recommending giant sizes.
It is a same-model comparison labelled as model output under declared
assumptions — not an accessibility requirement and not a calibrated human error
rate. RH-01 quotes the model-*predicted* (uncalibrated thumb-reach-v3) grip,
zone, difficulty and easiest-point coordinates; it is never called a
measurement of actual users. A same-severity group can hold distinct
per-profile evidence (seated k = 1.3 → 15.0 mm; walking k = 1.82 → none within
the bound), so every derived segment is labelled with the profile id(s) whose
observation supports it, in sorted order — the aggregate text and the per-profile
QA-bundle proposals (each quoting the persona's own observation) are
order-independent and never present one profile's numbers as another's. This
layer only adds text and typed measurement fields: pass/fail, severity, tiers,
counts and thresholds stay computed exactly as above.

## Gaze and attention

| ID | Basis | Rule | Severity |
| --- | --- | --- | --- |
| GZ-01 (hypothesis) | model | Reported as a **hypothesis**, not a defect: no unique detection on 53 seeded defects and 0/6 judged valid. `gaze-priority-v3`: priority combines screenshot conspicuity, hand-fit layout priors, element cues and ad-like penalty. 300 simulated paths of 10 selections report the fraction that includes the primary region within the first 4 selections. Equivalent visual representations share one sampled region; distinct controls remain separate. This fraction has no human-probability calibration or fixed time equivalent. Free-viewing priors do not predict goal-directed search; the output prompts hierarchy review. | < 0.5 → P3 |
| GZ-02 | model | Action-to-feedback separation: exact angle θ between display rays to the last input location and the nearest visible point of new or changed feedback, with independent x/y physical scales. The eye projection is assumed at viewport centre; `focus_point` is a pointer/keyboard anchor, with no measured gaze. When a successful pointer action transfers observed DOM focus from a known prior field or body to a unique visible field directly linked to this feedback by aria-describedby or applicable aria-errormessage, the visible field centre supplies an explicitly assumed attention anchor for that feedback only. Missing, ambiguous, hidden, unchanged or unrelated focus keeps the original input anchor; direct pointer focus and keyboard actions keep their existing semantics. The original input point is retained in provenance and for thumb occlusion; GZ-01 sampling is unchanged. Salient change (new object ≥ 1° with ≥ 3:1 box contrast, or bold/icon-led text at ≥ 4.5:1): likely ≤ 10°, uncertain ≤ 20°, else likely missed. Non-salient: 2° / 5°. Bands × 0.7 for 70+, low vision or high load (assumption); the scaled bands are stored. One-hand grips also test the thumb/hand occlusion wedge (±35° toward the thumb base). Not flagged when another salient message appeared near the input anchor (redundant), or when the action replaced the screen (except declared transient messages). Only messages with text count, and "new" means absent (or blank) before the action: a message that was already there and only changed its text is reported at P3 at most. After the app itself scrolled by half a screen or more (`APP_SCROLL_REORIENT_FRACTION`) without a scroll gesture, the user re-orients, so the angle from the old tap point is not used (declared transient messages still are). Feedback rendered outside the viewport is flagged directly. | new message off-screen: error/critical P1, else P2; likely missed or occluded: error/critical P2, status P3; uncertain critical P3; changed message P3 |
| GZ-03 | model | Critical information in a desktop right rail, a thin full-width top banner or declared `ad_like` styling (banner blindness: banners found ~58 % vs 94 % for links, Benway & Lane 1998). Needs judgment. | P3 |
| GZ-04 (hypothesis) | model | ≥ 4 distinct interactive visual regions out-prioritise the primary action; aliases of the same entity count once. Reported as a hypothesis (no unique detection; 1/6 judged valid). | – |

Each GZ-01 observation records model version, run/selection counts, starting
anchor, seed, visible-region aliases, physical scales and unmeasured eye
projection. The existing P3 threshold is 0.5; 0.8 remains an advisory reference.
GZ-01/GZ-04 retain the hypothesis tier. Parent-clipped or unsupported painted
geometry produces an explicit inconclusive record, with no gaze score. Raw
boxes remain available to target-size and reach checks; legacy captures without
`visible_box` retain viewport-only intersection, except an explicit clipped-paint
gap also abstains.

[UEyes](https://userinterfaces.aalto.fi/ueyeschi23/) and
[Leiva et al.](https://arxiv.org/abs/2101.09176) observed static screenshots in
labs. The model's hand-fit coefficients and feedback bands remain policy
assumptions. [Task-driven webpage saliency](https://openaccess.thecvf.com/content_ECCV_2018/html/Quanlong_Zheng_Task-driven_Webpage_Saliency_ECCV_2018_paper.html)
distinguishes task conditions. The display-ray formula is geometry;
[PsychoPy's unit documentation](https://psychopy.org/general/units.html) explains
why physical scales and viewing distance matter. No empirical human accuracy,
message understanding or Korean task-search improvement is claimed. Gutenberg,
Z-pattern and golden-ratio rules are not encoded.

## Perception

| ID | Basis | Rule | Severity |
| --- | --- | --- | --- |
| PC-01 | measured | WCAG 1.4.3: 4.5:1, or 3:1 for ≥ 24 px / ≥ 18.66 px bold (KWCAG 2.2 5.4.3 expansion exception is assessed separately), over the whole rendered page. Disabled controls exempt. | < 3:1 or primary/critical → P1, else P2 |
| PC-02 | measured | WCAG 1.4.11: rendered identifying boundary, glyph or state indicator ≥ 3:1 against its known adjacent layer. Web captures use solid CSS parts and SVG fill/stroke; unused CSS foreground cannot stand in for a glyph. Switch/slider track and thumb nodes are checked separately from the label and each other. Text-labelled custom radio/checkbox cards are exempt from outline contrast; a rendered state indicator is still checked. Inactive controls are exempt. | P2 |
| PC-03 | model | Colour-only states: within same-shaped groups, corresponding rendered CSS/SVG paint channels that differ clearly (ΔE00 ≥ 20) are treated as candidate state codes. Different SVG geometry supplies another cue; visible state words (including 입금/출금, 승인/취소), check/cross glyphs and signed amounts supply redundancy. ARIA-only names do not supply a visible cue. After Machado per-severity simulation, ΔE00 < 5 confusable, 5–10 marginal; exempt when the states differ by ≥ 3:1 luminance (G183). Tritan simulation is low confidence. | < 5 → P2; 5–10 → P3, but P2 when the colour encodes a status, warning or error |
| PC-04 | model | Retained project policy on CSS em angle: < 16′ → P2 (P1 for critical messages); < 24.6′ young / 31.2′ 60s+/presbyopic → P3 for running Hangul prose (≥ 12 syllables; excludes controls, headings and table cells). These values do not certify ISO/HIG conformance or an individual's critical print size. Apple 11pt is a platform-point guideline; the retained 11 CSS px floor is project policy. Profile distance and device vertical physical scale remain assumptions. | as rule |
| PC-05 (hypothesis) | model | Reported as a hypothesis (no unique detection; judges split). Bright-sun profile: primary, status, error and critical text below 7:1 (one ambient model: 2000 nits, 50 klx, ρ 0.02 ≈ WCAG 7.07). | P3 |

Web `paint.source = dom-solid-v1` is a bounded DOM measurement: at most 64
visited nodes and 16 paint channels per extracted element. It owns textless
child indicator parts, skips nested controls and fully covered/clipped parts,
and composites supported alpha over known solid layers. SVG shape/group CSS
box backgrounds are ignored because they do not paint those shapes. Partial
occlusion/clipping, gradients/media backdrops, pseudo-elements, effects, complex
SVG and browser-native checkbox/radio/select paint remain explicit gaps in the
report; they produce no PC-02/PC-03 verdict. Authored CSS boundaries on native
text inputs remain measurable. Legacy captures without paint metadata retain
their boundary checks; a foreground glyph requires visible glyph text.
Colour-only grouping and shape correspondence are screening heuristics, not a
WCAG certification or a calibrated prediction of an individual's perception.

글자 추출 시 브라우저의
[Canvas TextMetrics](https://html.spec.whatwg.org/multipage/canvas.html#textmetrics)로
`font_metrics`를 CSS px 단위로 저장할 수 있다. 화면에 표시된 텍스트의 본문 높이는
고정 표본 H의 cap-height, x의 x-height, Hg의 본문 높이, 한의 높이와 구분한다.
글꼴 로드가 완료되고 같은 글꼴·스타일을 사용하는 가로 텍스트에 적용한다.
변형·확대, 지원하지 않는 글자 조형, 입력 필드와 보호된 텍스트는 측정에서 제외한다.
혼합 글꼴, Canvas·글꼴 지원 부족, 노드·문자 수 상한 초과는 측정 불가 사유로 남긴다.
Canvas 값은 DOM의 래스터 픽셀을 실측하지 않으며 실제 대체 글꼴도 확정하지 못한다.
모든 측정에 이 제한을 기록하고, PC-04는 em 정책과 글리프·표본의 시각각을 구분한다.

[XAG 101](https://learn.microsoft.com/en-us/xbox/accessibility/xbox-accessibility-guidelines/101)은
ascender부터 descender까지 렌더링된 본문 높이를 사용한다. 1080p에서 콘솔 26px,
PC 18px를 기준으로 한다. GM-01은 선언된 패널 높이와 DPR로 환산한 기존 비교값에
표시 텍스트의 Canvas 본문 높이 추정값을 비교한다. 측정 불가 시 XAG 판정을 보류하고,
기존 em 경고는 프로젝트의 대리 지표로 표시한다. 추정값 비교만으로 렌더링된 글자의
XAG 적합성을 확정하지 않는다. NASA의 cap-height 요건은 우주 비행 시스템에 적용되며,
연속 독서의 x-height 연구도 모든 CSS em에 적용할 하한을 제시하지 않는다.

Korean CVD prevalence: men 5.9 % (1989) / 6.5 % (KNHANES 2013, 19–49), women
0.44 % / 1.1 %; deutan ≈ 6× protan [snippet]. KRDS body text ≥ 16 px (17 px
default).

## Cognition and timing

| ID | Basis | Rule | Severity |
| --- | --- | --- | --- |
| CG-01 | model | More than 9 same-shaped interactive choices in one container, counted over the whole rendered group (below the fold or under a sticky bar still count; only a modal hides them) (Hick-Hyman b ≈ 150 ms/bit used only to show relative cost; not a Miller 7±2 rule). Numeric keypads are exempt (recall of a known code). | P3 |
| CG-02 | model | Transient text (timing window of kind `transient_text`, declared or inferred from a readable message; on game surfaces only declared or message-role windows) shown for less than the reading time of a −1 SD reader (Korean adults ~330, older ~290 syllables/min; mean ~587/410) × 1.5, floor 4 s (Material), with 50 ms measurement tolerance. Toasts with an action must not auto-dismiss (WCAG 2.2.1). A message that only ever appeared outside the viewport fails. | action toast or off-screen error → P1; too short → P2 |
| CG-03 | measured | First DOM change after a tap/click: > 400 ms (Doherty) P3; > 1 s P2 (needs a progress indicator); > 10 s P1; none within 3 s P2. Not evaluated when the target was disabled, hidden or covered, when a timed control was tapped after its window closed, or for text fields (their feedback is the caret and focus ring). | as rule |

## Games

| ID | Basis | Rule | Severity |
| --- | --- | --- | --- |
| GM-01 (perception) | measured/model | HUD/subtitle text: XAG 101 floor 26 px at 1080p on console/TV/handheld, 18 px on PC (scaled to the display and DPR); visual angle ≥ 16′. | P2 (P1 for critical prompts) |
| GM-05 | measured | Touch game controls (`game_control`): < 7 mm → P2; < 9.6 mm (serial thumb taps, Parhi) → P3 for gameplay controls, not for secondary controls such as pause or menu (discrete taps); closer than 2 mm to a screen edge (system gestures, bezel) → P3 (HGR-11). | as rule |
| GM-06 (not emitted) | measured | Emits nothing until a press-rate and hold-time sweep (game brief GQA-02) measures the rate the game demands (XAG 107 / GAG: avoid mashing; offer hold/toggle/auto). The earlier rule counted the presses the script needed (≥ 8 on one target), which measured the script; it was cut (GQA-13). | – |
| GM-03 | model | Timed input (QTE) window (measured) vs the profile's choice reaction time 95th percentile (log-normal, CV 0.2 assumption; per-age values provisional) + 100 ms motor + input latency. | margin < 0 → P2; P1 only when even a typical young adult (median, 20s) misses the window |
| GM-04 | measured | WCAG 2.3.1 / ITU-R BT.1702 flash screening from two sources. (a) Sampled frames on a block grid: per block, transitions are opposing luminance changes ≥ 10 % with the darker state < 0.80 (general) or ≥ 10 % of the block moving into or out of saturated red (red); a block flashes while it has more than 6 transitions in any 1 s (50 ms sampling tolerance, so a 3 Hz flicker passes); the areas of concurrently flashing blocks are summed within any 10° field with the device pixel pitch and the profile viewing distance. More than 0.006 sr → P0. Extended failure → P1 when either rule holds on that area: `sustained_5s` (10 or more flashes within 5 s) or `iris_extended` (EA IRIS's rule, ported from `TransitionTracker.cpp`: at least 4 of the last 5 s at 4–6 transitions per second, exact 1 s window, and now at ≥ 4). `iris_warning` (4 or more transitions in 1 s over the area) is recorded, not reported. Blocks whose change is explained by content motion (scrolling in one direction; the page's own measured scroll is the motion) are not flashing; page scroll that reverses direction more than 3 times within 1 s, after at least 4 CSS px of travel each way (a shaking page), is not treated as motion. A pass is reported as `inconclusive` (not clean) when mean capture rate < 20 fps, a wait step had no samples or sampling was truncated. Runs without a block grid fall back to the whole-viewport mean. (b) DOM elements that appear and disappear more than 3 times in any second (16 ms in-page polling), cover the WCAG area, and are saturated red (linear R/(R+G+B) ≥ 0.8) or differ by ≥ 10 % luminance → P0. Live check: `docs/validation/flash-screening/`. Screening only. EA IRIS is not a certification either (its README says so), and its defaults count a transition only when 25 % of the frame changes, so a local flash can pass IRIS; an IRIS pass does not overturn this result. For broadcast or certification, use a certified process such as Harding FPA. | as rule |
These are repository documents, not installed with the skill.

Game timing must be measured, not inferred from an agent failing in real time.
Photosensitivity, subtitles-for-dialogue and audio-only cues are covered in
game-ux-ergonomics.md; subtitle coverage and audio cues are not automated here.

## Semantics and layout (profile-independent, web DOM)

These are measured once per screen and reported as profile-independent. Their
precision is gated on the W3C ACT rule examples where an ACT rule exists
(`scripts/ergo_act.py`, pinned ACT commit; SM-01/02/03, SM-05 and LY-01): no Passed or
Inapplicable example may be reported. 59br37 (LY-01) is also run at its own 640 × 512
viewport (`--viewport 640x512`). SM-08, FM-02 and RF-01 have no ACT rule and are
checked on the driver self-test fixtures and the dev suites only. They
matter most to people the swarm does not simulate (screen-reader, voice-control
and keyboard users), so the report names them. The rules are kept narrow for
precision; a full audit still needs axe-core or a manual WCAG review.

| ID | Basis | Rule | Severity |
| --- | --- | --- | --- |
| SM-01 | measured | A control (button, link, role control) that is not hidden from assistive technology has no accessible name (WCAG 4.1.2; axe `button-name`/`link-name`). Name order: aria-labelledby (resolved in the element's own tree), aria-label, alt, value, label, title, placeholder (fields), own text (SVG: its `<title>`). | P1 on the task path or primary, else P2 |
| SM-02 | measured | The control's name comes from aria-label/labelledby and its visible inner text (visually hidden text excluded, inline boxes joined) is not contained in the name by the ACT label-in-name algorithm: parenthesised text dropped, case-folded, NFKD, letters and digits only, contiguous token run. A lone "x", icon-font text, abbreviations ("Ave.") and hyphenation differences count as contained; a Hangul label token also matches a name token that starts with it (particles). | P2 on the path, else P3 |
| SM-03 | measured | A form field (input, select, textarea, or role textbox, searchbox, combobox, listbox, spinbutton, slider) has no accessible name at all (WCAG 4.1.2; ACT e086e5). Disabled fields too; presentational, non-focusable ones are skipped. | P1 on the path, else P2; disabled P3 |
| SM-07 | measured | A form field is named only by its placeholder or title. That is an accessible name (ACT passes it) but not a visible label: best practice, not a WCAG failure. | P3 |
| SM-04 | measured | An input error (declared `error_message`, or `role=alert` while a field is invalid) names no field, is more than 48 CSS px from every field, and no field points to it or its wrapper with aria-describedby or aria-errormessage (WCAG 3.3.1; LAT-09 ER-01). Field names match as Hangul (2+ syllables) or whole Latin words (4+ letters). System notices declared `critical_message`/`status` are skipped. | P2 |
| SM-05 | measured | Keyboard focus walk (mouse and keyboard devices, after the run: end state and initial screen) and focus probes before clicks on the screens in between: focusing the element changes fewer than 4 pixels in its box, its small wrappers and 4 px around them, compared with the element unfocused at the same scroll position (WCAG 2.4.7); a probe counts only when the control matched `:focus-visible`. Probes: keyboard modality by an F24 key press (Tab-only modality scripts are not triggered), two unfocused captures before and one after (pixels that change without focus are animation), the previous control's own ring masked (not when it holds the target; a large element along its edges only). Focus goes back to the previous element only where losing it would change the page (an expanded trigger, focus inside a dialog, menu, listbox or popover); elsewhere the target is blurred. Before a button, a focused text field is blurred first and the screen measured again; after typing in a field with suggestions, or before a non-button, the click is not probed. When more than half of the target's box is masked (the previous control, or content that keeps moving), the probe is inconclusive. Skipped for text fields, controls inside menus, listboxes, trees and grids (they manage focus), game and timed targets. A walk that measured an indicator is never overridden by a probe. | P2 |
| SM-06 | measured | Walks: the focused element is behind a painting fixed or sticky layer that does not contain it, at all nine sample points (WCAG 2.4.11); partly covered is P3 (2.4.12). Worst result over the walks; not also reported as SM-05. Steps: after a tap, click, key press or typing that moved focus, the focused element is fully covered (five sample points ≥ 0.999) and not under a layer the user opened (the 2.4.11 note exempts those; FM-02 covers them). | P2 / P3 |
| SM-08 | measured | A tap or click of the task landed on an element that is not a control (native control, link, widget role, tabindex ≥ 0, a label of a usable control, a web component that delegates focus or holds one), is not inside one within five levels (links and buttons at any depth), and holds none; the driver resolves this at the click point through open shadow roots. Exempt: a click with no feedback at all (not evidence of a handler), game surfaces, scenario hotspots, `game_control` targets, content hidden from assistive technology, and the image or text of a card whose own link or button the keyboard reaches (an ancestor at most 4× the clicked area holding a control, unless the clicked element looks operable on its own with a pointer cursor the card lacks, or the control is a peer item of the same size, as in a chip row). WCAG 2.1.1 and 4.1.2: keyboard and screen-reader users cannot operate it. | P1 |
| FM-02 | measured | A click opened a layer that was not there before (a declared dialog, or a fixed or absolute painted box over ≥ 40 % of the viewport that covers rendered content) and keyboard focus is not inside it, or on its overlay root when that root wraps the layer (the outermost fixed ancestor that is not the app shell, e.g. a portal that focuses itself; focus left on a trigger in the same fixed bar does not count). Focus that arrives within 1 s of the click (entrance transitions) counts; after a wait or snapshot step focus is polled for 0.7 s more; a layer first seen at a wait right after the click (spinner first, dialog after a request) counts for that click when no other input came between and within 3 s. Exempt: undeclared sheets with nothing to operate, a scrim around a new dialog, and non-modal layers the focused trigger controls (`aria-expanded` + `aria-controls`) or the next Tab reaches (disclosures, mega menus). Focus is read once per step, so a layer that steals focus later and gives it back is not seen. WCAG 2.4.3. | P2 |
| LY-01 | measured | Text is cut off by its own box (overflow hidden or clip and scroll size > client size; XCTest `textClipped`, a symptom for WCAG 1.4.4 and 1.4.12), or by a clipping ancestor within three levels (a fixed-width chip or label) while partly visible. ACT 59br37's exceptions mark a clean cut (`act_59br37: passed`): one nowrap line ending in a marker (text-overflow other than clip, drawn only by a block container), or a box one line high (used line-height ≥ its height, a "normal" line height measured from the text's first line box; the text's glyphs fit). Clean cuts stay as P3 truncation notes (a value cut in a confirmation screen still hides information) and do not count against the ACT gate. Boxes under 4 px (screen-reader-only text) and moving text (tickers, marquees) are skipped. | P2; P3 with an ellipsis, line clamp or clean cut |
| RF-01 | measured | WCAG 1.4.10 at 320 CSS px. The driver keeps a static copy of each distinct screen (fingerprint: path, headings, dialogs, `main`/`form`/`section` elements with an id, large regions with an id and messages on screen (alerts, status and live regions with text), digits removed; the newest copy per screen; 12 screens per run, later ones counted as dropped) as the browser holds it: CSSOM-inserted rules, adopted sheets and open shadow roots included, scripts off, loaded under the page's own URL so its CSS and fonts load same-origin. It renders the copy at the device width and at 320 px. Findings: (a) the outermost elements past the right edge when the page scrolls sideways or the root clips, or inside a fixed bar (a fixed box cannot be scrolled to) that is not wholly off screen (a fixed off-canvas menu is exempt); two-dimensional content (tables, maps, video, code, `role=grid/toolbar`), inert and `aria-hidden` content, content with its own scroll or clipping box, and anything off screen at the device width too are exempt; (b) text ≥ 90 % visible at the device width and < 50 % visible at 320 px (cut by a clipping container), except text that is invisible, sits in a collapsed disclosure (a clipping box 0 high or `max-height: 0`), in a clipping box a control points to with `aria-controls` (a disclosure, carousel or tabs: reachable through it) or in a carousel track (`aria-roledescription` carousel, or a carousel library's class), or in a fixed box wholly off screen; (c) the page itself when it scrolls sideways and no element was located, unless exempt content (a table, code, an off-canvas box) reaches as far as the page scrolls (`exempt_right`). When more than three boxes stick out on one screen, the layout does not reflow at all and the screen gets one finding naming every box (`offender_count`). A copy that kept < 90 % of the live page's CSS rules is not measured (`styles_lost`). Layouts switched by scripts (`matchMedia`) are not re-evaluated. | P2 |

| ID | Basis | Rule | Severity |
| --- | --- | --- | --- |
| RF-02 | measured | 같은 viewport와 DPR의 정적 복제에서 지원하는 HTML 텍스트에 WCAG 1.4.12 간격 조건을 적용합니다. 기존 값이 큰 경우에는 유지합니다. 실제 적용값을 확인한 뒤 텍스트 Range가 새로 잘린 경우를 기록하며 기본 간격에는 판정을 붙이지 않습니다. 문서·컨테이너 스크롤 접근은 유지합니다. 입력 UI·아이콘·이미지 문자, 지원하지 않는 문자 체계, 대체 접근 경로와 확인할 수 없는 스타일은 근거 부족으로 남깁니다. 실제 브라우저 확대나 전체 WCAG 적합성 검증은 포함하지 않습니다. | P2 |
| RF-03 | measured | 폭과 DPR을 유지하고 높이를 `max(256, floor(원래 높이 / 2))`로 줄인 실험에서 새로 잘려 접근할 수 없는 텍스트와 조작을 비교합니다. 고정 영역의 버튼은 toolbar 역할만으로 면제하지 않습니다. 스크롤로 접근하는 콘텐츠는 유지됩니다. 화면 비율·높이 자체에는 통과·실패 기준을 부여하지 않습니다. 원래 높이가 256 CSS px 이하면 생략 이유를 기록합니다. | P2 |

RF-02/RF-03은 `run.adaptation[]`과 원본·복제 baseline·변경 조건의 캡처 ID를
연결합니다. 실제 변경 캡처의 PNG 해시와 기존 QA 영수증 경로를 사용합니다.
일부 글자가 사라지는 경우도 비교하며 0.25 CSS px²를 계산 오차로 허용합니다.
정수 CSS API로 읽은 스크롤 범위에는 해당 축의 끝 경계에 1 CSS px 반올림
오차를 허용합니다. 숨김 상자의 경계는 유지합니다.
이 허용량은 접근성 기준이 아닙니다. CSS·스캔·적용값 확인 실패와 사라진
요소의 대체 경로 미확인은 `gaps`에 남습니다. 정적 복제가 재현하지 못하는
스크립트 배치·키보드·가림은 추가 확인이 필요합니다.
[WCAG 1.4.12 해설](https://www.w3.org/WAI/WCAG22/Understanding/text-spacing.html).

`TI-01` is an opt-in measured task comparison on the recorded owner execution:
`success.task_checks` compares authored value/text/checked expectations after
specified actions and at completion. It stores checkpoint/capture IDs without
field values. Severity and consequence are authored task impact; comparison
alone does not prove downstream harm. Unvisited, ambiguous, protected and missing
targets remain unevaluable. See `drivers/web/README.md` for executable payloads.

## Judgment (not automated)

- WCAG 2.5.8 exceptions; whether an action is irreversible; whether a
  destructive button reads as primary; ad-like appearance.
- Heuristic evaluation with the 24 UXD checks in
  `docs/human-factors/ux-design-discipline.md` (Nielsen, Norman, Shneiderman,
  ISO 9241-110/112). Persona agents record expected vs. observed per step.
- Korean dark patterns (전자상거래법 제21조의2, in force 2025-02-14: 순차공개
  가격, 사전선택, 잘못된 계층, 취소 방해, 반복간섭; 개인정보보호법 제22조 separate
  consents). Run these as a separate auditor pass: agents can be manipulated by
  the patterns they are checking.
- Game intent (QTE/mashing as design), left-handed HUD options, motion comfort.
These are repository documents, not installed with the skill.
