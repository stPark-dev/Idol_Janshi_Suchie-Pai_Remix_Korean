"""Voice subtitles (docs/voice-subtitles.md): executable stub, SUB.BIN, SUBDAT.BIN, root directory.

The executable "A" (loaded at 0x06010000) gets, at the same size:
  - in an SGL function that nothing calls (0x060A7840..0x060A78F6), a stub that every call of
    the file loader 0x0601A6A4 now goes through: if SUB.BIN's code is in RAM it jumps to BASE;
    otherwise, when the current directory has SUB.BIN, it reads it to BASE through the loader,
    purges the cache and checks again; without it the call goes on to the loader;
  - the 26 literals holding 0x0601A6A4 point at the stub.
SUB.BIN installs its other hooks in RAM (tools/subtitle/sub.c).

Voices and groups are known by their position on the disc (FAD = LBA + 150): the same voice
names exist in many directories.  A group holds the subtitles of one directory's voices.

The two new files go into the empty sectors after the last file of Track 1; the root directory
is rewritten in ISO 9660 name order and must keep its 4 sectors.
"""
import hashlib
import re
import struct
from dataclasses import dataclass

from . import cdsector, lzss

EXE_BASE, EXE_SIZE = 0x06010000, 702681
LOADER = 0x0601A6A4
STUB, STUB_END = 0x060A7840, 0x060A78F6
ORIG_STUB_SHA1 = "617b857b7d51257e3a86d842b8302b30daf32fcf"     # original 0x060A7840..0x060A78F6
MAGIC = 0x4B485355          # "KHSU" at BASE+0x10
GFS_NAME2ID = 0x060ADDCC

# RAM (measured free in every scene reached: docs/voice-subtitles.md 2)
FREE_RAM = (0x060D2C00, 0x060FEAE0)
DATA, GROUP_MAX = 0x060EF000, 0xA000        # one unpacked group (and its sectors), ending at BASE
BASE, CODE_MAX = 0x060F9000, 0x2000         # SUB.BIN code
INDEX, INDEX_MAX = BASE + CODE_MAX, 0x1000  # SUB.BIN index, read with the code
CELLBUF = 0x060FC000                        # 160 NBG3 cells
CELLUSE = 0x060FD400                        # VRAM slot bits (512 bytes)
FILES_OFF = 0x24                            # FAD and size of SUB.BIN and SUBDAT.BIN in the code
INDEX_MAGIC = 0x4B485258    # "KHRX"
GROUP_MAGIC = 0x4B485247    # "KHRG"
FAD_OFFSET = 150

# literals of the executable that hold the file loader (all of them), and the ones sub.c patches
LOADER_LITS = [
    0x6010348, 0x6017ae0, 0x6017bb8, 0x602f18c, 0x6030484, 0x603b77c, 0x603ba84, 0x603bef4, 0x603d49c,
    0x603f05c, 0x603f5e0, 0x603f670, 0x603f850, 0x60401d0, 0x6040680, 0x6047d9c, 0x60488e0, 0x604ea5c,
    0x604f204, 0x604f404, 0x604f6c8, 0x60500c8, 0x6050300, 0x605114c, 0x6051858, 0x6052028,
]
DIR, PLAY, PLAY2 = 0x0601A71A, 0x0603BBBC, 0x0603BD4C
HOOK_LITS = {
    DIR: [0x06017AD4, 0x06017B1C, 0x06025B94, 0x06025C34, 0x0602E894, 0x0603C024, 0x0603C77C, 0x0603D48C,
          0x0603D738, 0x0603F050, 0x0603F880, 0x0604EA4C, 0x0604F254, 0x0604F400, 0x0604F6B8, 0x060501D4,
          0x060502EC, 0x06051140, 0x06051268, 0x06051844, 0x0605201C, 0x060527F0, 0x06052888],
    PLAY: [0x06012C3C, 0x06012EB8, 0x06015EF0, 0x06016114, 0x0601632C, 0x06016544, 0x060220C8, 0x06022858,
           0x06023D44, 0x0602DF04, 0x06042A4C, 0x06049140, 0x0604A1A8, 0x0604B0B0],
    PLAY2: [0x060247F4, 0x06024950, 0x06024A08, 0x06024AC0, 0x06024BAC, 0x06024C54, 0x06024D98, 0x06024E60,
            0x06024F68, 0x06025024, 0x060250B0, 0x0602514C, 0x06025270, 0x0602530C, 0x060253A8, 0x06025444,
            0x060254E0, 0x06025BA4, 0x06030C04, 0x06031284, 0x0603D740, 0x0603FA04, 0x0604A5C4, 0x0604A870,
            0x0604A908, 0x0604B580, 0x0604FE14, 0x06050204, 0x06050330, 0x060527F8, 0x06052890],
}


class SubtitleError(RuntimeError):
    pass


# ---- the stub: a tiny SH-2 assembler with labels -----------------------------------------------
def _asm(org: int, items: list) -> bytes:
    """items: ("label", name) | (op, *args) | ("long", value) | ("word", value) | ("bytes", b) | ("align",)."""
    def size(it):
        return {"long": 4, "align": None, "bytes": len(it[1]) if it[0] == "bytes" else 0}.get(it[0], 2)

    labels, pc = {}, org
    for it in items:
        if it[0] == "label":
            labels[it[1]] = pc
        elif it[0] == "align":
            pc += -pc % 4
        else:
            pc += size(it)

    def disp(target, pc, scale, base_align, lo, hi, what):
        base = (pc & ~3 if base_align else pc) + 4
        d, r = divmod(target - base, scale)
        if r or not lo <= d <= hi:
            raise SubtitleError(f"{what} out of reach at {pc:#x}")
        return d

    out, pc = bytearray(), org
    for it in items:
        op = it[0]
        if op == "label":
            continue
        if op == "align":
            out += bytes(-pc % 4)
            pc += -pc % 4
            continue
        if op == "long":
            out += struct.pack(">I", it[1])
            pc += 4
            continue
        if op == "bytes":
            out += it[1]
            pc += len(it[1])
            continue
        if op == "word":
            w = it[1]
        elif op == "movl":                      # mov.l @(disp,PC),Rn
            w = 0xD000 | it[2] << 8 | disp(labels[it[1]], pc, 4, True, 0, 255, "mov.l")
        elif op == "movw":                      # mov.w @(disp,PC),Rn
            w = 0x9000 | it[2] << 8 | disp(labels[it[1]], pc, 2, False, 0, 255, "mov.w")
        elif op == "mova":                      # mova @(disp,PC),R0
            w = 0xC700 | disp(labels[it[1]], pc, 4, True, 0, 255, "mova")
        elif op in ("bt", "bf"):
            w = (0x8900 if op == "bt" else 0x8B00) | disp(labels[it[1]], pc, 2, False, -128, 127, op) & 0xFF
        else:
            raise SubtitleError(f"unknown op {op}")
        out += struct.pack(">H", w)
        pc += 2
    return bytes(out)


def stub() -> bytes:
    """New bytes for STUB..STUB_END."""
    items = [
        ("movl", "base", 1),            # r1 = BASE
        ("word", 0x5014),               # r0 = @(16,r1): the magic
        ("movl", "magic", 2),
        ("word", 0x3020),               # cmp/eq r2,r0
        ("bt", "loaded"),
        ("word", 0x4F22), ("word", 0x2F46), ("word", 0x2F56),     # push pr, r4, r5
        ("mova", "name"), ("word", 0x6403),                       # r4 = "SUB.BIN"
        ("movl", "name2id", 0),
        ("word", 0x400B), ("word", 0x0009),                       # GFS_NameToId("SUB.BIN")
        ("word", 0x4011),                                         # cmp/pz r0: in this directory?
        ("bf", "restore"),
        ("mova", "name"), ("word", 0x6403),                       # r4 = "SUB.BIN"
        ("movl", "base", 5),                                      # r5 = BASE
        ("movl", "load", 0),
        ("word", 0x400B), ("word", 0x0009),                       # loader("SUB.BIN", BASE)
        ("movw", "ccr", 1),                                       # r1 = 0xFFFFFE92 (CCR)
        ("word", 0x6010), ("word", 0xCB10), ("word", 0x2100),     # CCR |= CP: purge the cache
        ("label", "restore"),
        ("word", 0x65F6), ("word", 0x64F6), ("word", 0x4F26),     # pop r5, r4, pr
        ("movl", "base", 1),
        ("word", 0x5014),
        ("movl", "magic", 2),
        ("word", 0x3020),
        ("bf", "fail"),
        ("label", "loaded"),
        ("word", 0x412B), ("word", 0x0009),                       # jmp @r1 (BASE)
        ("label", "fail"),
        ("movl", "load", 0),                                      # the loader itself
        ("word", 0x402B), ("word", 0x0009),
        ("label", "ccr"), ("word", 0xFE92),
        ("align",),
        ("label", "base"), ("long", BASE),
        ("label", "magic"), ("long", MAGIC),
        ("label", "load"), ("long", LOADER),
        ("label", "name2id"), ("long", GFS_NAME2ID),
        ("label", "name"), ("bytes", b"SUB.BIN\0"),
    ]
    out = _asm(STUB, items)
    if STUB + len(out) > STUB_END:
        raise SubtitleError("stub overruns the unused function")
    return out + bytes(STUB_END - STUB - len(out))


def exe_changes(exe: bytes) -> list[tuple[int, bytes]]:
    """(file offset, new bytes) for the executable; checks the original bytes it replaces."""
    if len(exe) != EXE_SIZE:
        raise SubtitleError(f"executable size {len(exe)} != {EXE_SIZE}")
    lo, hi = STUB - EXE_BASE, STUB_END - EXE_BASE
    if hashlib.sha1(exe[lo:hi]).hexdigest() != ORIG_STUB_SHA1:
        raise SubtitleError("the stub area differs from the supported executable")
    changes = [(lo, stub())]
    for a in LOADER_LITS:
        o = a - EXE_BASE
        if exe[o:o + 4] != struct.pack(">I", LOADER):
            raise SubtitleError(f"literal at {a:#x} does not hold the file loader")
        changes.append((o, struct.pack(">I", STUB)))
    found = [EXE_BASE + o for o in range(0, len(exe) - 3, 2) if exe[o:o + 4] == struct.pack(">I", LOADER)]
    if sorted(found) != sorted(LOADER_LITS):
        raise SubtitleError("file loader literals differ from the known list")
    return changes


# ---- ISO 9660 root directory ---------------------------------------------------------------
@dataclass
class DirRecord:
    raw: bytes

    @property
    def name(self) -> bytes:
        return self.raw[33:33 + self.raw[32]]

    @property
    def lba(self) -> int:
        return struct.unpack("<I", self.raw[2:6])[0]

    @property
    def size(self) -> int:
        return struct.unpack("<I", self.raw[10:14])[0]

    @property
    def is_dir(self) -> bool:
        return bool(self.raw[25] & 2)


def parse_dir(sectors: list[bytes]) -> list[DirRecord]:
    recs = []
    for s in sectors:
        p = 0
        while p < len(s) and s[p]:
            recs.append(DirRecord(s[p:p + s[p]]))
            p += s[p]
    return recs


def new_record(template: DirRecord, name: str, lba: int, size: int) -> DirRecord:
    ident = (name + ";1").encode("ascii")
    n = 33 + len(ident)
    n += n & 1
    r = bytearray(n)
    r[0] = n
    r[2:10] = struct.pack("<I", lba) + struct.pack(">I", lba)
    r[10:18] = struct.pack("<I", size) + struct.pack(">I", size)
    r[18:25] = template.raw[18:25]          # recording date and time
    r[25] = 0                               # file flags
    r[28:32] = template.raw[28:32]          # volume sequence number
    r[32] = len(ident)
    r[33:33 + len(ident)] = ident
    return DirRecord(bytes(r))


def _sort_key(rec: DirRecord):
    nm = rec.name
    if nm in (b"\x00", b"\x01"):
        return (0, nm, b"")
    base = nm.split(b";")[0]
    stem, _, ext = base.partition(b".")
    return (1, stem, ext)


def pack_dir(recs: list[DirRecord], nsectors: int) -> list[bytes]:
    out, cur = [], bytearray()
    for r in recs:
        if len(cur) + len(r.raw) >= cdsector.USER:     # the mastering tool never fills a sector exactly
            out.append(bytes(cur) + bytes(cdsector.USER - len(cur)))
            cur = bytearray()
        cur += r.raw
    out.append(bytes(cur) + bytes(cdsector.USER - len(cur)))
    if len(out) > nsectors:
        raise SubtitleError(f"root directory needs {len(out)} sectors, has {nsectors}")
    return out + [bytes(cdsector.USER)] * (nsectors - len(out))


def with_files(recs: list[DirRecord], new: list[tuple[str, int, int]]) -> list[DirRecord]:
    """Records in ISO name order with the new files added (names must be new)."""
    have = {r.name.split(b";")[0].decode("latin1") for r in recs}
    template = next(r for r in recs if r.name not in (b"\x00", b"\x01"))
    extra = []
    for name, lba, size in new:
        if name in have:
            raise SubtitleError(f"{name} already exists on the disc")
        extra.append(new_record(template, name, lba, size))
    dots = [r for r in recs if r.name in (b"\x00", b"\x01")]
    files = sorted([r for r in recs if r.name not in (b"\x00", b"\x01")] + extra, key=_sort_key)
    return dots + files


# ---- disc layout of the new files ---------------------------------------------------------
DIR_LBA, DIR_SECTORS = 20, 4
FREE_LBA, FREE_END = 147218, 147518     # empty Mode 1 sectors after GOODEND/MATAAIMA.AIF, up to the end of Track 1
SUB_NAME, DAT_NAME = "SUB.BIN", "SUBDAT.BIN"


def _sectors(data: bytes) -> list[bytes]:
    data = data + bytes(-len(data) % cdsector.USER)
    return [data[i:i + cdsector.USER] for i in range(0, len(data), cdsector.USER)]


def layout(sub_bytes: int, dat_bytes: int) -> tuple[int, int]:
    """LBAs of SUB.BIN and SUBDAT.BIN."""
    sub_lba = FREE_LBA
    dat_lba = sub_lba + -(-sub_bytes // cdsector.USER)
    end = dat_lba + -(-dat_bytes // cdsector.USER)
    if end > FREE_END:
        raise SubtitleError(f"subtitle files need up to LBA {end}, free space ends at {FREE_END}")
    return sub_lba, dat_lba


def disc_sectors(user, sub_bin: bytes, subdat: bytes) -> tuple[list[tuple[int, bytes]], dict]:
    """User-data sectors to write: the root directory and the two new files.

    `user(lba)` reads 2048 bytes of the source.  The executable's byte changes are separate
    (exe_changes) because they go through the file-level writer."""
    sub_lba, dat_lba = layout(len(sub_bin), len(subdat))
    end = dat_lba + len(_sectors(subdat))
    for lba in range(FREE_LBA, end):
        if any(user(lba)):
            raise SubtitleError(f"LBA {lba} after the last file is not empty")
    old = [user(DIR_LBA + i) for i in range(DIR_SECTORS)]
    recs = parse_dir(old)
    if pack_dir(with_files(recs, []), DIR_SECTORS) != old:
        raise SubtitleError("root directory layout differs from the supported source")
    new_dir = pack_dir(with_files(recs, [(SUB_NAME, sub_lba, len(sub_bin)), (DAT_NAME, dat_lba, len(subdat))]),
                       DIR_SECTORS)
    out = [(DIR_LBA + i, s) for i, s in enumerate(new_dir) if s != old[i]]
    out += [(sub_lba + i, s) for i, s in enumerate(_sectors(sub_bin))]
    out += [(dat_lba + i, s) for i, s in enumerate(_sectors(subdat))]
    info = {"sub_bin": {"lba": sub_lba, "bytes": len(sub_bin)}, "subdat": {"lba": dat_lba, "bytes": len(subdat)}}
    return out, info


def empty_index() -> bytes:
    return struct.pack(">IHH", INDEX_MAGIC, 0, 0)


def sub_bin(code: bytes, index: bytes, sub: tuple[int, int], dat: tuple[int, int]) -> bytes:
    """SUB.BIN: code (with the LBA and size of both files written in) + index at CODE_MAX."""
    if len(code) > CODE_MAX:
        raise SubtitleError(f"subtitle code is {len(code)} bytes, room for {CODE_MAX}")
    if len(code) < FILES_OFF + 16 or struct.unpack(">I", code[0x10:0x14])[0] != MAGIC:
        raise SubtitleError("subtitle code does not carry the magic at +0x10")
    if len(index) > INDEX_MAX:
        raise SubtitleError(f"subtitle index is {len(index)} bytes, room for {INDEX_MAX}")
    files = struct.pack(">IIII", sub[0] + FAD_OFFSET, sub[1], dat[0] + FAD_OFFSET, dat[1])
    code = code[:FILES_OFF] + files + code[FILES_OFF + 16:]
    return code + bytes(CODE_MAX - len(code)) + index


# ---- subtitle data: glyphs, cues, groups, index ---------------------------------------------
FPS = 59.826                # vblanks per second in the 320-dot modes
LEAD = 0.1                  # a line appears this much before its voice segment
HOLD = 0.6                  # and stays this much after it, unless the next line starts earlier
MIN_SHOW = 1.0
SCREEN_W, LINE_MAX = 320, 304
GLYPH_ROWS = 16
FONT_SIZE = 14
ALLOWED = re.compile(r"[가-힣 A-Za-z0-9.,!?~…·'\"()\-:;%/&+=]*")   # what the subtitles may contain


def _font(path: str, size: int):
    from PIL import ImageFont
    return ImageFont.truetype(path, size)


def render_glyph(ch: str, font) -> tuple[int, bytes]:
    """One character as 2bpp rows (0 clear, 1 black outline, 2 grey edge, 3 white), 16 rows."""
    from PIL import Image, ImageDraw, ImageFilter
    if ch == " ":
        w = max(3, round(font.getlength(" ")))
        return w, bytes(((w + 3) // 4) * GLYPH_ROWS)
    adv = max(1, round(font.getlength(ch)))
    W = adv + 8
    im = Image.new("L", (W, GLYPH_ROWS), 0)
    asc, _ = font.getmetrics()
    top = (GLYPH_ROWS - FONT_SIZE) // 2 - (asc - FONT_SIZE) - 1
    ImageDraw.Draw(im).text((4, top), ch, font=font, fill=255)
    fill = im.point(lambda v: 3 if v >= 150 else (2 if v >= 70 else 0))
    edge = im.point(lambda v: 255 if v >= 70 else 0).filter(ImageFilter.MaxFilter(3))
    px, ex = fill.load(), edge.load()
    cols = [x for x in range(W) if any(ex[x, y] for y in range(GLYPH_ROWS))]
    if not cols:
        raise SubtitleError(f"glyph {ch!r} draws nothing")
    x0, x1 = min(cols), max(cols) + 1
    w = x1 - x0
    pitch = (w + 3) // 4
    out = bytearray(pitch * GLYPH_ROWS)
    for y in range(GLYPH_ROWS):
        for x in range(x0, x1):
            v = px[x, y] or (1 if ex[x, y] else 0)
            if v:
                i = x - x0
                out[y * pitch + i // 4] |= v << (6 - 2 * (i % 4))
    return w, bytes(out)


def wrap(text: str, width_of) -> list[str]:
    """One line, or two split at the space nearest the middle (both must fit LINE_MAX)."""
    text = " ".join(text.split())
    if width_of(text) <= LINE_MAX:
        return [text]
    spaces = [i for i, c in enumerate(text) if c == " "]
    best = None
    for i in spaces:
        a, b = text[:i], text[i + 1:]
        wa, wb = width_of(a), width_of(b)
        if wa <= LINE_MAX and wb <= LINE_MAX and (best is None or max(wa, wb) < best[0]):
            best = (max(wa, wb), [a, b])
    if best is None:
        raise SubtitleError(f"line does not fit in two lines of {LINE_MAX}px: {text}")
    return best[1]


def cue_frames(lines: list[dict]) -> list[tuple[int, int]]:
    out = []
    for i, ln in enumerate(lines):
        start = max(0.0, ln["start"] - LEAD)
        end = max(ln["end"] + HOLD, start + MIN_SHOW)
        if i + 1 < len(lines):
            end = min(end, max(lines[i + 1]["start"] - LEAD, ln["end"]))
        out.append((round(start * FPS), round(end * FPS)))
    return out


def build_group(group: int, voices: list[tuple[int, dict]], font_path: str) -> bytes:
    """voices: (FAD, translation doc {"voice", "lines": [{start, end, ko}]}) in voice-number order."""
    font = _font(font_path, FONT_SIZE)
    glyphs: dict[str, tuple[int, bytes]] = {}
    gid: dict[str, int] = {}

    def width_of(s):
        w = 0
        for ch in s:
            if ch not in glyphs:
                glyphs[ch] = render_glyph(ch, font)
            w += glyphs[ch][0]
        return w

    cues, text = [], []
    for vno, (_, doc) in enumerate(voices):
        lines = [ln for ln in doc["lines"] if ln.get("ko")]
        for ln, (s, e) in zip(lines, cue_frames(lines)):
            if not ALLOWED.fullmatch(ln["ko"]):
                bad = sorted(set(re.sub(ALLOWED.pattern[:-1], "", ln["ko"])))
                raise SubtitleError(f"{doc['voice']} {ln['start']}: characters outside the subtitle set {bad}")
            if e <= s:
                raise SubtitleError(f"{doc['voice']} {ln['start']}: line ends before it starts")
            parts = wrap(ln["ko"], width_of)
            ids = []
            for p in parts:
                for ch in p:
                    if ch not in gid:
                        gid[ch] = len(gid)
                    ids.append(gid[ch])
            n1 = len(parts[0])
            n2 = len(parts[1]) if len(parts) > 1 else 0
            xs = [(SCREEN_W - width_of(p)) // 2 for p in parts]
            if len(parts) == 1:       # a single line sits on the lower row
                cues.append((vno, 2, s, e, len(text), 0, n1, 0, xs[0]))
            else:
                cues.append((vno, 2, s, e, len(text), n1, n2, xs[0], xs[1]))
            text += ids
    order = sorted(gid, key=gid.get)
    gl_tab, bits = b"", b""
    for ch in order:
        w, b = glyphs[ch]
        gl_tab += struct.pack(">HH", w, len(bits))
        bits += b
    fads = b"".join(struct.pack(">I", fad) for fad, _ in voices)
    cue_b = b"".join(struct.pack(">BBHHHHHhh", *c) for c in cues)
    text_b = b"".join(struct.pack(">H", t) for t in text)
    o_voices = 32
    o_cues = o_voices + len(fads)
    o_gl = o_cues + len(cue_b)
    o_text = o_gl + len(gl_tab)
    o_bits = o_text + len(text_b)
    o_bits += o_bits & 1
    data = struct.pack(">IHHHHIIIII", GROUP_MAGIC, group, len(voices), len(cues), len(order),
                       o_voices, o_cues, o_gl, o_text, o_bits)
    data += fads + cue_b + gl_tab + text_b
    data += bytes(o_bits - len(data)) + bits
    if len(data) > GROUP_MAX:
        raise SubtitleError(f"group {group} is {len(data)} bytes, room for {GROUP_MAX}")
    return data


def unpack(stream: bytes) -> tuple[bytes, list[tuple[int, int]]]:
    """Model of sub.c unlzss(): (output, [(output length, input bytes consumed)] per step)."""
    out, steps, i, flags = bytearray(), [], 0, 0
    while i < len(stream):
        flags >>= 1
        if not flags & 0x100:
            flags = stream[i] | 0xFF00
            i += 1
            if i >= len(stream):
                break
        if flags & 1:
            out.append(stream[i])
            i += 1
        else:
            if i + 1 >= len(stream):
                break
            lo, hi = stream[i], stream[i + 1]
            i += 2
            p, n = lo | (hi & 0xF0) << 4, (hi & 0x0F) + 3
            back = (0xFEE + len(out) - p) & 0xFFF or 0x1000
            for _ in range(n):
                k = len(out) - back
                out.append(out[k] if k >= 0 else 0)
        steps.append((len(out), i))
    return bytes(out), steps


def pack_group(data: bytes) -> bytes:
    """LZSS stream without its header, checked through the model of sub.c's decoder."""
    stream = lzss.compress(data)[4:]
    if unpack(stream)[0] != data:
        raise SubtitleError("LZSS round trip failed")
    return stream


def group_place(off: int, packed: int, size: int) -> tuple[int, int]:
    """(where the group's sectors are read, where it is unpacked), as offsets in the data area;
    the same rule as sub.c load_group(): a group that fits beside its sectors is unpacked at the
    end of the area; a larger one in place, sectors at the end and output from the start (never
    passing the input)."""
    area = ((off + packed - 1) // cdsector.USER - off // cdsector.USER + 1) * cdsector.USER
    top = GROUP_MAX - ((size + 3) & ~3)
    if area <= top:
        return 0, top
    return GROUP_MAX - area, 0


def build_index(groups: list[tuple[int, bytes]]) -> tuple[bytes, bytes]:
    """(index, SUBDAT.BIN) for (directory FAD, group bytes).

    SUBDAT.BIN holds the groups' LZSS streams back to back; the index gives each one's directory,
    byte offset, packed and unpacked sizes."""
    subdat, table, dirs = b"", b"", set()
    for g, (dir_fad, data) in enumerate(groups):
        if dir_fad in dirs:
            raise SubtitleError(f"directory FAD {dir_fad} has two groups (twice)")
        dirs.add(dir_fad)
        stream = pack_group(data)
        off = len(subdat)
        first, last = off // cdsector.USER, (off + len(stream) - 1) // cdsector.USER
        area = (last - first + 1) * cdsector.USER
        if area > GROUP_MAX or len(data) > GROUP_MAX:
            raise SubtitleError(f"group {g}: {len(data)} bytes unpacked, {area} bytes of sectors")
        read_at, unpack_at = group_place(off, len(stream), len(data))
        start = read_at + off % cdsector.USER                 # where the stream begins in the area
        for produced, consumed in unpack(stream)[1]:
            if unpack_at < start + len(stream) and unpack_at + produced > start + consumed:
                raise SubtitleError(f"group {g}: unpacking would overwrite its own input")
        table += struct.pack(">IIHH", dir_fad, off, len(stream), len(data))
        subdat += stream
    index = struct.pack(">IHH", INDEX_MAGIC, len(groups), 0) + table
    if len(index) > INDEX_MAX:
        raise SubtitleError(f"subtitle index is {len(index)} bytes, room for {INDEX_MAX}")
    return index, subdat + bytes(-len(subdat) % cdsector.USER) if subdat else bytes(cdsector.USER)


# ---- whole subtitle data set ------------------------------------------------------------------
def load_voice_docs(voice_dir) -> dict:
    """translation/voice/<disc path without .AIF>.json -> {"KAIWADIR/OPSIHO/MAI.AIF": doc}."""
    import json
    from pathlib import Path
    root = Path(voice_dir)
    docs = {}
    for p in sorted(root.rglob("*.json")):
        doc = json.loads(p.read_text(encoding="utf-8"))
        key = doc["voice"].upper()
        want = p.relative_to(root).with_suffix(".AIF").as_posix().upper()
        if key != want:
            raise SubtitleError(f"{p}: voice {doc['voice']} does not match its file name ({want})")
        docs[key] = doc
    return docs


def build_data(scenes: dict, docs: dict, font_path: str, lba_of) -> tuple[bytes, bytes, dict]:
    """(index, SUBDAT.BIN, manifest info); sub_bin() puts the index after the code once the
    files have their places (layout()).

    scenes: {"groups": [{"id", "dir", "voices": [names in that directory]}]}; `lba_of(path, is_dir)`
    gives the LBA of a file or directory on the source disc ("" = the root directory).  A group goes on
    the disc when at least one of its voices has a translated line; voices without a translation
    stay in the group with no cues."""
    groups, info_groups, statuses, seen_dirs = [], [], {}, set()
    paths = {}
    for g in scenes["groups"]:
        if g["dir"] in seen_dirs:
            raise SubtitleError(f"directory {g['dir'] or '/'} listed twice")
        seen_dirs.add(g["dir"])
        for v in g["voices"]:
            paths[(g["dir"] + "/" + v if g["dir"] else v).upper()] = g["id"]
    stray = sorted(set(docs) - set(paths))
    if stray:
        raise SubtitleError(f"translations for voices outside every group: {stray}")
    for g in scenes["groups"]:
        voices = []
        for v in g["voices"]:
            path = (g["dir"] + "/" + v if g["dir"] else v).upper()
            voices.append((lba_of(path, False) + FAD_OFFSET, docs.get(path, {"voice": path, "lines": []})))
        lines = [ln for _, d in voices for ln in d["lines"] if ln.get("ko")]
        if not lines:
            continue
        for ln in lines:
            st = ln.get("status", "needs_review")
            statuses[st] = statuses.get(st, 0) + 1
        data = build_group(len(groups), voices, font_path)
        groups.append((lba_of(g["dir"], True) + FAD_OFFSET, data))
        info_groups.append({"id": g["id"], "dir": g["dir"], "voices": len(voices), "lines": len(lines),
                            "bytes": len(data)})
    index, subdat = build_index(groups)
    info = {"groups": info_groups, "lines": sum(statuses.values()), "status": statuses,
            "distribution": bool(statuses) and set(statuses) <= {"distribution_eligible"},
            "index_bytes": len(index), "subdat_bytes": len(subdat)}
    return index, subdat, info
