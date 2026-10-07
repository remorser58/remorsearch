"""Official-route adapter for a video platform's Data API v3: a video's record and its top-level comments.

data/routes.json names this module as the `adapter` of a platform's 'api' route and holds everything
site-specific: the hosts and URL shapes, the endpoint templates `url` (videos.list) and `comments_url`
(commentThreads.list), the key's environment variable, page_size, max_pages, quota_units_per_call,
quota_reset_tz, retention_days and policy_note. No host name lives in this file.

The page is never requested. For one video URL the adapter takes the video ID from the URL's template
variables (the route's `id_from`, checked against `id_pattern`) and makes, through the reader's own
request path (the scope checks on every call, the API host's robots.txt, pacing and budgets shared by
every reader of the run, no redirect followed):

  1. one call to `url`: the video's record (part=snippet,statistics);
  2. calls to `comments_url`: top-level comment threads (part=snippet, textFormat=plainText,
     order=relevance, maxResults=page_size, at most MAX_PAGE_SIZE), following nextPageToken for at
     most max_pages pages (at most MAX_PAGES) while the run's budgets and pacing allow.

Quota: every call that gets an HTTP answer records route, api_method and quota_units
(quota_units_per_call, default 1; the API charges calls that fail too) in its ledger request entry, and
the run's summary adds them up per route (api_quota).

Key: from the route's `env` (REMORSEARCH_*) or an alias the packaged route table lists for it, sent
only to the hosts the packaged table names for that key (ladder.key_for). It travels as the `key`
query parameter, which every recorded URL masks; it is never printed, saved, logged or put in an error
message. Without a key the URL is a coverage gap (official_route_needs_key:<ENV>), never a page read.

Answers, mapped onto the reader's vocabulary (only reason codes are kept, never the API's messages):
  no item for the video (removed, private)  stopped, gone: video_not_found
  commentsDisabled                          stopped, gone: comments_disabled
  videoNotFound, 404                        stopped, gone: video_not_found
  quotaExceeded, dailyLimitExceeded         deferred until the daily quota resets (the next midnight in
                                            quota_reset_tz); the API host is held until then for the run
  429, rateLimitExceeded, 503+Retry-After   a rate-limit signal: deferred after the first (one wait),
                                            stopped (rate_limit; the API host stops) after the second
  a rejected key (keyInvalid, keyExpired,   the route fails: official_route_key_rejected:<ENV>, and the
  accessNotConfigured, 401 and the like)    API host stops for the run (key_rejected)
  403 forbidden                             the route fails: official_route_refused
  5xx, 408, timeout, connection failure     deferred; retry after ladder.TRANSIENT_RETRY_S
  robots.txt of the API host disallows      stopped, opted_out
  anything else                             the route fails: official_route_failed
A route that fails ends a terms_restricted URL as terms_restricted with these reasons (official-only
mode never falls back to the page). A failure after at least one comment page keeps what was read: a
read whose api.partial_because says why paging stopped.

Privacy (D9, D12): titles, descriptions and comment text are scrubbed field by field (privacy.scrub)
before anything is printed or saved, so the structured headers (IDs, author keys, dates) stay intact.
Promotion, incentive and virtual-person flags are scanned block by block (the title, the description and
each comment), and each flag names its block, so a viewer's comment never counts as the video's disclosure.
Commenters' display names and the uploader's channel title become salted author keys
(privacy.author_key with the route's platform id, the key `ux_research.py author-key --platform <id>`
gives) and are never written. Channel IDs, channel URLs and avatars are never copied; a comment by the
uploader is marked by comparing channel IDs in memory. Every item carries retention_until = its fetch
time + retention_days (at most MAX_RETENTION_DAYS). The adapter derives nothing about a commenter, so
no age, health, political or other protected-attribute cue is ever stored against an author key.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, time as clock_time, timedelta, timezone
from urllib.parse import parse_qsl, quote, unquote, urlsplit, urlunsplit

from . import ROBOTS_TOKEN, extract, ladder, net, privacy, robots, verdict
from .ledger import BudgetExceeded, Deferred, HostStopped, iso

ADAPTER_API = 1  # the contract ladder.route_adapter checks
MAX_PAGE_SIZE = 100
MAX_PAGES = 5
DEFAULT_PAGE_SIZE = 100
DEFAULT_PAGES = 2
MAX_RETENTION_DAYS = 30
FALLBACK_UTC_OFFSET_H = -8  # the quota's reset zone when its time zone data is missing
TITLE_MAX_CHARS = 300
DESCRIPTION_MAX_CHARS = 5000
COMMENT_MAX_CHARS = 2000
SCRUB_MAX_CHARS = 20000  # longer than any field the API returns, so a cut never splits an identifier
CUT = " [cut]"
DEFAULT_ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"
QUOTA_REASONS = frozenset({"quotaExceeded", "dailyLimitExceeded", "dailyLimitExceededUnreg"})
RATE_REASONS = frozenset({"rateLimitExceeded", "userRateLimitExceeded", "RATE_LIMIT_EXCEEDED", "RESOURCE_EXHAUSTED"})
KEY_REASONS = frozenset({"keyInvalid", "keyExpired", "accessNotConfigured", "ipRefererBlocked", "API_KEY_INVALID",
                         "API_KEY_EXPIRED", "SERVICE_DISABLED", "API_KEY_SERVICE_BLOCKED",
                         "API_KEY_HTTP_REFERRER_BLOCKED", "API_KEY_IP_ADDRESS_BLOCKED", "API_KEY_ANDROID_APP_BLOCKED",
                         "API_KEY_IOS_APP_BLOCKED", "UNAUTHENTICATED"})
DISABLED_REASONS = frozenset({"commentsDisabled"})
GONE_REASONS = frozenset({"videoNotFound", "notFound", "NOT_FOUND"})
_REASON = re.compile(r"^[A-Za-z0-9_.]{1,60}$")
_PAGE_TOKEN = re.compile(r"^[A-Za-z0-9_\-=.+/]{1,1000}$")
_ITEM_ID = re.compile(r"^[A-Za-z0-9_.-]{1,120}$")
_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})$")
_LANG = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{1,8}){0,3}$")
_FORGED_HEADER = re.compile(r"(?m)^(\s*)\[(?=\s*comment\b)", re.I)  # a line in free text that mimics a header
IDS_NOTE = ("the video and comment IDs point at people's posts, like post URLs: keep them in the evidence bundle "
            "only, never in reports shared outside the team")

# Tests only: the origin of a fake API on loopback. Never set by a command, a brief, a route table or an
# environment variable, so nothing a user or a page can change sends the key anywhere else.
_TEST_ORIGIN: str | None = None


# ---------------------------------------------------------------- pure helpers


def video_id(route: dict, values: dict) -> str | None:
    """The video ID from a URL's template variables (ladder.Routes.match): the first of the route's
    id_from names that holds a value matching id_pattern. Decided locally; the page is never requested."""
    try:
        pattern = re.compile(route.get("id_pattern") or DEFAULT_ID_PATTERN)
    except (re.error, TypeError):
        return None
    for name in route.get("id_from") or []:
        value = values.get(name) if isinstance(name, str) else None
        if isinstance(value, str):
            value = unquote(value)
            if pattern.fullmatch(value):
                return value
    return None


def quota_reset(now: float, zone_name: str | None) -> float:
    """The next midnight in the quota's time zone (UTC-8 when the zone's data is missing), as UNIX time."""
    zone = None
    if zone_name:
        try:
            from zoneinfo import ZoneInfo
            zone = ZoneInfo(zone_name)
        except (ImportError, KeyError, ValueError, OSError):
            zone = None
    zone = zone or timezone(timedelta(hours=FALLBACK_UTC_OFFSET_H))
    today = datetime.fromtimestamp(now, zone).date()
    return datetime.combine(today + timedelta(days=1), clock_time.min, tzinfo=zone).timestamp()


def api_reasons(text: str) -> set:
    """The reason codes of an API error body (errors[].reason, details[].reason and the status name);
    never its messages."""
    try:
        data = json.loads(text)
    except (ValueError, RecursionError):
        return set()
    error = data.get("error") if isinstance(data, dict) else None
    if not isinstance(error, dict):
        return set()
    found = set()
    for group in ("errors", "details"):
        items = error.get(group) if isinstance(error.get(group), list) else []
        for item in items[:20]:
            reason = item.get("reason") if isinstance(item, dict) else None
            if isinstance(reason, str) and _REASON.match(reason):
                found.add(reason)
    status = error.get("status")
    if isinstance(status, str) and _REASON.match(status):
        found.add(status)
    return found


def answer_kind(status: int, headers: dict, reasons: set) -> str:
    """ok | quota | rate | key | disabled | gone | refused | transient | failed, for one API answer."""
    if 200 <= status < 300:
        return "ok"
    if reasons & QUOTA_REASONS:
        return "quota"
    if status == 429 or reasons & RATE_REASONS or (status == 503 and headers.get("retry-after")):
        return "rate"
    if status == 401 or reasons & KEY_REASONS:
        return "key"
    if reasons & DISABLED_REASONS:
        return "disabled"
    if status in (404, 410) or reasons & GONE_REASONS:
        return "gone"
    if status == 403:
        return "refused"
    if 500 <= status < 600 or status == 408:
        return "transient"
    return "failed"


def _int(value, default: int, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return max(low, min(high, value))


def _count(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, str) and value.isdigit() and len(value) <= 20:
        return int(value)
    return None


def _time(value) -> str | None:
    return value if isinstance(value, str) and len(value) <= 40 and _TIME.match(value) else None


def _endpoint(template, variables: dict) -> str | None:
    """One call's URL from a route template, or None when the template does not fit."""
    if not isinstance(template, str) or "{key}" not in template:
        return None
    url = ladder.expand(template, variables)
    try:
        return net.parse_url(url) if url else None
    except net.NetError:
        return None


def _rehome(url: str) -> str:
    """Tests only: the same call on the fake API's origin (_TEST_ORIGIN)."""
    if not _TEST_ORIGIN:
        return url
    origin, parts = urlsplit(_TEST_ORIGIN), urlsplit(url)
    return urlunsplit((origin.scheme, origin.netloc, parts.path, parts.query, ""))


@dataclass(frozen=True)
class _Settings:
    page_size: int
    max_pages: int
    units: int
    retention_days: int
    reset_zone: str | None


def _settings(route: dict) -> _Settings:
    zone = route.get("quota_reset_tz")
    return _Settings(page_size=_int(route.get("page_size"), DEFAULT_PAGE_SIZE, 1, MAX_PAGE_SIZE),
                     max_pages=_int(route.get("max_pages"), DEFAULT_PAGES, 1, MAX_PAGES),
                     units=_int(route.get("quota_units_per_call"), 1, 1, 10000),
                     retention_days=_int(route.get("retention_days"), MAX_RETENTION_DAYS, 1, MAX_RETENTION_DAYS),
                     reset_zone=zone if isinstance(zone, str) and len(zone) <= 64 else None)


@dataclass
class _Answer:
    """One call's outcome: ok (data holds the JSON object), stop, error, an answer_kind, or an exception
    the request path raised (deferred, host_stopped, budget, neterror)."""
    kind: str
    attempt: object = None
    reasons: set = field(default_factory=set)
    data: dict | None = None
    at: float = 0.0
    note: str | None = None
    exc: Exception | None = None

    def codes(self) -> list:
        return [f"api:{r}" for r in sorted(self.reasons)][:3]


def _comment(item, channel: str | None) -> dict | None:
    """The fields read from one comment thread; the display name only lives here until it is keyed."""
    if not isinstance(item, dict):
        return None
    snippet = item.get("snippet") if isinstance(item.get("snippet"), dict) else {}
    if snippet.get("isPublic") is False:
        return None
    top = snippet.get("topLevelComment") if isinstance(snippet.get("topLevelComment"), dict) else {}
    inner = top.get("snippet") if isinstance(top.get("snippet"), dict) else {}
    text = inner.get("textDisplay") if isinstance(inner.get("textDisplay"), str) else inner.get("textOriginal")
    if not isinstance(text, str):
        return None
    ident = item.get("id") if isinstance(item.get("id"), str) else top.get("id")
    author_channel = inner.get("authorChannelId")
    author_channel = author_channel.get("value") if isinstance(author_channel, dict) else None
    published = _time(inner.get("publishedAt"))
    return {"id": ident if isinstance(ident, str) and _ITEM_ID.match(ident) else None,
            "name": inner.get("authorDisplayName"), "text": text, "published": published,
            "updated": _time(inner.get("updatedAt")), "likes": _count(inner.get("likeCount")),
            "replies": _count(snippet.get("totalReplyCount")),
            "by_uploader": bool(channel) and isinstance(author_channel, str) and author_channel == channel}


# ---------------------------------------------------------------- one URL


class _Session:
    def __init__(self, st, platform: dict, route: dict, official_only: bool):
        self.st, self.run, self.route, self.official_only = st, st.run, route, official_only
        self.route_id = str(platform.get("id") or "api")
        self.env = ladder.user_key(route)[1]
        self.s = _settings(route)
        self.video: str | None = None
        self.order: str | None = None
        self.calls = self.units = self.pages = self.comments_read = 0
        self.fetch_ids: list = []
        self.reported: int | None = None
        self.more = False
        self.partial: str | None = None
        self.scrubbed: dict = {}
        self._salt: bytes | None = None

    # ------------------------------------------------------------ results

    def tags(self) -> list:
        return [f"route:{self.route_id}"] + (["official_only"] if self.official_only else [])

    def extra(self, retention_until: str | None = None) -> dict:
        api = {"route": self.route_id, "adapter": self.route.get("adapter"), "video_id": self.video,
               "calls": self.calls, "quota_units": self.units, "fetch_ids": list(self.fetch_ids), "order": self.order,
               "page_size": self.s.page_size, "page_cap": self.s.max_pages, "pages": self.pages,
               "comments_read": self.comments_read, "reported_comments": self.reported,
               "more_available": self.more, "partial_because": self.partial,
               "retention_days": self.s.retention_days}
        return {"api": api, **({"retention_until": retention_until} if retention_until else {})}

    def done(self, bucket: str, *, reasons=(), attempt=None, retention_until: str | None = None, **kwargs):
        result = ladder._done(self.st, bucket, reasons=[*reasons, *self.tags()], rung="R0", attempt=attempt,
                              extra=self.extra(retention_until), **kwargs)
        return result, self.calls

    def fail(self, *reasons) -> tuple:
        """The route cannot serve this URL: None, with the reasons for a terms_restricted stop."""
        self.st.route_reasons.extend(r for r in reasons if r)
        return None, self.calls

    # ------------------------------------------------------------ calls

    def call(self, url: str, method: str, page: int | None, *, control_retry: bool = False) -> _Answer:
        """One API call through the reader's request path (ladder._request): the scope checks, the API
        host's robots.txt, a paced slot charged to the budgets, no redirect followed."""
        try:
            attempt = ladder._request(self.st, url, "R0", accept=ladder.JSON_ACCEPT, purpose="route",
                                      redirects=False)
        except Deferred as exc:
            return _Answer("deferred", exc=exc)
        except HostStopped as exc:
            return _Answer("host_stopped", exc=exc)
        except BudgetExceeded as exc:
            return _Answer("budget", exc=exc)
        except net.NetError as exc:
            return _Answer("neterror", exc=exc)
        now = self.run.clock()
        if attempt.response is not None or attempt.error not in (None, "robots_unreachable"):
            self.calls += 1
        label = method + (f" page {page}" if page else "")
        if attempt.stop:
            ladder._trail(self.st, "R0", "stopped", url=url, attempt=attempt,
                          note=f"{label}: {', '.join(attempt.reasons[:2])}")
            return _Answer("stop", attempt, at=now)
        if attempt.error:
            ladder._trail(self.st, "R0", "failed", url=url, attempt=attempt, note=label)
            return _Answer("error", attempt, at=now)
        response = attempt.response
        self.units += self.s.units
        self.fetch_ids.append(attempt.fetch_id)
        text = response.text()[0]
        control_page, control = ladder._route_control(self.st, attempt, text)
        if control_page is not None and control.stop_class:
            ladder._log_attempt(self.run, attempt, control, control_page,
                                extra={"route": self.route_id, "api_method": method, "api_page": page,
                                       "quota_units": self.s.units, "api_answer": "access_control"})
            ladder._trail(self.st, "R0", "stopped", url=url, attempt=attempt, v=control, note=label)
            if ladder._host_signal(control):
                noted = self.note_rate(attempt, control.reasons)
                if not noted["stopped"] and not control_retry:
                    retried = self.call(url, method, page, control_retry=True)
                    if retried.kind in ("ok", "response_stop"):
                        return retried
                    if retried.kind == "rate":
                        self.note_rate(retried.attempt, retried.codes())
            elif control.stop_class in verdict.HOST_STOPPING and control.host_wide:
                self.run.stop_host(net.host_of(response.final_url), control.stop_class,
                                   ladder.site_stop_reason(control), control.reasons)
            attempt.stop, attempt.reasons = control.stop_class, list(control.reasons)
            return _Answer("response_stop", attempt, at=now)
        reasons = set() if 200 <= response.status < 300 else api_reasons(text)
        kind = answer_kind(response.status, response.headers, reasons)
        data, note = None, None
        if kind == "ok":
            optouts = robots.page_optouts(response.headers, [], None, ROBOTS_TOKEN, response.x_robots)
            if optouts:
                attempt.stop, attempt.reasons, kind = "opted_out", list(optouts), "stop"
            else:
                try:
                    data = json.loads(text)
                except (ValueError, RecursionError):
                    data = None
                if not isinstance(data, dict):
                    kind, note, data = "failed", "api_bad_answer", None
        ladder._log_attempt(self.run, attempt, extra={"route": self.route_id, "api_method": method, "api_page": page,
                                                      "quota_units": self.s.units, "api_answer": note or kind,
                                                      "api_reasons": sorted(reasons)[:4] or None})
        outcome = "read" if kind == "ok" else "stopped" if kind == "stop" else "failed"
        codes = sorted(reasons)[:2]
        ladder._trail(self.st, "R0", outcome, url=url, attempt=attempt,
                      note=label + (f": {', '.join(codes)}" if codes else f": {note}" if note else ""))
        return _Answer(kind, attempt, reasons, data, now, note)

    def hold_quota(self, attempt) -> float:
        until = quota_reset(self.run.clock(), self.s.reset_zone)
        self.run.hold_host(net.host_of(attempt.response.final_url), until, "quota")
        return until

    def note_rate(self, attempt, codes: list) -> dict:
        response = attempt.response
        wait = verdict.retry_after_seconds(response.headers.get("retry-after"), self.run.clock())
        return self.run.note_rate_limit(net.host_of(response.final_url), wait, [f"status:{response.status}", *codes])

    def stop_key(self, attempt, codes: list) -> None:
        self.run.stop_host(net.host_of(attempt.response.final_url), "key_rejected",
                           f"the API rejected the key in ${self.env}", codes)

    def settle(self, answer: _Answer) -> tuple:
        """The URL's end when its first call of a kind did not answer with data."""
        kind, attempt, codes = answer.kind, answer.attempt, answer.codes()
        if kind == "deferred":
            return self.done("deferred", reasons=[f"deferred:{answer.exc.why}"], retry_after_s=answer.exc.retry_after_s)
        if kind == "host_stopped":
            stop = answer.exc.stop
            if stop.get("class") == "key_rejected":
                return self.fail(f"official_route_key_rejected:{self.env}", "host_stop:key_rejected")
            if not self.official_only:
                return self.fail("official_route_failed", f"host_stop:{stop.get('class')}")
            return self.done("stopped", stop="host_stopped", reasons=[f"host_stop:{stop.get('class')}"], host_stop=stop)
        if kind == "budget":
            exc = answer.exc
            if exc.scope == "host" and not self.official_only:
                return self.fail("official_route_failed", f"budget:{exc.scope}:{exc.limit}")
            return self.done("stopped", stop="budget", reasons=[f"budget:{exc.scope}:{exc.limit}"])
        if kind == "neterror":
            return self.fail("official_route_failed", f"api_error:{answer.exc.kind}")
        if kind in ("stop", "response_stop"):  # scope, robots.txt, a login redirect, or response controls
            if not self.official_only and not attempt.contacted and kind != "response_stop":
                return self.fail("official_route_failed", *attempt.reasons[:2])
            return self.done("stopped", stop=attempt.stop, reasons=list(attempt.reasons), attempt=attempt,
                             out_of_scope=attempt.out_of_scope,
                             host_stop=self.run.host_stop(net.host_of(attempt.response.final_url)) if
                             attempt.response else None,
                             terms=attempt.scope_stop.terms if attempt.scope_stop else None)
        if kind == "error":
            if attempt.error == "robots_unreachable":
                return self.done("deferred", error=attempt.error, attempt=attempt, retry_after_s=attempt.retry_after_s,
                                 reasons=["robots_unreachable", ladder.ROBOTS_UNREACHABLE])
            if attempt.error in net.TRANSIENT_KINDS:
                return self.done("deferred", error=attempt.error, reasons=[attempt.error_detail or attempt.error],
                                 attempt=attempt, retry_after_s=ladder.TRANSIENT_RETRY_S)
            return self.fail("official_route_failed", f"api_error:{attempt.error}")
        status = attempt.response.status
        if kind == "quota":
            until = self.hold_quota(attempt)
            return self.done("deferred", reasons=["quota_exhausted", *codes], attempt=attempt,
                             retry_after_s=max(1, int(math.ceil(until - self.run.clock()))))
        if kind == "rate":
            noted = self.note_rate(attempt, codes)
            if noted["stopped"]:
                return self.done("stopped", stop="rate_limit", attempt=attempt, host_stop=noted["stop"],
                                 reasons=["rate_limited", *codes, noted["stop"]["reason"]])
            return self.done("deferred", reasons=["rate_limited", *codes], attempt=attempt,
                             retry_after_s=max(1, int(math.ceil(noted["wait_s"]))))
        if kind == "key":
            self.stop_key(attempt, codes)
            return self.fail(f"official_route_key_rejected:{self.env}", *codes)
        if kind == "refused":
            return self.fail("official_route_refused", *codes)
        if kind in ("disabled", "gone"):
            why = "comments_disabled" if kind == "disabled" else "video_not_found"
            return self.done("stopped", stop="gone", reasons=[why, *codes], attempt=attempt)
        if kind == "transient":
            return self.done("deferred", reasons=[f"status:{status}", *codes], attempt=attempt,
                             retry_after_s=ladder.TRANSIENT_RETRY_S)
        return self.fail("official_route_failed", *(codes or [answer.note or f"api_status:{status}"]))

    def partial_reason(self, answer: _Answer) -> str:
        """Why comment paging stopped after a page was read; the answer's side effects still apply (a
        quota hold, a rate-limit signal, a key stop)."""
        kind, attempt, codes = answer.kind, answer.attempt, answer.codes()
        if kind == "deferred":
            return f"deferred:{answer.exc.why}"
        if kind == "host_stopped":
            return f"host_stop:{answer.exc.stop.get('class')}"
        if kind == "budget":
            return f"budget:{answer.exc.scope}:{answer.exc.limit}"
        if kind == "neterror":
            return f"api_error:{answer.exc.kind}"
        if kind == "stop":
            return f"stopped:{attempt.stop}"
        if kind == "error":
            return f"api_error:{attempt.error}"
        if kind == "quota":
            self.hold_quota(attempt)
            return "quota_exhausted"
        if kind == "rate":
            noted = self.note_rate(attempt, codes)
            return "rate_limit:host_stopped" if noted["stopped"] else "rate_limited"
        if kind == "key":
            self.stop_key(attempt, codes)
            return "key_rejected"
        return answer.note or (codes[0] if codes else f"api_status:{attempt.response.status}")

    # ------------------------------------------------------------ text

    def clean(self, value, limit: int, *, one_line: bool = False) -> str:
        """A free-text field, scrubbed before it is cut, so a cut never leaves part of an identifier. A line
        that mimics a comment header ('[comment 9 | id ...') starts with '(' instead, so a commenter
        cannot pass text off as another comment."""
        text = extract.nfc(value[:SCRUB_MAX_CHARS]) if isinstance(value, str) else ""
        if one_line:
            text = " ".join(text.split())
        text, found = privacy.scrub(text)
        for name, n in found.items():
            self.scrubbed[name] = self.scrubbed.get(name, 0) + n
        text = _FORGED_HEADER.sub(r"\1(", text.strip())
        return text if len(text) <= limit else text[:limit].rstrip() + CUT

    def key(self, name) -> str | None:
        """The salted author key of a display name or channel title; None when it is no identity."""
        if not isinstance(name, str) or not name.strip():
            return None
        if self._salt is None:
            self._salt = self.run.salt
        try:
            return privacy.author_key(self._salt, self.route_id, name[:200])
        except ValueError:
            return None

    def compose(self, record: dict, video_answer: _Answer, comments: list):
        snippet = record.get("snippet") if isinstance(record.get("snippet"), dict) else {}
        stats = record.get("statistics") if isinstance(record.get("statistics"), dict) else {}
        days = self.s.retention_days * 86400
        until = iso(video_answer.at + days)
        title = self.clean(snippet.get("title"), TITLE_MAX_CHARS, one_line=True)
        description = self.clean(snippet.get("description"), DESCRIPTION_MAX_CHARS)
        uploader = self.key(snippet.get("channelTitle"))
        shown = [(label, _count(stats.get(name))) for label, name in (("views", "viewCount"), ("likes", "likeCount"),
                                                                      ("comments", "commentCount"))]
        self.reported = dict(shown)["comments"]
        lang = next((v for v in (snippet.get("defaultAudioLanguage"), snippet.get("defaultLanguage"))
                     if isinstance(v, str) and _LANG.match(v)), "")
        head = [f"video {self.video}", f"title: {title or '(none)'}",
                f"published: {_time(snippet.get('publishedAt')) or '-'}",
                f"uploader: author {uploader}" if uploader else "uploader: not keyed",
                "counts: " + (", ".join(f"{label} {n}" for label, n in shown if n is not None) or "not shown"),
                f"keep until: {until}", "description:", description or "(none)"]
        more = "more not read" if self.more else "no more pages"
        body = [f"comments: {len(comments)} read, order {self.order or '-'}, {self.pages} page(s) of up to "
                f"{self.s.page_size}; {more}"]
        blocks = [{"block": "description", "text": description}]
        research_items = []
        for i, item in enumerate(comments, 1):
            author = self.key(item["name"])
            header = [f"comment {i}", f"id {item['id'] or '-'}", f"author {author}" if author else "author not keyed",
                      f"published {item['published'] or '-'}"]
            if item["updated"] and item["updated"] != item["published"]:
                header.append(f"edited {item['updated']}")
            header += [f"{label} {item[name]}" for label, name in (("likes", "likes"), ("replies", "replies"))
                       if item[name] is not None]
            if item["by_uploader"]:
                header.append("by uploader")
            header.append(f"keep until {iso(item['at'] + days)}")
            text = self.clean(item["text"], COMMENT_MAX_CHARS)
            body.append("[" + " | ".join(header) + "]\n" + (text or "(empty)"))
            research_items.append({"item_key": item["id"] or str(i), "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                                   "author_key": author, "published_at": (item["published"] or "")[:10] or None,
                                   "retention_until": iso(item["at"] + days), "block": f"comment:{item['id'] or i}"})
            blocks.append({"block": f"comment:{item['id'] or i}", "text": text, "by_uploader": item["by_uploader"]})
        if not comments:
            body.append("(no comments)")
        listing = "\n\n".join(body)
        page = extract.from_text("\n".join(head) + "\n\n" + listing)
        page.kind = page.extraction_source = "api"
        page.title, page.lang, page.description = title[:500], lang[:20], description[:1000]
        page.main_text = extract.nfc(extract.tidy((description or "") + "\n\n" + listing))[:extract.TEXT_CAP_CHARS]
        # The flag checks read each block on its own: the uploader's description has its own lead and tail, and
        # each comment is its own block, so a viewer's words are never the video's disclosure (verdict.content_flags).
        page.flag_blocks = blocks
        page.research_items = research_items
        return page, until

    # ------------------------------------------------------------ the URL

    def read(self, values: dict) -> tuple:
        st = self.st
        self.video = video_id(self.route, values)
        if self.video is None:
            ladder._trail(st, "R0", "skipped", note=f"route {self.route_id}: no video ID in this URL")
            return self.fail("official_route_does_not_fit")
        # The URL's own template variables ({scheme}, {port_suffix}, ...) plus the adapter's: {id}, {page_size}.
        variables = {**values, "id": quote(self.video, safe=""), "page_size": str(self.s.page_size)}
        fields = ("url", "comments_url")
        probes = [_endpoint(self.route.get(name), {**variables, "key": "KEY"}) for name in fields]
        if not all(probes):
            ladder._trail(st, "R0", "skipped", note=f"route {self.route_id}: its endpoint templates do not fit")
            return self.fail("official_route_unavailable")
        key = None
        for probe in probes:
            key, withheld = ladder.key_for(self.route, probe)
            if withheld:
                ladder._trail(st, "R0", "skipped", note=ladder.withheld_note(withheld, self.env))
                return self.fail(withheld)
        secret = {**variables, "key": quote(key, safe="")}
        video_url, comments_url = (_endpoint(self.route.get(name), secret) for name in fields)
        if not video_url or not comments_url:
            return self.fail("official_route_unavailable")
        video_url, comments_url = _rehome(video_url), _rehome(comments_url)
        self.order = dict(parse_qsl(urlsplit(comments_url).query)).get("order")

        video = self.call(video_url, "videos.list", None)
        if video.kind != "ok":
            return self.settle(video)
        items = video.data.get("items") if isinstance(video.data.get("items"), list) else []
        record = next((item for item in items if isinstance(item, dict) and item.get("id") in (None, self.video)), None)
        if record is None:  # removed, private, or never there
            return self.done("stopped", stop="gone", reasons=["video_not_found"], attempt=video.attempt)
        snippet = record.get("snippet") if isinstance(record.get("snippet"), dict) else {}
        channel = snippet.get("channelId") if isinstance(snippet.get("channelId"), str) else None

        comments: list = []
        seen: set = set()
        token = None
        while self.pages < self.s.max_pages:
            url = comments_url if token is None else f"{comments_url}&pageToken={quote(token, safe='')}"
            answer = self.call(url, "commentThreads.list", self.pages + 1)
            if answer.kind != "ok":
                if self.pages == 0 or answer.kind == "response_stop" or \
                        (answer.kind == "stop" and answer.attempt.contacted):
                    return self.settle(answer)
                self.partial, self.more = self.partial_reason(answer), True
                break
            items = answer.data.get("items") if isinstance(answer.data.get("items"), list) else []
            for item in items[:MAX_PAGE_SIZE]:
                found = _comment(item, channel)
                if found is None or (found["id"] and found["id"] in seen):
                    continue
                seen.add(found["id"])
                found["at"] = answer.at
                comments.append(found)
            self.pages += 1
            following = answer.data.get("nextPageToken")
            if following is None or following == "":
                self.more = False
                break
            if not isinstance(following, str) or not _PAGE_TOKEN.match(following) or following == token:
                self.partial, self.more = "api_bad_page_token", True
                break
            token, self.more = following, True
        self.comments_read = len(comments)
        page, until = self.compose(record, video, comments)
        lowered = page.text.lower()
        reasons = ["official:api"] + [f"expect:{t}" for t in st.expect if t and t.lower() in lowered][:3]
        notes = [IDS_NOTE]
        policy = self.route.get("policy_note")
        if isinstance(policy, str) and policy.strip():
            notes.insert(0, policy.strip()[:1200])
        if self.partial:
            reasons.append("comments_partial")
            notes.append(f"comment paging stopped early ({self.partial}); api.more_available says whether comments "
                         "were left unread")
        return self.done("read", verdict_="ok_strong", reasons=reasons, attempt=video.attempt, page=page,
                         access_basis="official_api", notes=notes, prescrubbed=dict(self.scrubbed),
                         retention_until=until)


def read_route(st, platform: dict, route: dict, values: dict, *, official_only: bool = False) -> tuple:
    """Read one video URL through the route (the module notes say how). Returns (the URL's result, or
    None when the route cannot serve it and st.route_reasons says why; the API calls made)."""
    return _Session(st, platform, route, official_only).read(values)


__all__ = ["read_route", "video_id", "quota_reset", "api_reasons", "answer_kind", "ADAPTER_API", "MAX_PAGE_SIZE",
           "MAX_PAGES", "MAX_RETENTION_DAYS"]
