"""SSRF-guarded HTTP(S) GET with manual redirects, size caps and charset handling.

Only http and https. Before every hop the host is resolved and every A/AAAA
record must be a public unicast address (IPv4-mapped, 6to4, Teredo and NAT64
addresses are unwrapped first; CGNAT, link-local, metadata, multicast and
reserved ranges are refused). Direct connections are pinned to the checked
address while SNI and Host keep the hostname. Through an HTTP(S)_PROXY the proxy
resolves the name, so the local pre-check is best effort and the response says
so. Certificates are always verified. Redirects are followed by hand so each hop
is checked again. A malformed URL or Location header is a NetError, never an
uncaught ValueError. The time limit covers the whole body: each read waits at
most for the time that is left, so a server that trickles bytes cannot hold the
reader (and its host slot) past the limit.

Test hooks (never for real use): two module attributes that only the
repository's tests set, in the same process: _TEST_ALLOW_LOOPBACK lets the reader
connect to loopback addresses, and _TEST_RESOLVE maps reserved test names (.test,
.example, .invalid, .localhost) to loopback addresses. No environment variable,
command-line switch, brief, route table or page text can turn them on. Test names
are never looked up in real DNS and never go through a proxy. Responses record
when a test hook was used, and `start` records test_hooks in run.json.
"""
from __future__ import annotations

import base64
import codecs
import http.client
import ipaddress
import os
import re
import socket
import ssl
import time
import urllib.request
import zlib
from dataclasses import dataclass, field
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

TIMEOUT_S = 20.0
MAX_WIRE_BYTES = 5 * 1024 * 1024
MAX_DECODED_BYTES = 8 * 1024 * 1024
MAX_REDIRECTS = 5
REDIRECT_BODY_BYTES = 64 * 1024
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
TEST_SUFFIXES = (".test", ".example", ".invalid", ".localhost")
# Tests only, set in process (mock.patch.object): never read from the environment or any file.
_TEST_ALLOW_LOOPBACK = False
_TEST_RESOLVE: dict = {}
# Python maps euc-kr and ks_c_5601-1987 to strict EUC-KR and does not know
# x-windows-949; pages with these labels are nearly always CP949 in practice.
CP949_LABELS = frozenset({"euc-kr", "euc_kr", "euckr", "ks_c_5601-1987", "ks_c_5601_1987", "ks_c_5601",
                          "ksc5601", "ksc_5601", "x-windows-949", "windows-949", "uhc", "cp949", "ms949"})
REFUSAL_KINDS = frozenset({"bad_url", "bad_scheme", "credentials_in_url", "ssrf_blocked"})
TRANSIENT_KINDS = frozenset({"timeout", "connect_error"})
_NAT64 = ipaddress.ip_network("64:ff9b::/96")
_META_CHARSET = re.compile(rb"<meta[^>]{0,200}?charset\s*=\s*[\"']?\s*([A-Za-z0-9_.:-]{1,40})", re.I)
_XML_ENCODING = re.compile(rb"<\?xml[^>]{0,200}?encoding\s*=\s*[\"']([A-Za-z0-9_.:-]{1,40})", re.I)


class NetError(Exception):
    """A fetch that produced no usable response. `kind` is a stable token."""

    def __init__(self, kind: str, detail: str = "", redirects: list | None = None):
        super().__init__(f"{kind}: {detail}" if detail else kind)
        self.kind = kind
        self.detail = detail
        self.redirects = redirects or []


@dataclass
class Response:
    url: str
    final_url: str
    status: int
    headers: dict
    body: bytes
    wire_bytes: int
    elapsed_ms: int
    redirects: list = field(default_factory=list)
    location: str | None = None
    via_proxy: bool = False
    precheck: str = "pinned"
    test_override: bool = False
    truncated: bool = False
    x_robots: list = field(default_factory=list)  # each X-Robots-Tag header on its own

    @property
    def content_type(self) -> str:
        return self.headers.get("content-type", "").split(";", 1)[0].strip().lower()

    def text(self) -> tuple[str, str]:
        return decode_body(self.body, self.headers.get("content-type", ""))


# ---------------------------------------------------------------- URLs


def _ascii_host(host: str) -> str:
    try:
        return str(ipaddress.ip_address(host)).lower()
    except ValueError:
        pass
    try:
        value = host.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise NetError("bad_url", "invalid host name") from exc
    if not value or not re.fullmatch(r"[a-z0-9._-]+", value):
        raise NetError("bad_url", "invalid host name")
    return value


def parse_url(url: str) -> str:
    """Validate an absolute http(s) URL; return it with an ASCII host, no fragment, no default port."""
    if not isinstance(url, str) or not url.strip() or len(url) > 8192 or re.search(r"[\x00-\x1f\x7f]", url.strip()):
        raise NetError("bad_url", "not a single-line absolute URL")
    try:
        parts = urlsplit(url.strip())
        hostname = parts.hostname
    except ValueError as exc:  # for example 'http://[oops/' (an unclosed IPv6 bracket)
        raise NetError("bad_url", "malformed URL") from exc
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise NetError("bad_scheme", f"only http and https are read (got {scheme or 'none'})")
    if "@" in parts.netloc:
        raise NetError("credentials_in_url", "URLs carrying user:password@ are refused")
    if not hostname:
        raise NetError("bad_url", "no host")
    try:
        port = parts.port
    except ValueError as exc:
        raise NetError("bad_url", "invalid port") from exc
    host = _ascii_host(hostname)
    netloc = f"[{host}]" if ":" in host else host
    if port is not None and port != (443 if scheme == "https" else 80):
        netloc += f":{port}"
    path = quote(parts.path or "/", safe="/%:@!$&'()*+,;=-._~")
    query = quote(parts.query, safe="/?%:@!$&'()*+,;=-._~")
    return urlunsplit((scheme, netloc, path, query, ""))


def host_of(url: str) -> str:
    try:
        return urlsplit(url).hostname or ""
    except ValueError:  # a malformed authority such as 'http://[oops/'
        return ""


def origin_of(url: str) -> str:
    try:
        parts = urlsplit(url)
    except ValueError:
        return ""
    return f"{parts.scheme}://{parts.netloc}".lower()


# ---------------------------------------------------------------- addresses


def _embedded_v4(ip) -> ipaddress.IPv4Address | None:
    if ip.version != 6:
        return None
    if ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    if ip.sixtofour is not None:
        return ip.sixtofour
    if ip.teredo is not None:
        return ip.teredo[1]
    if ip in _NAT64:
        return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    return None


def is_public_address(ip) -> bool:
    inner = _embedded_v4(ip)
    if inner is not None and not is_public_address(inner):
        return False
    if ip.is_multicast or ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_unspecified:
        return False
    if ip.version == 6 and ip.is_site_local:
        return False
    return ip.is_global


def _is_loopback(ip) -> bool:
    inner = _embedded_v4(ip)
    return ip.is_loopback or (inner is not None and inner.is_loopback)


def test_hooks_enabled() -> bool:
    return _TEST_ALLOW_LOOPBACK is True


def _test_map() -> dict[str, str]:
    return {str(name).strip().lower().rstrip("."): str(address).strip()
            for name, address in dict(_TEST_RESOLVE).items() if str(name).strip()}


def is_test_host(host: str) -> bool:
    return host.lower().rstrip(".").endswith(TEST_SUFFIXES)


def resolve(host: str, port: int) -> tuple[list, bool]:
    """Return (addresses, test_override). Reserved test names never reach real DNS."""
    name = host.lower().rstrip(".").strip("[]")
    try:
        return [ipaddress.ip_address(name)], False
    except ValueError:
        pass
    if is_test_host(name):
        if not test_hooks_enabled():
            raise NetError("dns_error", f"{name} is a reserved test name")
        address = _test_map().get(name)
        if address is None:
            raise NetError("dns_error", f"test name {name} is not mapped")
        try:
            ip = ipaddress.ip_address(address)
        except ValueError as exc:
            raise NetError("dns_error", f"test name {name} maps to an invalid address") from exc
        if not _is_loopback(ip):
            raise NetError("ssrf_blocked", "test names may map only to loopback addresses")
        return [ip], True
    try:
        infos = socket.getaddrinfo(name, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError, OSError) as exc:
        raise NetError("dns_error", f"{name} did not resolve") from exc
    addresses = []
    for info in infos:
        text = str(info[4][0]).split("%", 1)[0]
        ip = ipaddress.ip_address(text)
        if ip not in addresses:
            addresses.append(ip)
    if not addresses:
        raise NetError("dns_error", f"{name} has no addresses")
    return addresses, False


def check_host(host: str, port: int) -> tuple[list, bool]:
    """Resolve and require public addresses (loopback only with the test flag)."""
    addresses, override = resolve(host, port)
    allow_loopback = test_hooks_enabled()
    for ip in addresses:
        if is_public_address(ip) or (allow_loopback and _is_loopback(ip)):
            continue
        raise NetError("ssrf_blocked", f"{host} resolves to a non-public address ({ip})")
    return addresses, override


def resolves(host: str) -> bool:
    """True when the name resolves to acceptable addresses (used before generic rewrites)."""
    try:
        check_host(_ascii_host(host), 443)
        return True
    except NetError:
        return False


# ---------------------------------------------------------------- connections


def _ssl_context() -> ssl.SSLContext:
    context = ssl.create_default_context()  # verification stays on; OpenSSL honours SSL_CERT_FILE
    cafile = os.environ.get("SSL_CERT_FILE")
    if cafile and os.path.isfile(cafile):
        context.load_verify_locations(cafile=cafile)
    return context


MAX_ADDRESSES = 4


def _connect_checked(addresses: list, port: int, timeout: float) -> socket.socket:
    """Connect to the first reachable address among those already checked (no new lookup)."""
    failure: OSError | None = None
    for ip in addresses[:MAX_ADDRESSES]:
        try:
            return socket.create_connection((str(ip), port), timeout)
        except OSError as exc:
            failure = exc
    raise failure or OSError("no address to connect to")


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host: str, port: int, addresses: list, timeout: float):
        super().__init__(host, port, timeout=timeout)
        self._addresses = addresses

    def connect(self) -> None:
        self.sock = _connect_checked(self._addresses, self.port, self.timeout)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, port: int, addresses: list, timeout: float, context: ssl.SSLContext):
        super().__init__(host, port, timeout=timeout, context=context)
        self._addresses = addresses

    def connect(self) -> None:
        sock = _connect_checked(self._addresses, self.port, self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def _proxy_for(scheme: str, host: str) -> str | None:
    proxies = urllib.request.getproxies_environment()
    if not proxies or urllib.request.proxy_bypass_environment(host, proxies):
        return None
    return proxies.get(scheme)


def _proxy_connection(proxy: str, scheme: str, host: str, port: int, timeout: float):
    parts = urlsplit(proxy if "://" in proxy else "http" + "://" + proxy)
    if parts.scheme.lower() != "http" or not parts.hostname:
        raise NetError("connect_error", "only plain-HTTP proxies are supported")
    headers = {}
    if parts.username is not None:
        token = f"{parts.username}:{parts.password or ''}".encode()
        headers["Proxy-Authorization"] = "Basic " + base64.b64encode(token).decode("ascii")
    if scheme == "https":
        # Proxy credentials travel only in the CONNECT request, never inside the tunnel.
        conn = http.client.HTTPSConnection(parts.hostname, parts.port or 80, timeout=timeout, context=_ssl_context())
        conn.set_tunnel(host, port, headers=headers)
        return conn, {}, False
    conn = http.client.HTTPConnection(parts.hostname, parts.port or 80, timeout=timeout)
    return conn, headers, True


def _headers(message) -> dict:
    result: dict[str, str] = {}
    for name, value in message.items():
        key = name.lower()
        result[key] = f"{result[key]}, {value}" if key in result else value
    return result


def _read_capped(response, cap: int, deadline: float, truncate: bool, sock=None) -> tuple[bytes, bool]:
    """Read at most `cap` bytes before `deadline`. Each read returns what has arrived (read1) and
    waits at most for the time that is left, so a trickling server cannot stretch the limit."""
    chunks, total = [], 0
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise NetError("timeout", "the response exceeded the time limit")
        if sock is not None:
            try:
                sock.settimeout(remaining)
            except OSError:
                pass
        chunk = response.read1(65536)
        if not chunk:
            if getattr(response, "length", None):  # Content-Length promised more than arrived
                raise NetError("protocol_error", "the connection closed before the body was complete")
            return b"".join(chunks), False
        total += len(chunk)
        if total > cap:
            if truncate:
                chunks.append(chunk[: len(chunk) - (total - cap)])
                return b"".join(chunks), True
            raise NetError("too_large", f"more than {cap} bytes on the wire")
        chunks.append(chunk)


def _inflate(raw: bytes, wbits: int, cap: int, truncate: bool) -> tuple[bytes, bool]:
    engine = zlib.decompressobj(wbits)
    out = bytearray()
    data = raw
    while data and not engine.eof:
        chunk = engine.decompress(data, cap + 1 - len(out))
        out += chunk
        if len(out) > cap:
            if truncate:
                return bytes(out[:cap]), True
            raise NetError("too_large", f"more than {cap} bytes after decompression")
        data = engine.unconsumed_tail
        if not chunk and data:
            break
    return bytes(out), False


def _decode_content(raw: bytes, encoding: str, cap: int, truncate: bool) -> tuple[bytes, bool]:
    token = encoding.strip().lower()
    if token in ("", "identity"):
        return raw, False
    if token in ("gzip", "x-gzip"):
        try:
            return _inflate(raw, 16 + zlib.MAX_WBITS, cap, truncate)
        except zlib.error as exc:
            raise NetError("decode_error", "invalid gzip body") from exc
    if token == "deflate":
        try:
            return _inflate(raw, zlib.MAX_WBITS, cap, truncate)
        except zlib.error:
            try:
                return _inflate(raw, -zlib.MAX_WBITS, cap, truncate)
            except zlib.error as exc:
                raise NetError("decode_error", "invalid deflate body") from exc
    raise NetError("unsupported_encoding", token)


@dataclass
class _Hop:
    status: int
    headers: dict
    body: bytes
    wire_bytes: int
    location: str | None
    via_proxy: bool
    precheck: str
    test_override: bool
    truncated: bool
    x_robots: list


def _request_once(url: str, headers: dict, timeout: float, max_wire: int, max_decoded: int, truncate: bool) -> _Hop:
    parts = urlsplit(url)
    scheme = parts.scheme
    host = parts.hostname or ""
    port = parts.port or (443 if scheme == "https" else 80)
    target = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    proxy = None
    try:
        addresses, override = check_host(host, port)
        precheck = "test_override" if override else "pinned"
        direct = override or any(_is_loopback(ip) for ip in addresses)
    except NetError as exc:
        if exc.kind != "dns_error" or is_test_host(host) or _proxy_for(scheme, host) is None:
            raise
        addresses, override, precheck, direct = [], False, "proxy_best_effort", False
    if not direct:
        proxy = _proxy_for(scheme, host)
        if proxy and precheck == "pinned":
            precheck = "proxy_checked"
    extra: dict = {}
    if proxy:
        conn, extra, absolute = _proxy_connection(proxy, scheme, host, port, timeout)
        if absolute:
            target = url
    elif scheme == "https":
        conn = _PinnedHTTPSConnection(host, port, addresses, timeout, _ssl_context())
    else:
        conn = _PinnedHTTPConnection(host, port, addresses, timeout)
    deadline = time.monotonic() + timeout
    response = None
    try:
        conn.putrequest("GET", target, skip_accept_encoding=True)
        for name, value in {**headers, **extra}.items():
            conn.putheader(name, value)
        conn.putheader("Accept-Encoding", "gzip, deflate")
        conn.putheader("Connection", "close")
        conn.endheaders()
        sock = conn.sock  # kept: the connection object drops it once the response owns the stream
        response = conn.getresponse()
        status = response.status
        found = _headers(response.msg)
        x_robots = [str(v) for v in (response.msg.get_all("X-Robots-Tag") or [])][:20]
        if status in REDIRECT_STATUSES and found.get("location"):
            raw, _ = _read_capped(response, REDIRECT_BODY_BYTES, deadline, True, sock)
            return _Hop(status, found, b"", len(raw), found["location"].strip(), bool(proxy), precheck, override, False,
                        x_robots)
        declared = found.get("content-length", "").strip()
        if declared.isdigit() and int(declared) > max_wire and not truncate:
            raise NetError("too_large", f"content-length {declared} exceeds {max_wire} bytes")
        raw, cut = _read_capped(response, max_wire, deadline, truncate, sock)
        body, cut_decoded = _decode_content(raw, found.get("content-encoding", ""), max_decoded, truncate)
        return _Hop(status, found, body, len(raw), None, bool(proxy), precheck, override, cut or cut_decoded, x_robots)
    except NetError:
        raise
    except (socket.timeout, TimeoutError) as exc:
        raise NetError("timeout", "no response within the time limit") from exc
    except ssl.SSLError as exc:
        raise NetError("tls_error", exc.__class__.__name__) from exc
    except http.client.RemoteDisconnected as exc:
        raise NetError("connect_error", "the server closed the connection") from exc
    except http.client.HTTPException as exc:
        raise NetError("protocol_error", exc.__class__.__name__) from exc
    except ValueError as exc:  # a malformed status line, header or chunk size
        raise NetError("protocol_error", "malformed response") from exc
    except OSError as exc:
        raise NetError("connect_error", exc.__class__.__name__) from exc
    finally:
        if response is not None:
            response.close()  # also when a read failed half-way, so the socket is closed now, not at collection
        conn.close()


def fetch(url: str, *, headers: dict | None = None, timeout: float = TIMEOUT_S,
          max_redirects: int = MAX_REDIRECTS, on_redirect=None, max_wire: int = MAX_WIRE_BYTES,
          max_decoded: int = MAX_DECODED_BYTES, truncate: bool = False) -> Response:
    """GET `url`. `on_redirect(from_url, to_url)` returning False stops at that redirect
    and returns it with `location` set, so the caller can apply its own policy."""
    started = time.monotonic()
    current = parse_url(url)
    first = current
    seen = {current}
    redirects: list[dict] = []
    wire = 0
    while True:
        hop = _request_once(current, dict(headers or {}), timeout, max_wire, max_decoded, truncate)
        wire += hop.wire_bytes
        if hop.location is None:
            return Response(first, current, hop.status, hop.headers, hop.body, wire,
                            int((time.monotonic() - started) * 1000), redirects, None,
                            hop.via_proxy, hop.precheck, hop.test_override, hop.truncated, hop.x_robots)
        try:
            target = parse_url(urljoin(current, hop.location))
        except (NetError, ValueError) as exc:
            kind = exc.kind if isinstance(exc, NetError) else "bad_url"
            raise NetError("protocol_error", f"redirect to an unusable URL ({kind})", redirects) from exc
        redirects.append({"status": hop.status, "from": current, "to": target})
        if len(redirects) > max_redirects or target in seen:
            raise NetError("redirect_loop", f"more than {max_redirects} redirects or a cycle", redirects)
        seen.add(target)
        if on_redirect is not None and not on_redirect(current, target):
            return Response(first, current, hop.status, hop.headers, b"", wire,
                            int((time.monotonic() - started) * 1000), redirects, target,
                            hop.via_proxy, hop.precheck, hop.test_override, False, hop.x_robots)
        current = target


# ---------------------------------------------------------------- text


def codec_for(label: str | None) -> str | None:
    if not label:
        return None
    name = label.strip().strip("\"'").lower()
    if name in CP949_LABELS:
        return "cp949"
    try:
        return codecs.lookup(name).name
    except LookupError:
        return None


def _charset_param(content_type: str) -> str | None:
    match = re.search(r"charset\s*=\s*[\"']?([A-Za-z0-9_.:-]+)", content_type or "", re.I)
    return match.group(1) if match else None


def decode_body(body: bytes, content_type: str = "") -> tuple[str, str]:
    """Decode by BOM, then the header charset, then a meta or XML declaration, else UTF-8."""
    if body.startswith(b"\xef\xbb\xbf"):
        return body[3:].decode("utf-8", "replace"), "utf-8"
    if body.startswith((b"\xff\xfe", b"\xfe\xff")):
        return body.decode("utf-16", "replace"), "utf-16"
    head = body[:4096]
    label = _charset_param(content_type)
    if not label:
        found = _META_CHARSET.search(head) or _XML_ENCODING.search(head)
        label = found.group(1).decode("ascii", "replace") if found else None
    codec = codec_for(label)
    if codec:
        try:
            return body.decode(codec), codec
        except UnicodeDecodeError:
            return body.decode(codec, "replace"), codec
    try:
        return body.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass
    try:
        return body.decode("cp949"), "cp949"
    except UnicodeDecodeError:
        return body.decode("utf-8", "replace"), "utf-8"
