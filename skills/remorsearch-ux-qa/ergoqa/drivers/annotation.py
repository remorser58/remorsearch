"""Vision/human screenshot annotation -> ergo-snapshot.v1 with ``source: "vision"``.

Input (JSON object)::

    {"screenshot": "shot.png", "device_id": "galaxy-s24", "viewport_css": [360, 780],
     "elements": [{"name": "결제하기", "role": "button", "box": {"x": 16, "y": 700, "w": 328, "h": 48},
                   "roles": ["primary"], "text": "결제하기",
                   "color_fg": "#ffffff", "color_bg": "#1a73e8", "font_size_px": 16}]}

Optional: ``dpr``, ``orientation``, ``box_units`` ("css" default, or
"screenshot_px"), ``annotator`` ("model" or "human"), ``surface``
({kind, url, title, app_id}), ``sha256``, ``screenshot_size`` [w, h],
per-element ``id``, ``selector``, ``interactive``, ``enabled``, ``font_weight``,
``border_color``.

Geometry here is ESTIMATED from pixels, not read from the surface: the snapshot
notes say so, every element has ``source: "vision"``, and every observation
derived from it must carry epistemic status ``inferred``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..devices import get_device
from ..snapshot import (ROLES, SURFACE_KINDS, SnapshotError, is_number, parse_hex_color, resolve_within,
                        safe_relative_path, sha256_file, validate_snapshot)

INTERACTIVE_ROLES = ("button", "link", "textbox", "searchbox", "checkbox", "radio", "switch", "slider",
                     "tab", "menuitem", "combobox", "spinbutton", "option")
ESTIMATED_NOTE = ("geometry estimated from a screenshot annotation (source: vision); boxes and colours are "
                  "not measured, so observations derived from them are epistemic 'inferred'")


def _box(value: Any) -> dict[str, float] | None:
    if isinstance(value, dict) and set(value) >= {"x", "y", "w", "h"}:
        parts = [value["x"], value["y"], value["w"], value["h"]]
    elif isinstance(value, (list, tuple)) and len(value) == 4:
        parts = list(value)
    else:
        return None
    if not all(is_number(v) for v in parts) or parts[2] < 0 or parts[3] < 0:
        return None
    return {"x": float(parts[0]), "y": float(parts[1]), "w": float(parts[2]), "h": float(parts[3])}


def validate_annotation(annotation: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(annotation, dict):
        return ["annotation must be an object"]
    if not safe_relative_path(annotation.get("screenshot")):
        errors.append("screenshot: must be a safe relative path")
    try:
        get_device(annotation.get("device_id"))
    except KeyError:
        errors.append(f"device_id: unknown device {annotation.get('device_id')!r}")
    vp = annotation.get("viewport_css")
    if not (isinstance(vp, (list, tuple)) and len(vp) == 2 and all(is_number(v) and v > 0 for v in vp)):
        errors.append("viewport_css: must be [width, height] positive numbers")
    if "dpr" in annotation and not (is_number(annotation["dpr"]) and annotation["dpr"] > 0):
        errors.append("dpr: must be a positive number")
    if annotation.get("box_units", "css") not in ("css", "screenshot_px"):
        errors.append("box_units: must be 'css' or 'screenshot_px'")
    if annotation.get("orientation", "portrait") not in ("portrait", "landscape"):
        errors.append("orientation: must be portrait or landscape")
    surface = annotation.get("surface")
    if surface is not None and (not isinstance(surface, dict) or surface.get("kind") not in SURFACE_KINDS):
        errors.append(f"surface.kind: must be one of {list(SURFACE_KINDS)}")
    elements = annotation.get("elements")
    if not isinstance(elements, list):
        return errors + ["elements: must be an array"]
    for i, el in enumerate(elements):
        path = f"elements[{i}]"
        if not isinstance(el, dict):
            errors.append(f"{path}: must be an object")
            continue
        if not isinstance(el.get("name"), str):
            errors.append(f"{path}.name: must be a string")
        if not isinstance(el.get("role"), str) or not el["role"].strip():
            errors.append(f"{path}.role: must be a non-empty string")
        if _box(el.get("box")) is None:
            errors.append(f"{path}.box: must be {{x,y,w,h}} or [x,y,w,h] with w,h >= 0")
        roles = el.get("roles", [])
        if not isinstance(roles, list) or any(r not in ROLES for r in roles):
            errors.append(f"{path}.roles: must be a list drawn from {list(ROLES)}")
        if el.get("text") is not None and not isinstance(el["text"], str):
            errors.append(f"{path}.text: must be a string or null")
        for key in ("color_fg", "color_bg", "border_color"):
            if el.get(key) is not None:
                try:
                    parse_hex_color(el[key])
                except ValueError:
                    errors.append(f"{path}.{key}: must be a hex colour")
        if el.get("font_size_px") is not None and not (is_number(el["font_size_px"]) and el["font_size_px"] > 0):
            errors.append(f"{path}.font_size_px: must be a positive number")
        for key in ("interactive", "enabled"):
            if key in el and not isinstance(el[key], bool):
                errors.append(f"{path}.{key}: must be a boolean")
    return errors


def annotation_to_snapshot(annotation: dict[str, Any], *, base_dir: str | Path | None = None,
                           run_id: str = "R-annotation", snapshot_id: str | None = None,
                           step_index: int = 0, captured_at: str | None = None) -> dict[str, Any]:
    """Convert an annotation into a validated snapshot.

    With ``base_dir`` the screenshot must exist inside it (traversal-safe); its
    SHA-256 and PNG dimensions are recorded. Without it, dimensions come from
    ``screenshot_size`` or viewport x dpr and a note records that the file was
    not verified.
    """
    from ..png import read_header

    problems = validate_annotation(annotation)
    if problems:
        raise SnapshotError("invalid annotation: " + "; ".join(problems))
    device = get_device(annotation["device_id"])
    vw, vh = (float(v) for v in annotation["viewport_css"])
    dpr = float(annotation.get("dpr", device.dpr))
    orientation = annotation.get("orientation") or ("landscape" if vw > vh else "portrait")
    notes = [ESTIMATED_NOTE, f"annotator: {annotation.get('annotator', 'unspecified')}"]
    surface = dict(annotation.get("surface") or {})
    if not surface:
        surface = {"kind": "web"}
        notes.append("surface kind not given; assumed 'web'")
    surface.setdefault("url", None)
    surface.setdefault("title", None)
    surface.setdefault("app_id", None)

    ref = annotation["screenshot"]
    if base_dir is not None:
        png_path = resolve_within(base_dir, ref)
        if not png_path.is_file():
            raise SnapshotError(f"screenshot not found: {ref}")
        header = read_header(png_path)
        width_px, height_px = header.width, header.height
        sha = sha256_file(png_path)
        if annotation.get("sha256") not in (None, sha):
            raise SnapshotError("annotation sha256 does not match the screenshot file")
    else:
        size = annotation.get("screenshot_size")
        if isinstance(size, (list, tuple)) and len(size) == 2 and all(isinstance(v, int) and v > 0 for v in size):
            width_px, height_px = size
        else:
            width_px, height_px = round(vw * dpr), round(vh * dpr)
        sha = annotation.get("sha256")
        notes.append("screenshot file not verified (no base_dir); dimensions/sha256 as declared")

    scale = 1.0
    if annotation.get("box_units", "css") == "screenshot_px":
        scale = width_px / vw
        notes.append(f"boxes converted from screenshot px by 1/{scale:g}")

    elements = []
    for i, src in enumerate(annotation["elements"]):
        raw = _box(src["box"])
        assert raw is not None
        box = {k: round(v / scale, 3) for k, v in raw.items()}
        role = src["role"].strip()
        elements.append({
            "id": src.get("id") or f"el-{i + 1}",
            "role": role,
            "name": src["name"],
            "text": src.get("text"),
            "tag": None,
            "selector": src.get("selector"),
            "box": box,
            "interactive": src.get("interactive", role in INTERACTIVE_ROLES),
            "visible": True,
            "enabled": src.get("enabled", True),
            "in_viewport": box["x"] < vw and box["y"] < vh and box["x"] + box["w"] > 0 and box["y"] + box["h"] > 0,
            "font_size_px": src.get("font_size_px"),
            "font_weight": src.get("font_weight"),
            "color_fg": src.get("color_fg"),
            "color_bg": src.get("color_bg"),
            "border_color": src.get("border_color"),
            "roles": list(src.get("roles", [])),
            "source": "vision",
        })
    snapshot = {
        "schema_version": "ergo-snapshot.v1",
        "snapshot_id": snapshot_id or f"S-{run_id}-{step_index:03d}",
        "run_id": run_id,
        "step_index": step_index,
        "captured_at": captured_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "surface": surface,
        "device": {"id": device.id, "viewport_css": [vw, vh], "dpr": dpr, "orientation": orientation},
        "screenshot": {"path": ref, "sha256": sha, "width_px": width_px, "height_px": height_px},
        "elements": elements,
        "focus_point": annotation.get("focus_point"),
        "console_errors": [],
        "notes": notes + [n for n in (annotation.get("notes") if isinstance(annotation.get("notes"), list) else [])
                          if isinstance(n, str)],
        "geometry_basis": "estimated",
    }
    problems = validate_snapshot(snapshot)
    if problems:
        raise SnapshotError("annotation produced an invalid snapshot: " + "; ".join(problems))
    return snapshot
