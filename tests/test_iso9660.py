import struct

import pytest

from remix import iso9660


def _rec(name: bytes, lba: int, size: int, flags: int = 0) -> bytes:
    ln = 33 + len(name) + (1 - len(name) % 2)
    r = bytearray(ln)
    r[0] = ln
    r[2:10] = struct.pack("<I", lba) + struct.pack(">I", lba)
    r[10:18] = struct.pack("<I", size) + struct.pack(">I", size)
    r[25] = flags
    r[32] = len(name)
    r[33:33 + len(name)] = name
    return bytes(r)


def _image() -> dict[int, bytes]:
    sectors = {}
    pvd = bytearray(2048)
    pvd[0:6] = b"\x01CD001"
    pvd[156:190] = _rec(b"\x00", 20, 2048, 2)
    sectors[16] = bytes(pvd)
    root = _rec(b"\x00", 20, 2048, 2) + _rec(b"\x01", 20, 2048, 2) + _rec(b"A;1", 30, 5000) + _rec(b"SUB", 21, 2048, 2)
    sectors[20] = root.ljust(2048, b"\0")
    sub = _rec(b"\x00", 21, 2048, 2) + _rec(b"\x01", 20, 2048, 2) + _rec(b"X.CX;1", 40, 100)
    sectors[21] = sub.ljust(2048, b"\0")
    return sectors


def test_find_root_and_subdirectory():
    img = _image()
    a = iso9660.find(img.__getitem__, "A")
    assert (a.lba, a.size) == (30, 5000)
    x = iso9660.find(img.__getitem__, "SUB/X.CX")
    assert (x.lba, x.size, x.dir_lba) == (40, 100, 21)
    assert img[21][x.rec_offset + 33:x.rec_offset + 39] == b"X.CX;1"


def test_find_missing_raises():
    img = _image()
    with pytest.raises(iso9660.IsoError):
        iso9660.find(img.__getitem__, "SUB/NOPE")
    with pytest.raises(iso9660.IsoError):
        iso9660.find(img.__getitem__, "NOPE/X.CX")


def test_with_size_patches_both_endian_fields_only():
    img = _image()
    x = iso9660.find(img.__getitem__, "SUB/X.CX")
    new = iso9660.with_size(img[21], x, 96)
    off = x.rec_offset
    assert struct.unpack("<I", new[off + 10:off + 14])[0] == 96
    assert struct.unpack(">I", new[off + 14:off + 18])[0] == 96
    diff = [i for i in range(2048) if new[i] != img[21][i]]
    assert all(off + 10 <= i < off + 18 for i in diff)


def test_with_size_rejects_stale_record():
    img = _image()
    x = iso9660.find(img.__getitem__, "SUB/X.CX")
    bad = bytearray(img[21])
    bad[x.rec_offset + 10] ^= 1
    with pytest.raises(iso9660.IsoError):
        iso9660.with_size(bytes(bad), x, 96)


def test_find_a_directory_only_when_asked():
    img = _image()
    d = iso9660.find(img.__getitem__, "SUB", directory=True)
    assert (d.lba, d.size) == (21, 2048)
    with pytest.raises(iso9660.IsoError):
        iso9660.find(img.__getitem__, "SUB")                  # a file is expected by default
    with pytest.raises(iso9660.IsoError):
        iso9660.find(img.__getitem__, "A", directory=True)
