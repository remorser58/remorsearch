"""One verdict or stop class per response. HTTP 200 is never success on its own.

Precedence (the first match wins):
  opted_out    robots.txt, TDM reservation, noai, the researcher's deny list
  gone         404/410, or a deleted-post notice on a thin page
  auth_gate    401/407; a redirect (or a meta refresh) to a login page; a login
               form on a page that is almost empty, or outside the page's
               navigation chrome on a thin page; a membership, age or identity
               notice on a thin page; for captures, signs of a signed-in view
               (except in a community the brief authorises)
  paywall      JSON-LD isAccessibleForFree=false, or a paywall notice on a thin page
  human_check  an interactive challenge widget on a thin or challenge-status page,
               or a challenge notice (word_only when nothing backs it): every human
               check stops the whole site. A captcha inside a comment or sign-in form
               of a readable post is not a stop.
  rate_limit   429 or 503 with Retry-After, or a rate-limit notice on a thin page
               (word_only): a site signal, one wait, then the site stops
  geo_block    a geo notice on a thin page
  legal_block  451, a redirect to a legal-block host, or a legal notice on a thin page
  js_check     a browser-check interstitial ("checking your browser"), even one that
               would clear by itself: opted_out, reasons prefixed 'js_check:', and the
               whole site stops (it is never waited out or rendered past)
  bot_filter   403/405/406 or other 4xx without other markers, or a block notice: the
               site refused our honest request, so opted_out, reasons prefixed
               'bot_filter:', and the whole site stops (never escalated)
  js_shell     almost no visible text plus an SPA root or a noscript notice (escalates)
  suspect      no usable text, or a redirect to the site root (escalates)
  ok_weak      readable text, including a short post inside a main or article element
  ok_strong    readable text plus an --expect term, a JSON-LD body or an official feed

Word markers count only when the main content is thin, and only as notices: in
the page's own text outside navigation chrome and links, in a JS alert or
noscript text, or in the title of a page with no text of its own. A marker that
a person quotes, asks about or reports in their own words ('보안문자가 너무
어려워요', 'I keep getting access denied') is part of a post, not a notice, and
so is a marker in a short line, such as a post title, above lines in a person's
own words; the page is read and the marker is kept as a `mention:` reason. A
sentence that is little more than the marker ('삭제된 게시글이에요') and holds
most of the text is a notice whatever its ending. On a page served with a
non-2xx status every marker counts. Structural markers are checked before words.

Three stop classes are decided before any request, never from a response:
terms_restricted (the host's terms restrict automated collection, see
scope.py), budget and host_stopped.

Content flags (promotion_scan, incentive_flags, virtual_person_flags) mark
candidate disclosures in page text: complete disclosure or label forms from
data/markers.json, never bare words, each with the position it was found in
(lead: the title and the first thresholds.promotion_lead_chars characters;
tail: the last thresholds.promotion_tail_chars characters; body: elsewhere). A
match is dropped when a negation follows it, when it is quoted, or when its
sentence is a question. Width and dash variants are folded first (fold: NFKC
per character, and dashes such as the en dash or 'ㅡ' become '-'), so a
full-width '＃광고' counts. When the text comes in blocks (an official API's
video: its title, its description and each comment), each block is scanned on
its own, so lead and tail are the block's own, and each flag names its block; a
viewer's comment is that comment's text, never the video's disclosure. The scan
is linear: sentence ends are found once per text, the look-around is bounded
and the matches examined per marker family are capped. A verifier confirms
every flag before a grade cap applies; an incentive flag is a per-review
candidate, never a page-wide cap.
"""
from __future__ import annotations

import bisect
import functools
import json
import re
import unicodedata
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit

DATA = Path(__file__).resolve().parent / "data"
VERDICTS = ("ok_strong", "ok_weak", "suspect", "js_shell", "js_check", "bot_filter")
STOP_CLASSES = ("auth_gate", "paywall", "human_check", "opted_out", "terms_restricted", "rate_limit", "geo_block",
                "legal_block", "gone", "budget", "host_stopped")
PRE_REQUEST_STOPS = frozenset({"terms_restricted", "budget", "host_stopped"})
INCENTIVE_KINDS = ("seller_event", "seller_notice", "platform_points", "reward_unspecified")
POSITIONS = ("lead", "body", "tail")
ESCALATE = frozenset({"js_shell", "suspect"})  # the only verdicts that climb to the next rung
CHECK_VERDICTS = frozenset({"js_check", "bot_filter"})  # a refusal or a browser check: a site-wide opted_out stop
OK = frozenset({"ok_strong", "ok_weak"})
HOST_STOPPING = frozenset({"human_check", "opted_out"})  # with host_wide: the whole site stops for the run
PRESENTATIONS = ("official_route", "honest_ua", "site_alternate", "real_browser")
BUCKETS = ("read", "deferred", "unread", "stopped")
WORD_FAMILIES = ("deleted", "membership", "age_identity", "paywall", "human_check", "rate_limit", "geo", "legal",
                 "bot_filter", "js_check")
META_REFRESH_MAX_S = 10  # a meta refresh this quick sends the visitor on before they can read the page


@dataclass
class Verdict:
    verdict: str | None = None
    stop_class: str | None = None
    reasons: list = field(default_factory=list)
    transient: bool = False
    # Every human check, bot filter and browser check stops the whole site; every rate-limit status or
    # notice is a site-level rate-limit signal (one wait, then the site stops).
    host_wide: bool = False

    @property
    def ok(self) -> bool:
        return self.verdict in OK

    @property
    def escalate(self) -> bool:
        return self.verdict in ESCALATE


@functools.lru_cache(maxsize=4)
def _load(name: str) -> dict:
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def load_markers() -> dict:
    return _load("markers.json")


def _word_pattern(marker: str) -> str:
    if marker.isascii():
        body = r"\s+".join(re.escape(part) for part in marker.split())
        start = r"(?<![a-z0-9])" if marker[:1].isalnum() else ""
        end = r"(?![a-z0-9])" if marker[-1:].isalnum() else ""
        return start + body + end
    return r"\s*".join(re.escape(part) for part in marker.split())


def _alternation(markers) -> re.Pattern | None:
    items = sorted({m for m in markers if m}, key=len, reverse=True)
    if not items:
        return None
    return re.compile("|".join(_word_pattern(m) for m in items), re.I)


def _langs(section: dict | None) -> list:
    """Every marker of a {language: [markers]} section; other values (such as a note) are skipped."""
    if not isinstance(section, dict):
        return []
    return [m for values in section.values() if isinstance(values, list) for m in values if isinstance(m, str)]


def _regexes(values) -> list:
    return [re.compile(p, re.I) for p in values or () if isinstance(p, str)]


class _Compiled:
    def __init__(self, markers: dict):
        self.raw = markers
        self.thresholds = markers["thresholds"]
        self.words = {}
        for key in ("login", "membership", "age_identity", "paywall", "deleted", "rate_limit", "geo", "legal",
                    "bot_filter", "human_check", "js_check"):
            self.words[key] = _alternation(_langs(markers[key].get("words")))
        self.noscript = _alternation(_langs(markers["spa_root"]["noscript_words"]))
        self.any_word = _alternation([m for key in WORD_FAMILIES for m in _langs(markers[key].get("words"))])
        self.promotion = _alternation(_langs(markers["promotion"]))
        self.promotion_patterns = _regexes(_langs(markers.get("promotion_patterns")))
        self.promotion_placed = _alternation(_langs(markers.get("promotion_placed")))
        self.promotion_labels = _alternation(_langs(markers.get("promotion_labels")))
        incentive = markers.get("incentive") or {}
        self.incentive = {kind: _alternation(_langs(incentive.get(kind))) for kind in INCENTIVE_KINDS}
        self.virtual_person = _alternation(_langs(markers.get("virtual_person")))
        guards = markers.get("guards") or {}
        self.negation_after = _regexes(guards.get("negation_after"))
        self.negation_clause = _regexes(guards.get("negation_clause"))
        self.question_endings = tuple(_langs(guards.get("question_endings")))
        handles = markers.get("anonymous_handles") or {}
        self.anonymous_handles = frozenset(handle_form(h) for h in _langs(
            {k: v for k, v in handles.items() if k != "patterns"}))
        # NFKC maps compatibility jamo (ㅇ) to conjoining jamo, so the patterns get the same form as the handles.
        self.anonymous_patterns = _regexes(unicodedata.normalize("NFKC", p) for p in handles.get("patterns") or [])
        self.human_src = _alternation(markers["human_check"]["src"])
        self.human_ident = _alternation(markers["human_check"]["idents"])
        self.human_input = _alternation(markers["human_check"]["inputs"])
        self.js_src = _alternation(markers["js_check"]["src"])
        self.js_ident = _alternation(markers["js_check"]["idents"])
        self.logout_href = _alternation(markers["logged_in"]["href"])
        self.logged_in_lines = {" ".join(x.lower().split()) for x in _langs(markers["logged_in"]["lines"])}
        self.greetings = tuple(" ".join(x.lower().split()) for x in _langs(markers["logged_in"].get("greetings")))
        self.login_paths = [re.compile(p, re.I) for p in markers["login"]["url_path"]]
        self.legal_hosts = frozenset(markers["legal"].get("hosts", []))
        self.spa_ids = frozenset(markers["spa_root"]["ids"])
        self.spa_attrs = frozenset(markers["spa_root"]["attrs"])
        self.spa_tags = frozenset(markers["spa_root"]["tags"])
        self.injection = {
            name: [re.compile(p, re.I | re.S) for p in _langs(section)]
            for name, section in markers["injection"].items()
        }


@functools.lru_cache(maxsize=1)
def compiled() -> _Compiled:
    return _Compiled(load_markers())


_SENTENCE_END = ".!?\n。…"
_QUOTE_PAIRS = (('"', '"'), ("'", "'"), ("“", "”"), ("‘", "’"), ("「", "」"),
                ("『", "』"))
_HANGUL = re.compile("[가-힣]")
# punctuation, emoticons and chat jamo after the last word of a sentence
_TRAILING_CHARS = frozenset("~^.!?,;:)]}\"'*-…。”’」』♡♥♪☆★" + "".join(chr(c) for c in range(0x3131, 0x3164)))
_CHAT_JAMO = re.compile("[ㅋㅎㅠㅜ]{2,}")  # ㅋㅋ ㅎㅎ ㅠㅠ ㅜㅜ
_KO_FIRST_PERSON = re.compile("(?<![가-힣])(저는|제가|저만|저도|저한테|나는|내가|나만|나도)(?![가-힣])")
_EN_FIRST_PERSON = re.compile(r"(?<![a-z'])(i|i'm|i've|i'd|i'll|me|my|mine|myself)(?![a-z'])", re.I)
_WORD_CHAR = re.compile(r"\w")
BARE_OTHER_CHARS = 5  # at most this many letters besides the marker: the sentence is the notice itself
VOICED_LINE_CHARS = 8  # a line needs this many letters to count as a person's own words


def _sentence_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    left = max(text.rfind(ch, 0, start) for ch in _SENTENCE_END) + 1
    rights = [i for i in (text.find(ch, end) for ch in _SENTENCE_END) if i != -1]
    return left, (min(rights) if rights else len(text))


def _first_person(sentence: str) -> bool:
    return bool(_EN_FIRST_PERSON.search(sentence) or _KO_FIRST_PERSON.search(sentence) or _CHAT_JAMO.search(sentence))


def _conversational(sentence: str, terminator: str) -> bool:
    """A sentence in a person's own voice: first person, chat jamo, a question, or (in Korean) a
    해요체 or plain -다 ending. Site notices use the formal -니다, -니까?, -세요 and -십시오
    forms or a bare noun phrase; English notices are boilerplate, so only first person counts there."""
    if _first_person(sentence):
        return True
    if not _HANGUL.search(sentence):
        return False
    core = _strip_trailing(sentence)
    if not core:
        return False
    if terminator == "?":
        return not core.endswith("니까")  # '로그인 하시겠습니까?' is the site asking
    if core.endswith("요"):
        return not core.endswith("세요")  # '입력해 주세요' is an instruction
    return core.endswith("다") and not core.endswith("니다")


def _line_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    line_end = text.find("\n", end)
    return text.rfind("\n", 0, start) + 1, len(text) if line_end == -1 else line_end


def _holds_most(text: str, line_start: int, line_end: int) -> bool:
    """True when this line holds at least half of the text's non-space characters."""
    return 2 * len("".join(text[line_start:line_end].split())) >= len("".join(text.split()))


def _sentences(text: str, start: int, end: int):
    """(start, stop, terminator) of each sentence between start and end."""
    cursor = start
    while cursor < end:
        stops = [i for i in (text.find(ch, cursor, end) for ch in _SENTENCE_END) if i != -1]
        stop = min(stops) if stops else end
        yield cursor, stop, text[stop] if stop < end else ""
        cursor = stop + 1


def _bare(blanked: str, terminator: str) -> bool:
    """Little more than the marker itself ('삭제된 게시글이에요', '로그인이 필요해요'): friendly
    services write notices in the 해요체 too. A Korean question is still someone asking."""
    if len(_WORD_CHAR.findall(blanked)) > BARE_OTHER_CHARS:
        return False
    return not (terminator == "?" and _HANGUL.search(blanked) and not _strip_trailing(blanked).endswith("니까"))


@functools.lru_cache(maxsize=16)
def _voiced_lines(text: str) -> frozenset:
    """Start offsets of the lines that hold no marker at all and read as a person's own words: the
    body of a post, as opposed to the rest of a site's notice."""
    words = compiled().any_word
    found = set()
    offset = 0
    for line in text.split("\n"):
        if len(_WORD_CHAR.findall(line)) >= VOICED_LINE_CHARS and not (words and words.search(line)):
            if any(_conversational(line[a:b], term) for a, b, term in _sentences(line, 0, len(line))):
                found.add(offset)
        offset += len(line) + 1
    return frozenset(found)


def _reported(text: str, start: int, end: int) -> bool:
    """True when a marker is part of a person's post, not a site notice: it is quoted or asked
    about ('...'라고 떠요, ...나요?), its line reads as someone's own report ('해외에서 접속하면
    결제가 안 돼요', 'I keep getting access denied'), or it sits in a short line such as a post
    title ('보안문자 질문') above lines in a person's own words."""
    left, right = _sentence_bounds(text, start, end)
    before, after = text[left:start], text[end:right]
    for opening, closing in _QUOTE_PAIRS:
        if opening == closing:
            if before.count(opening) % 2 == 1 and opening in after:
                return True
        elif before.rfind(opening) > before.rfind(closing) and closing in after:
            return True
    terminator = text[right] if right < len(text) else ""
    blanked = before + " " * (end - start) + after  # the marker itself is blanked
    line_start, line_end = _line_bounds(text, start, end)
    most = _holds_most(text, line_start, line_end)
    if most and not _first_person(blanked) and _bare(blanked, terminator):
        return False  # the notice itself, whatever its ending
    if _conversational(blanked, terminator):
        return True
    for first, stop, mark in _sentences(text, line_start, line_end):
        if not left <= first < right and _conversational(text[first:stop], mark):
            return True  # another sentence of the same line is in a person's voice
    return not most and bool(_voiced_lines(text) - {line_start})


def _hits(pattern: re.Pattern | None, text: str, limit: int = 5, *, notices_only: bool = False) -> list[str]:
    if pattern is None or not text:
        return []
    found: list[str] = []
    for match in pattern.finditer(text):
        if notices_only and _reported(text, match.start(), match.end()):
            continue
        value = " ".join(match.group(0).split())
        if value.lower() not in (f.lower() for f in found):
            found.append(value)
        if len(found) >= limit:
            break
    return found


def _any_hit(pattern: re.Pattern | None, values) -> list[str]:
    if pattern is None:
        return []
    found = []
    for value in values:
        match = pattern.search(value)
        if match:
            found.append(match.group(0))
            if len(found) >= 3:
                break
    return found


def host_matches(host: str, patterns) -> bool:
    host = host.lower().rstrip(".")
    for pattern in patterns:
        pattern = pattern.lower()
        if pattern.startswith("*."):
            if host.endswith(pattern[1:]) and host != pattern[2:]:
                return True
        elif host == pattern or host.endswith("." + pattern):
            return True
    return False


def is_login_url(url: str, login_hosts=()) -> bool:
    parts = urlsplit(url)
    if host_matches(parts.hostname or "", login_hosts):
        return True
    target = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    return any(p.search(target) for p in compiled().login_paths)


def is_legal_block_url(url: str) -> bool:
    return host_matches(urlsplit(url).hostname or "", compiled().legal_hosts)


def _human_widgets(page) -> tuple[list, list, list]:
    """Challenge widgets outside any form, widgets inside a form, and supporting hints (widget
    scripts, captcha inputs). A script alone is never a widget: invisible checks load on ordinary pages."""
    c = compiled()
    outside = [f"ident:{x}" for x in _any_hit(c.human_ident, sorted(page.open_idents))]
    outside += [f"src:{x}" for x in _any_hit(c.human_src, page.open_srcs)]
    if page.challenge_interactive:
        outside.append("capture:challenge.interactive")
    inside = [f"form_ident:{x}" for x in _any_hit(c.human_ident, sorted(page.form_idents))]
    inside += [f"form_src:{x}" for x in _any_hit(c.human_src, page.form_srcs)]
    hints = [f"script:{x}" for x in _any_hit(c.human_src, page.script_srcs)]
    hints += [f"input:{x}" for x in _any_hit(c.human_input, page.input_names)]
    return outside, inside, hints


def _structure_js(page) -> list[str]:
    c = compiled()
    reasons = [f"src:{x}" for x in _any_hit(c.js_src, page.srcs)]
    reasons += [f"ident:{x}" for x in _any_hit(c.js_ident, list(page.ids) + list(page.classes))]
    return reasons


def _spa_root(page) -> list[str]:
    c = compiled()
    found = [f"id:{x}" for x in sorted(page.ids & c.spa_ids)]
    found += [f"attr:{x}" for x in sorted(page.attrs & c.spa_attrs)]
    found += [f"tag:{x}" for x in sorted(page.tags & c.spa_tags)]
    return found


def _logged_in(page) -> list[str]:
    """Signs that only a signed-in visitor sees: a sign-out link or line, or a member greeting.
    Links such as 'My page' or 'My account' are shown to anonymous visitors too, so they do not count."""
    c = compiled()
    reasons = [f"href:{x}" for x in _any_hit(c.logout_href, page.hrefs)]
    limit = c.thresholds["standalone_line_chars"]
    for line in page.visible_text.splitlines():
        value = " ".join(line.lower().split())
        if 0 < len(value) <= limit and value in c.logged_in_lines:
            reasons.append(f"line:{value}")  # a fixed marker line from data/markers.json
            break
        if 0 < len(value) <= limit and value.endswith(c.greetings or ("\0",)):
            reasons.append("line:greeting")  # never the line itself: a greeting names a member
            break
    return reasons


_SENTENCE_ENDS = re.compile("[" + re.escape(_SENTENCE_END) + "]")
FLAG_WINDOW_CHARS = 300  # the look-around of a flag's quote and question checks, each side
FLAG_CANDIDATES_MAX = 400  # matches examined per marker family in one text
_DASHES = frozenset("\u2010\u2011\u2012\u2013\u2014\u2015\u2212\u3161\ufe58\ufe63\uff0d")
# Characters that may fold: not ASCII, not Hangul syllables or compatibility jamo (chat jamo such as 'ㅋㅋ' must
# stay as they are), not kana or CJK ideographs. 'ㅡ' (U+3161), often typed as a dash, is folded.
_FOLDABLE = re.compile("[^\x00-\x7f\uac00-\ud7a3\u3131-\u3160\u3162-\u318f\u3040-\u30ff\u4e00-\u9fff]")


@functools.lru_cache(maxsize=8192)
def _fold_char(char: str) -> str:
    if char in _DASHES:
        return "-"
    folded = unicodedata.normalize("NFKC", char)
    return folded if len(folded) == 1 else char


def fold(text: str) -> str:
    """Width and dash variants folded, one character for one: NFKC per character when it gives a single
    character ('＃' '#', '（' '(', '０' '0', '＠' '@'), and dashes ('–', '—', '―', '−', 'ㅡ') become '-'.
    The text keeps its length, so offsets found in the folded text are offsets in the original."""
    if not text or text.isascii():
        return text
    return _FOLDABLE.sub(lambda m: _fold_char(m.group()), text)


def _strip_trailing(text: str) -> str:
    """The text without the punctuation, emoticons and chat jamo after its last word (linear)."""
    i = len(text)
    while i and (text[i - 1].isspace() or text[i - 1] in _TRAILING_CHARS):
        i -= 1
    return text[:i]


class _FlagText:
    """One text prepared for the content-flag scan: folded, with its sentence ends found once, so each
    match's sentence is found by bisection and its look-around is bounded."""

    def __init__(self, text: str):
        self.text = fold(text or "")
        self.ends = [m.start() for m in _SENTENCE_ENDS.finditer(self.text)]

    def bounds(self, start: int, end: int) -> tuple[int, int]:
        i = bisect.bisect_left(self.ends, start)
        left = self.ends[i - 1] + 1 if i else 0
        j = bisect.bisect_left(self.ends, end)
        right = self.ends[j] if j < len(self.ends) else len(self.text)
        return max(left, start - FLAG_WINDOW_CHARS), min(right, end + FLAG_WINDOW_CHARS)


def _quoted(text, start: int, end: int) -> bool:
    """True when the span sits inside quotation marks within its sentence."""
    flag_text = text if isinstance(text, _FlagText) else _FlagText(text)
    left, right = flag_text.bounds(start, end)
    before, after = flag_text.text[left:start], flag_text.text[end:right]
    for opening, closing in _QUOTE_PAIRS:
        if opening == closing:
            if before.count(opening) % 2 == 1 and opening in after:
                return True
        elif before.rfind(opening) > before.rfind(closing) and closing in after:
            return True
    return False


def _question(text, start: int, end: int) -> bool:
    """True when the span's sentence is a question: it ends with '?' or with a Korean question ending."""
    flag_text = text if isinstance(text, _FlagText) else _FlagText(text)
    left, right = flag_text.bounds(start, end)
    source = flag_text.text
    if right < len(source) and source[right] == "?":
        return True
    core = _strip_trailing(source[left:right])
    endings = compiled().question_endings
    return bool(endings and core and core.endswith(endings) and not core.endswith("니다"))


def _dropped(text, start: int, end: int) -> bool:
    """A marker that is negated right after it, quoted, or asked about is not a disclosure."""
    c = compiled()
    flag_text = text if isinstance(text, _FlagText) else _FlagText(text)
    after = flag_text.text[end:end + 60]
    if any(p.match(after) for p in c.negation_after) or any(p.match(after) for p in c.negation_clause):
        return True
    return _quoted(flag_text, start, end) or _question(flag_text, start, end)


def _position(start: int, end: int, length: int) -> str:
    t = compiled().thresholds
    if start < t.get("promotion_lead_chars", 150):
        return "lead"
    if end > length - t.get("promotion_tail_chars", 200):
        return "tail"
    return "body"


def _scan(patterns, text: str, title: str, *, placed: bool = False, limit: int = 10) -> list[tuple[str, str]]:
    """(marker as found, position) for each kept match, title first. `placed` keeps only the lead and
    the tail, for markers that count only where a disclosure is expected. Linear in the text: each
    match's sentence comes from a precomputed index, a repeat of a kept marker at the same position is
    skipped before its checks, and at most FLAG_CANDIDATES_MAX matches are examined per text."""
    found: list[tuple[str, str]] = []
    seen: set = set()
    for source, is_title in ((title or "", True), (text or "", False)):
        if not source:
            continue
        flag_text = _FlagText(source)
        folded, length = flag_text.text, len(flag_text.text)
        for pattern in patterns:
            if pattern is None:
                continue
            examined = 0
            for match in pattern.finditer(folded):
                position = "lead" if is_title else _position(match.start(), match.end(), length)
                if placed and position == "body":
                    continue
                value = " ".join(match.group(0).split())
                key = (value.lower(), position)
                if key in seen:
                    continue
                examined += 1
                if examined > FLAG_CANDIDATES_MAX:
                    break
                if _dropped(flag_text, match.start(), match.end()):
                    continue
                seen.add(key)
                found.append((value, position))
                if len(found) >= limit:
                    return found
    return found


def promotion_scan(text: str, title: str = "") -> list[dict]:
    """Candidate promotion disclosures: [{marker, family, position}], family one of promotion
    (clear wordings, anywhere), promotion_placed (clear wordings in the lead or tail) and
    promotion_label (foreign labels the KFTC counts as unclear, in the lead or tail)."""
    c = compiled()
    hits = [{"marker": m, "family": "promotion", "position": p}
            for m, p in _scan([c.promotion, *c.promotion_patterns], text, title)]
    hits += [{"marker": m, "family": "promotion_placed", "position": p}
             for m, p in _scan([c.promotion_placed], text, title, placed=True)]
    hits += [{"marker": m, "family": "promotion_label", "position": p}
             for m, p in _scan([c.promotion_labels], text, title, placed=True)]
    return hits[:12]


def promotion_flags(text: str, title: str = "") -> list[str]:
    """The markers of promotion_scan, in order, without duplicates."""
    flags: list[str] = []
    for hit in promotion_scan(text, title):
        if hit["marker"].lower() not in (f.lower() for f in flags):
            flags.append(hit["marker"])
    return flags[:10]


def incentive_flags(text: str, title: str = "") -> list[dict]:
    """Candidate review incentives: [{marker, kind, position}], kind one of INCENTIVE_KINDS
    (seller_event, seller_notice, platform_points, reward_unspecified). Each is a per-review
    candidate for the verifier, never a page-wide cap."""
    c = compiled()
    flags = []
    for kind in INCENTIVE_KINDS:
        flags += [{"marker": m, "kind": kind, "position": p} for m, p in _scan([c.incentive[kind]], text, title)]
    return flags[:10]


def virtual_person_flags(text: str, title: str = "") -> list[dict]:
    """Candidate AI virtual-person labels or sentences: [{marker, position}]."""
    return [{"marker": m, "position": p} for m, p in _scan([compiled().virtual_person], text, title)][:5]


BLOCK_LIMITS = {"promotion_hits": 30, "incentive_flags": 30, "virtual_person_flags": 10}


def content_flags(text: str, title: str = "", blocks=None) -> dict:
    """Every candidate flag of one page's main text, as read and ingest report them.

    `blocks` (from an official API's page, such as a video: [{"block": id, "text": text, "by_uploader":
    bool}]) replaces `text`: each block is scanned on its own, so lead and tail are measured within it,
    and every flag names its block ('title', 'description' or 'comment:<id>'). A viewer's comment is that
    comment's own text: its flags stay in the lists with their block, but never count as the page's own
    disclosure (promo_flags lists the title's, the description's and the uploader's comments' only)."""
    if blocks is None:
        hits = promotion_scan(text, title)
        flags: list[str] = []
        for hit in hits:
            if hit["marker"].lower() not in (f.lower() for f in flags):
                flags.append(hit["marker"])
        return {"promo_flags": flags[:10], "promotion_hits": hits, "incentive_flags": incentive_flags(text, title),
                "virtual_person_flags": virtual_person_flags(text, title)}
    out: dict = {"promotion_hits": [], "incentive_flags": [], "virtual_person_flags": []}
    parts = ([{"block": "title", "text": title, "is_title": True}] if title else []) + list(blocks)
    for part in parts:
        is_title = bool(part.get("is_title"))
        body, head = ("", part["text"]) if is_title else (part.get("text") or "", "")
        extra = {"block": part["block"]}
        if str(part["block"]).startswith("comment:"):
            extra["by_uploader"] = bool(part.get("by_uploader"))
        out["promotion_hits"] += [{**hit, **extra} for hit in promotion_scan(body, head)]
        out["incentive_flags"] += [{**hit, **extra} for hit in incentive_flags(body, head)]
        out["virtual_person_flags"] += [{**hit, **extra} for hit in virtual_person_flags(body, head)]
    for name, cap in BLOCK_LIMITS.items():
        out[name] = out[name][:cap]
    flags = []
    for hit in out["promotion_hits"]:
        if hit.get("by_uploader") is False:  # a viewer's comment is never the page's own disclosure
            continue
        if hit["marker"].lower() not in (f.lower() for f in flags):
            flags.append(hit["marker"])
    return {"promo_flags": flags[:10], **out}


def handle_form(handle: str) -> str:
    """The form handles are compared in: NFKC, case-folded, single spaces."""
    return " ".join(unicodedata.normalize("NFKC", handle).casefold().split())


def anonymous_handle(handle: str) -> bool:
    """True for a default anonymous nickname (data/markers.json anonymous_handles), which is never
    an identity. A trailing partial-IP group should already be split off (privacy.normalize_handle)."""
    c = compiled()
    value = handle_form(handle)
    return value in c.anonymous_handles or any(p.search(value) for p in c.anonymous_patterns)


def _stop(stop_class: str, reasons: list) -> Verdict:
    return Verdict(stop_class=stop_class, reasons=reasons)


def _check_stop(kind: str, reasons: list) -> Verdict:
    """A bot filter or a browser check: verdict `kind` (bot_filter or js_check), stop class opted_out, every
    reason prefixed with the kind, and the whole site stops for the run (never escalated, never rendered)."""
    return Verdict(kind, stop_class="opted_out", reasons=[f"{kind}:{r}" for r in reasons], host_wide=True)


def classify(*, status: int, headers: dict, page, requested_url: str, final_url: str | None = None,
             redirect_urls=(), expect=(), optouts=(), login_hosts=(), capture: bool = False,
             signed_in: bool = False) -> Verdict:
    """Classify one response (or one render capture when `capture` is true). `signed_in` marks a
    capture from a community the brief authorises, where a signed-in view is expected."""
    c = compiled()
    t = c.thresholds
    final_url = final_url or requested_url
    if optouts:
        return _stop("opted_out", list(optouts))
    main = page.main_chars if page is not None else 0
    thin = main < t["thin_main_chars"]
    empty = main < t["empty_main_chars"]
    thin_note = f"thin_main:{main}"
    plain_status = 200 <= status < 300
    # What a visitor sees; a JSON-LD body never hides or causes a stop. Navigation chrome and link
    # text (menus, related-post lists) are not notices about this page.
    # Width and dash variants are folded before any marker is matched (fold keeps offsets).
    body_notice = fold(page.notice_text[:20000]) if page is not None else ""
    site_messages = fold("\n".join([*page.alerts, page.noscript_text])) if page is not None else ""
    title = fold(page.title) if page is not None else ""

    def words(key: str) -> list[str]:
        if not thin or page is None:
            return []
        found = _hits(c.words[key], body_notice, notices_only=plain_status)
        found += _hits(c.words[key], site_messages)
        if empty:  # the title speaks for the page only when the page has almost no text of its own
            found += _hits(c.words[key], title, notices_only=plain_status)
        unique: list[str] = []
        for value in found:
            if value.lower() not in (u.lower() for u in unique):
                unique.append(value)
        return unique[:5]

    # gone
    if status in (404, 410):
        return _stop("gone", [f"status:{status}"])
    if hit := words("deleted"):
        return _stop("gone", [f"word:{w}" for w in hit] + [thin_note])
    # auth_gate
    if status in (401, 407):
        return _stop("auth_gate", [f"status:{status}"])
    requested_login = is_login_url(requested_url, login_hosts)
    for target in [*redirect_urls, final_url]:
        if target and target != requested_url and not requested_login and is_login_url(target, login_hosts):
            return _stop("auth_gate", ["redirect:login_page"])
    refresh = []
    if page is not None and page.refresh_url and page.refresh_delay is not None \
            and page.refresh_delay <= META_REFRESH_MAX_S:
        refresh = [page.refresh_url]
        if not requested_login and page.refresh_url != requested_url and is_login_url(page.refresh_url, login_hosts):
            return _stop("auth_gate", ["meta_refresh:login_page"])
    # A login wall: a password field and a login word on a page that is almost empty, or a password
    # field outside the navigation chrome on a thin page. A login box in the header of a short post
    # is neither.
    if page is not None and page.login_form and (empty or (thin and page.open_password_inputs)):
        login_words = _hits(c.words["login"], "\n".join([title, fold(page.visible_text[:20000]), site_messages]))
        if login_words:
            return _stop("auth_gate", ["structure:password_field", f"word:{login_words[0]}", thin_note])
    for key in ("membership", "age_identity"):
        if hit := words(key):
            return _stop("auth_gate", [f"word:{w}" for w in hit] + [thin_note])
    if capture and not signed_in and page is not None and (seen := _logged_in(page)):
        return _stop("auth_gate", ["capture:signed_in_view", *seen])
    # paywall
    if page is not None and page.jsonld_free is False:
        return _stop("paywall", ["structure:json_ld_isAccessibleForFree_false"])
    if hit := words("paywall"):
        return _stop("paywall", [f"word:{w}" for w in hit] + [thin_note])
    # human_check
    form_captcha = False
    if page is not None:
        outside, inside, hints = _human_widgets(page)
        challenge_status = status in (403, 429, 503)
        # A captcha only inside a form, on a page with readable text outside that form, is a comment or
        # sign-in form under a post, not a challenge that blocks the page.
        readable_outside = (page.main_container and page.main_free_chars > 0) or \
            page.free_chars >= t["suspect_main_chars"]
        form_captcha = bool(inside) and not outside and readable_outside and not challenge_status
        if (outside or inside) and not form_captcha and (thin or challenge_status):
            return Verdict(stop_class="human_check", reasons=outside + inside + hints + [thin_note], host_wide=True)
        hint = outside or inside or hints or status >= 400 or main < t["suspect_main_chars"]
        if hint and not form_captcha and (hit := words("human_check")):
            backed = bool(outside or inside) or status >= 400
            return Verdict(stop_class="human_check", host_wide=True,
                           reasons=[f"word:{w}" for w in hit] + outside + inside + hints + [thin_note] +
                           ([] if backed else ["word_only"]))
    # rate_limit: a status or a notice is a site signal (one wait, then the site stops)
    if status == 429:
        return Verdict(stop_class="rate_limit", reasons=["status:429"], host_wide=True)
    if status == 503 and headers.get("retry-after"):
        return Verdict(stop_class="rate_limit", reasons=["status:503", "header:retry-after"], host_wide=True)
    if hit := words("rate_limit"):
        return Verdict(stop_class="rate_limit", reasons=[f"word:{w}" for w in hit] + [thin_note, "word_only"],
                       host_wide=True)
    # geo_block
    if hit := words("geo"):
        return _stop("geo_block", [f"word:{w}" for w in hit] + [thin_note])
    # legal_block
    if status == 451:
        return _stop("legal_block", ["status:451"])
    for target in [*redirect_urls, final_url, *refresh]:
        if target and is_legal_block_url(target):
            return _stop("legal_block", ["redirect:legal_block_host"])
    if hit := words("legal"):
        return _stop("legal_block", [f"word:{w}" for w in hit] + [thin_note])
    # js_check: a browser check, even one that clears by itself, is a stop for the whole site
    if page is not None and thin:
        structure = _structure_js(page)
        hit = words("js_check")
        if structure or hit:
            return _check_stop("js_check", structure + [f"word:{w}" for w in hit] + [thin_note])
    if 500 <= status < 600 or status == 408:
        return Verdict(transient=True, reasons=[f"status:{status}"])
    # bot_filter: the site refused our honest request, so the whole site stops
    if status >= 400:
        return _check_stop("bot_filter", [f"status:{status}"] + [f"word:{w}" for w in words("bot_filter")])
    if hit := words("bot_filter"):
        return _check_stop("bot_filter", [f"word:{w}" for w in hit] + [thin_note])
    if page is None:
        return Verdict("suspect", reasons=[f"status:{status}", "no_page"])
    rescued = page.extraction_source in ("json_ld", "feed", "oembed")
    # js_shell (a render capture has already run the page's scripts, so it is never a shell)
    if not rescued and not capture and page.visible_chars < t["shell_visible_chars"]:
        roots = _spa_root(page)
        notices = _hits(c.noscript, page.noscript_text)
        if roots or notices:
            return Verdict("js_shell", reasons=roots + [f"noscript:{w}" for w in notices] +
                           [f"visible:{page.visible_chars}"])
    # suspect
    if not plain_status:
        return Verdict("suspect", reasons=[f"status:{status}"])
    notes = []
    if main < t["suspect_main_chars"] and not rescued:
        # A short post inside a main or article element, or a render capture with some text, is read;
        # a short body with no such container may still be a page that needs scripts.
        if main == 0 or not (capture or page.main_container):
            return Verdict("suspect", reasons=[thin_note])
        notes.append(f"short_main:{main}")
    requested_path = urlsplit(requested_url).path or "/"
    if final_url != requested_url and (urlsplit(final_url).path or "/") == "/" and requested_path != "/":
        return Verdict("suspect", reasons=["redirect:site_root"])
    if form_captcha:
        notes.append("captcha_in_form")
    if thin:  # markers that were part of the post, not notices, stay visible to later steps
        mentioned = []
        for key in WORD_FAMILIES:
            for value in _hits(c.words[key], body_notice, limit=3):
                if value.lower() not in (m.lower() for m in mentioned):
                    mentioned.append(value)
        notes += [f"mention:{w}" for w in mentioned[:5]]
    # ok
    strong = []
    lowered = page.text.lower()
    strong += [f"expect:{term}" for term in expect if term and term.lower() in lowered][:3]
    if page.jsonld_body_chars:
        strong.append("json_ld_body")
    if page.extraction_source in ("feed", "oembed"):
        strong.append(f"official:{page.extraction_source}")
    if strong:
        return Verdict("ok_strong", reasons=strong + notes)
    return Verdict("ok_weak", reasons=[f"main:{main}"] + notes + (["expect_missing"] if expect else []))


def robots_challenge_kind(status: int | None, page) -> str | None:
    """'js_check' or 'bot_filter' when a challenge or block page was served instead of robots.txt (recorded
    as unavailable_bot_filtered: robots.txt then disallows everything and the site stops), else None.
    Called only when the body holds no robots.txt lines (ladder.robots_decision)."""
    if page is None or status is None:
        return None
    c = compiled()
    thin = page.main_chars < c.thresholds["thin_main_chars"]
    outside, inside, hints = _human_widgets(page)
    notice = fold("\n".join([page.title, page.visible_text[:20000]]))
    if thin and (_structure_js(page) or _hits(c.words["js_check"], notice)):
        return "js_check"
    if outside or inside or [h for h in hints if h.startswith("script:")]:
        return "bot_filter"
    if not thin:
        return None
    if any(_hits(c.words[k], notice) for k in ("human_check", "bot_filter")):
        return "bot_filter"
    return "bot_filter" if status in (401, 403, 406) and page.visible_chars > 0 else None


def robots_challenge(status: int | None, page) -> bool:
    """True when a challenge or block page was served instead of robots.txt (robots_challenge_kind)."""
    return robots_challenge_kind(status, page) is not None


def retry_after_seconds(value: str | None, now: float) -> float | None:
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        moment = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    if moment is None:
        return None
    return max(0.0, moment.timestamp() - now)
