import struct

import numpy as np
import pytest

from remix import bank


def _bank(textures: list[tuple[int, int, int, bytes]]) -> bytes:
    """textures: (width, height, bpp, pixels-bytes)"""
    n = len(textures)
    hs = 8 + 8 * n
    head, body = b"", b""
    for w, h, bpp, px in textures:
        head += struct.pack(">HHI", w // 8, h, len(body))
        body += px
    return struct.pack(">IHH", hs, n, n) + head + body


def test_parse_and_build_round_trip():
    raw = _bank([(8, 2, 8, bytes(range(16))), (8, 2, 4, bytes(range(8)))])
    b = bank.Bank.parse(raw)
    assert [(t.width, t.height, t.bpp) for t in b.textures] == [(8, 2, 8), (8, 2, 4)]
    assert b.build() == raw


def test_get_and_set_8bpp():
    raw = _bank([(8, 2, 8, bytes(range(16)))])
    b = bank.Bank.parse(raw)
    a = b.get(0)
    assert a.shape == (2, 8) and a[1, 0] == 8
    a[1, 0] = 99
    b.set(0, a)
    assert b.build()[16 + 8] == 99


def test_get_and_set_4bpp():
    raw = _bank([(8, 2, 4, bytes([0x12, 0x34, 0x56, 0x78] * 2))])
    b = bank.Bank.parse(raw)
    a = b.get(0)
    assert list(a[0, :4]) == [1, 2, 3, 4]
    a[0, 0] = 15
    b.set(0, a)
    assert b.build()[16] == 0xF2


def test_set_rejects_shape_or_range():
    b = bank.Bank.parse(_bank([(8, 2, 4, bytes(8))]))
    with pytest.raises(bank.BankError):
        b.set(0, np.zeros((2, 16), np.uint8))
    with pytest.raises(bank.BankError):
        b.set(0, np.full((2, 8), 16, np.uint8))


def test_shared_offset_textures_are_one_storage():
    raw = struct.pack(">IHH", 24, 2, 2) + struct.pack(">HHI", 1, 2, 0) * 2 + bytes(range(16))
    b = bank.Bank.parse(raw)
    assert b.build() == raw


def test_parse_rejects_non_bank():
    with pytest.raises(bank.BankError):
        bank.Bank.parse(struct.pack(">IHH", 99, 1, 1) + bytes(8))
