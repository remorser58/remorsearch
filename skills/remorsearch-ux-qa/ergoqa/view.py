"""Profile view: an approximation of what a profile sees, for persona agents.

This is ILLUSTRATIVE, not a validated visual simulation. It lets an LLM persona
agent look at a screenshot degraded like the profile's vision instead of a
perfect one:

- colour-vision deficiency: Machado et al. per-severity matrices on linear RGB;
- reduced acuity / presbyopia without correction: box blur scaled by assumed
  optical blur (declared assumption);
- bright ambient light: veiling reflection added in linear light (reflectance
  rho=0.02 of the ambient illuminance over a display peak; see
  docs/human-factors/perception-cognition.md) which lowers contrast.

Measurements never use this view; checks read the original geometry and colours.
"""

from __future__ import annotations

from typing import Any

from . import png
from .hf.perception import MACHADO_MATRICES, _matrix_for

_LIN = [((v / 255.0) / 12.92) if v / 255.0 <= 0.04045 else (((v / 255.0) + 0.055) / 1.055) ** 2.4 for v in range(256)]


def _to_srgb8(value: float) -> int:
    v = max(0.0, min(1.0, value))
    s = v * 12.92 if v <= 0.0031308 else 1.055 * (v ** (1 / 2.4)) - 0.055
    return int(round(s * 255))


def _encode_table() -> list[int]:
    # 4096-step lookup from linear [0, 1] to sRGB 8-bit.
    return [_to_srgb8(i / 4095.0) for i in range(4096)]


_ENC = _encode_table()


def _enc(value: float) -> int:
    if value <= 0:
        return 0
    if value >= 1:
        return 255
    return _ENC[int(value * 4095 + 0.5)]


def _box_blur_rgb(image: png.Image, radius: int) -> png.Image:
    if radius <= 0:
        return image
    w, h = image.width, image.height
    src = image.data
    tmp = bytearray(len(src))
    for y in range(h):
        row = y * w * 3
        for c in range(3):
            values = [src[row + x * 3 + c] for x in range(w)]
            prefix = [0]
            for v in values:
                prefix.append(prefix[-1] + v)
            for x in range(w):
                x0, x1 = max(0, x - radius), min(w, x + radius + 1)
                tmp[row + x * 3 + c] = (prefix[x1] - prefix[x0]) // (x1 - x0)
    out = bytearray(len(src))
    for x in range(w):
        for c in range(3):
            values = [tmp[(y * w + x) * 3 + c] for y in range(h)]
            prefix = [0]
            for v in values:
                prefix.append(prefix[-1] + v)
            for y in range(h):
                y0, y1 = max(0, y - radius), min(h, y + radius + 1)
                out[(y * w + x) * 3 + c] = (prefix[y1] - prefix[y0]) // (y1 - y0)
    return png.Image(w, h, 3, bytes(out))


def profile_view(image: png.Image, profile: dict[str, Any], dpr: float = 1.0) -> tuple[png.Image, list[str]]:
    """Return (degraded RGB image at CSS-pixel scale, list of applied transforms)."""
    applied: list[str] = []
    rgb = png.to_rgb(image)
    factor = max(1, int(round(dpr)))
    if factor > 1:
        rgb = png.downsample(rgb, factor)
        applied.append(f"downsample x{factor} to CSS px")
    attrs = profile.get("attributes", {})
    vision = attrs.get("vision", {})
    kind = vision.get("cvd", "none")
    lighting = attrs.get("context", {}).get("lighting", "indoor")
    matrix = _matrix_for(kind, float(vision.get("cvd_severity") or 1.0)) if kind in MACHADO_MATRICES else None
    veil = 0.0
    if lighting == "bright_sun":
        # rho * E / pi over peak luminance: 0.02 * 50,000 lux / pi / 1000 nits ~ 0.32 [assumption]
        veil = 0.32
        applied.append("bright-sun veiling reflection (0.32 of peak, assumption)")
    if matrix is not None:
        applied.append(f"Machado CVD {kind} severity {vision.get('cvd_severity', 1.0)}")
    if matrix is not None or veil:
        data = rgb.data
        out = bytearray(len(data))
        for i in range(0, len(data), 3):
            r, g, b = _LIN[data[i]], _LIN[data[i + 1]], _LIN[data[i + 2]]
            if matrix is not None:
                r, g, b = (
                    matrix[0][0] * r + matrix[0][1] * g + matrix[0][2] * b,
                    matrix[1][0] * r + matrix[1][1] * g + matrix[1][2] * b,
                    matrix[2][0] * r + matrix[2][1] * g + matrix[2][2] * b,
                )
            if veil:
                r, g, b = (r + veil) / (1 + veil), (g + veil) / (1 + veil), (b + veil) / (1 + veil)
            out[i], out[i + 1], out[i + 2] = _enc(r), _enc(g), _enc(b)
        rgb = png.Image(rgb.width, rgb.height, 3, bytes(out))
    radius = 0
    if vision.get("acuity") == "low":
        radius = 2
    elif vision.get("acuity") == "reduced" or (vision.get("presbyopia") and vision.get("uncorrected")):
        radius = 1
    if radius:
        rgb = _box_blur_rgb(rgb, radius)
        applied.append(f"box blur r={radius} (acuity assumption)")
    return rgb, applied
