"""Game-play timing and photosensitivity models.

References: REF-wcag22 (2.3.1 Three Flashes or Below Threshold; general flash
definition), REF-itu-bt1702 (broadcast flash guidance), REF-xag (Xbox
Accessibility Guidelines), REF-der-deary2006 (reaction time by age).

Flash detection here is a screening heuristic on sampled frames. It is not a
certified analysis (Harding FPA is the usual broadcast one); EA IRIS is a
screening tool too, not a certification (its README says so). A pass is not a
certification, and a pass in another screening tool does not overturn a failure
here.
"""

from __future__ import annotations

import base64
import binascii
import functools
import hashlib
import math
import statistics
from typing import Any, Sequence

from .. import params


def count_general_flashes(samples: Sequence[dict], window_ms: float | None = None) -> dict:
    """Count WCAG-style general flashes in a luminance time series.

    ``samples`` are ``{"t_ms": float, "mean_luminance": 0..1, "changed_fraction": 0..1}``
    (changed_fraction = share of the viewport whose luminance changed by >10 %
    since the previous frame). A *transition* is a change in relative luminance
    of at least 10 % of the maximum where the darker state is below 0.80; a flash
    is a pair of opposing transitions. Returns the maximum number of flashes in
    any window and the maximum changed area during those transitions.
    """
    if window_ms is None:
        window_ms = params.FLASH_WINDOW_MS - params.FLASH_WINDOW_TOLERANCE_MS
    pts = sorted((float(s["t_ms"]), float(s["mean_luminance"]), float(s.get("changed_fraction", 1.0))) for s in samples)
    transitions: list[tuple[float, int, float]] = []  # (t, direction, area)
    if len(pts) < 2:
        return {"max_flashes_per_window": 0.0, "max_area_fraction": 0.0, "transitions": 0, "max_flashes_per_5s": 0.0, "extended": False}
    ref_t, ref_l, _ = pts[0]
    last_dir = 0
    for t, lum, area in pts[1:]:
        delta = lum - ref_l
        darker = min(lum, ref_l)
        if abs(delta) >= params.FLASH_DELTA and darker < params.FLASH_DARK_LIMIT:
            direction = 1 if delta > 0 else -1
            if direction != last_dir:
                transitions.append((t, direction, area))
                last_dir = direction
            ref_t, ref_l = t, lum
        elif (delta > 0 and last_dir == 1) or (delta < 0 and last_dir == -1):
            # Keep tracking the extreme of the current excursion.
            ref_t, ref_l = t, lum
    max_flashes = 0.0
    max_area = 0.0
    max_extended = 0.0
    for i, (t0, _, _) in enumerate(transitions):
        # "Any one-second period" is half-open: a 3 Hz flicker has 7 transitions
        # spanning exactly 1 s, which is 3 flashes, not 3.5.
        in_window = [tr for tr in transitions[i:] if tr[0] - t0 < window_ms]
        flashes = len(in_window) / 2.0
        if flashes > max_flashes:
            max_flashes = flashes
            max_area = max((tr[2] for tr in in_window), default=0.0)
        in_long = [tr for tr in transitions[i:] if tr[0] - t0 < params.FLASH_EXTENDED_WINDOW_MS]
        max_extended = max(max_extended, len(in_long) / 2.0)
    return {"max_flashes_per_window": max_flashes, "max_area_fraction": max_area, "transitions": len(transitions),
            "max_flashes_per_5s": max_extended,
            "extended": max_extended >= params.FLASH_EXTENDED_MIN_FLASHES}


def viewport_solid_angle_sr(display_w_mm: float, display_h_mm: float, viewing_distance_mm: float) -> float:
    """Approximate solid angle of a rectangular display centred on the line of sight."""
    a = display_w_mm / 2.0
    b = display_h_mm / 2.0
    d = viewing_distance_mm
    return 4.0 * math.asin((a * b) / math.sqrt((a * a + d * d) * (b * b + d * d)))


def flash_area_exceeds(changed_fraction: float, display_w_mm: float, display_h_mm: float, viewing_distance_mm: float) -> bool:
    """True when the flashing area exceeds WCAG's 0.006 sr combined-area threshold.

    Assumes the changed area is contiguous; the solid angle is approximated as the
    changed fraction of the display's solid angle.
    """
    return changed_fraction * viewport_solid_angle_sr(display_w_mm, display_h_mm, viewing_distance_mm) > params.FLASH_AREA_SR


# ------------------------------------------------------------------ block-grid flash screening
#
# WCAG 2.3.1 (Understanding 2.3.1, ITU-R BT.1702): a general flash is a pair of
# opposing changes in relative luminance of >= 10 % of the maximum where the
# darker state is < 0.80; a red flash is a pair of opposing transitions involving
# a saturated red. Content fails when more than three flashes of either kind
# occur in any one-second period AND the combined area of the concurrently
# flashing regions exceeds 0.006 sr within any 10 degree visual field.
#
# The web driver records, per flash sample, a block grid over the viewport
# (block_lum: mean relative luminance, block_red: share of saturated-red pixels,
# block_moved: blocks whose change is explained by content motion). Each block's
# series is reduced to transitions between adjacent peaks and valleys; a block
# flashes while it has > 6 transitions within 1 s; the concurrently flashing
# blocks are converted to steradians with the device's physical pixel size and
# the profile's viewing distance, and summed within 10 degree fields.


def _decode_bytes(value: Any, size: int) -> bytes | None:
    if not isinstance(value, str):
        return None
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        return None
    return raw if len(raw) == size else None


def has_block_grid(samples: Sequence[dict], grid: dict | None) -> bool:
    """True when the run's flash samples carry a decodable block grid."""
    if not isinstance(grid, dict) or not samples:
        return False
    cols, rows = grid.get("cols"), grid.get("rows")
    if not isinstance(cols, int) or not isinstance(rows, int) or cols < 1 or rows < 1:
        return False
    n = cols * rows
    return any(_decode_bytes(s.get("block_lum"), n) is not None for s in samples if isinstance(s, dict))


def extreme_transitions(times: Sequence[float], values: Sequence[float], moved: Sequence[bool] | None, hysteresis: float,
                        dark_limit: float | None = None) -> list[tuple[float, int, float]]:
    """Transitions between adjacent peaks and valleys of one block's series (WCAG 2.3.1 note).

    Wiggles smaller than ``hysteresis`` are ignored. A transition is reported as
    ``(t_ms, direction, magnitude)`` at the time its extreme was reached, and only
    when its darker state is below ``dark_limit`` (None: always). ``moved[i]`` marks
    that the change into sample ``i`` came from content motion (scrolling): the
    pending transition is closed and tracking restarts from the new content.
    """
    out: list[tuple[float, int, float]] = []
    if len(values) < 2:
        return out

    def close(anchor: float, cand: float, t_cand: float, direction: int) -> None:
        if abs(cand - anchor) >= hysteresis and (dark_limit is None or min(anchor, cand) < dark_limit):
            out.append((t_cand, direction, abs(cand - anchor)))

    lo = hi = values[0]
    direction = 0
    anchor = cand = t_cand = 0.0
    for i in range(1, len(values)):
        v, t = values[i], times[i]
        if moved is not None and moved[i]:
            if direction:
                close(anchor, cand, t_cand, direction)
            direction = 0
            lo = hi = v
            continue
        if direction == 0:
            lo = min(lo, v)
            hi = max(hi, v)
            if v - lo >= hysteresis:
                direction, anchor, cand, t_cand = 1, lo, v, t
            elif hi - v >= hysteresis:
                direction, anchor, cand, t_cand = -1, hi, v, t
        elif direction == 1:
            if v >= cand:
                cand, t_cand = v, t
            elif cand - v >= hysteresis:
                close(anchor, cand, t_cand, 1)
                direction, anchor, cand, t_cand = -1, cand, v, t
        else:
            if v <= cand:
                cand, t_cand = v, t
            elif v - cand >= hysteresis:
                close(anchor, cand, t_cand, -1)
                direction, anchor, cand, t_cand = 1, cand, v, t
    if direction:
        close(anchor, cand, t_cand, direction)
    return out


def _max_in_window(times: Sequence[float], window_ms: float) -> int:
    best = 0
    j = 0
    for i, t in enumerate(times):
        while t - times[j] >= window_ms:
            j += 1
        best = max(best, i - j + 1)
    return best


def _runs(times: Sequence[float], need: int, window_ms: float) -> list[tuple[float, float]]:
    """Merged intervals in which ``need`` consecutive transitions fall within less than ``window_ms``."""
    runs: list[tuple[float, float]] = []
    for i in range(len(times) - need + 1):
        t0, t1 = times[i], times[i + need - 1]
        if t1 - t0 < window_ms:
            if runs and t0 <= runs[-1][1]:
                runs[-1] = (runs[-1][0], max(runs[-1][1], t1))
            else:
                runs.append((t0, t1))
    return runs


@functools.lru_cache(maxsize=4096)
def iris_extended_runs(times: tuple[float, ...], window_ms: float | None = None, frame_ms: float | None = None) -> tuple[tuple[float, float], ...]:
    """Intervals in which EA IRIS's extended-failure rule holds for one transition train.

    A port of IRIS's TransitionTracker counters on a virtual frame clock: per frame,
    n = transitions in the last second; the frame is "in band" when
    FLASH_IRIS_MIN_TRANSITIONS <= n <= FLASH_IRIS_MAX_TRANSITIONS; a frame fails when
    it is in band and at least FLASH_IRIS_EXTENDED_SECONDS of in-band frames fall in
    the last FLASH_IRIS_EXTENDED_WINDOW_S seconds (a count above the maximum is the
    ordinary flash failure, which IRIS checks first). IRIS counts a transition only
    when 25 % of the frame changes; here the train belongs to one block and the
    caller applies the 10 degree field area instead. The window is IRIS's exact
    second: the WCAG rule's lag tolerance protects an upper bound, and here it
    would undercount the lower bound (a 2 Hz flicker would read 3 a fifth of the time).
    """
    if len(times) < params.FLASH_IRIS_MIN_TRANSITIONS:
        return ()
    window = params.FLASH_WINDOW_MS if window_ms is None else window_ms
    if _max_in_window(list(times), window) < params.FLASH_IRIS_MIN_TRANSITIONS:
        return ()
    frame = frame_ms or params.FLASH_IRIS_FRAME_MS
    one = max(1, int(round(window / frame)))
    ext_window = int(round(params.FLASH_IRIS_EXTENDED_WINDOW_S * 1000.0 / frame))
    need = int(round(params.FLASH_IRIS_EXTENDED_SECONDS * 1000.0 / frame))
    base = times[0] - frame
    per_frame: dict[int, int] = {}
    for t in times:
        f = max(1, int(math.ceil((t - base) / frame - 1e-9)))
        per_frame[f] = per_frame.get(f, 0) + 1
    last = max(per_frame) + one
    counts = [0] * (last + 1)
    band = [0] * (last + 1)
    n = in_band = 0
    runs: list[tuple[float, float]] = []
    for f in range(1, last + 1):
        n += per_frame.get(f, 0) - per_frame.get(f - one, 0)
        counts[f] = n
        band[f] = 1 if params.FLASH_IRIS_MIN_TRANSITIONS <= n <= params.FLASH_IRIS_MAX_TRANSITIONS else 0
        in_band += band[f] - (band[f - ext_window] if f - ext_window >= 1 else 0)
        if band[f] and in_band >= need:
            t = base + f * frame
            if runs and t - runs[-1][1] <= frame + 1e-9:
                runs[-1] = (runs[-1][0], t)
            else:
                runs.append((t, t))
    return tuple(runs)


_EVENT_CACHE: dict[tuple, dict] = {}


def block_flash_events(samples: Sequence[dict], cols: int, rows: int) -> dict:
    """Per-block transitions of a run's flash samples (independent of viewer geometry; cached per run).

    Returns ``{"general": {block: [(t, dir, magnitude)]}, "red": {...}, "samples": n,
    "moved_samples": k}`` with luminance and red share in 0..1 units.
    """
    n = cols * rows
    rows_data = []
    for s in samples:
        if not isinstance(s, dict) or not isinstance(s.get("t_ms"), (int, float)):
            continue
        lum = _decode_bytes(s.get("block_lum"), n)
        red = _decode_bytes(s.get("block_red"), n)
        if lum is None or red is None:
            continue
        rows_data.append((float(s["t_ms"]), lum, red, _decode_bytes(s.get("block_moved"), (n + 7) // 8)))
    rows_data.sort(key=lambda r: r[0])
    # Keyed by the full content: object ids are reused after garbage collection and
    # the first and last frames of two runs can be identical.
    digest = hashlib.sha1()
    for t, lum, red, moved in rows_data:
        digest.update(repr(t).encode())
        digest.update(lum)
        digest.update(red)
        digest.update(moved or b"-")
    key = (cols, rows, digest.hexdigest())
    if key in _EVENT_CACHE:
        return _EVENT_CACHE[key]
    times = [r[0] for r in rows_data]
    moved_rows = [r[3] for r in rows_data]
    any_moved = any(m is not None for m in moved_rows)
    general: dict[int, list[tuple[float, int, float]]] = {}
    red: dict[int, list[tuple[float, int, float]]] = {}
    h_lum = params.FLASH_DELTA * 255.0
    h_red = params.FLASH_RED_SHARE_DELTA * 255.0
    dark = params.FLASH_DARK_LIMIT * 255.0
    lum_cols = list(zip(*(r[1] for r in rows_data))) if rows_data else []
    red_cols = list(zip(*(r[2] for r in rows_data))) if rows_data else []

    def moved_flags(b: int) -> list[bool] | None:
        if not any_moved:
            return None
        byte, bit = b >> 3, 1 << (b & 7)
        return [bool(m is not None and m[byte] & bit) for m in moved_rows]

    for b in range(n if rows_data else 0):
        # A block whose value never spans the threshold cannot have a transition.
        for series, h, limit, store in ((lum_cols[b], h_lum, dark, general), (red_cols[b], h_red, None, red)):
            if max(series) - min(series) >= h:
                found = extreme_transitions(times, series, moved_flags(b), h, limit)
                if found:
                    store[b] = [(t, d, m / 255.0) for t, d, m in found]
    events = {"general": general, "red": red, "samples": len(rows_data),
              "moved_samples": sum(1 for m in moved_rows if m is not None)}
    if len(_EVENT_CACHE) > 8:
        _EVENT_CACHE.clear()
    _EVENT_CACHE[key] = events
    return events


def _field_stencil(block_mm: tuple[float, float], radius_mm: float, cols: int) -> list[tuple[int, int]]:
    """Blocks whose centres lie within ``radius_mm`` of a block centre: (row offset, half width in columns)."""
    bw, bh = block_mm
    reach_r = int(math.floor(radius_mm / bh)) if bh > 0 else 0
    stencil = []
    for dr in range(-reach_r, reach_r + 1):
        span = math.sqrt(max(0.0, radius_mm * radius_mm - (dr * bh) ** 2))
        stencil.append((dr, int(math.floor(span / bw + 1e-9)) if bw > 0 else cols))
    return stencil


def _concurrent_area(transitions: dict[int, list[tuple[float, int, float]]], need: int, window_ms: float, cols: int, rows: int,
                     block_mm: tuple[float, float], viewing_distance_mm: float, amplitude_is_coverage: bool,
                     runs_of: Any = None) -> dict:
    """Largest solid angle of concurrently flashing blocks within any 10 degree field.

    A block flashes during each interval where ``need`` of its transitions fall
    within less than ``window_ms``. Its area is weighted by the share of the
    block that flashes: for red flashes the change of the saturated-red share;
    for general flashes the block's median transition amplitude relative to the
    largest amplitude among itself and its flashing neighbours (a block half
    covered by a flashing region changes half as much as a covered one; an
    isolated block counts whole). Fields are circles of 5 degrees radius centred
    on flashing blocks; a block is inside when its centre is. ``runs_of`` replaces
    the "``need`` transitions within ``window_ms``" rule (IRIS extended failure);
    its amplitude then also uses the transitions of the second before each run.
    """
    runs: dict[int, list[tuple[float, float]]] = {}
    amplitude: dict[int, float] = {}
    rate: dict[int, float] = {}
    for b, trans in transitions.items():
        times = [t for t, _, _ in trans]
        rate[b] = _max_in_window(times, window_ms) / 2.0 * (1000.0 / max(1000.0, window_ms))  # flashes per 1 s window
        block_runs = list(runs_of(tuple(times))) if runs_of else _runs(times, need, window_ms)
        lead = window_ms if runs_of else 0.0
        if block_runs:
            runs[b] = block_runs
            amplitude[b] = statistics.median(m for t, _, m in trans if any(r0 - lead <= t <= r1 for r0, r1 in block_runs))
    result: dict[str, Any] = {"max_rate": max(rate.values(), default=0.0), "flashing_blocks": len(runs), "area_sr": 0.0,
                              "at_ms": None, "center_block": None, "field_blocks": 0, "field_rate": 0.0}
    if not runs:
        return result
    block_sr = viewport_solid_angle_sr(block_mm[0], block_mm[1], viewing_distance_mm)
    radius = viewing_distance_mm * math.tan(math.radians(params.FLASH_FIELD_DEG / 2.0))
    stencil = _field_stencil(block_mm, radius, cols)
    weight: dict[int, float] = {}
    for b, amp in amplitude.items():
        if amplitude_is_coverage:
            weight[b] = min(1.0, amp)
            continue
        r, c = divmod(b, cols)
        ref = max(amplitude.get(rr * cols + cc, 0.0)
                  for rr in range(max(0, r - 1), min(rows, r + 2)) for cc in range(max(0, c - 1), min(cols, c + 2)))
        weight[b] = min(1.0, amp / ref) if ref > 0 else 1.0

    def field(active: list[int]) -> tuple[float, int | None]:
        cell = [0.0] * (cols * rows)
        for b in active:
            cell[b] = weight[b] * block_sr
        prefix = []
        for r in range(rows):
            acc = [0.0]
            for c in range(cols):
                acc.append(acc[-1] + cell[r * cols + c])
            prefix.append(acc)
        best, where = 0.0, None
        for center in active:
            r0, c0 = divmod(center, cols)
            total = 0.0
            for dr, half in stencil:
                r = r0 + dr
                if 0 <= r < rows:
                    total += prefix[r][min(cols, c0 + half + 1)] - prefix[r][max(0, c0 - half)]
            if total > best:
                best, where = total, center
        return best, where

    evaluated: set[int] = set()
    best_active: list[int] = []
    for t in sorted({r0 for block_runs in runs.values() for r0, _ in block_runs}):
        active = [b for b, block_runs in runs.items() if any(r0 <= t <= r1 for r0, r1 in block_runs)]
        if evaluated.issuperset(active):
            continue  # a subset of an evaluated set cannot cover more (weights do not depend on time)
        evaluated = set(active)
        area, center = field(active)
        if area > result["area_sr"]:
            result.update(area_sr=area, at_ms=t, center_block=center)
            best_active = active
    if result["center_block"] is not None:
        r0, c0 = divmod(result["center_block"], cols)
        members = [b for b in best_active for r, c in [divmod(b, cols)]
                   if any(r - r0 == dr and abs(c - c0) <= half for dr, half in stencil)]
        result.update(field_blocks=len(members), field_rate=max(rate[b] for b in members))
    return result


def analyse_block_flashes(samples: Sequence[dict], grid: dict, mm_per_css_px: tuple[float, float] | None,
                          viewing_distance_mm: float) -> dict:
    """WCAG 2.3.1 general- and red-flash screening on the driver's block grid.

    ``grid`` is ``run.flash_sampling.block_grid`` (cols, rows, block_css).
    ``mm_per_css_px`` is the device's physical pixel pitch (x, y); None uses the
    WCAG proxy for an unknown screen (a 341 x 256 CSS px rectangle as the 10
    degree field at 1024 x 768). Returns per-kind results and the verdict fields
    ``failed`` (P0) and ``extended`` (P1): ``sustained_5s`` (10 or more flashes
    within 5 s) or ``iris_extended`` (EA IRIS's extended-failure rule), each over
    the same 10 degree field area. ``iris_warning`` (IRIS's 4 transitions in one
    second over that area) is a measurement only.
    """
    cols, rows = int(grid["cols"]), int(grid["rows"])
    block_css = grid.get("block_css") or [float(grid["viewport_css"][0]) / cols, float(grid["viewport_css"][1]) / rows]
    if mm_per_css_px and all(v > 0 for v in mm_per_css_px) and viewing_distance_mm > 0:
        distance = float(viewing_distance_mm)
        block_mm = (float(block_css[0]) * mm_per_css_px[0], float(block_css[1]) * mm_per_css_px[1])
        geometry = "device"
    else:
        # Unknown geometry: scale so that a 341 x 256 CSS px rectangle subtends the 10 degree field.
        distance = 1000.0
        field_mm = 2.0 * distance * math.tan(math.radians(params.FLASH_FIELD_DEG / 2.0))
        mm = field_mm / math.sqrt(341.0 * 256.0 * 4.0 / math.pi)
        block_mm = (float(block_css[0]) * mm, float(block_css[1]) * mm)
        geometry = "wcag-proxy"
    events = block_flash_events(samples, cols, rows)
    out: dict[str, Any] = {"method": "block-grid-v1", "grid": [cols, rows], "block_css": [round(float(v), 2) for v in block_css],
                           "geometry": geometry, "viewing_distance_mm": round(distance, 1), "samples": events["samples"],
                           "moved_samples": events["moved_samples"]}
    window = params.FLASH_WINDOW_MS - params.FLASH_WINDOW_TOLERANCE_MS
    for kind in ("general", "red"):
        coverage = kind == "red"
        main = _concurrent_area(events[kind], params.FLASH_FAIL_TRANSITIONS, window, cols, rows, block_mm, distance, coverage)
        ext = _concurrent_area(events[kind], int(2 * params.FLASH_EXTENDED_MIN_FLASHES), params.FLASH_EXTENDED_WINDOW_MS, cols, rows,
                               block_mm, distance, coverage)
        iris = _concurrent_area(events[kind], 0, params.FLASH_WINDOW_MS, cols, rows, block_mm, distance, coverage, runs_of=iris_extended_runs)
        warn = _concurrent_area(events[kind], params.FLASH_IRIS_MIN_TRANSITIONS, params.FLASH_WINDOW_MS, cols, rows, block_mm, distance, coverage)
        center = main["center_block"]
        out[kind] = {
            "max_flashes_per_s": round(main["max_rate"], 2),
            "flashing_blocks": main["flashing_blocks"],
            "area_sr": round(main["area_sr"], 5),
            "failed": main["area_sr"] > params.FLASH_AREA_SR,
            "at_ms": main["at_ms"],
            "field_center_css": None if center is None else [round((center % cols + 0.5) * float(block_css[0]), 1),
                                                              round((center // cols + 0.5) * float(block_css[1]), 1)],
            "field_blocks": main["field_blocks"],
            "field_flashes_per_s": round(main["field_rate"], 2),
            "sustained_5s_area_sr": round(ext["area_sr"], 5),
            "sustained_5s": ext["area_sr"] > params.FLASH_AREA_SR,
            "iris_extended_area_sr": round(iris["area_sr"], 5),
            "iris_extended": iris["area_sr"] > params.FLASH_AREA_SR,
            "iris_extended_at_ms": iris["at_ms"],
            "iris_warning": warn["area_sr"] > params.FLASH_AREA_SR,
        }
        out[kind]["extended_failed"] = out[kind]["sustained_5s"] or out[kind]["iris_extended"]
    out["failed"] = out["general"]["failed"] or out["red"]["failed"]
    out["sustained_5s"] = out["general"]["sustained_5s"] or out["red"]["sustained_5s"]
    out["iris_extended"] = out["general"]["iris_extended"] or out["red"]["iris_extended"]
    out["iris_warning"] = out["general"]["iris_warning"] or out["red"]["iris_warning"]
    out["extended"] = not out["failed"] and (out["sustained_5s"] or out["iris_extended"])
    return out


def sampling_coverage(samples: Sequence[dict], steps: Sequence[dict] = (), flash_sampling: dict | None = None) -> dict:
    """How much of the run the flash samples observed.

    Samples of one step form a burst (one sampling window). ``sampled_ms`` sums
    the burst spans, ``mean_fps`` is the capture rate inside bursts and
    ``max_gap_ms`` the longest pause inside a burst. ``unsampled_steps`` lists
    executed steps without a sample; ``unsampled_animating_steps`` the ones where
    the page was expected to move (waits, or inputs on an already-changing page).
    """
    pts = sorted((float(s["t_ms"]), s.get("step_index")) for s in samples if isinstance(s, dict) and isinstance(s.get("t_ms"), (int, float)))
    sampled = 0.0
    gaps: list[float] = []
    bursts = 0
    start = 0
    for i in range(1, len(pts) + 1):
        if i == len(pts) or pts[i][1] != pts[i - 1][1]:
            sampled += pts[i - 1][0] - pts[start][0]
            bursts += 1
            start = i
        else:
            gaps.append(pts[i][0] - pts[i - 1][0])
    times = [t for t, _ in pts]
    unsampled: list[int] = []
    animating: list[int] = []
    for step in steps:
        if not isinstance(step, dict) or step.get("result") != "ok":
            continue
        t0, t1 = step.get("t_start_ms"), step.get("t_end_ms")
        if not isinstance(t0, (int, float)) or not isinstance(t1, (int, float)):
            continue
        if any(t0 <= t <= max(t1, t0) for t in times):
            continue
        unsampled.append(step.get("step_index"))
        action = step.get("action") or {}
        if (action.get("action") == "wait" and float(action.get("ms") or 0) >= 100) or step.get("feedback_visual_ambient") is True:
            animating.append(step.get("step_index"))
    fs = flash_sampling if isinstance(flash_sampling, dict) else {}
    return {
        "samples": len(pts),
        "bursts": bursts,
        "sampled_ms": round(sampled, 1),
        "mean_fps": round(len(gaps) * 1000.0 / sampled, 1) if sampled > 0 else None,
        "max_gap_ms": round(max(gaps), 1) if gaps else None,
        "run_ms": fs.get("run_ms"),
        "jitter": bool(fs.get("jitter_ms")),
        "truncated": bool(fs.get("truncated")),
        "unsampled_steps": unsampled,
        "unsampled_animating_steps": animating,
    }


def coverage_problems(coverage: dict) -> list[str]:
    """Why a pass on these samples would be inconclusive: ``low_fps``, ``unsampled_steps``, ``truncated``."""
    problems = []
    fps = coverage.get("mean_fps")
    if fps is None or fps < params.FLASH_MIN_FPS:
        problems.append("low_fps")
    if coverage.get("unsampled_animating_steps"):
        problems.append("unsampled_steps")
    if coverage.get("truncated"):
        problems.append("truncated")
    return problems


def timing_window_margin_ms(window_ms: float, reaction_ms: float, input_latency_ms: float, motor_ms: float | None = None) -> float:
    """Remaining slack after perceiving, deciding, moving and system latency."""
    motor = params.QTE_MOTOR_MS if motor_ms is None else motor_ms
    return window_ms - (reaction_ms + motor + input_latency_ms)


def reaction_time_quantile_ms(mean_ms: float, sd_ms: float, quantile: float = 0.95) -> float:
    """Upper quantile of reaction time assuming a log-normal distribution."""
    if mean_ms <= 0 or sd_ms <= 0:
        return mean_ms
    sigma2 = math.log(1 + (sd_ms / mean_ms) ** 2)
    mu = math.log(mean_ms) - sigma2 / 2
    z = {0.5: 0.0, 0.9: 1.2816, 0.95: 1.6449, 0.99: 2.3263}.get(quantile, 1.6449)
    return math.exp(mu + z * math.sqrt(sigma2))
