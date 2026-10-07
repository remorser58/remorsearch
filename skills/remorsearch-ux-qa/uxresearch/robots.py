"""robots.txt (RFC 9309) parsing and matching, plus page-level opt-out signals.

Our own parser and matcher. The group is chosen by product token
(case-insensitive; every group naming the token is merged; '*' groups are the
fallback). Among the rules of that group the longest matching pattern wins and
Allow wins a tie. '*' matches any run of characters and a trailing '$' anchors
the end. Paths and patterns are compared after percent-encoding normalisation,
and a URL is allowed only when every form a server may map its path to is
allowed: as sent, with dot segments removed, and with empty segments collapsed
('/./search', '/a/../search' and '//search' all meet 'Disallow: /search').
urllib.robotparser is not used for decisions: it takes the first matching rule
and matches prefixes only, so 'Disallow: /board/' plus 'Allow: /board/view'
would deny /board/view there.

Fetch status: 2xx is parsed; 4xx means unavailable (allowed); 5xx, 429 or a
network failure means unreachable (disallow everything for now, so the reader
defers and checks again later). Three answers make robots.txt unavailable in the
stricter direction, disallowing everything on the origin for the run:
unavailable_bot_filtered, a challenge or block page served instead of the file
(the site stops too, see ladder.robots_decision); and unavailable_redirect, a
redirect loop or a redirect hop into a host the scope checks stop or a stopped
site (never requested). Each record says why (reason). A 2xx body that holds
robots.txt lines is always parsed as robots.txt, whatever its content type and
whatever its comments say.

X-Robots-Tag: each header is read on its own. Inside one header, a
'product-token:' prefix scopes the directives after it to that crawler; a known
directive with a value (such as 'unavailable_after: <date>') is not a crawler name.

Other AI agents (data/agent-tokens.json). The reader is itself an AI agent that
fetches pages for a person, so robots.txt groups naming another agent that
fetches on a user's behalf (fetch_on_behalf) are honoured as if they named our
own token, with two limits: a group naming our own token decides alone, and
such a group only adds disallows (its Allow lines never lift a '*' disallow).
The cached record keeps each of those groups' merged rules, and decide()
consults them only when the base decision came from the '*' group or from no
group. Groups naming training or AI-search crawlers (training_or_index) never
change the decision: the record keeps only those that disallow something, and
decide() returns the tokens that disallow the URL as ai_training_disallow, a
recorded signal. Records carry RECORD_FORMAT; a record in another format is
fetched again.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

PARSE_LIMIT_BYTES = 512 * 1024
STATUSES = ("ok", "unavailable", "unavailable_bot_filtered", "unavailable_redirect", "unreachable")
DISALLOW_ALL = frozenset({"unreachable", "unavailable_bot_filtered", "unavailable_redirect"})
RECORD_FORMAT = 2  # 2: records keep the rules of other AI agents' groups (agents)
AGENT_CATEGORIES = ("fetch_on_behalf", "training_or_index")
_UNRESERVED = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
_HEX = frozenset("0123456789abcdefABCDEF")
_AGENT_KEYS = {"user-agent", "useragent", "user agent"}
_RULE_KEYS = _AGENT_KEYS | {"allow", "disallow"}
_DIRECTIVES = {"all", "none", "index", "follow", "noindex", "nofollow", "noarchive", "nocache", "nosnippet",
               "notranslate", "noimageindex", "indexifembedded", "noai", "noimageai", "noodp", "noydir",
               "unavailable_after", "max-snippet", "max-image-preview", "max-video-preview"}
_PRODUCT_TOKEN = re.compile(r"[a-z0-9_-]+")


@dataclass
class Group:
    agents: list = field(default_factory=list)
    rules: list = field(default_factory=list)  # [allow: bool, pattern: str]
    crawl_delay: float | None = None
    request_rate_s: float | None = None


def normalize_path(value: str) -> str:
    """Percent-encode non-ASCII and control octets, decode unreserved escapes, upper-case the rest."""
    raw = value.encode("utf-8", "surrogatepass")
    out: list[str] = []
    i = 0
    while i < len(raw):
        octet = raw[i]
        if octet == 0x25 and i + 2 < len(raw) and chr(raw[i + 1]) in _HEX and chr(raw[i + 2]) in _HEX:
            decoded = int(raw[i + 1:i + 3], 16)
            out.append(chr(decoded) if chr(decoded) in _UNRESERVED else "%" + raw[i + 1:i + 3].decode("ascii").upper())
            i += 3
            continue
        out.append(f"%{octet:02X}" if octet >= 0x7F or octet <= 0x20 else chr(octet))
        i += 1
    return "".join(out)


def target_of(url: str) -> str:
    parts = urlsplit(url)
    path = parts.path or "/"
    return normalize_path(path + (f"?{parts.query}" if parts.query else ""))


def _dot_free(path: str) -> str:
    """RFC 3986 section 5.2.4 on an already normalised path."""
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


def targets_of(url: str) -> list:
    """The forms a server may map this URL's path to, each normalised like target_of: as sent, with dot
    segments removed, and with empty segments collapsed as well."""
    parts = urlsplit(url)
    query = f"?{parts.query}" if parts.query else ""
    path = normalize_path(parts.path or "/")
    dot_free = _dot_free(path)
    collapsed = "/" + "/".join(s for s in dot_free.split("/") if s)
    if dot_free.endswith("/") and collapsed != "/":
        collapsed += "/"
    return list(dict.fromkeys(p + query for p in (path, dot_free, collapsed)))


def _float(value: str) -> float | None:
    try:
        number = float(value.strip())
    except ValueError:
        return None
    return number if 0 <= number < 86400 else None


def _rate(value: str) -> float | None:
    match = re.fullmatch(r"\s*(\d+)\s*/\s*(\d+)\s*([smh]?)\s*", value.lower())
    if not match or int(match.group(1)) == 0:
        return None
    seconds = int(match.group(2)) * {"": 1, "s": 1, "m": 60, "h": 3600}[match.group(3)]
    return seconds / int(match.group(1))


def parse(text: str) -> list[Group]:
    groups: list[Group] = []
    current: Group | None = None
    in_rules = False
    for line in re.split(r"\r\n|\r|\n", text[:PARSE_LIMIT_BYTES]):
        line = line.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip().lower(), value.strip()
        if key in _AGENT_KEYS:
            if current is None or in_rules:
                current = Group()
                groups.append(current)
                in_rules = False
            current.agents.append(value)
            continue
        if current is None:
            continue  # rules before any user-agent line belong to no group
        if key in ("allow", "disallow"):
            in_rules = True
            if value:
                current.rules.append([key == "allow", normalize_path(value)])
        elif key == "crawl-delay":
            in_rules = True
            current.crawl_delay = _float(value)
        elif key == "request-rate":
            in_rules = True
            current.request_rate_s = _rate(value)
    return groups


def looks_like_robots(text: str) -> bool:
    """True when the body holds at least one user-agent, allow or disallow line."""
    for line in re.split(r"\r\n|\r|\n", text[:PARSE_LIMIT_BYTES]):
        key, sep, _ = line.split("#", 1)[0].partition(":")
        if sep and key.strip().lower() in _RULE_KEYS:
            return True
    return False


def _agent_token(agent: str) -> str:
    return re.split(r"[/\s]", agent.strip().lower(), maxsplit=1)[0]


def _groups_naming(groups: list[Group], token: str) -> list[Group]:
    """Every group whose user-agent lines name this product token (case-insensitive; never '*')."""
    wanted = token.strip().lower()
    return [g for g in groups if wanted and any(_agent_token(a) == wanted for a in g.agents)]


def _merged(chosen: list[Group]) -> dict:
    rules: list = []
    for group in chosen:
        for rule in group.rules:
            if rule not in rules:
                rules.append(rule)
    delays = [g.crawl_delay for g in chosen if g.crawl_delay is not None]
    rates = [g.request_rate_s for g in chosen if g.request_rate_s is not None]
    return {"rules": rules, "crawl_delay": max(delays) if delays else None,
            "request_rate_s": max(rates) if rates else None}


def select(groups: list[Group], token: str) -> dict:
    """Merge the groups for `token`, else the '*' groups. Returns rules and pacing hints."""
    chosen = _groups_naming(groups, token)
    label = token
    if not chosen:
        chosen = [g for g in groups if any(a.strip() == "*" for a in g.agents)]
        label = "*" if chosen else None
    return {"group": label, **_merged(chosen)}


def agent_groups(groups: list[Group], agent_tokens: dict | None, own_token: str) -> dict:
    """The merged rules of other AI agents' groups: every fetch_on_behalf token with a group, and
    the training_or_index tokens whose groups disallow something. Our own token is never listed."""
    found: dict = {name: {} for name in AGENT_CATEGORIES}
    own = own_token.strip().lower()
    for category in AGENT_CATEGORIES:
        for token in (agent_tokens or {}).get(category) or []:
            if not isinstance(token, str) or token.strip().lower() == own or token in found[category]:
                continue
            chosen = _groups_naming(groups, token)
            if not chosen:
                continue
            merged = _merged(chosen)
            if category == "training_or_index":
                if any(not allow and pattern for allow, pattern in merged["rules"]):
                    found[category][token] = merged["rules"]
            else:
                found[category][token] = merged
    return found


def pattern_matches(pattern: str, target: str) -> bool:
    """Glob match without regular expressions (no backtracking blow-up on hostile files)."""
    if pattern.endswith("$"):
        pattern = pattern[:-1]
    else:
        pattern += "*"
    p = s = 0
    star, mark = -1, 0
    while s < len(target):
        if p < len(pattern) and pattern[p] == "*":
            star, mark = p, s
            p += 1
        elif p < len(pattern) and pattern[p] == target[s]:
            p += 1
            s += 1
        elif star >= 0:
            p = star + 1
            mark += 1
            s = mark
        else:
            return False
    while p < len(pattern) and pattern[p] == "*":
        p += 1
    return p == len(pattern)


def match(rules: list, target: str) -> tuple[bool, dict | None]:
    """Longest match wins; Allow wins a tie; no match means allowed."""
    if target == "/robots.txt":
        return True, None
    best = None
    for allow, pattern in rules:
        if pattern and pattern_matches(pattern, target):
            key = (len(pattern), bool(allow))
            if best is None or key > best[0]:
                best = (key, bool(allow), pattern)
    if best is None:
        return True, None
    return best[1], {"type": "allow" if best[1] else "disallow", "pattern": best[2]}


def record_from_fetch(origin: str, *, status: int | None, body: bytes = b"", error: str | None = None,
                      challenge=False, token: str, fetched_at: str, agent_tokens: dict | None = None,
                      refused_redirect: str | None = None) -> dict:
    """Interpret one robots.txt fetch as a cacheable record. `agent_tokens` maps each of
    AGENT_CATEGORIES to a list of other AI agents' product tokens. `challenge` is the kind of a challenge
    or block page served instead of the file ('js_check' or 'bot_filter'; True means 'bot_filter'), and
    `refused_redirect` why a redirect hop was never requested."""
    record = {"format": RECORD_FORMAT, "origin": origin, "http_status": status, "fetched_at": fetched_at,
              "error": error, "sha256": hashlib.sha256(body).hexdigest() if body else None,
              "group": None, "own_group": False, "rules": [], "crawl_delay": None, "request_rate_s": None,
              "agents": {name: {} for name in AGENT_CATEGORIES}, "reason": None, "challenge": None}
    if refused_redirect:  # the hop was never requested: robots.txt is unavailable in the stricter direction
        record["status"], record["reason"] = "unavailable_redirect", f"redirect_refused:{refused_redirect}"
    elif error == "redirect_loop":  # a loop is how some checks keep a client out: the stricter direction too
        record["status"], record["reason"] = "unavailable_redirect", "redirect_loop"
    elif error is not None or status is None:
        record["status"] = "unreachable"
    elif status == 429 or status >= 500:
        record["status"] = "unreachable"
    elif challenge:
        record["status"] = "unavailable_bot_filtered"
        record["challenge"] = challenge if isinstance(challenge, str) else "bot_filter"
        record["reason"] = f"{record['challenge']}:robots_txt"
    elif 200 <= status < 300:
        record["status"] = "ok"
        groups = parse(body[:PARSE_LIMIT_BYTES].decode("utf-8-sig", "replace"))  # BOM-safe
        record.update(select(groups, token))
        record["own_group"] = record["group"] == token
        record["agents"] = agent_groups(groups, agent_tokens, token)
        if not record["own_group"]:
            # A group honoured as if it named us also paces us; the slower pace wins.
            for name in ("crawl_delay", "request_rate_s"):
                values = [v for v in [record[name], *(a[name] for a in record["agents"]["fetch_on_behalf"].values())]
                          if v is not None]
                record[name] = max(values) if values else None
    else:
        record["status"] = "unavailable"
    return record


def decide(record: dict, url: str) -> dict:
    """Decision for one URL against a cached robots record."""
    status = record["status"]
    base = {"robots_status": status, "http_status": record.get("http_status"), "group": record.get("group"),
            "sha256": record.get("sha256"), "crawl_delay": record.get("crawl_delay"), "ai_agent_token": None,
            "ai_training_disallow": [], "challenge": record.get("challenge"), "reason": record.get("reason")}
    if status in DISALLOW_ALL:
        why = {"unreachable": "robots.txt unreachable: complete disallow",
               "unavailable_bot_filtered": "a challenge or block page instead of robots.txt: complete disallow",
               "unavailable_redirect": "robots.txt redirected into a loop or to a host never requested: complete "
                                       "disallow"}[status]
        return {**base, "allowed": False, "decision": "disallowed",
                "rule": {"type": "disallow", "pattern": "/*", "reason": why}}
    if status != "ok":
        return {**base, "allowed": True, "decision": "allowed", "rule": None}
    agents = record.get("agents") or {}
    allowed, rule = True, None
    for target in targets_of(url):  # every form must be allowed
        form_allowed, form_rule = match(record["rules"], target)
        if form_allowed and not record.get("own_group"):
            # Only when no group names our own token: another AI agent's group can add a disallow, never an allow.
            for token, data in (agents.get("fetch_on_behalf") or {}).items():
                agent_allowed, agent_rule = match(data.get("rules") or [], target)
                if not agent_allowed:
                    form_allowed, form_rule = False, agent_rule
                    base["ai_agent_token"] = token
                    break
        if rule is None or not form_allowed:
            rule = form_rule
        if not form_allowed:
            allowed = False
            break
    target = target_of(url)
    base["ai_training_disallow"] = [token for token, rules in (agents.get("training_or_index") or {}).items()
                                    if not match(rules, target)[0]]
    return {**base, "allowed": allowed, "decision": "allowed" if allowed else "disallowed", "rule": rule}


def _x_robots(value: str, token: str) -> set[str]:
    """Directives of one X-Robots-Tag header that apply to `token` (unscoped ones apply to all)."""
    found: set[str] = set()
    agent = None
    for item in value.split(","):
        item = item.strip().lower()
        if ":" in item:
            head, _, tail = item.partition(":")
            head = head.strip()
            if head not in _DIRECTIVES and _PRODUCT_TOKEN.fullmatch(head):
                agent, item = head, tail.strip()
        if item and (agent is None or agent == token.lower()):
            found.add(item.split(":", 1)[0].strip())
    return found


def page_optouts(headers: dict, meta_robots: list, tdm_meta: str | None, token: str,
                 x_robots: list | None = None) -> list[str]:
    """X-Robots-Tag or robots meta 'noai', and TDM reservation (header or meta). `x_robots` lists
    each X-Robots-Tag header separately; without it the (possibly merged) header value is used."""
    reasons: list[str] = []
    values = x_robots if x_robots is not None else [headers.get("x-robots-tag", "")]
    if any("noai" in _x_robots(value, token) for value in values):
        reasons.append("x-robots-tag:noai")
    for name, content in meta_robots:
        if name in ("robots", token.lower()) and "noai" in {p.strip().lower() for p in content.split(",")}:
            reasons.append(f"meta-{name}:noai")
    if headers.get("tdm-reservation", "").strip() == "1":
        reasons.append("tdm-reservation:header")
    if (tdm_meta or "").strip() == "1":
        reasons.append("tdm-reservation:meta")
    return reasons
