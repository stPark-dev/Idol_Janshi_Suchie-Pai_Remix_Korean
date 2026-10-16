import struct

import pytest

from remix import cx, rle


def _container(entries: list[bytes]) -> bytes:
    n = len(entries)
    hs = 8 + 4 * n
    offs, p = [], 0
    for e in entries:
        offs.append(p)
        p += len(e)
    return struct.pack(">IHH", hs, n, n) + struct.pack(f">{n}I", *offs) + b"".join(entries)


def _image(w: int, h: int, bpp: int, fill: int = 0x12) -> bytes:
    return bytes([w // 8, h]) + bytes([fill]) * (w * h * bpp // 8)


def test_parse_and_rebuild_identical():
    raw = _image(16, 2, 8)
    packed = cx.pack_entry(cx.KIND_BYTE, raw)
    data = _container([packed, b"\x00\x00\x00\x10\x00\x01\x00\x01" + bytes(8)])
    c = cx.Container.parse(data)
    assert len(c.entries) == 2
    assert c.build() == data


def test_unpack_entry_kinds():
    raw = _image(16, 2, 8)
    for kind in (cx.KIND_BYTE, cx.KIND_WORD):
        assert cx.unpack_entry(cx.pack_entry(kind, raw)) == raw


def test_pack_entry_pads_to_four_bytes():
    raw = bytes([2, 1]) + bytes(range(16))  # incompressible, odd stream length
    e = cx.pack_entry(cx.KIND_BYTE, raw)
    assert len(e) % 4 == 0
    assert cx.unpack_entry(e) == raw


def test_build_rejects_misaligned_entry():
    c = cx.Container.parse(_container([bytes(8)]))
    c.entries[0] = bytes(6)
    with pytest.raises(cx.CxError, match="4-byte"):
        c.build()


def test_unpack_rejects_size_mismatch():
    raw = _image(16, 2, 8)
    e = bytearray(cx.pack_entry(cx.KIND_BYTE, raw))
    e[2:4] = (len(raw) + 4).to_bytes(2, "big")
    with pytest.raises(rle.RleError):
        cx.unpack_entry(bytes(e))


def test_unpack_rejects_unknown_kind():
    with pytest.raises(cx.CxError, match="kind"):
        cx.unpack_entry(b"\x0c\x00\x00\x02\x00\x00\x00\x00")


def test_parse_rejects_bad_header():
    with pytest.raises(cx.CxError):
        cx.Container.parse(struct.pack(">IHH", 12, 2, 2) + bytes(8))


def test_image_4bpp_round_trip():
    pix = [i % 16 for i in range(16 * 3)]
    raw = cx.image_4bpp(16, 3, pix)
    assert raw[:2] == bytes([2, 3]) and len(raw) == 2 + 16 * 3 // 2
    w, h, back = cx.parse_image_4bpp(raw)
    assert (w, h, back) == (16, 3, pix)


def test_image_4bpp_rejects_bad_index_or_size():
    with pytest.raises(cx.CxError):
        cx.image_4bpp(16, 1, [16] + [0] * 15)
    with pytest.raises(cx.CxError):
        cx.image_4bpp(12, 1, [0] * 12)


def test_parse_rejects_gap_before_first_entry():
    data = struct.pack(">IHH", 12, 1, 1) + struct.pack(">I", 4) + bytes(8)
    with pytest.raises(cx.CxError, match="first entry"):
        cx.Container.parse(data)
