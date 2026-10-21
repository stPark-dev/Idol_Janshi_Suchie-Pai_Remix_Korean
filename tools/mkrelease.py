#!/usr/bin/env python3
"""Make the distribution zip from a finished build (BPS patches only, no game data).

  python3 tools/mkrelease.py --source work/disc/remix.cue --build out/v11 --version 1.1 [--accept-pending]

Layout:
  Suchie-Pai-Remix_KR_v<ver>/README.txt                          <- docs/release/README.txt
  .../Redump/Idol Janshi Suchie-Pai Remix (Japan) (Track 1).bin.bps   Redump track 1 -> Korean track 1
  .../Redump/Idol Janshi Suchie-Pai Remix (Korean).cue               Korean track 1 + original tracks 2-6
  .../CHD/Idol Janshi Suchie-Pai Remix (Japan).bin.bps               chdman's single BIN -> Korean BIN
  .../CHD/Idol Janshi Suchie-Pai Remix (Korean).cue

The source is the single BIN that `chdman extractcd` writes; Redump track files are that BIN cut at
each track's INDEX 00 (track 1 = the first 147,518 sectors, the hash the build checks).  Only track 1
may differ.  Every patch is applied back to its source and checked against the build before zipping.
A build that is not `distribution: true` only because of pending in-game checks can be released with
--accept-pending (owner decision); development builds never.
"""
import argparse
import hashlib
import json
import re
import sys
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from remix import build as rbuild  # noqa: E402

JP = "Idol Janshi Suchie-Pai Remix (Japan)"
KO = "Idol Janshi Suchie-Pai Remix (Korean)"
SECTOR = 2352


MERGE_GAP = 16      # equal runs shorter than this stay inside a TargetRead


def _num(n: int) -> bytes:
    out = bytearray()
    while True:
        x = n & 0x7F
        n >>= 7
        if n == 0:
            out.append(0x80 | x)
            return bytes(out)
        out.append(x)
        n -= 1


def bps_create(src: bytes, tgt: bytes) -> bytes:
    """Linear BPS: SourceRead where the bytes match in place, TargetRead elsewhere."""
    n = min(len(src), len(tgt))
    a = np.frombuffer(src, np.uint8, n)
    b = np.frombuffer(tgt, np.uint8, n)
    diff = np.flatnonzero(a != b)
    runs = []                                    # [start, end) of differing bytes
    if len(diff):
        cut = np.flatnonzero(np.diff(diff) > MERGE_GAP)
        starts = np.concatenate(([diff[0]], diff[cut + 1]))
        ends = np.concatenate((diff[cut], [diff[-1]])) + 1
        runs = list(zip(starts.tolist(), ends.tolist()))
    if len(tgt) > n:
        if runs and runs[-1][1] >= n - MERGE_GAP:
            runs[-1] = (runs[-1][0], len(tgt))
        else:
            runs.append((n, len(tgt)))
    out = bytearray(b"BPS1" + _num(len(src)) + _num(len(tgt)) + _num(0))
    pos = 0
    for s, e in runs:
        if s > pos:
            out += _num(((s - pos) - 1) << 2 | 0)
        out += _num(((e - s) - 1) << 2 | 1) + tgt[s:e]
        pos = e
    if pos < len(tgt):
        out += _num(((len(tgt) - pos) - 1) << 2 | 0)
    out += (zlib.crc32(src) & 0xFFFFFFFF).to_bytes(4, "little")
    out += (zlib.crc32(tgt) & 0xFFFFFFFF).to_bytes(4, "little")
    out += (zlib.crc32(out) & 0xFFFFFFFF).to_bytes(4, "little")
    return bytes(out)


def bps_apply(patch: bytes, src: bytes) -> bytes:
    """Full BPS decoder (all four actions), used to check every patch we write."""
    assert patch[:4] == b"BPS1"
    assert zlib.crc32(patch[:-4]) & 0xFFFFFFFF == int.from_bytes(patch[-4:], "little"), "patch crc"
    p = 4

    def num():
        nonlocal p
        data, shift = 0, 1
        while True:
            x = patch[p]
            p += 1
            data += (x & 0x7F) * shift
            if x & 0x80:
                return data
            shift <<= 7
            data += shift

    ssize, tsize, msize = num(), num(), num()
    p += msize
    assert ssize == len(src), "source size"
    assert zlib.crc32(src) & 0xFFFFFFFF == int.from_bytes(patch[-12:-8], "little"), "source crc"
    out = bytearray(tsize)
    o = srel = trel = 0
    end = len(patch) - 12
    while p < end:
        d = num()
        cmd, ln = d & 3, (d >> 2) + 1
        if cmd == 0:
            out[o:o + ln] = src[o:o + ln]
        elif cmd == 1:
            out[o:o + ln] = patch[p:p + ln]
            p += ln
        else:
            v = num()
            delta = -(v >> 1) if v & 1 else v >> 1
            if cmd == 2:
                srel += delta
                out[o:o + ln] = src[srel:srel + ln]
                srel += ln
            else:
                trel += delta
                for i in range(ln):
                    out[o + i] = out[trel + i]
                trel += ln
        o += ln
    assert o == tsize, "target size"
    assert zlib.crc32(out) & 0xFFFFFFFF == int.from_bytes(patch[-8:-4], "little"), "target crc"
    return bytes(out)


def sha1(b: bytes) -> str:
    return hashlib.sha1(b).hexdigest()


@dataclass
class Track:
    number: int
    mode: str
    start: int      # sector of INDEX 00 (INDEX 01 for track 1) in the single BIN
    sectors: int
    pregap: int     # INDEX 01 - INDEX 00


def _lba(msf: str) -> int:
    m, s, f = map(int, msf.split(":"))
    return (m * 60 + s) * 75 + f


def _msf(lba: int) -> str:
    return f"{lba // 4500:02d}:{lba // 75 % 60:02d}:{lba % 75:02d}"


def split_tracks(cue: str, size: int) -> list[Track]:
    """Tracks of a single-BIN cue, cut where Redump cuts them (each file starts at INDEX 00)."""
    if len(re.findall(r"^\s*FILE\b", cue, re.M)) != 1:
        raise SystemExit("source cue must be the single BIN that chdman extractcd writes")
    raw = []
    for m in re.finditer(r"TRACK\s+(\d+)\s+(\S+)((?:\s*INDEX\s+\d+\s+[\d:]+)+)", cue):
        idx = {int(i): _lba(t) for i, t in re.findall(r"INDEX\s+(\d+)\s+([\d:]+)", m.group(3))}
        raw.append((int(m.group(1)), m.group(2), idx.get(0, idx[1]), idx[1]))
    ends = [r[2] for r in raw[1:]] + [size // SECTOR]
    return [Track(n, mode, s, e - s, i1 - s) for (n, mode, s, i1), e in zip(raw, ends)]


def redump_cue(tracks: list[Track], ko: str, jp: str) -> str:
    out = []
    for t in tracks:
        name = f"{ko if t.number == 1 else jp} (Track {t.number}).bin"
        out += [f'FILE "{name}" BINARY', f"  TRACK {t.number:02d} {t.mode}"]
        if t.pregap:
            out.append("    INDEX 00 00:00:00")
        out.append(f"    INDEX 01 {_msf(t.pregap)}")
    return "\n".join(out) + "\n"


def gate(manifest: dict, accept_pending: bool) -> list[str]:
    """Pending in-game checks that the release goes out with; exits for anything else."""
    modes = manifest.get("modes", {})
    if manifest.get("unverified") or any(modes.get(k) != "korean" for k in ("title", "opening", "graphics")):
        sys.exit("development build (unverified or original graphics) cannot be released")
    if manifest.get("distribution"):
        return []
    pending = manifest.get("screen_checks_pending", []) + manifest.get("subtitle_checks_pending", [])
    if not accept_pending:
        sys.exit(f"the build is not distribution: true (pending: {pending}); "
                 "--accept-pending only on the owner's decision")
    return pending


def _crlf(s: str) -> bytes:
    return s.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, help="single-BIN CUE (chdman extractcd) of the original disc")
    ap.add_argument("--build", required=True, help="khpatch build output")
    ap.add_argument("--version", required=True)
    ap.add_argument("--out", default=str(ROOT / "out/release"))
    ap.add_argument("--accept-pending", action="store_true",
                    help="release although in-game checks are pending (owner decision)")
    a = ap.parse_args()

    build = Path(a.build)
    manifest = json.loads((build / "manifest.json").read_text(encoding="utf-8"))
    pending = gate(manifest, a.accept_pending)
    src_cue = Path(a.source)
    src = (src_cue.parent / re.search(r'FILE\s+"([^"]+)"', src_cue.read_text()).group(1)).read_bytes()
    tracks = split_tracks(src_cue.read_text(), len(src))
    t1 = tracks[0].sectors * SECTOR
    if sha1(src[:t1]) != rbuild.TRACK1_SHA1 or sha1(src) != manifest["source_data_sha1"]:
        sys.exit("source is not the supported disc or not the build's source")
    ko = (build / manifest["data_file"]).read_bytes()
    if len(ko) != len(src) or ko[t1:] != src[t1:]:
        sys.exit("build does not match the source layout (track 1 only may differ)")
    if sha1(ko) != manifest["data_sha1"]:
        sys.exit("build data does not match its manifest")

    name = f"Suchie-Pai-Remix_KR_v{a.version}"
    top = Path(a.out) / name
    (top / "Redump").mkdir(parents=True, exist_ok=True)
    (top / "CHD").mkdir(exist_ok=True)
    (top / "README.txt").write_bytes(_crlf((ROOT / "docs/release/README.txt").read_text(encoding="utf-8")))

    redump = bps_create(src[:t1], ko[:t1])
    assert bps_apply(redump, src[:t1]) == ko[:t1]
    (top / f"Redump/{JP} (Track 1).bin.bps").write_bytes(redump)
    (top / f"Redump/{KO}.cue").write_bytes(_crlf(redump_cue(tracks, KO, JP)))

    chd = bps_create(src, ko)
    assert bps_apply(chd, src) == ko
    (top / f"CHD/{JP}.bin.bps").write_bytes(chd)
    cue = (build / manifest["cue"]).read_text().replace(f'"{manifest["data_file"]}"', f'"{KO}.bin"')
    (top / f"CHD/{KO}.cue").write_bytes(_crlf(cue))

    zpath = Path(a.out) / f"{name}.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in sorted(top.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(top.parent).as_posix())
    for t in tracks:
        part = src[t.start * SECTOR:(t.start + t.sectors) * SECTOR]
        print(f"Track {t.number}  {len(part):,} bytes  SHA-1 {sha1(part)}")
    print(f"source BIN      {len(src):,} bytes  SHA-1 {sha1(src)}")
    print(f"Korean track 1  SHA-1 {sha1(ko[:t1])}")
    print(f"Korean BIN      SHA-1 {sha1(ko)}")
    print(f"Redump patch    {len(redump):,} bytes, CHD patch {len(chd):,} bytes")
    if pending:
        print(f"released with pending checks (owner decision): {', '.join(pending)}")
    print(f"{zpath}  {zpath.stat().st_size:,} bytes  SHA-1 {sha1(zpath.read_bytes())}")


if __name__ == "__main__":
    main()
