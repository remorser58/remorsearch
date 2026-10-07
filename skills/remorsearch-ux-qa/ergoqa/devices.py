"""Device catalog: physical body/display geometry and CSS viewport per device.

Every number is a published specification (body size, display diagonal and
resolution) or a published CSS viewport/DPR listing, with its URL in ``source``.
Where a spec sheet gives only the diagonal, the active display area is derived
from the diagonal and the pixel aspect ratio, assuming square pixels and a
rectangular active area (manufacturers state the diagonal of the full rectangle,
ignoring rounded corners)::

    diag_px    = hypot(px_w, px_h)
    display_w  = diagonal_in * 25.4 * px_w / diag_px      (mm)
    display_h  = diagonal_in * 25.4 * px_h / diag_px      (mm)

Marketing diagonals are rounded to 0.1 inch, so derived display sizes carry
about +-1 % error on phones. Physical pitch of one CSS px is::

    mm_per_css_px = display_mm / display_px * dpr

It depends only on the panel geometry and DPR, not on the viewport height, so a
viewport that excludes browser chrome maps with the same pitch.

Coordinate conventions
----------------------
* ``viewport_css``/``display_px``/``display_mm``/``physical_mm`` are portrait
  (width < height) for phones, foldables and tablets, and landscape for desktop,
  laptop, TV and handheld console.
* ``viewport_css`` is the full CSS screen in this catalog: browser UI (status,
  address and navigation bars) is not subtracted. ``viewport_offset_css`` is the
  viewport's top-left inside the display (default ``(0, 0)``); set it when a
  capture's viewport starts below browser chrome.
* ``display_offset_mm`` is the display's top-left inside the body, measured from
  the body's top-left. ``None`` means the display is centred horizontally with
  equal top and bottom bezels (the default; exact bezel asymmetry is rarely
  published).
* ``rotate(device)`` turns a portrait device 90 degrees counter-clockwise (Android
  ``ROTATION_90``: the top edge ends on the user's left).
* ``playwright_device`` names a Playwright 1.56.1 descriptor for user-agent and
  mobile/touch flags only. Viewport and DPR must always come from this catalog;
  several descriptors differ (noted per device).

Typical viewing distances are round planning values (phones ~30 cm, tablets
~40 cm, laptops ~50 cm, desktop monitors ~65 cm, TV "10-foot" ~2.75 m, handheld
console ~35 cm); profiles may override them per person.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, replace
from typing import Any

FORM_FACTORS = ("phone", "tablet", "foldable", "desktop", "laptop", "tv", "handheld_console")
INPUTS = ("touch", "mouse", "keyboard", "gamepad", "remote")
ORIENTATIONS = ("portrait", "landscape")
ROTATABLE = ("phone", "tablet", "foldable")
MM_PER_INCH = 25.4


@dataclass(frozen=True)
class Device:
    id: str
    label: str
    form_factor: str
    viewport_css: tuple[float, float]
    dpr: float
    physical_mm: tuple[float, float]
    display_mm: tuple[float, float]
    input: str
    viewing_distance_mm: int
    playwright_device: str | None
    source: str
    # Additive fields beyond the spec's minimum (kept stable for other modules).
    display_px: tuple[int, int] = (0, 0)
    diagonal_in: float = 0.0
    orientation: str = "portrait"
    display_offset_mm: tuple[float, float] | None = None
    viewport_offset_css: tuple[float, float] = (0.0, 0.0)
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def has_touch(self) -> bool:
        return self.input == "touch" or self.form_factor in ("phone", "tablet", "foldable", "handheld_console")

    @property
    def is_mobile(self) -> bool:
        return self.form_factor in ("phone", "tablet", "foldable")

    @property
    def screen_css(self) -> tuple[float, float]:
        """Full display size in CSS px (display_px / dpr)."""
        return (self.display_px[0] / self.dpr, self.display_px[1] / self.dpr)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for key, value in list(data.items()):
            if isinstance(value, tuple):
                data[key] = list(value)
        data["display_offset_mm"] = list(display_offset_mm(self))
        data["has_touch"] = self.has_touch
        data["is_mobile"] = self.is_mobile
        data["mm_per_css_px"] = round(mm_per_css_px(self, "x"), 5)
        return data


def display_mm_from_diagonal(diagonal_in: float, px_w: int, px_h: int) -> tuple[float, float]:
    """Active display width/height (mm) from a diagonal and pixel resolution."""
    if diagonal_in <= 0 or px_w <= 0 or px_h <= 0:
        raise ValueError("diagonal and resolution must be positive")
    diagonal_mm = diagonal_in * MM_PER_INCH
    diag_px = math.hypot(px_w, px_h)
    return (round(diagonal_mm * px_w / diag_px, 2), round(diagonal_mm * px_h / diag_px, 2))


def _device(**kw: Any) -> Device:
    if "display_mm" not in kw:
        kw["display_mm"] = display_mm_from_diagonal(kw["diagonal_in"], *kw["display_px"])
    kw["notes"] = tuple(kw.get("notes", ()))
    return Device(**kw)


_CATALOG: tuple[Device, ...] = (
    _device(
        id="galaxy-s24", label="Samsung Galaxy S24", form_factor="phone",
        viewport_css=(360, 780), dpr=3.0, physical_mm=(70.6, 147.0),
        display_px=(1080, 2340), diagonal_in=6.2, input="touch", viewing_distance_mm=300,
        playwright_device="Galaxy S24",
        source=("body/display: https://www.samsung.com/uk/smartphones/galaxy-s24/specs/ ; "
                "viewport/DPR: https://viewpo.io/tools/device-viewports/samsung-galaxy-s24/ "
                "(matches Playwright 1.56.1 'Galaxy S24' 360x780@3)"),
    ),
    _device(
        id="galaxy-s24-ultra", label="Samsung Galaxy S24 Ultra", form_factor="phone",
        viewport_css=(384, 824), dpr=3.75, physical_mm=(79.0, 162.3),
        display_px=(1440, 3120), diagonal_in=6.8, input="touch", viewing_distance_mm=300,
        playwright_device=None,
        source=("body/display: https://www.samsung.com/latin_en/smartphones/galaxy-s24-ultra/specs/ ; "
                "viewport/DPR: https://viewpo.io/tools/device-viewports/samsung-galaxy-s24-ultra/ "
                "and https://blisk.io/devices/details/galaxy-s24-ultra"),
        notes=("Published viewport height 824 < 3120/3.75 = 832; kept as published.",
               "One UI defaults to FHD+ (1080x2340, DPR 2.8125); CSS geometry and mm pitch are unchanged."),
    ),
    _device(
        id="galaxy-a55", label="Samsung Galaxy A55 5G", form_factor="phone",
        viewport_css=(412, 892), dpr=2.625, physical_mm=(77.4, 161.1),
        display_px=(1080, 2340), diagonal_in=6.6, input="touch", viewing_distance_mm=300,
        playwright_device=None,
        source=("body/display: https://www.o2.co.uk/help/phones-sims-and-devices/samsung/galaxy-a55-5g-android-14/specifications ; "
                "viewport/DPR: https://yesviz.com/devices/samsung-a55/"),
        notes=("LOW CONFIDENCE viewport: public listings disagree (412x892@2.625, 360x780@3) and the "
               "Playwright 1.56.1 'Galaxy A55' descriptor uses 480x1040@2.25. Prefer a measured "
               "'adb shell wm density' when a real device is available.",),
    ),
    _device(
        id="galaxy-z-flip6", label="Samsung Galaxy Z Flip6 (main display, unfolded)", form_factor="foldable",
        viewport_css=(412, 1006), dpr=2.625, physical_mm=(71.9, 165.1),
        display_px=(1080, 2640), diagonal_in=6.7, input="touch", viewing_distance_mm=300,
        playwright_device=None,
        source=("body/display: https://www.samsung.com/ae/support/mobile-devices/comparing-flip6-and-fold6-to-their-predecessors-display-sizes-dimensions-and-screen-quality-specifications/ "
                "and https://www.samsung.com/levant/smartphones/galaxy-z-flip6/specs/ ; "
                "DPR: Z Flip family listing https://yesviz.com/devices/samsung-z-flip/"),
        notes=("Viewport computed as ceil(1080/2.625) x ceil(2640/2.625); no Flip6-specific listing found.",
               "Horizontal hinge crosses the display at mid-height."),
    ),
    _device(
        id="galaxy-z-fold6-inner", label="Samsung Galaxy Z Fold6 (inner display, unfolded)", form_factor="foldable",
        viewport_css=(707, 823), dpr=2.625, physical_mm=(132.6, 153.5),
        display_px=(1856, 2160), diagonal_in=7.6, input="touch", viewing_distance_mm=330,
        playwright_device=None,
        source=("body/display: https://www.samsung.com/ae/support/mobile-devices/comparing-flip6-and-fold6-to-their-predecessors-display-sizes-dimensions-and-screen-quality-specifications/ ; "
                "viewport/DPR: https://1440px.com/screen-sizes/samsung-galaxy-z-fold-6/"),
        notes=("Vertical fold axis crosses the display at mid-width; typically held with two hands.",),
    ),
    _device(
        id="iphone-15", label="Apple iPhone 15", form_factor="phone",
        viewport_css=(393, 852), dpr=3.0, physical_mm=(71.6, 147.6),
        display_px=(1179, 2556), diagonal_in=6.1, input="touch", viewing_distance_mm=300,
        playwright_device="iPhone 15",
        source=("body/display: https://support.apple.com/en-us/111831 ; viewport = 1179/3 x 2556/3 "
                "(Playwright 1.56.1 'iPhone 15' screen 393x852@3)"),
        notes=("Playwright descriptor viewport 393x659 subtracts Safari UI; this catalog uses the full screen.",),
    ),
    _device(
        id="iphone-15-pro-max", label="Apple iPhone 15 Pro Max", form_factor="phone",
        viewport_css=(430, 932), dpr=3.0, physical_mm=(76.7, 159.9),
        display_px=(1290, 2796), diagonal_in=6.7, input="touch", viewing_distance_mm=300,
        playwright_device="iPhone 15 Pro Max",
        source=("body/display: https://support.apple.com/en-us/111828 ; viewport = 1290/3 x 2796/3 "
                "(Playwright 1.56.1 'iPhone 15 Pro Max' screen 430x932@3)"),
        notes=("Playwright descriptor viewport 430x739 subtracts Safari UI; this catalog uses the full screen.",),
    ),
    _device(
        id="pixel-8", label="Google Pixel 8", form_factor="phone",
        viewport_css=(412, 915), dpr=2.625, physical_mm=(70.8, 150.5),
        display_px=(1080, 2400), diagonal_in=6.2, input="touch", viewing_distance_mm=300,
        playwright_device=None,
        source=("body/display: https://store.google.com/ca/product/pixel_8_specs?hl=en-GB ; "
                "viewport/DPR: https://blisk.io/devices/details/google-pixel-8"),
        notes=("Playwright 1.56.1 has no 'Pixel 8' descriptor.",),
    ),
    _device(
        id="galaxy-tab-s9", label="Samsung Galaxy Tab S9 (11-inch)", form_factor="tablet",
        viewport_css=(800, 1280), dpr=2.0, physical_mm=(165.8, 254.3),
        display_px=(1600, 2560), diagonal_in=11.0, input="touch", viewing_distance_mm=400,
        playwright_device=None,
        source=("body/display: https://deviceguides.ee.co.uk/samsung/galaxy-tab-s9-android-13/specifications/ ; "
                "viewport/DPR: https://1440px.com/screen-sizes/samsung-galaxy-tab-s9/"),
        notes=("Playwright 1.56.1 'Galaxy Tab S9' descriptor uses 640x1024@2.5; this catalog follows the published 800x1280@2.",),
    ),
    _device(
        id="desktop-1920", label="24-inch class 1920x1080 monitor (23.8-inch viewable)", form_factor="desktop",
        viewport_css=(1920, 1080), dpr=1.0, physical_mm=(538.0, 322.0),
        display_px=(1920, 1080), diagonal_in=23.8, display_mm=(527.04, 296.46),
        input="mouse", viewing_distance_mm=650, playwright_device="Desktop Chrome", orientation="landscape",
        source=("display area (Dell P2422H 527.04 x 296.46 mm): https://www.displayspecifications.com/en/model/02fa26f2 ; "
                "https://www.dell.com/en-us/shop/dell-24-monitor-p2422h/apd/210-bbcc/monitors-monitor-accessories"),
        notes=("Body size is an estimate (display plus typical thin bezels and chin); it is not used by mouse models.",
               "Viewport is the full screen; a windowed browser loses roughly 100-130 CSS px of height to chrome/taskbar."),
    ),
    _device(
        id="laptop-1440", label="14-inch 16:10 laptop, 2880x1800 panel at 200% (1440x900 CSS)", form_factor="laptop",
        viewport_css=(1440, 900), dpr=2.0, physical_mm=(312.4, 220.1),
        display_px=(2880, 1800), diagonal_in=14.0, input="mouse", viewing_distance_mm=500,
        playwright_device=None, orientation="landscape",
        source=("reference model ASUS Zenbook 14 OLED UX3405 (14.0-inch 2880x1800, 312.4 x 220.1 x 14.9 mm): "
                "https://www.asus.com/laptops/for-home/zenbook/asus-zenbook-14-oled-ux3405/techspec/"),
        notes=("physical_mm is the base footprint (width x depth); input is a touchpad/mouse pointer.",),
    ),
    _device(
        id="tv-55-1080", label="55-inch class 1080p TV (10-foot UI)", form_factor="tv",
        viewport_css=(1920, 1080), dpr=1.0, physical_mm=(1229.4, 718.8),
        display_px=(1920, 1080), diagonal_in=54.6, input="remote", viewing_distance_mm=2750,
        playwright_device=None, orientation="landscape",
        source=("reference model Samsung UN55H6350 (54.6-inch viewable, 48.4 x 28.3 in without stand): "
                "https://www.tvsfaq.com/en/specifications/samsung-un55h6350af"),
        notes=("Viewing distance 2.75 m is the mid-point of the 2.5-3 m living-room planning range.",
               "Some TV browsers lay out at 960x540 CSS with DPR 2; this entry assumes 1920x1080@1."),
    ),
    _device(
        id="switch-handheld", label="Nintendo Switch (original, handheld mode)", form_factor="handheld_console",
        viewport_css=(1280, 720), dpr=1.0, physical_mm=(239.0, 102.0),
        display_px=(1280, 720), diagonal_in=6.2, input="gamepad", viewing_distance_mm=350,
        playwright_device=None, orientation="landscape",
        source=("https://www.nintendo.com/us/gaming-systems/switch/tech-specs/ "
                "(6.2-inch 1280x720 LCD; 102 x 239 x 13.9 mm with Joy-Con attached)"),
        notes=("Display assumed centred between the two Joy-Con.",),
    ),
)

_BY_ID: dict[str, Device] = {d.id: d for d in _CATALOG}
REQUIRED_IDS = (
    "galaxy-s24", "galaxy-s24-ultra", "galaxy-a55", "galaxy-z-flip6", "galaxy-z-fold6-inner",
    "iphone-15", "iphone-15-pro-max", "pixel-8", "galaxy-tab-s9", "desktop-1920",
    "laptop-1440", "tv-55-1080", "switch-handheld",
)


def get_device(device_id: str | Device) -> Device:
    if isinstance(device_id, Device):
        return device_id
    if not isinstance(device_id, str) or device_id not in _BY_ID:
        raise KeyError(f"unknown device id: {device_id!r}")
    return _BY_ID[device_id]


def list_devices() -> list[Device]:
    return list(_CATALOG)


def _axis(axis: str) -> int:
    if axis not in ("x", "y"):
        raise ValueError("axis must be 'x' or 'y'")
    return 0 if axis == "x" else 1


def mm_per_css_px(device: str | Device, axis: str = "x") -> float:
    d = get_device(device)
    i = _axis(axis)
    return d.display_mm[i] / d.display_px[i] * d.dpr


def css_px_to_mm(device: str | Device, px: float, axis: str = "x") -> float:
    return float(px) * mm_per_css_px(device, axis)


def mm_to_css_px(device: str | Device, mm: float, axis: str = "x") -> float:
    return float(mm) / mm_per_css_px(device, axis)


def display_offset_mm(device: str | Device) -> tuple[float, float]:
    """Display top-left inside the body (mm from body top-left)."""
    d = get_device(device)
    if d.display_offset_mm is not None:
        return d.display_offset_mm
    return ((d.physical_mm[0] - d.display_mm[0]) / 2, (d.physical_mm[1] - d.display_mm[1]) / 2)


def css_to_display_mm_point(device: str | Device, x: float, y: float) -> tuple[float, float]:
    """Viewport CSS point -> mm from the display's top-left."""
    d = get_device(device)
    ox, oy = d.viewport_offset_css
    return (css_px_to_mm(d, x + ox, "x"), css_px_to_mm(d, y + oy, "y"))


def css_to_body_mm_point(device: str | Device, x: float, y: float) -> tuple[float, float]:
    """Viewport CSS point -> mm from the body's top-left (for grip/reach models)."""
    d = get_device(device)
    dx, dy = css_to_display_mm_point(d, x, y)
    ox, oy = display_offset_mm(d)
    return (dx + ox, dy + oy)


def body_mm_to_css_point(device: str | Device, x_mm: float, y_mm: float) -> tuple[float, float]:
    """Inverse of css_to_body_mm_point."""
    d = get_device(device)
    ox, oy = display_offset_mm(d)
    vx, vy = d.viewport_offset_css
    return (mm_to_css_px(d, x_mm - ox, "x") - vx, mm_to_css_px(d, y_mm - oy, "y") - vy)


def _swap(pair: tuple[Any, Any]) -> tuple[Any, Any]:
    return (pair[1], pair[0])


def rotate(device: str | Device, orientation: str = "landscape") -> Device:
    """Return the device in ``orientation`` (90 degrees counter-clockwise from portrait).

    Already-matching devices are returned unchanged. Fixed-orientation devices
    (desktop, laptop, TV, handheld console) cannot be turned to portrait.
    """
    d = get_device(device)
    if orientation not in ORIENTATIONS:
        raise ValueError(f"orientation must be one of {ORIENTATIONS}")
    if d.orientation == orientation:
        return d
    if d.form_factor not in ROTATABLE:
        raise ValueError(f"{d.id} ({d.form_factor}) has a fixed {d.orientation} orientation")
    body_w = d.physical_mm[0]
    ox, oy = display_offset_mm(d)
    screen_w_css = d.screen_css[0]
    vx, vy = d.viewport_offset_css
    if orientation == "landscape":
        # CCW turn: portrait point (x, y) -> landscape (y, W - x); the display's
        # portrait top-right corner becomes its landscape top-left.
        new_offset = (oy, body_w - ox - d.display_mm[0])
        new_voffset = (vy, screen_w_css - vx - d.viewport_css[0])
    else:
        body_h = d.physical_mm[1]
        new_offset = (body_h - oy - d.display_mm[1], ox)
        new_voffset = (d.screen_css[1] - vy - d.viewport_css[1], vx)
    return replace(
        d,
        viewport_css=_swap(d.viewport_css), physical_mm=_swap(d.physical_mm),
        display_mm=_swap(d.display_mm), display_px=_swap(d.display_px),
        display_offset_mm=(round(new_offset[0], 4), round(new_offset[1], 4)) if d.display_offset_mm is not None else None,
        viewport_offset_css=(round(max(0.0, new_voffset[0]), 4), round(max(0.0, new_voffset[1]), 4)),
        orientation=orientation,
    )


def device_for_snapshot(snapshot_device: dict[str, Any]) -> Device:
    """Catalog device matching a snapshot's ``device`` block (id + orientation)."""
    d = get_device(snapshot_device.get("id"))
    orientation = snapshot_device.get("orientation") or d.orientation
    return rotate(d, orientation) if orientation != d.orientation else d
