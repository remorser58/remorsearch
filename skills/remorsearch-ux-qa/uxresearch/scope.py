"""What the reader never requests, decided from the URL alone.

Checked before any DNS lookup, robots.txt fetch, slot or request, and again on
every redirect hop (robots.txt redirects included), official route and site
alternate, in this order:

  deny list       the researcher's deny_hosts (brief or --deny-host): a stop,
                  opted_out.
  search pages    the route table's search_pages (portal and web search
                  results), and a site's own search results page: a URL with a
                  query on a host of the route table's platforms whose path has a
                  'search' segment ('/search', '/search.php', '/board-search').
                  A URL handed to `read`, `robots` or `ingest` is refused (exit
                  2); one reached by a redirect is a stop (opted_out, out of
                  scope, not a coverage gap).
  never call      the never_call endpoints (and the endpoints) of discovery
                  entries that are switched off (enabled is not true): the same
                  as search pages. The reader never calls a disabled route.
  copies          the route table's third_party_copies: archives, caches,
                  translation and reader proxies, AMP caches and front ends that
                  show another site's pages. The URL they wrap is judged first:
                  when the scope checks stop it, the copy stops with the same
                  class. Otherwise the copy itself is refused like a search page
                  (third_party_copy), except an archive entry marked
                  wayback_for_official, for a page of the product's own site
                  when the brief allows it (allow_wayback_for_official).
  private         the route table's out_of_scope channels: a stop, auth_gate,
                  out of scope.
  terms           terms_restricted entries: hosts whose published ('confirmed')
                  or reported ('reported') terms restrict automated collection.
                  A stop, terms_restricted, and a coverage gap. Every entry that
                  covers the URL's host must be lifted, each by a check of its
                  own; lift_requires decides whether it can be lifted.

Host names cover their subdomains in every list; path prefixes match whole path
segments, case-insensitively, on the raw path and on its normalised forms (dot
segments removed, unreserved escapes decoded, empty segments and ';' parameters
cut), so a stop matches when any form does. Nothing a page says changes these
lists, and only the user's brief carries terms checks.

The packaged lists (data/routes.json) always apply. A route table given with
`start --routes` may add platforms and list entries, but check_run_table()
refuses one that redefines a packaged entry or a platform of a terms_restricted
host, and official-only mode reads only the packaged table's routes.
"""
from __future__ import annotations

import functools
import ipaddress
import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit

from . import verdict

DATA = Path(__file__).resolve().parent / "data"
STATUSES = ("reported", "confirmed")
LIFT_REQUIREMENTS = ("never", "written_permission", "terms_check")
TERMS_POLICY_VERSION = "lift_requires.v1"  # older runs must restart; previously ignored checks stay inactive
RESTRICTS = ("automated_collection", "bulk_collection", "ai_input", "storage")
CHECK_RESULTS = ("permits_this_reading", "restricts_this_reading", "unclear")
LIFTING_RESULT = "permits_this_reading"
LIFTED_HOST_BUDGET = 10
MAX_TERMS_CHECKS = 20
MAX_CHECK_AGE_DAYS = 365  # an older terms check is stale: the terms may have changed since
CHECK_FIELDS = ("host", "terms_url", "checked_on", "result", "note", "permission")
CHECK_REQUIRED = ("host", "terms_url", "checked_on", "result")
PERMISSION_FIELDS = ("granted_by", "granted_on", "reference")
KINDS = ("deny", "search_page", "never_call", "third_party_copy", "out_of_scope", "terms")
REFUSED_KINDS = frozenset({"search_page", "never_call", "third_party_copy"})  # refused (exit 2) when handed in
ERRORS = {"search_page": "search_results_page", "never_call": "disabled_route", "third_party_copy": "third_party_copy"}
COPY_TARGETS = ("path_url", "label_host", "amp_path", "query_url", "template", "none")
MAX_WRAP_DEPTH = 3
_HOST_NAME = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9-]{1,63}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_UNRESERVED = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
_EMBEDDED_URL = re.compile(r"https?:/{1,3}[^\s]+", re.I)
# A path segment that names a site's own search results page: 'search', 'search.php', 'board-search', 'search_list'.
_SEARCH_SEGMENT = re.compile(r"^(?:[a-z0-9]+[._-])*search(?:[._-][a-z0-9]+)*$")
SEARCH_NOTE = ("a search results page: never read, captured or opened by a browser tool; discovery runs through the "
               "agent's own search tool, and each result page is read on its own")
NEVER_CALL_NOTE = "an endpoint of a discovery route that is switched off: the reader never calls it"
COPY_NOTE = ("a third-party copy of another site's page (an archive, a cache, a translation or reader proxy, an AMP "
             "cache or a front end): never read; read the original page itself, whose own stops then apply")
PRIVATE_NOTE = "a private channel: out of the research's scope, not a coverage gap"
TERMS_NOTE = ("this host's terms restrict automated collection (terms_restricted): nothing is requested from it and "
              "no render capture is taken in; the stop is a coverage gap, never a reason to look for another way in")


@functools.lru_cache(maxsize=1)
def packaged() -> dict:
    """The packaged route table (data/routes.json)."""
    return json.loads((DATA / "routes.json").read_text(encoding="utf-8"))


@functools.lru_cache(maxsize=1)
def _suffix_data() -> dict:
    return json.loads((DATA / "suffixes.json").read_text(encoding="utf-8"))


def registrable_domain(host: str, *, hosting: bool = True) -> str:
    """The registrable domain, honouring multi-label suffixes (data/suffixes.json) and, with `hosting`,
    hosting suffixes whose every subdomain is a separate author."""
    host = (host or "").lower().rstrip(".")
    try:
        ipaddress.ip_address(host.strip("[]"))
        return host
    except ValueError:
        pass
    data = _suffix_data()
    suffixes = set(data["public_suffixes"]) | (set(data["hosting_suffixes"]) if hosting else set())
    labels = host.split(".")
    for i in range(1, len(labels)):
        if ".".join(labels[i:]) in suffixes:
            return ".".join(labels[i - 1:])
    return ".".join(labels[-2:])


def site_of(host: str) -> str:
    """The site a host-wide stop covers: the registrable domain of the operator (a blog-hosting platform's
    subdomains count as that platform's site, not as separate sites)."""
    return registrable_domain(host, hosting=False)


def _items(data, name: str) -> list:
    value = data.get(name) if isinstance(data, dict) else None
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


# ---------------------------------------------------------------- paths


def _decode_unreserved(path: str) -> str:
    def replace(match: re.Match) -> str:
        char = chr(int(match.group(1), 16))
        return char if char in _UNRESERVED else "%" + match.group(1).upper()
    return re.sub(r"%([0-9A-Fa-f]{2})", replace, path)


def remove_dot_segments(path: str) -> str:
    """RFC 3986 section 5.2.4."""
    output: list[str] = []
    for segment in path.split("/"):
        if segment == "..":
            if len(output) > 1:
                output.pop()
        elif segment != ".":
            output.append(segment)
    result = "/".join(output)
    if path.endswith(("/.", "/..")):
        result += "/"
    return result if result.startswith("/") else "/" + result


def path_forms(path: str) -> tuple:
    """The forms a server may map this path to: as sent, with unreserved escapes decoded and dot segments
    removed, and fully decoded with empty segments and ';' parameters cut. Lower case, for scope matching."""
    raw = path or "/"
    decoded = remove_dot_segments(_decode_unreserved(raw))
    loose = remove_dot_segments(unquote(raw))
    loose = "/" + "/".join(s.split(";", 1)[0] for s in loose.split("/") if s.split(";", 1)[0])
    return tuple(dict.fromkeys(p.lower() for p in (raw, decoded, loose)))


def path_under(path: str, prefix: str) -> bool:
    """True when `path` lies under `prefix`, matched on whole path segments ('' or '/' is everything), in any
    of the path's normalised forms."""
    prefix = (prefix or "").rstrip("/").lower()
    if not prefix:
        return True
    return any(form == prefix or form.startswith(prefix + "/") for form in path_forms(path))


def _query_names(query: str) -> set:
    return {name.strip().lower() for name, _ in parse_qsl(query or "", keep_blank_values=True)}


def site_search(path: str, query: str) -> bool:
    """True for a site's own search results page: a query, and a path segment that names a search, in any of
    the path's forms."""
    if not (query or "").strip():
        return False
    return any(_SEARCH_SEGMENT.match(segment) for form in path_forms(path) for segment in form.split("/"))


# ---------------------------------------------------------------- lists


def _host_patterns(value) -> list:
    if isinstance(value, str):
        return [value.strip().lower().rstrip(".")] if value.strip() else []
    return [h.strip().lower().rstrip(".") for h in value or [] if isinstance(h, str) and h.strip()]


def _endpoint_guard(url: str) -> tuple[str, str] | None:
    """(host, path prefix) that covers one discovery endpoint template."""
    if not isinstance(url, str) or "://" not in url:
        return None
    head = url.split("{", 1)[0]
    try:
        parts = urlsplit(head)
        host = (parts.hostname or "").lower()
    except ValueError:
        return None
    if not host:
        return None
    path = parts.path or ""
    if "{" in url and not head.endswith("/"):  # a template variable inside the last segment
        path = path.rsplit("/", 1)[0]
    return host, path.rstrip("/")


def _documents(entry: dict) -> list:
    """The terms documents a check may cite to lift this entry: terms_url and terms_urls."""
    if not entry.get("terms_url"):
        return []  # a missing primary document cannot be lifted by an alias alone
    urls = [entry.get("terms_url")] + list(entry.get("terms_urls") or [])
    return list(dict.fromkeys(u for u in urls if isinstance(u, str) and u.strip()))


def document_key(url) -> tuple[str, str] | None:
    """(host, path) of a document URL, ignoring the scheme, query and fragment."""
    if not isinstance(url, str) or not url.strip():
        return None
    try:
        parts = urlsplit(url.strip())
        host = (parts.hostname or "").lower().rstrip(".")
    except ValueError:
        return None
    if not host:
        return None
    path = remove_dot_segments(_decode_unreserved(parts.path or "/"))
    return host, (path.rstrip("/") or "/")


@dataclass(frozen=True)
class Lists:
    """The scope lists of one route table merged with the packaged ones."""
    search_pages: tuple = ()
    never_call: tuple = ()  # (discovery id, host, path prefix, reason)
    out_of_scope: tuple = ()
    terms: tuple = ()  # entries; each carries 'packaged': True or False
    copies: tuple = ()
    platform_hosts: tuple = ()  # hosts of the route tables' platforms, whose own search pages are refused


def lists_for(run_routes: dict | None) -> Lists:
    """Packaged lists first, then the run's own route table; an entry never removes another."""
    sources = [(packaged(), True)]
    if isinstance(run_routes, dict) and run_routes is not sources[0][0]:
        sources.append((run_routes, False))
    search, never, private, terms, copies, platform_hosts = [], [], [], [], [], []
    seen: set = set()

    def add(bucket: list, key, item) -> None:
        if key not in seen:
            seen.add(key)
            bucket.append(item)

    for data, is_packaged in sources:
        for platform in _items(data, "platforms"):
            for host in _host_patterns(platform.get("hosts")):
                if host not in platform_hosts:
                    platform_hosts.append(host)
        for item in _items(data, "search_pages"):
            for host in _host_patterns(item.get("host")):
                add(search, ("search", host, item.get("path_prefix") or "", item.get("query_param") or ""),
                    {**item, "host": host})
        for item in _items(data, "discovery"):
            if item.get("enabled") is True:
                continue
            reason = str(item.get("reason") or "switched off")
            guards = [(g.get("host"), g.get("path_prefix") or "") for g in _items(item, "never_call")]
            endpoints = item.get("endpoints") if isinstance(item.get("endpoints"), dict) else {}
            guards += [g for g in (_endpoint_guard(u) for u in endpoints.values()) if g]
            for host, prefix in guards:
                for name in _host_patterns(host):
                    add(never, ("never", name, prefix.rstrip("/")),
                        (str(item.get("id") or "discovery"), name, prefix.rstrip("/"), reason))
        for item in _items(data, "third_party_copies"):
            hosts = _host_patterns(item.get("hosts") if "hosts" in item else item.get("host"))
            if hosts or item.get("target") == "template":
                add(copies, ("copy", str(item.get("id")), tuple(hosts), json.dumps(item, sort_keys=True)),
                    {**item, "hosts": hosts, "packaged": is_packaged})
        for item in _items(data, "out_of_scope"):
            for host in _host_patterns(item.get("host")):
                add(private, ("private", host, item.get("path_prefix") or ""), {**item, "host": host})
        for item in _items(data, "terms_restricted"):
            hosts = _host_patterns(item.get("hosts"))
            if hosts:
                add(terms, ("terms", str(item.get("id")), tuple(hosts)),
                    {**item, "hosts": hosts, "packaged": is_packaged})
    return Lists(tuple(search), tuple(never), tuple(private), tuple(terms), tuple(copies), tuple(platform_hosts))


# ---------------------------------------------------------------- stops


@dataclass
class ScopeStop:
    """Why a URL is never requested. `kind` is one of KINDS."""
    kind: str
    stop_class: str
    reasons: list
    out_of_scope: bool = False
    note: str = ""
    terms: dict | None = None
    detail: str = ""

    @property
    def refused_at_start(self) -> bool:
        return self.kind in REFUSED_KINDS

    @property
    def error(self) -> str | None:
        return ERRORS.get(self.kind)


def _split(url: str) -> tuple[str, str, str]:
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower().rstrip(".")
    except ValueError:
        return "", "/", ""
    return host, parts.path or "/", parts.query


def terms_entries(host: str, lists: Lists) -> list:
    """Every terms_restricted entry that covers this host, in list order (packaged first)."""
    host = (host or "").lower().rstrip(".")
    return [entry for entry in lists.terms if verdict.host_matches(host, entry["hosts"])]


def terms_entry(host: str, lists: Lists) -> dict | None:
    """The first terms_restricted entry that covers this host, if any."""
    found = terms_entries(host, lists)
    return found[0] if found else None


def _status(entry: dict) -> str:
    return entry.get("status") if entry.get("status") in STATUSES else "reported"


def _requires(entry: dict) -> str:
    value = entry.get("lift_requires")
    return value if value in LIFT_REQUIREMENTS else "never"  # missing or unknown: fail closed


def check_applies(check: dict, entry: dict) -> bool:
    """A check is for this entry when it cites one of the entry's own terms documents and its host is one of
    the entry's hosts or narrower (a check for a parent domain never lifts a more specific entry)."""
    name = str(check.get("host") or "").lower().rstrip(".")
    if not name or not verdict.host_matches(name, entry["hosts"]):
        return False
    cited = document_key(check.get("terms_url"))
    return cited is not None and cited in {document_key(u) for u in _documents(entry)}


def _check_brief(check: dict) -> dict:
    brief = {k: check.get(k) for k in ("host", "terms_url", "checked_on", "result")}
    if isinstance(check.get("permission"), dict):
        brief["permission"] = {k: check["permission"].get(k) for k in PERMISSION_FIELDS}
    return brief


def lift_record(entry: dict, host: str, policy: dict) -> dict:
    """What the run records about one terms entry for one URL's host, lifted or not. The entry is lifted only
    when its lift_requires permits it, a check of the user's covers the host (its host is the URL's host or a parent of
    it), is for this entry (check_applies), says permits_this_reading, and, for an entry that needs written
    permission, records that permission; any check for the entry that covers the host and does not permit
    the reading keeps it closed, and so does a check dated before the restriction came into force."""
    host = (host or "").lower().rstrip(".")
    status, requires = _status(entry), _requires(entry)
    checks = [c for c in policy.get("terms_checked") or []
              if verdict.host_matches(host, [str(c.get("host") or "").lower().rstrip(".")])]
    own = [c for c in checks if check_applies(c, entry)]
    permitting = [c for c in own if c.get("result") == LIFTING_RESULT]
    blocking = [c for c in own if c.get("result") != LIFTING_RESULT]
    since = entry.get("effective_from") if isinstance(entry.get("effective_from"), str) else None
    usable = [c for c in permitting if not since or str(c.get("checked_on") or "") >= since]
    if requires == "written_permission":
        usable = [c for c in usable if isinstance(c.get("permission"), dict)]
    chosen = max(usable, key=lambda c: len(str(c.get("host")))) if usable else None
    if requires == "never":
        why = "lift_requires_never"
    elif blocking:
        why = f"check_result:{blocking[0].get('result')}"
    elif chosen is not None:
        why = None
    elif permitting and since and not [c for c in permitting if str(c.get("checked_on") or "") >= since]:
        why = "check_predates_restriction"
    elif permitting:
        why = "needs_written_permission"
    elif [c for c in checks if verdict.host_matches(str(c.get("host") or "").lower(), entry["hosts"])]:
        why = "check_cites_another_document"
    else:
        why = "no_terms_check"
    lifted = why is None
    record = {"entry": entry.get("id"), "status": status, "lift_requires": requires,
              "restricts": list(entry.get("restricts") or []), "terms_url": entry.get("terms_url"),
              "official_route": entry.get("official_route"), "packaged": bool(entry.get("packaged")),
              "lifted": lifted, "not_lifted_because": why, "check": _check_brief(chosen) if lifted else None}
    if lifted:
        record["host_budget"] = LIFTED_HOST_BUDGET
    return record


def terms_record(entry: dict, check: dict | None, host: str | None = None) -> dict:
    """Compatibility wrapper: the record of one entry with one check (the check's host stands for the URL's)."""
    policy = {"terms_checked": [check] if check else []}
    return lift_record(entry, host or (check or {}).get("host") or (entry["hosts"][0] if entry["hosts"] else ""),
                       policy)


def combine(records: list) -> dict:
    """The terms record of a URL: the deciding entry's fields (the first entry that is not lifted, else the
    first entry), plus every covering entry in 'entries'."""
    deciding = next((r for r in records if not r["lifted"]), records[0])
    combined = dict(deciding)
    combined["lifted"] = all(r["lifted"] for r in records)
    combined["entries"] = [{k: r.get(k) for k in ("entry", "status", "lift_requires", "lifted", "not_lifted_because")}
                           | {"check_host": (r.get("check") or {}).get("host")} for r in records]
    combined["lifted_entries"] = [r["entry"] for r in records if r["lifted"]]
    if combined["lifted"]:
        combined["host_budget"] = LIFTED_HOST_BUDGET
    else:
        combined.pop("host_budget", None)
    return combined


def terms_reasons(record: dict) -> list:
    restricts = "+".join(record["restricts"]) or "unspecified"
    reasons = [f"terms:{record['status']}:{restricts}", f"terms_entry:{record['entry']}"]
    if record.get("not_lifted_because"):
        reasons.append(f"terms_check:{record['not_lifted_because']}")
    for other in record.get("entries") or []:  # every other covering entry that is not lifted either
        if other["entry"] != record["entry"] and not other["lifted"]:
            reasons.append(f"terms_entry:{other['entry']}:{other['not_lifted_because']}")
    return reasons


def official_route(record: dict, lists: Lists) -> tuple[str | None, str | None]:
    """(the official route that official-only mode may run for this terms stop, or None; why not). Only a
    packaged entry's official_route counts, and every covering entry that is not lifted must name it."""
    closed = [e for e in record.get("entries") or [] if not e["lifted"]]
    by_id = {e["id"]: e for e in lists.terms}
    names = set()
    for item in closed:
        entry = by_id.get(item["entry"])
        if entry is None or not entry.get("packaged"):
            return None, "official_route_not_packaged" if (entry or {}).get("official_route") else None
        names.add(entry.get("official_route"))
    if len(names) != 1 or None in names:
        return None, None
    return names.pop(), None


def _copy_target(item: dict, url: str) -> str | None:
    """The URL a third-party copy shows, or None when it cannot be told from the URL."""
    target = item.get("target")
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    if target == "path_url":
        found = _EMBEDDED_URL.search(unquote(parts.path + ("?" + parts.query if parts.query else "")))
        if not found:
            return None
        value = re.sub(r"^(https?):/+", r"\1://", found.group(0), flags=re.I)
        return value
    if target in ("label_host", "amp_path"):
        if target == "amp_path":
            found = re.match(r"^/[a-z]/(s/)?([^/]+)(/.*)?$", parts.path or "", re.I)
            if found:
                scheme = "https" if found.group(1) else "http"
                return f"{scheme}://{found.group(2)}{found.group(3) or '/'}" + (f"?{parts.query}" if parts.query else "")
        label = host.split(".", 1)[0]
        for suffix in item["hosts"]:
            if host.endswith("." + suffix.lstrip("*.")):
                label = host[: -len("." + suffix.lstrip("*."))].split(".")[-1]
                break
        if not label or label == host:
            return None
        decoded = label.replace("--", "\0").replace("-", ".").replace("\0", "-")
        if "." not in decoded:
            return None
        query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not k.startswith("_x_tr_")]
        return f"https://{decoded}{parts.path or '/'}" + (f"?{urlencode(query)}" if query else "")
    if target == "query_url":
        for name in item.get("query_params") or ["q", "url", "u"]:
            for key, value in parse_qsl(parts.query, keep_blank_values=True):
                if key.lower() == name:
                    value = re.sub(r"^cache:(?:[A-Za-z0-9_-]{6,}:)?", "", value.strip(), flags=re.I)
                    if not value:
                        continue
                    return value if re.match(r"^https?://", value, re.I) else "https://" + value
        return None
    if target == "template":
        path_pattern = item.get("path")
        if not isinstance(path_pattern, str) or not re.match(path_pattern, parts.path or "/"):
            return None
        values = {}
        for name, pattern in (item.get("query") or {}).items():
            found = [v for k, v in parse_qsl(parts.query, keep_blank_values=True) if k == name]
            if not found or not re.fullmatch(pattern, found[0]):
                return None
            values[name] = found[0]
        template = item.get("wraps")
        return re.sub(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", lambda m: values.get(m.group(1), ""), template) \
            if isinstance(template, str) else None
    return None


def _copy_stop(url: str, host: str, policy: dict, lists: Lists, depth: int) -> tuple[ScopeStop | None, bool]:
    """(the stop for a third-party copy, or None; whether the URL is a copy at all)."""
    for item in lists.copies:
        if not item["hosts"]:  # a rule for any host, by URL shape alone
            if item.get("target") != "template" or verdict.host_matches(host, _host_patterns(item.get("except_hosts"))):
                continue
            wrapped = _copy_target(item, url)
            if wrapped is None:
                continue
        elif verdict.host_matches(host, item["hosts"]):
            wrapped = _copy_target(item, url)
        else:
            continue
        label = str(item.get("id") or host)
        if wrapped:
            inner, _ = evaluate(wrapped, policy, lists, _depth=depth + 1)
            if inner is not None:
                inner.reasons = list(inner.reasons) + [f"third_party_copy:{label}"]
                inner.detail = (inner.detail + "; " if inner.detail else "") + f"reached through a copy ({label})"
                return inner, True
            official = policy.get("official_sites") or []
            if item.get("wayback_for_official") and policy.get("allow_wayback_for_official") and official:
                wrapped_host = (urlsplit(wrapped).hostname or "").lower() if "://" in wrapped else ""
                if wrapped_host and site_of(wrapped_host) in official:
                    return None, True
        return ScopeStop("third_party_copy", "opted_out", ["third_party_copy", f"third_party_copy:{label}"],
                         out_of_scope=True, note=COPY_NOTE,
                         detail=f"a third-party copy ({label}) of another site's page is never read: read the "
                                "original page itself"), True
    return None, False


def evaluate(url: str, policy: dict, lists: Lists, *, _depth: int = 0) -> tuple[ScopeStop | None, dict | None]:
    """(the stop, or None; the terms record of a lifted host, or None) for one URL."""
    host, path, query = _split(url)
    if verdict.host_matches(host, policy.get("deny_hosts") or []):
        return ScopeStop("deny", "opted_out", ["deny_hosts"], note="a host the researcher excludes",
                         detail="a host the researcher excludes (deny_hosts)"), None
    for item in lists.search_pages:
        if not verdict.host_matches(host, [item["host"]]) or not path_under(path, item.get("path_prefix") or ""):
            continue
        param = item.get("query_param")
        if param and param.lower() not in _query_names(query):
            continue
        return ScopeStop("search_page", "opted_out", ["search_results_page", f"search_page:{item['host']}"],
                         out_of_scope=True, note=SEARCH_NOTE,
                         detail="search results pages are never read, captured or opened by a browser tool; discovery "
                                "runs through the agent's own search tool, and each result page is read on its own"), \
            None
    if lists.platform_hosts and verdict.host_matches(host, lists.platform_hosts) and site_search(path, query):
        return ScopeStop("search_page", "opted_out", ["search_results_page", f"site_search:{host}"],
                         out_of_scope=True, note=SEARCH_NOTE,
                         detail="a site's own search results page is never read, captured or opened by a browser "
                                "tool; each result page is read on its own"), None
    for route_id, name, prefix, reason in lists.never_call:
        if verdict.host_matches(host, [name]) and path_under(path, prefix):
            return ScopeStop("never_call", "opted_out", [f"never_call:{route_id}", reason], out_of_scope=True,
                             note=NEVER_CALL_NOTE,
                             detail=f"this endpoint belongs to the discovery route {route_id}, which is switched off "
                                    f"({reason}); the reader never calls it"), None
    if _depth < MAX_WRAP_DEPTH:
        copy, is_copy = _copy_stop(url, host, policy, lists, _depth)
        if copy is not None:
            return copy, None
    else:
        is_copy = False
    for item in lists.out_of_scope:
        if verdict.host_matches(host, [item["host"]]) and path_under(path, item.get("path_prefix") or ""):
            reason = item.get("reason", "out of scope")
            return ScopeStop("out_of_scope", "auth_gate", [f"private_channel:{reason}"], out_of_scope=True,
                             note=PRIVATE_NOTE, detail=f"a private channel ({reason})"), None
    entries = terms_entries(host, lists)
    if not entries:
        return None, None
    record = combine([lift_record(entry, host, policy) for entry in entries])
    if record["lifted"]:
        return None, record
    lift_notes = []
    for item in record["entries"]:
        if not item["lifted"]:
            action = ("this restriction cannot be lifted" if item["lift_requires"] == "never" else
                      "a lift needs the user's current terms check and prior written permission" if
                      item["lift_requires"] == "written_permission" else "a lift needs the user's current terms check")
            lift_notes.append(f"{item['entry']} (lift_requires: {item['lift_requires']}): {action}")
    return ScopeStop("terms", "terms_restricted", terms_reasons(record),
                     note=TERMS_NOTE + "; " + "; ".join(lift_notes), terms=record,
                     detail=f"terms_restricted ({record['status']}): {record['entry']}"), None


def lifted_entries(host: str, policy: dict, lists: Lists) -> list:
    """The ids of the terms entries covering this host that the user's checks lift (all of them must be)."""
    entries = terms_entries(host, lists)
    if not entries or not policy.get("terms_checked"):
        return []
    records = [lift_record(entry, host, policy) for entry in entries]
    return [r["entry"] for r in records] if all(r["lifted"] for r in records) else []


def lifted_host(host: str, policy: dict, lists: Lists) -> bool:
    """True when terms entries cover this host and the user's terms checks lift every one of them."""
    return bool(lifted_entries(host, policy, lists))


def _entry_effect(check: dict, entry: dict) -> tuple[str, bool]:
    """(what one check does for one entry, whether it lifts it for URLs under the check's host)."""
    entry_id, hosts = entry.get("id"), ", ".join(entry["hosts"])
    name = str(check.get("host") or "").lower()
    if not verdict.host_matches(name, entry["hosts"]):
        return (f"does not lift {entry_id}: the check's host {name} is broader than the entry's hosts ({hosts}); "
                "only a check for one of those hosts (or a narrower one) lifts it"), False
    if _requires(entry) == "never":
        return f"{entry_id}: lift_requires_never; this restriction is never lifted", False
    if not check_applies(check, entry):
        documents = ", ".join(_documents(entry)) or "none: this entry lists no terms document, so no check lifts it"
        return (f"does not lift {entry_id}: the check's terms_url is not this entry's terms document "
                f"({documents})"), False
    if check.get("result") != LIFTING_RESULT:
        return f"does not lift {entry_id}: the result is {check.get('result')}", False
    since = entry.get("effective_from")
    if isinstance(since, str) and str(check.get("checked_on") or "") < since:
        return f"does not lift {entry_id}: the check predates the restriction ({since})", False
    if _requires(entry) == "written_permission" and not isinstance(check.get("permission"), dict):
        return f"does not lift {entry_id}: its terms require prior written permission, and the check records none", \
            False
    extra = " with the written permission it records" if _requires(entry) == "written_permission" else ""
    return (f"lifts {entry_id} ({_status(entry)}){extra} for URLs under {name}, when every other entry covering a URL is "
            f"lifted by its own check; at most {LIFTED_HOST_BUDGET} documents under this entry"), True


def describe_checks(policy: dict, lists: Lists) -> list:
    """For `start` and `close`: what each of the user's terms checks does, entry by entry."""
    rows = []
    for item in policy.get("terms_checked") or []:
        host = item["host"]
        related = [e for e in lists.terms
                   if verdict.host_matches(host, e["hosts"]) or any(verdict.host_matches(h, [host]) for h in e["hosts"])]
        effects = []
        for entry in related:
            effect, lifts = _entry_effect(item, entry)
            effects.append({"entry": entry.get("id"), "status": _status(entry), "lift_requires": _requires(entry),
                            "lifts": lifts, "effect": effect})
        lifting = [e["entry"] for e in effects if e["lifts"]]
        if not effects:
            summary = "no terms_restricted entry covers this host; nothing to lift"
        elif lifting:
            summary = "lifts " + ", ".join(lifting) + " (each entry that covers a URL needs a check of its own)"
        else:
            summary = "lifts nothing: " + "; ".join(e["effect"] for e in effects)
        rows.append({"host": host, "checked_on": item.get("checked_on"), "result": item.get("result"),
                     "terms_url": item.get("terms_url"), "entry": lifting[0] if lifting else
                     (effects[0]["entry"] if effects else None),
                     "lifts": lifting, "entries": effects, "effect": summary,
                     "permission": _check_brief(item).get("permission")})
    return rows


def describe_lifts(policy: dict, lists: Lists) -> list:
    """For `start` and `close`: every terms entry a check names, with the checks that lift it."""
    rows: dict = {}
    for check in describe_checks(policy, lists):
        for effect in check["entries"]:
            row = rows.setdefault(effect["entry"], {"entry": effect["entry"], "status": effect["status"],
                                                    "lift_requires": effect["lift_requires"], "lifted_by": [],
                                                    "permission": None, "effect": None})
            if effect["lifts"]:
                row["lifted_by"].append(check["host"])
                row["permission"] = row["permission"] or check.get("permission")
    for row in rows.values():
        entry = next((e for e in lists.terms if e.get("id") == row["entry"]), None)
        hosts = ", ".join(entry["hosts"]) if entry else ""
        if row["lifted_by"]:
            row["effect"] = (f"lifted for URLs under {', '.join(row['lifted_by'])} (hosts {hosts}) when every other "
                             f"entry covering the URL is lifted too; at most {LIFTED_HOST_BUDGET} documents")
        elif row["lift_requires"] == "never":
            row["effect"] = "lift_requires_never: never lifted"
        else:
            row["effect"] = f"not lifted: no check of its own lifts it (hosts {hosts})"
    return list(rows.values())


# ---------------------------------------------------------------- brief checks


def _valid_date(value: str) -> date | None:
    if not isinstance(value, str) or not _DATE.match(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def valid_host(value, *, wildcard: bool = False) -> str | None:
    """A host name (lower case, no trailing dot), or None when it is not one: no scheme, path, port or space.
    With `wildcard`, a leading '*.' is allowed."""
    if not isinstance(value, str):
        return None
    host = value.strip().lower().rstrip(".")
    body = host[2:] if wildcard and host.startswith("*.") else host
    try:
        ipaddress.ip_address(body)
        return host
    except ValueError:
        pass
    return host if _HOST_NAME.match(body) else None


def validate_checks(items, today: date) -> None:
    """Shape checks for access_policy.terms_checked; raises ValueError with the first problem.
    `today` may be a day ahead of UTC (the user's own time zone)."""
    if not isinstance(items, list) or len(items) > MAX_TERMS_CHECKS:
        raise ValueError(f"brief.access_policy.terms_checked must be a list of at most {MAX_TERMS_CHECKS} checks")
    for item in items:
        if not isinstance(item, dict) or set(item) - set(CHECK_FIELDS):
            raise ValueError("each terms check is {host, terms_url, checked_on, result} with an optional note and an "
                             "optional permission {granted_by, granted_on, reference}")
        for key in CHECK_REQUIRED:
            if not isinstance(item.get(key), str) or not item[key].strip():
                raise ValueError(f"a terms check needs a non-empty {key}")
        if valid_host(item["host"]) is None:
            raise ValueError(f"terms check host {item['host']!r} must be a host name, without a scheme or a path")
        url = item["terms_url"].strip()
        try:
            parts = urlsplit(url)
            ok = parts.scheme in ("http", "https") and bool(parts.hostname) and len(url) <= 2000 \
                and not re.search(r"\s", url)
        except ValueError:
            ok = False
        if not ok:
            raise ValueError("a terms check's terms_url must be the http(s) address of the terms the user read "
                             "(with the clause's anchor when there is one)")
        checked = _valid_date(item["checked_on"])
        if checked is None:
            raise ValueError("a terms check's checked_on must be a date, YYYY-MM-DD")
        if checked > today:
            raise ValueError(f"a terms check's checked_on ({item['checked_on']}) cannot be after today")
        # `today` is a day ahead of UTC, so a check exactly MAX_CHECK_AGE_DAYS old in the user's zone still passes
        if (today - checked).days > MAX_CHECK_AGE_DAYS + 1:
            raise ValueError(f"the terms check for {item['host']} is stale ({item['checked_on']}, more than "
                             f"{MAX_CHECK_AGE_DAYS} days old): read the current terms again and record the new date")
        if item["result"] not in CHECK_RESULTS:
            raise ValueError(f"a terms check's result must be one of {', '.join(CHECK_RESULTS)}")
        if "note" in item and (not isinstance(item["note"], str) or not item["note"].strip()):
            raise ValueError("a terms check's note must be non-empty text when given")
        if "permission" in item:
            permission = item["permission"]
            if not isinstance(permission, dict) or set(permission) != set(PERMISSION_FIELDS):
                raise ValueError("a terms check's permission is {granted_by, granted_on, reference}: who granted the "
                                 "written permission, the date (YYYY-MM-DD) and the letter's or agreement's reference")
            for key in PERMISSION_FIELDS:
                value = permission.get(key)
                if not isinstance(value, str) or not value.strip() or len(value) > 300:
                    raise ValueError(f"a terms check's permission needs a non-empty {key} of at most 300 characters")
            granted = _valid_date(permission["granted_on"])
            if granted is None or granted > today:
                raise ValueError("a terms check's permission.granted_on must be a date (YYYY-MM-DD), not after today")
    seen: dict = {}
    for index, item in enumerate(items, 1):
        host = valid_host(item["host"])
        if host in seen and seen[host][1]["result"] != item["result"]:
            first_index, first = seen[host]
            raise ValueError(
                f"two terms checks for {host} disagree: check {first_index} says {first['result']} "
                f"({first['terms_url']}, {first['checked_on']}) and check {index} says {item['result']} "
                f"({item['terms_url']}, {item['checked_on']}); keep only the one that is true")
        seen.setdefault(host, (index, item))


def validate_lifts(policy: dict, lists: Lists) -> None:
    """The checks against the run's terms entries, for `start`: a check that would lift an entry whose terms need
    prior written permission must record that permission, and a check dated before an entry's restriction came
    into force is refused. Raises ValueError saying what is missing."""
    for item in policy.get("terms_checked") or []:
        if item.get("result") != LIFTING_RESULT:
            continue
        for entry in lists.terms:
            if _requires(entry) == "never" or not check_applies(item, entry):
                continue
            since = entry.get("effective_from")
            if isinstance(since, str) and str(item.get("checked_on") or "") < since:
                raise ValueError(f"the terms check for {item['host']} ({item['checked_on']}) predates the "
                                 f"restriction {entry.get('id')} in force since {since}: read the current terms "
                                 "again and record the new date")
            if _requires(entry) == "written_permission" and not isinstance(item.get("permission"), dict):
                raise ValueError(f"the terms check for {item['host']} cites the terms of {entry.get('id')}, which "
                                 "forbid automated collection without prior written permission: a lift needs "
                                 "permission {granted_by, granted_on, reference} in the check (who granted the "
                                 "written permission, when, and the letter's or agreement's reference); without "
                                 "it, remove the check or set its result to restricts_this_reading")


def normalize_checks(items) -> list:
    out = []
    for item in items or []:
        value = {"host": item["host"].strip().lower().rstrip("."), "terms_url": item["terms_url"].strip(),
                 "checked_on": item["checked_on"], "result": item["result"]}
        if item.get("note"):
            value["note"] = item["note"].strip()
        if isinstance(item.get("permission"), dict):
            value["permission"] = {k: item["permission"][k].strip() for k in PERMISSION_FIELDS}
        out.append(value)
    return out


# ---------------------------------------------------------------- route tables


def _covers(pattern_hosts, other_hosts) -> bool:
    """True when two host lists overlap: a host of one is, or lies under, a host of the other."""
    def plain(host: str) -> str:
        return host[2:] if host.startswith("*.") else host
    for a in pattern_hosts:
        for b in other_hosts:
            if verdict.host_matches(plain(a), [plain(b)]) or verdict.host_matches(plain(b), [plain(a)]):
                return True
    return False


def check_run_table(run_routes: dict) -> list:
    """What a route table given with `start --routes` may not do, as messages (empty when it may be used):
    redefine a packaged terms_restricted, discovery or third-party-copy entry (same id, other content); name an
    official_route in its own terms entries (official-only mode reads the packaged table only); or add or change
    a platform for a host a packaged terms entry covers, or the platform a packaged terms entry names as its
    official route, unless it is an unchanged copy of the packaged platform."""
    base = packaged()
    problems: list = []
    for table in (base,) if run_routes is base else (base, run_routes):
        for item in _items(table, "terms_restricted"):
            if item.get("lift_requires") not in LIFT_REQUIREMENTS:
                problems.append(f"terms_restricted entry {item.get('id')} needs an explicit lift_requires "
                                f"({', '.join(LIFT_REQUIREMENTS)}); a missing or unknown value is never liftable")
    if not isinstance(run_routes, dict) or run_routes is base:
        return problems
    for name in ("terms_restricted", "discovery", "third_party_copies"):
        ours = {str(item.get("id")): item for item in _items(base, name)}
        for item in _items(run_routes, name):
            packaged_item = ours.get(str(item.get("id")))
            if packaged_item is not None and item != packaged_item:
                problems.append(f"the route table redefines the packaged {name} entry {item.get('id')}: a route table "
                                "can add entries but never change or remove a packaged one; leave it out (the "
                                "packaged entry always applies) or copy it unchanged")
    for item in _items(run_routes, "terms_restricted"):
        if str(item.get("id")) not in {str(e.get("id")) for e in _items(base, "terms_restricted")} \
                and item.get("official_route"):
            problems.append(f"the route table's own terms_restricted entry {item.get('id')} names an official_route: "
                            "official-only mode reads only the packaged route table, so a route table's own entry "
                            "cannot open one; set official_route to null")
    terms = [e for e in _items(base, "terms_restricted") if _host_patterns(e.get("hosts"))]
    named = {e.get("official_route"): e.get("id") for e in terms if e.get("official_route")}
    platforms = {str(p.get("id")): p for p in _items(base, "platforms")}
    for platform in _items(run_routes, "platforms"):
        pid = str(platform.get("id"))
        hosts = _host_patterns(platform.get("hosts"))
        restricted = [e.get("id") for e in terms if _covers(hosts, _host_patterns(e.get("hosts")))]
        if pid in named:
            restricted.append(named[pid])
        if restricted and platform != platforms.get(pid):
            problems.append(f"the route table adds or changes routes for the platform {pid}, whose hosts or official "
                            f"route belong to the packaged terms_restricted entry {', '.join(dict.fromkeys(restricted))}: "
                            "a route table may add platforms for other hosts only; leave this one out (official-only "
                            "mode always reads the packaged platform) or copy the packaged platform unchanged")
    return problems


__all__ = ["Lists", "ScopeStop", "lists_for", "evaluate", "lifted_host", "lifted_entries", "terms_entry",
           "terms_entries", "terms_record", "lift_record", "combine", "check_applies", "describe_checks",
           "describe_lifts", "validate_checks", "validate_lifts", "normalize_checks", "check_run_table", "path_under",
           "path_forms", "packaged", "registrable_domain", "site_of", "official_route", "valid_host",
           "LIFTED_HOST_BUDGET", "CHECK_RESULTS", "LIFTING_RESULT", "STATUSES", "RESTRICTS", "KINDS",
           "LIFT_REQUIREMENTS", "PERMISSION_FIELDS"]
