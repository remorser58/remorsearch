"""Pointing, target-size and touch-accuracy models.

These are population-level models applied to measured geometry. Parameters live
in ergoqa/params.py with their sources; the functions stay pure.
"""

from __future__ import annotations

import math
from typing import Sequence

Box = dict  # {"x","y","w","h"} in CSS px

# Numerical search bound (mm) for equivalent_square_mm: far beyond any real touch
# target; only marks the bisection domain, never a design threshold.
EQUIV_SQUARE_SEARCH_MAX_MM = 40.0


def fitts_id(distance: float, width: float) -> float:
    """Shannon formulation of Fitts' index of difficulty (bits)."""
    if width <= 0:
        raise ValueError("target width must be positive")
    return math.log2(distance / width + 1.0)


def fitts_mt_ms(distance: float, width: float, a_ms: float, b_ms_per_bit: float) -> float:
    return a_ms + b_ms_per_bit * fitts_id(distance, width)


def ffitts_id(distance_mm: float, width_mm: float, sigma_a_mm: float) -> float:
    """Finger-Fitts (Bi, Li & Zhai 2013) index of difficulty.

    The effective width removes the absolute finger imprecision sigma_a from the
    nominal target width: ID = log2(A / sqrt(2*pi*e*(sigma^2 - sigma_a^2)) + 1),
    where sigma = W / sqrt(2*pi*e) is the spread a target of width W affords.
    When W is so small that sigma <= sigma_a the target is below the finger's
    absolute precision and the ID is unbounded; we return math.inf.
    """
    sigma = width_mm / math.sqrt(2 * math.pi * math.e)
    residual = sigma * sigma - sigma_a_mm * sigma_a_mm
    if residual <= 0:
        return math.inf
    we = math.sqrt(2 * math.pi * math.e * residual)
    return math.log2(distance_mm / we + 1.0)


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def dual_gaussian_sigma_mm(width_mm: float, axis: str, multiplier: float = 1.0,
                           constants: dict[str, tuple[float, float]] | None = None) -> float:
    """Tap endpoint SD for a target of width_mm (Bi & Zhai 2016 dual-Gaussian).

    sigma^2 = alpha * W^2 + sigma_a^2 per axis, with the published constants
    x: (0.0075, 1.68 mm^2), y: (0.0108, 1.33 mm^2). ``multiplier`` inflates the SD
    for profile conditions (thumb, walking, tremor); multipliers are declared
    assumptions, not fitted values.
    """
    table = constants or {"x": (0.0075, 1.68), "y": (0.0108, 1.33)}
    alpha, absolute = table[axis]
    return math.sqrt(alpha * width_mm * width_mm + absolute) * multiplier


def dual_gaussian_hit_probability(width_mm: float, height_mm: float, multiplier: float = 1.0) -> float:
    """2D tap success for a w x h target aimed at its centre (Bi & Zhai 2016)."""
    sx = dual_gaussian_sigma_mm(width_mm, "x", multiplier)
    sy = dual_gaussian_sigma_mm(height_mm, "y", multiplier)
    return math.erf(width_mm / (2 * math.sqrt(2) * sx)) * math.erf(height_mm / (2 * math.sqrt(2) * sy))


def equivalent_square_mm(reference_mm: float, multiplier: float, max_mm: float = EQUIV_SQUARE_SEARCH_MAX_MM,
                         tolerance_mm: float = 0.05) -> float | None:
    """Smallest square whose dual-Gaussian hit probability at ``multiplier``
    matches the ``reference_mm`` square at k = 1 (same-hit-probability size).

    A model-equivalent comparison for advice (SIT-05), not an accessibility
    requirement and not a calibrated human error rate. P(hit) of a square is
    monotone increasing in its side (the absolute sigma term dominates), so a
    bounded bisection is exact. ``None`` means no square was found within
    ``max_mm``: a matching size may still exist beyond the bound (or not — with
    the published constants sigma grows with W, so P(hit) saturates), so None is
    "unknown within the bound", never proof that size cannot help. The bound
    exists so the advice never recommends giant sizes.
    """
    if reference_mm <= 0:
        raise ValueError("reference_mm must be positive")
    if multiplier <= 0:
        raise ValueError("multiplier must be positive")
    if max_mm <= reference_mm:
        raise ValueError("max_mm must exceed reference_mm")
    target = dual_gaussian_hit_probability(reference_mm, reference_mm, 1.0)

    def hit(side: float) -> float:
        return dual_gaussian_hit_probability(side, side, multiplier)

    if hit(reference_mm) >= target:
        return reference_mm
    if hit(max_mm) < target:
        return None
    lo, hi = reference_mm, max_mm
    while hi - lo > tolerance_mm:
        mid = (lo + hi) / 2.0
        if hit(mid) >= target:
            hi = mid
        else:
            lo = mid
    return hi


def dual_gaussian_neighbour_probability(target_mm: dict, neighbour_mm: dict, multiplier: float = 1.0) -> float:
    """P(a tap aimed at target's centre lands inside neighbour); boxes in mm."""
    sx = dual_gaussian_sigma_mm(target_mm["w"], "x", multiplier)
    sy = dual_gaussian_sigma_mm(target_mm["h"], "y", multiplier)
    cx = target_mm["x"] + target_mm["w"] / 2.0
    cy = target_mm["y"] + target_mm["h"] / 2.0
    px = _norm_cdf((neighbour_mm["x"] + neighbour_mm["w"] - cx) / sx) - _norm_cdf((neighbour_mm["x"] - cx) / sx)
    py = _norm_cdf((neighbour_mm["y"] + neighbour_mm["h"] - cy) / sy) - _norm_cdf((neighbour_mm["y"] - cy) / sy)
    return px * py


def hit_probability_1d(width: float, sigma: float, offset: float = 0.0) -> float:
    """P(|landing - centre| within the target) for a Gaussian landing point.

    width and sigma in the same unit; offset is a systematic aim bias from the
    target centre (e.g. perceived-input-point offset).
    """
    if sigma <= 0:
        return 1.0 if abs(offset) <= width / 2 else 0.0
    half = width / 2.0
    return _norm_cdf((half - offset) / sigma) - _norm_cdf((-half - offset) / sigma)


def hit_probability(width_mm: float, height_mm: float, sigma_mm: float,
                    offset_mm: tuple[float, float] = (0.0, 0.0)) -> float:
    """Probability a touch aimed at the centre lands inside a w x h target."""
    return hit_probability_1d(width_mm, sigma_mm, offset_mm[0]) * hit_probability_1d(height_mm, sigma_mm, offset_mm[1])


def neighbour_hit_probability(target: Box, neighbour: Box, sigma_px: float) -> float:
    """Probability that a touch aimed at target's centre lands inside neighbour.

    Independent Gaussian per axis around the target centre (CSS px).
    """
    if sigma_px <= 0:
        return 0.0
    cx = target["x"] + target["w"] / 2.0
    cy = target["y"] + target["h"] / 2.0

    def interval(lo: float, hi: float, centre: float) -> float:
        return _norm_cdf((hi - centre) / sigma_px) - _norm_cdf((lo - centre) / sigma_px)

    px = interval(neighbour["x"], neighbour["x"] + neighbour["w"], cx)
    py = interval(neighbour["y"], neighbour["y"] + neighbour["h"], cy)
    return px * py


def box_gap(a: Box, b: Box) -> float:
    """Minimum edge-to-edge distance between two boxes (0 when overlapping)."""
    dx = max(0.0, max(a["x"], b["x"]) - min(a["x"] + a["w"], b["x"] + b["w"]))
    dy = max(0.0, max(a["y"], b["y"]) - min(a["y"] + a["h"], b["y"] + b["h"]))
    return math.hypot(dx, dy)


def centre(box: Box) -> tuple[float, float]:
    return (box["x"] + box["w"] / 2.0, box["y"] + box["h"] / 2.0)


def wcag_target_size_ok(target: Box, others: Sequence[Box], minimum: float = 24.0) -> tuple[bool, str]:
    """WCAG 2.2 SC 2.5.8 Target Size (Minimum), geometric part only.

    Passes when the target is at least minimum x minimum CSS px, or when the
    undersized target's 24 px diameter circle centred on its bounding box does
    not intersect another target or another target's circle (spacing exception).
    The inline/essential/user-agent exceptions need human judgment and are not
    decided here.
    Returns (passes, reason).
    """
    if target["w"] >= minimum and target["h"] >= minimum:
        return True, "size"
    cx, cy = centre(target)
    radius = minimum / 2.0
    for other in others:
        if other is target:
            continue
        ox, oy = centre(other)
        # Circle vs other target's box.
        nearest_x = max(other["x"], min(cx, other["x"] + other["w"]))
        nearest_y = max(other["y"], min(cy, other["y"] + other["h"]))
        if math.hypot(cx - nearest_x, cy - nearest_y) < radius:
            return False, "spacing_circle_hits_target"
        other_undersized = other["w"] < minimum or other["h"] < minimum
        if other_undersized and math.hypot(cx - ox, cy - oy) < 2 * radius:
            return False, "spacing_circles_overlap"
    return True, "spacing_exception"
