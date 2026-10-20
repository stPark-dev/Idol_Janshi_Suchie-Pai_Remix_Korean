"""Sprite bank (docs/initial-survey.md 2.1): textures replaced in place, same size and depth.

u32 header size (8 + 8 * count), u16 count, u16 count, then per texture u16 width / 8, u16 height,
u32 offset (from the header end). Texture depth is 8bpp when its storage holds width * height bytes,
4bpp otherwise. Several entries may share one offset.
"""
import struct
from dataclasses import dataclass

import numpy as np


class BankError(ValueError):
    pass


@dataclass(frozen=True)
class Texture:
    width: int
    height: int
    offset: int     # from the header end
    bpp: int

    @property
    def nbytes(self) -> int:
        return self.width * self.height * self.bpp // 8


class Bank:
    def __init__(self, raw: bytes, header: int, textures: list[Texture]):
        self._raw = bytearray(raw)
        self.header = header
        self.textures = textures

    @classmethod
    def parse(cls, raw: bytes) -> "Bank":
        if len(raw) < 8:
            raise BankError("shorter than a bank header")
        hs, n, n2 = struct.unpack(">IHH", raw[:8])
        if n != n2 or n == 0 or hs != 8 + 8 * n or hs > len(raw):
            raise BankError("not a sprite bank")
        ents = [struct.unpack(">HHI", raw[8 + 8 * i:16 + 8 * i]) for i in range(n)]
        ends = sorted({o for _, _, o in ents} | {len(raw) - hs})
        tex = []
        for w8, h, o in ents:
            nxt = next(e for e in ends if e > o) if o < len(raw) - hs else o
            size = nxt - o
            w = w8 * 8
            bpp = 8 if size >= w * h else 4
            if w * h * bpp // 8 > size and w * h:
                raise BankError(f"texture at {o:#x} ({w}x{h}) does not fit its storage")
            tex.append(Texture(w, h, o, bpp))
        return cls(raw, hs, tex)

    def get(self, i: int) -> np.ndarray:
        t = self.textures[i]
        data = np.frombuffer(bytes(self._raw[self.header + t.offset:self.header + t.offset + t.nbytes]), np.uint8)
        if t.bpp == 4:
            data = np.stack([data >> 4, data & 15], axis=1).ravel()
        return data.reshape(t.height, t.width).copy()

    def set(self, i: int, pixels: np.ndarray) -> None:
        t = self.textures[i]
        if pixels.shape != (t.height, t.width):
            raise BankError(f"texture {i} is {t.width}x{t.height}, not {pixels.shape[1]}x{pixels.shape[0]}")
        if pixels.min() < 0 or pixels.max() >= (1 << t.bpp):
            raise BankError(f"texture {i}: pixel index out of range for {t.bpp}bpp")
        flat = pixels.astype(np.uint8).ravel()
        if t.bpp == 4:
            flat = (flat[0::2] << 4) | flat[1::2]
        self._raw[self.header + t.offset:self.header + t.offset + t.nbytes] = flat.tobytes()

    def build(self) -> bytes:
        return bytes(self._raw)
