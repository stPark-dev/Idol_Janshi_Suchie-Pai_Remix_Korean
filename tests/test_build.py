"""Integration tests on the real source disc (skipped when it is not present).

Source: REMIX_SOURCE (a .cue) or work/disc/remix.cue (chdman extractcd of the supported CHD).
"""
import hashlib
import json
import os
import pathlib

import pytest

from remix import build, cdsector, cx

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = pathlib.Path(os.environ.get("REMIX_SOURCE", ROOT / "work/disc/remix.cue"))
needs_source = pytest.mark.skipif(not SOURCE.exists(), reason="source disc not present")


@pytest.fixture(scope="module")
def disc():
    return build.SourceDisc.open(SOURCE)


@needs_source
def test_source_track1_hash_is_checked(disc):
    assert disc.track1_sha1 == build.TRACK1_SHA1


@needs_source
def test_every_cx_entry_round_trips_through_our_codec(disc):
    for path in build.CX_FILES:
        data = disc.read_file(path)
        c = cx.Container.parse(data)
        assert c.build() == data
        for i, e in enumerate(c.entries):
            if int.from_bytes(e[:2], "big") not in (cx.KIND_BYTE, cx.KIND_WORD) or build.is_raw_bank(e):
                continue
            raw = cx.unpack_entry(e)
            kind = int.from_bytes(e[:2], "big")
            assert cx.unpack_entry(cx.pack_entry(kind, raw)) == raw, (path, i)


@needs_source
def test_control_build_is_identical_to_source(tmp_path):
    out = tmp_path / "control"
    build.build(SOURCE, out, title="original", opening="original", graphics="original")
    m = json.loads((out / "manifest.json").read_text())
    data = out / m["data_file"]
    h = hashlib.sha1()
    with open(data, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    assert h.hexdigest() == m["source_data_sha1"]
    assert m["changes"] == []


def _korean(tmp_path, **kw):
    out = tmp_path / "ko"
    build.build(SOURCE, out, **kw)
    m = json.loads((out / "manifest.json").read_text())
    ko = build.SourceDisc.open(out / m["cue"], check_hash=False)
    return m, ko


@needs_source
def test_logo_only_build_matches_screen_verified_hash(tmp_path):
    m, ko = _korean(tmp_path, opening="original", graphics="original")
    assert [c["writer"] for c in m["changes"]] == ["title_cg"]
    c = cx.Container.parse(ko.read_file("TITL_CG.CX"))
    orig = cx.Container.parse(build.SourceDisc.open(SOURCE).read_file("TITL_CG.CX"))
    for idx, (w, h) in build.LOGO_CELLS.items():
        img = cx.unpack_entry(c.entries[idx])
        assert (img[0] * 8, img[1]) == (w, h)
    keep = [i for i in range(len(c.entries)) if i not in build.LOGO_CELLS]
    assert all(c.entries[i] == orig.entries[i] for i in keep)
    data = ko.read_file("TITL_CG.CX")
    assert build.title_cells_sha1(data) == build.TITL_CG_CELLS_SHA1[("korean", "original")]
    # directory size and sector protection of every written sector
    r = ko.lookup("TITL_CG.CX")
    assert r.size == len(data)
    for lba in [r.dir_lba] + list(range(r.lba, r.lba + (r.size + 2047) // 2048)):
        sec = ko.raw_sector(lba)
        assert bytes(cdsector.fix_mode1(bytearray(sec))) == sec


@needs_source
def test_opening_letters_replace_only_their_cells(tmp_path):
    m, ko = _korean(tmp_path, unverified=True)
    assert m["unverified"] is True and m["distribution"] is False
    c = cx.Container.parse(ko.read_file("TITL_CG.CX"))
    orig = cx.Container.parse(build.SourceDisc.open(SOURCE).read_file("TITL_CG.CX"))
    changed = set(build.LOGO_CELLS) | set(build.SCROLL_LETTERS) | set(build.ART_LETTERS) | {
        e["cx_entry"] for e in build.load_tables()[0] if e["file"] == "TITL_CG.CX"}
    for i in range(len(c.entries)):
        if i in changed:
            a, b = cx.unpack_entry(c.entries[i]), cx.unpack_entry(orig.entries[i])
            assert a[:2] == b[:2] and len(a) == len(b)       # same cell size and 4bpp
            assert a != b
        else:
            assert c.entries[i] == orig.entries[i], i
    blank = cx.parse_image_4bpp(cx.unpack_entry(c.entries[10]))[2]
    assert set(blank) == {0}                                  # 士 cell left empty


@needs_source
def test_unverified_combination_is_refused_without_flag(tmp_path):
    assert ("original", "korean") not in build.TITL_CG_CELLS_SHA1
    with pytest.raises(build.BuildError, match="verified"):
        build.build(SOURCE, tmp_path / "x", title="original", opening="korean")


def test_directory_patches_merge_per_sector():
    a = build.DirPatch()
    sec = bytes(2048)
    a.add(23, 0x10, sec, lambda s: s[:0x10] + b"\x01" + s[0x11:])
    a.add(23, 0x40, sec, lambda s: s[:0x40] + b"\x02" + s[0x41:])
    merged = a.sectors()
    assert list(merged) == [23]
    assert merged[23][0x10] == 1 and merged[23][0x40] == 2


@needs_source
def test_select_graphics_change_only_listed_textures(tmp_path):
    from remix import bank
    m, ko = _korean(tmp_path)
    assert "gfx:SELECT.CX" in [c["writer"] for c in m["changes"]]
    src = build.SourceDisc.open(SOURCE)
    new_c = cx.Container.parse(ko.read_file("SELECT.CX"))
    old_c = cx.Container.parse(src.read_file("SELECT.CX"))
    assert len(ko.read_file("SELECT.CX")) == len(src.read_file("SELECT.CX"))
    touched: dict[int, set[int]] = {}
    for e in build.load_tables()[0]:
        if e["file"] != "SELECT.CX":
            continue
        touched.setdefault(e["cx_entry"], set()).update(e["tex"])
    for i, (a, b) in enumerate(zip(new_c.entries, old_c.entries)):
        if i not in touched:
            assert a == b, i
            continue
        na, ob = bank.Bank.parse(a), bank.Bank.parse(b)
        for t in range(len(ob.textures)):
            if t not in touched[i]:
                assert (na.get(t) == ob.get(t)).all(), (i, t)


def test_tables_have_one_layout_per_entry_and_known_states():
    entries, layouts = build.load_tables()
    assert sorted(e["id"] for e in entries) == sorted(layouts)
    assert all(e["state"] in build.STATES for e in entries)
    assert all(e["file"] in build.ORIGINAL_SHA1 for e in entries)


@needs_source
def test_round_plates_keep_their_frame_rows(tmp_path):
    """column clean must copy a straight-section column: frame rows 4/21 stay opaque frame colour"""
    from remix import bank
    m, ko = _korean(tmp_path)
    entries, layouts = build.load_tables(("round",))
    for e in entries:
        if ".plate." not in e["id"]:
            continue
        a = bank.Bank.parse(ko.read_file(e["file"])).get(e["tex"][0])
        x0, _, x1, _ = layouts[e["id"]]["clean"]["box"]
        for y in (4, 21):
            assert (a[y, x0:x1] != 0).all(), (e["id"], y)


@needs_source
def test_title_table_entries_apply_on_top_of_verified_cells(tmp_path):
    m, ko = _korean(tmp_path)
    data = ko.read_file("TITL_CG.CX")
    assert build.title_cells_sha1(data) == build.TITL_CG_CELLS_SHA1[("korean", "korean")]
    assert [c["writer"] for c in m["changes"]].count("title_cg") == 1


@needs_source
def test_credits_same_in_both_files_and_only_roll_pages_change(tmp_path):
    m, ko = _korean(tmp_path)
    src = build.SourceDisc.open(SOURCE)
    nb = cx.Container.parse(ko.read_file("BADGRAPH.CX"))
    ng = cx.Container.parse(ko.read_file("GOODEND/GOODEND.CX"))
    ob = cx.Container.parse(src.read_file("BADGRAPH.CX"))
    og = cx.Container.parse(src.read_file("GOODEND/GOODEND.CX"))
    for i in range(17):
        assert cx.unpack_entry(nb.entries[i]) == cx.unpack_entry(ng.entries[i + 7])
        assert cx.unpack_entry(nb.entries[i]) != cx.unpack_entry(ob.entries[i])
    assert all(nb.entries[i] == ob.entries[i] for i in range(17, len(ob.entries)))
    assert all(ng.entries[i] == og.entries[i] for i in list(range(7)) + list(range(24, len(og.entries))))


def test_distribution_requires_eligible_texts_and_no_pending_screen_checks():
    assert build.distribution_ready([{"state": "distribution_eligible"}], {"pending": []}) is True
    assert build.distribution_ready([{"state": "distribution_eligible"}], {"pending": [{"id": "x"}]}) is False
    assert build.distribution_ready([{"state": "needs_human_review"}], {"pending": []}) is False
