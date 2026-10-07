"""Visible text and page facts from HTML, plain text, render captures and feeds.

html.parser only. Visible text skips script, style, noscript, template, svg and
head content (and elements marked hidden), keeps paragraph breaks and is capped
at 400 KB. The parser also records: title, description, Open Graph, canonical,
lang; declared alternates (mobile/handheld, AMP, RSS/Atom); robots,
tdm-reservation and refresh meta; password inputs and captcha widgets, and
whether they sit inside a form or inside the page's navigation chrome; the
length of the main content; and JSON-LD, at most 10 blocks and 1 MB, of which
only isAccessibleForFree, articleBody, reviewBody, aggregateRating and the
author's @type are kept. A Review node becomes one text item: the reviewer's
name is dropped for an '[author]' placeholder, and the date, rating and body
stay.

Privacy, structure-based: a page marks whose text is a person's label with
itemprop="author", rel="author" or an id/class/data-* token from
markers.json author_idents (matched split on hyphens and underscores), and,
inside such an element, a link whose target is a member or profile URL
(privacy.profile_href). The reader drops everything a label holds — its own
text and any child's, so a name sitting in an <a>, <strong>, <b> or <span
class="name"> goes with the label's own name — and writes '[author]' in its
place. Two kinds of text survive inside a label: text in a time element or an
element with a keep_in_author_idents token (date, time, count and rating
markers), and a text piece that on its own is only a date, a time, a relative
time, a number with an optional unit or a rating; alt and title attribute
text is never read anywhere. An element marked this way that holds running
text longer than author_label_chars is a wrapper, and its text stays, so a
post body or a comment is never lost with the name — but a nested short label
or a member/profile link inside a wrapper is still dropped. Elements whose
idents carry an item_idents token (comment,
reply, review) open with a '---' line, one per item, so a page that holds
several people's items keeps a visible boundary even without labels. A
platform whose markup needs a token the packaged lists lack can add one in
its routes.json entry (drop for chrome, author for labels). Render captures
(ux-page-read.v1) carry no markup in their text field, so the structure-based
pass there covers their json_ld; the plain pattern scrub (privacy.py) still
runs over everything.

Chrome comes in two kinds. Navigation chrome (headers, navigation, footers,
sidebars, menus, login boxes and the like) repeats on every page of a site.
Widget chrome (buttons, labels, selects, text areas, dialogs) holds controls. A
form counts as chrome only inside navigation chrome, so a form that wraps a
whole page (common on older sites) does not hide the post inside it. Main
content is the text outside both kinds of chrome, inside main or article when
the page has them. `notice_text` is the text a site notice could be in: outside
navigation chrome and outside links.

The JSON-LD body replaces the visible text only when it is longer, and
`extraction_source` says which one was used. `main_text` is the main content
as text (the JSON-LD body when that was used); the promotion, incentive and
virtual-person checks read their lead and tail positions from it. Text is
NFC-normalised.
"""
from __future__ import annotations

import json
import re
import functools
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from . import ROBOTS_TOKEN, privacy

TEXT_CAP_CHARS = 400 * 1024
PARSE_CAP_CHARS = 4 * 1024 * 1024  # markup beyond this is not parsed (hostile or oversized pages)
MAX_DEPTH = 1024  # deeper elements are not tracked, so hostile nesting stays linear
JSONLD_MAX_BLOCKS = 10
JSONLD_MAX_BYTES = 1024 * 1024
FEED_MAX_ITEMS = 200
SKIP_TAGS = frozenset({"script", "style", "noscript", "template", "svg", "head", "iframe", "object", "canvas", "math"})
VOID_TAGS = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param",
                       "source", "track", "wbr"})
BLOCK_TAGS = frozenset({"p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "table",
                        "section", "article", "header", "footer", "nav", "aside", "main", "blockquote", "pre",
                        "dd", "dt", "dl", "figure", "figcaption", "form", "hr", "address", "details",
                        "summary", "fieldset", "legend", "tbody", "thead", "tfoot", "caption"})
CELL_TAGS = frozenset({"td", "th"})
NAV_TAGS = frozenset({"header", "nav", "footer", "aside", "menu"})
NAV_ROLES = frozenset({"navigation", "banner", "contentinfo", "complementary", "search", "menu", "menubar",
                       "toolbar"})
WIDGET_TAGS = frozenset({"button", "select", "option", "label", "textarea", "dialog"})
WIDGET_ROLES = frozenset({"dialog", "alertdialog"})
MAIN_TAGS = frozenset({"main", "article"})
FRAME_TAGS = frozenset({"iframe", "img", "embed"})
FEED_TYPES = frozenset({"application/rss+xml", "application/atom+xml", "application/feed+json"})
_ALERT = re.compile(r"\balert\s*\(\s*([\"'])(.{1,300}?)\1", re.S)
_HIDDEN_STYLE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden", re.I)
_REFRESH = re.compile(r"^\s*(\d{1,6})(?:\.\d*)?\s*(?:[;,]\s*(?:url\s*=\s*)?[\"']?\s*([^\"'\s][^\"']*?)\s*[\"']?\s*)?$", re.I)
TOKEN_CAP = 2000
AUTHOR_LABEL_CHARS = 80  # a name cell is this short; a longer element marked as one is a wrapper, and its text stays
AUTHOR_PLACEHOLDER = "[author]"
ITEM_SEPARATOR = "---"
IDENT_SPLIT = re.compile(r"[-_]+")
# An element that also carries one of these tokens holds a whole list or a part of one item, not the
# boundary between two people's items, so it opens no '---' separator and blocks none.
ITEM_SIDE_TOKENS = frozenset({"list", "lists", "wrap", "wrapper", "box", "area", "all", "group", "container",
                              "section", "holder", "info", "count", "cnt", "num", "total", "sort", "order",
                              "filter", "write", "form", "pagination", "pager", "more", "body", "content",
                              "text"})
ROUTES_PATH = Path(__file__).resolve().parent / "data" / "routes.json"

# Inside an author label a text piece survives only when it is, on its own, one of these shapes: a date, a
# time, a relative time, a number with an optional unit or count word, or a rating. Everything else in the
# label is the person's name and goes. keep_in_author_idents (markers.json) keeps the same ground
# structurally: a time element or a date/count/rating token keeps its text whatever it says. Separators
# around and between such pieces (' · ', ' | ') are layout, not a name, and stay.
_VALUE_EDGE = " \t\n\r\f\v·|/:,;()[]{}<>\"'“”‘’.-–—~ㆍ∙•"
_VALUE_SPLIT = re.compile(r"[·|/,;()\[\]{}•∙ㆍ]")
_NUM = r"\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?"
_MONTHS = r"jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec"
_KO_UNITS = r"건|명|개|번|회|점|층|권|잔|편|곡|부|대|마리|채|살|표|위|등|배|천|만|억|조|년|월|일|주|달|개월|시간|시|분|초"
_EN_UNITS = r"years?|yrs?|months?|weeks?|days?|hours?|hrs?|minutes?|mins?|seconds?|secs?|views?|likes?|k|m|g|b"
_COUNT_WORDS = r"(?:조회|추천|비추|반대|댓글|덧글|댓수|좋아요|싫어요|별점|평점|평가|점수|리뷰|like|likes|view|views|hit|hits|comment|comments|reply|replies|count|score|rating|star|stars)"
_DATE = (r"\d{4}\s?[년./-]\s?\d{1,2}\s?[월./-]\s?\d{1,2}\s?일?"           # 2026-09-01, 2026.09.27, 2026년 9월 1일
         r"|\d{4}\s?년(?:\s?\d{1,2}\s?월)?(?:\s?\d{1,2}\s?일)?"          # 2026년, 2026년 9월
         r"|\d{1,2}\s?월(?:\s?\d{1,2}\s?일)?"                           # 9월, 9월 1일
         r"|\d{1,2}\s?[./-]\s?\d{1,2}"                                # 9/1, 09.01
         rf"|(?:{_MONTHS})[a-z]*\.?\s*\d{{1,2}}(?:st|nd|rd|th)?(?:\s*,\s*\d{{4}})?"  # Sep 1, Sep 1, 2026
         rf"|\d{{1,2}}\s+(?:{_MONTHS})[a-z]*\.?(?:\s*,?\s*\d{{4}})?")   # 1 Sep, 1 Sep 2026
_TIME = r"(?:오전|오후|am|pm)?\s*\d{1,2}\s?:\s?\d{2}(?:\s?:\s?\d{2})?\s?(?:am|pm)?"
_RELATIVE = (r"\d+\s?(?:초|분|시간|일|주|개월|달|년)\s?(?:전|후|째)"        # 3시간 전, 3시간전, 2일째
             r"|\d+\s?(?:" + _EN_UNITS + r")\s+ago"                   # 2 days ago
             r"|방금|방금전|금방|아까|어제|그제|작일|금일|오늘|올해|작년|내년|모레|지금|just now|yesterday|today|now")
_NUMBER = (rf"(?:{_COUNT_WORDS})?\s*[:.]?\s*(?:{_NUM})(?:\s?(?:{_KO_UNITS}|{_EN_UNITS}|%|\+))?"
           rf"(?:\s?/\s?(?:{_NUM})(?:\s?(?:{_KO_UNITS}|{_EN_UNITS}|%|\+))?)?")
_VALUE_SHAPE = re.compile("|".join((
    f"(?:{_DATE})(?:\\s+(?:{_TIME}))?",
    _TIME,
    _RELATIVE,
    _NUMBER,
    "[★☆✩✪⭐]{1,10}",
)), re.I)


def _keeps_value(text: str) -> bool:
    """True when a text piece inside an author label is only a value the label carries next to the name: a
    date, a time, a relative time, a number with an optional unit or count word, or a rating (each
    separator-delimited piece must be one of these, so '3시간 전 · 조회 5' stays while '이름 · 조회 5'
    does not). Never a name: no shape matches letters that are not count words or months."""
    stripped = text.strip(_VALUE_EDGE)
    if not stripped:
        return True  # separators and whitespace between children are layout, not a name
    pieces = [piece.strip(_VALUE_EDGE) for piece in _VALUE_SPLIT.split(stripped)]
    return all(_VALUE_SHAPE.fullmatch(piece) for piece in pieces if piece)


def nonspace(text: str) -> int:
    return len("".join(text.split()))


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def tidy(raw: str) -> str:
    text = re.sub(r"[\u200b\ufeff]", "", raw)  # zero-width space and stray byte-order marks vanish
    text = re.sub(r"[ \t\f\v\r\u00a0\u3000]+", " ", text)  # no-break and ideographic spaces become spaces
    text = re.sub(r" *\n *", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


@dataclass
class Page:
    kind: str
    text: str = ""
    visible_text: str = ""
    main_text: str = ""  # the main content only (outside chrome; inside main or article when the page has them)
    extraction_source: str = "html"
    visible_chars: int = 0
    main_chars: int = 0
    title: str = ""
    lang: str = ""
    description: str = ""
    og: dict = field(default_factory=dict)
    canonical: str | None = None
    alternates: list = field(default_factory=list)
    meta_robots: list = field(default_factory=list)
    tdm_meta: str | None = None
    meta_refresh: str | None = None
    refresh_delay: int | None = None  # seconds, from <meta http-equiv="refresh">
    refresh_url: str | None = None  # the absolute URL a meta refresh sends the visitor to
    password_inputs: int = 0
    open_password_inputs: int = 0  # password inputs outside navigation chrome (not a header login box)
    notice_text: str = ""  # text outside navigation chrome and outside links: where a site notice can be
    main_container: bool = False  # the page has a main or article element
    free_chars: int = 0  # main-content characters outside any form
    main_free_chars: int = 0  # characters inside main or article, outside chrome and forms
    jsonld_blocks: int = 0
    jsonld_free: bool | None = None
    jsonld_body_chars: int = 0
    jsonld_rating: dict | None = None
    jsonld_author_types: list = field(default_factory=list)
    ids: set = field(default_factory=set)
    classes: set = field(default_factory=set)
    attrs: set = field(default_factory=set)
    tags: set = field(default_factory=set)
    srcs: list = field(default_factory=list)
    script_srcs: list = field(default_factory=list)
    form_idents: set = field(default_factory=set)  # id and class tokens seen inside a form
    open_idents: set = field(default_factory=set)  # id and class tokens seen outside any form
    form_srcs: list = field(default_factory=list)  # iframe, img and embed sources inside a form
    open_srcs: list = field(default_factory=list)  # iframe, img and embed sources outside any form
    input_names: list = field(default_factory=list)
    hrefs: list = field(default_factory=list)
    noscript_text: str = ""
    alerts: list = field(default_factory=list)
    challenge_interactive: bool | None = None
    challenge_markers: list = field(default_factory=list)
    truncated: bool = False

    @property
    def login_form(self) -> bool:
        return self.password_inputs > 0

    def metadata(self) -> dict:
        return {"title": self.title[:300], "lang": self.lang[:20], "description": self.description[:500],
                "og": {k: v[:300] for k, v in list(self.og.items())[:12]}}


def _join(base: str, href: str) -> str | None:
    """urljoin that returns None instead of raising on malformed input such as 'http://[x'."""
    try:
        joined = urljoin(base, href.strip())
        urlsplit(joined).hostname  # raises ValueError for a malformed authority
        return joined
    except ValueError:
        return None


def _section_tokens(markers: dict, name: str) -> frozenset:
    """A markers.json token list; a section may be a plain list or a versioned {version, tokens} object."""
    section = markers.get(name)
    if isinstance(section, dict):
        section = section.get("tokens")
    return frozenset(t for t in (section or ()) if isinstance(t, str))


def _marker_tokens(markers: dict | None) -> tuple[frozenset, frozenset, frozenset, frozenset]:
    """(chrome, author, item, keep) ident tokens. Author, item and keep tokens match split on hyphens and
    underscores ('author-name' and 'nick_area' carry 'author' and 'nick'); chrome tokens stay whole-token,
    as before."""
    if markers is None:
        from .verdict import load_markers
        markers = load_markers()
    return (frozenset(markers.get("chrome_idents", ())),
            _section_tokens(markers, "author_idents"),
            _section_tokens(markers, "item_idents"),
            _section_tokens(markers, "keep_in_author_idents"))


@functools.lru_cache(maxsize=1)
def _route_overrides() -> tuple:
    """(host, drop tokens, author tokens) per host of every platform in the packaged route table that
    carries the optional drop or author fields."""
    try:
        routes = json.loads(ROUTES_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ()
    found = []
    for platform in routes.get("platforms", ()):
        if not isinstance(platform, dict):
            continue
        drop = frozenset(t for t in platform.get("drop", ()) if isinstance(t, str))
        author = frozenset(t for t in platform.get("author", ()) if isinstance(t, str))
        for host in platform.get("hosts", ()):
            if isinstance(host, str) and host and (drop or author):
                found.append((host.lower(), drop, author))
    return tuple(found)


def _platform_tokens(url: str) -> tuple[frozenset, frozenset]:
    """A URL's platform's extra chrome (drop) and author tokens; a platform needs them only when its markup
    carries a token the packaged lists do not."""
    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:
        return frozenset(), frozenset()
    drop: set = set()
    author: set = set()
    for pattern, drops, authors in _route_overrides():
        if host == pattern or (pattern.startswith("*.") and host.endswith(pattern[1:])):
            drop |= drops
            author |= authors
    return frozenset(drop), frozenset(author)


def _ident_tokens(ident: str, classes: list, attrs: dict) -> frozenset:
    """id, class and data-* name tokens, whole and split on hyphens and underscores."""
    tokens: set = set()
    for value in [ident] + list(classes):
        if value:
            tokens.add(value)
            tokens.update(IDENT_SPLIT.split(value))
    for name in attrs:
        if name.startswith("data-"):
            tokens.add(name[5:])
            tokens.update(IDENT_SPLIT.split(name[5:]))
    return frozenset(tokens)


class _Parser(HTMLParser):
    def __init__(self, base_url: str, chrome_tokens: frozenset, author_tokens: frozenset = frozenset(),
                 item_tokens: frozenset = frozenset(), keep_tokens: frozenset = frozenset()):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.chrome_tokens = chrome_tokens
        self.author_tokens = author_tokens
        self.item_tokens = item_tokens
        self.keep_tokens = keep_tokens
        self.page = Page(kind="html")
        self.stack: list[tuple[str, dict]] = []
        self.open: dict[str, int] = {}
        self.depth = {"skip": 0, "nav": 0, "chrome": 0, "form": 0, "link": 0, "main": 0, "title": 0, "noscript": 0,
                      "jsonld": 0, "script": 0, "author": 0, "item": 0, "keep": 0}
        self.author_scopes: list[dict] = []  # open author-labelled elements, outermost first
        self.parts: list[str] = []
        self.notice_parts: list[str] = []
        self.body_parts: list[str] = []  # outside chrome
        self.main_parts: list[str] = []  # outside chrome, inside main or article
        self.size = 0
        self.notice_size = 0
        self.body_size = 0
        self.main_size = 0
        self.main_seen = False
        self.main_count = 0
        self.body_count = 0
        self.free_count = 0
        self.main_free_count = 0
        self.jsonld: list[str] = []
        self.jsonld_bytes = 0
        self.jsonld_index: int | None = None
        self.script_text: list[str] = []
        self.script_bytes = 0
        self.noscript: list[str] = []

    def _emit(self, text: str, notice: bool = True) -> None:
        """Visible text; `notice` also adds it to the text a site notice could be in."""
        if self.author_scopes and self.author_scopes[-1]["mode"] == "label" and not text.strip():
            return  # layout whitespace inside a dropped label never reaches the text
        if notice and self.notice_size < TEXT_CAP_CHARS:
            self.notice_parts.append(text)
            self.notice_size += len(text)
        if not self.depth["chrome"]:
            if self.body_size < TEXT_CAP_CHARS:
                self.body_parts.append(text)
                self.body_size += len(text)
            if self.depth["main"] and self.main_size < TEXT_CAP_CHARS:
                self.main_parts.append(text)
                self.main_size += len(text)
        if self.size >= TEXT_CAP_CHARS:
            self.page.truncated = True
            return
        self.parts.append(text)
        self.size += len(text)

    def _text(self, data: str) -> None:
        """Text the reader keeps: emit it everywhere it belongs and count it."""
        self._emit(data, notice=not self.depth["nav"] and not self.depth["link"])
        count = nonspace(data)
        if not self.depth["chrome"]:
            self.body_count += count
            if not self.depth["form"]:
                self.free_count += count
            if self.depth["main"]:
                self.main_count += count
                if not self.depth["form"]:
                    self.main_free_count += count

    def _label_scope(self) -> dict | None:
        """The innermost open author scope, when it is still a label. Text inside it is held back: dropped when
        the element closes as a label, except a keep-marked or value-only piece, and replayed when the
        element turns out to hold content."""
        scope = self.author_scopes[-1] if self.author_scopes else None
        return scope if scope is not None and scope["mode"] == "label" else None

    def _overflow_author(self) -> None:
        """The open label holds more than a name: the text is content and stays, so a wrapper the page marked
        with an author token cannot swallow a post body. Outer labels that contain it overflow too; text
        recorded inside a deeper label or a member/profile link stays dropped (that deeper element is a
        name cell)."""
        for scope in [s for s in self.author_scopes if s["mode"] == "label"]:
            scope["mode"] = "content"
            for text, delta, _keep in scope["buffer"]:
                if delta == 0:
                    self._text(text)
            scope["buffer"] = []

    def _pop_author_scope(self) -> None:
        """Close one author-labelled element. Every piece of text it holds goes — its own and any child's,
        so a name sitting in an '<a>', '<strong>', '<b>' or '<span class="name">' drops with the label's own
        name — except text inside a time element or an element with a keep_in_author_idents token, and a
        piece that on its own is only a date, a time, a relative time, a number with an optional unit or a
        rating; those replay, so a name cell cannot take the post's facts with it. One '[author]'
        placeholder stands for the label (and for an enclosing label's name too, so one name cell yields
        exactly one placeholder, which survives even when the enclosing element overflows into content)."""
        scope = self.author_scopes.pop()
        if scope["mode"] != "label":
            return  # the element held content: its text was flushed when it overflowed
        for text, _delta, keep in scope["buffer"]:
            if keep or _keeps_value(text):
                self._text(text)
        if scope["emitted"]:
            return
        outer = next((s for s in reversed(self.author_scopes) if s["mode"] == "label"), None)
        if outer is not None:
            outer["emitted"] = True  # this placeholder stands for the enclosing label's name as well
        self._emit(AUTHOR_PLACEHOLDER, notice=not self.depth["nav"] and not self.depth["link"])

    def _record_tokens(self, tokens: list[str], src: str, tag: str) -> None:
        """Where widgets sit: inside a form (a comment or sign-in form) or on the page itself."""
        page = self.page
        inside = self.depth["form"] > 0
        idents = page.form_idents if inside else page.open_idents
        for token in tokens:
            if len(idents) < TOKEN_CAP:
                idents.add(token)
        if src and tag in FRAME_TAGS:
            frames = page.form_srcs if inside else page.open_srcs
            if len(frames) < 300:
                frames.append(src)

    def handle_starttag(self, tag: str, attrs_list: list) -> None:
        tag = tag.lower()
        attrs = {k.lower(): (v or "") for k, v in attrs_list}
        page = self.page
        if "-" in tag and len(page.tags) < 200:
            page.tags.add(tag)
        ident = attrs.get("id", "").strip().lower()
        classes = attrs.get("class", "").lower().split()
        if ident and len(page.ids) < 2000:
            page.ids.add(ident)
        for token in classes[:20]:
            if len(page.classes) < 5000:
                page.classes.add(token)
        for name in attrs:
            if (name.startswith("ng-") or name.startswith("data-react") or name in ("data-v-app", "data-server-rendered")) \
                    and len(page.attrs) < 200:
                page.attrs.add(name)
        src = attrs.get("src", "")[:300].lower()
        if src and tag in ("script", "iframe", "img", "embed") and len(page.srcs) < 300:
            page.srcs.append(src)
            if tag == "script" and len(page.script_srcs) < 300:
                page.script_srcs.append(src)
        href = attrs.get("href", "").strip()
        self._record_tokens(([ident] if ident else []) + classes[:20], src, tag)
        if tag == "html" and attrs.get("lang"):
            page.lang = attrs["lang"].strip()
        elif tag == "meta":
            self._meta(attrs)
        elif tag == "link":
            self._link(attrs)
        elif tag == "input":
            kind = attrs.get("type", "").lower()
            if kind == "password":
                page.password_inputs += 1
                if not self.depth["nav"]:
                    page.open_password_inputs += 1
            name = (attrs.get("name") or attrs.get("id") or "").lower()
            if name and len(page.input_names) < 300:
                page.input_names.append(name[:100])
        elif tag == "a" and href and len(page.hrefs) < 3000:
            page.hrefs.append(attrs["href"][:300].lower())
        if tag == "br":
            self._emit("\n")
        if tag in VOID_TAGS:
            return
        if tag == "body" and self.open.get("head"):
            self.handle_endtag("head")  # an unterminated head ends where the body starts
        if len(self.stack) >= MAX_DEPTH:
            if tag in BLOCK_TAGS:
                self._emit("\n")
            return
        role = attrs.get("role", "").lower()
        nav = tag in NAV_TAGS or role in NAV_ROLES or (ident in self.chrome_tokens) \
            or any(c in self.chrome_tokens for c in classes)
        tokens = _ident_tokens(ident, classes, attrs)
        # A link to a member or profile page inside an author label or wrapper is the person's name even
        # when no token marks it: privacy.profile_href applies the scrubber's profile-URL patterns to the
        # absolute target, so such a link opens a label scope of its own and its text drops.
        member_link = tag == "a" and self.depth["author"] > 0 and href \
            and privacy.profile_href(_join(self.base_url, href) or href)
        flags = {
            "skip": tag in SKIP_TAGS or "hidden" in attrs or bool(_HIDDEN_STYLE.search(attrs.get("style", ""))),
            "nav": nav,
            "chrome": nav or tag in WIDGET_TAGS or role in WIDGET_ROLES or (tag == "form" and self.depth["nav"] > 0),
            "form": tag == "form",
            "link": tag == "a",
            "main": tag in MAIN_TAGS or role == "main",
            "title": tag == "title",
            "noscript": tag == "noscript",
            "jsonld": tag == "script" and attrs.get("type", "").strip().lower() == "application/ld+json",
            "script": tag == "script" and attrs.get("type", "").strip().lower() in ("", "text/javascript",
                                                                                         "application/javascript", "module"),
            "author": "author" in attrs.get("itemprop", "").lower().split()
                      or "author" in attrs.get("rel", "").lower().split()
                      or bool(tokens & self.author_tokens)
                      or member_link,
            "keep": tag == "time" or bool(tokens & self.keep_tokens),
            "item": bool(tokens & self.item_tokens) and not (tokens & ITEM_SIDE_TOKENS),
        }
        if flags["main"]:
            self.main_seen = True
        if flags["jsonld"] and len(self.jsonld) < JSONLD_MAX_BLOCKS:
            self.jsonld.append("")
            self.jsonld_index = len(self.jsonld) - 1
        for key, on in flags.items():
            if on:
                self.depth[key] += 1
        if flags["author"]:
            self.author_scopes.append({"level": self.depth["author"], "mode": "label", "buffer": [],
                                       "size": 0, "emitted": False})
        if flags["item"] and self.depth["item"] == 1 and not self.depth["author"] and not flags["chrome"]:
            self._emit(ITEM_SEPARATOR + "\n", notice=False)  # one person's item starts here
        self.stack.append((tag, flags))
        self.open[tag] = self.open.get(tag, 0) + 1
        if tag in BLOCK_TAGS:
            self._emit("\n")
        elif tag in CELL_TAGS:
            self._emit(" ")

    def handle_startendtag(self, tag: str, attrs: list) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if not self.open.get(tag):
            return
        while self.stack:
            name, flags = self.stack.pop()
            self.open[name] -= 1
            for key, on in flags.items():
                if on:
                    self.depth[key] -= 1
            if flags["jsonld"]:
                self.jsonld_index = None
            if flags["author"]:
                self._pop_author_scope()
            if name in BLOCK_TAGS:
                self._emit("\n")
            if name == tag:
                break

    def handle_data(self, data: str) -> None:
        depth = self.depth
        if depth["title"] and not self.page.title:
            self.page.title = " ".join(data.split())[:500]
        if depth["jsonld"]:
            if self.jsonld_index is not None and self.jsonld_bytes + len(data) <= JSONLD_MAX_BYTES:
                self.jsonld[self.jsonld_index] += data
                self.jsonld_bytes += len(data)
            return
        if depth["script"]:
            if self.script_bytes < 256 * 1024:
                self.script_text.append(data[:65536])
                self.script_bytes += min(len(data), 65536)
            return
        if depth["noscript"]:
            if sum(len(x) for x in self.noscript) < 4000:
                self.noscript.append(data)
            return
        if depth["skip"]:
            return
        scope = self._label_scope()
        if scope is not None:
            # (the text, its author depth above the scope, whether it sits inside a time element or an
            # element a keep_in_author_idents token marks) — kept pieces replay when the label closes.
            scope["buffer"].append((data, self.depth["author"] - scope["level"], self.depth["keep"] > 0))
            scope["size"] += nonspace(data)
            if scope["size"] > AUTHOR_LABEL_CHARS:
                self._overflow_author()
            return
        self._text(data)

    def _meta(self, attrs: dict) -> None:
        page = self.page
        name = (attrs.get("name") or attrs.get("property") or "").strip().lower()
        content = attrs.get("content", "")
        equiv = attrs.get("http-equiv", "").strip().lower()
        if name == "description" and not page.description:
            page.description = " ".join(content.split())[:1000]
        elif name.startswith("og:") and len(page.og) < 20:
            page.og[name[3:]] = " ".join(content.split())[:1000]
        elif name in ("robots", ROBOTS_TOKEN.lower()):
            page.meta_robots.append((name, content[:300]))
        elif name == "tdm-reservation":
            page.tdm_meta = content.strip()[:20]
        if equiv == "refresh" and page.meta_refresh is None:
            page.meta_refresh = content[:300]
            found = _REFRESH.match(page.meta_refresh)
            if found:
                page.refresh_delay = int(found.group(1))
                if found.group(2):
                    page.refresh_url = _join(self.base_url, found.group(2))

    def _link(self, attrs: dict) -> None:
        rel = set(attrs.get("rel", "").lower().split())
        href = attrs.get("href", "").strip()
        if not href:
            return
        absolute = _join(self.base_url, href)
        if absolute is None:
            return  # a malformed link is skipped; the rest of the page is still parsed
        if "canonical" in rel and self.page.canonical is None:
            self.page.canonical = absolute
        kind = None
        if "amphtml" in rel:
            kind = "amp"
        elif "alternate" in rel and not attrs.get("hreflang"):
            media = attrs.get("media", "").lower()
            if attrs.get("type", "").strip().lower() in FEED_TYPES:
                kind = "feed"
            elif "handheld" in media or "max-width" in media or "max-device-width" in media:
                kind = "mobile"
        if kind and len(self.page.alternates) < 20:
            self.page.alternates.append({"kind": kind, "href": absolute, "type": attrs.get("type", "")[:60]})


def _walk(value, depth: int = 0, budget: list | None = None):
    budget = budget if budget is not None else [4000]
    if depth > 8 or budget[0] <= 0:
        return
    budget[0] -= 1
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _walk(item, depth + 1, budget)
    elif isinstance(value, list):
        for item in value[:500]:
            yield from _walk(item, depth + 1, budget)


def _review_item(node: dict) -> str:
    """One Review node as text. The reviewer (author.name) never enters: an '[author]' placeholder keeps
    the item boundary; the date, the rating and the body stay."""
    parts = [AUTHOR_PLACEHOLDER]
    date = node.get("datePublished")
    if isinstance(date, str) and date.strip():
        parts.append(" ".join(date.split())[:40])
    rating = node.get("reviewRating")
    if isinstance(rating, dict):
        value, best = rating.get("ratingValue"), rating.get("bestRating")
        if isinstance(value, (int, float, str)) and str(value).strip():
            tail = f"/{best}" if isinstance(best, (int, float, str)) and str(best).strip() else ""
            parts.append(f"rating {str(value)[:20]}{tail[:12]}")
    body = node.get("reviewBody")
    if isinstance(body, str) and body.strip():
        parts.append(html_to_text(body) if "<" in body else body.strip())
    return "\n".join(parts)


def _apply_jsonld(page: Page, blocks: list) -> str:
    bodies: list[str] = []
    for raw in blocks[:JSONLD_MAX_BLOCKS]:
        if isinstance(raw, str):
            try:
                data = json.loads(raw, strict=False)
            except (ValueError, RecursionError):
                continue
        else:
            data = raw
        page.jsonld_blocks += 1
        for node in _walk(data):
            free = node.get("isAccessibleForFree")
            if free is False or (isinstance(free, str) and free.strip().lower() == "false"):
                page.jsonld_free = False
            elif page.jsonld_free is None and (free is True or (isinstance(free, str) and free.strip().lower() == "true")):
                page.jsonld_free = True
            types = node.get("@type")
            types = types if isinstance(types, list) else [types]
            if any(isinstance(t, str) and t.strip().lower() == "review" for t in types):
                bodies.append(_review_item(node))  # a review item, its author's name dropped
            else:
                for key in ("articleBody", "reviewBody"):
                    body = node.get(key)
                    if isinstance(body, str) and body.strip():
                        bodies.append(html_to_text(body) if "<" in body else body.strip())
            rating = node.get("aggregateRating")
            if isinstance(rating, dict) and page.jsonld_rating is None:
                page.jsonld_rating = {k: rating[k] for k in ("ratingValue", "ratingCount", "reviewCount", "bestRating")
                                      if isinstance(rating.get(k), (int, float, str))}
            authors = node.get("author")
            for author in authors if isinstance(authors, list) else [authors]:
                if isinstance(author, dict) and isinstance(author.get("@type"), str) and len(page.jsonld_author_types) < 20:
                    page.jsonld_author_types.append(author["@type"][:40])
    body = "\n\n".join(dict.fromkeys(b for b in bodies if b))
    page.jsonld_body_chars = nonspace(body)
    return body[:TEXT_CAP_CHARS]


def _finish(page: Page, visible: str, body: str, kept: str | None = None) -> Page:
    """`visible_text` stays what a visitor sees (access checks use it); `text` is the reader's text: the
    JSON-LD body when it is longer, else the visible text without page chrome (`kept`, which only HTML
    parsing can supply; a render capture's inner text carries no structure)."""
    visible = nfc(visible)
    page.visible_text = visible
    page.visible_chars = nonspace(visible)
    if body and nonspace(body) > page.visible_chars:
        page.text, page.extraction_source = nfc(tidy(body)), "json_ld"
        page.main_text = page.text
    else:
        page.text = visible if kept is None else nfc(tidy(kept))
    if not page.main_text:
        page.main_text = page.text
    return page


def from_html(html: str, base_url: str, markers: dict | None = None) -> Page:
    chrome, author, item, keep = _marker_tokens(markers)
    drop, platform_author = _platform_tokens(base_url)
    parser = _Parser(base_url, chrome | drop, author | platform_author, item, keep)
    try:
        parser.feed(html[:PARSE_CAP_CHARS])
        parser.close()
    except (AssertionError, ValueError, RecursionError):
        pass  # malformed markup: keep what was parsed
    page = parser.page
    page.truncated = page.truncated or len(html) > PARSE_CAP_CHARS
    page.noscript_text = tidy(" ".join(parser.noscript))[:2000]
    script = "".join(parser.script_text)
    page.alerts = [m.group(2)[:300] for m in _ALERT.finditer(script)][:20]
    page.main_chars = parser.main_count if parser.main_seen else parser.body_count
    page.main_container = parser.main_seen
    page.free_chars = parser.main_free_count if parser.main_seen else parser.free_count
    page.main_free_chars = parser.main_free_count
    page.notice_text = nfc(tidy("".join(parser.notice_parts)))
    page.main_text = nfc(tidy("".join(parser.main_parts if parser.main_seen else parser.body_parts)))
    body = _apply_jsonld(page, parser.jsonld)
    return _finish(page, tidy("".join(parser.parts)), body, "".join(parser.body_parts))


def html_to_text(fragment: str) -> str:
    _, author, item, keep = _marker_tokens(None)
    parser = _Parser("", frozenset(), author, item, keep)  # links are ignored here; author labels are not
    try:
        parser.feed(fragment[:PARSE_CAP_CHARS])
        parser.close()
    except (AssertionError, ValueError):
        pass
    return tidy("".join(parser.parts))


def from_text(text: str) -> Page:
    page = Page(kind="text", extraction_source="text")
    body = nfc(tidy(text[:TEXT_CAP_CHARS]))
    page.truncated = len(text) > TEXT_CAP_CHARS
    page.text = page.visible_text = page.notice_text = page.main_text = body
    page.visible_chars = page.main_chars = page.free_chars = nonspace(body)
    return page


def from_page_read(doc: dict) -> Page:
    """A ux-page-read.v1 render capture (see schemas/ux-page-read.v1.schema.json)."""
    page = Page(kind="page_read", extraction_source="page_read")
    text = str(doc.get("text") or "")
    page.truncated = len(text) > TEXT_CAP_CHARS
    page.title = " ".join(str(doc.get("title") or "").split())[:500]
    page.lang = str(doc.get("lang") or "")[:20]
    meta = doc.get("meta") if isinstance(doc.get("meta"), dict) else {}
    page.description = " ".join(str(meta.get("description") or "").split())[:1000]
    if isinstance(meta.get("og"), dict):
        page.og = {str(k)[:40]: str(v)[:1000] for k, v in list(meta["og"].items())[:20]}
    if meta.get("robots"):
        page.meta_robots.append(("robots", str(meta["robots"])[:300]))
    if meta.get("tdm_reservation") is not None:
        page.tdm_meta = str(meta["tdm_reservation"])[:20]
    challenge = doc.get("challenge") if isinstance(doc.get("challenge"), dict) else {}
    page.challenge_interactive = bool(challenge.get("interactive"))
    page.challenge_markers = [str(m)[:100] for m in (challenge.get("markers") or [])[:20]]
    # A render capture says only that a password field was on the page, not where; the login-wall
    # rule then needs almost no text around it (verdict.py).
    page.password_inputs = 1 if doc.get("login_form") else 0
    blocks = doc.get("json_ld") if isinstance(doc.get("json_ld"), list) else []
    body = _apply_jsonld(page, blocks)
    visible = tidy(text[:TEXT_CAP_CHARS])
    result = _finish(page, visible, body)
    result.main_chars = result.free_chars = result.visible_chars
    result.notice_text = result.visible_text
    return result  # main_text: the render's text, or the JSON-LD body when that was used (_finish)


def _same_link(a: str, b: str) -> bool:
    def key(url: str) -> tuple:
        parts = urlsplit(url.strip())
        host = (parts.hostname or "").lower()
        for prefix in ("www.", "m."):
            if host.startswith(prefix):
                host = host[len(prefix):]
        return host, (parts.path or "/").rstrip("/") or "/", parts.query
    try:
        return key(a) == key(b)
    except ValueError:
        return False  # a malformed link in a feed matches nothing


def _declares_dtd(xml_text: str) -> bool:
    """True when anything before the root element declares a DTD (or is not a comment or a
    processing instruction), however long the prolog is."""
    i = 0
    while True:
        j = xml_text.find("<", i)
        if j == -1:
            return False
        if xml_text.startswith("<!--", j):
            end = xml_text.find("-->", j + 4)
            if end == -1:
                return True
            i = end + 3
        elif xml_text.startswith("<?", j):
            end = xml_text.find("?>", j + 2)
            if end == -1:
                return True
            i = end + 2
        else:
            return xml_text.startswith("<!", j)  # <!DOCTYPE (and any entity it declares) before the root


def _local(tag) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _child_text(node, *names: str) -> str:
    """First non-empty child text by local name, so any namespace prefix works."""
    for name in names:
        for child in node:
            if _local(child.tag) == name and (child.text or "").strip():
                return child.text.strip()
    return ""


def from_feed(xml_text: str, target_url: str, scope: str = "item") -> Page | None:
    """RSS (0.9x, 1.0, 2.0) or Atom. scope 'item' keeps only the entry linking to target_url;
    'all' keeps every entry (a thread or review feed)."""
    if _declares_dtd(xml_text):
        return None  # no DTDs: entity expansion is never allowed
    try:
        # The text is already decoded (net.decode_body), so it is parsed as a str: expat then ignores
        # the declared encoding, which would otherwise break EUC-KR/CP949 feeds and garble Latin-1 ones.
        root = ET.fromstring(xml_text)
    except (ET.ParseError, ValueError):
        return None
    entries = []
    for item in (el for el in root.iter() if _local(el.tag) in ("item", "entry")):
        link = _child_text(item, "link")
        if not link:
            for child in item:
                if _local(child.tag) == "link" and child.get("href") and child.get("rel", "alternate") == "alternate":
                    link = child.get("href")
                    break
        title = _child_text(item, "title")
        body = _child_text(item, "encoded", "description", "content", "summary")
        entries.append((link, title, html_to_text(body) if "<" in body else body))
        if len(entries) >= FEED_MAX_ITEMS:
            break
    if scope == "item":
        entries = [e for e in entries if e[0] and _same_link(e[0], target_url)][:1]
    if not entries:
        return None
    text = "\n\n".join(f"{title}\n{body}".strip() for _, title, body in entries)
    page = from_text(text)
    page.kind, page.extraction_source = "feed", "feed"
    channel = next((el for el in root if _local(el.tag) == "channel"), root)
    page.title = _child_text(channel, "title")[:500]
    return page


def from_oembed(json_text: str) -> Page | None:
    try:
        data = json.loads(json_text)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    title = str(data.get("title") or "")
    body = html_to_text(str(data.get("html") or ""))
    text = "\n".join(x for x in (title, body) if x)
    if not text.strip():
        return None
    page = from_text(text)
    page.kind, page.extraction_source = "oembed", "oembed"
    page.title = title[:500]
    return page
