"""Safe typed capture flags, retaining candidates without their original text."""
from __future__ import annotations
from .canonical import digest, ordered

BOOL_FLAGS = ("secondhand", "unclear_context", "count_only", "seller_managed", "own_brand",
              "community_modelled_demographics", "protected_attribute_cue", "polarity_uncertain")
HITS = ("promotion_hits", "incentive_hits", "virtual_person_hits", "injection_flags")


def empty():
    return {**{k: False for k in BOOL_FLAGS}, "lead_kind": "full_text", **{k: [] for k in HITS}}


def captured(result):
    flags = empty()
    for target, source, default in (("promotion_hits", "promotion_hits", "disclosure"),
                                     ("incentive_hits", "incentive_flags", "reward_unspecified"),
                                     ("virtual_person_hits", "virtual_person_flags", "disclosed_virtual_person")):
        for hit in result.get(source) or []:
            code = hit.get("kind", default)
            if target == "incentive_hits" and code not in {"seller_event", "seller_notice", "platform_points", "reward_unspecified"}:
                code = "reward_unspecified"
            flags[target].append(dict(id="F-" + digest([target, hit])[:16], code=code, position=hit.get("position", "unknown")))
    for code in (result.get("injection") or {}).get("signals", []):
        flags["injection_flags"].append(dict(id="F-" + digest(["injection", code])[:16], code=code, position="unknown"))
    return ordered(flags)


def combine(*inputs):
    out = empty()
    for value in inputs:
        if not value:
            continue
        for key in BOOL_FLAGS:
            out[key] = out[key] or value.get(key, False)
        if value.get("lead_kind", "full_text") != "full_text":
            out["lead_kind"] = value["lead_kind"]
        for key in HITS:
            out[key].extend(value.get(key, []))
    return ordered(out)


def metadata(result):
    robots = result.get("robots") or {}
    return dict(content_sha256=result.get("content_sha256"),
                flags=captured(result), retention_until=result.get("retention_until"),
                access_basis=result.get("access_basis"), context=result.get("context", "anonymous"),
                final_url=result.get("final_url"),
                access=dict(rung=result.get("rung"), presentation=result.get("presentation"),
                            verdict=result.get("verdict"), stop_class=result.get("stop_class") or "none",
                            fetched_at=result.get("fetched_at"),
                            robots=dict(decision=robots.get("decision"), status=robots.get("robots_status", robots.get("status"))),
                            context=result.get("context", "anonymous"), terms=None))
