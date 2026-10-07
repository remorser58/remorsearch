"""URL masking, PII scrubbing, salted author and thread keys, excerpt limits.

- mask_url removes user:password@ and masks the values of credential-like query
  or fragment parameters (token, key, secret, sig, signature, auth, session,
  code, state, password and their common variants).
- scrub replaces e-mail addresses, Korean phone numbers (with or without spaces
  around the dashes, and area codes in brackets), resident-registration-like
  numbers (also with the last digits masked, such as '900101-1******'),
  card-like digit runs, bank-account-like numbers (dashed groups of 10 to 16
  digits, or a digit run after an account word or a bank's name such as '계좌'
  or '신한'), @handles (including dots and hyphens), profile URLs, full IP
  addresses, masked ones such as '211.36.***.***' or '118.235.*.*', an 'IP'
  label with a partial address ('IP 118.235'), and a partial IP group attached
  to a handle, such as 'ㅇㅇ(118.235)' or 'ㅇㅇ(2001:2d8)' (or after only a space
  or a line break, as table cells render it). A parenthesised decimal in
  running text, such as a rating '별점 (4.5)', '(1.5)배속' or a version '(3.2)',
  is kept: a group counts only when it follows a handle and looks like an
  address, not a small decimal such as 4.8, and not a version glued with no
  space to a word that names an OS, an app or a version ('iOS(17.2)',
  'Android(14.1)', 'v(2.3)', '버전(12.5)'): such a pair stays only when it also
  looks like a version, a first number below 30 and a second of 30 or less.
  Every other pair after a handle goes, so a nickname such as 'ㅇㅇ(14.52)',
  'ㅇㅇ(118.235)' or '아이폰(17.2)' loses it (Korean address blocks start with
  1, 14 and 27 too, and a nickname can be a device name), and so does a
  version pair with a large number such as 'Chrome(141.0)': losing a version
  is the safer mistake. The
  patterns match on a folded copy of the text (verdict.fold: full-width forms
  and dashes such as '–' or 'ㅡ' fold to ASCII, one character for one), and the
  replacements are made at the same offsets in the text itself, so only the
  identifiers change. Profile and post URLs that carry an author's name come
  from the data files: hosts whose first path segment or subdomain is the author
  (data/suffixes.json path_hosted and hosting_suffixes, and routes whose
  author_from is path_segment or subdomain), and a route's profile_paths (such
  as a channel path) on its hosts. `read` and `ingest` scrub all page text before it is printed,
  saved or scanned, so the planned merge verbatim check compares against the
  scrubbed text. The patterns are imperfect; excerpts are also kept short and
  verifier-sampled later.
- origin_only keeps only a URL's scheme and host, for records kept after a run closes.
- author_key is an HMAC-SHA256 of the run's salt with the platform and handle,
  truncated to 16 hex characters. The handle itself is never written anywhere.
  Before keying, the handle is NFKC-normalised, stripped of zero-width
  characters, trimmed and case-folded, and a trailing partial-IP group such as
  '(118.235)', '(2001:2d8)', '(118.235.*.*)' or the scrubber's own '([ip])' is
  split off. A handle that carried such a group (a logged-out poster), that
  holds an IP-like fragment anywhere or any placeholder the scrubber or the reader's label pass writes
  ('[handle]', '[email]', '[author]' and the rest), or that is a default anonymous nickname
  (data/markers.json anonymous_handles, such as 'ㅇㅇ', also spaced 'ㅇ ㅇ') is
  refused: it is not an identity (a scrubbed handle would merge different
  people into one key), so such posts are counted by thread key instead.
  thread_key is the same over a normalised thread URL.
- Excerpts are at most 300 characters, and at most 5 per source.
"""
from __future__ import annotations

import functools
import hashlib
import hmac
import json
import re
import unicodedata
from pathlib import Path
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit, urlunsplit

from . import verdict

DATA = Path(__file__).resolve().parent / "data"
MAX_EXCERPT_CHARS = 300
MAX_EXCERPTS_PER_SOURCE = 5
MASK = "***"
_SECRET_EXACT = frozenset({"token", "key", "secret", "sig", "signature", "auth", "session", "code", "state",
                           "password", "passwd", "pwd", "pw", "apikey", "sid", "otp", "ticket", "nonce",
                           "credential", "credentials", "jsessionid", "phpsessid", "sessid"})
_SECRET_SUFFIX = re.compile(r"(token|secret|signature|password|passwd|sessionid|sessid|apikey)$"
                            r"|(^|[_.-])(key|sig|auth|code|state|session|pass)$")
_TRACKING = re.compile(r"^(utm_[a-z]+|fbclid|gclid|dclid|msclkid|igshid|mc_eid|_ga)$", re.I)

_SEP = r"(?:\s?[-.]\s?|\s)"  # a dash or dot with optional spaces around it, or one space (dashes are folded)
_URL_TAIL = r"[^\s<>\"')]*"
ACCOUNT_DIGITS = (10, 16)  # digits in a bank-account-like number
_MASK = r"[*xX●○]{1,3}"
_MEMBER_WORDS = r"(?:user|users|u|profile|profiles|member|members|people|author|authors|mypage)"
# A profile or member URL on any host: any path that holds a member segment or an '@name'.
_PROFILE_URL = re.compile(r"https?://[^\s<>\"')]+/(?:@[\w.-]+|" + _MEMBER_WORDS + r"/" + _URL_TAIL + ")", re.I)
# The same shape for a bare link path with no scheme: '/member/123', '/u/9', '/@nick', '/blog/@nick'.
_PROFILE_PATH = re.compile(r"(?:^|/)(?:@[\w.-]+|" + _MEMBER_WORDS + r"/)")


def _account(match: re.Match) -> bool:
    """True when an account-like number has a digit count that fits."""
    number = match.group("number") if "number" in match.re.groupindex else match.group(0)
    digits = sum(ch.isdigit() for ch in number)
    return ACCOUNT_DIGITS[0] <= digits <= ACCOUNT_DIGITS[1]


_VERSION_CARRIERS = frozenset({"v", "ver", "vers", "version", "버전"})
# Latin OS and app names that may carry a glued version pair. Korean device names are left out on purpose:
# a floating nickname can be '아이폰' or '갤럭시', and its partial IP must still go.
_VERSION_NAMES = frozenset({"android", "windows", "chrome", "chromium", "edge", "firefox", "opera", "brave",
                            "vivaldi", "whale", "node", "nodejs", "npm", "yarn", "pnpm", "python", "java", "jdk",
                            "kotlin", "swift", "flutter", "dart", "xcode", "ubuntu", "debian", "fedora", "centos",
                            "rhel", "slack", "kakaotalk"})


def _glued_word(folded: str, end: int) -> str:
    """The word, case-folded, that ends right before `end` in the folded text."""
    start = end
    while start > 0 and folded[start - 1].isalnum():
        start -= 1
    return folded[start:end].casefold()


def _names_version(word: str) -> bool:
    """True when a word glued to a parenthesised pair names an OS or app version: a version carrier ('v',
    'ver', 'version'), a word ending in 'os' (iOS, iPadOS, macOS, HarmonyOS) or a known OS or app name."""
    stem = word.rstrip("0123456789")  # 'chrome141' names Chrome
    return stem in _VERSION_CARRIERS or (stem.endswith("os") and len(stem) >= 3) or stem in _VERSION_NAMES


def _address_like(match: re.Match) -> bool:
    """A parenthesised pair attached to a handle that looks like the first half of an IPv4 address, not a
    small decimal such as a rating or a speed ('(4.8)', '(1.5)') and not a version glued with no space to a
    word that names an OS, an app or a version ('iOS(17.2)', 'v(2.3)', '버전(12.5)') when the pair also looks
    like a version (a first number below 30 and a second of 30 or less). Any other pair after a handle, such
    as 'ㅇㅇ(14.52)', 'ㅇㅇ(118.235)', '아이폰(17.2)' or 'Chrome(141.0)', counts as an address."""
    first, second = int(match.group("a")), int(match.group("b"))
    if first > 255 or second > 255:
        return False
    if not match.group("gap"):
        attached = match.string[match.start() - 1]
        if attached.isalpha() and first < 30 and second <= 30 \
                and _names_version(_glued_word(match.string, match.start())):
            return False
    return not (first <= 10 and len(match.group("b")) == 1)


# (category, pattern on the folded text, replacement, the group to replace or None for the match, a check
# that must pass or None). Run in this order; a later pattern sees the earlier placeholders.
_PATTERNS = [
    ("email", re.compile(r"[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,253}\.[A-Za-z]{2,24}"), "[email]", None, None),
    ("id_number", re.compile(r"(?<!\d)\d{6}(?:\s?-\s?|\s)[1-8]\d{6}(?!\d)"), "[id-number]", None, None),
    ("id_number", re.compile(r"(?<!\d)\d{6}\s?-\s?[1-8][*＊xX●○]{6}"), "[id-number]", None, None),
    ("card", re.compile(r"(?<!\d)(?:\d{4}[ -]?){3}\d{1,7}(?!\d)"), "[card]", None, None),
    ("phone", re.compile(r"(?<![\d+])(?:\+?82[ -]?)?\(?0?1[016789](?:\)\s?|" + _SEP + r")?\d{3,4}" + _SEP
                         + r"?\d{4}(?!\d)"), "[phone]", None, None),
    ("phone", re.compile(r"(?<!\d)\(?0(?:2|[3-6][1-5]|70|50\d?)(?:\)\s?|" + _SEP + r")\d{3,4}" + _SEP + r"\d{4}(?!\d)"),
     "[phone]", None, None),
    ("account", re.compile(r"(?:계좌|입금|송금|account|은행|뱅크|국민|신한|우리|하나|농협|기업|우체국|새마을|수협|씨티|SC제일)"
                           r"[^\d\n]{0,16}?(?P<number>\d[\d -]{8,22}\d)(?![\d-])", re.I), "[account]", "number", _account),
    ("account", re.compile(r"(?<![\d.-])\d{2,6}(?:-\d{2,7}){2,3}(?![\d-]|\.\d)"), "[account]", None, _account),
    ("profile_url", _PROFILE_URL, "[profile-url]", None, None),
    ("ip", re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?!\d|\.\d)"), "[ip]", None, None),
    # Masked addresses: '211.36.***.***', '118.235.xxx.xxx', '118.235.*.*', '***.***.12.34'.
    ("partial_ip", re.compile(r"(?<![\w.*])(?=[\d.*xX●○]*\d)(?=[\d.]*[*xX●○])(?:\d{1,3}|" + _MASK + r")(?:\.(?:\d{1,3}|"
                              + _MASK + r")){3}(?![\w*])"), "[ip]", None, None),
    # An 'IP' label with a partial address: 'IP 118.235', '(IP: 118.235)', '아이피 118.235'.
    ("partial_ip", re.compile(r"(?:(?<![A-Za-z])IP|아이피)\s*:?\s*(?P<number>\d{1,3}\.\d{1,3})(?![\d.])"), "[ip]", "number",
     None),
    # A group attached to a handle: 'ㅇㅇ(118.235)', 'ㅇㅇ(2001:2d8)', or after only a space or a line break, as table
    # cells and line layouts render it ('ㅇㅇ (118.235)'). A small decimal such as a rating is never taken, and a
    # version-shaped pair glued to a word that names an OS, an app or a version ('iOS(17.2)') is kept; see
    # _address_like.
    ("partial_ip", re.compile(r"(?<=[^\s(\[{<])(?P<gap>[ \t]*\n?[ \t]*)(?P<group>\(\s*(?P<a>\d{1,3})\.(?P<b>\d{1,3})"
                              r"\s*\))"), "([ip])", "group", _address_like),
    ("partial_ip", re.compile(r"(?<=[^\s(\[{<])[ \t]*\n?[ \t]*(?P<group>\(\s*[23][0-9A-Fa-f]{3}(?::[0-9A-Fa-f]{1,4}){1,3}"
                              r"\s*\))"), "([ip])", "group", None),
    ("handle", re.compile(r"(?<![\w@.])@(?=[\w.-]*[^\W\d_])\w[\w.-]{1,30}"), "[handle]", None, None),
]
PLACEHOLDERS = ("[email]", "[id-number]", "[card]", "[phone]", "[account]", "[profile-url]", "[ip]", "[handle]",
                "[author]")


@functools.lru_cache(maxsize=1)
def _author_urls() -> re.Pattern | None:
    """URLs whose first path segment or subdomain names the author, from the data files only."""
    suffixes = json.loads((DATA / "suffixes.json").read_text(encoding="utf-8"))
    routes = json.loads((DATA / "routes.json").read_text(encoding="utf-8"))
    path_hosts = {item["host"] for item in suffixes.get("path_hosted", []) if item.get("host")}
    path_hosts |= set(suffixes.get("profile_hosts", []))
    sub_hosts = set(suffixes.get("hosting_suffixes", []))
    for platform in routes.get("platforms", []):
        for host in platform.get("hosts", []):
            if platform.get("author_from") == "subdomain" and host.startswith("*."):
                sub_hosts.add(host[2:])
            elif platform.get("author_from") == "path_segment" and not host.startswith("*."):
                path_hosts.add(host)
    parts = [r"(?:www\.|m\.)?" + re.escape(h) + r"/[^\s<>\"'/)]+" + _URL_TAIL
             for h in sorted(path_hosts, key=len, reverse=True)]
    parts += [r"[a-z0-9-]+(?:\.[a-z0-9-]+)*\." + re.escape(h) + r"(?![a-z0-9.-])(?:/" + _URL_TAIL + ")?"
              for h in sorted(sub_hosts, key=len, reverse=True)]
    for platform in routes.get("platforms", []):  # channel or profile paths, such as /channel/<id>
        paths = [p for p in platform.get("profile_paths") or [] if isinstance(p, str) and re.fullmatch(r"[\w.-]+", p)]
        if paths:
            parts += [re.escape(h) + r"/(?:" + "|".join(re.escape(p) for p in paths) + r")/[^\s<>\"'/)]+" + _URL_TAIL
                      for h in platform.get("hosts", []) if isinstance(h, str) and not h.startswith("*.")]
    return re.compile(r"https?://(?:" + "|".join(parts) + ")", re.I) if parts else None


def _is_secret(name: str) -> bool:
    lowered = unquote(name).strip().lower()
    return lowered in _SECRET_EXACT or bool(_SECRET_SUFFIX.search(lowered))


def masks_param(name: str) -> bool:
    """True when mask_url masks the value of a query or fragment parameter with this name."""
    return _is_secret(name)


def _mask_pairs(value: str) -> str:
    pieces = []
    for piece in value.split("&"):
        name, sep, _ = piece.partition("=")
        pieces.append(f"{name}={MASK}" if sep and _is_secret(name) else piece)
    return "&".join(pieces)


def mask_url(url: str) -> str:
    """Drop credentials and mask secret-looking parameter values; keep names for diagnosis."""
    if not isinstance(url, str):
        return ""
    try:
        parts = urlsplit(url)
    except ValueError:
        return "[unparseable-url]"
    netloc = parts.netloc
    if "@" in netloc:
        netloc = f"{MASK}@{netloc.rsplit('@', 1)[1]}"
    return urlunsplit((parts.scheme, netloc, parts.path, _mask_pairs(parts.query) if parts.query else "",
                       _mask_pairs(parts.fragment) if "=" in parts.fragment else parts.fragment))


def origin_only(url: str) -> str:
    """scheme://host[:port] of a URL: what a closed run keeps instead of a post URL."""
    if not isinstance(url, str) or not url:
        return ""
    try:
        parts = urlsplit(url)
        netloc = parts.netloc.rsplit("@", 1)[-1]
    except ValueError:
        return "[unparseable-url]"
    return f"{parts.scheme}://{netloc}" if parts.scheme and netloc else "[url]"


def _replace(pattern: re.Pattern, text: str, folded: str | None, replacement: str, group: str | None,
             check) -> tuple[str, str | None, int]:
    """Find the pattern in the folded copy and replace the same spans in both. `folded` is None when the
    text needs no folding."""
    source = text if folded is None else folded
    pieces, folded_pieces, last, count = [], [], 0, 0
    for match in pattern.finditer(source):
        if check is not None and not check(match):
            continue
        start, end = match.span(group) if group else match.span()
        if start < last:
            continue
        pieces += [text[last:start], replacement]
        if folded is not None:
            folded_pieces += [folded[last:start], replacement]
        last, count = end, count + 1
    if not count:
        return text, folded, 0
    pieces.append(text[last:])
    if folded is not None:
        folded_pieces.append(folded[last:])
    return "".join(pieces), ("".join(folded_pieces) if folded is not None else None), count


def profile_href(url: str) -> bool:
    """True when this URL points at a person's profile or member page. The reader's author-label pass uses
    it for a link inside a label (extract.py): the same profile-URL patterns the scrubber applies — the
    generic member/profile path on any host, plus the author URLs the data files list — matched against the
    whole URL; a bare link path ('/member/123', '/u/9', '/@nick') is judged by its path shape alone."""
    if not isinstance(url, str) or not url.strip():
        return False
    value = url.strip()
    try:
        parts = urlsplit(value)
    except ValueError:
        parts = None
    candidates = [value]
    if parts is not None and not parts.scheme:
        if parts.netloc:  # protocol-relative '//site/member/123'
            candidates.append("https:" + value)
        elif parts.path:
            rest = parts.path + (f"?{parts.query}" if parts.query else "")
            if _PROFILE_PATH.search(rest):
                return True
    authors = _author_urls()
    for candidate in candidates:
        if _PROFILE_URL.match(candidate) or (authors is not None and bool(authors.match(candidate))):
            return True
    return False


def scrub(text: str) -> tuple[str, dict]:
    """Replace personal identifiers; returns the scrubbed text and a count per category. The patterns match
    on a folded copy (verdict.fold, which keeps every offset), and only the matched spans change."""
    counts: dict[str, int] = {}
    folded = verdict.fold(text)
    folded = None if folded == text else folded
    authors = _author_urls()
    steps = ([("profile_url", authors, "[profile-url]", None, None)] if authors is not None else []) + _PATTERNS
    for name, pattern, replacement, group, check in steps:
        text, folded, n = _replace(pattern, text, folded, replacement, group, check)
        if n:
            counts[name] = counts.get(name, 0) + n
    return text, counts


def _key(salt: bytes, *parts: str) -> str:
    message = "\x1f".join(parts).encode("utf-8")
    return hmac.new(salt, message, hashlib.sha256).hexdigest()[:16]


_ZERO_WIDTH = re.compile("[\u00ad\u180e\u200b-\u200f\u2060-\u2064\ufeff]")
_OCTET = r"(?:\d{1,3}|" + _MASK + r")"
# A trailing partial-IP group: IPv4 (masked or not), IPv6, or the scrubber's own '([ip])'.
_TRAILING_IP = re.compile(r"\s*[(\[]{1,2}\s*(?:" + _OCTET + r"(?:\s*\.\s*" + _OCTET + r"){1,3}"
                          r"|[0-9A-Fa-f]{1,4}(?:\s*:\s*[0-9A-Fa-f]{0,4}){1,7}|ip)\s*[)\]]{1,2}\s*$", re.I)
# An IP-like fragment anywhere in a handle: '118.235', '118.235.*.*', '2001:2d8'.
_IP_FRAGMENT = re.compile(r"(?<!\d)\d{1,3}\s*\.\s*" + _OCTET + r"(?!\d)|(?<![0-9A-Fa-f])[0-9A-Fa-f]{2,4}:[0-9A-Fa-f]{1,4}"
                          r"(?![0-9A-Fa-f])")
USE_THREAD_KEY = "use --thread-url for a thread key instead"


def normalize_handle(handle: str) -> tuple[str, bool]:
    """(the handle NFKC-normalised, without zero-width characters, trimmed and without a trailing
    partial-IP group, whether it had one). 'ㅇㅇ(118.235)' and 'ㅇㅇ([ip])' become ('ㅇㅇ', True)."""
    value = _ZERO_WIDTH.sub("", unicodedata.normalize("NFKC", handle or "")).strip()
    stripped = _TRAILING_IP.sub("", value)
    return stripped.strip(), stripped != value


def check_handle(handle: str) -> str:
    """The normalised handle, or ValueError when it is not an identity: empty, carrying a partial IP
    address anywhere (a logged-out poster, who can type any nickname), holding a scrubber placeholder
    (the scrubbed text hides who wrote it, so every such handle would share one key) or a default
    anonymous nickname."""
    value, had_ip = normalize_handle(handle)
    if had_ip or _IP_FRAGMENT.search(value):
        raise ValueError("a handle with a partial IP address, such as 'ㅇㅇ(118.235)', 'ㅇㅇ(2001:2d8)' or 'ㅇㅇ([ip])' "
                         f"as the scrubbed text shows it, is a logged-out poster, not an identity; {USE_THREAD_KEY}")
    lowered = value.casefold()
    if any(placeholder in lowered for placeholder in PLACEHOLDERS):
        raise ValueError("a handle that holds a placeholder of the scrubber (such as '[handle]' or '[email]') is not "
                         f"an identity: the scrubbed text hides who wrote it; {USE_THREAD_KEY}")
    if not value:
        raise ValueError("handle is empty")
    if verdict.anonymous_handle(value) or verdict.anonymous_handle("".join(value.split())):
        raise ValueError(f"a default anonymous nickname is not an identity; {USE_THREAD_KEY}")  # anonymous_handles
    return value


def author_key(salt: bytes, platform: str, handle: str) -> str:
    normalized = check_handle(handle).casefold()
    return _key(salt, "author", platform.strip().lower(), normalized)


def normalize_thread_url(url: str) -> str:
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    for prefix in ("www.", "m."):
        if host.startswith(prefix):
            host = host[len(prefix):]
    query = sorted((k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _TRACKING.match(k))
    path = (parts.path or "/").rstrip("/") or "/"
    return urlunsplit(("", host, quote(unquote(path), safe="/%:@!$&'()*+,;=-._~"), urlencode(query), ""))


def thread_key(salt: bytes, url: str) -> str:
    return _key(salt, "thread", normalize_thread_url(url))


def check_excerpt(text: str) -> str:
    """Return the NFC excerpt, or raise ValueError when it is longer than the limit."""
    value = unicodedata.normalize("NFC", text)
    if len(value) > MAX_EXCERPT_CHARS:
        raise ValueError(f"excerpt is {len(value)} characters; the limit is {MAX_EXCERPT_CHARS}")
    return value
