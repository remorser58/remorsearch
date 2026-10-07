"""Audience research -> persona composition (ergo-audience.v1).

Stage 0 of the skill researches who uses the product under test and writes an
``ergo-audience.v1`` file: segments with evidence, age and device mix,
abilities, contexts of use and key tasks with concrete data. This module turns
that file into ergonomic profiles deterministically, so every persona in the
swarm can be traced to a segment and to the evidence behind it.

Composition rules (see docs/ergonomic-swarm-spec.md section 13):

1. Every segment gets at least one profile; the remaining budget is split by
   largest remainder over segment weights (share, or a priority default).
2. Inside a segment the first profile is the segment's typical member (modal
   age, top device, dominant grip, modal context, conditions the segment
   shares in majority). Each further profile varies ONE facet (a minority
   condition, a context, the left-hand mirror, a first-time user, another
   age band), so a finding's differential condition stays attributable.
3. Inclusive floors (optional, default on) guarantee, per device group, a left
   one-hand / left mouse profile and the conditions listed in ``floors``,
   attached to the segment where they are most plausible and labelled as
   floors rather than evidence.

Profiles are test inputs. Segment shares steer the allocation; they are never
reported as prevalence of the findings.
"""

from __future__ import annotations

import copy
import re
from typing import Any, Iterable

from . import params
from .devices import get_device
from .profiles import AGE_BANDS, SCHEMA_VERSION as PROFILE_SCHEMA, _finalise, _set_path, label_ko

SCHEMA_VERSION = "ergo-audience.v1"
PRIORITIES = ("primary", "secondary", "edge")
PRIORITY_DEFAULT_SHARE = {"primary": 0.5, "secondary": 0.3, "edge": 0.2}
SHARE_BASIS = ("measured", "estimated", "unknown")
CONFIDENCE = ("high", "medium", "low")
SOURCE_TYPES = (
    "official_statistics", "product_analytics", "app_store_reviews", "community", "survey",
    "interview", "usability_test", "support_tickets", "official_docs", "competitor",
    "market_report", "research_paper", "product_brief", "expert_judgment", "news",
)
# Self-selected or reported sources support that a group or complaint exists, never
# its size (references/research/source-grading.md, packaging session design).
EXISTENCE_ONLY_TYPES = ("community", "app_store_reviews", "news")
EVIDENCE_KINDS = ("firsthand", "statistic", "official", "inference")
# How the quote was read: the page itself, a document the team supplied, or only a
# search-result snippet (the page could not be opened). Snippet quotes are listed as
# unverified in the plan and must be checked before anyone relies on them.
QUOTE_BASIS = ("page", "document", "snippet")


def quote_basis_kind(value: Any) -> str | None:
    """Normalise ``quote_basis``: the enum values, or free text classified
    conservatively (anything that is not clearly a page or a full document read
    counts as a snippet)."""
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in QUOTE_BASIS:
        return text
    if any(w in text for w in ("snippet", "search", "extract", "excerpt", "headline", "title")):
        return "snippet"
    if "document" in text or "read in full" in text or "pdf" in text:
        return "document"
    if "page" in text:
        return "page"
    return "snippet"
FREQUENCIES = ("daily", "weekly", "monthly", "rare", "once")
CRITICALITY = ("safety", "health", "money", "legal", "data", "access", "convenience")
STAKES = ("high", "normal")

# Condition vocabulary -> profile attribute overrides.
CONDITIONS: dict[str, dict[str, Any]] = {
    "presbyopia": {"vision.presbyopia": True},
    "low_vision": {"vision.acuity": "low"},
    "reduced_acuity": {"vision.acuity": "reduced"},
    "cvd_deutan": {"vision.cvd": "deutan"},
    "cvd_protan": {"vision.cvd": "protan"},
    "cvd_tritan": {"vision.cvd": "tritan"},
    "tremor_mild": {"motor.tremor": "mild"},
    "tremor_moderate": {"motor.tremor": "moderate"},
    "first_use": {"cognition.familiarity": "first_use"},
    "expert": {"cognition.familiarity": "expert"},
    "time_pressure": {"cognition.time_pressure": "high"},
    "small_hand": {"hand_percentile": 5},
    "large_hand": {"hand_percentile": 95},
}
# Conditions a Stage-0 file may declare but the models do not simulate: they are listed
# as untested with their source, never silently dropped (AP-10).
NOT_SIMULATED = ("hearing_loss", "deaf", "screen_reader", "switch_access", "cognitive", "magnifier")
ROLES = ("operator", "customer", "served")
CONTEXT_KEYS = ("mobility", "lighting", "one_handed", "interruptions", "time_pressure")
MOBILITY = ("seated", "standing", "walking", "transit")
LIGHTING = ("indoor", "bright_sun", "dark")
# Inclusive floors: conditions whose removal lost unique seeded defects in >= 2 of the
# 3 development suites (docs/validation/experiments/ablation-dev-8707b70.json):
# deutan 4 defects/3 suites, left one-hand 3/2, presbyopia 3/3 (PC-04), walking 2/2.
FLOOR_DEFAULTS = ("left_hand", "cvd_deutan", "presbyopia", "walking")
FLOOR_CHOICES = ("left_hand", "walking") + tuple(CONDITIONS)
MAJORITY = 0.5            # a condition shared by >= 50 % of a segment is applied to its typical member
MINOR_CONTEXT_SHARE = 0.15  # contexts at or above this share get their own profile when slots allow
EXTRA_AGE_SHARE = 0.2     # a second age band at or above this share gets its own profile
DEVICE_FACET_SHARE = 0.3  # another device at or above this share of the segment gets a typical member


class AudienceError(ValueError):
    pass


# ---------------------------------------------------------------------------
# Validation


def _is_share(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 1


def _weights_ok(obj: Any, allowed: Iterable[str] | None, where: str, errors: list[str]) -> None:
    if not isinstance(obj, dict) or not obj:
        errors.append(f"{where} must be a non-empty object of weights")
        return
    for key, value in obj.items():
        if allowed is not None and key not in allowed:
            errors.append(f"{where}: unknown key {key!r}")
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
            errors.append(f"{where}.{key} must be a non-negative number")
    if sum(v for v in obj.values() if isinstance(v, (int, float))) <= 0:
        errors.append(f"{where} weights must not all be zero")


def validate_audience(doc: Any) -> list[str]:
    """Return a list of contract errors (empty when the document is valid)."""
    errors: list[str] = []
    if not isinstance(doc, dict):
        return ["audience must be an object"]
    if doc.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    if not isinstance(doc.get("audience_id"), str) or not doc["audience_id"]:
        errors.append("audience_id is required")
    product = doc.get("product")
    if not isinstance(product, dict) or not product.get("name"):
        errors.append("product.name is required")
    sources = doc.get("sources")
    source_ids: set[str] = set()
    if not isinstance(sources, list) or not sources:
        errors.append("sources must be a non-empty array")
    else:
        for i, src in enumerate(sources):
            if not isinstance(src, dict):
                errors.append(f"sources[{i}] must be an object")
                continue
            sid = src.get("source_id")
            if not isinstance(sid, str) or not sid:
                errors.append(f"sources[{i}].source_id is required")
            elif sid in source_ids:
                errors.append(f"duplicate source_id {sid}")
            else:
                source_ids.add(sid)
            if src.get("type") not in SOURCE_TYPES:
                errors.append(f"sources[{i}].type must be one of {', '.join(SOURCE_TYPES)}")
            if not src.get("title"):
                errors.append(f"sources[{i}].title is required")
            if src.get("bundle_ref") is not None and (not isinstance(src["bundle_ref"], str) or not src["bundle_ref"].strip()):
                errors.append(f"sources[{i}].bundle_ref must be a non-empty string (ux-evidence-bundle source id) when present")
    type_of = {src.get("source_id"): src.get("type") for src in sources if isinstance(src, dict)} if isinstance(sources, list) else {}

    def existence_only(refs: Any) -> bool:
        return isinstance(refs, list) and bool(refs) and all(type_of.get(r) in EXISTENCE_ONLY_TYPES for r in refs)

    def refs_ok(refs: Any, where: str, required: bool = True) -> None:
        if refs is None and not required:
            return
        if not isinstance(refs, list) or (required and not refs):
            errors.append(f"{where} must list at least one source_id")
            return
        for ref in refs:
            if ref not in source_ids:
                errors.append(f"{where}: unknown source_id {ref!r}")

    segments = doc.get("segments")
    if not isinstance(segments, list) or not segments:
        return errors + ["segments must be a non-empty array"]
    seen: set[str] = set()
    task_ids: set[str] = set()
    for i, seg in enumerate(segments):
        where = f"segments[{i}]"
        if not isinstance(seg, dict):
            errors.append(f"{where} must be an object")
            continue
        sid = seg.get("segment_id")
        if not isinstance(sid, str) or not sid:
            errors.append(f"{where}.segment_id is required")
        elif sid in seen:
            errors.append(f"duplicate segment_id {sid}")
        else:
            seen.add(sid)
        if not seg.get("name_ko"):
            errors.append(f"{where}.name_ko is required")
        if seg.get("priority") not in PRIORITIES:
            errors.append(f"{where}.priority must be one of {', '.join(PRIORITIES)}")
        if seg.get("confidence") not in CONFIDENCE:
            errors.append(f"{where}.confidence must be one of {', '.join(CONFIDENCE)}")
        share = seg.get("share")
        if not isinstance(share, dict) or share.get("basis") not in SHARE_BASIS:
            errors.append(f"{where}.share must be an object with basis {'|'.join(SHARE_BASIS)}")
        else:
            value = share.get("value")
            if share["basis"] == "unknown":
                if value is not None:
                    errors.append(f"{where}.share.value must be null when basis is unknown")
            else:
                if not _is_share(value):
                    errors.append(f"{where}.share.value must be between 0 and 1")
                refs_ok(share.get("source_ids"), f"{where}.share.source_ids")
                if existence_only(share.get("source_ids")):
                    errors.append(f"{where}.share rests only on community, review or news sources; they support existence, not size (use basis unknown)")
        evidence = seg.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            errors.append(f"{where}.evidence must be a non-empty array (why this segment exists)")
        else:
            for j, ev in enumerate(evidence):
                if not isinstance(ev, dict) or not ev.get("claim"):
                    errors.append(f"{where}.evidence[{j}].claim is required")
                    continue
                if ev.get("kind") not in EVIDENCE_KINDS:
                    errors.append(f"{where}.evidence[{j}].kind must be one of {', '.join(EVIDENCE_KINDS)}")
                elif ev["kind"] == "statistic" and not re.search(r"\d", str(ev.get("quote") or "")):
                    errors.append(f"{where}.evidence[{j}].quote must quote the source's number for statistic evidence")
                elif ev["kind"] == "official" and not str(ev.get("quote") or "").strip():
                    errors.append(f"{where}.evidence[{j}].quote must quote the official text")
                if ev.get("quote_basis") is not None and (not isinstance(ev["quote_basis"], str) or not ev["quote_basis"].strip()):
                    errors.append(f"{where}.evidence[{j}].quote_basis must be a non-empty string ({', '.join(QUOTE_BASIS)} or a description)")
                refs_ok([ev.get("source_id")], f"{where}.evidence[{j}].source_id")
                if ev.get("kind") == "statistic" and existence_only([ev.get("source_id")]):
                    errors.append(f"{where}.evidence[{j}] is a statistic from a community, review or news source; record it as firsthand (existence only)")
        _weights_ok(seg.get("age_bands"), AGE_BANDS, f"{where}.age_bands", errors)
        devices = seg.get("devices")
        _weights_ok(devices, None, f"{where}.devices", errors)
        if isinstance(devices, dict):
            for device_id in devices:
                try:
                    get_device(device_id)
                except Exception:  # noqa: BLE001 - report unknown ids
                    errors.append(f"{where}.devices: unknown device id {device_id!r} (add it to ergoqa/devices.py)")
        if seg.get("orientation") not in (None, "portrait", "landscape"):
            errors.append(f"{where}.orientation must be portrait or landscape")
        left = seg.get("left_hand_share")
        if left is not None and not _is_share(left):
            errors.append(f"{where}.left_hand_share must be between 0 and 1")
        if seg.get("grips") is not None:
            _weights_ok(seg["grips"], ("one_hand", "cradle", "two_thumbs"), f"{where}.grips", errors)
        if seg.get("familiarity") is not None:
            _weights_ok(seg["familiarity"], ("first_use", "returning", "expert"), f"{where}.familiarity", errors)
        if seg.get("role", "operator") not in ROLES:
            errors.append(f"{where}.role must be one of {', '.join(ROLES)}")
        for j, cond in enumerate(seg.get("conditions") or []):
            cw = f"{where}.conditions[{j}]"
            if not isinstance(cond, dict) or cond.get("condition") not in CONDITIONS and cond.get("condition") not in NOT_SIMULATED:
                errors.append(f"{cw}.condition must be one of {', '.join(CONDITIONS)} (or declared-not-simulated: {', '.join(NOT_SIMULATED)})")
                continue
            if cond.get("cause") not in (None, "permanent", "temporary", "situational"):
                errors.append(f"{cw}.cause must be permanent, temporary or situational")
            if cond.get("share") is not None and not _is_share(cond["share"]):
                errors.append(f"{cw}.share must be between 0 and 1 or null")
            if cond.get("stakes", "normal") not in STAKES:
                errors.append(f"{cw}.stakes must be high or normal")
            refs_ok(cond.get("source_ids"), f"{cw}.source_ids")
        for j, ctx in enumerate(seg.get("contexts") or []):
            cw = f"{where}.contexts[{j}]"
            if not isinstance(ctx, dict) or not ctx.get("context_id"):
                errors.append(f"{cw}.context_id is required")
                continue
            if ctx.get("mobility", "seated") not in MOBILITY:
                errors.append(f"{cw}.mobility must be one of {', '.join(MOBILITY)}")
            if ctx.get("lighting", "indoor") not in LIGHTING:
                errors.append(f"{cw}.lighting must be one of {', '.join(LIGHTING)}")
            if ctx.get("share") is not None and not _is_share(ctx["share"]):
                errors.append(f"{cw}.share must be between 0 and 1 or null")
            refs_ok(ctx.get("source_ids"), f"{cw}.source_ids")
        tasks = seg.get("tasks")
        if not isinstance(tasks, list) or not tasks:
            errors.append(f"{where}.tasks must list the segment's key tasks")
        else:
            for j, task in enumerate(tasks):
                tw = f"{where}.tasks[{j}]"
                if not isinstance(task, dict) or not task.get("task_id") or not task.get("goal_ko"):
                    errors.append(f"{tw} needs task_id and goal_ko")
                    continue
                task_ids.add(task["task_id"])
                if not isinstance(task.get("concrete_data"), dict) or not task["concrete_data"]:
                    errors.append(f"{tw}.concrete_data must give the values an agent types or picks (amounts, dates, names)")
                if task.get("frequency") not in FREQUENCIES:
                    errors.append(f"{tw}.frequency must be one of {', '.join(FREQUENCIES)}")
                if task.get("criticality") not in CRITICALITY:
                    errors.append(f"{tw}.criticality must be one of {', '.join(CRITICALITY)}")
                refs_ok(task.get("source_ids"), f"{tw}.source_ids")
    floors = doc.get("floors")
    if floors is not None:
        if not isinstance(floors, list) or any(f not in FLOOR_CHOICES for f in floors):
            errors.append(f"floors must be a list drawn from {', '.join(FLOOR_CHOICES)}")
    return errors


# ---------------------------------------------------------------------------
# Composition


def _largest_remainder(weights: dict[str, float], total: int, order: list[str]) -> dict[str, int]:
    """Integer allocation of ``total`` proportional to weights (ties by ``order``)."""
    out = {k: 0 for k in weights}
    mass = sum(weights.values())
    if total <= 0 or mass <= 0:
        return out
    quotas = {k: total * w / mass for k, w in weights.items()}
    for k, q in quotas.items():
        out[k] = int(q)
    left = total - sum(out.values())
    rank = sorted(weights, key=lambda k: (-(quotas[k] - int(quotas[k])), order.index(k)))
    for k in rank[:left]:
        out[k] += 1
    return out


def segment_weights(segments: list[dict[str, Any]]) -> dict[str, float]:
    """Share when known; otherwise a priority default scaled into the unclaimed mass."""
    known = {s["segment_id"]: float(s["share"]["value"]) for s in segments if s["share"].get("value") is not None}
    unknown = [s for s in segments if s["share"].get("value") is None]
    weights = dict(known)
    if unknown:
        remaining = max(0.0, 1.0 - sum(known.values()))
        raw = {s["segment_id"]: PRIORITY_DEFAULT_SHARE[s["priority"]] for s in unknown}
        if remaining <= 0.0:
            remaining = 0.05 * len(unknown)
        scale = remaining / sum(raw.values())
        weights.update({k: v * scale for k, v in raw.items()})
    return weights


def _modal(weights: dict[str, float], order: Iterable[str]) -> str:
    order = list(order)
    return max(weights, key=lambda k: (weights[k], -order.index(k) if k in order else 0))


def _base_attrs(device: Any, orientation: str) -> dict[str, Any]:
    touch = device.input == "touch"
    return {
        "age_band": "30s", "handedness": "right",
        "grip": ("two_thumbs" if orientation == "landscape" else "one_hand_right") if touch else ("mouse_right" if device.input == "mouse" else "keyboard_only" if device.input == "keyboard" else device.input),
        "thumb_length_mm": 0, "hand_percentile": 50,
        "device_id": device.id, "orientation": orientation,
        "vision": {"acuity": "normal", "presbyopia": False, "cvd": "none", "cvd_severity": 1.0, "viewing_distance_mm": 0},
        "motor": {"tremor": "none", "touch_sigma_multiplier": 1.0, "touch_sigma_mm": 0.0},
        "context": {"mobility": "seated", "lighting": "indoor", "free_hands": 1 if touch else 2, "interruptions": False},
        "cognition": {"familiarity": "returning", "time_pressure": "low", "reading_wpm_ko": 0},
        "reaction_time_ms": 0,
    }


def _grip_for(device: Any, orientation: str, grip_kind: str, left: bool) -> tuple[str, str]:
    """(grip, handedness) for a device, a grip family and a side."""
    side = "left" if left else "right"
    if device.input == "touch":
        if orientation == "landscape" or grip_kind == "two_thumbs":
            return "two_thumbs", side
        if min(getattr(device, "physical_mm", (0, 0))) > 120.0:
            return f"cradle_{side}", side  # tablets: held with one hand, tapped with the other (HGR-9)
        return (f"cradle_{side}" if grip_kind == "cradle" else f"one_hand_{side}"), side
    if device.input == "mouse":
        return f"mouse_{side}", side
    if device.input == "keyboard":
        return "keyboard_only", side
    return device.input, side


def _apply_context(attrs: dict[str, Any], ctx: dict[str, Any] | None, device: Any, orientation: str) -> None:
    if not ctx:
        return
    mobility = ctx.get("mobility", "seated")
    # The profile schema has no "standing"; standing is treated like seated for the hand models.
    attrs["context"]["mobility"] = "seated" if mobility == "standing" else mobility
    attrs["context"]["lighting"] = ctx.get("lighting", "indoor")
    attrs["context"]["interruptions"] = bool(ctx.get("interruptions", False))
    if ctx.get("time_pressure") == "high":
        attrs["cognition"]["time_pressure"] = "high"
    if device.input == "touch" and orientation == "portrait" and (ctx.get("one_handed") or mobility in ("walking", "transit")):
        side = "left" if attrs["handedness"] == "left" else "right"
        attrs["grip"] = f"one_hand_{side}"
        attrs["context"]["free_hands"] = 1


def _facets(seg: dict[str, Any], modal_ctx: dict[str, Any] | None, modal_age: str) -> list[dict[str, Any]]:
    """Ordered single-facet variations of a segment's typical member.

    Order: high-stakes minority conditions, the left-hand mirror, the typical
    member on another device the segment really uses, contexts, remaining
    minority conditions, first-time use, other age bands, other grips.
    """
    conds = [c for c in seg.get("conditions") or [] if c["condition"] in CONDITIONS and (c.get("share") is None or c["share"] < MAJORITY)]
    conds.sort(key=lambda c: (-(c.get("share") or 0.0), list(CONDITIONS).index(c["condition"])))

    def cond_facet(c: dict[str, Any]) -> dict[str, Any]:
        return {"kind": "condition", "condition": c["condition"], "source_ids": c.get("source_ids", []),
                "reason": f"condition {c['condition']}" + (f" (share {c['share']:.0%})" if c.get("share") is not None else "") + (", high stakes" if c.get("stakes") == "high" else "")}

    facets: list[dict[str, Any]] = [cond_facet(c) for c in conds if c.get("stakes") == "high"]
    left_share = seg.get("left_hand_share")
    if left_share is None:
        left_share = params.LEFT_SHARE_BY_AGE_KR.get(modal_age, params.HANDEDNESS_SHARE_KR["left"])
    facets.append({"kind": "left_mirror", "source_ids": [],
                   "reason": f"left-hand mirror (left-handed share {left_share:.0%}; left-thumb one-handed use is common)"})
    devices = seg.get("devices") or {}
    total_dev = sum(devices.values()) or 1.0
    ranked = sorted(devices, key=lambda d: -devices[d])
    for device_id in ranked[1:]:
        if devices[device_id] / total_dev >= DEVICE_FACET_SHARE:
            facets.append({"kind": "device", "device_id": device_id, "source_ids": [],
                           "reason": f"typical member on {device_id} ({devices[device_id] / total_dev:.0%} of segment devices)"})
    for ctx in sorted(seg.get("contexts") or [], key=lambda c: -(c.get("share") or 0.0)):
        if modal_ctx is not None and ctx.get("context_id") == modal_ctx.get("context_id"):
            continue
        if ctx.get("share") is None or ctx["share"] >= MINOR_CONTEXT_SHARE:
            facets.append({"kind": "context", "context": ctx, "source_ids": ctx.get("source_ids", []),
                           "reason": f"context {ctx['context_id']} ({ctx.get('mobility', 'seated')}, {ctx.get('lighting', 'indoor')})"})
    facets += [cond_facet(c) for c in conds if c.get("stakes") != "high"]
    fam = seg.get("familiarity") or {}
    if fam and fam.get("first_use", 0) >= 0.2 and _modal(fam, ("returning", "first_use", "expert")) != "first_use" \
            and not any(f.get("condition") == "first_use" for f in facets):
        facets.append({"kind": "condition", "condition": "first_use", "source_ids": [], "reason": f"first-time users ({fam['first_use']:.0%})"})
    ages = seg.get("age_bands") or {}
    total = sum(ages.values()) or 1.0
    for band in sorted(ages, key=lambda b: (-ages[b], AGE_BANDS.index(b))):
        if band != modal_age and ages[band] / total >= EXTRA_AGE_SHARE:
            facets.append({"kind": "age", "age_band": band, "source_ids": [], "reason": f"age band {band} ({ages[band] / total:.0%} of segment)"})
    grips = seg.get("grips") or {}
    for g in ("two_thumbs", "cradle"):
        if grips and grips.get(g, 0) / (sum(grips.values()) or 1.0) >= 0.25:
            facets.append({"kind": "grip", "grip": g, "source_ids": [], "reason": f"grip {g} ({grips[g] / sum(grips.values()):.0%})"})
    return facets


def _make_profile(audience: dict[str, Any], seg: dict[str, Any], device_id: str, orientation: str | None,
                  facet: dict[str, Any] | None, modal_age: str, modal_ctx: dict[str, Any] | None,
                  majority: list[dict[str, Any]], dominant_grip: str, index: int, floor: str | None = None) -> dict[str, Any]:
    device = get_device(device_id)
    orient = orientation or seg.get("orientation") or device.orientation
    attrs = _base_attrs(device, orient)
    age = facet["age_band"] if facet and facet.get("kind") == "age" else modal_age
    attrs["age_band"] = age
    left = bool(facet and facet.get("kind") == "left_mirror") or floor == "left_hand"
    grip_kind = facet["grip"] if facet and facet.get("kind") == "grip" else dominant_grip
    attrs["grip"], attrs["handedness"] = _grip_for(device, orient, grip_kind, left)
    if attrs["grip"].startswith("one_hand"):
        attrs["context"]["free_hands"] = 1
    # Presbyopia comes from the segment's own declared conditions (or a facet/floor),
    # never from an age band — neither the modal age nor an age facet (AP-14 and the
    # personas-and-audience rules: age is context; a sensory condition is an explicit
    # input or a separately declared simulation assumption). A 50+ segment that does
    # not declare presbyopia keeps it unset; the inclusive floor still guarantees
    # coverage when the audience needs it.
    reasons = [f"segment {seg['segment_id']} base profile (a base for variation, not an average user): {age}, {device_id}, {attrs['grip']}"]
    for cond in majority:
        for k, v in CONDITIONS[cond["condition"]].items():
            _set_path(attrs, k, v)
        reasons.append(f"majority condition {cond['condition']} ({cond['share']:.0%})")
    ctx = facet["context"] if facet and facet.get("kind") == "context" else modal_ctx
    _apply_context(attrs, ctx, device, orient)
    fam = seg.get("familiarity") or {}
    if fam:
        attrs["cognition"]["familiarity"] = _modal(fam, ("returning", "first_use", "expert"))
    if facet and facet.get("kind") == "condition":
        for k, v in CONDITIONS[facet["condition"]].items():
            _set_path(attrs, k, v)
    if floor == "walking":
        _apply_context(attrs, {"context_id": "floor-walking", "mobility": "walking", "lighting": attrs["context"]["lighting"], "one_handed": True}, device, orient)
    elif floor and floor != "left_hand":
        for k, v in CONDITIONS[floor].items():
            _set_path(attrs, k, v)
    if facet:
        reasons.append("varies one facet: " + facet["reason"])
    if floor:
        reasons.append(f"inclusive floor: {floor} (coverage guarantee, not segment evidence)")
    profile = {
        "schema_version": PROFILE_SCHEMA,
        "profile_id": f"AP-{index:02d}",
        "origin": "audience_composed",
        "persona_ref": None,
        "label_ko": "",
        "attributes": attrs,
        "assumption_fields": ["handedness", "grip", "thumb_length_mm", "hand_percentile", "motor", "reaction_time_ms"],
        "base_rate_refs": dict(params.BASE_RATE_REFS),
        "audience_ref": {
            "audience_id": audience["audience_id"],
            "segment_id": seg["segment_id"],
            "segment_priority": seg["priority"],
            "context_id": (ctx or {}).get("context_id"),
            "task_ids": [t["task_id"] for t in seg.get("tasks") or []],
            "facet": (facet or {}).get("kind", "typical"),
            "floor": floor,
            "reasons": reasons,
            "source_ids": sorted({*(facet or {}).get("source_ids", []), *[e.get("source_id") for e in seg.get("evidence", []) if e.get("source_id")]}),
        },
    }
    _finalise(profile, device)
    profile["label_ko"] = f"[{seg['name_ko']}] " + label_ko(profile)
    return profile


def _input_kind(device_id: str) -> str:
    kind = get_device(device_id).input
    return "pointer" if kind in ("mouse", "keyboard") else kind


HANDHELD_FORM_FACTORS = ("phone", "foldable")


def _kind_ok(device_id: str, kind: str | None) -> bool:
    """Whether a device fits a floor's requirement: an input kind, or ``handheld``
    (walking is only plausible with a phone in the hand, not a tablet on a stand)."""
    if kind is None:
        return True
    if kind == "handheld":
        return get_device(device_id).form_factor in HANDHELD_FORM_FACTORS
    return _input_kind(device_id) == kind


def _is_left(profile: dict[str, Any]) -> bool:
    a = profile["attributes"]
    return a["grip"] in ("one_hand_left", "cradle_left", "mouse_left") or (a["grip"] == "two_thumbs" and a["handedness"] == "left")


def _get(attrs: dict[str, Any], dotted: str) -> Any:
    cur: Any = attrs
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _floor_requirements(floor_list: list[str], segments: list[dict[str, Any]]) -> list[tuple[str, str | None]]:
    """(floor, input kind or None). Left-hand floors apply per input kind; others once per swarm."""
    kinds = sorted({_input_kind(d) for s in segments for d in s["devices"]} & {"touch", "pointer"})
    reqs: list[tuple[str, str | None]] = []
    for floor in floor_list:
        if floor == "left_hand":
            reqs += [(floor, kind) for kind in kinds]
        elif floor == "walking":
            if any(_kind_ok(d, "handheld") for s in segments for d in s["devices"]):
                reqs.append((floor, "handheld"))  # walking only changes handheld touch use
        else:
            reqs.append((floor, None))
    return reqs


def _floor_met(floor: str, kind: str | None, profiles: list[dict[str, Any]]) -> bool:
    pool = [p for p in profiles if _kind_ok(p["attributes"]["device_id"], kind)]
    if floor == "left_hand":
        return any(_is_left(p) for p in pool)
    if floor == "walking":
        return any(p["attributes"]["context"]["mobility"] == "walking" for p in pool)
    return any(all(_get(p["attributes"], k) == v for k, v in CONDITIONS[floor].items()) for p in pool)


def _floor_segment(floor: str, kind: str | None, segments: list[dict[str, Any]], weights: dict[str, float]) -> tuple[dict[str, Any], str]:
    """The segment where a floor is most plausible, and its top device of the needed input kind."""
    users = [s for s in segments if any(_kind_ok(d, kind) for d in s["devices"])] or segments

    def share_of(s: dict[str, Any], bands: tuple[str, ...]) -> float:
        ages = s.get("age_bands") or {}
        return sum(v for k, v in ages.items() if k in bands) / (sum(ages.values()) or 1.0)

    def left_share(s: dict[str, Any]) -> float:
        if s.get("left_hand_share") is not None:
            return float(s["left_hand_share"])
        ages = s.get("age_bands") or {}
        return sum(v * params.LEFT_SHARE_BY_AGE_KR.get(k, 0.06) for k, v in ages.items()) / (sum(ages.values()) or 1.0)

    if floor == "presbyopia":
        seg = max(users, key=lambda s: (share_of(s, ("50s", "60s", "70s+")), weights[s["segment_id"]]))
    elif floor == "left_hand":
        seg = max(users, key=lambda s: (left_share(s) * weights[s["segment_id"]], weights[s["segment_id"]]))
    else:
        seg = max(users, key=lambda s: weights[s["segment_id"]])
    devices = [d for d in sorted(seg["devices"], key=lambda d: -seg["devices"][d]) if _kind_ok(d, kind)]
    return seg, (devices or sorted(seg["devices"], key=lambda d: -seg["devices"][d]))[0]


def _segment_state(seg: dict[str, Any]) -> dict[str, Any]:
    ages = seg["age_bands"]
    modal_age = _modal(ages, AGE_BANDS)
    ctxs = seg.get("contexts") or []
    modal_ctx = max(ctxs, key=lambda c: c.get("share") or 0.0) if ctxs else None
    grips = seg.get("grips") or params.MOBILE_GRIP_SHARE
    return {
        "modal_age": modal_age,
        "modal_ctx": modal_ctx,
        "majority": [c for c in seg.get("conditions") or [] if c["condition"] in CONDITIONS and c.get("share") is not None and c["share"] >= MAJORITY],
        "dominant": _modal(grips, ("one_hand", "cradle", "two_thumbs")),
        "top_device": max(seg["devices"], key=lambda d: (seg["devices"][d], d)),
        "queue": _facets(seg, modal_ctx, modal_age),
    }


def compose(audience: dict[str, Any], budget: int, floors: Iterable[str] | None = None, *, research_run=None, bundle_path=None, gate_path=None) -> dict[str, Any]:
    """Compose ``budget`` profiles from an audience file. Returns the persona plan.

    1. One typical member per segment (by priority, then weight, if the budget is
       smaller than the number of segments).
    2. Reserve slots for unmet inclusive floors (at most a third of what is left).
    3. D'Hondt over segment weights: the segment with the highest
       weight / (profiles + 1) that still has an untried facet gets the next
       profile, which varies exactly one facet of its typical member.
    4. Add floor profiles that the segments did not already satisfy; give unused
       reserve back to step 3.
    """
    research_origin = any(x.get("basis") == "research_claim" for x in audience.get("value_provenance", []) if isinstance(x, dict)) or any(re.fullmatch(r"SRC-[0-9a-f]{8}", str(x.get("bundle_ref", ""))) for x in audience.get("sources", []) if isinstance(x, dict)) or any(k in audience for k in ("gate_bundle_input_sha256", "gate_process_input_sha256", "research"))
    if research_origin:
        if not all((research_run, bundle_path, gate_path)):
            raise AudienceError("Research audience composition requires a fresh gate and completed value check")
        from uxresearch.ledger import Run
        from uxresearch.storage import Store, read_json
        from uxresearch.engine import fresh
        from uxresearch.audiences import check_audience
        run = Run(research_run)
        with Store(run.path) as store:
            bundle, gate = fresh(run, store, bundle_path, gate_path)
            if gate["mode"] != "live" or check_audience(audience, bundle, gate, read_json(run.path / "brief.json"))["exit_code"]:
                raise AudienceError("Research audience is incomplete or stale for composition")
    errors = validate_audience(audience)
    if errors:
        raise AudienceError("; ".join(errors))
    if budget < 1:
        raise AudienceError("budget must be >= 1")
    all_segments = audience["segments"]
    segments = [s for s in all_segments if s.get("role", "operator") == "operator"]
    if not segments:
        raise AudienceError("no operator segment: only people who operate the product get profiles")
    floor_list = list(floors) if floors is not None else list(audience.get("floors", FLOOR_DEFAULTS))
    for f in floor_list:
        if f not in FLOOR_CHOICES:
            raise AudienceError(f"unknown floor {f!r}")
    weights = segment_weights(segments)
    state = {s["segment_id"]: _segment_state(s) for s in segments}
    for seg in segments:
        # A facet that changes nothing (a two-thumb variation of a two-thumb base) would
        # spend a slot on a copy of the typical member; it is already covered.
        st = state[seg["segment_id"]]

        def attrs_for(facet: dict[str, Any] | None, st: dict[str, Any] = st, seg: dict[str, Any] = seg) -> dict[str, Any]:
            dev = (facet or {}).get("device_id") or st["top_device"]
            return _make_profile(audience, seg, dev, seg.get("orientation"), facet, st["modal_age"], st["modal_ctx"],
                                 st["majority"], st["dominant"], 0)["attributes"]

        base = attrs_for(None)
        st["queue"] = [f for f in st["queue"] if attrs_for(f) != base]
    by_id = {s["segment_id"]: s for s in segments}
    profiles: list[dict[str, Any]] = []
    counts = {s["segment_id"]: 0 for s in segments}

    def add(seg: dict[str, Any], facet: dict[str, Any] | None, floor: str | None = None, device_id: str | None = None) -> None:
        st = state[seg["segment_id"]]
        dev = device_id or (facet or {}).get("device_id") or st["top_device"]
        profiles.append(_make_profile(audience, seg, dev, seg.get("orientation"), facet, st["modal_age"], st["modal_ctx"],
                                      st["majority"], st["dominant"], len(profiles) + 1, floor=floor))
        counts[seg["segment_id"]] += 1

    rank = sorted(segments, key=lambda s: (PRIORITIES.index(s["priority"]), -weights[s["segment_id"]]))
    for seg in rank[:budget]:
        add(seg, None)

    reqs = _floor_requirements(floor_list, segments)
    reserve = min(len(reqs), max(0, budget - len(profiles)) // 3)

    def dhondt(limit: int) -> None:
        while len(profiles) < limit:
            open_segs = [s for s in segments if state[s["segment_id"]]["queue"]]
            if not open_segs:
                return
            seg = max(open_segs, key=lambda s: (weights[s["segment_id"]] / (counts[s["segment_id"]] + 1), -PRIORITIES.index(s["priority"])))
            add(seg, state[seg["segment_id"]]["queue"].pop(0))

    dhondt(budget - reserve)
    floors_used: list[dict[str, Any]] = []
    untested: list[dict[str, Any]] = []
    for floor, kind in reqs:
        if _floor_met(floor, kind, profiles):
            continue
        seg, device_id = _floor_segment(floor, kind, segments, weights)
        if len(profiles) >= budget:
            untested.append({"segment_id": seg["segment_id"], "facet": "floor", "reason": f"inclusive floor {floor}" + (f" ({kind})" if kind else "") + " — budget exhausted"})
            continue
        queue = state[seg["segment_id"]]["queue"]
        same = next((f for f in queue if (floor == "left_hand" and f["kind"] == "left_mirror")
                     or (floor == "walking" and f["kind"] == "context" and f["context"].get("mobility") == "walking")
                     or f.get("condition") == floor), None)
        if same is not None and _kind_ok(state[seg["segment_id"]]["top_device"], kind):
            # The segment's own facet satisfies the floor: use it (evidence-backed) instead of a floor-only profile.
            queue.remove(same)
            add(seg, same)
            floors_used.append({"floor": floor, "input": kind, "device_id": profiles[-1]["attributes"]["device_id"], "segment_id": seg["segment_id"], "via_facet": True})
            continue
        add(seg, None, floor=floor, device_id=device_id)
        floors_used.append({"floor": floor, "input": kind, "device_id": device_id, "segment_id": seg["segment_id"], "via_facet": False})
    dhondt(budget)
    for sid, st in state.items():
        for facet in st["queue"]:
            untested.append({"segment_id": sid, "facet": facet["kind"], "reason": facet["reason"]})
    for seg in rank[budget:]:
        untested.append({"segment_id": seg["segment_id"], "facet": "segment", "reason": "segment not tested — budget smaller than the number of segments"})
    for seg in all_segments:
        if seg.get("role", "operator") != "operator":
            untested.append({"segment_id": seg["segment_id"], "facet": "segment", "reason": f"role {seg['role']}: does not operate the product (no profile)"})
        for c in seg.get("conditions") or []:
            if c["condition"] in NOT_SIMULATED:
                untested.append({"segment_id": seg["segment_id"], "facet": "not_simulated", "reason": f"{c['condition']} is not simulated by the models — test with real users or assistive technology"})
    for ex in audience.get("exclusions") or []:
        untested.append({"segment_id": "-", "facet": "exclusion", "reason": f"{ex.get('group')}: {ex.get('why', '')}" + (f" — test instead: {ex['test_instead']}" if ex.get("test_instead") else "")})
    return {
        "schema_version": "ergo-persona-plan.v1",
        "audience_id": audience["audience_id"],
        "budget": budget,
        "floors": floor_list,
        "segments": {sid: {"weight": round(weights[sid], 3), "priority": by_id[sid]["priority"], "profiles": counts[sid]} for sid in counts},
        "floors_used": floors_used,
        "untested": untested,
        "profiles": profiles,
    }


def scenario_stubs(audience: dict[str, Any]) -> list[dict[str, Any]]:
    """ergo-scenario.v1 skeletons for the audience's key tasks (steps and roles left to fill)."""
    errors = validate_audience(audience)
    if errors:
        raise AudienceError("; ".join(errors))
    by_task: dict[str, dict[str, Any]] = {}
    for seg in audience["segments"]:
        if seg.get("role", "operator") != "operator":
            continue  # buyers and people served by staff do not operate the product
        for task in seg.get("tasks") or []:
            entry = by_task.setdefault(task["task_id"], {"task": task, "segments": [], "devices": set()})
            entry["segments"].append(seg["segment_id"])
            entry["devices"].update(seg["devices"])
    stubs = []
    for tid, entry in by_task.items():
        task = entry["task"]
        data = ", ".join(f"{k}={v}" for k, v in task["concrete_data"].items())
        stubs.append({
            "schema_version": "ergo-scenario.v1",
            "scenario_id": f"SC-{tid}",
            "surface": {"kind": audience.get("product", {}).get("surface", "web"), "url": "TODO"},
            "task_goal_ko": f"{task['goal_ko']} (사용할 값: {data})",
            "device_ids": sorted(entry["devices"]),
            "targets": {"primary": [], "destructive": [], "irreversible": [], "critical_message": [], "error_message": [], "status": [], "ad_like": [], "hud": [], "game_control": [], "timed": []},
            "steps": [],
            "timing_windows": [],
            "success": {},
            "audience_ref": {"audience_id": audience["audience_id"], "task_id": tid, "segment_ids": entry["segments"],
                             "criticality": task["criticality"], "frequency": task["frequency"]},
            "todo": ["fill surface.url", "declare element roles", "write steps or run persona agents in serve mode", "declare timing windows", "set success"],
        })
    return stubs


def segments_of(profile_ids: Iterable[str], profiles_by_id: dict[str, dict[str, Any]]) -> list[str]:
    out = {((profiles_by_id.get(pid) or {}).get("audience_ref") or {}).get("segment_id") for pid in profile_ids}
    return sorted(s for s in out if s)


def plan_markdown(plan: dict[str, Any], audience: dict[str, Any]) -> str:
    """Korean table explaining why each persona exists."""
    names = {s["segment_id"]: s["name_ko"] for s in audience["segments"]}
    lines = [f"# 페르소나 구성 근거 ({plan['audience_id']})", "",
             f"예산 {plan['budget']}개. 세그먼트 비중은 배분에만 쓰며 실제 사용자 비율을 뜻하지 않습니다. 각 프로필은 시험 조건이지 평균 사용자가 아닙니다.", "",
             "| 세그먼트 | 우선순위 | 가중치 | 프로필 수 |", "|---|---|---|---|"]
    for sid, row in plan["segments"].items():
        lines.append(f"| {names.get(sid, sid)} ({sid}) | {row['priority']} | {row['weight']} | {row['profiles']} |")
    lines += ["", "| ID | 설명 | 기기 | 이유 | 근거 |", "|---|---|---|---|---|"]
    for p in plan["profiles"]:
        ref = p["audience_ref"]
        lines.append(f"| {p['profile_id']} | {p['label_ko']} | {p['attributes']['device_id']} | {'; '.join(ref['reasons'])} | {', '.join(ref['source_ids']) or '-'} |")
    snippets = [ev for s in audience["segments"] for ev in s.get("evidence") or [] if quote_basis_kind(ev.get("quote_basis")) == "snippet"]
    if snippets:
        lines += ["", f"주의: 증거 {len(snippets)}건은 원문을 열지 못하고 검색 결과 발췌로만 인용했습니다(quote_basis=snippet). 원문으로 확인하기 전에는 근거로 쓰지 마세요."]
    unrecorded = [ev for s in audience["segments"] for ev in s.get("evidence") or []
                  if ev.get("kind") in ("statistic", "official", "firsthand") and not ev.get("quote_basis")]
    if unrecorded:
        lines += ["", f"주의: 인용 증거 {len(unrecorded)}건은 원문을 읽었는지(quote_basis)가 기록되지 않았습니다."]
    if plan["untested"]:
        lines += ["", "## 예산 밖이라 시험하지 않은 조건", ""]
        for u in plan["untested"]:
            lines.append(f"- {names.get(u['segment_id'], u['segment_id'])}: {u['reason']}")
    return "\n".join(lines) + "\n"


def clone(profile: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(profile)
