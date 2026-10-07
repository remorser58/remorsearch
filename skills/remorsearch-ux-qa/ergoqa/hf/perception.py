"""Colour, contrast, colour-vision-deficiency and text-size models.

References (see ergoqa/refs.py): REF-wcag22 (relative luminance, contrast ratio,
1.4.3/1.4.6/1.4.11), REF-machado2009 (CVD simulation matrices), REF-ciede2000
(Sharma, Wu & Dalal 2005 implementation notes for CIEDE2000).
"""

from __future__ import annotations

import math
import re
from typing import Iterable

RGB = tuple[float, float, float]

_HEX = re.compile(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
_RGB_FN = re.compile(r"^rgba?\(\s*([^)]*)\)$")


def parse_color(value: str | Iterable[float] | None) -> RGB | None:
    """Parse '#rgb', '#rrggbb', '#rrggbbaa', 'rgb(...)' or an (r, g, b) tuple (0-255).

    Returns None for missing/transparent/unparseable colours so callers can mark
    the measurement unknown instead of guessing a background.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        parts = list(value)
        if len(parts) < 3:
            return None
        return (float(parts[0]), float(parts[1]), float(parts[2]))
    text = value.strip()
    match = _HEX.match(text)
    if match:
        digits = match.group(1)
        if len(digits) == 3:
            digits = "".join(ch * 2 for ch in digits)
        if len(digits) == 8 and int(digits[6:8], 16) == 0:
            return None
        return (float(int(digits[0:2], 16)), float(int(digits[2:4], 16)), float(int(digits[4:6], 16)))
    match = _RGB_FN.match(text)
    if match:
        raw = [p.strip() for p in re.split(r"[,\s/]+", match.group(1)) if p.strip()]
        if len(raw) < 3:
            return None
        try:
            channels = [float(p[:-1]) * 2.55 if p.endswith("%") else float(p) for p in raw[:3]]
            if len(raw) >= 4:
                alpha = float(raw[3][:-1]) / 100 if raw[3].endswith("%") else float(raw[3])
                if alpha == 0:
                    return None
        except ValueError:
            return None
        return (channels[0], channels[1], channels[2])
    return None


def to_hex(rgb: RGB) -> str:
    return "#" + "".join(f"{max(0, min(255, round(c))):02x}" for c in rgb)


def srgb_to_linear(channel_0_255: float) -> float:
    c = max(0.0, min(255.0, channel_0_255)) / 255.0
    # WCAG 2.2 notes the sRGB threshold as 0.04045 (older text used 0.03928; the
    # difference cannot change an 8-bit result).
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def linear_to_srgb(linear: float) -> float:
    v = max(0.0, min(1.0, linear))
    s = v * 12.92 if v <= 0.0031308 else 1.055 * (v ** (1 / 2.4)) - 0.055
    return s * 255.0


def relative_luminance(rgb: RGB) -> float:
    r, g, b = (srgb_to_linear(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(fg: RGB, bg: RGB) -> float:
    """WCAG 2.x contrast ratio (1.0 - 21.0)."""
    l1, l2 = relative_luminance(fg), relative_luminance(bg)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def is_large_text(font_size_css_px: float | None, font_weight: float | None) -> bool:
    """WCAG 'large scale' text: >= 18pt (24 CSS px) or >= 14pt (18.66 CSS px) bold."""
    if font_size_css_px is None:
        return False
    weight = font_weight or 400
    return font_size_css_px >= 24.0 or (font_size_css_px >= 18.66 and weight >= 700)


def required_text_contrast(font_size_css_px: float | None, font_weight: float | None, level: str = "AA") -> float:
    large = is_large_text(font_size_css_px, font_weight)
    if level == "AAA":
        return 4.5 if large else 7.0
    return 3.0 if large else 4.5


from .machado_data import MACHADO_MATRICES  # noqa: E402

CVD_KINDS = tuple(MACHADO_MATRICES)


def _matrix_for(kind: str, severity: float) -> tuple[tuple[float, float, float], ...]:
    """Tabulated Machado matrix, linearly interpolated between adjacent 0.1 steps."""
    table = MACHADO_MATRICES[kind]
    s = max(0.0, min(1.0, float(severity)))
    lo = round(int(s * 10 + 1e-9) / 10.0, 1)
    hi = min(1.0, round(lo + 0.1, 1))
    if hi == lo or abs(s - lo) < 1e-9:
        return table[lo]
    t = (s - lo) / (hi - lo)
    a, b = table[lo], table[hi]
    return tuple(tuple((1 - t) * a[r][c] + t * b[r][c] for c in range(3)) for r in range(3))  # type: ignore[return-value]


def simulate_cvd(rgb: RGB, kind: str, severity: float = 1.0) -> RGB:
    """Simulate how an sRGB colour appears with protan/deutan/tritan deficiency.

    Uses the Machado (2009/2010) per-severity matrices on linear RGB.
    """
    if kind in (None, "", "none"):
        return rgb
    if kind not in MACHADO_MATRICES:
        raise ValueError(f"unknown CVD kind {kind!r}")
    matrix = _matrix_for(kind, severity)
    lin = [srgb_to_linear(c) for c in rgb]
    out = [sum(row[i] * lin[i] for i in range(3)) for row in matrix]
    return tuple(linear_to_srgb(v) for v in out)  # type: ignore[return-value]


def rgb_to_lab(rgb: RGB) -> tuple[float, float, float]:
    """sRGB (D65) -> CIE L*a*b*."""
    r, g, b = (srgb_to_linear(c) for c in rgb)
    x = (0.4124564 * r + 0.3575761 * g + 0.1804375 * b) / 0.95047
    y = (0.2126729 * r + 0.7151522 * g + 0.0721750 * b) / 1.00000
    z = (0.0193339 * r + 0.1191920 * g + 0.9503041 * b) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > (6 / 29) ** 3 else t / (3 * (6 / 29) ** 2) + 4 / 29

    fx, fy, fz = f(x), f(y), f(z)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def delta_e_2000(lab1: tuple[float, float, float], lab2: tuple[float, float, float]) -> float:
    """CIEDE2000 colour difference (kL = kC = kH = 1)."""
    l1, a1, b1 = lab1
    l2, a2, b2 = lab2
    c1 = math.hypot(a1, b1)
    c2 = math.hypot(a2, b2)
    c_bar = (c1 + c2) / 2
    g = 0.5 * (1 - math.sqrt(c_bar ** 7 / (c_bar ** 7 + 25 ** 7))) if c_bar > 0 else 0.0
    a1p, a2p = (1 + g) * a1, (1 + g) * a2
    c1p, c2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1p = math.degrees(math.atan2(b1, a1p)) % 360 if c1p else 0.0
    h2p = math.degrees(math.atan2(b2, a2p)) % 360 if c2p else 0.0
    dlp = l2 - l1
    dcp = c2p - c1p
    if c1p * c2p == 0:
        dhp = 0.0
    else:
        dh = h2p - h1p
        if dh > 180:
            dh -= 360
        elif dh < -180:
            dh += 360
        dhp = dh
    dHp = 2 * math.sqrt(c1p * c2p) * math.sin(math.radians(dhp / 2))
    l_bar = (l1 + l2) / 2
    cp_bar = (c1p + c2p) / 2
    if c1p * c2p == 0:
        hp_bar = h1p + h2p
    else:
        hsum = h1p + h2p
        if abs(h1p - h2p) <= 180:
            hp_bar = hsum / 2
        elif hsum < 360:
            hp_bar = (hsum + 360) / 2
        else:
            hp_bar = (hsum - 360) / 2
    t = (
        1
        - 0.17 * math.cos(math.radians(hp_bar - 30))
        + 0.24 * math.cos(math.radians(2 * hp_bar))
        + 0.32 * math.cos(math.radians(3 * hp_bar + 6))
        - 0.20 * math.cos(math.radians(4 * hp_bar - 63))
    )
    d_theta = 30 * math.exp(-(((hp_bar - 275) / 25) ** 2))
    rc = 2 * math.sqrt(cp_bar ** 7 / (cp_bar ** 7 + 25 ** 7)) if cp_bar > 0 else 0.0
    sl = 1 + (0.015 * (l_bar - 50) ** 2) / math.sqrt(20 + (l_bar - 50) ** 2)
    sc = 1 + 0.045 * cp_bar
    sh = 1 + 0.015 * cp_bar * t
    rt = -math.sin(math.radians(2 * d_theta)) * rc
    return math.sqrt(
        (dlp / sl) ** 2 + (dcp / sc) ** 2 + (dHp / sh) ** 2 + rt * (dcp / sc) * (dHp / sh)
    )


def color_difference(c1: RGB, c2: RGB) -> float:
    return delta_e_2000(rgb_to_lab(c1), rgb_to_lab(c2))


def cvd_difference(c1: RGB, c2: RGB, kind: str, severity: float = 1.0) -> float:
    """CIEDE2000 difference between two colours as seen with the given CVD."""
    return color_difference(simulate_cvd(c1, kind, severity), simulate_cvd(c2, kind, severity))


def visual_angle_arcmin(size_mm: float, viewing_distance_mm: float) -> float:
    """Visual angle subtended by an object of size_mm at viewing_distance_mm."""
    if viewing_distance_mm <= 0:
        raise ValueError("viewing distance must be positive")
    return math.degrees(2 * math.atan(size_mm / (2 * viewing_distance_mm))) * 60
