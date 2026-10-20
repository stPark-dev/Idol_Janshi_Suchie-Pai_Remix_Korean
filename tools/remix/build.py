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

from . import bank, bigletters, cdsector, cx, gfxtext, iso9660, logo
from .writeplan import WritePlan

ROOT = Path(__file__).resolve().parents[2]

TRACK1_SECTORS = 147518
TRACK1_SHA1 = "ac800da596c31d478989e9dac309198ddf527143"
RAW = cdsector.RAW
CX_FILES = ("TITL_CG.CX", "SELECT.CX", "BADGRAPH.CX", "GAMEDRV/MJCG.CX", "GOODEND/GOODEND.CX")

# TITL_CG.CX: single 4bpp images, byte RLE (survey 3.4, 3.7).
TITLE_FILE = "TITL_CG.CX"
TITLE_SHA1 = "39ead2b63eaff305a8c4a771e7b02a79f67153ff"
# Logo and opening cells checked on screen, per (title, opening) mode: SHA-1 of the unpacked logo,
# scroll and art cells in index order (Pillow 9.4, NanumSquareRound EB). Table entries for other
# TITL_CG cells (translation/*.json) are applied afterwards and are not part of this pin.
TITL_CG_CELLS_SHA1 = {
    ("korean", "original"): "fb5bdefdd369224cb704cffba21379b9366a3825",   # survey 3.7
    ("korean", "korean"): "34a2eb23b45f81432b978451f7f3168439d80b98",     # survey 3.8
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


# Graphic text tables: translation/<name>.json + assets/<name>/layout.json. Each entry names its file
# (table default "file") and, for CX files, the bank entry "cx_entry".
GRAPHIC_TABLES = ("select", "round", "match", "panel", "intro", "misc")
ORIGINAL_SHA1 = {
    "PNL1.BNN": "5bdbb036a14a211e7a8146f8ba14787d3558508b",
    "PNL2.BNN": "ab440176f0336b51ed83941f44e25b8e7b027c7d",
    "KAIWADIR/CLER.BNN": "ca659716afdb9252853ff671f7ae4c6b628866a8",
    "KAIWADIR/LOAD.BNN": "7382bb1c661bb91d39ce85acbc44410273c2530e",
    "SELECT.CX": "9b0734a6d425606aceb303bf8a02bc945a0142db",
    "TITL_CG.CX": TITLE_SHA1,
    "KAIWADIR/ROUND.BNN": "59e43c61bb6e151e8faf4330b56fba07be1404ac",
    "GAMEDRV/MJCG.CX": "67b201f58538e19226202ece91eae31a8b6200ed",
    "PANELDIR/ROUND2.BNN": "6b6fe2e86c329545e5c9e2e27d1397b793d61b78",
}
STATES = ("untranslated", "in_progress", "needs_review", "needs_human_review", "distribution_eligible")


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


def load_table(name: str) -> tuple[list[dict], list[dict]]:
    t = json.loads((ROOT / "translation" / f"{name}.json").read_text())
    lay = json.loads((ROOT / "assets" / name / "layout.json").read_text())
    for l in lay["entries"]:
        l.setdefault("font", lay["font"])
    for e in t["entries"]:
        e.setdefault("file", t.get("file"))
        e.setdefault("cx_entry", None)
    return t["entries"], lay["entries"]


def load_tables(names=GRAPHIC_TABLES) -> tuple[list[dict], dict[str, dict]]:
    """All entries (ko_from resolved to the referenced entry's wording) and layouts by id."""
    entries, layouts = [], {}
    for n in names:
        e, l = load_table(n)
        entries += e
        for x in l:
            if x["id"] in layouts:
                raise BuildError(f"duplicate layout id {x['id']}")
            layouts[x["id"]] = x
    by_id = {e["id"]: e for e in entries}
    if len(by_id) != len(entries):
        raise BuildError("duplicate translation ids")
    for e in entries:
        if "ko_from" in e:
            src = by_id.get(e["ko_from"])
            if src is None or "ko_from" in src:
                raise BuildError(f"{e['id']}: ko_from {e['ko_from']!r} is not a direct entry")
            e["ko"], e["state"] = src["ko"], src["state"]
        if e["state"] not in STATES:
            raise BuildError(f"{e['id']}: unknown translation state {e['state']!r}")
        if e["id"] not in layouts:
            raise BuildError(f"{e['id']}: no layout")
    return entries, layouts


def _apply_bank(raw: bytes, group: list[dict], layouts: dict[str, dict], where: str) -> bytes:
    b = bank.Bank.parse(raw)
    try:
        gfxtext.apply_all(b, group, [layouts[e["id"]] for e in group])
    except gfxtext.GfxTextError as e:
        raise BuildError(f"{where}: {e}") from None
    return b.build()


def graphic_file(path: str, original: bytes, entries: list[dict], layouts: dict[str, dict]) -> bytes:
    if hashlib.sha1(original).hexdigest() != ORIGINAL_SHA1.get(path):
        raise BuildError(f"{path}: content is not the original")
    if path.endswith(".CX"):
        c = cx.Container.parse(original)
        for k in sorted({e["cx_entry"] for e in entries}):
            group = [e for e in entries if e["cx_entry"] == k]
            raw = c.entries[k]
            if is_raw_bank(raw):
                c.entries[k] = _apply_bank(raw, group, layouts, f"{path} #{k}")
            else:   # compressed bank: unpack, edit, repack with the same kind (shortest stream)
                kind = int.from_bytes(raw[:2], "big")
                new = _apply_bank(cx.unpack_entry(raw), group, layouts, f"{path} #{k}")
                c.entries[k] = cx.pack_entry(kind, new, optimal=True)
        return c.build()
    if any(e["cx_entry"] is not None for e in entries):
        raise BuildError(f"{path}: cx_entry given for a plain bank file")
    return _apply_bank(original, entries, layouts, path)


def title_cells_sha1(data: bytes) -> str:
    c = cx.Container.parse(data)
    cells = sorted(set(LOGO_CELLS) | set(SCROLL_LETTERS) | set(ART_LETTERS))
    return hashlib.sha1(b"".join(cx.unpack_entry(c.entries[i]) for i in cells)).hexdigest()


def title_cg(original: bytes, title: str, opening: str, unverified: bool = False,
             entries: list[dict] | None = None, layouts: dict[str, dict] | None = None) -> bytes:
    if hashlib.sha1(original).hexdigest() != TITLE_SHA1:
        raise BuildError(f"{TITLE_FILE}: content is not the original")
    c = cx.Container.parse(original)
    if title == "korean":
        _logo(c)
    if opening == "korean":
        _opening(c)
    new = c.build()
    if "korean" in (title, opening):
        got = title_cells_sha1(new)
        want = TITL_CG_CELLS_SHA1.get((title, opening))
        if want is None and not unverified:
            raise BuildError(f"{TITLE_FILE}: title={title} opening={opening} has not been verified on screen "
                             "(build with unverified=True / --unverified for a test disc)")
        if want is not None and got != want:
            raise BuildError(f"{TITLE_FILE}: logo/opening cells {got} differ from the verified {want} "
                             "(source PNG, font or Pillow changed; re-verify on screen before updating)")
    if entries:
        pinned = set(LOGO_CELLS) | set(SCROLL_LETTERS) | set(ART_LETTERS)
        clash = [e["id"] for e in entries if e["cx_entry"] in pinned]
        if clash:
            raise BuildError(f"{TITLE_FILE}: table entries touch logo/opening cells: {clash}")
        c = cx.Container.parse(new)
        for k in sorted({e["cx_entry"] for e in entries}):
            group = [e for e in entries if e["cx_entry"] == k]
            raw = c.entries[k]
            if is_raw_bank(raw):
                c.entries[k] = _apply_bank(raw, group, layouts, f"{TITLE_FILE} #{k}")
            else:
                kind = int.from_bytes(raw[:2], "big")
                c.entries[k] = cx.pack_entry(kind, _apply_bank(cx.unpack_entry(raw), group, layouts,
                                                               f"{TITLE_FILE} #{k}"), optimal=True)
        new = c.build()
    return new


def build(source: Path, out: Path, title: str = "korean", opening: str = "korean", graphics: str = "korean",
          unverified: bool = False, name: str = "remix_ko") -> dict:
    disc = SourceDisc.open(Path(source))
    out = Path(out)
    check_output_paths(disc.cue, disc.data, out, name)
    out.mkdir(parents=True, exist_ok=True)
    dirs = DirPatch()
    protected = [(TRACK1_SECTORS * RAW, disc.data.stat().st_size)]
    plan = WritePlan(disc.data, protected=protected)
    changes = []
    for mode in (title, opening, graphics):
        if mode not in ("korean", "original"):
            raise BuildError(f"unknown mode {mode}")
    entries, layouts = load_tables() if graphics == "korean" else ([], {})
    title_entries = [e for e in entries if e["file"] == TITLE_FILE]
    if "korean" in (title, opening) or title_entries:
        new = title_cg(disc.read_file(TITLE_FILE), title, opening, unverified, title_entries, layouts)
        changes.append(_plan_file(plan, disc, TITLE_FILE, new, "title_cg", dirs))
    texts = []
    if graphics == "korean":
        for path in sorted({e["file"] for e in entries} - {TITLE_FILE}):
            group = [e for e in entries if e["file"] == path]
            new = graphic_file(path, disc.read_file(path), group, layouts)
            changes.append(_plan_file(plan, disc, path, new, f"gfx:{path}", dirs))
        texts = [{"id": e["id"], "state": e["state"]} for e in entries]
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
        "modes": {"title": title, "opening": opening, "graphics": graphics}, "unverified": unverified,
        "translations": texts,
        "distribution": False,
        "distribution_note": "translation review not complete (survey 5: v1.0 = all graphic text)",
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n")
    return manifest
