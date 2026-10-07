"""Canonical research JSON and conservative resource identities (no network)."""
from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote, urlsplit, urlunsplit


class EngineError(ValueError):
    def __init__(self, code, reason, exit_code=2, location="input", next_step="Correct the input and rerun."):
        super().__init__(reason)
        self.exit_code = exit_code
        # Diagnostics never echo a rejected identifier embedded in a field path.
        from . import privacy
        if not isinstance(location,str) or privacy.scrub(location)[0]!=location:
            location="input"
        self.issue = dict(code=code, location=location, reason=reason, next_step=next_step)


def normalize(value):
    if isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeError as exc:
            raise EngineError("invalid_unicode", "Input contains invalid Unicode.") from exc
        return unicodedata.normalize("NFC", value)
    if value is None or type(value) in (bool, int):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise EngineError("invalid_number", "Numbers must be finite.")
        return int(value) if value.is_integer() else value
    if isinstance(value, list):
        return [normalize(x) for x in value]
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if not isinstance(k, str):
                raise EngineError("invalid_key", "Object keys must be strings.")
            key = normalize(k)
            if key in out:
                raise EngineError("duplicate_key", "Normalized object keys collide.")
            out[key] = normalize(v)
        return out
    raise EngineError("invalid_json", "Input contains a non-JSON value.")


def canonical(value):
    return json.dumps(normalize(value), ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def byte_digest(value):
    return hashlib.sha256(value).hexdigest()


def loads(raw):
    def pairs(items):
        out = {}
        for k, v in items:
            if k in out:
                raise EngineError("duplicate_key", "JSON contains duplicate object keys.")
            out[k] = v
        return out
    def invalid(_):
        raise EngineError("invalid_number", "Numbers must be finite.")
    try:
        return normalize(json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid))
    except (ValueError, UnicodeError, RecursionError) as exc:
        if isinstance(exc, EngineError):
            raise
        raise EngineError("invalid_json", "Input is not valid UTF-8 JSON.") from exc


def quote_text(text):
    return " ".join(normalize(text).split())


def timestamp(value, *, bare_date=False):
    try:
        if bare_date and len(value) == 10:
            return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc) + timedelta(days=1)
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if date.tzinfo is None:
            raise ValueError()
        return date.astimezone(timezone.utc)
    except (TypeError, ValueError, AttributeError) as exc:
        raise EngineError("invalid_date", "Date or timestamp is invalid.") from exc


_TRACKING = re.compile(r"^(utm_.*|fbclid|gclid|dclid|msclkid|mc_cid|mc_eid)$", re.I)
_UNRESERVED = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")


def resource_url(url):
    from . import privacy
    try:
        parts = urlsplit(url)
        if parts.scheme.lower() not in ("http", "https") or not parts.hostname or parts.username or parts.password:
            raise ValueError()
        host = parts.hostname.rstrip(".").encode("idna").decode().lower()
        port = parts.port
        if ":" in host:
            host = "[" + host + "]"
        if port and (parts.scheme.lower(), port) not in (("http", 80), ("https", 443)):
            host += ":" + str(port)
        def escapes(x):
            if re.search(r"%(?![0-9A-Fa-f]{2})", x):
                raise ValueError()
            return re.sub(r"%([0-9A-Fa-f]{2})", lambda m: chr(int(m[1], 16)) if chr(int(m[1], 16)) in _UNRESERVED else "%" + m[1].upper(), x)
        query = []
        for pair in parts.query.split("&") if parts.query else []:
            name = unquote(pair.split("=", 1)[0])
            if privacy._is_secret(name):
                raise EngineError("secret_url", "Secret URL parameters cannot establish identity.")
            if not _TRACKING.fullmatch(name):
                query.append(escapes(pair))
        return urlunsplit((parts.scheme.lower(), host, escapes(parts.path), "&".join(query), ""))
    except (ValueError, UnicodeError) as exc:
        if isinstance(exc, EngineError):
            raise
        raise EngineError("invalid_url", "A resource URL is invalid or unsafe.") from exc


class Ids:
    def __init__(self, hash_fn=digest):
        self.identities = {}
        self.hash_fn = hash_fn

    def make(self, prefix, identity):
        full = self.hash_fn(identity)
        short = prefix + "-" + full[:8]
        encoded = canonical(identity)
        if short in self.identities and self.identities[short] != encoded:
            raise EngineError("id_collision", "Unequal identity tuples share an ID.")
        self.identities[short] = encoded
        return short, full


def claim_identity(run_id, claim):
    values = sorted(({"join": x["join"], "value": x["value"]} for x in claim.get("audience_values", [])), key=canonical)
    return [run_id, claim["claim_kind"], quote_text(claim["statement"]), claim["subject"], claim["scope"], values]


REF_ARRAYS = frozenset({"evidence_ids", "research_support_evidence_ids", "research_context_evidence_ids",
                       "context_evidence_ids", "counter_evidence_ids", "observation_ids", "persona_ids", "claim_ids",
                       "scenario_priorities", "basis_evidence_ids", "flag_ids", "call_ids", "read_source_ids",
                       "replaces_call_ids", "denominator_evidence_ids", "motivation_claim_ids", "aliases"})


def ordered(value, key=None):
    if isinstance(value, dict):
        return {k: ordered(v, k) for k, v in value.items()}
    if isinstance(value, list):
        out = [ordered(x) for x in value]
        if key in REF_ARRAYS or key in {"promotion_hits", "incentive_hits", "virtual_person_hits", "injection_flags"}:
            return [loads(x) for x in sorted(set(canonical(x) for x in out))]
        if key == "captures":
            return sorted(out, key=lambda x: (x["metadata"]["observed_at"], x["capture_ref"]))
        if key == "audience_values":
            return sorted(out, key=lambda x: canonical(x["join"]))
        return out
    return value


def input_bundle(bundle):
    """Only known derived fields are removed; proposed and original evidence stay hashed."""
    import copy
    out = ordered(copy.deepcopy(bundle))
    for name, records in out["records"].items():
        records.sort(key=lambda x: x["id"])
        if name == "claims":
            for c in records:
                c.pop("verification_status", None)
                c["epistemic_status"] = c.get("research_epistemic_status", c.get("epistemic_status"))
                c["evidence_ids"] = c.get("research_support_evidence_ids", c.get("evidence_ids", []))
                c["context_evidence_ids"] = c.get("research_context_evidence_ids", c.get("context_evidence_ids", []))
    return out
