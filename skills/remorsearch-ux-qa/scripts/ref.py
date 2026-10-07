#!/usr/bin/env python3
"""Bounded, offline Markdown section and Korean channel lookup."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path
import re
import sys
import unicodedata

SKILL_ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 8192


@dataclass
class Heading:
    level: int
    title: str
    section_id: str
    aliases: tuple[str, ...]
    start: int
    end: int
    path: tuple[str, ...]


def slug(title: str) -> str:
    title = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", title)
    title = re.sub(r"<[^>]*>|\{#[^}]+\}", "", title)
    title = re.sub(r"[^\w\s-]", "", unicodedata.normalize("NFC", title).casefold())
    return re.sub(r"[-\s]+", "-", title).strip("-") or "section"


def heading_ids(title: str, anchor: str | None) -> list[str]:
    explicit = re.search(r"\{#([^\s}]+)\}\s*$", title)
    numbered = re.match(r"^(\d+(?:\.\d+)*(?:[a-zA-Z])?)(?:[.)])?(?=\s|$)", title)
    code_id = re.match(r"^`([^`]+)`(?:\s|$)", title)
    named = re.match(r"^([A-Z]+\d+(?:[a-zA-Z])?)(?=\s|$)", title)
    choices = [explicit.group(1) if explicit else anchor]
    choices.extend(m.group(1) for m in (numbered, code_id, named) if m)
    return list(dict.fromkeys(x for x in choices if x))


def parse_headings(markdown: str) -> list[Heading]:
    """ATX/Setext headings, explicit anchors, numeric and literal IDs; fences excluded."""
    lines = markdown.splitlines(keepends=True)
    offsets, offset = [], 0
    for line in lines:
        offsets.append(offset)
        offset += len(line)
    found: list[Heading] = []
    stack: list[Heading] = []
    counts: Counter = Counter()
    fence_char, fence_len = "", 0
    anchor = None
    frontmatter = bool(lines and lines[0].strip() == "---")
    for i, line in enumerate(lines):
        raw = line.rstrip("\r\n")
        if frontmatter:
            if i and raw.strip() == "---":
                frontmatter = False
            continue
        fence = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", raw)
        if fence_char:
            if fence and fence.group(1)[0] == fence_char and len(fence.group(1)) >= fence_len and not fence.group(2).strip():
                fence_char, fence_len = "", 0
            continue
        if fence:
            fence_char, fence_len = fence.group(1)[0], len(fence.group(1))
            continue
        html_anchor = re.fullmatch(r"\s*<a\s+(?:id|name)=[\"']([^\"']+)[\"']\s*>\s*</a>\s*", raw)
        if html_anchor:
            anchor = html_anchor.group(1)
            continue
        atx = re.match(r"^ {0,3}(#{1,6})[ \t]+(.+?)\s*$", raw)
        start = offsets[i]
        if atx:
            level = len(atx.group(1))
            title = re.sub(r"\s+#+\s*$", "", atx.group(2))
        elif re.fullmatch(r" {0,3}(?:=+|-+)[ \t]*", raw) and i and lines[i - 1].strip():
            previous = lines[i - 1].strip()
            if lines[i - 1].startswith(("    ", "\t")) or re.match(r"^(?:[#>|]|[-*+]\s|`{3,}|~{3,}|<a\s)", previous):
                continue
            level, title, start = (1 if raw.lstrip().startswith("=") else 2), previous, offsets[i - 1]
        else:
            if raw.strip():
                anchor = None
            continue
        title = unicodedata.normalize("NFC", title)
        base_slug = slug(title)
        counts[base_slug] += 1
        unique_slug = base_slug if counts[base_slug] == 1 else f"{base_slug}-{counts[base_slug]}"
        explicit_ids = heading_ids(title, anchor)
        aliases = tuple(dict.fromkeys([*explicit_ids, unique_slug]))
        while stack and stack[-1].level >= level:
            stack.pop().end = start
        path = tuple(h.title for h in stack) + (title,)
        heading = Heading(level, title, aliases[0], aliases, start, len(markdown), path)
        found.append(heading)
        stack.append(heading)
        anchor = None
    return found


@dataclass
class TableRow:
    section_id: str
    path: tuple[str, ...]
    header: str
    divider: str
    line: str


def parse_table_rows(markdown: str, headings: list[Heading]) -> list[TableRow]:
    """Named check/standard IDs in first cells are addressable within their heading."""
    rows = []
    previous, header, divider = "", "", ""
    fence_char, fence_len, offset = "", 0, 0
    for line in markdown.splitlines(keepends=True):
        raw = line.rstrip("\r\n")
        position, offset = offset, offset + len(line)
        fence = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", raw)
        if fence_char:
            if fence and fence.group(1)[0] == fence_char and len(fence.group(1)) >= fence_len and not fence.group(2).strip():
                fence_char, fence_len = "", 0
            continue
        if fence:
            fence_char, fence_len = fence.group(1)[0], len(fence.group(1))
            previous, header, divider = "", "", ""
            continue
        if raw.startswith(("    ", "\t")):
            previous, header, divider = "", "", ""
            continue
        if re.fullmatch(r"\s*\|\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)+\|?\s*", raw):
            header, divider = previous if previous.lstrip().startswith("|") else "", raw
        elif header and raw.lstrip().startswith("|"):
            cell = raw.strip().strip("|").split("|", 1)[0].strip()
            cell = re.sub(r"\[([^\]]+)\](?:\([^)]*\)|\[[^\]]*\])", r"\1", cell)
            cell = cell.replace("`", "").replace("**", "")
            identifier = re.match(r"^([A-Z]+-\d+[a-z]?|[A-Z]+\d+|\d+(?:\.\d+){2,})(?=\s|$)", cell)
            if identifier:
                parents = [h for h in headings if h.start <= position < h.end]
                path = parents[-1].path if parents else ()
                rows.append(TableRow(identifier.group(1), path, header, divider, raw))
        else:
            header, divider = "", ""
        previous = raw
    return rows


def bounded(text: str, cap: int = MAX_BYTES) -> str:
    raw = text.encode("utf-8")
    if len(raw) <= cap:
        return text
    tail = "\n[listing shortened to byte cap]\n"
    return raw[: cap - len(tail.encode())].decode("utf-8", errors="ignore").rsplit("\n", 1)[0] + tail


def list_ids(headings: list[Heading], prefix: str = "") -> str:
    # Compact enough to list all IDs even when the original headings are very long.
    listing = prefix + "\n".join(f"{'  ' * (h.level - 1)}{h.section_id}\t{h.title}" for h in headings) + "\n"
    if len(listing.encode()) > MAX_BYTES:
        listing = prefix + "\n".join(h.section_id for h in headings) + "\n"
    return bounded(listing)


def reference_output(path: Path, section_id: str | None = None) -> str:
    markdown = path.read_text(encoding="utf-8")
    headings = parse_headings(markdown)
    rows = parse_table_rows(markdown, headings)
    if section_id is None:
        heading_aliases = {alias for h in headings for alias in h.aliases}
        extra = "".join(f"row {r.section_id}\t{' > '.join(r.path)}\n" for r in rows if r.section_id not in heading_aliases)
        listing = list_ids(headings, "Section IDs:\n") if headings else "No headings found.\n"
        return bounded(listing + extra)
    matches = [h for h in headings if section_id in h.aliases]
    if not matches:
        selected = [r for r in rows if r.section_id == section_id]
        if len(selected) > 1:
            raise ValueError(f"Ambiguous section ID {section_id!r}; use the parent heading ID.")
        if selected:
            row = selected[0]
            prefix = f"Heading path: {' > '.join(row.path)}\nID: {row.section_id}\n\n"
            output = prefix + "\n".join((row.header, row.divider, row.line)) + "\n"
            if len(output.encode()) > MAX_BYTES:
                return bounded(prefix + "Row exceeds 8192 bytes; no subsections.\n")
            return output
        raise ValueError(f"Unknown section ID {section_id!r}; omit the ID to list available sections.")
    if len(matches) != 1:
        raise ValueError(f"Ambiguous section ID {section_id!r}; use a unique listed ID.")
    heading = matches[0]
    prefix = f"Heading path: {' > '.join(heading.path)}\nID: {heading.section_id}\n\n"
    body = prefix + markdown[heading.start:heading.end].rstrip() + "\n"
    if len(body.encode("utf-8")) <= MAX_BYTES:
        return body
    children = [h for h in headings if heading.start < h.start < heading.end]
    notice = prefix + "Section exceeds 8192 bytes. Look up a subsection ID:\n"
    if not children:
        return bounded(notice + "No subsections; the full section is not printed.\n")
    return list_ids(children, notice)


def resolve_reference(file_arg: str) -> Path:
    requested = Path(file_arg).expanduser()
    candidates = [requested] if requested.is_absolute() else [SKILL_ROOT / requested, Path.cwd() / requested]
    for candidate in candidates:
        path = candidate.resolve()
        if not path.is_relative_to(SKILL_ROOT.resolve()):
            continue
        if path.is_file() and path.suffix.lower() == ".md":
            return path
    raise ValueError("Reference must be an existing .md file inside the skill folder.")


def platform_output(channel_id: str, root: Path = SKILL_ROOT) -> str:
    data = json.loads((root / "uxresearch/data/korea-platforms.json").read_text(encoding="utf-8"))
    matches = [p for p in data["platforms"] if p["id"] == channel_id]
    if not matches:
        ids = ", ".join(p["id"] for p in data["platforms"])
        raise ValueError(f"Unknown channel ID {channel_id!r}. Available: {ids}")
    platform = matches[0]
    routes = json.loads((root / "uxresearch/data/routes.json").read_text(encoding="utf-8"))
    terms = []
    for entry in routes["terms_restricted"]:
        if any(host == covered or host.endswith("." + covered) for host in platform["hosts"] for covered in entry["hosts"]):
            terms.append({key: entry.get(key) for key in ("id", "hosts", "status", "lift_requires", "official_route", "terms_url", "effective_from")})
    output = {"id": channel_id, "name_ko": platform.get("name_ko"), "version": data.get("version"),
              "checked_at": data.get("checked_at"), "verified_at": data.get("verified_at")}
    for key in ("hosts", "family", "public_scope", "routes", "route_ids", "expected_stops"):
        output[key] = platform.get(key)
    output["robots"] = {k: platform.get("robots", {}).get(k) for k in ("expectation", "checked_at")}
    output["channel_terms"] = {k: platform.get("terms", {}).get(k) for k in ("status", "routes_entry", "lift_requires")}
    output["terms_entries"] = terms
    output["rule"] = "Packaged metadata, not a live access check. Read the access card and run the reader; status records evidence, lift_requires decides lifts."
    rendered = json.dumps(output, ensure_ascii=False, indent=2) + "\n"
    if len(rendered.encode()) > MAX_BYTES:
        raise ValueError("Channel record exceeds the byte cap; no partial JSON was printed.")
    return rendered


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", help="Skill-relative Markdown path, or platform")
    parser.add_argument("section_id", nargs="?", help="Heading number/ID, or channel ID")
    args = parser.parse_args(argv)
    try:
        if args.file == "platform":
            if args.section_id is None:
                data = json.loads((SKILL_ROOT / "uxresearch/data/korea-platforms.json").read_text(encoding="utf-8"))
                output = bounded("\n".join(p["id"] for p in data["platforms"]) + "\n")
            else:
                output = platform_output(args.section_id)
        else:
            output = reference_output(resolve_reference(args.file), args.section_id)
        sys.stdout.write(output)
        return 0
    except (ValueError, OSError, UnicodeError, KeyError, TypeError) as exc:
        sys.stderr.write(bounded(f"ref: {exc}\n"))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
