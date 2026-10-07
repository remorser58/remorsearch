"""The reader ladder for one public URL, and `ingest` for render captures.

Rungs, cheapest and most honest first. Each runs at most once per URL:

  R0 official_route  the route table's feeds or oEmbed for this host
                     (data/routes.json); at most 2 requests. An unverified route
                     that fails, for example with a 404, falls through. An 'api'
                     route is read only by the adapter it names (uxresearch/
                     <adapter>.py, see route_adapter), with its own request cap
                     and no redirects; an 'api' route with no adapter is skipped.
  R1 honest_ua       one GET with the identifying User-Agent and the brief's
                     Accept-Language. No Referer, no cookies.
  R2 site_alternate  the page's own declared mobile, AMP or feed alternate on the
                     same registrable domain, then the route table's twins, then a
                     generic www.-to-m. rewrite only if that name resolves; at most
                     2 requests. A JSON-LD body is used on any rung when it is
                     longer than the visible text.
  R3 real_browser    an unmodified browser render in an anonymous context. The
                     researcher's own browser, or the bundled page reader
                     (drivers/web/read_page.mjs), renders the page and the capture
                     is handed in with `ingest`; `read` exits 4 and says how. A
                     community the brief authorises may be captured signed in.

Before any rung, and before any DNS lookup, the page's own URL goes through the
scope checks (scope.py): the deny list, search results pages, switched-off
discovery endpoints and third-party copies such as archives and reader proxies
(refused with exit 2; a copy of a stopped URL stops like it), the route table's
out-of-scope private channels, and terms_restricted hosts. A terms_restricted
host is never requested, not even for robots.txt, unless the user's own terms
checks lifted every entry that covers it for the run (then each lifted entry has
a budget of 10 documents); lift_requires: never prohibits a page lift. When the
packaged entry names an official route whose kind has an adapter and whose key is
set, only that route of the PACKAGED route table runs (official-only mode: R0, no
page request, no alternate, no render capture); if it fails, the URL ends as
terms_restricted with official_route_failed. Then the page's own robots.txt: a
disallowed path stops there, so no official route or alternate is read for it.
robots.txt groups naming other AI agents that fetch for a user
(data/agent-tokens.json) are honoured as if they named our own token when no
group names it; training and AI-search crawler groups are a recorded signal.
Escalation happens only on js_shell or suspect. A site that refuses our honest
request (bot_filter: a 4xx or a block notice) or shows a browser check (js_check,
even one that would clear by itself) is a stop, opted_out, never escalated, and
the whole site stops for the run. Any stop class ends the URL. The whole site
(scope.site_of: m., www. and the apex alike) stops for the run on any human
check, bot filter or browser check, on a second rate-limit signal (a status or a
notice), after three URLs in a row that no allowed rung could read (a URL still
waiting for its render does not count), and on a challenge page served instead
of robots.txt. robots.txt that cannot be fetched (5xx, 429, network failure)
disallows everything for now: the URL is deferred until it is checked again. A
robots.txt redirect is followed only to hosts the scope checks allow and that are
not stopped; a hop anywhere else is never requested, and robots.txt then
disallows the whole origin for the run, as it does after a redirect loop. Every
request, redirect hop, official route and alternate goes through the same checks
as a new URL: the scope checks and robots.txt; a redirect into a search page, a
switched-off endpoint, a private channel or a terms_restricted host is a stop.
Redirects are followed only within one origin and only to paths robots.txt
allows; a redirect to a login page is an auth_gate stop, and a redirect loop is
an opted_out stop (redirect_loop), never escalated.

Page text is scrubbed of personal identifiers (privacy.scrub) before it is
printed, saved or scanned, in `read` and `ingest` alike (an adapter scrubs each
free-text field itself, so its structured headers stay intact).

Keys (D6) come only from REMORSEARCH_* environment variables, plus the older
names the packaged route table lists as aliases. A key the packaged table names
is sent only to the hosts that table names for it, whatever route table a run
uses (key_for), so no table given with `start --routes` can send it elsewhere.
"""
from __future__ import annotations

import functools
import hashlib
import importlib
import json
import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qsl, quote, urlsplit

from . import ROBOTS_TOKEN, USER_AGENT, extract, net, privacy, robots, scope, verdict
from .flags import metadata as capture_metadata, captured as research_flags
from .envelope import scan as scan_injection
from .ledger import ROBOTS_RETRY_S, BudgetExceeded, Deferred, HostStopped, Run, RunError

DATA = Path(__file__).resolve().parent / "data"
PRESENTATION = {"R0": "official_route", "R1": "honest_ua", "R2": "site_alternate", "R3": "real_browser"}
RUNGS = tuple(PRESENTATION)
IMPLEMENTED_ROUTE_KINDS = ("feed", "oembed")  # official route kinds this version can read; 'api' needs an adapter
ADAPTER_KINDS = ("api",)  # route kinds read only by the adapter module the route names (route_adapter)
ADAPTER_API = 1  # the adapter contract: a module-level ADAPTER_API == 1 and read_route(st, platform, route, values)
KEY_ENV = re.compile(r"^REMORSEARCH_[A-Z0-9_]{1,80}$")
_ADAPTER_NAME = re.compile(r"^[a-z][a-z0-9_]{0,40}$")
R0_MAX_REQUESTS = 2
R2_MAX_REQUESTS = 2
EXIT = {"read": 0, "refused": 2, "stopped": 3, "unread": 4, "deferred": 5}
TRANSIENT_RETRY_S = 120
INGEST_MAX_BYTES = 8 * 1024 * 1024
PAGE_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
FEED_ACCEPT = "application/rss+xml,application/atom+xml,application/xml;q=0.9,text/xml;q=0.9,*/*;q=0.5"
JSON_ACCEPT = "application/json;q=1.0,*/*;q=0.5"
ROBOTS_ACCEPT = "text/plain,*/*;q=0.5"
HTML_TYPES = frozenset({"text/html", "application/xhtml+xml"})
FEED_TYPES = frozenset({"application/rss+xml", "application/atom+xml", "application/xml", "text/xml"})
INGEST_HELP = ("Render it yourself: open the URL in a private or signed-out browser window (a signed-in session "
               "only for a community the brief authorises) and scroll only (no typing, no clicks). If the page shows "
               "any check at all, a 'checking your browser' page that would clear by itself included, stop there: "
               "never wait for it to clear and never capture it. Otherwise save the page as HTML or copy its text, "
               "then run: ux_research.py ingest --run RUN --url URL --file FILE --context anonymous")
DRIVER_NOTE = ("render with the bundled page reader (node drivers/web/read_page.mjs URL --out capture.json), then pass "
               "the capture to ingest; a capture that shows or waited out a check is refused")
AUTHORISED_NOTE = ("member content from an authorised community: shared outputs keep authored summaries only "
                   "(no quotes, no post URLs, no member's personal data)")
ROBOTS_UNREACHABLE = ("robots.txt could not be fetched (5xx, 429 or a network failure), so nothing may be read "
                      "there until it is checked again")
CONTEXTS = ("anonymous", "unknown", "signed_in")


# ---------------------------------------------------------------- site data


def registrable_domain(host: str) -> str:
    """The registrable domain, honouring multi-label and hosting suffixes (data/suffixes.json)."""
    return scope.registrable_domain(host)


_TEMPLATE_VAR = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def expand(template: str, values: dict) -> str | None:
    missing: list[str] = []

    def replace(match: re.Match) -> str:
        if match.group(1) not in values:
            missing.append(match.group(1))
            return ""
        return str(values[match.group(1)])

    result = _TEMPLATE_VAR.sub(replace, template)
    return None if missing else result


def _variables(url: str, groups: dict) -> dict:
    parts = urlsplit(url)
    host = parts.hostname or ""
    values = {"scheme": parts.scheme, "host": host, "port_suffix": f":{parts.port}" if parts.port else "",
              "path": parts.path or "/", "query": parts.query, "url_enc": quote(url, safe=""),
              "registrable": registrable_domain(host)}
    values.update(groups)
    for name, value in parse_qsl(parts.query):
        if re.fullmatch(r"[A-Za-z0-9_]{1,40}", name):
            values.setdefault(f"q_{name}", quote(value, safe=""))
    return values


def _template_host(template) -> str | None:
    """The host a URL template names, or None when a template variable is part of it."""
    if not isinstance(template, str) or "://" not in template:
        return None
    scheme, rest = template.split("://", 1)
    authority = re.split(r"[/?#]", rest, maxsplit=1)[0]
    if "{" in scheme or "{" in authority:
        return None
    try:
        host = urlsplit(f"{scheme}://{authority}").hostname
    except ValueError:
        return None
    return host.lower().rstrip(".") if host else None


@functools.lru_cache(maxsize=1)
def _packaged_keys() -> tuple[dict, dict]:
    """({env: the aliases listed for it}, {env or alias: the hosts it may be sent to}), from the packaged
    route table's user_key official routes (their url and *_url templates) and discovery entries."""
    data = scope.packaged()
    aliases: dict = {}
    hosts: dict = {}

    def bind(names, extra, templates) -> None:
        names = [n for n in names or [] if isinstance(n, str) and n]
        extra = [a for a in extra or [] if isinstance(a, str) and a]
        found = {h for h in (_template_host(t) for t in templates) if h}
        for name in names:
            aliases.setdefault(name, set()).update(extra)
        for name in names + extra:
            hosts.setdefault(name, set()).update(found)

    for platform in data.get("platforms", []):
        for route in platform.get("official") or [] if isinstance(platform, dict) else []:
            if isinstance(route, dict) and route.get("auth") == "user_key":
                bind([route.get("env")], route.get("env_aliases"),
                     [v for k, v in route.items() if k == "url" or k.endswith("_url")])
    for entry in data.get("discovery", []):
        auth = entry.get("auth") if isinstance(entry, dict) and isinstance(entry.get("auth"), dict) else {}
        endpoints = entry.get("endpoints") if isinstance(entry.get("endpoints"), dict) else {}
        if auth.get("type") == "user_key":
            bind(auth.get("env"), auth.get("env_aliases"), list(endpoints.values()))
    return ({k: frozenset(v) for k, v in aliases.items()}, {k: frozenset(v) for k, v in hosts.items()})


def _key_names(route: dict) -> list:
    """The variables a user_key route may read, in order: its 'env' (REMORSEARCH_* only), then those of
    its 'env_aliases' that are REMORSEARCH_* names or that the packaged route table lists for that env
    (D6). Any other name in a route table is never read."""
    env = route.get("env")
    if not isinstance(env, str) or not KEY_ENV.match(env):
        return []
    listed = _packaged_keys()[0].get(env, frozenset())
    names = [env]
    for alias in route.get("env_aliases") or []:
        if isinstance(alias, str) and alias not in names and (KEY_ENV.match(alias) or alias in listed):
            names.append(alias)
    return names


def _user_key(route: dict) -> tuple[str | None, str, str | None]:
    """(the user's key or None; the variable to ask for; the variable the key came from)."""
    names = _key_names(route)
    primary = names[0] if names else str(route.get("env") or "unset")
    for name in names:
        value = os.environ.get(name)
        if value:
            return value, primary, name
    return None, primary, None


def user_key(route: dict) -> tuple[str | None, str]:
    """(the user's key for a user_key route, or None; the variable name to ask for). The route's 'env'
    (always REMORSEARCH_*) is read first, then its accepted 'env_aliases' (_key_names). The value is
    never stored or logged."""
    value, primary, _ = _user_key(route)
    return value, primary


_KEY_SLOT = re.compile(r"[?&]([A-Za-z0-9_.-]{1,40})=\{key\}(?=&|#|$)")


def _key_slots_ok(route: dict) -> bool:
    """True when every URL template of the route that carries {key} carries it once, as the value of a
    query parameter that recorded URLs mask (privacy.masks_param), so the key never shows in a ledger
    entry, a trail or a result."""
    for name, template in route.items():
        if (name == "url" or name.endswith("_url")) and isinstance(template, str) and "{key}" in template:
            found = _KEY_SLOT.search(template)
            if template.count("{key}") != 1 or not found or not privacy.masks_param(found.group(1)):
                return False
    return True


def key_for(route: dict, url: str) -> tuple[str | None, str | None]:
    """(the user's key for a request to `url`, or None; why it is withheld, or None). A key the packaged
    route table names is sent only to the hosts the packaged table names for it, whatever route table
    the run uses: 'official_route_key_host:<ENV>'. No key: 'official_route_needs_key:<ENV>'. A template
    that would put the key anywhere but a masked query parameter: 'official_route_unavailable'."""
    if not _key_slots_ok(route):
        return None, "official_route_unavailable"
    value, primary, source = _user_key(route)
    if value is None:
        return None, f"official_route_needs_key:{primary}"
    bound = _packaged_keys()[1].get(source)
    if bound is not None and net.host_of(url).lower().rstrip(".") not in bound:
        return None, f"official_route_key_host:{primary}"
    return value, None


def withheld_note(reason: str, env: str) -> str:
    """The trail note for a key that key_for withheld."""
    if reason.startswith("official_route_needs_key"):
        return f"no user key in ${env}"
    if reason.startswith("official_route_key_host"):
        return f"the key in ${env} is sent only to the hosts the packaged route table names for it"
    return f"the route would record the key in ${env}: its templates must carry {{key}} as a masked query parameter"


def key_status(routes: dict) -> list:
    """For `start`: every key a user_key official route of this route table, or of the packaged platforms
    official-only mode reads, uses: the routes that use it and whether it is set, with the variable it came
    from. Never the value."""
    rows: dict = {}
    platforms = list(routes.get("platforms") or [] if isinstance(routes, dict) else [])
    named = {e.get("official_route") for e in scope.packaged().get("terms_restricted") or [] if isinstance(e, dict)}
    ids = {p.get("id") for p in platforms if isinstance(p, dict)}
    platforms += [p for p in scope.packaged().get("platforms") or []
                  if isinstance(p, dict) and p.get("id") in named and p.get("id") not in ids]
    for platform in platforms:
        for route in platform.get("official") or [] if isinstance(platform, dict) else []:
            if not isinstance(route, dict) or route.get("auth") != "user_key":
                continue
            value, primary, source = _user_key(route)
            row = rows.setdefault(primary, {"env": primary, "routes": [], "set": False, "from": None})
            if platform.get("id") not in row["routes"]:
                row["routes"].append(platform.get("id"))
            if value and not row["set"]:
                row["set"], row["from"] = True, source
    return list(rows.values())


def route_adapter(route: dict):
    """The adapter module an 'api' route names in its 'adapter' field (uxresearch/<adapter>.py), or None
    when this version has no such adapter. Only a module that declares ADAPTER_API and read_route counts,
    so a route table can pick among the shipped adapters but never run other code."""
    if not isinstance(route, dict) or route.get("kind") not in ADAPTER_KINDS:
        return None
    name = route.get("adapter")
    if not isinstance(name, str) or not _ADAPTER_NAME.match(name):
        return None
    try:
        module = importlib.import_module(f"{__package__}.{name}")
    except ImportError:
        return None
    if getattr(module, "ADAPTER_API", None) != ADAPTER_API or not callable(getattr(module, "read_route", None)):
        return None
    return module


def route_readiness(route: dict) -> list[str]:
    """Why an official route cannot run in this version ([] when it can): 'official_route_unavailable'
    for a kind with no adapter, 'official_route_needs_key:<ENV>' when the user's key is missing."""
    why = []
    if (route.get("kind") not in IMPLEMENTED_ROUTE_KINDS and route_adapter(route) is None) or \
            (route.get("auth") == "user_key" and not _key_slots_ok(route)):
        why.append("official_route_unavailable")
    if route.get("auth") == "user_key":
        value, primary = user_key(route)
        if value is None:
            why.append(f"official_route_needs_key:{primary}")
    return why


def _path_pattern(platform: dict, host: str) -> str | None:
    """The platform's path pattern for this host: the path_by_host entry of the most specific host name
    that covers it (such as a short-link host whose paths differ), else 'path'."""
    by_host = platform.get("path_by_host") if isinstance(platform.get("path_by_host"), dict) else {}
    chosen = None
    for name, pattern in by_host.items():
        if isinstance(pattern, str) and verdict.host_matches(host, [name]) and (chosen is None or
                                                                                 len(name) > len(chosen[0])):
            chosen = (name, pattern)
    return chosen[1] if chosen else platform.get("path")


class Routes:
    def __init__(self, data: dict):
        self.platforms = [p for p in data.get("platforms", []) if isinstance(p, dict)]
        self.lists = scope.lists_for(data)  # the packaged scope lists plus this table's own
        self.login_hosts = sorted({h for p in self.platforms for h in p.get("login_hosts", []) if h})

    @staticmethod
    def _fit(platform: dict, url: str) -> dict | None:
        """The URL's template variables when the platform reads this URL, else None."""
        parts = urlsplit(url)
        host = parts.hostname or ""
        if not verdict.host_matches(host, platform.get("hosts", [])):
            return None
        groups: dict = {}
        pattern = _path_pattern(platform, host)
        if pattern:
            found = re.match(pattern, parts.path or "/")
            if not found:
                return None
            groups = {k: v for k, v in found.groupdict().items() if v is not None}
        return _variables(url, groups)

    def match(self, url: str) -> tuple[dict | None, dict]:
        for platform in self.platforms:
            values = self._fit(platform, url)
            if values is not None:
                return platform, values
        return None, {}

    def match_platform(self, platform_id: str, url: str) -> tuple[dict | None, dict]:
        """(the platform with this id, the URL's variables) when that platform reads the URL."""
        for platform in self.platforms:
            if platform.get("id") == platform_id:
                values = self._fit(platform, url)
                return (platform, values) if values is not None else (None, {})
        return None, {}


def packaged_routes() -> Routes:
    """The packaged route table: the only table official-only mode reads (a run's own table never can)."""
    return Routes(scope.packaged())


# ---------------------------------------------------------------- one request


@dataclass
class _Read:
    run: Run
    url: str
    expect: tuple
    max_wait: float
    routes: Routes
    trail: list = field(default_factory=list)
    contacted: bool = False
    target_robots: dict | None = None
    terms: dict | None = None  # the terms record of the page's host: lifted, or the stop's (scope.terms_record)
    route_reasons: list = field(default_factory=list)  # why official routes could not serve this URL


@dataclass
class _Attempt:
    url: str
    rung: str
    purpose: str
    response: net.Response | None = None
    fetch_id: str | None = None
    error: str | None = None
    error_detail: str = ""
    stop: str | None = None
    reasons: list = field(default_factory=list)
    contacted: bool = False
    chain: list = field(default_factory=list)
    robots: dict | None = None
    waited_s: float = 0.0
    retry_after_s: int | None = None
    scope: bool = False  # stopped by a scope check (scope.py), before any request
    out_of_scope: bool = False
    scope_stop: scope.ScopeStop | None = None


def _headers(run: Run, accept: str) -> dict:
    return {"User-Agent": USER_AGENT, "Accept": accept, "Accept-Language": run.policy["accept_language"]}


def _looks_html(response: net.Response) -> bool:
    if response.content_type in HTML_TYPES:
        return True
    head = response.body[:1024].lstrip().lower()
    return head.startswith((b"<!doctype html", b"<html")) or b"<body" in head


def _robots_brief(decision: dict | None) -> dict | None:
    if not decision:
        return None
    return {k: decision.get(k) for k in ("allowed", "decision", "robots_status", "http_status", "group", "rule",
                                         "sha256", "crawl_delay", "ai_agent_token", "ai_training_disallow",
                                         "reason")}


def scope_check(run: Run, routes: Routes, url: str) -> tuple[scope.ScopeStop | None, dict | None]:
    """(why this URL is never requested, or None; the terms record of a lifted entry, or None).
    Decided from the URL alone, before any DNS lookup, robots.txt, slot or request (scope.py)."""
    return scope.evaluate(url, run.policy, routes.lists)


def scope_stop(run: Run, routes: Routes, url: str) -> scope.ScopeStop | None:
    """Why this URL is never requested (scope.py), or None."""
    return scope_check(run, routes, url)[0]


def _hop_refusal(run: Run, target: str, terms: list | None = None) -> str | None:
    """Why a robots.txt redirect hop is never requested: a scope stop (deny list, search page, switched-off
    endpoint, third-party copy, private channel, terms restriction) or a stopped host or site."""
    stop = scope.evaluate(target, run.policy, run.scope_lists)[0]
    if stop is not None:  # the terms entry by name when there is one, else the first reason
        if stop.terms and terms is not None:
            terms.append(_terms_brief(stop.terms))
        first = next((r for r in stop.reasons if r.startswith("terms_entry:")), None) or \
            (stop.reasons[0] if stop.reasons else stop.stop_class)
        return first if first.startswith((stop.kind + ":", "terms_entry:")) else f"{stop.kind}:{first}"
    stopped = run.host_stop(net.host_of(target))
    return f"host_stop:{stopped.get('class')}" if stopped else None


def robots_decision(run: Run, url: str, max_wait: float) -> dict:
    """Fetch robots.txt for the URL's origin once per run (paced, not charged) and decide. Every redirect hop
    gets the scope checks and the host stops first; a hop they refuse is never requested, and robots.txt then
    disallows the whole origin for the run (unavailable_redirect), as after a redirect loop. A challenge or
    block page served instead of the file disallows the whole origin too (unavailable_bot_filtered) and stops
    the whole site for the run (opted_out, 'bot_filter:' or 'js_check:')."""
    origin = net.origin_of(url)
    record = run.robots_record(origin)
    if record is None:
        host = net.host_of(url)
        slot = run.acquire(host, "policy", max_wait)
        fetch_id = run.new_fetch_id()
        response, failure = None, None
        refused: list = []
        refused_terms: list = []
        entry = {"kind": "request", "purpose": "robots", "fetch_id": fetch_id, "url": origin + "/robots.txt",
                 "host": host, "waited_s": round(slot.waited, 3)}

        def follow(source: str, target: str) -> bool:
            why = _hop_refusal(run, target, refused_terms)
            if why:
                refused.append(why)
                return False
            return True

        try:
            try:
                response = net.fetch(origin + "/robots.txt", headers=_headers(run, ROBOTS_ACCEPT),
                                     max_wire=robots.PARSE_LIMIT_BYTES, max_decoded=robots.PARSE_LIMIT_BYTES,
                                     truncate=True, on_redirect=follow)
            except net.NetError as exc:
                failure = exc
            if failure is not None and (failure.kind in net.REFUSAL_KINDS or failure.kind in ("dns_error", "tls_error")):
                run.log({**entry, "error": failure.kind, "redirects": failure.redirects})
                raise failure
            challenge = None
            refused_hop = refused[0] if refused and response is not None and response.location is not None else None
            parsed = response is not None and 200 <= response.status < 300 and \
                robots.looks_like_robots(response.body[:robots.PARSE_LIMIT_BYTES].decode("utf-8", "replace"))
            if response is not None and not refused_hop and not parsed and _looks_html(response):
                # Only a body with no robots.txt lines can be a challenge page: words in a real file's
                # comments never override its rules.
                challenge = verdict.robots_challenge_kind(response.status,
                                                          extract.from_html(response.text()[0], response.final_url))
            record = robots.record_from_fetch(origin, status=response.status if response else None,
                                              body=response.body if response and not refused_hop else b"",
                                              error=failure.kind if failure else None, challenge=challenge or False,
                                              token=ROBOTS_TOKEN, fetched_at=run.now_iso(),
                                              agent_tokens=run.agent_tokens(), refused_redirect=refused_hop)
            run.store_robots(origin, host, record)  # before release, so a Crawl-delay paces the next request
        finally:
            run.release(slot)
        if response is not None:
            entry.update(status=response.status, wire_bytes=response.wire_bytes, elapsed_ms=response.elapsed_ms,
                         redirects=response.redirects, via_proxy=response.via_proxy, precheck=response.precheck,
                         test_override=response.test_override)
        elif failure is not None:
            entry["redirects"] = failure.redirects
        agents = record.get("agents") or {}
        run.log({**entry, "error": failure.kind if failure else None, "robots_status": record["status"],
                 "robots_reason": record.get("reason"),
                 "terms": refused_terms[0] if refused_terms else None,
                 "sha256": record["sha256"], "crawl_delay": record["crawl_delay"],
                 "ai_agent_groups": sorted(agents.get("fetch_on_behalf") or {}) or None,
                 "ai_training_groups": sorted(agents.get("training_or_index") or {}) or None})
        if record["status"] == "unavailable_bot_filtered":  # the site showed our honest client a check: it stops
            run.stop_host(host, "opted_out", "a challenge or block page was served instead of robots.txt",
                          [record.get("reason") or "bot_filter:robots_txt"])
    decision = {"origin": origin, **robots.decide(record, url)}
    if decision["robots_status"] == "unreachable":  # disallowed for now; checked again after ROBOTS_RETRY_S
        stored = float(record.get("stored_at") or run.clock())
        decision["retry_after_s"] = max(1, int(math.ceil(ROBOTS_RETRY_S - (run.clock() - stored))))
    return decision


def _robots_reasons(decision: dict) -> list:
    rule = decision.get("rule") or {}
    reasons = [f"robots.txt:{rule.get('type', 'disallow')} {rule.get('pattern', '')}".strip(),
               f"robots_status:{decision['robots_status']}"]
    if decision.get("reason"):  # a challenge page ('bot_filter:robots_txt'), a refused hop or a redirect loop
        reasons.insert(0, decision["reason"] if decision.get("challenge") else f"robots_redirect:{decision['reason']}")
    if decision.get("ai_agent_token"):  # a group naming another AI agent that fetches for a user
        reasons.append(f"robots:ai_agent:{decision['ai_agent_token']}")
    return reasons


def _request(st: _Read, url: str, rung: str, *, accept: str = PAGE_ACCEPT, purpose: str = "page",
             redirects: bool = True) -> _Attempt:
    """Deny list and out-of-scope check, robots.txt, a paced slot, one GET; same-origin redirects
    only; login redirects stop. Every hop gets the same checks as a new URL. With redirects=False (an
    official API call) no redirect is followed at all: the attempt ends with error redirect_refused."""
    run = st.run
    attempt = _Attempt(url=url, rung=rung, purpose=purpose)
    requested_login = verdict.is_login_url(url, st.routes.login_hosts)
    current = url
    hops = 0
    while True:
        parts = urlsplit(current)
        excluded = scope_stop(run, st.routes, current)  # before any slot, robots.txt or request
        if excluded:
            attempt.stop, attempt.out_of_scope = excluded.stop_class, excluded.out_of_scope
            attempt.reasons = list(excluded.reasons) + (["reached_by_redirect"] if current != url else [])
            attempt.scope, attempt.scope_stop = True, excluded
            return attempt
        try:
            net.check_host(parts.hostname or "", parts.port or (443 if parts.scheme == "https" else 80))
        except net.NetError as exc:
            if exc.kind in net.REFUSAL_KINDS:
                raise
        decision = robots_decision(run, current, st.max_wait)
        attempt.robots = decision
        if not decision["allowed"]:
            if decision["robots_status"] == "unreachable":
                attempt.error, attempt.error_detail = "robots_unreachable", ROBOTS_UNREACHABLE
                attempt.retry_after_s = decision.get("retry_after_s")
                return attempt
            attempt.stop, attempt.reasons = "opted_out", _robots_reasons(decision)
            return attempt
        host = net.host_of(current)
        origin = net.origin_of(current)
        slot = run.acquire(host, "doc", st.max_wait)
        attempt.waited_s += slot.waited
        fetch_id = run.new_fetch_id()

        def follow(source: str, target: str, origin: str = origin) -> bool:
            if not redirects or net.origin_of(target) != origin or verdict.is_legal_block_url(target):
                return False
            if scope_stop(run, st.routes, target):
                return False
            if not requested_login and verdict.is_login_url(target, st.routes.login_hosts):
                return False
            record = run.robots_record(origin)
            return record is not None and robots.decide(record, target)["allowed"]

        entry = {"kind": "request", "purpose": purpose, "fetch_id": fetch_id, "rung": rung,
                 "presentation": PRESENTATION[rung], "url": current, "host": host}
        try:  # the slot is released whatever happens, so a failure never leaves the host leased
            response = net.fetch(current, headers=_headers(run, accept),
                                 max_redirects=max(0, net.MAX_REDIRECTS - hops), on_redirect=follow)
        except net.NetError as exc:
            attempt.error, attempt.error_detail = exc.kind, exc.detail
            attempt.chain.extend(exc.redirects)
            attempt.contacted = attempt.contacted or exc.kind in ("too_large", "redirect_loop", "protocol_error",
                                                                  "decode_error", "unsupported_encoding")
            st.contacted = st.contacted or attempt.contacted
            run.log({**entry, "error": exc.kind, "redirects": exc.redirects, "waited_s": round(slot.waited, 3)})
            return attempt
        finally:
            run.release(slot)
        attempt.contacted = st.contacted = True
        attempt.chain.extend(response.redirects)
        hops += len(response.redirects)
        if response.location is None:
            attempt.response, attempt.fetch_id = response, fetch_id
            return attempt
        run.log({**entry, "status": response.status, "location": response.location, "redirects": response.redirects,
                 "wire_bytes": response.wire_bytes, "elapsed_ms": response.elapsed_ms,
                 "waited_s": round(slot.waited, 3), "test_override": response.test_override,
                 "precheck": response.precheck})
        if not requested_login and verdict.is_login_url(response.location, st.routes.login_hosts):
            attempt.stop, attempt.reasons = "auth_gate", ["redirect:login_page"]
            return attempt
        if not redirects:  # an official API answers or fails; its redirects are never followed, to any origin
            attempt.error, attempt.error_detail = "redirect_refused", "the official route answered with a redirect"
            return attempt
        if verdict.is_legal_block_url(response.location):
            attempt.stop, attempt.reasons = "legal_block", ["redirect:legal_block_host"]
            return attempt
        current = response.location  # another origin, or a same-origin path robots.txt disallows


def _scrubbed(page) -> tuple[str, dict]:
    """The page text scrubbed of personal identifiers, and the counts; computed once per page."""
    cached = getattr(page, "_scrubbed_cache", None)
    if cached is None:
        cached = privacy.scrub(page.text)
        page._scrubbed_cache = cached
    return cached


def _log_attempt(run: Run, attempt: _Attempt, v: verdict.Verdict | None = None, page=None,
                 extra: dict | None = None) -> None:
    """One request entry for a response; `extra` adds fields (an adapter's api_method and quota_units). Its
    text size and hash are of the scrubbed text, like the outcome's: nothing kept refers to raw page text."""
    response = attempt.response
    entry = {"kind": "request", "purpose": attempt.purpose, "fetch_id": attempt.fetch_id, "rung": attempt.rung,
             "presentation": PRESENTATION[attempt.rung], "url": attempt.url, "final_url": response.final_url,
             "host": net.host_of(response.final_url), "status": response.status,
             "content_type": response.content_type, "wire_bytes": response.wire_bytes,
             "elapsed_ms": response.elapsed_ms, "waited_s": round(attempt.waited_s, 3),
             "redirects": response.redirects, "via_proxy": response.via_proxy, "precheck": response.precheck,
             "test_override": response.test_override, "truncated": response.truncated,
             "robots": _robots_brief(attempt.robots)}
    if v is not None:
        entry.update(verdict=v.verdict, stop_class=v.stop_class, transient=v.transient)
    if page is not None:
        text = _scrubbed(page)[0]
        entry.update(text_chars=len(text), extraction_source=page.extraction_source,
                     content_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest())
    if extra:
        entry.update(extra)
    run.log(entry)


def _evaluate(st: _Read, attempt: _Attempt, *, requested: str, feed_target: str | None = None,
              feed_scope: str = "item"):
    response = attempt.response
    text, _ = response.text()
    page = None
    if _looks_html(response):
        page = extract.from_html(text, response.final_url)
    elif response.content_type in FEED_TYPES or text.lstrip()[:200].startswith(("<?xml", "<rss", "<feed")):
        page = extract.from_feed(text, feed_target or response.final_url, feed_scope if feed_target else "all")
    elif response.content_type.startswith("text/"):
        page = extract.from_text(text)
    v = _classify_response(st, attempt, page, requested)
    _log_attempt(st.run, attempt, v, page)
    return page, v


def _classify_response(st: _Read, attempt: _Attempt, page, requested: str) -> verdict.Verdict:
    response = attempt.response
    optouts = robots.page_optouts(response.headers, page.meta_robots if page else [],
                                  page.tdm_meta if page else None, ROBOTS_TOKEN, response.x_robots)
    return verdict.classify(status=response.status, headers=response.headers, page=page, requested_url=requested,
                            final_url=response.final_url, redirect_urls=[r["to"] for r in attempt.chain],
                            expect=st.expect, optouts=optouts, login_hosts=st.routes.login_hosts)


def _route_control(st: _Read, attempt: _Attempt, text: str):
    """Access controls in a route response, before feed, oEmbed or adapter parsing."""
    response = attempt.response
    page = extract.from_html(text, response.final_url) if _looks_html(response) else \
        extract.from_text(text) if response.content_type.startswith("text/") else None
    return page, _classify_response(st, attempt, page, attempt.url)


def _trail(st: _Read, rung: str, outcome: str, *, url: str | None = None, attempt: _Attempt | None = None,
           v: verdict.Verdict | None = None, note: str | None = None) -> None:
    item = {"rung": rung, "presentation": PRESENTATION[rung], "outcome": outcome}
    if url:
        item["url"] = privacy.mask_url(url)
    if attempt is not None:
        if attempt.fetch_id:
            item["fetch_id"] = attempt.fetch_id
        if attempt.response is not None:
            item["status"] = attempt.response.status
        if attempt.error:
            item["error"] = attempt.error
        if attempt.stop:
            item["stop_class"] = attempt.stop
    if v is not None:
        item.update({k: val for k, val in (("verdict", v.verdict), ("stop_class", v.stop_class)) if val})
        item["reasons"] = v.reasons[:4]
    if note:
        item["note"] = note
    st.trail.append(item)


# ---------------------------------------------------------------- outcomes


def _remaining(st: _Read) -> tuple[list, list]:
    untried, notes = [], []
    render = st.run.policy.get("render", "host_browser")
    if render != "off":
        untried.append("R3")
        if render == "driver":
            notes.append(DRIVER_NOTE)
    else:
        notes.append("render disabled by the brief")
    return untried, notes


def _meta(page) -> dict:
    """Page metadata as printed and returned: scrubbed like the page text."""
    meta = page.metadata()
    meta["title"] = privacy.scrub(meta["title"])[0]
    meta["description"] = privacy.scrub(meta["description"])[0]
    meta["og"] = {k: privacy.scrub(v)[0] for k, v in meta["og"].items()}
    return meta


def _payload(page, prescrubbed: dict | None = None) -> tuple[str, dict]:
    """(the page text as saved and printed, the result fields that describe it). The same for `read`
    and `ingest`: personal identifiers are scrubbed before anything is printed, saved or scanned, so the
    content hash and any later verbatim check refer to the scrubbed text. `prescrubbed` holds the counts
    of an adapter that scrubbed every free-text field itself (its IDs, author keys and dates are not
    personal identifiers and must stay intact), so the text is not scrubbed again."""
    if prescrubbed is not None:
        text, scrubbed = page.text, dict(prescrubbed)
        content, title = page.main_text or page.text, page.title
    else:
        text, scrubbed = _scrubbed(page)
        scrubbed = dict(scrubbed)
        main = page.main_text or page.text
        content = text if main == page.text else privacy.scrub(main)[0]
        title = privacy.scrub(page.title)[0]
    # An adapter's page may come in blocks (a video's description and each comment, already scrubbed): each
    # block is scanned on its own, so a comment's words are never the video's own disclosure.
    blocks = getattr(page, "flag_blocks", None)
    fields = {"extraction_source": page.extraction_source, "text_chars": len(text), "truncated": page.truncated,
              "content_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "scrubbed": scrubbed,
              "injection": scan_injection(text), **verdict.content_flags(content, title, blocks=blocks)}
    return text, fields


def _flag_counts(result: dict) -> dict | None:
    counts = {name: len(result.get(key) or []) for name, key in (("promotion", "promotion_hits"),
                                                                ("incentive", "incentive_flags"),
                                                                ("virtual_person", "virtual_person_flags"))}
    return counts if any(counts.values()) else None


def _terms_brief(terms: dict | None) -> dict | None:
    """What the ledger keeps of a URL's terms record: the deciding entry, and every lifted entry with the host
    of the check that lifted it (the close summary counts lifts per entry and per check)."""
    if not terms:
        return None
    brief = {k: terms.get(k) for k in ("entry", "status", "lift_requires", "lifted", "mode", "not_lifted_because")}
    brief["entries"] = list(terms.get("entries") or [])
    brief["lifted_entries"] = list(terms.get("lifted_entries") or [])
    brief["lift_checks"] = [e.get("check_host") for e in terms.get("entries") or [] if e.get("lifted")]
    return brief


API_BRIEF = ("route", "calls", "quota_units", "pages", "comments_read", "more_available", "partial_because")


def _api_brief(api: dict | None) -> dict | None:
    """What the ledger keeps of an adapter's `api` field: counts only, no IDs (they outlive the run's
    URL cut at close)."""
    return {k: api.get(k) for k in API_BRIEF} if isinstance(api, dict) else None


def _capture_metadata(result, terms, page=None, text=None):
    value = capture_metadata(result)
    value["access"]["terms"] = _terms_brief(terms)
    # Only packaged adapters can provide item/author bindings; generic separators are hints.
    items = getattr(page, "research_items", []) if page is not None else []
    blocks = {x["block"]: x.get("text", "") for x in getattr(page, "flag_blocks", [])} if page is not None else {}
    attested = {}
    for item in items:
        body = blocks.get(item["block"], "")
        start = (text or "").find(body)
        if body and start >= 0 and (text or "").find(body, start + 1) < 0 and hashlib.sha256(body.encode()).hexdigest() == item["text_sha256"]:
            per_item = {key: [hit for hit in result.get(key, []) if hit.get("block") == item["block"]]
                        for key in ("promotion_hits", "incentive_flags", "virtual_person_flags")}
            per_item["injection"] = result.get("injection")
            attested[item["item_key"]] = {**item, "start": start, "end": start + len(body),
                                         "content_sha256": result["content_sha256"],
                                         "flags": research_flags(per_item)}
    if attested:
        value["item_attestations"] = attested
    return value


def _done(st: _Read, bucket: str, *, stop: str | None = None, verdict_: str | None = None, reasons=(),
          rung: str | None = None, attempt: _Attempt | None = None, page=None, untried=(), error: str | None = None,
          retry_after_s: int | None = None, host_stop: dict | None = None, next_step: str | None = None,
          notes=(), out_of_scope: bool = False, access_basis: str = "public_anonymous",
          terms: dict | None = None, extra: dict | None = None, prescrubbed: dict | None = None) -> dict:
    """The URL's result and its ledger outcome. `extra` adds an adapter's fields (api, retention_until);
    `prescrubbed` is passed on to _payload."""
    run = st.run
    host = net.host_of(st.url)
    response = attempt.response if attempt is not None else None
    # The source's robots record is its own page's decision, not a route or alternate host's, unless
    # another host's robots.txt is what stopped or deferred it.
    robots_source = st.target_robots
    if attempt is not None and attempt.robots and (robots_source is None or not attempt.robots.get("allowed")):
        robots_source = attempt.robots
    robots_info = _robots_brief(robots_source)
    terms = terms or st.terms
    result = {"source": "read", "bucket": bucket, "exit_code": EXIT[bucket], "url": privacy.mask_url(st.url),
              "final_url": privacy.mask_url(response.final_url) if response else None, "host": host,
              "verdict": verdict_, "stop_class": stop, "reasons": list(reasons)[:10], "rung": rung,
              "presentation": PRESENTATION.get(rung) if rung else None,
              "fetch_id": attempt.fetch_id if attempt is not None else None, "trail": st.trail,
              "untried": list(untried), "error": error, "retry_after_s": retry_after_s, "host_stop": host_stop,
              "next_step": next_step, "notes": list(notes), "robots": robots_info, "fetched_at": run.now_iso(),
              "render": "needs_host_render" if "R3" in untried else None,
              "context": "anonymous", "access_basis": access_basis if bucket == "read" else None}
    if terms:
        result["terms"] = terms
        if terms.get("lifted"):
            result["notes"].append(_lift_note(terms))
    if out_of_scope:
        result["out_of_scope"] = True
        if not result["notes"]:
            result["notes"].append(scope.PRIVATE_NOTE)
    if extra:
        result.update(extra)
    text = None
    if bucket == "read" and page is not None:
        text, fields = _payload(page, prescrubbed)
        result.update(fields, meta=_meta(page))
        run.save_page(attempt.fetch_id, text)
        result["research_flags"] = research_flags(result)
        result["research_access"] = _capture_metadata(result, terms, page, text)["access"]
    elif stop == "paywall" and page is not None:
        result["meta"] = _meta(page)
    # Only a URL with no allowed rung left counts toward bot_filter_persistent: a page that is waiting
    # for its render (R3 untried) has not been found unreadable yet.
    if bucket == "read" or (bucket == "unread" and not untried):
        streak = run.note_outcome(host, bucket)
        if streak:
            result["host_stop"] = streak
            result["notes"].append("this host is now stopped for the run: " + streak["reason"])
    run.log({"kind": "outcome", "source": "read", "url": st.url, "url_key": run.url_key(st.url), "host": host,
             "fetched_at": result["fetched_at"], "context": "anonymous",
             "access_basis": result["access_basis"], "out_of_scope": out_of_scope or None,
             "robots": {"decision": (robots_info or {}).get("decision"), "status": (robots_info or {}).get("robots_status")},
             "bucket": bucket, "verdict": verdict_, "stop_class": stop, "rung": rung,
             "presentation": result["presentation"], "fetch_id": result["fetch_id"], "untried": result["untried"],
             "error": error, "retry_after_s": retry_after_s, "contacted": st.contacted,
             "reasons": result["reasons"][:6], "trail": st.trail, "text_chars": result.get("text_chars"),
             "content_sha256": result.get("content_sha256"), "extraction_source": result.get("extraction_source"),
             "injection_risk": (result.get("injection") or {}).get("risk"),
             "host_stop": (result["host_stop"] or {}).get("class"), "terms": _terms_brief(terms),
             "scrubbed": result.get("scrubbed") or None, "flags": _flag_counts(result),
             "ai_agent_token": (robots_info or {}).get("ai_agent_token"),
             "ai_training_disallow": (robots_info or {}).get("ai_training_disallow") or None,
             "api": _api_brief(result.get("api")), "retention_until": result.get("retention_until"),
             "capture_metadata": _capture_metadata(result, terms, page, text) if text is not None else None})
    result["text"] = text
    return result


def _lift_note(terms: dict) -> str:
    entries = ", ".join(terms.get("lifted_entries") or [terms.get("entry")])
    checks = sorted({e.get("check_host") for e in terms.get("entries") or [] if e.get("lifted") and e.get("check_host")})
    return (f"the terms_restricted entries {entries} (lift_requires: {terms['lift_requires']}) are lifted for this run "
            "by the user's own terms checks "
            f"({', '.join(checks)}); each lifted entry has a budget of {scope.LIFTED_HOST_BUDGET} documents across "
            "its hosts")


def _url_key(run: Run, url) -> str | None:
    """The run's key for a URL the reader could parse (so a refusal of a URL that has an outcome counts as
    that URL, not a new one), else None."""
    if not isinstance(url, str) or not url:
        return None
    try:
        return run.url_key(net.parse_url(url))
    except (net.NetError, RunError):
        return None


def _refused(run: Run, url, kind: str, detail: str, st: _Read | None = None) -> dict:
    masked = privacy.mask_url(url) if isinstance(url, str) else ""
    host = net.host_of(url) if isinstance(url, str) else ""
    result = {"source": "read", "bucket": "refused", "exit_code": EXIT["refused"], "url": masked, "host": host,
              "verdict": None, "stop_class": None, "error": kind, "reasons": [detail] if detail else [],
              "trail": st.trail if st else [], "untried": [], "fetched_at": run.now_iso(), "text": None}
    run.log({"kind": "outcome", "source": "read", "url": url if isinstance(url, str) else "",
             "url_key": _url_key(run, url), "host": host, "bucket": "refused", "error": kind,
             "contacted": bool(st and st.contacted)})
    return result


REDIRECT_LOOP_NOTE = ("a redirect loop is how some checks keep a client out: the URL stops (opted_out), and no "
                      "other rung and no render capture follows")


def _error_outcome(st: _Read, attempt: _Attempt) -> dict:
    if attempt.error in net.REFUSAL_KINDS:
        return _refused(st.run, st.url, attempt.error, attempt.error_detail, st)
    if attempt.error == "redirect_loop":  # never escalated: a browser that keeps cookies would pass the loop
        return _done(st, "stopped", stop="opted_out", reasons=["redirect_loop", attempt.error_detail],
                     rung=attempt.rung, attempt=attempt, notes=[REDIRECT_LOOP_NOTE])
    if attempt.error == "robots_unreachable":
        return _done(st, "deferred", error=attempt.error, reasons=["robots_unreachable", attempt.error_detail],
                     rung=attempt.rung, attempt=attempt, retry_after_s=attempt.retry_after_s)
    if attempt.error in net.TRANSIENT_KINDS:
        return _done(st, "deferred", error=attempt.error, reasons=[attempt.error_detail], rung=attempt.rung,
                     attempt=attempt, retry_after_s=TRANSIENT_RETRY_S)
    untried, notes = _remaining(st)
    return _done(st, "unread", error=attempt.error, reasons=[attempt.error_detail], rung=attempt.rung,
                 attempt=attempt, untried=untried, notes=notes, next_step=INGEST_HELP if "R3" in untried else None)


def _rate_limited(st: _Read, attempt: _Attempt, v: verdict.Verdict, rung: str) -> dict | None:
    response = attempt.response
    host = net.host_of(response.final_url)
    wait = verdict.retry_after_seconds(response.headers.get("retry-after"), st.run.clock())
    noted = st.run.note_rate_limit(host, wait, v.reasons)
    if noted["stopped"]:
        return _done(st, "stopped", stop="rate_limit", reasons=v.reasons + [noted["stop"]["reason"]], rung=rung,
                     attempt=attempt, host_stop=noted["stop"])
    _trail(st, rung, "rate_limited", attempt=attempt, v=v, note=f"one wait of {noted['wait_s']:.0f} s, then one retry")
    return None


def _host_signal(v: verdict.Verdict) -> bool:
    """A 429 or a 503 with Retry-After: one polite wait, then the host stops. A rate-limit notice
    without those statuses stops only its URL."""
    return v.stop_class == "rate_limit" and v.host_wide


STOP_REASONS = {"human_check": "a human check", "bot_filter": "the site refused an honest request (bot filter)",
                "js_check": "a browser check interstitial (never waited out)"}


def site_stop_reason(v: verdict.Verdict) -> str:
    return STOP_REASONS.get(v.verdict or "", STOP_REASONS.get(v.stop_class or "", v.stop_class or "stop"))


def _terminal(st: _Read, attempt: _Attempt, page, v: verdict.Verdict, rung: str) -> dict | None:
    if v.stop_class:
        host_stop = None
        if v.stop_class in verdict.HOST_STOPPING and v.host_wide:  # the whole site stops for the run
            host_stop = st.run.stop_host(net.host_of(attempt.response.final_url), v.stop_class, site_stop_reason(v),
                                         v.reasons)
        return _done(st, "stopped", stop=v.stop_class, reasons=v.reasons, rung=rung, attempt=attempt,
                     page=page if v.stop_class == "paywall" else None, host_stop=host_stop)
    if v.transient:
        return _done(st, "deferred", reasons=v.reasons, rung=rung, attempt=attempt, retry_after_s=TRANSIENT_RETRY_S)
    if v.ok:
        return _done(st, "read", verdict_=v.verdict, reasons=v.reasons, rung=rung, attempt=attempt, page=page)
    return None


# ---------------------------------------------------------------- rungs


def _rung0(st: _Read, platform: dict | None, values: dict, *, official_only: bool = False) -> dict | None:
    """R0: the route table's official routes for this page. `official_only` is the mode of a
    terms_restricted host whose entry names this platform: the same routes, and nothing after them.
    An adapter route (route_adapter) makes its own calls, up to its own cap, through _request; when
    it cannot serve the URL it says why in st.route_reasons."""
    if not platform or not platform.get("official"):
        return None
    requests = 0
    for route in platform["official"]:
        kind = route.get("kind")
        if requests >= R0_MAX_REQUESTS:
            _trail(st, "R0", "skipped", note="R0 request cap reached")
            break
        adapter = None if kind in IMPLEMENTED_ROUTE_KINDS else route_adapter(route)
        if kind not in IMPLEMENTED_ROUTE_KINDS and adapter is None:
            _trail(st, "R0", "skipped", note=f"{kind} routes need a provider adapter (later phase)")
            continue
        if adapter is not None:
            result, made = adapter.read_route(st, platform, route, values, official_only=official_only)
            requests += made
            if result is not None:
                return result
            continue
        local = dict(values)
        if route.get("auth") == "user_key":
            key, env = user_key(route)
            if not key:
                _trail(st, "R0", "skipped", note=f"no user key in ${env}")
                continue
            local["key"] = quote(key, safe="")
        candidate = expand(route.get("url", ""), local)
        try:
            candidate = net.parse_url(candidate) if candidate else None
        except net.NetError:
            candidate = None
        if not candidate:
            _trail(st, "R0", "skipped", note=f"route {platform.get('id')} does not fit this URL")
            continue
        if route.get("auth") == "user_key":
            withheld = key_for(route, candidate)[1]
            if withheld:  # the key goes only where the packaged route table sends it, and only masked
                st.route_reasons.append(withheld)
                _trail(st, "R0", "skipped", note=withheld_note(withheld, user_key(route)[1]))
                continue
        limited = None
        while requests < R0_MAX_REQUESTS:
            try:
                attempt = _request(st, candidate, "R0", accept=FEED_ACCEPT if kind == "feed" else JSON_ACCEPT,
                                   purpose="route")
            except HostStopped as exc:
                return _done(st, "stopped", stop="host_stopped", reasons=[f"host_stop:{exc.stop.get('class')}"],
                             rung="R0", host_stop=exc.stop)
            except BudgetExceeded as exc:
                if exc.scope == "run" or limited:
                    raise
                _trail(st, "R0", "skipped", url=candidate, note="route host budget used up")
                break
            except net.NetError as exc:
                if limited:
                    return _done(st, "stopped", stop="rate_limit", reasons=limited.reasons, rung="R0")
                _trail(st, "R0", "failed", url=candidate, note=f"route host unusable ({exc.kind})")
                break
            if attempt.contacted or attempt.error:
                requests += 1
            if attempt.stop:
                if attempt.scope and not attempt.contacted and not limited:
                    _trail(st, "R0", "skipped", url=candidate, attempt=attempt,
                           note=", ".join(attempt.reasons[:2]))
                    break  # an excluded route was never requested; the allowed source page remains eligible
                found = attempt.scope_stop
                return _done(st, "stopped", stop=attempt.stop, reasons=attempt.reasons, rung="R0", attempt=attempt,
                             out_of_scope=attempt.out_of_scope, notes=[found.note] if found else (),
                             terms=found.terms if found else None,
                             host_stop=st.run.host_stop(net.host_of(candidate)))
            if attempt.error:
                if limited:
                    return _done(st, "stopped", stop="rate_limit", reasons=limited.reasons, rung="R0", attempt=attempt)
                if attempt.error == "redirect_loop":
                    return _error_outcome(st, attempt)
                _trail(st, "R0", "failed", url=candidate, attempt=attempt)
                break
            response = attempt.response
            text, _ = response.text()
            # Classify controls before feed/oEmbed extraction: an HTML check is never a route miss.
            control_page, control = _route_control(st, attempt, text)
            page, v = control_page, control
            if 200 <= response.status < 300 and not control.stop_class:
                page = extract.from_feed(text, st.url, route.get("scope", "item")) if kind == "feed" \
                    else extract.from_oembed(text)
                if page is None:
                    _log_attempt(st.run, attempt)
                    if limited:
                        return _done(st, "stopped", stop="rate_limit", reasons=limited.reasons, rung="R0", attempt=attempt)
                    _trail(st, "R0", "failed", url=candidate, attempt=attempt, note="no entry for this page")
                    break
                v = _classify_response(st, attempt, page, candidate)
            _log_attempt(st.run, attempt, v, page)
            if _host_signal(v):
                stopped = _rate_limited(st, attempt, v, "R0")
                if stopped is not None:
                    return stopped
                limited = v
                if requests >= R0_MAX_REQUESTS:
                    return _done(st, "stopped", stop="rate_limit", reasons=v.reasons, rung="R0", attempt=attempt)
                continue
            if v.stop_class and not (v.stop_class == "gone" and response.status in (404, 410)):
                return _terminal(st, attempt, page, v, "R0")
            if not 200 <= response.status < 300:
                if limited:
                    return _done(st, "stopped", stop="rate_limit", reasons=limited.reasons, rung="R0", attempt=attempt)
                _trail(st, "R0", "failed", url=candidate, attempt=attempt, note="unverified route; falls through")
                break
            if v.ok:
                basis = "official_api" if route.get("auth") == "user_key" else "public_anonymous"
                extra = ["official_only"] if official_only else []
                return _done(st, "read", verdict_=v.verdict, reasons=v.reasons + [f"route:{platform.get('id')}"] + extra,
                             rung="R0", attempt=attempt, page=page, access_basis=basis)
            if limited:
                return _done(st, "stopped", stop="rate_limit", reasons=limited.reasons, rung="R0", attempt=attempt)
            _trail(st, "R0", "failed", url=candidate, attempt=attempt, v=v)
            break
    return None


def _terms_stop(st: _Read, stop: scope.ScopeStop) -> dict:
    """A terms_restricted page. When its entry names an official route that can run (an adapter for
    its kind, the user's key when it needs one), that route is read in official-only mode: R0 alone,
    never the page, an alternate or a render. Otherwise, or when the route fails, the URL stops; the
    reasons then say why (st.route_reasons, else official_route_failed). An adapter's own outcome (a
    gone video, a quota deferral) is the URL's result."""
    record = dict(stop.terms or {})
    st.terms = record
    reasons = list(stop.reasons)
    # Official-only mode reads the PACKAGED route table only: a run's own route table can never change the
    # route, its hosts or the host it calls for a terms_restricted host.
    route_id, why_not = scope.official_route(record, st.routes.lists)
    if why_not:
        reasons.append(why_not)
    if route_id:
        platform, values = packaged_routes().match_platform(route_id, st.url)
        if platform is None:
            reasons.append("official_route_does_not_fit")
        else:
            why = sorted({w for route in platform.get("official") or [] for w in route_readiness(route)})
            ready = [route for route in platform.get("official") or [] if not route_readiness(route)]
            if not ready:
                reasons += why
            else:
                record["mode"] = "official_only"
                result = _rung0(st, platform, values, official_only=True)
                if result is not None:
                    return result
                reasons += list(dict.fromkeys(st.route_reasons)) or ["official_route_failed"]
    return _done(st, "stopped", stop="terms_restricted", reasons=reasons, notes=[stop.note], terms=record)


def _alternates(st: _Read, platform: dict | None, values: dict, page) -> list[tuple[str, str]]:
    site = registrable_domain(net.host_of(st.url))
    found: list[tuple[str, str]] = []

    def add(url: str | None, source: str) -> None:
        try:
            url = net.parse_url(url) if url else None
        except net.NetError:
            return
        if not url or url == st.url or any(url == u for u, _ in found):
            return
        if registrable_domain(net.host_of(url)) != site:
            _trail(st, "R2", "ignored", url=url, note=f"{source} is on another registrable domain")
            return
        found.append((url, source))

    if page is not None:
        for kind in ("mobile", "amp", "feed"):
            for alternate in page.alternates:
                if alternate["kind"] == kind:
                    add(alternate["href"], f"declared:{kind}")
    for twin in (platform or {}).get("alternates", []):
        add(expand(twin.get("url", ""), values), f"route:{twin.get('kind', 'twin')}")
    host = net.host_of(st.url)
    mobile = None
    if host.startswith("www."):
        mobile = "m." + host[4:]
    elif host == site and not host.startswith("m."):
        mobile = "m." + host
    if mobile and net.resolves(mobile):
        parts = urlsplit(st.url)
        netloc = mobile + (f":{parts.port}" if parts.port else "")
        add(parts._replace(netloc=netloc).geturl(), "generic:m")
    return found


def _ladder(st: _Read) -> dict:
    # The page's own robots.txt decides before any rung: a path the site disallows is never read,
    # not even through an official route or an alternate on another host. This decision, not a
    # route host's, is the source's robots record.
    decision = robots_decision(st.run, st.url, st.max_wait)
    st.target_robots = decision
    if not decision["allowed"]:
        if decision["robots_status"] == "unreachable":
            return _done(st, "deferred", error="robots_unreachable", retry_after_s=decision.get("retry_after_s"),
                         reasons=["robots_unreachable", ROBOTS_UNREACHABLE])
        host_stop = st.run.host_stop(net.host_of(st.url)) if decision.get("challenge") else None
        return _done(st, "stopped", stop="opted_out", reasons=_robots_reasons(decision), host_stop=host_stop)
    platform, values = st.routes.match(st.url)
    result = _rung0(st, platform, values)
    if result is not None:
        return result
    # R1: one honest GET, plus at most one polite retry after a first rate-limit signal
    attempt = _request(st, st.url, "R1")
    for _ in range(2):
        if attempt.stop:
            found = attempt.scope_stop  # a redirect into a scope stop (a short link to a restricted host)
            return _done(st, "stopped", stop=attempt.stop, reasons=attempt.reasons, rung="R1", attempt=attempt,
                         out_of_scope=attempt.out_of_scope, notes=[found.note] if found and found.note else (),
                         terms=found.terms if found else None)
        if attempt.error:
            return _error_outcome(st, attempt)
        page, v = _evaluate(st, attempt, requested=st.url)
        if not _host_signal(v):
            break
        stopped = _rate_limited(st, attempt, v, "R1")
        if stopped is not None:
            return stopped
        attempt = _request(st, st.url, "R1")
    terminal = _terminal(st, attempt, page, v, "R1")
    if terminal is not None:
        return terminal
    _trail(st, "R1", "escalate", attempt=attempt, v=v)
    last = v
    last_rung = "R1"
    # R2: the site's own alternates, at most two requests
    requests = 0
    candidates = _alternates(st, platform, values, page)
    if not candidates:
        _trail(st, "R2", "skipped", note="no alternate on this site")
    for candidate, source in candidates:
        if requests >= R2_MAX_REQUESTS:
            _trail(st, "R2", "skipped", url=candidate, note="R2 request cap reached")
            break
        feed = source.endswith(":feed")
        try:
            alt = _request(st, candidate, "R2", accept=FEED_ACCEPT if feed else PAGE_ACCEPT, purpose="alternate")
        except HostStopped as exc:
            _trail(st, "R2", "skipped", url=candidate, note=f"host stopped ({exc.stop.get('class')})")
            continue
        except BudgetExceeded as exc:
            if exc.scope == "run":
                raise
            _trail(st, "R2", "skipped", url=candidate, note="host budget used up")
            continue
        except net.NetError as exc:
            _trail(st, "R2", "failed", url=candidate, note=f"{source}: host unusable ({exc.kind})")
            continue
        if alt.contacted or alt.error:
            requests += 1
        if alt.scope or (alt.stop == "opted_out" and not (alt.robots or {}).get("challenge")):
            why = ", ".join(alt.reasons[:1]) if alt.scope else "robots.txt disallows it"
            _trail(st, "R2", "skipped", url=candidate, attempt=alt, note=f"{source}: {why}")
            continue
        if alt.stop:
            return _done(st, "stopped", stop=alt.stop, reasons=alt.reasons, rung="R2", attempt=alt)
        if alt.error == "redirect_loop":  # the same site keeps our client out: a stop, never a way around
            return _error_outcome(st, alt)
        if alt.error:
            _trail(st, "R2", "failed", url=candidate, attempt=alt, note=source)
            continue
        alt_page, alt_v = _evaluate(st, alt, requested=candidate, feed_target=st.url if feed else None)
        if alt_v.stop_class == "gone" and alt.response.status in (404, 410):
            _trail(st, "R2", "failed", url=candidate, attempt=alt, v=alt_v, note=f"{source} does not exist")
            continue
        if _host_signal(alt_v):
            stopped = _rate_limited(st, alt, alt_v, "R2")
            if stopped is not None:
                return stopped
            continue
        if alt_v.transient:
            _trail(st, "R2", "failed", url=candidate, attempt=alt, v=alt_v, note=source)
            continue
        terminal = _terminal(st, alt, alt_page, alt_v, "R2")
        if terminal is not None:
            return terminal
        _trail(st, "R2", "escalate", url=candidate, attempt=alt, v=alt_v, note=source)
        last, last_rung = alt_v, "R2"
    untried, notes = _remaining(st)
    return _done(st, "unread", verdict_=last.verdict, reasons=last.reasons, rung=last_rung, untried=untried,
                 notes=notes, next_step=INGEST_HELP if "R3" in untried else None)


# ---------------------------------------------------------------- entry points


def read(run: Run, url: str, *, expect=(), max_wait: float | None = None) -> dict:
    run.require_open()
    wait = float(run.policy.get("max_wait_s", 60) if max_wait is None else max_wait)
    try:
        target = net.parse_url(url)
    except net.NetError as exc:
        return _refused(run, url, exc.kind, exc.detail)
    st = _Read(run, target, tuple(t for t in expect if t), wait, Routes(run.routes))
    host = net.host_of(target)
    parts = urlsplit(target)
    # The scope checks come first: decided from the URL alone, before any DNS lookup or request.
    excluded, st.terms = scope_check(run, st.routes, target)
    if excluded is not None and excluded.refused_at_start:
        return _refused(run, target, excluded.error, excluded.detail, st)
    if excluded is not None and excluded.kind != "terms":
        return _done(st, "stopped", stop=excluded.stop_class, reasons=excluded.reasons,
                     out_of_scope=excluded.out_of_scope, notes=[excluded.note] if excluded.note else ())
    if excluded is None:  # a terms_restricted host is never looked up or contacted
        try:
            net.check_host(host, parts.port or (443 if parts.scheme == "https" else 80))
        except net.NetError as exc:
            if exc.kind in net.REFUSAL_KINDS:
                return _refused(run, target, exc.kind, exc.detail, st)
        stopped = run.host_stop(host)
        if stopped:
            return _done(st, "stopped", stop="host_stopped", reasons=[f"host_stop:{stopped['class']}"],
                         host_stop=stopped)
    try:
        if excluded is not None:  # terms_restricted: official-only mode or a stop, never the page itself
            return _terms_stop(st, excluded)
        return _ladder(st)
    except Deferred as exc:
        return _done(st, "deferred", reasons=[f"deferred:{exc.why}"], retry_after_s=exc.retry_after_s)
    except HostStopped as exc:
        return _done(st, "stopped", stop="host_stopped", reasons=[f"host_stop:{exc.stop.get('class')}"],
                     host_stop=exc.stop)
    except BudgetExceeded as exc:
        return _done(st, "stopped", stop="budget", reasons=[f"budget:{exc.scope}:{exc.limit}"])
    except net.NetError as exc:
        if exc.kind in net.REFUSAL_KINDS:
            return _refused(run, target, exc.kind, exc.detail, st)
        return _done(st, "unread", error=exc.kind, reasons=[exc.detail])


def check_robots(run: Run, url: str, *, max_wait: float | None = None) -> dict:
    """What a browser tool may open on this URL's host, without reading the page: the scope checks
    (deny list, search pages and switched-off endpoints, which exit 2, out-of-scope channels and
    terms_restricted hosts, which exit 3), a host stopped for this run, and robots.txt. A
    terms_restricted host exits 3 even when its official route can run: browser tools never open it.
    Page-level opt-outs (noai, TDM) are in the page itself, so only `read` sees them."""
    run.require_open()
    wait = float(run.policy.get("max_wait_s", 60) if max_wait is None else max_wait)
    try:
        target = net.parse_url(url)
    except net.NetError as exc:
        return {"url": privacy.mask_url(url), "exit_code": EXIT["refused"], "error": exc.kind,
                "reasons": [exc.detail]}
    masked = privacy.mask_url(target)
    excluded, lift = scope_check(run, Routes(run.routes), target)
    if excluded is not None and excluded.refused_at_start:
        return {"url": masked, "exit_code": EXIT["refused"], "allowed": False, "error": excluded.error,
                "reasons": list(excluded.reasons) + [excluded.detail]}
    if excluded is not None:  # decided before robots.txt is fetched: nothing is sent to an excluded host
        value = {"url": masked, "exit_code": EXIT["stopped"], "allowed": False, "stop_class": excluded.stop_class,
                 "reasons": excluded.reasons, "out_of_scope": excluded.out_of_scope}
        if excluded.terms:
            value["terms"] = excluded.terms
        run.log({"kind": "outcome", "source": "robots", "url": target, "url_key": run.url_key(target),
                 "host": net.host_of(target), "bucket": "stopped", "stop_class": excluded.stop_class,
                 "out_of_scope": excluded.out_of_scope, "reasons": excluded.reasons, "contacted": False,
                 "terms": _terms_brief(excluded.terms)})
        return value
    parts = urlsplit(target)
    try:
        net.check_host(parts.hostname or "", parts.port or (443 if parts.scheme == "https" else 80))
    except net.NetError as exc:
        if exc.kind in net.REFUSAL_KINDS:
            return {"url": masked, "exit_code": EXIT["refused"], "error": exc.kind, "reasons": [exc.detail]}
    value = _robots_check(run, target, masked, wait)
    if lift:
        value["terms"] = lift
    if value.get("exit_code") == EXIT["stopped"]:
        run.log({"kind": "outcome", "source": "robots", "url": target, "url_key": run.url_key(target),
                 "host": net.host_of(target), "bucket": "stopped", "stop_class": value.get("stop_class"),
                 "contacted": False, "robots": {"decision": value.get("decision"),
                                                "status": value.get("robots_status")}})
    return value


def _robots_check(run: Run, target: str, masked: str, wait: float) -> dict:
    stopped = run.host_stop(net.host_of(target))
    if stopped:
        return {"url": masked, "exit_code": EXIT["stopped"], "allowed": False, "stop_class": "host_stopped",
                "reasons": [f"host_stop:{stopped['class']}"], "host_stop": stopped}
    try:
        decision = robots_decision(run, target, wait)
    except Deferred as exc:
        return {"url": masked, "exit_code": EXIT["deferred"], "allowed": False, "retry_after_s": exc.retry_after_s,
                "reasons": [f"deferred:{exc.why}"]}
    except HostStopped as exc:
        return {"url": masked, "exit_code": EXIT["stopped"], "allowed": False, "stop_class": "host_stopped",
                "host_stop": exc.stop}
    except net.NetError as exc:
        code = EXIT["refused"] if exc.kind in net.REFUSAL_KINDS else EXIT["unread"]
        return {"url": masked, "exit_code": code, "allowed": False, "error": exc.kind, "reasons": [exc.detail]}
    if decision["allowed"]:
        return {"url": masked, "exit_code": EXIT["read"], "stop_class": None, **decision}
    if decision["robots_status"] == "unreachable":
        return {"url": masked, "exit_code": EXIT["deferred"], "stop_class": None, "error": "robots_unreachable",
                "reasons": ["robots_unreachable", ROBOTS_UNREACHABLE], **decision}
    return {"url": masked, "exit_code": EXIT["stopped"], "stop_class": "opted_out",
            "reasons": _robots_reasons(decision), **decision}


PAGE_READ_REQUIRED = {"schema_version": str, "url": str, "final_url": str, "status": int, "text": str,
                      "context": str, "started_at": str, "finished_at": str}


def check_page_read(doc) -> None:
    """Shape checks for ux-page-read.v1 (schemas/ux-page-read.v1.schema.json)."""
    if not isinstance(doc, dict) or doc.get("schema_version") != "ux-page-read.v1":
        raise ValueError("not a ux-page-read.v1 document")
    for name, kind in PAGE_READ_REQUIRED.items():
        if not isinstance(doc.get(name), kind) or isinstance(doc.get(name), bool):
            raise ValueError(f"ux-page-read.v1 needs {name} ({kind.__name__})")
    if len(doc["text"]) > extract.TEXT_CAP_CHARS:
        raise ValueError("ux-page-read.v1 text is longer than 400 KB")
    blocks = doc.get("json_ld", [])
    if not isinstance(blocks, list) or len(blocks) > extract.JSONLD_MAX_BLOCKS:
        raise ValueError("ux-page-read.v1 json_ld must be a list of at most 10 blocks")
    for name in ("meta", "challenge"):
        if name in doc and not isinstance(doc[name], dict):
            raise ValueError(f"ux-page-read.v1 {name} must be an object")
    challenge = doc.get("challenge") or {}
    if "interactive" in challenge and not isinstance(challenge["interactive"], bool):
        raise ValueError("ux-page-read.v1 challenge.interactive must be true or false")
    if not isinstance(challenge.get("markers", []), list):
        raise ValueError("ux-page-read.v1 challenge.markers must be a list")
    waited = doc.get("waited_ms", 0)
    if not isinstance(waited, int) or isinstance(waited, bool) or waited < 0:
        raise ValueError("ux-page-read.v1 waited_ms must be a whole number of milliseconds, 0 or more")


def capture_check(doc: dict) -> tuple[str, list] | None:
    """(the stop class, the reasons) when a ux-page-read.v1 capture went through a check: an interactive human
    check, any challenge marker (a check that clears by itself included), or a wait for a check (waited_ms).
    A render that met a check is never taken in, and the whole site stops, as it would on a read."""
    challenge = doc.get("challenge") or {}
    markers = [str(m)[:60] for m in challenge.get("markers") or []][:3]
    waited = doc.get("waited_ms") or 0
    if challenge.get("interactive"):
        return "human_check", ["human_check:capture:challenge.interactive"] + [f"human_check:marker:{m}" for m in markers]
    if markers or waited > 0:
        return "opted_out", [f"js_check:capture:marker:{m}" for m in markers] + \
            ([f"js_check:capture:waited_ms:{waited}"] if waited > 0 else [])
    return None


def _ingest_refused(run: Run, url: str, reason: str, *, terms: dict | None = None) -> dict:
    run.log({"kind": "outcome", "source": "ingest", "url": url, "url_key": _url_key(run, url),
             "host": net.host_of(url) if url else "", "bucket": "refused", "error": "ingest_refused",
             "reasons": [reason], "terms": _terms_brief(terms)})
    return {"source": "ingest", "bucket": "refused", "exit_code": EXIT["refused"], "url": privacy.mask_url(url),
            "error": "ingest_refused", "reasons": [reason], "text": None, **({"terms": terms} if terms else {})}


def _ingest_stopped(run: Run, target: str, host: str, context: str, stop_class: str, reasons: list,
                    **extra) -> dict:
    """A capture that is not taken in: a host or site stop, a budget stop, or a check the render met."""
    run.log({"kind": "outcome", "source": "ingest", "url": target, "url_key": run.url_key(target), "host": host,
             "bucket": "stopped", "stop_class": stop_class, "rung": "R3", "context": context, "reasons": reasons,
             "host_stop": (extra.get("host_stop") or {}).get("class")})
    return {"source": "ingest", "bucket": "stopped", "exit_code": EXIT["stopped"], "url": privacy.mask_url(target),
            "host": host, "verdict": None, "stop_class": stop_class, "reasons": reasons, "rung": "R3",
            "presentation": "real_browser", "context": context, "untried": [],
            "notes": ["the capture text was discarded"], "text": None, **extra}


def _capture_scope_refusal(stop: scope.ScopeStop) -> str:
    """Why `ingest` never takes in a capture of this URL (a scope stop decided from the URL alone)."""
    if stop.kind == "terms":
        record = stop.terms or {}
        requires = record.get("lift_requires", "never")
        if requires != "never":
            permission = "; the check must record prior written permission" if requires == "written_permission" else ""
            lift = ("only the user can lift this restriction, by recording their own reading of the host's "
                    "current terms in the brief (access_policy.terms_checked)" + permission +
                    "; an agent never writes that entry")
        else:
            lift = "lift_requires_never: this restriction is never lifted"
        official = (" Its official route, when it can run, is read by `read` alone (official-only mode), never "
                    "through a capture." if record.get("official_route") else "")
        return (f"this host's terms restrict automated collection ({', '.join(stop.reasons)}); a capture is never "
                f"taken in: {lift}.{official}")
    if stop.kind == "out_of_scope":
        return f"this URL is on a private channel, out of this research's scope ({', '.join(stop.reasons)}); " \
               "it is never captured"
    if stop.kind == "deny":
        return "this URL is on a host the researcher excludes (deny_hosts); it is never captured"
    return f"{stop.detail}; it is never captured"


def authorised_community(run: Run, url: str) -> dict | None:
    """The community in the brief's access_policy.signed_in_communities that covers this URL: its
    host (subdomains included) and, when the entry has one, its path prefix. Only the user's brief
    adds entries; nothing a page says counts as authorisation."""
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
    except ValueError:
        return None
    path = parts.path or "/"
    for community in run.policy.get("signed_in_communities") or []:
        if not verdict.host_matches(host, [community.get("host", "")]):
            continue
        prefix = (community.get("path_prefix") or "").rstrip("/")
        if not prefix or path == prefix or path.startswith(prefix + "/"):
            return community
    return None


def _capture_blocked(run: Run, target: str, community: dict | None) -> tuple[str | None, dict | None]:
    """(why a capture of this URL may not be taken in, or None; the anonymous read of it).

    A capture needs an earlier anonymous read of the same URL that reached the page and did not
    stop; in an authorised community a membership stop (auth_gate) is the one stop a signed-in
    capture may follow. A capture never replaces a stop, and no capture follows one that stopped."""
    key = run.url_key(target)
    prior = run.last_outcome(key, kind="read")
    if prior is None:
        return "no earlier anonymous read of this URL in this run; run `read` first", None
    bucket, stop = prior.get("bucket"), prior.get("stop_class")
    if bucket == "deferred":
        return "the anonymous read was deferred; run `read` again after its retry_after_s", prior
    member_wall = community is not None and stop == "auth_gate" and not prior.get("out_of_scope")
    if (bucket not in ("read", "unread") or stop) and not member_wall:
        lifted = "; authorisation lifts only a membership stop (auth_gate)" if community is not None else ""
        return f"the anonymous read ended in {stop or bucket}; a capture cannot replace a stop{lifted}", prior
    if not prior.get("contacted"):
        return "the anonymous read made no request for this page; run `read` again", prior
    for earlier in run.outcomes(key, kind="ingest"):
        if earlier.get("bucket") != "stopped":
            continue
        if community is not None and earlier.get("stop_class") == "auth_gate" and earlier.get("context") != "signed_in":
            continue  # an anonymous capture met the membership wall; the authorised member's view may follow
        return (f"an earlier capture of this URL ended in {earlier.get('stop_class')}; "
                "a capture cannot replace a stop"), prior
    return None, prior


def ingest(run: Run, url: str, file_path, *, fmt: str | None = None, context: str, expect=()) -> dict:
    """Accept a render capture (html, txt or ux-page-read.v1) after an anonymous read of the same URL.

    `context` is the browser context the capture came from: `anonymous`, or `signed_in` for a community
    the brief authorises only; `unknown` is refused (re-capture the page in a private window). Signed-in
    text is member content (access_basis authorised_member), scrubbed of personal identifiers, and shared
    outputs keep authored summaries of it only. No capture is taken in on a host or site that is stopped
    for the run, for any reason. A capture that went through a check (a ux-page-read.v1 document with
    challenge markers or a waited_ms, or captured text whose verdict is a human check, a bot filter or a
    browser check) is refused and recorded as the same site-wide stop a read would record; a rate-limit
    page in it is a rate-limit signal, and the capture resets or extends the site's run of unreadable
    URLs."""
    run.require_open()
    try:
        target = net.parse_url(url)
    except net.NetError as exc:
        return _ingest_refused(run, url if isinstance(url, str) else "", f"{exc.kind}: {exc.detail}")
    if context not in CONTEXTS:
        return _ingest_refused(run, target, f"context must be one of {', '.join(CONTEXTS)}")
    if context == "unknown":
        return _ingest_refused(run, target, "a capture from an unknown browser context is not taken in: it may be a "
                                            "signed-in view. Capture the page again in a private or signed-out window "
                                            "(or with drivers/web/read_page.mjs) and pass it with --context anonymous; "
                                            "--context signed_in is only for a community the brief authorises")
    routes = Routes(run.routes)
    excluded, lift = scope_check(run, routes, target)
    if excluded is not None:
        return _ingest_refused(run, target, _capture_scope_refusal(excluded), terms=excluded.terms)
    community = authorised_community(run, target) if context == "signed_in" else None
    if context == "signed_in" and community is None:
        return _ingest_refused(run, target, "signed-in captures are accepted only for communities the brief authorises "
                                            "(access_policy.signed_in_communities); capture this page in a private "
                                            "or signed-out window")
    blocked, prior = _capture_blocked(run, target, community)
    if blocked:
        return _ingest_refused(run, target, blocked)
    path = Path(file_path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > INGEST_MAX_BYTES:
        return _ingest_refused(run, target, "the capture must be a regular file of at most 8 MB")
    data = path.read_bytes()
    fmt = fmt or {".json": "page-read", ".txt": "txt", ".text": "txt"}.get(path.suffix.lower(), "html")
    status, final_url = 200, target
    try:
        if fmt == "page-read":
            doc = json.loads(data.decode("utf-8"))
            check_page_read(doc)
            if doc["context"] != "anonymous" or context == "signed_in":
                return _ingest_refused(run, target, "a ux-page-read.v1 capture comes from a fresh anonymous context; "
                                                    "declare it with --context anonymous")
            declared = {net.parse_url(u) for u in (doc.get("url"), doc.get("final_url")) if isinstance(u, str) and u}
            if target not in declared:
                return _ingest_refused(run, target, "the capture is for a different URL")
            page = extract.from_page_read(doc)
            status = int(doc.get("status") or 200)
            if isinstance(doc.get("final_url"), str) and doc["final_url"]:
                final_url = net.parse_url(doc["final_url"])
            # Where the browser went counts too: a render that a script or a redirect carried into a search
            # page, a private channel or a terms_restricted host is never taken in under the first URL.
            hops = [final_url] + [r.get("url") for r in doc.get("redirects") or [] if isinstance(r, dict)]
            for hop in hops:
                try:
                    hop_url = net.parse_url(hop) if isinstance(hop, str) else None
                except net.NetError:
                    hop_url = None
                hop_stop = scope_check(run, routes, hop_url)[0] if hop_url and hop_url != target else None
                if hop_stop is not None:
                    return _ingest_refused(run, target, "the capture's browser reached another URL that is never "
                                                        "captured: " + _capture_scope_refusal(hop_stop),
                                           terms=hop_stop.terms)
            checked = capture_check(doc)
        elif fmt == "html":
            page = extract.from_html(net.decode_body(data, "text/html")[0], target)
            checked = None
        elif fmt == "txt":
            page = extract.from_text(net.decode_body(data, "text/plain")[0])
            checked = None
        else:
            return _ingest_refused(run, target, f"unknown format {fmt}")
    except (ValueError, TypeError, UnicodeError, net.NetError) as exc:
        return _ingest_refused(run, target, f"unreadable capture: {exc}")
    host = net.host_of(target)
    stopped = run.host_stop(host)
    if stopped:  # a host or site stopped for any reason takes no capture: a render never follows a stop
        return _ingest_stopped(run, target, host, context, "host_stopped", [f"host_stop:{stopped['class']}"],
                               host_stop=stopped)
    if checked is not None:  # the render met a check: refused, and the same site-wide stop a read records
        stop_class, reasons = checked
        try:
            run.book_render(host)  # the render was made; it counts against the budgets like any other
        except BudgetExceeded:
            pass
        kind = "human_check" if stop_class == "human_check" else "js_check"
        host_stop = run.stop_host(host, stop_class, f"{STOP_REASONS[kind]} in a render capture", reasons)
        return _ingest_stopped(run, target, host, context, stop_class, reasons, host_stop=host_stop)
    try:
        run.book_render(host)
    except BudgetExceeded as exc:
        return _ingest_stopped(run, target, host, context, "budget", [f"budget:{exc.scope}:{exc.limit}"])
    optouts = robots.page_optouts({}, page.meta_robots, page.tdm_meta, ROBOTS_TOKEN)
    v = verdict.classify(status=status, headers={}, page=page, requested_url=target, final_url=final_url,
                         expect=tuple(t for t in expect if t), optouts=optouts, login_hosts=routes.login_hosts,
                         capture=True, signed_in=community is not None)
    fetch_id = run.new_fetch_id()
    bucket = "read" if v.ok else "stopped" if v.stop_class else "unread"
    notes: list = []
    host_stop = None
    # A render is what a person's browser shows, so a human check, a bot filter or a browser check in it
    # stops the whole site, and a rate-limit page in it is a rate-limit signal for the site (one wait, then
    # the site stops).
    if v.stop_class == "human_check":
        host_stop = run.stop_host(host, "human_check", "human check in a render capture", v.reasons)
    elif v.stop_class == "opted_out" and v.host_wide:
        host_stop = run.stop_host(host, "opted_out", f"{site_stop_reason(v)} in a render capture", v.reasons)
    elif v.stop_class == "rate_limit":
        noted = run.note_rate_limit(host, None, v.reasons)
        host_stop = noted["stop"] if noted["stopped"] else None
    if bucket in ("read", "unread"):  # a render was the last allowed rung: it resets or extends the streak
        streak = run.note_outcome(host, bucket)
        if streak:
            host_stop = streak
    if host_stop:
        notes.append("this host is now stopped for the run: " + host_stop["reason"])
    basis = ("authorised_member" if community is not None else "public_anonymous") if bucket == "read" else None
    text, fields = _payload(page) if v.ok else (None, {})
    run.log({"kind": "ingest", "fetch_id": fetch_id, "rung": "R3", "presentation": PRESENTATION["R3"],
             "url": target, "final_url": final_url, "host": host, "format": fmt, "context": context,
             "bytes": len(data), "status": status, "verdict": v.verdict, "stop_class": v.stop_class,
             "text_chars": fields.get("text_chars"), "extraction_source": page.extraction_source})
    result = {"source": "ingest", "bucket": bucket, "exit_code": EXIT[bucket], "url": privacy.mask_url(target),
              "final_url": privacy.mask_url(final_url), "host": host, "verdict": v.verdict,
              "stop_class": v.stop_class, "reasons": v.reasons[:10], "rung": "R3", "presentation": "real_browser",
              "context": context, "format": fmt, "fetch_id": fetch_id, "untried": [], "fetched_at": run.now_iso(),
              "access_basis": basis, "host_stop": host_stop, "notes": notes, "text": None}
    if community is not None:
        result["community"] = community.get("name")
    if lift:  # terms restrictions the user's own terms checks lifted for this run
        result["terms"] = lift
        notes.append(_lift_note(lift))
    if v.ok:
        # The same scrubbing and flags as `read`: identifiers never reach the agent, in any context.
        if community is not None:  # member content: summaries only downstream
            result["summary_only"] = True
            notes.append(AUTHORISED_NOTE)
        else:
            result["meta"] = _meta(page)
        run.save_page(fetch_id, text)
        result.update(fields, text=text)
        result["research_flags"] = research_flags(result)
        result["research_access"] = _capture_metadata({**result, "robots": prior.get("robots")}, lift, page, text)["access"]
        result["robots"] = {"decision": (prior.get("robots") or {}).get("decision"),
                            "status": (prior.get("robots") or {}).get("status")}
    elif v.stop_class:
        notes.append("the capture text was discarded")
    run.log({"kind": "outcome", "source": "ingest", "url": target, "url_key": run.url_key(target), "host": host,
             "fetched_at": result["fetched_at"],
             "robots": {"decision": (prior.get("robots") or {}).get("decision"),
                        "status": (prior.get("robots") or {}).get("status")},
             "bucket": bucket, "verdict": v.verdict, "stop_class": v.stop_class, "rung": "R3",
             "presentation": "real_browser", "fetch_id": fetch_id, "context": context, "untried": [],
             "access_basis": basis, "community": result.get("community"), "contacted": False,
             "reasons": v.reasons[:6], "text_chars": result.get("text_chars"),
             "content_sha256": result.get("content_sha256"),
             "injection_risk": (result.get("injection") or {}).get("risk"),
             "host_stop": (host_stop or {}).get("class"), "terms": _terms_brief(lift),
             "scrubbed": result.get("scrubbed") or None, "flags": _flag_counts(result),
             "capture_metadata": _capture_metadata({**result, "robots": prior.get("robots")}, lift, page, text) if text is not None else None})
    return result


__all__ = ["read", "ingest", "check_robots", "check_page_read", "robots_decision", "registrable_domain", "Routes",
           "EXIT", "PRESENTATION", "RUNGS", "IMPLEMENTED_ROUTE_KINDS", "ADAPTER_KINDS", "scope_check", "scope_stop",
           "user_key", "key_for", "key_status", "withheld_note", "route_adapter", "route_readiness"]
