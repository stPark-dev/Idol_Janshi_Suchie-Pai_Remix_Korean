"""Product build: verified source disc -> Korean disc (BIN/CUE) + manifest.json.

Every change is a whole-sector write registered in a WritePlan with the original raw sector as
the expected source bytes (docs/initial-survey.md 1, 3.6, 3.7).
"""
import hashlib
import json
import re
import struct
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

import numpy as np

from . import bigletters, cdsector, cx, iso9660, logo
from .writeplan import WritePlan

ROOT = Path(__file__).resolve().parents[2]

TRACK1_SECTORS = 147518
TRACK1_SHA1 = "ac800da596c31d478989e9dac309198ddf527143"
RAW = cdsector.RAW
CX_FILES = ("TITL_CG.CX", "SELECT.CX", "BADGRAPH.CX", "GAMEDRV/MJCG.CX", "GOODEND/GOODEND.CX")

# TITL_CG.CX: single 4bpp images, byte RLE (survey 3.4, 3.7).
TITLE_FILE = "TITL_CG.CX"
TITLE_SHA1 = "39ead2b63eaff305a8c4a771e7b02a79f67153ff"
# Results checked on screen, per (title, opening) mode (Pillow 9.4, NanumSquareRound EB).
TITL_CG_SHA1 = {
    ("korean", "original"): "ebd598109d6b173057c590f4d67505553b51c458",   # survey 3.7
    ("korean", "korean"): "32a3c708f9d1c7e0b92ce8b055fb142c39b5cbcb",     # survey 3.8
}
# Title logo: palette CRAM 0x200-0x20F shared by both pieces.
LOGO_CELLS = {104: (120, 21), 105: (256, 87)}
LOGO_SOURCES = {104: ROOT / "logo_idoljanshi_120x21_ko.png", 105: ROOT / "logo_suchiepai_256x87_ko.png"}
LOGO_PALETTE = {   # colours the original logo pieces use (RGB555 expanded), index 1 and 8 left alone
    2: (144, 0, 24), 3: (232, 72, 0), 4: (248, 200, 0), 5: (248, 224, 112), 6: (168, 120, 144),
    7: (216, 176, 200), 9: (72, 0, 48), 10: (184, 32, 128), 11: (240, 32, 168), 12: (248, 96, 192),
    13: (248, 152, 216), 14: (248, 200, 232), 15: (248, 248, 248),
}


# Opening big letters (survey 3.8): scroll row #5-#10 (bevel style), art flashes #11-#16.
SCROLL_LETTERS = {5: "아", 6: "이", 7: "돌", 8: "작", 9: "사", 10: ""}   # 10 (士) left empty
ART_LETTERS = {11: "스", 13: "치", 15: "파", 16: "이"}                # 12, 14 (ー) kept
SCROLL_BOLD, SCROLL_MARGIN = 3, 3
ART_BOLD, ART_MARGIN = 6, 2


class BuildError(RuntimeError):
    pass


def is_raw_bank(e: bytes) -> bool:
    if len(e) < 8:
        return False
    hs, n, n2 = struct.unpack(">IHH", e[:8])
    return n == n2 and n > 0 and hs == 8 + 8 * n


def _sha1_file_prefix(path: Path, nbytes: int) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        left = nbytes
        while left:
            chunk = f.read(min(1 << 22, left))
            if not chunk:
                raise BuildError(f"{path} is shorter than track 1")
            h.update(chunk)
            left -= len(chunk)
    return h.hexdigest()


def _sha1_file(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


_TRACK1 = re.compile(r'FILE\s+"([^"]+)"\s+BINARY\s+TRACK\s+01\s+MODE1/2352\s+INDEX\s+01\s+00:00:00')
_FILE = re.compile(r'FILE\s+"([^"]+)"')


def parse_cue(text: str, cue_dir: Path) -> tuple[re.Match, Path]:
    m = _TRACK1.search(text)
    if not m:
        raise BuildError("track 1 must be MODE1/2352 at the start of its FILE")
    return m, cue_dir / m.group(1)


def rewrite_cue(text: str, cue_dir: Path, data_name: str) -> str:
    """Point track 1 at data_name (the exact FILE token that was parsed); other FILEs absolute."""
    m, _ = parse_cue(text, cue_dir)
    a, b = m.span(1)
    head, tail = text[:a], text[b:]
    fix = lambda t: _FILE.sub(lambda f: f'FILE "{(cue_dir / f.group(1)).resolve()}"', t)
    out = fix(head) + data_name + fix(tail)
    if parse_cue(out, cue_dir)[0].group(1) != data_name:
        raise BuildError("cue rewrite did not point track 1 at the output")
    return out


def check_output_paths(cue: Path, data: Path, out: Path, name: str) -> None:
    for new, old in ((out / (name + ".bin"), data), (out / (name + ".cue"), cue)):
        if new.resolve() == Path(old).resolve():
            raise BuildError(f"output {new} would overwrite the source")


class DirPatch:
    """Size patches grouped per directory sector, so several files in one directory merge."""

    def __init__(self) -> None:
        self._cur: dict[int, bytes] = {}

    def add(self, lba: int, rec_offset: int, user: bytes, patch) -> None:
        self._cur[lba] = patch(self._cur.get(lba, user))

    def sectors(self) -> dict[int, bytes]:
        return dict(self._cur)


@dataclass
class SourceDisc:
    cue: Path
    data: Path          # file holding track 1 at offset 0
    cue_text: str
    track1_sha1: str | None

    @classmethod
    def open(cls, cue: Path, check_hash: bool = True) -> "SourceDisc":
        cue = Path(cue)
        text = cue.read_text()
        try:
            _, data = parse_cue(text, cue.parent)
        except BuildError as e:
            raise BuildError(f"{cue}: {e}") from None
        sha = None
        if check_hash:
            sha = _sha1_file_prefix(data, TRACK1_SECTORS * RAW)
            if sha != TRACK1_SHA1:
                raise BuildError(f"{data}: track 1 SHA-1 {sha} is not the supported original {TRACK1_SHA1}")
        return cls(cue, data, text, sha)

    def raw_sector(self, lba: int) -> bytes:
        with open(self.data, "rb") as f:
            f.seek(lba * RAW)
            s = f.read(RAW)
        if len(s) != RAW:
            raise BuildError(f"sector {lba} outside the data file")
        return s

    def user(self, lba: int) -> bytes:
        return self.raw_sector(lba)[16:16 + 2048]

    def lookup(self, path: str) -> iso9660.Record:
        return iso9660.find(self.user, path)

    def read_file(self, path: str) -> bytes:
        r = self.lookup(path)
        return b"".join(self.user(r.lba + i) for i in range((r.size + 2047) // 2048))[:r.size]


def _plan_file(plan: WritePlan, disc: SourceDisc, path: str, new: bytes, writer: str, dirs: DirPatch) -> dict:
    """Rewrite a file in place (within its allocated sectors) and its directory size if needed."""
    r = disc.lookup(path)
    nsec = (r.size + 2047) // 2048
    if len(new) > nsec * 2048:
        raise BuildError(f"{path}: {len(new)} bytes do not fit its {nsec} sectors (relocation not supported)")
    padded = new + bytes(nsec * 2048 - len(new))
    old_padded = b"".join(disc.user(r.lba + i) for i in range(nsec))
    sectors = 0
    for i in range(nsec):
        part = padded[i * 2048:(i + 1) * 2048]
        if part == old_padded[i * 2048:(i + 1) * 2048]:
            continue
        orig = disc.raw_sector(r.lba + i)
        sec = bytearray(orig)
        sec[16:16 + 2048] = part
        cdsector.fix_mode1(sec)
        plan.add(writer, (r.lba + i) * RAW, orig, bytes(sec))
        sectors += 1
    if len(new) != r.size:
        dirs.add(r.dir_lba, r.rec_offset, disc.user(r.dir_lba), lambda u: iso9660.with_size(u, r, len(new)))
    return {"writer": writer, "file": path, "size": [r.size, len(new)], "sectors": sectors}


def _cell(c: cx.Container, idx: int) -> np.ndarray:
    w, h, px = cx.parse_image_4bpp(cx.unpack_entry(c.entries[idx]))
    return np.array(px, np.uint8).reshape(h, w)


def _put(c: cx.Container, idx: int, a: np.ndarray) -> None:
    h, w = a.shape
    c.entries[idx] = cx.pack_entry(cx.KIND_BYTE, cx.image_4bpp(w, h, [int(v) for v in a.ravel()]))


def _logo(c: cx.Container) -> None:
    for idx, (w, h) in LOGO_CELLS.items():
        if _cell(c, idx).shape != (h, w):
            raise BuildError(f"{TITLE_FILE} #{idx}: not the expected {w}x{h} 4bpp logo cell")
        with Image.open(LOGO_SOURCES[idx]) as src:
            pixels = logo.quantize(logo.fit(src, w, h), LOGO_PALETTE)
        _put(c, idx, np.array(pixels, np.uint8).reshape(h, w))


def _scroll_size(c: cx.Container) -> int:
    """One font size for the whole scroll row: the largest that fits every cell."""
    cells = [(ch, _cell(c, i).shape) for i, ch in SCROLL_LETTERS.items() if ch]
    size = 8
    while all(bigletters._render(ch, size + 1, SCROLL_BOLD).shape[1] <= w - 2 * SCROLL_MARGIN and
              bigletters._render(ch, size + 1, SCROLL_BOLD).shape[0] <= h - 2 * SCROLL_MARGIN
              for ch, (h, w) in cells):
        size += 1
    return size


def _opening(c: cx.Container) -> None:
    size = _scroll_size(c)
    for idx, ch in SCROLL_LETTERS.items():
        h, w = _cell(c, idx).shape
        if not ch:
            _put(c, idx, np.zeros((h, w), np.uint8))
            continue
        _put(c, idx, bigletters.bevel(bigletters.glyph_mask(ch, w, h, size, SCROLL_MARGIN, SCROLL_BOLD)))
    for idx, ch in ART_LETTERS.items():
        art = _cell(c, idx)
        h, w = art.shape
        _put(c, idx, bigletters.art_fill(art, bigletters.glyph_mask(ch, w, h, None, ART_MARGIN, ART_BOLD)))


def title_cg(original: bytes, title: str, opening: str, unverified: bool = False) -> bytes:
    if hashlib.sha1(original).hexdigest() != TITLE_SHA1:
        raise BuildError(f"{TITLE_FILE}: content is not the original")
    c = cx.Container.parse(original)
    if title == "korean":
        _logo(c)
    if opening == "korean":
        _opening(c)
    new = c.build()
    got = hashlib.sha1(new).hexdigest()
    want = TITL_CG_SHA1.get((title, opening))
    if want is None and not unverified:
        raise BuildError(f"{TITLE_FILE}: title={title} opening={opening} has not been verified on screen "
                         "(build with unverified=True / --unverified for a test disc)")
    if want is not None and got != want:
        raise BuildError(f"{TITLE_FILE}: result {got} differs from the verified {want} "
                         "(source PNG, font or Pillow changed; re-verify on screen before updating)")
    return new


def build(source: Path, out: Path, title: str = "korean", opening: str = "korean",
          unverified: bool = False, name: str = "remix_ko") -> dict:
    disc = SourceDisc.open(Path(source))
    out = Path(out)
    check_output_paths(disc.cue, disc.data, out, name)
    out.mkdir(parents=True, exist_ok=True)
    dirs = DirPatch()
    protected = [(TRACK1_SECTORS * RAW, disc.data.stat().st_size)]
    plan = WritePlan(disc.data, protected=protected)
    changes = []
    for mode in (title, opening):
        if mode not in ("korean", "original"):
            raise BuildError(f"unknown mode {mode}")
    if "korean" in (title, opening):
        new = title_cg(disc.read_file(TITLE_FILE), title, opening, unverified)
        changes.append(_plan_file(plan, disc, TITLE_FILE, new, "title_cg", dirs))
    for lba, user in dirs.sectors().items():
        orig = disc.raw_sector(lba)
        sec = bytearray(orig)
        sec[16:16 + 2048] = user
        cdsector.fix_mode1(sec)
        plan.add("iso_directory", lba * RAW, orig, bytes(sec))
    data_name = name + ".bin"
    plan.apply(out / data_name)
    (out / (name + ".cue")).write_text(rewrite_cue(disc.cue_text, disc.cue.parent, data_name))
    manifest = {
        "source_cue": str(disc.cue), "source_track1_sha1": disc.track1_sha1,
        "source_data_sha1": _sha1_file(disc.data), "data_file": data_name, "cue": name + ".cue",
        "data_sha1": _sha1_file(out / data_name), "changes": changes,
        "modes": {"title": title, "opening": opening}, "unverified": unverified,
        "distribution": False,
        "distribution_note": "translation review not complete (survey 5: v1.0 = all graphic text)",
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n")
    return manifest
