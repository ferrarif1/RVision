#!/usr/bin/env python3
"""Generate synthetic demo assets without external dependencies.

Outputs:
- demo_data/CAR123456_demo.png
- demo_data/BOLT_MISSING_001.png
- demo_data/CAR123456_demo.mp4 (if ffmpeg is available)
"""

from __future__ import annotations

import argparse
import binascii
import os
import struct
import subprocess
import zlib
from pathlib import Path


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    length = struct.pack(">I", len(data))
    crc = struct.pack(">I", binascii.crc32(chunk_type + data) & 0xFFFFFFFF)
    return length + chunk_type + data + crc


def write_png(path: Path, width: int, height: int, rgb: bytearray) -> None:
    if len(rgb) != width * height * 3:
        raise ValueError("invalid rgb buffer length")

    raw = bytearray()
    row_size = width * 3
    for y in range(height):
        raw.append(0)
        start = y * row_size
        raw.extend(rgb[start : start + row_size])

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    idat = zlib.compress(bytes(raw), level=9)

    png = bytearray()
    png.extend(b"\x89PNG\r\n\x1a\n")
    png.extend(_png_chunk(b"IHDR", ihdr))
    png.extend(_png_chunk(b"IDAT", idat))
    png.extend(_png_chunk(b"IEND", b""))

    path.write_bytes(bytes(png))


def _set_pixel(buf: bytearray, width: int, height: int, x: int, y: int, color: tuple[int, int, int]) -> None:
    if x < 0 or y < 0 or x >= width or y >= height:
        return
    i = (y * width + x) * 3
    buf[i] = color[0]
    buf[i + 1] = color[1]
    buf[i + 2] = color[2]


def _fill_rect(
    buf: bytearray,
    width: int,
    height: int,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    color: tuple[int, int, int],
) -> None:
    x1 = max(0, min(width, x1))
    x2 = max(0, min(width, x2))
    y1 = max(0, min(height, y1))
    y2 = max(0, min(height, y2))
    for y in range(y1, y2):
        row = (y * width) * 3
        for x in range(x1, x2):
            i = row + x * 3
            buf[i] = color[0]
            buf[i + 1] = color[1]
            buf[i + 2] = color[2]


def _draw_circle(
    buf: bytearray,
    width: int,
    height: int,
    cx: int,
    cy: int,
    radius: int,
    color: tuple[int, int, int],
) -> None:
    r2 = radius * radius
    for y in range(cy - radius, cy + radius + 1):
        for x in range(cx - radius, cx + radius + 1):
            if (x - cx) * (x - cx) + (y - cy) * (y - cy) <= r2:
                _set_pixel(buf, width, height, x, y, color)


def make_car_image(path: Path, width: int = 1280, height: int = 720) -> None:
    rgb = bytearray(width * height * 3)

    # sky gradient
    for y in range(height):
        r = 30 + int(50 * y / height)
        g = 60 + int(70 * y / height)
        b = 90 + int(90 * y / height)
        for x in range(width):
            i = (y * width + x) * 3
            rgb[i] = r
            rgb[i + 1] = g
            rgb[i + 2] = b

    # ground and rails
    _fill_rect(rgb, width, height, 0, int(height * 0.72), width, height, (70, 70, 70))
    _fill_rect(rgb, width, height, 0, int(height * 0.80), width, int(height * 0.82), (120, 120, 120))
    _fill_rect(rgb, width, height, 0, int(height * 0.88), width, int(height * 0.90), (120, 120, 120))

    # wagon body
    _fill_rect(rgb, width, height, 180, 250, 1120, 520, (148, 46, 46))
    _fill_rect(rgb, width, height, 200, 270, 1100, 500, (170, 58, 58))

    # number plate area (for OCR ROI)
    _fill_rect(rgb, width, height, 430, 330, 860, 410, (235, 235, 235))

    # bolts/wheels style circles
    for cx in (300, 500, 700, 900):
        _draw_circle(rgb, width, height, cx, 560, 30, (25, 25, 25))

    write_png(path, width, height, rgb)


def make_bolt_missing_image(path: Path, width: int = 1280, height: int = 720) -> None:
    rgb = bytearray(width * height * 3)

    for y in range(height):
        for x in range(width):
            i = (y * width + x) * 3
            rgb[i] = 210
            rgb[i + 1] = 215
            rgb[i + 2] = 220

    # machine plate area without bolts (intentionally missing)
    _fill_rect(rgb, width, height, 260, 180, 1020, 560, (180, 184, 190))
    _fill_rect(rgb, width, height, 300, 220, 980, 520, (205, 208, 212))

    # some rectangular features, no circles to trigger missing alert
    _fill_rect(rgb, width, height, 360, 280, 480, 340, (160, 165, 170))
    _fill_rect(rgb, width, height, 520, 280, 640, 340, (160, 165, 170))
    _fill_rect(rgb, width, height, 680, 280, 800, 340, (160, 165, 170))

    write_png(path, width, height, rgb)


def try_make_video_from_image(image_path: Path, video_path: Path, seconds: int = 6) -> bool:
    ffmpeg = shutil_which("ffmpeg")
    if not ffmpeg:
        return False

    cmd = [
        ffmpeg,
        "-y",
        "-loop",
        "1",
        "-i",
        str(image_path),
        "-t",
        str(seconds),
        "-r",
        "12",
        "-vf",
        "scale=1280:720",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        str(video_path),
    ]

    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return True
    except subprocess.CalledProcessError:
        return False


def shutil_which(name: str) -> str | None:
    paths = os.getenv("PATH", "").split(os.pathsep)
    for p in paths:
        full = Path(p) / name
        if full.exists() and os.access(full, os.X_OK):
            return str(full)
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic demo assets")
    parser.add_argument("--output-dir", default="demo_data", help="output directory")
    args = parser.parse_args()

    out = Path(args.output_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)

    car_img = out / "CAR123456_demo.png"
    bolt_img = out / "BOLT_MISSING_001.png"
    video = out / "CAR123456_demo.mp4"

    make_car_image(car_img)
    make_bolt_missing_image(bolt_img)
    video_ok = try_make_video_from_image(car_img, video)

    print(f"[ok] image: {car_img}")
    print(f"[ok] image: {bolt_img}")
    if video_ok:
        print(f"[ok] video: {video}")
    else:
        print("[warn] ffmpeg not found or failed, video not generated")


if __name__ == "__main__":
    main()
