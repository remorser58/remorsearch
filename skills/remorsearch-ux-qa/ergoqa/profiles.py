"""Ergonomic persona profiles (ergo-profile.v1).

A profile is a bounded test input. Ergonomic attributes that are not present in a
persona dataset (handedness, grip, hand size, vision, motor, device) are scenario
assumptions and are listed in ``assumption_fields``. Coverage sampling guarantees
that important strata appear at least once; it is not a population estimate.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from typing import Any, Iterable

from . import params

SCHEMA_VERSION = "ergo-profile.v1"

HANDEDNESS = ("right", "left", "mixed")
GRIPS = (
    "one_hand_right", "one_hand_left", "cradle_right", "cradle_left", "two_thumbs",
    "mouse_right", "mouse_left", "keyboard_only", "gamepad", "remote",
)
TOUCH_GRIPS = ("one_hand_right", "one_hand_left", "cradle_right", "cradle_left", "two_thumbs")
AGE_BANDS = ("10s", "20s", "30s", "40s", "50s", "60s", "70s+")
CVD = ("none", "protan", "deutan", "tritan")
TREMOR = ("none", "mild", "moderate")
MOBILITY = ("seated", "walking", "transit")
LIGHTING = ("indoor", "bright_sun", "dark")
FAMILIARITY = ("first_use", "returning", "expert")
ASSUMPTION_FIELDS = (
    "handedness", "grip", "thumb_length_mm", "hand_percentile", "device_id", "orientation",
    "vision", "motor", "context", "reaction_time_ms",
)

# Coverage plan. For every device the core input strata are filled first; then
# condition strata are added round-robin across devices, alternating the one-hand
# side on touch devices so both mirror frames meet every condition.
CORE_TOUCH_STRATA: tuple[tuple[str, dict[str, Any]], ...] = (
    ("right_one_hand", {"handedness": "right", "grip": "one_hand_right"}),
    ("left_one_hand", {"handedness": "left", "grip": "one_hand_left"}),
    ("two_thumbs", {"grip": "two_thumbs"}),
    ("cradle", {"grip": "cradle_right"}),
)
LANDSCAPE_STRATA: tuple[tuple[str, dict[str, Any]], ...] = (
    ("two_thumbs_right", {"handedness": "right", "grip": "two_thumbs"}),
    ("two_thumbs_left", {"handedness": "left", "grip": "two_thumbs"}),
)
TABLET_STRATA: tuple[tuple[str, dict[str, Any]], ...] = (
    ("two_thumbs", {"handedness": "right", "grip": "two_thumbs"}),
    ("cradle_right", {"handedness": "right", "grip": "cradle_right"}),
    ("cradle_left", {"handedness": "left", "grip": "cradle_left"}),
)
CORE_POINTER_STRATA: tuple[tuple[str, dict[str, Any]], ...] = (
    ("mouse_right", {"handedness": "right", "grip": "mouse_right"}),
    ("mouse_left", {"handedness": "left", "grip": "mouse_left"}),
    ("keyboard_only", {"grip": "keyboard_only"}),
)
# Strata for the fallback plan (no audience file). Kept: conditions whose removal lost
# unique seeded defects on the development suites (deutan, presbyopia, walking, 70s+,
# small hand) and tremor, an edge condition with a model. Removed after ablation
# (docs/validation/experiments/decisions.md): bright sun (0 unique, +31 findings, PC-05
# is a hypothesis), first use (no deterministic check reads familiarity), protan and
# large hand (0 unique). Audience composition adds them when the audience needs them.
# Low vision was added in round 12 so that a profile with low acuity exists: on dev-2,
# RF-01 found a timer cut away at 320 px (400 % zoom) but no swarm profile had the
# condition, and nothing else changed on the development suites. Its model reuses the
# presbyopic text thresholds and the older-adult noticing scale; magnification itself
# is covered by the profile-independent reflow and clipping checks (RF-01, LY-01), not
# simulated per profile.
CONDITION_STRATA: tuple[tuple[str, dict[str, Any]], ...] = (
    ("cvd_deutan", {"vision.cvd": "deutan"}),
    ("presbyopia_60s", {"age_band": "60s", "vision.presbyopia": True}),
    ("tremor", {"motor.tremor": "mild"}),
    ("walking", {"context.mobility": "walking", "context.free_hands": 1}),
    ("low_vision", {"vision.acuity": "low"}),
    ("70s_plus", {"age_band": "70s+", "vision.presbyopia": True}),
    ("small_hand", {"hand_percentile": 5}),
)
# Strata that change nothing on a pointer device: mobility, hand size and tremor feed
# only the touch model (touch_sigma_multiplier, thumb reach); on four desktop
# recordings the tremor profile's observations equalled the base persona's. A pointer
# device skips them, so its 7 slots cover every condition its checks read (round 12:
# no change on the dev suites).
TOUCH_ONLY_STRATA = frozenset({"walking", "small_hand", "tremor"})
COVERAGE_STRATA = CORE_TOUCH_STRATA + CORE_POINTER_STRATA + CONDITION_STRATA


def _weighted(rng: random.Random, table: dict[str, float]) -> str:
    total = sum(table.values())
    pick = rng.random() * total
    acc = 0.0
    for key, weight in table.items():
        acc += weight
        if pick <= acc:
            return key
    return next(iter(table))


def _set_path(obj: dict[str, Any], dotted: str, value: Any) -> None:
    parts = dotted.split(".")
    cur = obj
    for part in parts[:-1]:
        cur = cur.setdefault(part, {})
    cur[parts[-1]] = value


def _get_path(obj: dict[str, Any], dotted: str) -> Any:
    cur: Any = obj
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _grip_for(handedness: str, input_kind: str, rng: random.Random) -> str:
    if input_kind == "mouse":
        return "mouse_left" if handedness == "left" and rng.random() < params.LEFT_HANDERS_MOUSE_LEFT_SHARE else "mouse_right"
    if input_kind == "gamepad":
        return "gamepad"
    if input_kind == "remote":
        return "remote"
    if input_kind == "keyboard":
        return "keyboard_only"
    grip = _weighted(rng, params.MOBILE_GRIP_SHARE)
    side = "left" if handedness == "left" else "right"
    if grip == "one_hand":
        return f"one_hand_{side}"
    if grip == "cradle":
        return f"cradle_{side}"
    return "two_thumbs"


def thumb_length_for_percentile(percentile: int, sex: str | None = None) -> float:
    """Thumb length (mm) at a hand-size percentile using the params table."""
    table = params.THUMB_LENGTH_MM
    mean, sd = table.get(sex or "all", table["all"])
    z = {1: -2.326, 5: -1.645, 10: -1.282, 25: -0.674, 50: 0.0, 75: 0.674, 90: 1.282, 95: 1.645, 99: 2.326}
    return round(mean + z.get(int(percentile), 0.0) * sd, 1)


def _base_profile(index: int, rng: random.Random, device_id: str, input_kind: str, orientation: str) -> dict[str, Any]:
    age_band = _weighted(rng, params.AGE_BAND_SHARE_KR)
    left = params.LEFT_SHARE_BY_AGE_KR.get(age_band, params.HANDEDNESS_SHARE_KR["left"])
    mixed = params.HANDEDNESS_SHARE_KR["mixed"]
    handedness = _weighted(rng, {"right": max(0.0, 1.0 - left - mixed), "left": left, "mixed": mixed})
    percentile = rng.choice((25, 50, 50, 75))
    cvd = "none"
    # Age stays context (spec: an age band never switches a sensory/motor condition).
    # Presbyopia is an explicit input: only a condition stratum, a persona record that
    # declares it, or a caller sets it; 50s+ demographics alone never imply it.
    presbyopia = False
    profile = {
        "schema_version": SCHEMA_VERSION,
        "profile_id": f"EP-{index:02d}",
        "origin": "stratified_coverage",
        "persona_ref": None,
        "label_ko": "",
        "attributes": {
            "age_band": age_band,
            "handedness": handedness,
            "grip": _grip_for(handedness, input_kind, rng),
            "thumb_length_mm": thumb_length_for_percentile(percentile),
            "hand_percentile": percentile,
            "device_id": device_id,
            "orientation": orientation,
            "vision": {
                "acuity": "normal",
                "presbyopia": presbyopia,
                "cvd": cvd,
                "cvd_severity": 1.0,
                "viewing_distance_mm": 0,
            },
            "motor": {"tremor": "none", "touch_sigma_multiplier": 1.0, "touch_sigma_mm": 0.0},
            "context": {"mobility": "seated", "lighting": "indoor", "free_hands": 2 if input_kind == "touch" else 2, "interruptions": False},
            "cognition": {"familiarity": "returning", "time_pressure": "low", "reading_wpm_ko": 0},
            "reaction_time_ms": 0,
        },
        "assumption_fields": list(ASSUMPTION_FIELDS),
        "base_rate_refs": dict(params.BASE_RATE_REFS),
    }
    return profile


def tablet_like(device: Any) -> bool:
    """Handheld tablets and unfolded foldables: held at the sides or set down (HGR-9)."""
    mm = getattr(device, "physical_mm", None)
    return bool(mm) and min(mm) > 120.0 and getattr(device, "input", "") == "touch"


def _finalise(profile: dict[str, Any], device: Any) -> dict[str, Any]:
    attrs = profile["attributes"]
    if tablet_like(device) and attrs["grip"].startswith("one_hand"):
        # Nobody operates a tablet with the thumb of the holding hand: the one-hand
        # stratum becomes "hold with one hand, tap with the other" on the same side.
        attrs["grip"] = "cradle_left" if attrs["grip"].endswith("_left") else "cradle_right"
        attrs["context"]["free_hands"] = 0
    grip = attrs["grip"]
    if grip in ("one_hand_right", "one_hand_left"):
        attrs["context"]["free_hands"] = 1
    if attrs["handedness"] == "left" and grip in ("one_hand_right", "cradle_right", "mouse_right"):
        pass  # a left-hander using the right hand is allowed (e.g. mouse); keep explicit
    percentile = int(attrs.get("hand_percentile", 50))
    attrs["thumb_length_mm"] = thumb_length_for_percentile(percentile)
    vision = attrs["vision"]
    if not vision.get("viewing_distance_mm"):
        vision["viewing_distance_mm"] = int(getattr(device, "viewing_distance_mm", 0) or params.DEFAULT_VIEWING_DISTANCE_MM.get(getattr(device, "form_factor", "phone"), 350))
    motor = attrs["motor"]
    motor["touch_sigma_multiplier"] = round(touch_sigma_multiplier(profile), 3)
    motor["touch_sigma_mm"] = round(effective_touch_sigma_mm(profile), 3)
    cognition = attrs["cognition"]
    if not cognition.get("reading_wpm_ko"):
        cognition["reading_wpm_ko"] = params.reading_rate_for_age(attrs["age_band"])
    if not attrs.get("reaction_time_ms"):
        attrs["reaction_time_ms"] = params.choice_reaction_ms_for_age(attrs["age_band"])
    profile["label_ko"] = label_ko(profile)
    return profile


def touch_sigma_multiplier(profile: dict[str, Any]) -> float:
    """SD multiplier on the Bi & Zhai dual-Gaussian tap model for a profile.

    Multipliers come from params.TOUCH_SIGMA_MULT and are declared assumptions
    for sensitivity analysis (docs/human-factors/motor-pointing.md MP-11/12).
    """
    attrs = profile["attributes"]
    factors = []
    grip = attrs.get("grip", "")
    if grip.startswith("one_hand") or grip == "two_thumbs":
        factors.append(params.TOUCH_SIGMA_MULT["one_hand_thumb"])
    tremor = _get_path(attrs, "motor.tremor") or "none"
    factors.append(params.TOUCH_SIGMA_MULT.get(f"tremor_{tremor}", 1.0))
    mobility = _get_path(attrs, "context.mobility") or "seated"
    factors.append(params.TOUCH_SIGMA_MULT.get(f"mobility_{mobility}", 1.0))
    age = attrs.get("age_band", "30s")
    factors.append(params.TOUCH_SIGMA_MULT.get(f"age_{age}", 1.0))
    if params.TOUCH_SIGMA_COMBINE == "additive":
        return math.sqrt(1.0 + sum(f * f - 1.0 for f in factors))
    k = 1.0
    for f in factors:
        k *= f
    return k


def effective_touch_sigma_mm(profile: dict[str, Any]) -> float:
    """Absolute-term tap SD (mm) for display: base x-term times the multiplier."""
    return params.TOUCH_SIGMA_BASE_MM * touch_sigma_multiplier(profile)


def label_ko(profile: dict[str, Any]) -> str:
    a = profile["attributes"]
    hand = {"right": "오른손잡이", "left": "왼손잡이", "mixed": "양손잡이"}.get(a["handedness"], a["handedness"])
    grip = {
        "one_hand_right": "오른손 한 손 파지", "one_hand_left": "왼손 한 손 파지",
        "cradle_right": "왼손으로 받치고 오른손 검지", "cradle_left": "오른손으로 받치고 왼손 검지",
        "two_thumbs": "양손 엄지", "mouse_right": "오른손 마우스", "mouse_left": "왼손 마우스",
        "keyboard_only": "키보드 전용", "gamepad": "게임패드", "remote": "리모컨",
    }.get(a["grip"], a["grip"])
    parts = [a["age_band"], hand, grip]
    v = a.get("vision", {})
    if v.get("cvd") and v["cvd"] != "none":
        parts.append({"protan": "적색약", "deutan": "녹색약", "tritan": "청색약"}[v["cvd"]])
    if v.get("acuity") == "low":
        parts.append("저시력")
    elif v.get("acuity") == "reduced":
        parts.append("시력 저하")
    if v.get("presbyopia"):
        parts.append("노안")
    if a.get("motor", {}).get("tremor") not in (None, "none"):
        parts.append("손떨림")
    ctx = a.get("context", {})
    if ctx.get("mobility") == "walking":
        parts.append("걷는 중")
    if ctx.get("mobility") == "transit":
        parts.append("대중교통 이동 중")
    if ctx.get("lighting") == "bright_sun":
        parts.append("햇빛 아래")
    if a.get("cognition", {}).get("familiarity") == "first_use":
        parts.append("첫 사용")
    return " · ".join(parts)


def core_strata(device: Any, orientation: str | None = None) -> tuple[tuple[str, dict[str, Any]], ...]:
    """Input strata for a device: phone portrait grips, landscape two-thumb, tablet side grips, pointer."""
    if device.input == "touch":
        if tablet_like(device):
            return TABLET_STRATA
        if (orientation or device.orientation) == "landscape":
            return LANDSCAPE_STRATA
        return CORE_TOUCH_STRATA
    return CORE_POINTER_STRATA if device.input in ("mouse", "keyboard") else ()


def coverage_plan(devices: list[Any], count: int, orientation: str | None = None) -> list[tuple[Any, str | None, dict[str, Any]]]:
    """Ordered (device, stratum, overrides) slots for stratified coverage."""
    plan: list[tuple[Any, str | None, dict[str, Any]]] = []
    for device in devices:
        core = core_strata(device, orientation)
        for name, overrides in core:
            plan.append((device, name, dict(overrides)))
    index = 0
    for name, overrides in CONDITION_STRATA:
        eligible = [d for d in devices if d.input == "touch" or name not in TOUCH_ONLY_STRATA]
        if not eligible:
            continue
        device = eligible[index % len(eligible)]
        slot = dict(overrides)
        if device.input == "touch":
            left = (index // len(devices)) % 2 == 1
            landscape = (orientation or device.orientation) == "landscape"
            slot.setdefault("grip", "two_thumbs" if landscape else ("one_hand_left" if left else "one_hand_right"))
            slot.setdefault("handedness", "left" if left else "right")
        plan.append((device, name, slot))
        index += 1
    while len(plan) < count:
        plan.append((devices[len(plan) % len(devices)], None, {}))
    return plan[:count]


def sample_profiles(
    count: int,
    seed: int,
    device_ids: Iterable[str],
    strategy: str = "stratified_coverage",
    persona_records: list[dict[str, Any]] | None = None,
    orientation: str | None = None,
) -> list[dict[str, Any]]:
    """Deterministically sample ergonomic profiles.

    ``stratified_coverage`` fills the coverage plan (core input strata per device,
    then condition strata) before base-rate sampling; ``base_rate_sample`` only
    samples from base rates. Base rates choose plausible combinations and are
    never reported as population estimates.
    """
    from .devices import get_device

    if count < 1:
        raise ValueError("count must be >= 1")
    if strategy not in ("stratified_coverage", "base_rate_sample"):
        raise ValueError(f"unknown strategy {strategy!r}")
    devices = [get_device(d) for d in device_ids]
    if not devices:
        raise ValueError("at least one device is required")
    rng = random.Random(seed)
    if strategy == "stratified_coverage":
        plan = coverage_plan(devices, count, orientation)
    else:
        plan = [(devices[i % len(devices)], None, {}) for i in range(count)]
    profiles: list[dict[str, Any]] = []
    for index, (device, stratum_name, overrides) in enumerate(plan):
        # Default to the device's natural orientation (portrait phones/tablets,
        # landscape desktop/TV/handheld console).
        profile = _base_profile(index + 1, rng, device.id, device.input, orientation or device.orientation)
        attrs = profile["attributes"]
        if stratum_name is None:
            profile["origin"] = "base_rate_sample"
            if rng.random() < params.CVD_MALE_SHARE_KR / 2:
                attrs["vision"]["cvd"] = _weighted(rng, params.CVD_TYPE_SHARE)
            attrs["context"]["mobility"] = _weighted(rng, {"seated": 0.7, "walking": 0.15, "transit": 0.15})
            if attrs["context"]["mobility"] != "seated" and device.input == "touch":
                attrs["grip"] = "one_hand_left" if attrs["handedness"] == "left" else "one_hand_right"
        else:
            for key, value in overrides.items():
                _set_path(attrs, key, value)
            if "grip" in overrides and "handedness" not in overrides and overrides["grip"] != "two_thumbs":
                attrs["handedness"] = "left" if overrides["grip"].endswith("_left") else attrs["handedness"]
            profile["coverage_stratum"] = stratum_name
        if device.input == "touch" and profile["attributes"]["orientation"] == "landscape" and not tablet_like(device) \
                and attrs["grip"].startswith(("one_hand", "cradle")):
            # Landscape phone use (games, video) is two-thumb; keep the stratum's other conditions.
            attrs["grip"] = "two_thumbs"
        if persona_records and index < len(persona_records):
            record = persona_records[index]
            profile["persona_ref"] = {
                "dataset": record.get("dataset", "unknown"),
                "revision": record.get("revision", "unknown"),
                "record_id": str(record.get("record_id", record.get("uuid", index))),
            }
            if record.get("age_band") in AGE_BANDS and "age_band" not in overrides:
                attrs["age_band"] = record["age_band"]
            # Explicit sensory input does not require a demographic field. A
            # declared coverage condition takes precedence over a linked record.
            if "vision.presbyopia" not in overrides and isinstance(record.get("presbyopia"), bool):
                attrs["vision"]["presbyopia"] = record["presbyopia"]
        _finalise(profile, device)
        profiles.append(profile)
    return profiles


def validate_profile(profile: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(profile, dict):
        return ["profile must be an object"]
    if profile.get("schema_version") != SCHEMA_VERSION:
        errors.append("schema_version must be ergo-profile.v1")
    if not isinstance(profile.get("profile_id"), str) or not profile["profile_id"]:
        errors.append("profile_id is required")
    attrs = profile.get("attributes")
    if not isinstance(attrs, dict):
        return errors + ["attributes must be an object"]
    checks = (
        ("handedness", HANDEDNESS), ("grip", GRIPS), ("age_band", AGE_BANDS),
    )
    for key, allowed in checks:
        if attrs.get(key) not in allowed:
            errors.append(f"attributes.{key} must be one of {', '.join(allowed)}")
    if attrs.get("orientation") not in ("portrait", "landscape"):
        errors.append("attributes.orientation must be portrait or landscape")
    if not isinstance(attrs.get("device_id"), str):
        errors.append("attributes.device_id is required")
    for key in ("thumb_length_mm", "reaction_time_ms"):
        value = attrs.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
            errors.append(f"attributes.{key} must be a positive number")
    vision = attrs.get("vision")
    if not isinstance(vision, dict) or vision.get("cvd") not in CVD:
        errors.append("attributes.vision.cvd must be one of " + ", ".join(CVD))
    motor = attrs.get("motor")
    if not isinstance(motor, dict) or motor.get("tremor") not in TREMOR:
        errors.append("attributes.motor.tremor must be one of " + ", ".join(TREMOR))
    context = attrs.get("context")
    if not isinstance(context, dict) or context.get("mobility") not in MOBILITY or context.get("lighting") not in LIGHTING:
        errors.append("attributes.context mobility/lighting invalid")
    cognition = attrs.get("cognition")
    if not isinstance(cognition, dict) or cognition.get("familiarity") not in FAMILIARITY:
        errors.append("attributes.cognition.familiarity invalid")
    if not isinstance(profile.get("assumption_fields"), list):
        errors.append("assumption_fields must be an array")
    return errors


def profile_index(profiles: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Validate identities before any caller can overwrite a profile in a map."""
    indexed: dict[str, dict[str, Any]] = {}
    for profile in profiles:
        errors = validate_profile(profile)
        if errors:
            raise ValueError("invalid profile: " + "; ".join(errors))
        pid = profile["profile_id"]
        if pid in indexed:
            raise ValueError(f"duplicate profile id {pid!r}")
        indexed[pid] = profile
    return indexed


def profile_fingerprint(profile: dict[str, Any]) -> str:
    keys = sorted(_flatten_keys(profile))
    return hashlib.sha256(json.dumps(keys).encode()).hexdigest()


def _flatten_keys(obj: Any, prefix: str = "") -> list[str]:
    if isinstance(obj, dict):
        out: list[str] = []
        for key, value in obj.items():
            out.extend(_flatten_keys(value, f"{prefix}.{key}" if prefix else key))
        return out
    return [prefix]


def flatten_condition(condition: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """Flatten nested conditions ({"vision": {"cvd": "deutan"}}) to dotted keys."""
    flat: dict[str, Any] = {}
    for key, value in condition.items():
        dotted = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            flat.update(flatten_condition(value, dotted))
        else:
            flat[dotted] = value
    return flat


def matches_condition(profile: dict[str, Any], condition: dict[str, Any]) -> bool:
    """True when every (dotted or nested) key in condition equals the profile attribute."""
    attrs = profile.get("attributes", {})
    for key, expected in flatten_condition(condition).items():
        actual = _get_path(attrs, key)
        if isinstance(expected, (list, tuple)):
            if actual not in expected:
                return False
        elif actual != expected:
            return False
    return True
