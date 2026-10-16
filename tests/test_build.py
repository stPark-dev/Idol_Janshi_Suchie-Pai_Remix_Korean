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
    build.build(SOURCE, out, title="original")
    m = json.loads((out / "manifest.json").read_text())
    data = out / m["data_file"]
    h = hashlib.sha1()
    with open(data, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    assert h.hexdigest() == m["source_data_sha1"]
    assert m["changes"] == []


@needs_source
def test_korean_build_changes_only_title_logo(tmp_path):
    out = tmp_path / "ko"
    build.build(SOURCE, out)
    m = json.loads((out / "manifest.json").read_text())
    assert [c["writer"] for c in m["changes"]] == ["title_logo"]
    ko = build.SourceDisc.open(out / m["cue"], check_hash=False)
    c = cx.Container.parse(ko.read_file("TITL_CG.CX"))
    for idx, (w, h) in build.LOGO_CELLS.items():
        img = cx.unpack_entry(c.entries[idx])
        assert (img[0] * 8, img[1]) == (w, h)
    orig = cx.Container.parse(build.SourceDisc.open(SOURCE).read_file("TITL_CG.CX"))
    keep = [i for i in range(len(c.entries)) if i not in build.LOGO_CELLS]
    assert all(c.entries[i] == orig.entries[i] for i in keep)
    # directory size and sector protection of every written sector
    data = ko.read_file("TITL_CG.CX")
    assert ko.lookup("TITL_CG.CX").size == len(data)
    assert hashlib.sha1(data).hexdigest() == build.TITLE_KO_SHA1
    r = ko.lookup("TITL_CG.CX")
    for lba in [r.dir_lba] + list(range(r.lba, r.lba + (r.size + 2047) // 2048)):
        sec = ko.raw_sector(lba)
        assert bytes(cdsector.fix_mode1(bytearray(sec))) == sec


def test_directory_patches_merge_per_sector():
    a = build.DirPatch()
    sec = bytes(2048)
    a.add(23, 0x10, sec, lambda s: s[:0x10] + b"\x01" + s[0x11:])
    a.add(23, 0x40, sec, lambda s: s[:0x40] + b"\x02" + s[0x41:])
    merged = a.sectors()
    assert list(merged) == [23]
    assert merged[23][0x10] == 1 and merged[23][0x40] == 2
