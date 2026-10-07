"""Validator for the explicitly used JSON Schema subset, not a general replacement.

Unsupported schema keywords fail closed. Semantic links live in contracts.py.
"""
from __future__ import annotations

import math
import re
from typing import Any
from .io import canonical

KEYS = {"$schema", "$id", "$defs", "$ref", "title", "description", "type", "const",
        "enum", "required", "properties", "additionalProperties", "items", "minItems",
        "maxItems", "uniqueItems", "minLength", "maxLength", "minimum", "maximum", "pattern"}


def validate(value: Any, schema: dict, root: dict | None = None, path: str = "$") -> list[str]:
    root = schema if root is None else root
    errors: list[str] = []
    unsupported = set(schema) - KEYS
    if unsupported:
        return [f"{path}: unsupported schema keywords {sorted(unsupported)}"]
    if "$ref" in schema:
        ref = schema["$ref"]
        if not ref.startswith("#/$defs/") or ref[8:] not in root.get("$defs", {}):
            return [f"{path}: unsupported/missing schema reference {ref}"]
        return validate(value, root["$defs"][ref[8:]], root, path)
    if "type" in schema:
        kinds = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        matches = {"object": isinstance(value, dict), "array": isinstance(value, list),
                   "string": isinstance(value, str), "boolean": type(value) is bool,
                   "integer": type(value) is int, "number": type(value) in (int, float),
                   "null": value is None}
        if not any(matches.get(kind, False) for kind in kinds):
            return [f"{path}: expected {kinds}"]
    if "const" in schema and (type(value) is not type(schema["const"]) or value != schema["const"]):
        errors.append(f"{path}: must equal {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: invalid enum value")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}.{key}: required")
        props = schema.get("properties", {})
        for key, child in value.items():
            if key in props:
                errors.extend(validate(child, props[key], root, f"{path}.{key}"))
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}.{key}: unexpected field")
    if isinstance(value, list):
        if not schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", 10000):
            errors.append(f"{path}: invalid array size")
        if schema.get("uniqueItems"):
            try:
                if len({canonical(x) for x in value}) != len(value):
                    errors.append(f"{path}: duplicate items")
            except (ValueError, TypeError):
                errors.append(f"{path}: non-JSON item")
        for i, child in enumerate(value):
            errors.extend(validate(child, schema.get("items", {}), root, f"{path}[{i}]"))
    if isinstance(value, str):
        if not schema.get("minLength", 0) <= len(value) <= schema.get("maxLength", 100000):
            errors.append(f"{path}: invalid string length")
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            errors.append(f"{path}: invalid string pattern")
    if type(value) in (int, float):
        if (type(value) is float and not math.isfinite(value)) or not schema.get("minimum", -math.inf) <= value <= schema.get("maximum", math.inf):
            errors.append(f"{path}: invalid number range")
    return errors
