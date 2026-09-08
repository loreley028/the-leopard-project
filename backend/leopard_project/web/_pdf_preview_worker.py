"""One-shot, single-threaded PDFium owner. Only stdout carries the result."""
from __future__ import annotations

import json
import math
import struct
import sys
import zlib


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def _pdf_bitmap_png(bitmap) -> bytes:
    mode = bitmap.mode
    source_channels = bitmap.n_channels
    if mode not in {"BGR", "BGRA", "BGRX", "RGB", "RGBA"}:
        raise ValueError("Unsupported PDF preview bitmap mode")
    alpha = mode in {"BGRA", "RGBA"}
    raw = bytes(bitmap.buffer)
    scanlines = bytearray()
    for row_index in range(bitmap.height):
        row = raw[row_index * bitmap.stride : row_index * bitmap.stride + bitmap.width * source_channels]
        scanlines.append(0)
        for offset in range(0, len(row), source_channels):
            pixel = row[offset : offset + source_channels]
            scanlines.extend((pixel[2], pixel[1], pixel[0]) if mode.startswith("BGR") else pixel[:3])
            if alpha:
                scanlines.append(pixel[3])
    header = struct.pack(">IIBBBBB", bitmap.width, bitmap.height, 8, 6 if alpha else 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", header) + _png_chunk(b"IDAT", zlib.compress(bytes(scanlines), 6)) + _png_chunk(b"IEND", b"")


def main() -> int:
    # Bound an external binary input before importing/loading native code.
    if sys.platform == "linux":
        import resource
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
    from pypdfium2 import PdfDocument

    with PdfDocument(sys.argv[1]) as document:
        if sys.argv[2] == "info":
            sys.stdout.buffer.write(json.dumps({"page_count": len(document)}).encode())
            return 0
        number = int(sys.argv[2])
        if not 1 <= number <= len(document):
            return 4
        page = document[number - 1]
        try:
            width, height = page.get_size()
            if not all(math.isfinite(n) and n > 0 for n in (width, height)) or math.ceil(width * 1.6) * math.ceil(height * 1.6) > 16_000_000:
                raise ValueError("PDF page exceeds preview pixel limit")
            bitmap = page.render(scale=1.6)
            try:
                png = _pdf_bitmap_png(bitmap)
            finally:
                bitmap.close()
        finally:
            page.close()
    sys.stdout.buffer.write(png)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        # Python errors and native signals both become a failed worker contract.
        raise SystemExit(2)
