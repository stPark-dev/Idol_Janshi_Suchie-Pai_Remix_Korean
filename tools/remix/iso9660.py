"""ISO 9660 lookup with subdirectories, and in-place size updates of a directory record."""
import struct
from dataclasses import dataclass
from typing import Callable

ReadUser = Callable[[int], bytes]   # lba -> 2048 bytes of user data


class IsoError(ValueError):
    pass


@dataclass(frozen=True)
class Record:
    lba: int
    size: int
    dir_lba: int       # sector holding the directory record
    rec_offset: int    # offset of the record inside that sector


def _records(read: ReadUser, lba: int, size: int):
    for k in range((size + 2047) // 2048):
        sec = read(lba + k)
        p = 0
        while p < 2048 and sec[p]:
            ln = sec[p]
            yield lba + k, p, sec[p:p + ln]
            p += ln


def find(read: ReadUser, path: str, directory: bool = False) -> Record:
    """A file, or with directory=True a directory, by its path."""
    pvd = read(16)
    if pvd[:6] != b"\x01CD001":
        raise IsoError("no primary volume descriptor at LBA 16")
    root = pvd[156:190]
    lba, size = struct.unpack("<I", root[2:6])[0], struct.unpack("<I", root[10:14])[0]
    parts = path.split("/")
    for depth, part in enumerate(parts):
        last = depth == len(parts) - 1
        for dl, off, rec in _records(read, lba, size):
            nm = rec[33:33 + rec[32]]
            if nm in (b"\x00", b"\x01"):
                continue
            is_dir = bool(rec[25] & 2)
            if nm.decode("latin1").split(";")[0] == part and is_dir == (directory or not last):
                lba, size = struct.unpack("<I", rec[2:6])[0], struct.unpack("<I", rec[10:14])[0]
                if last:
                    return Record(lba, size, dl, off)
                break
        else:
            raise IsoError(f"{path}: {part} not found")
    raise IsoError(f"{path}: empty path")


def with_size(sector: bytes, rec: Record, new_size: int) -> bytes:
    """Return the directory sector with the record's both-endian size fields set to new_size."""
    o = rec.rec_offset
    if struct.unpack("<I", sector[o + 2:o + 6])[0] != rec.lba or \
            struct.unpack("<I", sector[o + 10:o + 14])[0] != rec.size or \
            struct.unpack(">I", sector[o + 14:o + 18])[0] != rec.size:
        raise IsoError("directory record does not match the lookup")
    s = bytearray(sector)
    s[o + 10:o + 18] = struct.pack("<I", new_size) + struct.pack(">I", new_size)
    return bytes(s)
