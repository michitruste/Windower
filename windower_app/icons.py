"""
Pixel helpers for window icons (no OS / GUI dependencies).

Tk 8.6 reads PNG natively, so icons are turned into tiny PNGs with zlib and
struct instead of needing Pillow.
"""
from __future__ import annotations

import struct
import zlib


def rgba_from_black_white(on_black: bytes, on_white: bytes) -> bytes:
    """Recover RGBA from the same icon drawn once on black and once on white (BGRA pixels).

    Where the icon is opaque both drawings match; where it is transparent they differ by
    the full 255. This works for every icon kind (32-bit alpha or old AND/XOR masks).
    """
    out = bytearray(len(on_black))
    for i in range(0, len(on_black), 4):
        diff = (on_white[i] - on_black[i] + on_white[i + 1] - on_black[i + 1]
                + on_white[i + 2] - on_black[i + 2])
        a = 255 - max(0, min(255, round(diff / 3)))
        if a == 0:
            continue
        out[i] = min(255, on_black[i + 2] * 255 // a)       # R (undo the blend with black)
        out[i + 1] = min(255, on_black[i + 1] * 255 // a)   # G
        out[i + 2] = min(255, on_black[i] * 255 // a)       # B
        out[i + 3] = a
    return bytes(out)


def png_bytes(w: int, h: int, rgba: bytes) -> bytes:
    """Encode w x h RGBA pixels as a PNG file."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    stride = w * 4
    raw = b"".join(b"\x00" + rgba[y * stride:(y + 1) * stride] for y in range(h))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))


def disc_icon(size: int, rgb: tuple[int, int, int]) -> bytes:
    """A smooth filled circle as RGBA pixels (placeholder icons for the demo backend)."""
    out = bytearray(size * size * 4)
    c = (size - 1) / 2
    radius = size / 2 - 0.5
    for y in range(size):
        for x in range(size):
            d = ((x - c) ** 2 + (y - c) ** 2) ** 0.5
            a = max(0.0, min(1.0, radius - d + 0.5))
            if a:
                i = (y * size + x) * 4
                out[i:i + 4] = bytes((*rgb, round(a * 255)))
    return bytes(out)
