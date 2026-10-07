"""Model parameters and policy thresholds with their sources.

Every value is tagged in a comment:
- [standard] normative text (WCAG/KWCAG/platform guideline);
- [paper]    peer-reviewed empirical value;
- [derived]  computed here from a cited model;
- [policy]   team-tunable severity/threshold choice anchored on cited sources;
- [assumption] declared scenario assumption (no direct source); used for
  sensitivity runs only and never reported as a measured population value.

Research briefs behind these values: docs/human-factors/*.md.
"""

from __future__ import annotations

# ------------------------------------------------------------------ units
# Viewing distances (mm) used when a profile does not set one. [assumption]
# anchored on typical-use ranges reported for phones (~30 cm), desktop monitors
# (~60 cm) and 10-foot TV UI (~2.5-3 m).
DEFAULT_VIEWING_DISTANCE_MM = {
    "phone": 300, "foldable": 300, "tablet": 380, "laptop": 500,
    "desktop": 600, "tv": 2700, "handheld_console": 350,
}

# ------------------------------------------------------------------ pointing
WCAG_TARGET_MIN_CSS_PX = 24.0          # [standard] WCAG 2.2 SC 2.5.8 (AA)
WCAG_TARGET_ENHANCED_CSS_PX = 44.0     # [standard] WCAG 2.2 SC 2.5.5 (AAA)
TOUCH_TARGET_MIN_MM = 7.0              # [standard] ~44 pt (Apple HIG) / 48 dp (7.6 mm nominal) / Windows 7.5 mm
TOUCH_TARGET_PLATFORM_FLOOR_MM = 4.4   # [derived] iOS HIG minimum 28 pt at ~0.157 mm/pt
TOUCH_TARGET_ONE_HAND_MM = 9.2         # [paper] Parhi, Karlson & Bederson 2006 (discrete thumb taps)
TOUCH_TARGET_MOTOR_IMPAIRED_MM = 18.0  # [paper] Findlater et al. 2017 (upper-body motor impairment)
PLATFORM_SPACING_MM = 1.27             # [standard] Material 8 dp between targets (8/160 in)
TOUCH_TARGET_SERIAL_MM = 9.6           # [paper] Parhi et al. 2006 (serial thumb taps)
GAME_CONTROL_EDGE_MIN_MM = 2.0         # [policy] HGR-11/MP-05: small non-zero edge gaps and system-gesture insets
POINTER_DESTRUCTIVE_MIN_GAP_CSS_PX = 8.0  # [standard] Material 8 dp spacing; Win32: separate destructive commands

# Dual-Gaussian tap model constants (Bi & Zhai 2016): sigma^2 = a*W^2 + b (mm^2).
DUAL_GAUSSIAN = {"x": (0.0075, 1.68), "y": (0.0108, 1.33)}  # [paper]

# Touch SD multipliers (sensitivity analysis). All are [assumption] except
# where noted; see docs/human-factors/motor-pointing.md MP-11/MP-12.
TOUCH_SIGMA_MULT = {
    # Parhi 2006 95 % thumb hit box (9.1 x 8.9 mm for 9.6 mm targets) implies
    # sigma ~2.3 mm vs ~1.5 mm from the index-finger model -> ratio ~1.5 [derived];
    # the box includes location-dependent offsets, so 1.3 is used [assumption].
    "one_hand_thumb": 1.3,
    "mobility_seated": 1.0,
    # [derived] back-calculated from Conradi et al. 2015 (walking vs standing error at
    # 5-8 mm targets): 1.27-1.74 by baseline posture (situational brief SIT-03, MP-11).
    # Ng, Brewster & Williamson 2014's +40 % is an encumbrance effect, not walking.
    "mobility_walking": 1.4,
    "mobility_transit": 1.4,    # [assumption] an alias of walking (no separate data)
    # [assumption] Ng et al. 2014 report +40% mean absolute distance error,
    # not a 1.4 multiplier of coordinate SD; all conditions involved walking.
    "encumbered": 1.4,
    "tremor_none": 1.0,
    "tremor_mild": 1.3,         # [derived] essential-tremor amplitude and Findlater & Zhang 2020 open data (self-reported tremor 1.07-1.15); was 1.5
    "tremor_moderate": 1.8,     # [derived] as above; was 2.25
    "age_60s": 1.10,            # [derived] Findlater & Zhang 2020 open data, 60-70 vs young: 1.10 (95 % CI 0.99-1.21); was 1.15
    "age_70s+": 1.3,            # [assumption] no data for 70+ in the open dataset
}
# How profile factors combine. "multiplicative": product of the factors. "additive":
# independent noise adds in variance, k = sqrt(1 + sum(k_i^2 - 1)) (situational brief
# SIT-02). A sensitivity switch: additive changed no dev finding (round 8), so the
# default stays multiplicative.
TOUCH_SIGMA_COMBINE = "multiplicative"
# SIT-01: profile-only PT-03/PT-04 findings (none at k = 1) on targets whose label-
# inclusive short side meets the platform size are P3 at most; smaller critical
# targets already get P2 from PT-02. None turns the cap off. [policy; dev round 8]
TOUCH_PROFILE_ONLY_P3_MIN_MM: float | None = TOUCH_TARGET_MIN_MM
TOUCH_SIGMA_BASE_MM = 1.30  # [derived] sqrt(1.68) absolute x-term of Bi & Zhai 2016

# PT-04 severity by predicted miss probability on a critical/path target. [policy]
# (MP-02: P1 if P(hit) < 0.90, P2 < 0.95, P3 < 0.97.)
MISS_PROBABILITY_SEVERITY = ((0.10, "P1"), (0.05, "P2"), (0.03, "P3"))

# PT-03 misfire policy (MP-03). [policy]
DESTRUCTIVE_NEIGHBOUR_PROB = 0.01        # P2 at >= 1 %
DESTRUCTIVE_NEIGHBOUR_PROB_HIGH = 0.05   # P1 at >= 5 %
DESTRUCTIVE_MIN_GAP_MM = PLATFORM_SPACING_MM  # P3 when spacing below platform recommendation

# Fitts (MacKenzie, Sellen & Buxton 1991 mouse pointing): MT = -107 + 223*ID ms. [paper]
FITTS_MOUSE_A_MS = -107.0
FITTS_MOUSE_B_MS = 223.0
FITTS_ID_HIGH_BITS = 6.0  # [policy] relative comparison flag only (P3)

# KLM operator times (Card, Moran & Newell 1980; Kieras). [paper]
KLM_MS = {"K": 280.0, "P": 1100.0, "B": 100.0, "H": 400.0, "M": 1350.0}
# Touch movement-only values (El Batran & Dunlop 2014). [paper, snippet-level]
KLM_TOUCH_MS = {"P": 80.0}

# ------------------------------------------------------------------ reach
# Filled from docs/human-factors/handedness-grip-reach.md (see reach.py).
REACH_EASY_MAX = 0.2      # [policy] "natural" zone upper bound
REACH_HARD = 0.6          # [policy] stretch zone lower bound -> P3 on path targets
REACH_UNREACHABLE = 1.0   # [policy] needs a grip change -> P2 (P1 one-handed + walking)

# Thumb length L for the reach model uses Parhi et al. 2006's landmark (thumb tip
# to base; US lab sample, 17/20 men: range 99-125, mean 115, SD 5.75 mm). [paper]
# Size Korea's "thumb length" (~81 mm) uses a different landmark and cannot be
# copied. Korean values are [derived] by scaling Parhi's L with Korean hand
# length (men 185.95 +- 8.13, women 172.40 +- 7.15 mm, n=325, Kim & Kee 2012
# [snippet]) relative to a ~192 mm US male reference (Otten et al. 2013): they are
# [assumption]s until calibrated with thumb-sweep data.
THUMB_LENGTH_MM = {"all": (107.0, 6.5), "male": (111.0, 5.6), "female": (103.0, 5.0)}
TOUCH_TARGET_CORNER_MM = 11.0  # [paper, secondary] Hoober 2017: ~11-12 mm at edges/corners
LANDSCAPE_REST_INSET_MM = (25.0, 22.0)  # [assumption] thumb rest points inset from lower side corners
LANDSCAPE_TRAVEL_MAX_MM = 35.0  # [policy] frequent game control travel from nearest thumb rest

# ------------------------------------------------------------------ populations (base rates for plausible combos, not estimates)
HANDEDNESS_SHARE_KR = {"right": 0.863, "left": 0.058, "mixed": 0.079}  # [paper, snippet] Jung et al. 2009, Ergonomics 52(11), N=2,437
# Left-handed share by age, Gallup Korea Nov 2025 (n=1,700, aged 13+) [secondary]:
# 13-18: 13 %, 19-29: 12 %, 30s: 8 %, 40s: 6 %, 50s: 4 %, 60+: 3 %.
LEFT_SHARE_BY_AGE_KR = {"10s": 0.13, "20s": 0.12, "30s": 0.08, "40s": 0.06, "50s": 0.04, "60s": 0.03, "70s+": 0.03}
MOBILE_GRIP_SHARE = {"one_hand": 0.49, "cradle": 0.36, "two_thumbs": 0.15}  # [paper] Hoober 2013 (N=1,333, North America; Korean grip mix unconfirmed)
LEFT_HANDERS_MOUSE_LEFT_SHARE = 0.3  # [assumption] many left-handers mouse right-handed; unconfirmed
# Age bands 10s-70s+ from the resident registration population, 2025-12-31
# (행정안전부, 51,117,378; 0-9 excluded and renormalised) [secondary, snippet].
AGE_BAND_SHARE_KR = {
    "10s": 0.0961, "20s": 0.1180, "30s": 0.1386, "40s": 0.1574, "50s": 0.1793, "60s": 0.1645, "70s+": 0.1461,
}
CVD_MALE_SHARE_KR = 0.059    # [snippet] J Korean Med Sci 1989 (HRR plates); KNHANES 2013 (19-49): 0.065
CVD_FEMALE_SHARE_KR = 0.0044  # [snippet] 1989; KNHANES 2013: 0.011
CVD_TYPE_SHARE = {"deutan": 0.86, "protan": 0.14}  # [snippet->derived] Korea deutan:protan ~ 2.5:0.4; tritan is a scenario, not sampled

BASE_RATE_REFS = {
    "handedness": "REF-kr-handedness-2009; REF-gallup-kr-2025",
    "grip": "REF-hoober2013",
    "age_band": "REF-kr-population",
    "cvd": "REF-kr-cvd",
}

# ------------------------------------------------------------------ perception
CONTRAST_SEVERE = 3.0            # [policy] body text under 3:1 -> P1
CONTRAST_BRIGHT_LIGHT = 7.0      # [standard] WCAG 1.4.6 AAA used as outdoor margin [policy]
NON_TEXT_CONTRAST_MIN = 3.0      # [standard] WCAG 1.4.11
CVD_DISTINCT_NORMAL_DE = 20.0    # [policy] colours intended as different categories under normal vision
CVD_CONFUSABLE_DE = 5.0          # [snippet+policy] below: confusable after simulation (JND ~1; Palettailor uses 10 as distinct)
CVD_MARGINAL_DE = 10.0           # [snippet+policy] 5-10: marginal; >= 10 distinct
CVD_STATE_CONTRAST_EXEMPT = 3.0  # [recalled] WCAG technique G183: >= 3:1 luminance contrast between states is a non-colour cue
# Legacy CSS em proxy thresholds remain project policy: character height,
# Latin x-height and cap-height are different metrics. No ISO/HIG conformance.
TEXT_PLATFORM_MIN_CSS_PX_MOBILE = 11.0  # [policy] retained CSS px floor; Apple HIG's 11pt applies to Apple platform points
TEXT_FLOOR_ARCMIN = 16.0         # [policy] retained em-angle floor; character-height source applicability unverified
TEXT_MIN_ARCMIN = 24.6           # [policy] retained young-adult em proxy; Hangul CPS snippet metric unconfirmed
TEXT_MIN_ARCMIN_PRESBYOPIA = 31.2  # [policy] retained older-adult em proxy; no calibrated individual reading prediction
# Presbyopia is represented by the older-adult critical print size at the normal
# viewing distance (Hofstetter: near point 15 - 0.25*age D, usually corrected).
HUD_MIN_ARCMIN = 16.0            # [policy] retained em-angle proxy, not measured character height
HUD_PLATFORM_MIN_PX_1080 = {"tv": 26.0, "handheld_console": 26.0, "desktop": 18.0, "laptop": 18.0}  # [standard] XAG 101 rendered ascender-to-descender body pixels, not CSS em
BODY_TEXT_MIN_CHARS = 12         # [policy] strings at least this long count as body text

# ------------------------------------------------------------------ gaze
GAZE_CENTRE_SURROUND_CELLS = ((1, 4), (2, 8))  # [policy] centre/surround box radii in grid cells
GAZE_CUE_WEIGHTS = {"size": 0.35, "text": 0.25, "contrast": 0.25, "fill": 0.15}  # [policy]
GAZE_COMBINE_WEIGHTS = {"bottom_up": 0.4, "prior": 0.3, "cue": 0.3}  # [policy]
GAZE_SACCADE_DISCOUNT = 1.5    # [policy] greedy report scanpath only
GAZE_AD_PENALTY = 0.6          # [policy] banner blindness: banners found ~58 % vs 94 % for links (Benway & Lane 1998)
GAZE_MC_RUNS = 300             # [policy] Monte Carlo scanpaths per snapshot
GAZE_MC_FIXATIONS = 10         # [snippet] ~3-4 fixations per second of viewing
GAZE_MC_GAMMA = 2.0            # [policy]
GAZE_MC_LAMBDA_DEG = 5.0       # [policy] saccade distance penalty (degrees)
GAZE_MC_IOR = 0.1              # [policy] inhibition of return
GAZE_MC_DIR_BIAS = 0.3         # [snippet] UEyes: saccades tend rightward/downward
GAZE_EARLY_FIXATIONS = 4       # [snippet->policy] ~1 s of viewing
GAZE_PRIMARY_PASS = 0.8        # [policy] P(primary fixated within early fixations) >= 0.8 passes
GAZE_PRIMARY_P2 = 0.5          # [policy] < 0.5 -> P2, 0.5-0.8 -> P3
GAZE_COMPETITORS_MAX = 4       # [policy]
# Feedback-noticing bands (likely <= a, uncertain a..b, likely missed > b), degrees. [policy]
# Anchored on UFOV test eccentricities (10/20/30 deg) and parafoveal limits (~5 deg).
NOTICE_BANDS_DEG = {"salient": (10.0, 20.0), "non_salient": (2.0, 5.0)}
NOTICE_PERSONA_SCALE = 0.7     # [assumption] 70+, low vision, high load: UFOV shrinks with age/load (magnitude unconfirmed)
SALIENT_CHANGE_MIN_DEG = 1.0   # [policy] a salient change is >= 1 deg
SALIENT_CHANGE_MIN_CONTRAST = 3.0  # [policy] and >= 3:1 against its surroundings
OCCLUSION_WEDGE_DEG = 35.0     # [assumption] HGR-8 thumb/hand occlusion wedge around touch->pivot vector
AD_RAIL_X_FRAC = 0.78          # [policy] right-rail zone on desktop
AD_BANNER_Y_FRAC = 0.15        # [policy]
AD_BANNER_MAX_H = 120          # [policy] CSS px

# ------------------------------------------------------------------ cognition
HICK_A_MS = 200.0              # [paper] provisional; perception brief
HICK_B_MS_PER_BIT = 150.0      # [paper] provisional
CHOICE_OVERLOAD_MAX = 9        # [policy] provisional
READING_ORIENT_MS = 500.0      # [assumption] time to notice/orient to a transient message
READING_LATIN_WPM = 200.0      # [paper] provisional
READING_SYLLABLES_PER_MIN = {  # [derived] Korean adults ~9.8 syll/s mean (~587/min); older ~30 % slower (~410)
    "10s": 587, "20s": 587, "30s": 587, "40s": 560, "50s": 500, "60s": 410, "70s+": 380,
}
READING_SLOW_SYLLABLES_PER_MIN = {  # [derived] -1 SD readers used by timing checks (adult ~330, older ~290)
    "10s": 330, "20s": 330, "30s": 330, "40s": 330, "50s": 310, "60s": 290, "70s+": 290,
}
TOAST_FLOOR_MS = 4000.0        # [snippet] Material snackbar lower bound 4 s
TOAST_SAFETY_FACTOR = 1.5      # [policy]
LATENCY_INSTANT_MS = 100.0     # [paper] Miller 1968 / Nielsen 1993
LATENCY_DOHERTY_MS = 400.0     # [recalled] Doherty & Thadani 1982 productivity threshold
LATENCY_FLOW_MS = 1000.0       # [paper]
LATENCY_ATTENTION_MS = 10000.0  # [paper]

# ------------------------------------------------------------------ game
FLASH_DELTA = 0.10             # [standard] WCAG general flash: 10 % of max relative luminance
FLASH_DARK_LIMIT = 0.80        # [standard] darker image below 0.80
FLASH_AREA_SR = 0.006          # [standard] WCAG 2.3.1 combined area threshold (25 % of any 10 deg field)
FLASH_EXTENDED_WINDOW_MS = 5000.0   # [policy] sustained rule: 10 or more flashes within 5 s -> P1
FLASH_EXTENDED_MIN_FLASHES = 10.0   # [derived] 2 flashes/s held over the 5 s window
# EA IRIS extended failure (src/TransitionTracker.cpp, config/appsettings.json at d96978a):
# a frame counts when its 1 s transition count is MinTransitions..MaxTransitions; the
# failure is a frame whose count is >= MinTransitions after ExtendedFailSeconds of such
# frames within the last ExtendedFailWindow seconds. [code]
FLASH_IRIS_MIN_TRANSITIONS = 4
FLASH_IRIS_MAX_TRANSITIONS = 6
FLASH_IRIS_EXTENDED_SECONDS = 4.0
FLASH_IRIS_EXTENDED_WINDOW_S = 5.0
FLASH_IRIS_FRAME_MS = 10.0          # [policy] virtual frame clock for IRIS's frame-based counters
FLASH_RED_RATIO = 0.8              # [standard] WCAG 2.2 red flash: R/(R+G+B) >= 0.8 (saturated red)
# Block-grid screening (flash samples with block_lum/block_red; docs/human-factors/game-ux-ergonomics.md 2.1).
FLASH_WINDOW_MS = 1000.0           # [standard] "any one-second period"
FLASH_WINDOW_TOLERANCE_MS = 50.0  # [policy] sampling sees a transition up to one capture interval late; a 3 Hz flicker must not fail on that lag
FLASH_FAIL_TRANSITIONS = 7         # [standard] more than 3 flashes = more than 6 transitions (Trace wording)
FLASH_FIELD_DEG = 10.0             # [standard] the 0.006 sr limit applies within any 10 degree visual field
FLASH_RED_SHARE_DELTA = 0.10       # [policy] a red transition moves >= 10 % of a block into/out of saturated red
FLASH_RED_EXCESS = 20.0 / 320.0    # [standard] WCAG 2.0 red flash note: (R-G-B)*320 > 20 on linear RGB (driver pixel test)
FLASH_MIN_FPS = 20.0               # [policy] below 20 samples/s (Nyquist 10 Hz) a pass is reported as inconclusive
FLASH_MAX_GAP_MS = 100.0           # [policy] a longer gap inside a sampling window is reported (can hide one 5 Hz flash pair)
QTE_MOTOR_MS = 100.0           # [assumption] provisional; game brief
RT_CV = 0.2                    # [assumption] provisional coefficient of variation of RT
INPUT_LATENCY_MS = {"touch": 80.0, "mouse": 20.0, "keyboard": 20.0, "gamepad": 50.0, "remote": 100.0}  # [assumption]

CHOICE_RT_MS_BY_AGE = {  # [assumption] per-decade values were not retrieved from Der & Deary 2006 (game brief); provisional
    "10s": 420, "20s": 420, "30s": 440, "40s": 460, "50s": 490, "60s": 530, "70s+": 580,
}


def reading_rate_for_age(age_band: str) -> int:
    return int(READING_SYLLABLES_PER_MIN.get(age_band, READING_SYLLABLES_PER_MIN["30s"]))


def choice_reaction_ms_for_age(age_band: str) -> int:
    return int(CHOICE_RT_MS_BY_AGE.get(age_band, CHOICE_RT_MS_BY_AGE["30s"]))

# Elements covered at >= this fraction of sample points (sheet, scrim, overlay) are
# not evaluated in that snapshot. [policy] (adjudication 2026-09-28: wrong-state findings)
OCCLUDED_MIN_FRACTION = 0.5

# GZ-02 salience of new messages: bold or icon-led text at >= 4.5:1 counts as a salient
# object (abrupt onsets capture attention; Yantis & Jonides 1984) [policy].
SALIENT_TEXT_MIN_CONTRAST = 4.5
SALIENT_ICON_CHARS = "⚠✓✔✗✕!❗ⓘ✅❌"
# An action that removes >= 60 % of the visible elements replaced the screen; feedback
# there is not peripheral (GZ-02 skipped). [policy]
SCREEN_CHANGE_FRACTION = 0.6
# When the app itself scrolls the view by at least half a screen during a step (a form
# jumping to its first error), the content under the tap has moved away and the user
# re-orients to the new view, as after a screen replacement: GZ-02 does not measure
# eccentricity from the old tap point (off-screen messages are still checked). [policy]
APP_SCROLL_REORIENT_FRACTION = 0.5

# Measured visible durations carry polling jitter (16 ms poll plus capture); a toast
# hidden by setTimeout(4000) measured 3995 ms. [policy]
TIMING_JITTER_MS = 50

# Reach is scored at the easiest point of a target, inset this far from its edges so
# the finger pad fits inside the target. [policy]
REACH_TARGET_INSET_MM = 3.0
