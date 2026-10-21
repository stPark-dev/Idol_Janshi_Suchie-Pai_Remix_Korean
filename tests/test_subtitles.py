"""Voice subtitles: executable stub, ISO root rewrite, group/index format, RAM layout (no game data)."""
import re
import struct
from pathlib import Path

import pytest

from remix import label, lzss, subtitles as S

SRC = Path(__file__).resolve().parents[1] / "tools" / "subtitle"


# ---- the stub in the executable ---------------------------------------------------------------
def _w(code: bytes, addr: int) -> int:
    o = addr - S.STUB
    return struct.unpack(">H", code[o:o + 2])[0]


def _movl_target(code: bytes, addr: int) -> int:
    ins = _w(code, addr)
    assert ins >> 12 == 0xD, hex(ins)
    lit = ((addr & ~3) + 4) + (ins & 0xFF) * 4
    o = lit - S.STUB
    return struct.unpack(">I", code[o:o + 4])[0]


def _branch_target(code: bytes, addr: int) -> int:
    disp = _w(code, addr) & 0xFF
    disp -= 0x100 if disp & 0x80 else 0
    return addr + 4 + disp * 2


def _find(code: bytes, word: int, start: int = 0) -> int:
    for o in range(start, len(code), 2):
        if struct.unpack(">H", code[o:o + 2])[0] == word:
            return S.STUB + o
    raise AssertionError(f"{word:#06x} not in the stub")


def test_stub_checks_the_magic_reads_sub_bin_and_falls_back_to_the_loader():
    code = S.stub()
    assert len(code) == S.STUB_END - S.STUB
    s = S.STUB
    assert _movl_target(code, s) == S.BASE                       # r1 = BASE
    assert _w(code, s + 2) == 0x5014                             # r0 = @(16,r1): the magic
    assert _movl_target(code, s + 4) == S.MAGIC
    loaded = _find(code, 0x412B)                                 # jmp @r1
    assert _branch_target(code, s + 8) == loaded                 # bt loaded
    mova = next(S.STUB + o for o in range(0, len(code), 2) if code[o] == 0xC7)   # first mova: the name
    name_at = ((mova & ~3) + 4) + code[mova - s + 1] * 4
    assert code[name_at - s:name_at - s + 8] == b"SUB.BIN\0"
    end = _find(code, 0xFE92) - S.STUB                           # the instructions end at the CCR constant
    calls = [S.STUB + o for o in range(0, end, 2) if (code[o] >> 4) == 0xD
             and _movl_target(code, S.STUB + o) == S.LOADER]
    assert len(calls) == 2                                       # read SUB.BIN, and the fallback
    fallback = calls[-1]
    assert _w(code, fallback + 2) == 0x402B                      # jmp @r0: the loader with the caller's r4/r5/pr
    assert _branch_target(code, loaded - 2) == fallback          # bf fail -> the loader itself


def test_exe_changes_point_every_loader_literal_at_the_stub():
    exe = bytearray(S.EXE_SIZE)
    for a in S.LOADER_LITS:
        exe[a - S.EXE_BASE:a - S.EXE_BASE + 4] = struct.pack(">I", S.LOADER)
    with pytest.raises(S.SubtitleError, match="stub area"):       # the dead SGL function is not there
        S.exe_changes(bytes(exe))
    with pytest.raises(S.SubtitleError):
        S.exe_changes(bytes(10))


def test_exe_changes_on_a_fake_executable(monkeypatch):
    exe = bytearray(S.EXE_SIZE)
    for a in S.LOADER_LITS:
        exe[a - S.EXE_BASE:a - S.EXE_BASE + 4] = struct.pack(">I", S.LOADER)
    import hashlib
    monkeypatch.setattr(S, "ORIG_STUB_SHA1", hashlib.sha1(bytes(S.STUB_END - S.STUB)).hexdigest())
    changes = dict(S.exe_changes(bytes(exe)))
    assert changes[S.STUB - S.EXE_BASE] == S.stub()
    for a in S.LOADER_LITS:
        assert changes[a - S.EXE_BASE] == struct.pack(">I", S.STUB)
    exe[0x100:0x104] = struct.pack(">I", S.LOADER)                # an unknown caller
    with pytest.raises(S.SubtitleError, match="literals"):
        S.exe_changes(bytes(exe))


# ---- ISO root directory -----------------------------------------------------------------------
def _rec(name: str, lba: int, size: int) -> S.DirRecord:
    return S.new_record(S.DirRecord(bytes(34)), name, lba, size)


def _dot(n: bytes) -> S.DirRecord:
    r = bytearray(34)
    r[0], r[32], r[33], r[25] = 34, 1, n[0], 2
    return S.DirRecord(bytes(r))


def test_root_directory_rewrite_keeps_iso_order_and_sector_rule():
    files = [_rec(f"F{i:03d}.BIN", 100 + i, 2048) for i in range(60)]
    recs = [_dot(b"\0"), _dot(b"\1")] + files
    sectors = S.pack_dir(recs, 3)
    assert [r.raw for r in S.parse_dir(sectors)] == [r.raw for r in recs]
    new = S.with_files(recs, [("SUB.BIN", 900, 5000), ("SUBDAT.BIN", 903, 9000)])
    names = [r.name for r in new[2:]]
    assert names == sorted(names, key=lambda n: (n.split(b";")[0].partition(b".")[0], n.split(b";")[0].partition(b".")[2]))
    sub = next(r for r in new if r.name == b"SUB.BIN;1")
    assert (sub.lba, sub.size) == (900, 5000)
    with pytest.raises(S.SubtitleError):
        S.with_files(recs, [("F001.BIN", 1, 1)])
    with pytest.raises(S.SubtitleError):
        S.pack_dir(new * 3, 3)


def test_pack_dir_never_fills_a_sector_exactly():
    exact = [S.DirRecord(bytes([64]) + bytes(63)) for _ in range(32)]  # 32 * 64 = 2048 exactly
    out = S.pack_dir(exact, 2)
    assert len(S.parse_dir(out[:1])) == 31


def test_disc_sectors_refuse_used_free_space():
    def user(lba):
        return b"\x01" + bytes(2047) if lba == S.FREE_LBA + 1 else bytes(2048)
    with pytest.raises(S.SubtitleError, match="not empty"):
        S.disc_sectors(user, bytes(S.CODE_MAX), bytes(2048))


def test_file_locations_go_into_sub_bin():
    code = bytes(0x10) + struct.pack(">I", S.MAGIC) + bytes(0x40)
    img = S.sub_bin(code, S.empty_index(), sub=(147218, 9000), dat=(147223, 40000))
    assert struct.unpack(">IIII", img[S.FILES_OFF:S.FILES_OFF + 16]) == (147218 + 150, 9000, 147223 + 150, 40000)
    assert img[S.CODE_MAX:S.CODE_MAX + 4] == b"KHRX"
    with pytest.raises(S.SubtitleError):
        S.sub_bin(bytes(S.CODE_MAX + 1), S.empty_index(), sub=(1, 1), dat=(1, 1))
    with pytest.raises(S.SubtitleError, match="magic"):
        S.sub_bin(bytes(0x40), S.empty_index(), sub=(1, 1), dat=(1, 1))


# ---- groups and index ------------------------------------------------------------------------
def _parse_group(data: bytes):
    magic, group, nvoices, ncues, nglyphs, o_v, o_cues, o_gl, o_text, o_bits = struct.unpack(">IHHHHIIIII", data[:32])
    voices = list(struct.unpack(f">{nvoices}I", data[o_v:o_v + 4 * nvoices]))
    cues = [struct.unpack(">BBHHHHHhh", data[o_cues + 16 * i:o_cues + 16 * i + 16]) for i in range(ncues)]
    return magic, group, voices, cues, nglyphs


def test_group_keys_voices_by_fad_wraps_long_lines_and_counts_vblanks():
    doc = {"voice": "KAIWADIR/OPSIHO/MAI.AIF", "lines": [
        {"start": 1.0, "end": 2.0, "ko": "오랜만이야."},
        {"start": 2.5, "end": 6.0, "ko": "아버님 어깨너머로 배운 정도라서 잘한다고 할 만한 실력은 아니에요."},
        {"start": 7.0, "end": 8.0, "ko": ""},
    ]}
    data = S.build_group(3, [(50509, doc), (50600, {"voice": "KAIWADIR/OPSIHO/RIE.AIF", "lines": []})],
                         label.DEFAULT_FONT)
    magic, group, voices, cues, nglyphs = _parse_group(data)
    assert (magic, group, voices) == (S.GROUP_MAGIC, 3, [50509, 50600])
    assert len(cues) == 2
    voice, _, start, end, _, n1, n2, x1, x2 = cues[0]
    assert (voice, n1) == (0, 0) and n2 == len("오랜만이야.")              # one line sits on the lower row
    assert start == round((1.0 - S.LEAD) * S.FPS)
    assert end <= round((2.5 - S.LEAD) * S.FPS)                              # stops before the next line
    _, _, _, _, _, n1, n2, x1, x2 = cues[1]
    assert n1 > 0 and n2 > 0                                                  # wrapped into two lines
    assert 0 <= x1 < 160 and 0 <= x2 < 160


def test_group_rejects_characters_outside_the_font_set():
    doc = {"voice": "PANELDIR/PNSIHO/AMAI.AIF", "lines": [{"start": 0.0, "end": 1.0, "ko": "부끄러워♡"}]}
    with pytest.raises(S.SubtitleError, match="characters outside"):
        S.build_group(0, [(1, doc)], label.DEFAULT_FONT)


def test_group_rejects_a_line_longer_than_two_rows():
    doc = {"voice": "X.AIF", "lines": [{"start": 0.0, "end": 9.0, "ko": "가나다라마바사아자차카타파하 " * 4}]}
    with pytest.raises(S.SubtitleError, match="two lines"):
        S.build_group(0, [(1, doc)], label.DEFAULT_FONT)


def test_index_lists_groups_by_directory_fad():
    g0 = S.build_group(0, [(10, {"voice": "A.AIF", "lines": [{"start": 0, "end": 1, "ko": "가"}]})], label.DEFAULT_FONT)
    g1 = S.build_group(1, [(20, {"voice": "B.AIF", "lines": [{"start": 0, "end": 1, "ko": "나"}]})], label.DEFAULT_FONT)
    index, subdat = S.build_index([(201, g0), (205, g1)])
    magic, ngroups, pad = struct.unpack(">IHH", index[:8])
    assert (magic, ngroups, pad) == (S.INDEX_MAGIC, 2, 0)
    (d0, o0, p0, n0), (d1, o1, p1, n1) = struct.unpack(">IIHH", index[8:20]), struct.unpack(">IIHH", index[20:32])
    assert (d0, d1) == (201, 205)
    assert (o0, n0, n1) == (0, len(g0), len(g1)) and o1 == p0
    assert S.unpack(subdat[o0:o0 + p0])[0] == g0 and S.unpack(subdat[o1:o1 + p1])[0] == g1
    assert len(subdat) % 2048 == 0 and len(index) == 8 + 12 * 2
    with pytest.raises(S.SubtitleError, match="twice"):
        S.build_index([(201, g0), (201, g1)])


def test_index_must_fit_its_ram_place():
    g = S.build_group(0, [(10, {"voice": "A.AIF", "lines": [{"start": 0, "end": 1, "ko": "가"}]})], label.DEFAULT_FONT)
    with pytest.raises(S.SubtitleError, match="index"):
        S.build_index([(i, g) for i in range(S.INDEX_MAX // 12)])


def test_unpack_model_matches_the_codec():
    data = bytes(range(256)) * 3 + bytes(500) + b"abcabcabc" * 40
    stream = lzss.compress(data)
    assert S.unpack(stream[4:])[0] == lzss.decompress(stream) == data


def test_small_groups_unpack_at_the_end_of_the_data_area():
    read_at, unpack_at = S.group_place(off=1000, packed=700, size=906)
    assert read_at == 0
    assert unpack_at == S.GROUP_MAX - 908                      # word aligned, ends at BASE
    assert read_at + 2048 <= unpack_at                         # the sectors stay clear of the output


def test_large_groups_unpack_in_place_from_the_start():
    read_at, unpack_at = S.group_place(off=5000, packed=30000, size=40000)
    area = ((5000 + 30000 - 1) // 2048 - 5000 // 2048 + 1) * 2048
    assert (read_at, unpack_at) == (S.GROUP_MAX - area, 0)


# ---- RAM layout -------------------------------------------------------------------------------
def test_everything_lies_in_the_measured_free_ram_without_overlap():
    regions = [(S.DATA, S.GROUP_MAX), (S.BASE, S.CODE_MAX), (S.INDEX, S.INDEX_MAX),
               (S.CELLBUF, 160 * 32), (S.CELLUSE, 0x200), (S.CELLUSE + 0x200, 4)]  # + the log counter
    regions.sort()
    for (a, n), (b, _) in zip(regions, regions[1:]):
        assert a + n <= b, hex(a)
    assert regions[0][0] >= S.FREE_RAM[0] and regions[-1][0] + regions[-1][1] <= S.FREE_RAM[1]
    assert S.INDEX == S.BASE + S.CODE_MAX                      # SUB.BIN = code + index, read whole


def test_sub_c_crt_and_linker_script_use_the_build_addresses():
    c = SRC.joinpath("sub.c").read_text()
    defs = {k: int(v, 16) for k, v in re.findall(r"#define (\w+)\s+\(?\(?[\w *]*\)?\s*(0x[0-9A-Fa-f]+)u?\)?", c)}
    for name in ("BASE", "DATA", "CELLUSE", "CELLBUF", "GROUP_MAX", "CODE_MAX", "INDEX_MAX"):
        assert defs[name] == getattr(S, name), name
    assert defs["INDEX_MAGIC"] == S.INDEX_MAGIC and defs["GROUP_MAGIC"] == S.GROUP_MAGIC
    ld = SRC.joinpath("sub.ld").read_text()
    assert int(re.search(r"\. = (0x[0-9A-Fa-f]+);", ld).group(1), 16) == S.BASE
    assert int(re.search(r"_end <= (0x[0-9A-Fa-f]+)", ld).group(1), 16) == S.BASE + S.CODE_MAX
    crt = SRC.joinpath("crt.S").read_text()
    assert f"BASE = {S.BASE:#010X}".replace("0X", "0x") in crt
    assert "BASE+0x24" in crt and S.FILES_OFF == 0x24
    for name, addr in (("dir_lits", S.DIR), ("play_lits", S.PLAY), ("play2_lits", S.PLAY2)):
        body = re.search(name + r"\[\] = \{([^}]*)\}", c).group(1)
        assert [int(x, 16) for x in re.findall(r"0x[0-9A-Fa-f]+", body)] == S.HOOK_LITS[addr], name


# ---- whole data set ---------------------------------------------------------------------------
def _fake_lookup(path, is_dir):
    table = {"": 20, "KAIWADIR/OPSIHO": 51, "KAIWADIR/OPSIHO/MAI.AIF": 50359, "KAIWADIR/OPSIHO/RIE.AIF": 50800,
             "PANELDIR/PNSIHO": 70, "PANELDIR/PNSIHO/AMAI.AIF": 60000, "WATASHI.AIF": 15025}
    assert is_dir == (path in ("", "KAIWADIR/OPSIHO", "PANELDIR/PNSIHO"))
    return table[path]


def _doc(voice, ko="안녕", status="needs_review"):
    return {"voice": voice, "lines": [{"start": 0.5, "end": 1.5, "ja": "x", "ko": ko, "status": status}]}


def test_build_data_groups_by_directory_and_skips_untranslated_groups():
    scenes = {"groups": [
        {"id": "opsiho", "dir": "KAIWADIR/OPSIHO", "voices": ["MAI.AIF", "RIE.AIF"]},
        {"id": "pnsiho", "dir": "PANELDIR/PNSIHO", "voices": ["AMAI.AIF"]},
        {"id": "root", "dir": "", "voices": ["WATASHI.AIF"]},
    ]}
    docs = {"KAIWADIR/OPSIHO/MAI.AIF": _doc("KAIWADIR/OPSIHO/MAI.AIF", status="distribution_eligible"),
            "WATASHI.AIF": _doc("WATASHI.AIF", status="distribution_eligible")}
    index, subdat, info = S.build_data(scenes, docs, label.DEFAULT_FONT, _fake_lookup)
    magic, ngroups, _ = struct.unpack(">IHH", index[:8])
    assert ngroups == 2                                            # PNSIHO has no translated line
    dirs = [struct.unpack(">I", index[8 + 12 * i:12 + 12 * i])[0] for i in range(ngroups)]
    assert dirs == [51 + S.FAD_OFFSET, 20 + S.FAD_OFFSET]
    d0, o0, p0, n0 = struct.unpack(">IIHH", index[8:20])
    group = S.unpack(subdat[o0:o0 + p0])[0]
    assert _parse_group(group)[2] == [50359 + S.FAD_OFFSET, 50800 + S.FAD_OFFSET]   # RIE stays, with no cues
    assert info["lines"] == 2 and info["distribution"] is True
    assert [g["id"] for g in info["groups"]] == ["opsiho", "root"]


def test_build_data_refuses_stray_or_misnamed_translations():
    scenes = {"groups": [{"id": "opsiho", "dir": "KAIWADIR/OPSIHO", "voices": ["MAI.AIF"]}]}
    with pytest.raises(S.SubtitleError, match="outside every group"):
        S.build_data(scenes, {"WATASHI.AIF": _doc("WATASHI.AIF")}, label.DEFAULT_FONT, _fake_lookup)
    with pytest.raises(S.SubtitleError, match="twice"):
        S.build_data({"groups": scenes["groups"] * 2}, {}, label.DEFAULT_FONT, _fake_lookup)


def test_build_data_is_not_for_distribution_while_lines_wait_for_review():
    scenes = {"groups": [{"id": "opsiho", "dir": "KAIWADIR/OPSIHO", "voices": ["MAI.AIF"]}]}
    docs = {"KAIWADIR/OPSIHO/MAI.AIF": _doc("KAIWADIR/OPSIHO/MAI.AIF")}
    _, _, info = S.build_data(scenes, docs, label.DEFAULT_FONT, _fake_lookup)
    assert info["distribution"] is False and info["status"] == {"needs_review": 1}


def test_load_voice_docs_keys_by_disc_path(tmp_path):
    import json
    p = tmp_path / "KAIWADIR" / "OPSIHO"
    p.mkdir(parents=True)
    (p / "MAI.json").write_text(json.dumps(_doc("KAIWADIR/OPSIHO/MAI.AIF")), encoding="utf-8")
    (tmp_path / "WATASHI.json").write_text(json.dumps(_doc("watashi.aif")), encoding="utf-8")
    docs = S.load_voice_docs(tmp_path)
    assert set(docs) == {"KAIWADIR/OPSIHO/MAI.AIF", "WATASHI.AIF"}
    (tmp_path / "BAD.json").write_text(json.dumps(_doc("KAIWADIR/OPSIHO/MAI.AIF")), encoding="utf-8")
    with pytest.raises(S.SubtitleError, match="file"):
        S.load_voice_docs(tmp_path)


def test_provisional_lines_may_ship_but_are_counted_and_never_audio_verified():
    scenes = {"groups": [{"id": "opsiho", "dir": "KAIWADIR/OPSIHO", "voices": ["MAI.AIF"]}]}
    doc = {"voice": "KAIWADIR/OPSIHO/MAI.AIF", "audio_verified": False, "lines": [
        {"start": 0.5, "end": 1.5, "ja": "x", "ko": "가", "status": "distribution_eligible"},
        {"start": 2.0, "end": 3.0, "ja": "y", "ko": "나", "status": "provisional", "asr_uncertain": True}]}
    _, _, info = S.build_data(scenes, {"KAIWADIR/OPSIHO/MAI.AIF": doc}, label.DEFAULT_FONT, _fake_lookup)
    assert info["distribution"] is True
    assert info["provisional"] == 1 and info["audio_verified_lines"] == 0
    doc["lines"][0]["status"] = "needs_human_review"
    _, _, info = S.build_data(scenes, {"KAIWADIR/OPSIHO/MAI.AIF": doc}, label.DEFAULT_FONT, _fake_lookup)
    assert info["distribution"] is False


def test_audio_verified_is_counted_only_where_a_file_says_so():
    scenes = {"groups": [{"id": "opsiho", "dir": "KAIWADIR/OPSIHO", "voices": ["MAI.AIF", "RIE.AIF"]}]}
    a = {"voice": "KAIWADIR/OPSIHO/MAI.AIF", "audio_verified": True,
         "lines": [{"start": 0.5, "end": 1.5, "ja": "x", "ko": "가", "status": "distribution_eligible"}]}
    b = {"voice": "KAIWADIR/OPSIHO/RIE.AIF",
         "lines": [{"start": 0.5, "end": 1.5, "ja": "x", "ko": "나", "status": "distribution_eligible"}]}
    _, _, info = S.build_data(scenes, {a["voice"]: a, b["voice"]: b}, label.DEFAULT_FONT, _fake_lookup)
    assert info["audio_verified_lines"] == 1
