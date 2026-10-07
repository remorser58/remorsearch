"""Heuristic visual-attention (gaze priority) model for a screenshot + elements.

Model ``gaze-priority-v3`` (docs/human-factors/gaze-visual-attention.md). It is a
population-level PRIORITY model, not an eye tracker, and it is not calibrated
against eye-tracking data in this repository. It combines:

1. bottom-up conspicuity from the screenshot (Itti-Koch style centre-surround
   contrast on luminance and two colour-opponent channels on a coarse grid);
2. a layout position prior fitted by hand to reported GUI tendencies:
   upper-left pull for every UI type in UEyes (CHI 2023; free viewing of
   screenshots) and Leiva et al. (MobileHCI 2020; segmented elements, lab
   viewing), left-half dominance on desktop web (NN/g 2010/2017), a two-band
   pattern for desktop apps; TV has no dataset (assumption);
3. element cues (size, text weight/size, contrast; text matters more than colour
   for mobile UIs per Leiva et al.);
4. a Monte Carlo scanpath over visual regions. Fixations are sampled with a
   distance penalty in visual degrees, inhibition of return and a slight
   rightward/downward bias. The result is a hit fraction of the runs, not a
   calibrated probability that a person sees the region. Free-viewing priors
   do not predict goal-directed search.

Duplicate nodes of one visible region share a single sample. The angle between
two display points is the angle between rays from an explicit eye position.
``eccentricity_deg`` and ``eccentricity_deg_css`` keep the historical call:
the eye's perpendicular foot is the first point, and one CSS scale is used
for both axes when no y scale is passed. Checks pass the viewport centre and
both axis scales; that foot is an unmeasured assumption, not a tracked eye.

Gutenberg and Z-patterns have no eye-tracking support and are not encoded.
Every observation produced from this module is ``inferred`` (basis ``model``).
"""

from __future__ import annotations

import math
import random
from typing import Any, Sequence

from .. import params
from ..snapshot import is_number

MODEL_ID = "gaze-priority-v3"
GEOMETRY_ID = "two-ray-display-v1"
EYE_PROJECTION = "viewport_centre_unmeasured"
ANGLE_MODEL = "two_ray_atan2_cross_dot"
START_LAST_ACTION = "last_action_focus_point"
START_PRIOR_PEAK = "layout_prior_peak"

# Clipped boxes that round to the same 0.01 CSS px are the same visible rectangle.
# The extractor already stores boxes at that precision (page_scripts round2).
_BOX_DECIMALS = 2

Grid = list[list[float]]

# Position priors: mixtures of anisotropic Gaussians on the unit square
# (weight, mu_x, mu_y, sigma_x, sigma_y). [policy] fitted by hand to the reported
# tendencies; refit from UEyes per-type mean fixation maps before relying on them.
PRIORS: dict[str, list[tuple[float, float, float, float, float]]] = {
    "mobile": [(1.0, 0.35, 0.25, 0.30, 0.30)],
    "web": [(1.0, 0.26, 0.30, 0.25, 0.35)],  # mu_x 0.26 reproduces the ~80 % left-half share
    "desktop": [(0.6, 0.50, 0.40, 0.25, 0.15), (0.4, 0.15, 0.12, 0.12, 0.10)],
    "tv": [(1.0, 0.50, 0.42, 0.25, 0.25)],  # [assumption] no TV/game dataset; poster-like
}


def prior_kind(form_factor: str, surface_kind: str = "web") -> str:
    if form_factor in ("phone", "foldable", "tablet", "handheld_console"):
        return "mobile"
    if form_factor == "tv":
        return "tv"
    return "web" if surface_kind == "web" else "desktop"


def _box_blur(grid: Grid, radius: int) -> Grid:
    h = len(grid)
    w = len(grid[0]) if h else 0
    if radius <= 0 or h == 0:
        return [row[:] for row in grid]
    sat = [[0.0] * (w + 1) for _ in range(h + 1)]
    for y in range(h):
        acc = 0.0
        for x in range(w):
            acc += grid[y][x]
            sat[y + 1][x + 1] = sat[y][x + 1] + acc
    out = [[0.0] * w for _ in range(h)]
    for y in range(h):
        y0, y1 = max(0, y - radius), min(h, y + radius + 1)
        for x in range(w):
            x0, x1 = max(0, x - radius), min(w, x + radius + 1)
            total = sat[y1][x1] - sat[y0][x1] - sat[y1][x0] + sat[y0][x0]
            out[y][x] = total / ((y1 - y0) * (x1 - x0))
    return out


def _normalise(grid: Grid) -> Grid:
    flat = [v for row in grid for v in row]
    if not flat:
        return grid
    lo, hi = min(flat), max(flat)
    if hi - lo < 1e-9:
        return [[0.0 for _ in row] for row in grid]
    scaled = [[(v - lo) / (hi - lo) for v in row] for row in grid]
    mean = sum(v for row in scaled for v in row) / len(flat)
    weight = (1.0 - mean) ** 2  # promote maps with few strong peaks (Itti-Koch)
    return [[v * weight for v in row] for row in scaled]


def conspicuity_map(pixels: Sequence[Sequence[tuple[float, float, float]]]) -> Grid:
    """Bottom-up conspicuity for a coarse RGB grid (values 0..255) -> [0, 1]."""
    h = len(pixels)
    w = len(pixels[0]) if h else 0
    if h == 0 or w == 0:
        return []
    lum = [[(0.299 * r + 0.587 * g + 0.114 * b) / 255.0 for (r, g, b) in row] for row in pixels]
    rg = [[(r - g) / 255.0 for (r, g, b) in row] for row in pixels]
    by = [[(b - (r + g) / 2.0) / 255.0 for (r, g, b) in row] for row in pixels]
    maps: list[Grid] = []
    for channel in (lum, rg, by):
        for centre_r, surround_r in params.GAZE_CENTRE_SURROUND_CELLS:
            c = _box_blur(channel, centre_r)
            s = _box_blur(channel, surround_r)
            maps.append(_normalise([[abs(c[y][x] - s[y][x]) for x in range(w)] for y in range(h)]))
    total = [[sum(m[y][x] for m in maps) for x in range(w)] for y in range(h)]
    flat_max = max(max(row) for row in total) or 1.0
    return [[v / flat_max for v in row] for row in total]


def position_prior(x_frac: float, y_frac: float, kind: str) -> float:
    """Layout prior (unnormalised, peak ~1) for a normalised position (0,0 = top-left)."""
    comps = PRIORS.get(kind, PRIORS["web"])
    return sum(w * math.exp(-(((x_frac - mx) ** 2) / (2 * sx * sx) + ((y_frac - my) ** 2) / (2 * sy * sy)))
               for w, mx, my, sx, sy in comps)


def prior_peak(kind: str) -> tuple[float, float]:
    comps = PRIORS.get(kind, PRIORS["web"])
    w, mx, my, _, _ = max(comps, key=lambda c: c[0])
    return mx, my


def element_cue(element: dict[str, Any]) -> float:
    """Attention cue from the element itself (size, text emphasis, contrast)."""
    box = element.get("box") or {}
    area = max(1.0, float(box.get("w", 0)) * float(box.get("h", 0)))
    size_term = min(1.0, math.log10(area) / 5.0)
    font = float(element.get("font_size_px") or 0)
    weight = float(element.get("font_weight") or 400)
    text_term = min(1.0, font / 32.0) * (1.25 if weight >= 600 else 1.0)
    if (element.get("text") or "").strip():
        text_term = max(text_term, 0.2)
    contrast = float(element.get("_contrast") or 0.0)
    contrast_term = min(1.0, max(0.0, (contrast - 1.0) / 6.0))
    fill_term = float(element.get("_fill_contrast") or 0.0)
    return (
        params.GAZE_CUE_WEIGHTS["size"] * size_term
        + params.GAZE_CUE_WEIGHTS["text"] * text_term
        + params.GAZE_CUE_WEIGHTS["contrast"] * contrast_term
        + params.GAZE_CUE_WEIGHTS["fill"] * min(1.0, fill_term)
    )


def element_priorities(
    elements: Sequence[dict[str, Any]],
    viewport: tuple[float, float],
    kind: str,
    conspicuity: Grid | None = None,
) -> dict[str, float]:
    """Priority in [0, 1] per element id (visible, in-viewport elements only)."""
    if _pair(viewport) is None or min(viewport) <= 0:
        return {}
    vw, vh = viewport
    scores: dict[str, float] = {}
    gh = len(conspicuity) if conspicuity else 0
    gw = len(conspicuity[0]) if gh else 0
    peak = max(position_prior(x / 20, y / 20, kind) for x in range(21) for y in range(21)) or 1.0
    for element in elements:
        visible = clipped_visible_box(element, viewport)
        if visible is None:
            continue
        x0, y0, width, height = visible
        x1, y1 = x0 + width, y0 + height
        cx, cy = (x0 + x1) / 2 / vw, (y0 + y1) / 2 / vh
        bottom_up = 0.0
        if gh and gw:
            gx0 = int(x0 / vw * gw)
            gx1 = max(gx0 + 1, int(math.ceil(x1 / vw * gw)))
            gy0 = int(y0 / vh * gh)
            gy1 = max(gy0 + 1, int(math.ceil(y1 / vh * gh)))
            cells = [conspicuity[y][x] for y in range(gy0, min(gy1, gh)) for x in range(gx0, min(gx1, gw))]
            if cells:
                cells.sort(reverse=True)
                top = cells[: max(1, len(cells) // 4)]
                bottom_up = sum(top) / len(top)
        prior = position_prior(cx, cy, kind) / peak
        cue = element_cue({**element, "box": {"w": width, "h": height}})
        w = params.GAZE_COMBINE_WEIGHTS
        penalty = params.GAZE_AD_PENALTY if "ad_like" in (element.get("roles") or []) else 1.0
        scores[element["id"]] = (w["bottom_up"] * bottom_up + w["prior"] * prior + w["cue"] * cue) * penalty
    if scores:
        hi = max(scores.values()) or 1.0
        scores = {k: v / hi for k, v in scores.items()}
    return scores


def _pair(point: object) -> tuple[float, float] | None:
    if isinstance(point, (tuple, list)) and len(point) == 2 and all(is_number(v) for v in point):
        return float(point[0]), float(point[1])
    return None


def angular_separation_mm(
    point_a_mm: tuple[float, float], point_b_mm: tuple[float, float],
    viewing_distance_mm: float, eye_mm: tuple[float, float] | None = None,
) -> float | None:
    """Exact two-ray angle; the eye projection defaults to a for legacy calls.

    The eye is at (eye_x, eye_y, distance) over a flat display. The projection
    and viewing distance are declared assumptions unless actually measured.
    Invalid coordinates/distance return None, never a successful measurement.
    """
    a, b = _pair(point_a_mm), _pair(point_b_mm)
    eye = a if eye_mm is None else _pair(eye_mm)
    if a is None or b is None or eye is None or not is_number(viewing_distance_mm) or viewing_distance_mm <= 0:
        return None
    u = (a[0] - eye[0], a[1] - eye[1], viewing_distance_mm)
    v = (b[0] - eye[0], b[1] - eye[1], viewing_distance_mm)
    un, vn = math.hypot(*u), math.hypot(*v)
    if not math.isfinite(un) or not math.isfinite(vn):
        return None
    ux, uy, uz = (c / un for c in u)
    vx, vy, vz = (c / vn for c in v)
    cross = math.hypot(uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx)
    dot = ux * vx + uy * vy + uz * vz
    return math.degrees(math.atan2(cross, dot))


def angular_separation_css(
    point_a_css: tuple[float, float], point_b_css: tuple[float, float],
    mm_per_css_px_x: float, mm_per_css_px_y: float, viewing_distance_mm: float,
    eye_css: tuple[float, float],
) -> float | None:
    """Two-ray angle with independent x/y scales and explicit eye projection."""
    a, b, eye = _pair(point_a_css), _pair(point_b_css), _pair(eye_css)
    if a is None or b is None or eye is None:
        return None
    if not all(is_number(v) and v > 0 for v in (mm_per_css_px_x, mm_per_css_px_y, viewing_distance_mm)):
        return None
    sx, sy = mm_per_css_px_x, mm_per_css_px_y
    return angular_separation_mm((a[0] * sx, a[1] * sy), (b[0] * sx, b[1] * sy),
                                 viewing_distance_mm, (eye[0] * sx, eye[1] * sy))


def clipped_visible_box(element: dict[str, Any], viewport: tuple[float, float]) -> tuple[float, float, float, float] | None:
    """Gaze-only viewport/ancestor intersection; raw target geometry is preserved.

    A clipped paint/text cue is unverified: abstain instead of scoring hidden
    font/fill as visible. Older captures with no visible_box keep viewport-only
    intersection. Unsupported clipping shapes also abstain.
    """
    if element.get("visible", True) is False or element.get("in_viewport") is False:
        return None
    if element.get("visible_geometry") in ("ancestor_clipped", "unsupported", "empty"):
        return None
    if "clipped_paint" in (element.get("paint") or {}).get("gaps", []):
        return None
    frame = _pair(viewport)
    box = element.get("box")
    if frame is None or min(frame) <= 0 or not isinstance(box, dict):
        return None
    if not all(is_number(box.get(k)) for k in ("x", "y", "w", "h")) or min(box["w"], box["h"]) <= 0:
        return None
    x0, y0 = max(0.0, box["x"]), max(0.0, box["y"])
    x1, y1 = min(frame[0], box["x"] + box["w"]), min(frame[1], box["y"] + box["h"])
    if "visible_box" in element:
        visible = element["visible_box"]
        if not isinstance(visible, dict) or not all(is_number(visible.get(k)) for k in ("x", "y", "w", "h")):
            return None
        x0, y0 = max(x0, visible["x"]), max(y0, visible["y"])
        x1, y1 = min(x1, visible["x"] + visible["w"]), min(y1, visible["y"] + visible["h"])
    return (x0, y0, x1 - x0, y1 - y0) if x1 > x0 and y1 > y0 else None


def _visual_key(element: dict[str, Any]) -> tuple:
    # IDs/selectors do not influence the sample order. Geometry, visual cues and
    # interaction semantics order distinct coincident regions deterministically.
    b = element["box"]
    return (b["y"], b["x"], b["h"], b["w"], element.get("text") or "", element.get("role") or "",
            bool(element.get("interactive")), element_cue(element), tuple(sorted(element.get("roles") or [])))


def _same_region(a: dict[str, Any], b: dict[str, Any]) -> bool:
    if any(round(a["box"][k], _BOX_DECIMALS) != round(b["box"][k], _BOX_DECIMALS) for k in ("x", "y", "w", "h")):
        return False
    # An API may expose several records for one DOM node with different selectors.
    same_node = any(a.get(k) and a.get(k) == b.get(k) for k in ("dom_id", "selector"))
    if a.get("interactive") and b.get("interactive") and not same_node:
        return False
    contained = bool((a.get("dom_id") and a["dom_id"] in (b.get("ancestor_ids") or []))
                     or (b.get("dom_id") and b["dom_id"] in (a.get("ancestor_ids") or [])))
    text_a, text_b = " ".join((a.get("text") or "").split()), " ".join((b.get("text") or "").split())
    if text_a != text_b or (a.get("role") != b.get("role") and not contained):
        return False
    if same_node or contained:
        return True
    # Distinct controls, siblings with different DOM identity and empty boxes are
    # never aliases merely because they overlap or share an accessible name.
    if a.get("interactive") or b.get("interactive") or not text_a:
        return False
    if a.get("dom_id") and b.get("dom_id") and a["dom_id"] != b["dom_id"]:
        return False
    return a.get("ancestor_ids") == b.get("ancestor_ids") and element_cue(a) == element_cue(b)


def equivalent_regions(elements: Sequence[dict[str, Any]], viewport: tuple[float, float]) -> list[dict[str, Any]]:
    """One region per visual entity, with original IDs retained for reporting."""
    buckets: dict[tuple, list[list[dict[str, Any]]]] = {}
    for e in sorted((e for e in elements if isinstance(e.get("id"), str)
                     and clipped_visible_box(e, viewport) is not None),
                    key=lambda e: (not e.get("interactive", False), _visual_key(e))):
        b = clipped_visible_box(e, viewport)
        assert b is not None
        key = tuple(round(v, _BOX_DECIMALS) for v in b)
        groups = buckets.setdefault(key, [])
        matches = [g for g in groups if all(_same_region(e, member) for member in g)]
        if len(matches) == 1:
            matches[0].append(e)
        else:
            groups.append([e])
    regions = []
    for (x, y, w, h), groups in buckets.items():
        for members in groups:
            regions.append({"member_ids": tuple(sorted({e["id"] for e in members})),
                            "box": {"x": x, "y": y, "w": w, "h": h},
                            "centre": (x + w / 2, y + h / 2), "visual_key": min(_visual_key(e) for e in members)})
    return sorted(regions, key=lambda r: (r["box"]["y"], r["box"]["x"], r["box"]["h"], r["box"]["w"], r["visual_key"]))


def fixation_probabilities(
    centres_css: dict[str, tuple[float, float]],
    priorities: dict[str, float],
    start_css: tuple[float, float],
    mm_per_css_px: float,
    viewing_distance_mm: float,
    n_runs: int | None = None,
    n_fix: int | None = None,
    seed: int = 1,
    mm_per_css_px_y: float | None = None,
    eye_css: tuple[float, float] | None = None,
) -> dict[str, list[float]]:
    """Monte Carlo hit fraction within the first k fixations, k = 1..n_fix.

    Visual position/priority set the sampling order. ``eye_css is None``
    puts the eye foot on the current point
    for each step (historical). A caller that passes ``eye_css`` uses that
    fixed foot for every step. Returns {} when the scale or the distance is
    not finite and positive, so a bad geometry does not become a hit fraction.
    """
    n_runs = params.GAZE_MC_RUNS if n_runs is None else n_runs
    n_fix = params.GAZE_MC_FIXATIONS if n_fix is None else n_fix
    if not isinstance(n_runs, int) or isinstance(n_runs, bool) or n_runs <= 0:
        return {}
    if not isinstance(n_fix, int) or isinstance(n_fix, bool) or n_fix <= 0:
        return {}
    scale_y = mm_per_css_px if mm_per_css_px_y is None else mm_per_css_px_y
    if not all(is_number(v) and v > 0 for v in (mm_per_css_px, scale_y, viewing_distance_mm)):
        return {}
    if eye_css is not None and _pair(eye_css) is None:
        return {}
    if _pair(start_css) is None:
        return {}
    rng = random.Random(seed)
    ids = sorted((i for i in centres_css if i in priorities and _pair(centres_css[i]) is not None
                  and is_number(priorities[i])), key=lambda i: (*centres_css[i], priorities[i]))
    hits = {i: [0] * n_fix for i in ids}
    if not ids:
        return {}
    for _ in range(n_runs):
        pos = start_css
        seen: set[str] = set()
        for k in range(n_fix):
            weights = []
            for i in ids:
                c = centres_css[i]
                foot = pos if eye_css is None else eye_css
                ecc = angular_separation_css(pos, c, mm_per_css_px, scale_y, viewing_distance_mm, foot)
                if ecc is None:
                    wgt = 0.0
                else:
                    wgt = (max(priorities[i], 1e-6) ** params.GAZE_MC_GAMMA) * math.exp(-ecc / params.GAZE_MC_LAMBDA_DEG)
                    if i in seen:
                        wgt *= params.GAZE_MC_IOR
                    if c[0] > pos[0] or c[1] > pos[1]:
                        wgt *= 1.0 + params.GAZE_MC_DIR_BIAS
                weights.append(wgt)
            total = sum(weights)
            if not math.isfinite(total) or total <= 0:
                return {}  # numerical underflow is unavailable simulation, never a hit
            pick = rng.random() * total
            acc = 0.0
            chosen = ids[-1]
            for i, wgt in zip(ids, weights):
                acc += wgt
                if acc >= pick:
                    chosen = i
                    break
            if chosen not in seen:
                for kk in range(k, n_fix):
                    hits[chosen][kk] += 1
            seen.add(chosen)
            pos = centres_css[chosen]
    return {i: [h / n_runs for h in hits[i]] for i in ids}


def sample_equivalent_fixations(
    elements: Sequence[dict[str, Any]],
    priorities: dict[str, float],
    viewport: tuple[float, float],
    start_css: tuple[float, float],
    mm_per_css_px: float,
    viewing_distance_mm: float,
    mm_per_css_px_y: float | None = None,
    eye_css: tuple[float, float] | None = None,
    n_runs: int | None = None,
    n_fix: int | None = None,
    seed: int = 1,
) -> tuple[list[dict[str, Any]], dict[str, list[float]]]:
    """Sample one target per equivalent region and copy the fraction to every member.

    Region priority is the max member priority, so a duplicate does not add
    weight and does not compete with itself. Region order is the canonical
    geometry order from ``equivalent_regions``, not the input order.
    """
    prepared: list[dict[str, Any]] = []
    for region in equivalent_regions(elements, viewport):
        member_ids = tuple(i for i in region["member_ids"] if i in priorities and is_number(priorities[i]))
        if not member_ids:
            continue
        prepared.append({**region, "member_ids": member_ids, "priority": max(priorities[i] for i in member_ids)})
    centres = {str(index): region["centre"] for index, region in enumerate(prepared)}
    region_priority = {str(index): region["priority"] for index, region in enumerate(prepared)}
    raw = fixation_probabilities(
        centres, region_priority, start_css, mm_per_css_px, viewing_distance_mm,
        n_runs=n_runs, n_fix=n_fix, seed=seed, mm_per_css_px_y=mm_per_css_px_y, eye_css=eye_css,
    )
    if not raw:
        return prepared, {}
    length = n_fix if n_fix is not None else params.GAZE_MC_FIXATIONS
    shared: dict[str, list[float]] = {}
    for index, region in enumerate(prepared):
        series = list(raw.get(str(index), [0.0] * length))
        for member_id in region["member_ids"]:
            shared[member_id] = list(series)
    return prepared, shared


def predicted_scanpath(
    elements: Sequence[dict[str, Any]],
    priorities: dict[str, float],
    viewport: tuple[float, float],
    start: tuple[float, float] | None = None,
    max_fixations: int = 12,
) -> list[str]:
    """Deterministic greedy scanpath (for reports/heatmaps; checks use the Monte Carlo)."""
    remaining = [r for r in equivalent_regions(elements, viewport)
                 if any(i in priorities for i in r["member_ids"])]
    diag = math.hypot(*viewport) or 1.0
    pos = start
    path: list[str] = []
    while remaining and len(path) < max_fixations:
        def value(region: dict[str, Any]) -> float:
            score = max(priorities[i] for i in region["member_ids"] if i in priorities)
            if pos is not None:
                cx, cy = region["centre"]
                score *= math.exp(-params.GAZE_SACCADE_DISCOUNT * math.hypot(cx - pos[0], cy - pos[1]) / diag)
            return score
        region = max(remaining, key=value)
        path.append(next(i for i in region["member_ids"] if i in priorities))
        pos = region["centre"]
        remaining.remove(region)
    return path


def eccentricity_deg_css(a: tuple[float, float], b: tuple[float, float], mm_per_css_px: float,
                         viewing_distance_mm: float, mm_per_css_px_y: float | None = None,
                         eye_css: tuple[float, float] | None = None) -> float | None:
    """Legacy call assumes the eye projection is a; extended calls name both axes."""
    return angular_separation_css(a, b, mm_per_css_px,
                                  mm_per_css_px if mm_per_css_px_y is None else mm_per_css_px_y,
                                  viewing_distance_mm, a if eye_css is None else eye_css)


def eccentricity_deg(point_a_mm: tuple[float, float], point_b_mm: tuple[float, float],
                     viewing_distance_mm: float, eye_mm: tuple[float, float] | None = None) -> float | None:
    """Legacy call assumes the eye projection is a; exact two-ray extension."""
    return angular_separation_mm(point_a_mm, point_b_mm, viewing_distance_mm, eye_mm)


def notice_band(theta_deg: float, salient: bool, persona_scale: float = 1.0) -> str:
    """Feedback-noticing band: likely / uncertain / likely_missed ([policy] bands)."""
    likely, uncertain = params.NOTICE_BANDS_DEG["salient" if salient else "non_salient"]
    likely *= persona_scale
    uncertain *= persona_scale
    if theta_deg <= likely:
        return "likely"
    if theta_deg <= uncertain:
        return "uncertain"
    return "likely_missed"
