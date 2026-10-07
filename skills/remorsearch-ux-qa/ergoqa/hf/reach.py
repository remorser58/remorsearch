"""Thumb reach difficulty for one-handed, two-thumb and landscape game grips.

Model ``thumb-reach-v3-uncalibrated`` (docs/human-factors/handedness-grip-reach.md
section 4): a polar model around a thumb-base pivot in a right-hand frame, with
the left hand as an exact mirror. Direction constraints come from Parhi et al.
2006 (centre best, far corner hardest), Trudeau et al. 2014 and Xiong & Muraki
2016 (grip-side bottom corner near the palm is awkward), Karlson et al. 2008 and
Trudeau et al. 2012 (flexion/extension is slower), and OS reachability features
(the top band of 6.1"+ phones is not one-hand reachable).

The numeric parameters are UNCONFIRMED heuristics: the Bergstrom-Lehtovirta &
Oulasvirta (CHI 2014) functional-area coefficients could not be retrieved. The
model reproduces 6 of 8 literature direction constraints (it fails Parhi's SW
comfort result and marks NW 'out' on Parhi's small screen for thumbs < 106 mm).
Use it for ordinal comparison and P2/P3 findings only; checks cap severities
derived from it at P2 unless trace evidence (observed mis-taps, grip-change
exits) corroborates.

Zones: natural D=0, mild 0<D<0.4, stretch 0.4<=D<1, out D=1 (needs a grip shift,
the second hand or OS reachability).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

MODEL_ID = "thumb-reach-v3-uncalibrated"
SUPPORTED_GRIPS = ("one_hand_right", "one_hand_left", "two_thumbs", "cradle_right", "cradle_left")


@dataclass(frozen=True)
class ReachParams:
    e_x: float = 3.0        # mm, pivot outside the grip-side body edge
    g_frac: float = 0.20    # pivot height above the body bottom as a fraction of body height
    g_min: float = 20.0     # mm clamp
    g_max: float = 35.0     # mm clamp
    rho_near: float = 0.30  # d/L below -> cramped (near the palm)
    rho_comf: float = 0.70  # d/L above -> stretch
    rho_max: float = 0.85   # d/L above -> out of reach
    th_comf: float = 80.0   # deg from 'up the grip edge' toward the far side/down
    th_max: float = 135.0
    tablet_g_frac: float = 0.5  # [assumption] HGR-9: tablets are held near the middle of the sides
    tablet_min_short_side_mm: float = 120.0  # body short side above this -> tablet-like (tablets, unfolded foldables)


DEFAULT = ReachParams()


@dataclass(frozen=True)
class Geometry:
    """Body and active-display geometry in mm (display offset inside the body)."""

    body_w: float
    body_h: float
    screen_x0: float
    screen_y0: float
    screen_w: float
    screen_h: float


def geometry_for_device(device) -> Geometry:
    from ..devices import display_offset_mm

    body_w, body_h = device.physical_mm
    screen_w, screen_h = device.display_mm
    ox, oy = display_offset_mm(device)
    return Geometry(body_w, body_h, ox, oy, screen_w, screen_h)


def tablet_like(geom: Geometry, p: ReachParams = DEFAULT) -> bool:
    """Handheld tablets and unfolded foldables (HGR-9): side grips, no one-hand thumb model."""
    return min(geom.body_w, geom.body_h) > p.tablet_min_short_side_mm


def _pivot(geom: Geometry, p: ReachParams) -> tuple[float, float]:
    if tablet_like(geom, p):
        g = p.tablet_g_frac * geom.body_h
    else:
        g = min(p.g_max, max(p.g_min, p.g_frac * geom.body_h))
    px_body = geom.body_w + p.e_x
    py_body = geom.body_h - g
    return px_body - geom.screen_x0, py_body - geom.screen_y0


def one_hand_score(x_mm: float, y_mm: float, geom: Geometry, thumb_length_mm: float,
                   hand: str = "R", p: ReachParams = DEFAULT) -> dict:
    """Reach difficulty for one-handed thumb use; (x, y) in display mm."""
    if thumb_length_mm <= 0:
        raise ValueError("thumb length must be positive")
    if hand == "L":
        x_mm = geom.screen_w - x_mm
    px, py = _pivot(geom, p)
    dx_across = px - x_mm
    dy_up = py - y_mm
    d = math.hypot(dx_across, dy_up)
    theta = math.degrees(math.atan2(dx_across, dy_up))
    rho = d / thumb_length_mm
    if rho > p.rho_max:
        rad = 1.0
    elif rho > p.rho_comf:
        rad = 0.4 + 0.5 * (rho - p.rho_comf) / (p.rho_max - p.rho_comf)
    elif rho < p.rho_near:
        rad = 0.2 + 0.3 * (p.rho_near - rho) / p.rho_near
    else:
        rad = 0.0
    if theta > p.th_comf and rho > 0.45:
        ang = min(0.8, 0.2 + 0.6 * (theta - p.th_comf) / (p.th_max - p.th_comf))
    else:
        ang = 0.0
    score = min(1.0, max(rad, ang) + 0.5 * min(rad, ang))
    return {"difficulty": round(score, 3), "rho": round(rho, 3), "theta_deg": round(theta, 1),
            "zone": zone(score, rho, p), "cramped": rho < p.rho_near}


def zone(score: float, rho: float | None = None, p: ReachParams = DEFAULT) -> str:
    if score >= 1.0:
        return "out"
    if score >= 0.4:
        return "stretch"
    if score > 0:
        return "mild"
    return "natural"


def reach_score(x_mm: float, y_mm: float, geom: Geometry, grip: str, thumb_length_mm: float,
                p: ReachParams = DEFAULT) -> dict:
    """Reach difficulty for a grip. Cradled grips have no reach penalty."""
    if grip == "one_hand_right":
        return one_hand_score(x_mm, y_mm, geom, thumb_length_mm, "R", p)
    if grip == "one_hand_left":
        return one_hand_score(x_mm, y_mm, geom, thumb_length_mm, "L", p)
    if grip == "two_thumbs":
        right = one_hand_score(x_mm, y_mm, geom, thumb_length_mm, "R", p)
        left = one_hand_score(x_mm, y_mm, geom, thumb_length_mm, "L", p)
        best = right if right["difficulty"] <= left["difficulty"] else left
        return {**best, "hand": "R" if best is right else "L"}
    if grip in ("cradle_right", "cradle_left"):
        return {"difficulty": 0.0, "rho": None, "theta_deg": None, "zone": "natural", "cramped": False}
    raise ValueError(f"unsupported grip {grip!r}")


def reach_difficulty(point_mm: tuple[float, float], geom: Geometry, grip: str, thumb_length_mm: float) -> float:
    return float(reach_score(point_mm[0], point_mm[1], geom, grip, thumb_length_mm)["difficulty"])


def asymmetry(x_mm: float, y_mm: float, geom: Geometry, thumb_length_mm: float) -> float:
    """D_L - D_R for one-handed grips (positive = harder for the left hand)."""
    right = one_hand_score(x_mm, y_mm, geom, thumb_length_mm, "R")["difficulty"]
    left = one_hand_score(x_mm, y_mm, geom, thumb_length_mm, "L")["difficulty"]
    return left - right


# ------------------------------------------------------------------ landscape games

def landscape_rest_points(geom: Geometry, inset_x_mm: float, inset_y_mm: float) -> tuple[tuple[float, float], tuple[float, float]]:
    """Typical thumb rest points for a two-thumb landscape grip (display mm).

    Apple HIG (game controls): movement on the left thumb, camera/actions on the
    right; frequent buttons near the thumbs, secondary controls such as menus at
    the top. The rest points are a declared assumption (inset from the lower
    side corners), not a measured anthropometric value.
    """
    left = (inset_x_mm, geom.screen_h - inset_y_mm)
    right = (geom.screen_w - inset_x_mm, geom.screen_h - inset_y_mm)
    return left, right


def landscape_control_cost(x_mm: float, y_mm: float, geom: Geometry, inset_x_mm: float, inset_y_mm: float) -> dict:
    """Travel from the nearest thumb rest point, and whether the control sits in the top band."""
    left, right = landscape_rest_points(geom, inset_x_mm, inset_y_mm)
    dl = math.hypot(x_mm - left[0], y_mm - left[1])
    dr = math.hypot(x_mm - right[0], y_mm - right[1])
    return {
        "travel_mm": round(min(dl, dr), 1),
        "thumb": "left" if dl <= dr else "right",
        "top_band": y_mm < geom.screen_h * 0.35,
    }


def occluded_by_thumb(touch_mm: tuple[float, float], target_mm: tuple[float, float], geom: Geometry,
                      grip: str, thumb_length_mm: float, wedge_deg: float = 35.0, p: ReachParams = DEFAULT) -> bool:
    """True when target lies in the hand/thumb occlusion wedge after a one-handed tap.

    HGR-8: in one-handed thumb use the thumb and hand hide content from the touch
    point toward the thumb base (down and to the grip side). The wedge (+-35 deg
    around the touch->pivot vector, up to the thumb length) is an UNCONFIRMED
    heuristic; a vision model or human should confirm.
    """
    if grip not in ("one_hand_right", "one_hand_left"):
        return False
    tx, ty = touch_mm
    x, y = target_mm
    if grip == "one_hand_left":
        tx, x = geom.screen_w - tx, geom.screen_w - x
    px, py = _pivot(geom, p)
    vx, vy = px - tx, py - ty
    wx, wy = x - tx, y - ty
    dist = math.hypot(wx, wy)
    if dist == 0:
        return True
    if dist > thumb_length_mm:
        return False
    angle = math.degrees(math.acos(max(-1.0, min(1.0, (vx * wx + vy * wy) / (math.hypot(vx, vy) * dist)))))
    return angle <= wedge_deg
