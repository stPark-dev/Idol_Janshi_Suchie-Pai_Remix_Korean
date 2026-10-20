"""CX container (docs/initial-survey.md 2.2).

Container: u32 header size (8 + 4 * count), u16 count, u16 count, u32 offsets[count] relative
to the header end. Every entry starts on a 4-byte boundary (all original files; a misaligned
entry froze the opening, survey 3.7).
Compressed entry: u16 kind, u16 unpacked size, RLE stream (rle.py), padded to 4 bytes.
Single image (one kind of unpacked payload): u8 width / 8, u8 height, pixels.
"""
import struct
from dataclasses import dataclass, field

from . import rle

KIND_BYTE = 0x0000
KIND_WORD = 0x0400
_UNIT = {KIND_BYTE: rle.BYTE, KIND_WORD: rle.WORD}


class CxError(ValueError):
    pass


@dataclass
class Container:
    entries: list[bytes] = field(default_factory=list)

    @classmethod
    def parse(cls, data: bytes) -> "Container":
        if len(data) < 8:
            raise CxError("shorter than the container header")
        hs, n, n2 = struct.unpack(">IHH", data[:8])
        if n != n2 or hs != 8 + 4 * n or hs > len(data):
            raise CxError(f"bad container header (size {hs}, count {n}/{n2})")
        offs = list(struct.unpack(f">{n}I", data[8:hs])) + [len(data) - hs]
        if offs != sorted(offs):
            raise CxError("entry offsets are not ascending")
        if offs[0] != 0:
            raise CxError("bytes between the header and the first entry")
        return cls([data[hs + offs[i]:hs + offs[i + 1]] for i in range(n)])

    def build(self) -> bytes:
        offs, p = [], 0
        for i, e in enumerate(self.entries):
            if len(e) % 4:
                raise CxError(f"entry {i} is not a multiple of 4 bytes (4-byte alignment)")
            offs.append(p)
            p += len(e)
        n = len(self.entries)
        return struct.pack(">IHH", 8 + 4 * n, n, n) + struct.pack(f">{n}I", *offs) + b"".join(self.entries)


def unpack_entry(entry: bytes) -> bytes:
    kind, size = struct.unpack(">HH", entry[:4])
    if kind not in _UNIT:
        raise CxError(f"unknown entry kind {kind:#06x}")
    return rle.decode(entry[4:], _UNIT[kind], size)


def pack_entry(kind: int, data: bytes, optimal: bool = False) -> bytes:
    if kind not in _UNIT:
        raise CxError(f"unknown entry kind {kind:#06x}")
    if len(data) > 0xFFFF:
        raise CxError("unpacked size does not fit the 16-bit size field")
    enc = rle.encode_optimal if optimal else rle.encode
    e = struct.pack(">HH", kind, len(data)) + enc(data, _UNIT[kind])
    return e + bytes(-len(e) % 4)


def image_4bpp(width: int, height: int, pixels: list[int]) -> bytes:
    if width % 8 or not 0 < width <= 2040 or not 0 < height <= 255:
        raise CxError(f"image size {width}x{height} cannot be stored")
    if len(pixels) != width * height:
        raise CxError("pixel count does not match the size")
    if any(not 0 <= v < 16 for v in pixels):
        raise CxError("4bpp pixel index out of range")
    body = bytes((pixels[i] << 4) | pixels[i + 1] for i in range(0, len(pixels), 2))
    return bytes([width // 8, height]) + body


def parse_image_4bpp(raw: bytes) -> tuple[int, int, list[int]]:
    w, h = raw[0] * 8, raw[1]
    if len(raw) != 2 + w * h // 2:
        raise CxError("not a 4bpp single image")
    return w, h, [v for b in raw[2:] for v in (b >> 4, b & 15)]
