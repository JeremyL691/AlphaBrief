"""Generate the AlphaBrief application icon from simple geometry.

Draws a rounded square with three candlesticks (the product domain) using
only the Python standard library, then emits the PNG sizes needed for an
``iconutil`` iconset plus a small tray PNG. No third-party trademarks or
assets; run ``iconutil -c icns`` afterwards to produce ``icon.icns``
(macOS only, same as the release build).
"""

from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

SIZE = 1024

# Soft-palette colours on the deep navy canvas (RGB).
CANVAS = (11, 17, 32, 255)
CANVAS_BORDER = (32, 48, 82, 255)
UP = (52, 168, 112, 255)
DOWN = (224, 100, 100, 255)
WICK = (148, 170, 205, 255)


def _rounded_rect_mask(size: int, radius: int) -> list[list[bool]]:
    inside = [[False] * size for _ in range(size)]
    r2 = radius * radius
    for y in range(size):
        for x in range(size):
            # Corner-centre distance test for the four rounded corners.
            cx = min(max(x, radius), size - 1 - radius)
            cy = min(max(y, radius), size - 1 - radius)
            inside[y][x] = (x - cx) ** 2 + (y - cy) ** 2 <= r2
    return inside


def _fill_rect(
    buf: list[list[tuple[int, int, int, int]]],
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    colour: tuple[int, int, int, int],
) -> None:
    for y in range(max(0, y0), min(SIZE, y1)):
        row = buf[y]
        for x in range(max(0, x0), min(SIZE, x1)):
            row[x] = colour


def _candle(
    buf: list[list[tuple[int, int, int, int]]],
    centre_x: int,
    body_top: int,
    body_bottom: int,
    wick_top: int,
    wick_bottom: int,
    width: int,
    body: tuple[int, int, int, int],
) -> None:
    half = width // 2
    _fill_rect(
        buf, centre_x - 3, wick_top, centre_x + 4, wick_bottom + 1, WICK
    )
    _fill_rect(
        buf,
        centre_x - half,
        body_top,
        centre_x + half + 1,
        body_bottom + 1,
        body,
    )


def draw() -> list[list[tuple[int, int, int, int]]]:
    mask = _rounded_rect_mask(SIZE, 220)
    buf: list[list[tuple[int, int, int, int]]] = [
        [CANVAS if mask[y][x] else (0, 0, 0, 0) for x in range(SIZE)]
        for y in range(SIZE)
    ]
    # Border ring for a soft edge.
    inner = _rounded_rect_mask(SIZE - 24, 208)
    for y in range(SIZE):
        for x in range(SIZE):
            within = 12 <= x < SIZE - 12 and 12 <= y < SIZE - 12
            if mask[y][x] and not (within and inner[y - 12][x - 12]):
                buf[y][x] = CANVAS_BORDER

    # Three candles: down, up, up (left to right), centred vertically.
    _candle(buf, 320, 430, 640, 330, 740, 120, DOWN)
    _candle(buf, 512, 350, 590, 250, 700, 120, UP)
    _candle(buf, 704, 380, 620, 300, 780, 120, UP)
    return buf


def png_bytes(buf: list[list[tuple[int, int, int, int]]], size: int) -> bytes:
    raw = bytearray()
    step = SIZE // size
    for y in range(0, SIZE, step):
        raw.append(0)  # filter: none
        for x in range(0, SIZE, step):
            r, g, b, a = buf[y][x]
            raw += bytes((r, g, b, a))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


def main() -> int:
    out_dir = Path(__file__).resolve().parent
    iconset = out_dir / "alphabrief.iconset"
    iconset.mkdir(parents=True, exist_ok=True)
    buf = draw()
    sizes = (16, 32, 64, 128, 256, 512, 1024)
    for size in sizes:
        name = f"icon_{size}x{size}.png"
        if size == 1024:
            name = "icon_512x512@2x.png"
        (iconset / name).write_bytes(png_bytes(buf, size))
        # Retina pairs.
        if size in (16, 32, 128, 256, 512):
            retina = f"icon_{size}x{size}@2x.png"
            (iconset / retina).write_bytes(png_bytes(buf, size * 2))
    # Tray icon (template-style 32px).
    (out_dir / "icon-tray.png").write_bytes(png_bytes(buf, 32))
    print(f"iconset written to {iconset}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
