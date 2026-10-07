"""Stdlib-only PNG decode/encode plus small raster helpers (luminance, heat overlay).

Supported on decode: 8-bit greyscale (colour type 0), RGB (2), grey+alpha (4) and
RGBA (6); palette (3) at 1/2/4/8 bits, expanded to RGB, or RGBA when a tRNS chunk
is present. Filters 0-4 and multiple IDAT chunks are handled and every chunk CRC
is checked. Interlaced (Adam7), 16-bit and other sub-byte images are rejected
with :class:`PNGError`; tRNS on non-palette images and colour-management chunks
(gAMA/iCCP/sRGB) are ignored, i.e. samples are treated as sRGB.

Everything is pure Python: decoding a 1080x2340 screenshot takes seconds, not
milliseconds. Downsample before per-pixel work where the analysis allows it.
"""
from __future__ import annotations

import math
import operator
import struct
import zlib
from array import array
from functools import lru_cache
from itertools import accumulate
from pathlib import Path
from typing import Iterable, NamedTuple, Sequence

SIGNATURE = b"\x89PNG\r\n\x1a\n"
COLOR_TYPE_BY_CHANNELS = {1: 0, 2: 4, 3: 2, 4: 6}
CHANNELS_BY_COLOR_TYPE = {0: 1, 2: 3, 4: 2, 6: 4}
MODES = {1: "L", 2: "LA", 3: "RGB", 4: "RGBA"}
MAX_PIXELS = 50_000_000
MAX_FILE_BYTES = 128 * 1024 * 1024
_AND255 = (255).__and__


class PNGError(ValueError):
    """Malformed or unsupported PNG data."""


class Image(NamedTuple):
    """8-bit image: row-major interleaved samples without filter bytes."""

    width: int
    height: int
    channels: int
    data: bytes

    @property
    def mode(self) -> str:
        return MODES[self.channels]

    @property
    def stride(self) -> int:
        return self.width * self.channels

    def row(self, y: int) -> bytes:
        s = self.stride
        return bytes(self.data[y * s:(y + 1) * s])

    def pixel(self, x: int, y: int) -> tuple[int, ...]:
        if not (0 <= x < self.width and 0 <= y < self.height):
            raise IndexError("pixel outside image")
        i = (y * self.width + x) * self.channels
        return tuple(self.data[i:i + self.channels])


class Grid(NamedTuple):
    """Row-major float grid (e.g. luminance or heat values)."""

    width: int
    height: int
    values: array

    def at(self, x: int, y: int) -> float:
        return self.values[y * self.width + x]


def make_image(width: int, height: int, channels: int, data: bytes | bytearray) -> Image:
    if channels not in MODES:
        raise PNGError(f"unsupported channel count: {channels}")
    if width <= 0 or height <= 0:
        raise PNGError("image dimensions must be positive")
    if len(data) != width * height * channels:
        raise PNGError(f"data length {len(data)} != {width}x{height}x{channels}")
    return Image(width, height, channels, bytes(data))


def new_image(width: int, height: int, channels: int = 4, fill: Sequence[int] | None = None) -> Image:
    fill = tuple(fill) if fill is not None else (0,) * channels
    if len(fill) != channels or any(not 0 <= v <= 255 for v in fill):
        raise PNGError("fill must have one 0-255 value per channel")
    return make_image(width, height, channels, bytes(fill) * (width * height))


# --------------------------------------------------------------------------- decode

def _chunks(raw: bytes) -> Iterable[tuple[bytes, bytes]]:
    if not raw.startswith(SIGNATURE):
        raise PNGError("not a PNG file (bad signature)")
    pos = len(SIGNATURE)
    end = len(raw)
    while True:
        if pos + 8 > end:
            raise PNGError("truncated PNG: missing IEND")
        length, kind = struct.unpack(">I4s", raw[pos:pos + 8])
        if length > 0x7FFFFFFF or pos + 12 + length > end:
            raise PNGError(f"truncated PNG chunk {kind!r}")
        body = raw[pos + 8:pos + 8 + length]
        (crc,) = struct.unpack(">I", raw[pos + 8 + length:pos + 12 + length])
        if zlib.crc32(kind + body) & 0xFFFFFFFF != crc:
            raise PNGError(f"CRC mismatch in chunk {kind!r}")
        pos += 12 + length
        yield kind, body
        if kind == b"IEND":
            return


class Header(NamedTuple):
    width: int
    height: int
    bit_depth: int
    color_type: int
    interlace: int


def _parse_ihdr(body: bytes) -> Header:
    if len(body) != 13:
        raise PNGError("IHDR must be 13 bytes")
    w, h, depth, ctype, comp, filt, interlace = struct.unpack(">IIBBBBB", body)
    if w == 0 or h == 0 or w > 0x7FFFFFFF or h > 0x7FFFFFFF:
        raise PNGError("invalid IHDR dimensions")
    if comp != 0 or filt != 0:
        raise PNGError("unsupported IHDR compression/filter method")
    if interlace not in (0, 1):
        raise PNGError("invalid interlace method")
    return Header(w, h, depth, ctype, interlace)


def read_header(source: bytes | str | Path) -> Header:
    """Parse and CRC-check only the signature and IHDR chunk."""
    if isinstance(source, (str, Path)):
        with open(source, "rb") as stream:
            raw = stream.read(64)
    else:
        raw = bytes(source[:64])
    for kind, body in _chunks(raw):
        if kind != b"IHDR":
            raise PNGError("first chunk must be IHDR")
        return _parse_ihdr(body)
    raise PNGError("missing IHDR")  # pragma: no cover - _chunks raises first


@lru_cache(maxsize=64)
def _masks(n: int) -> tuple[int, int]:
    return int.from_bytes(b"\x7f" * n, "big"), int.from_bytes(b"\x80" * n, "big")


def _add_bytes(a: bytes, b: bytes) -> bytes:
    """Byte-wise (a + b) mod 256 via SWAR on Python big integers."""
    n = len(a)
    if n == 0:
        return b""
    low, high = _masks(n)
    ia = int.from_bytes(a, "big")
    ib = int.from_bytes(b, "big")
    return (((ia & low) + (ib & low)) ^ ((ia ^ ib) & high)).to_bytes(n, "big")


def _unsub(line: bytes, bpp: int) -> bytearray:
    out = bytearray(len(line))
    for c in range(bpp):
        out[c::bpp] = bytes(map(_AND255, accumulate(line[c::bpp])))
    return out


def _unavg(line: bytes, prior: bytes, bpp: int) -> bytearray:
    cur = bytearray(line)
    for i in range(min(bpp, len(cur))):
        cur[i] = (cur[i] + (prior[i] >> 1)) & 255
    for i in range(bpp, len(cur)):
        cur[i] = (cur[i] + ((cur[i - bpp] + prior[i]) >> 1)) & 255
    return cur


def _unpaeth(line: bytes, prior: bytes, bpp: int) -> bytearray:
    cur = bytearray(line)
    for i in range(min(bpp, len(cur))):
        cur[i] = (cur[i] + prior[i]) & 255
    for i in range(bpp, len(cur)):
        a = cur[i - bpp]
        b = prior[i]
        c = prior[i - bpp]
        pa = abs(b - c)
        pb = abs(a - c)
        pc = abs(a + b - 2 * c)
        if pa <= pb and pa <= pc:
            pred = a
        elif pb <= pc:
            pred = b
        else:
            pred = c
        cur[i] = (cur[i] + pred) & 255
    return cur


def _unfilter(raw: bytes, height: int, stride: int, bpp: int) -> bytearray:
    out = bytearray(height * stride)
    prior = bytes(stride)
    pos = 0
    for y in range(height):
        ftype = raw[pos]
        line = raw[pos + 1:pos + 1 + stride]
        pos += 1 + stride
        if ftype == 0:
            cur: bytes | bytearray = line
        elif ftype == 1:
            cur = _unsub(line, bpp)
        elif ftype == 2:
            cur = _add_bytes(line, prior)
        elif ftype == 3:
            cur = _unavg(line, prior, bpp)
        elif ftype == 4:
            cur = _unpaeth(line, prior, bpp)
        else:
            raise PNGError(f"invalid filter type {ftype} on row {y}")
        out[y * stride:(y + 1) * stride] = cur
        prior = bytes(cur)
    return out


def _expand_palette(indices: bytearray, header: Header, stride: int, palette: bytes, trns: bytes | None) -> Image:
    entries = len(palette) // 3
    depth = header.bit_depth
    w, h = header.width, header.height
    channels = 4 if trns else 3
    lut: list[bytes] = []
    for i in range(256):
        if i < entries:
            rgb = palette[i * 3:i * 3 + 3]
            lut.append(rgb + bytes([trns[i] if trns and i < len(trns) else 255]) if trns else rgb)
        else:
            lut.append(b"")
    out = bytearray()
    per_byte = 8 // depth
    mask = (1 << depth) - 1
    for y in range(h):
        row = indices[y * stride:(y + 1) * stride]
        if depth == 8:
            idx = row[:w]
        else:
            idx = bytearray()
            for byte in row:
                for k in range(per_byte):
                    idx.append((byte >> (8 - depth * (k + 1))) & mask)
            idx = idx[:w]
        if max(idx) >= entries:
            raise PNGError("palette index out of range")
        out += b"".join(lut[i] for i in idx)
    return Image(w, h, channels, bytes(out))


def decode(raw: bytes, *, max_pixels: int = MAX_PIXELS) -> Image:
    """Decode PNG bytes into an :class:`Image` (fails closed on anything unsupported)."""
    header: Header | None = None
    palette: bytes | None = None
    trns: bytes | None = None
    idat: list[bytes] = []
    seen_iend = False
    for index, (kind, body) in enumerate(_chunks(raw)):
        if index == 0:
            if kind != b"IHDR":
                raise PNGError("first chunk must be IHDR")
            header = _parse_ihdr(body)
            continue
        if kind == b"IHDR":
            raise PNGError("duplicate IHDR")
        if kind == b"PLTE":
            if len(body) % 3 or not 3 <= len(body) <= 768:
                raise PNGError("invalid PLTE length")
            palette = body
        elif kind == b"tRNS":
            trns = body
        elif kind == b"IDAT":
            idat.append(body)
        elif kind == b"IEND":
            seen_iend = True
        elif kind[0:1].isupper():
            raise PNGError(f"unsupported critical chunk {kind!r}")
    assert header is not None
    if not seen_iend:
        raise PNGError("missing IEND")
    if header.interlace:
        raise PNGError("interlaced (Adam7) PNG is not supported")
    if header.bit_depth == 16:
        raise PNGError("16-bit PNG is not supported")
    if header.color_type == 3:
        if header.bit_depth not in (1, 2, 4, 8):
            raise PNGError("invalid palette bit depth")
        if palette is None:
            raise PNGError("palette PNG without PLTE")
        bits_per_pixel = header.bit_depth
    elif header.color_type in CHANNELS_BY_COLOR_TYPE:
        if header.bit_depth != 8:
            raise PNGError(f"only 8-bit samples are supported (got {header.bit_depth})")
        bits_per_pixel = 8 * CHANNELS_BY_COLOR_TYPE[header.color_type]
    else:
        raise PNGError(f"invalid colour type {header.color_type}")
    if header.width * header.height > max_pixels:
        raise PNGError(f"image exceeds {max_pixels} pixels")
    if not idat:
        raise PNGError("no IDAT data")
    stride = (header.width * bits_per_pixel + 7) // 8
    expected = header.height * (stride + 1)
    inflater = zlib.decompressobj()
    try:
        data = inflater.decompress(b"".join(idat), expected + 1)
    except zlib.error as exc:
        raise PNGError(f"corrupt IDAT stream: {exc}") from exc
    if len(data) < expected:
        raise PNGError("truncated image data")
    if len(data) > expected or inflater.unconsumed_tail:
        raise PNGError("image data longer than IHDR declares")
    bpp = max(1, bits_per_pixel // 8)
    pixels = _unfilter(data, header.height, stride, bpp)
    if header.color_type == 3:
        return _expand_palette(pixels, header, stride, palette or b"", trns)
    return Image(header.width, header.height, CHANNELS_BY_COLOR_TYPE[header.color_type], bytes(pixels))


def read_png(path: str | Path, *, max_bytes: int = MAX_FILE_BYTES, max_pixels: int = MAX_PIXELS) -> Image:
    p = Path(path)
    if p.stat().st_size > max_bytes:
        raise PNGError(f"PNG file exceeds {max_bytes} bytes")
    return decode(p.read_bytes(), max_pixels=max_pixels)


# --------------------------------------------------------------------------- encode

def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def filter_line(ftype: int, line: bytes, prior: bytes, bpp: int) -> bytes:
    """Apply PNG filter ``ftype`` to one raw scanline (encoder side)."""
    if ftype == 0:
        return bytes(line)
    n = len(line)
    out = bytearray(n)
    for i in range(n):
        left = line[i - bpp] if i >= bpp else 0
        up = prior[i]
        if ftype == 1:
            pred = left
        elif ftype == 2:
            pred = up
        elif ftype == 3:
            pred = (left + up) >> 1
        elif ftype == 4:
            pred = _paeth(left, up, prior[i - bpp] if i >= bpp else 0)
        else:
            raise PNGError(f"invalid filter type {ftype}")
        out[i] = (line[i] - pred) & 255
    return bytes(out)


def _chunk(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)


def encode(image: Image, *, filter_type: int | Sequence[int] = 0, level: int = 6,
           idat_chunk_size: int = 1 << 20) -> bytes:
    """Encode an 8-bit L/LA/RGB/RGBA :class:`Image` as a non-interlaced PNG.

    ``filter_type`` is one filter for every row (0-4) or a per-row sequence.
    """
    img = make_image(*image)
    stride = img.stride
    if isinstance(filter_type, int):
        filters = [filter_type] * img.height
    else:
        filters = list(filter_type)
        if len(filters) != img.height:
            raise PNGError("per-row filter list must match the image height")
    if any(f not in (0, 1, 2, 3, 4) for f in filters):
        raise PNGError("filter types must be 0-4")
    parts = []
    prior = bytes(stride)
    for y in range(img.height):
        line = img.data[y * stride:(y + 1) * stride]
        parts.append(bytes([filters[y]]) + filter_line(filters[y], line, prior, img.channels))
        prior = line
    compressed = zlib.compress(b"".join(parts), level)
    ihdr = struct.pack(">IIBBBBB", img.width, img.height, 8, COLOR_TYPE_BY_CHANNELS[img.channels], 0, 0, 0)
    out = [SIGNATURE, _chunk(b"IHDR", ihdr)]
    size = max(1, int(idat_chunk_size))
    for start in range(0, len(compressed), size):
        out.append(_chunk(b"IDAT", compressed[start:start + size]))
    out.append(_chunk(b"IEND", b""))
    return b"".join(out)


def write_png(path: str | Path, image: Image, **kwargs) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(encode(image, **kwargs))
    return p


# --------------------------------------------------------------------------- conversions

def to_rgba(image: Image) -> Image:
    img = make_image(*image)
    d = img.data
    n = img.width * img.height
    out = bytearray(n * 4)
    if img.channels == 4:
        return img
    if img.channels == 3:
        for c in range(3):
            out[c::4] = d[c::3]
        out[3::4] = b"\xff" * n
    elif img.channels == 2:
        for c in range(3):
            out[c::4] = d[0::2]
        out[3::4] = d[1::2]
    else:
        for c in range(3):
            out[c::4] = d
        out[3::4] = b"\xff" * n
    return Image(img.width, img.height, 4, bytes(out))


def to_rgb(image: Image) -> Image:
    """Drop alpha / expand grey (alpha is discarded, not composited)."""
    img = make_image(*image)
    if img.channels == 3:
        return img
    d = img.data
    n = img.width * img.height
    out = bytearray(n * 3)
    if img.channels == 4:
        for c in range(3):
            out[c::3] = d[c::4]
    else:
        grey = d[0::img.channels]
        for c in range(3):
            out[c::3] = grey
    return Image(img.width, img.height, 3, bytes(out))


def downsample(image: Image, factor: int) -> Image:
    """Box-average ``factor`` x ``factor`` blocks (edge blocks average what exists)."""
    img = make_image(*image)
    if not isinstance(factor, int) or factor < 1:
        raise PNGError("downsample factor must be a positive integer")
    if factor == 1:
        return img
    w, h, ch = img.width, img.height, img.channels
    ow, oh = -(-w // factor), -(-h // factor)
    stride = w * ch
    count_x = [min(factor, w - j * factor) for j in range(ow)]
    out = bytearray(ow * oh * ch)
    add = operator.add
    for oy in range(oh):
        y0 = oy * factor
        rows = range(y0, min(h, y0 + factor))
        n_rows = len(rows)
        for c in range(ch):
            acc = [0] * ow
            for y in rows:
                line = img.data[y * stride:(y + 1) * stride]
                for k in range(min(factor, w)):
                    samples = line[k * ch + c::factor * ch]
                    m = len(samples)
                    acc[:m] = map(add, acc[:m], samples)
            base = oy * ow * ch + c
            out[base:base + ow * ch:ch] = bytes(
                (acc[j] + (count_x[j] * n_rows) // 2) // (count_x[j] * n_rows) for j in range(ow))
    return Image(ow, oh, ch, bytes(out))


def srgb_to_linear(value: int) -> float:
    c = value / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


_LINEAR = tuple(srgb_to_linear(v) for v in range(256))


def relative_luminance(rgb: Sequence[int]) -> float:
    """WCAG 2.x relative luminance of an 8-bit sRGB colour."""
    r, g, b = rgb[:3]
    return 0.2126 * _LINEAR[r] + 0.7152 * _LINEAR[g] + 0.0722 * _LINEAR[b]


def to_luminance(image: Image) -> Grid:
    """Per-pixel sRGB relative luminance (0-1). Alpha is ignored, not composited."""
    img = make_image(*image)
    d, ch, lin = img.data, img.channels, _LINEAR
    if ch in (1, 2):
        values = array("d", (lin[v] for v in d[0::ch]))
    else:
        values = array("d", (0.2126 * lin[r] + 0.7152 * lin[g] + 0.0722 * lin[b]
                             for r, g, b in zip(d[0::ch], d[1::ch], d[2::ch])))
    return Grid(img.width, img.height, values)


def mean_luminance(image: Image) -> float:
    grid = to_luminance(image)
    return math.fsum(grid.values) / len(grid.values)


# --------------------------------------------------------------------------- heat overlay

COLORMAPS: dict[str, tuple[tuple[float, tuple[int, int, int]], ...]] = {
    # ColorBrewer YlOrRd (sequential; reads as "more = hotter").
    "heat": ((0.0, (255, 255, 178)), (0.25, (254, 204, 92)), (0.5, (253, 141, 60)),
             (0.75, (240, 59, 32)), (1.0, (189, 0, 38))),
    # Viridis anchor points (perceptually uniform, CVD-safer).
    "viridis": ((0.0, (68, 1, 84)), (0.25, (59, 82, 139)), (0.5, (33, 145, 140)),
                (0.75, (94, 201, 98)), (1.0, (253, 231, 37))),
}


def colormap_lut(name: str = "heat") -> list[tuple[int, int, int]]:
    if name not in COLORMAPS:
        raise PNGError(f"unknown colormap {name!r}")
    stops = COLORMAPS[name]
    lut = []
    for i in range(256):
        t = i / 255
        for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
            if t <= t1:
                f = 0.0 if t1 == t0 else (t - t0) / (t1 - t0)
                lut.append(tuple(round(a + (b - a) * f) for a, b in zip(c0, c1)))  # type: ignore[misc]
                break
    return lut  # type: ignore[return-value]


def _grid_values(values: Grid | Sequence[Sequence[float | None]]) -> tuple[int, int, list[float | None]]:
    if isinstance(values, Grid):
        return values.width, values.height, list(values.values)
    rows = [list(r) for r in values]
    if not rows or not rows[0] or any(len(r) != len(rows[0]) for r in rows):
        raise PNGError("heat values must be a non-empty rectangular grid")
    return len(rows[0]), len(rows), [v for r in rows for v in r]


def heat_overlay(image: Image, values: Grid | Sequence[Sequence[float | None]], *, alpha: float = 0.6,
                 colormap: str = "heat", vmin: float = 0.0, vmax: float = 1.0,
                 alpha_by_value: bool = True) -> Image:
    """Alpha-blend a colour-mapped value grid over ``image`` and return RGBA.

    The grid is stretched to the image with nearest-neighbour sampling, so it may
    be coarser than the image (e.g. one value per 8x8 CSS px). ``None``/NaN cells
    are left untouched. With ``alpha_by_value`` the overlay opacity scales with
    the normalised value, so low values stay nearly transparent.
    """
    base = to_rgba(image)
    if not 0.0 <= alpha <= 1.0 or vmax <= vmin:
        raise PNGError("alpha must be 0-1 and vmax > vmin")
    gw, gh, flat = _grid_values(values)
    lut = colormap_lut(colormap)
    cells: list[tuple[float, float, float, float] | None] = []
    for v in flat:
        if v is None or (isinstance(v, float) and math.isnan(v)):
            cells.append(None)
            continue
        t = min(1.0, max(0.0, (float(v) - vmin) / (vmax - vmin)))
        a = alpha * (t if alpha_by_value else 1.0)
        r, g, b = lut[round(t * 255)]
        cells.append((1.0 - a, r * a, g * a, b * a))
    w, h = base.width, base.height
    out = bytearray(base.data)
    col_cell = [x * gw // w for x in range(w)]
    for y in range(h):
        row_cells = cells[(y * gh // h) * gw:(y * gh // h + 1) * gw]
        i = y * w * 4
        for x in range(w):
            cell = row_cells[col_cell[x]]
            if cell is not None:
                keep, cr, cg, cb = cell
                j = i + x * 4
                out[j] = int(out[j] * keep + cr + 0.5)
                out[j + 1] = int(out[j + 1] * keep + cg + 0.5)
                out[j + 2] = int(out[j + 2] * keep + cb + 0.5)
    return Image(w, h, 4, bytes(out))


def draw_rect(image: Image, x: int, y: int, w: int, h: int, color: Sequence[int], thickness: int = 2) -> Image:
    """Outline a rectangle (pixel coordinates, clipped) in an RGBA copy of ``image``."""
    base = to_rgba(image)
    rgba = bytes((list(color) + [255])[:4])
    out = bytearray(base.data)
    iw, ih = base.width, base.height

    def fill(x0: int, y0: int, x1: int, y1: int) -> None:
        x0, y0, x1, y1 = max(0, x0), max(0, y0), min(iw, x1), min(ih, y1)
        if x0 >= x1 or y0 >= y1:
            return
        span = rgba * (x1 - x0)
        for yy in range(y0, y1):
            start = (yy * iw + x0) * 4
            out[start:start + len(span)] = span

    t = max(1, int(thickness))
    fill(x, y, x + w, y + t)
    fill(x, y + h - t, x + w, y + h)
    fill(x, y, x + t, y + h)
    fill(x + w - t, y, x + w, y + h)
    return Image(iw, ih, 4, bytes(out))
