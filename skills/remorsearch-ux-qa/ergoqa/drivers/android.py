"""Android driver: ``uiautomator dump`` XML -> ergo-snapshot.v1, plus adb argv builders.

Geometry: uiautomator ``bounds="[x1,y1][x2,y2]"`` are device pixels in screen
coordinates (status bar included). They are converted to dp with
``dp = px / (density_dpi / 160)`` and dp is treated as the CSS-equivalent px of
the snapshot contract, so the snapshot viewport is the whole screen in dp.
uiautomator exposes no font size or colours; those stay ``null`` and colour
checks must sample the screenshot instead.

Roles: the ARIA-like ``role`` comes from the widget class (e.g. ``Button`` ->
button). Ergonomic ``roles`` (primary, destructive, ...) are assigned only from a
scenario's ``targets`` via :func:`assign_roles`; nothing is guessed.

adb: every command is an argv list for ``subprocess`` without a host shell.
``adb shell`` still joins its arguments into one device-side command line, so
all arguments after ``shell`` are validated to shell-inert characters (digits,
``KEYCODE_*`` names, fixed remote paths, and a conservative ``input text``
alphabet with spaces escaped as ``%s``).

Live device execution (``run_adb`` and a real device/emulator) is NOT exercised
by this repository's tests; they cover XML parsing and argv construction only.
"""
from __future__ import annotations

import re
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence
from xml.etree import ElementTree

from ..devices import get_device
from ..snapshot import SnapshotError, safe_relative_path, sha256_file, validate_snapshot

BOUNDS_RE = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")
MAX_XML_BYTES = 16 * 1024 * 1024
ADB = "adb"

# Widget class (last dotted segment) -> ARIA-like role.
ROLE_BY_CLASS: dict[str, str] = {
    "Button": "button", "AppCompatButton": "button", "MaterialButton": "button",
    "ImageButton": "button", "AppCompatImageButton": "button",
    "FloatingActionButton": "button", "ExtendedFloatingActionButton": "button", "Chip": "button",
    "EditText": "textbox", "AppCompatEditText": "textbox", "TextInputEditText": "textbox",
    "MultiAutoCompleteTextView": "textbox", "AutoCompleteTextView": "combobox",
    "AppCompatAutoCompleteTextView": "combobox", "MaterialAutoCompleteTextView": "combobox",
    "SearchView": "searchbox", "SearchAutoComplete": "searchbox",
    "CheckBox": "checkbox", "AppCompatCheckBox": "checkbox", "MaterialCheckBox": "checkbox",
    "CheckedTextView": "checkbox",
    "RadioButton": "radio", "AppCompatRadioButton": "radio", "MaterialRadioButton": "radio",
    "Switch": "switch", "SwitchCompat": "switch", "SwitchMaterial": "switch", "MaterialSwitch": "switch",
    "ToggleButton": "switch",
    "SeekBar": "slider", "AppCompatSeekBar": "slider", "Slider": "slider", "RangeSlider": "slider",
    "RatingBar": "slider", "AppCompatRatingBar": "slider",
    "ProgressBar": "progressbar",
    "Spinner": "combobox", "AppCompatSpinner": "combobox",
    "NumberPicker": "spinbutton",
    "TextView": "text", "AppCompatTextView": "text", "MaterialTextView": "text",
    "ImageView": "img", "AppCompatImageView": "img", "ShapeableImageView": "img",
    "WebView": "document",
    "TabWidget": "tablist", "TabLayout": "tablist", "TabView": "tab",
    "RecyclerView": "list", "ListView": "list", "GridView": "grid",
    "ScrollView": "scrollview", "HorizontalScrollView": "scrollview", "NestedScrollView": "scrollview",
    "Toolbar": "toolbar", "ActionBar": "toolbar",
    "BottomNavigationView": "navigation", "NavigationBarView": "navigation",
}
INPUT_ROLES = ("textbox", "combobox", "searchbox", "slider", "switch", "checkbox", "radio", "spinbutton")


class AdbArgError(ValueError):
    """An adb argument that could be interpreted by the device shell or is out of range."""


# --------------------------------------------------------------------------- XML parsing

def parse_bounds(value: str) -> tuple[int, int, int, int]:
    match = BOUNDS_RE.fullmatch(value.strip()) if isinstance(value, str) else None
    if not match:
        raise SnapshotError(f"malformed uiautomator bounds: {value!r}")
    x1, y1, x2, y2 = (int(v) for v in match.groups())
    if x2 < x1 or y2 < y1:
        raise SnapshotError(f"inverted uiautomator bounds: {value!r}")
    return x1, y1, x2, y2


def density_scale(density_dpi: float) -> float:
    """dp scale factor (px per dp) = density_dpi / 160."""
    if isinstance(density_dpi, bool) or not isinstance(density_dpi, (int, float)) or not 60 <= density_dpi <= 1200:
        raise SnapshotError(f"density_dpi must be a number in 60..1200 (got {density_dpi!r})")
    return float(density_dpi) / 160.0


def px_to_dp(px: float, density_dpi: float) -> float:
    return px / density_scale(density_dpi)


def role_for_class(class_name: str | None, clickable: bool = False) -> tuple[str, str]:
    """Return (role, basis). basis is 'class' or 'clickable_fallback' or 'container'."""
    short = (class_name or "").split(".")[-1].split("$")[-1]
    if short in ROLE_BY_CLASS:
        return ROLE_BY_CLASS[short], "class"
    if clickable:
        return "button", "clickable_fallback"
    return "group", "container"


def _parse_xml(xml_text: str | bytes) -> ElementTree.Element:
    raw = xml_text.encode("utf-8") if isinstance(xml_text, str) else bytes(xml_text)
    if len(raw) > MAX_XML_BYTES:
        raise SnapshotError("uiautomator XML exceeds 16 MiB")
    head = raw[:4096].upper()
    if b"<!DOCTYPE" in head or b"<!ENTITY" in raw.upper():
        raise SnapshotError("uiautomator XML must not contain DTD/entity declarations")
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError as exc:
        raise SnapshotError(f"invalid uiautomator XML: {exc}") from exc
    if root.tag != "hierarchy":
        raise SnapshotError(f"expected <hierarchy> root, got <{root.tag}>")
    return root


def _flag(node: ElementTree.Element, name: str) -> bool:
    return node.get(name, "false").strip().lower() == "true"


def _selector(rid: str, desc: str, text: str, cls: str, path: str) -> str:
    if rid:
        return f"resource-id={rid}"
    if desc:
        return f"content-desc={desc}"
    if text:
        return f"text={text}"
    return f"class={cls}@{path}"


def _walk(root: ElementTree.Element) -> Iterable[tuple[ElementTree.Element, str]]:
    stack = [(child, str(i)) for i, child in reversed(list(enumerate(root.findall("node"))))]
    while stack:
        node, path = stack.pop()
        yield node, path
        children = list(enumerate(node.findall("node")))
        for i, child in reversed(children):
            stack.append((child, f"{path}/{i}"))


def screen_px_from_xml(xml_text: str | bytes) -> tuple[int, int]:
    """Largest right/bottom edge among top-level window nodes (a fallback screen size)."""
    return _screen_from_root(_parse_xml(xml_text))


def _screen_from_root(root: ElementTree.Element) -> tuple[int, int]:
    tops = root.findall("node")
    if not tops:
        raise SnapshotError("uiautomator XML has no nodes")
    edges = [parse_bounds(n.get("bounds", "")) for n in tops]
    return max(e[2] for e in edges), max(e[3] for e in edges)


def parse_uiautomator_xml(xml_text: str | bytes, density_dpi: float, *,
                          screen_px: tuple[int, int] | None = None,
                          include_containers: bool = False) -> list[dict[str, Any]]:
    """Convert a uiautomator dump into spec elements (boxes in dp).

    Kept nodes: interactive (clickable, long-clickable or checkable), input
    widgets, and nodes with text or content-desc. Zero-area nodes are dropped.
    ``include_containers`` keeps every positive-area node.
    Password fields never expose their text.
    """
    return _elements_from_root(_parse_xml(xml_text), density_scale(density_dpi), screen_px, include_containers)


def _elements_from_root(root: ElementTree.Element, scale: float, screen_px: tuple[int, int] | None,
                        include_containers: bool) -> list[dict[str, Any]]:
    sw, sh = screen_px if screen_px is not None else _screen_from_root(root)
    elements: list[dict[str, Any]] = []
    for node, path in _walk(root):
        x1, y1, x2, y2 = parse_bounds(node.get("bounds", ""))
        if x2 - x1 <= 0 or y2 - y1 <= 0:
            continue
        cls = node.get("class", "")
        text = node.get("text", "") or ""
        desc = node.get("content-desc", "") or ""
        rid = node.get("resource-id", "") or ""
        clickable = _flag(node, "clickable")
        long_clickable = _flag(node, "long-clickable")
        checkable = _flag(node, "checkable")
        password = _flag(node, "password")
        role, basis = role_for_class(cls, clickable or long_clickable)
        interactive = clickable or long_clickable or checkable
        if password:
            text = ""
        if not (include_containers or interactive or role in INPUT_ROLES or text.strip() or desc.strip()):
            continue
        visible_attr = node.get("visible-to-user")
        visible = visible_attr.strip().lower() == "true" if visible_attr is not None else True
        in_viewport = x2 > 0 and y2 > 0 and x1 < sw and y1 < sh
        elements.append({
            "id": f"el-{len(elements) + 1}",
            "role": role,
            "name": desc or text or "",
            "text": text or None,
            "tag": cls or None,
            "selector": _selector(rid, desc, text, cls, path),
            "box": {"x": round(x1 / scale, 3), "y": round(y1 / scale, 3),
                    "w": round((x2 - x1) / scale, 3), "h": round((y2 - y1) / scale, 3)},
            "interactive": interactive,
            "visible": visible,
            "enabled": _flag(node, "enabled") if node.get("enabled") is not None else True,
            "in_viewport": in_viewport,
            "font_size_px": None,
            "font_weight": None,
            "color_fg": None,
            "color_bg": None,
            "border_color": None,
            "roles": [],
            "source": "uiautomator",
            "native": {
                "class": cls, "resource_id": rid or None, "content_desc": desc or None,
                "package": node.get("package") or None,
                "bounds_px": [x1, y1, x2, y2], "index_path": path, "role_basis": basis,
                "checkable": checkable, "checked": _flag(node, "checked"),
                "focusable": _flag(node, "focusable"), "scrollable": _flag(node, "scrollable"),
                "long_clickable": long_clickable, "selected": _flag(node, "selected"),
                "password": password,
            },
        })
    return elements


def match_selector(element: dict[str, Any], selector: str) -> bool:
    """Android target selectors: ``resource-id=``, ``content-desc=``, ``text=``,
    ``class=`` (exact), or ``#name`` matching a resource-id ``...:id/name``."""
    native = element.get("native") or {}
    rid = native.get("resource_id") or ""
    if selector.startswith("#"):
        name = selector[1:]
        return bool(name) and (rid == name or rid.endswith(f":id/{name}"))
    key, sep, value = selector.partition("=")
    if not sep:
        return False
    if key == "resource-id":
        return rid == value
    if key == "content-desc":
        return (native.get("content_desc") or "") == value and bool(value)
    if key == "text":
        return (element.get("text") or "") == value and bool(value)
    if key == "class":
        return native.get("class") == value or element.get("tag") == value
    return False


def assign_roles(elements: list[dict[str, Any]], targets: dict[str, Sequence[str]] | None) -> list[str]:
    """Add ergo roles from scenario ``targets``; returns selectors that matched nothing."""
    unmatched: list[str] = []
    for role, selectors in (targets or {}).items():
        for selector in selectors:
            if selector.startswith("hotspot:"):
                continue
            hits = [el for el in elements if match_selector(el, selector)]
            if not hits:
                unmatched.append(f"{role}:{selector}")
            for el in hits:
                if role not in el["roles"]:
                    el["roles"].append(role)
    return unmatched


def build_snapshot(xml_text: str | bytes, *, screenshot_path: str | Path, device_id: str,
                   density_dpi: float | None = None, run_id: str = "R-android-adhoc",
                   snapshot_id: str | None = None, step_index: int = 0, captured_at: str | None = None,
                   screenshot_ref: str | None = None, targets: dict[str, Sequence[str]] | None = None,
                   focus_point: dict[str, float] | None = None) -> dict[str, Any]:
    """Build an ergo-snapshot.v1 from a dump and its screenshot PNG.

    ``screenshot_ref`` is the relative path stored in the snapshot (default: the
    screenshot's file name, i.e. the PNG sits next to the snapshot JSON). The PNG
    must exist; its SHA-256 and dimensions are recorded. When ``density_dpi`` is
    omitted the catalog DPR x 160 is used and a note says it was not measured.
    """
    from ..png import read_header

    device = get_device(device_id)
    notes = [
        "geometry: uiautomator bounds (device px) / (density_dpi/160) -> dp, used as CSS-equivalent px",
        "font size and colours are not exposed by uiautomator; colour checks must sample the screenshot",
    ]
    if density_dpi is None:
        density_dpi = device.dpr * 160
        notes.append(f"density_dpi={density_dpi:g} taken from the device catalog, not measured (wm density)")
    else:
        notes.append(f"density_dpi={density_dpi:g} supplied by caller")
    scale = density_scale(density_dpi)
    png_path = Path(screenshot_path)
    if not png_path.is_file():
        raise SnapshotError(f"screenshot not found: {png_path}")
    header = read_header(png_path)
    ref = screenshot_ref if screenshot_ref is not None else png_path.name
    if not safe_relative_path(ref):
        raise SnapshotError(f"unsafe screenshot reference: {ref!r}")
    root = _parse_xml(xml_text)
    rotation = root.get("rotation")
    elements = _elements_from_root(root, scale, (header.width, header.height), False)
    unmatched = assign_roles(elements, targets)
    for item in unmatched:
        notes.append(f"target selector matched no element: {item}")
    packages = Counter(el["native"]["package"] for el in elements
                       if el["native"]["package"] and el["native"]["package"] != "com.android.systemui")
    if rotation in ("1", "3"):
        orientation = "landscape"
    elif rotation in ("0", "2"):
        orientation = "portrait"
    else:
        orientation = "landscape" if header.width > header.height else "portrait"
    snapshot = {
        "schema_version": "ergo-snapshot.v1",
        "snapshot_id": snapshot_id or f"S-{run_id}-{step_index:03d}",
        "run_id": run_id,
        "step_index": step_index,
        "captured_at": captured_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "surface": {"kind": "android", "url": None, "title": None,
                    "app_id": packages.most_common(1)[0][0] if packages else None},
        "device": {"id": device.id,
                   "viewport_css": [round(header.width / scale, 3), round(header.height / scale, 3)],
                   "dpr": scale, "orientation": orientation},
        "screenshot": {"path": ref, "sha256": sha256_file(png_path),
                       "width_px": header.width, "height_px": header.height},
        "elements": elements,
        "focus_point": focus_point,
        "console_errors": [],
        "notes": notes,
    }
    problems = validate_snapshot(snapshot)
    if problems:
        raise SnapshotError("built snapshot is invalid: " + "; ".join(problems))
    return snapshot


# --------------------------------------------------------------------------- adb argv

_SERIAL = re.compile(r"[A-Za-z0-9._:\-]{1,128}")
_REMOTE_PATH = re.compile(r"/(?:sdcard|data/local/tmp)/[A-Za-z0-9._\-]{1,100}(?:/[A-Za-z0-9._\-]{1,100}){0,4}")
_TEXT = re.compile(r"[A-Za-z0-9 .,@+=:/_\-]{1,1000}")
_KEYCODE = re.compile(r"KEYCODE_[A-Z0-9_]{1,40}")
MAX_COORD = 100_000


def adb_base(serial: str | None = None, adb: str = ADB) -> list[str]:
    if not isinstance(adb, str) or Path(adb).name != "adb":
        raise AdbArgError("adb executable must be named 'adb'")
    if serial is None:
        return [adb]
    if not isinstance(serial, str) or not _SERIAL.fullmatch(serial):
        raise AdbArgError(f"invalid device serial: {serial!r}")
    return [adb, "-s", serial]


def _coord(value: Any, name: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
        raise AdbArgError(f"{name} must be a number")
    iv = int(round(value))
    if not 0 <= iv <= MAX_COORD:
        raise AdbArgError(f"{name} out of range: {value!r}")
    return str(iv)


def _duration(ms: Any) -> str:
    if isinstance(ms, bool) or not isinstance(ms, int) or not 0 <= ms <= 60_000:
        raise AdbArgError("duration_ms must be an integer in 0..60000")
    return str(ms)


def tap_argv(x: float, y: float, *, serial: str | None = None, adb: str = ADB) -> list[str]:
    """Tap at device px (x, y)."""
    return adb_base(serial, adb) + ["shell", "input", "tap", _coord(x, "x"), _coord(y, "y")]


def swipe_argv(x1: float, y1: float, x2: float, y2: float, duration_ms: int = 300, *,
               serial: str | None = None, adb: str = ADB) -> list[str]:
    return adb_base(serial, adb) + ["shell", "input", "swipe", _coord(x1, "x1"), _coord(y1, "y1"),
                                    _coord(x2, "x2"), _coord(y2, "y2"), _duration(duration_ms)]


def long_press_argv(x: float, y: float, duration_ms: int = 600, *, serial: str | None = None,
                    adb: str = ADB) -> list[str]:
    """Long press as a zero-distance swipe (standard adb idiom)."""
    return swipe_argv(x, y, x, y, duration_ms, serial=serial, adb=adb)


def escape_input_text(text: str) -> str:
    """Escape for ``input text``: spaces -> %s; reject anything the device shell could interpret.

    Allowed: ASCII letters/digits, space and . , @ + = : / _ - (not leading '-').
    Non-ASCII (e.g. Korean) cannot be typed with ``input text``; use an IME-based
    method instead (not implemented here).
    """
    if not isinstance(text, str) or not text:
        raise AdbArgError("text must be a non-empty string")
    if len(text) > 1000:
        raise AdbArgError("text longer than 1000 characters")
    if not _TEXT.fullmatch(text):
        bad = sorted({c for c in text if not _TEXT.fullmatch(c)})
        raise AdbArgError(f"text contains characters unsafe for 'adb shell input text': {bad!r}")
    if text.startswith("-"):
        raise AdbArgError("text must not start with '-' (would be read as an option)")
    return text.replace(" ", "%s")


def text_argv(text: str, *, serial: str | None = None, adb: str = ADB) -> list[str]:
    return adb_base(serial, adb) + ["shell", "input", "text", escape_input_text(text)]


def keyevent_argv(key: int | str, *, serial: str | None = None, adb: str = ADB) -> list[str]:
    if isinstance(key, bool):
        raise AdbArgError("keyevent must be an int keycode or KEYCODE_* name")
    if isinstance(key, int):
        if not 0 <= key <= 1000:
            raise AdbArgError("keycode out of range")
        code = str(key)
    elif isinstance(key, str) and _KEYCODE.fullmatch(key):
        code = key
    else:
        raise AdbArgError(f"invalid keyevent: {key!r}")
    return adb_base(serial, adb) + ["shell", "input", "keyevent", code]


def screencap_argv(*, serial: str | None = None, adb: str = ADB) -> list[str]:
    """PNG screenshot on stdout (``exec-out`` keeps the bytes binary-clean)."""
    return adb_base(serial, adb) + ["exec-out", "screencap", "-p"]


def _remote(path: str) -> str:
    if not isinstance(path, str) or not _REMOTE_PATH.fullmatch(path) or "/../" in f"{path}/" or "/./" in f"{path}/":
        raise AdbArgError(f"remote path must be under /sdcard or /data/local/tmp with safe characters: {path!r}")
    return path


def uiautomator_dump_argv(remote_path: str = "/sdcard/ergoqa_window_dump.xml", *, serial: str | None = None,
                          adb: str = ADB) -> list[str]:
    return adb_base(serial, adb) + ["shell", "uiautomator", "dump", _remote(remote_path)]


def read_remote_file_argv(remote_path: str = "/sdcard/ergoqa_window_dump.xml", *, serial: str | None = None,
                          adb: str = ADB) -> list[str]:
    return adb_base(serial, adb) + ["exec-out", "cat", _remote(remote_path)]


def wm_size_argv(*, serial: str | None = None, adb: str = ADB) -> list[str]:
    return adb_base(serial, adb) + ["shell", "wm", "size"]


def wm_density_argv(*, serial: str | None = None, adb: str = ADB) -> list[str]:
    return adb_base(serial, adb) + ["shell", "wm", "density"]


def parse_wm_size(output: str) -> tuple[int, int]:
    """Parse ``wm size`` output; an override size wins over the physical size."""
    found = {kind.lower(): (int(w), int(h)) for kind, w, h in
             re.findall(r"(Physical|Override) size:\s*(\d+)x(\d+)", output or "")}
    if "override" in found:
        return found["override"]
    if "physical" in found:
        return found["physical"]
    raise SnapshotError(f"cannot parse 'wm size' output: {output!r}")


def parse_wm_density(output: str) -> int:
    """Parse ``wm density`` output; an override density wins over the physical one."""
    found = {kind.lower(): int(v) for kind, v in re.findall(r"(Physical|Override) density:\s*(\d+)", output or "")}
    value = found.get("override", found.get("physical"))
    if value is None:
        raise SnapshotError(f"cannot parse 'wm density' output: {output!r}")
    density_scale(value)
    return value


def run_adb(argv: Sequence[str], *, timeout_s: float = 30.0) -> subprocess.CompletedProcess:
    """Run a prepared adb argv (no shell). NOT exercised by this repository's tests."""
    args = list(argv)
    if not args or not all(isinstance(a, str) for a in args) or Path(args[0]).name != "adb":
        raise AdbArgError("argv must be a list of strings starting with adb")
    return subprocess.run(args, shell=False, capture_output=True, timeout=timeout_s, check=False)
