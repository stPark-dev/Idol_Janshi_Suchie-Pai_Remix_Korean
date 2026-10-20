import hashlib
import struct

import numpy as np
import pytest

from remix import bank, gfxtext


def _bank(n: int, w: int = 24, h: int = 39, fill: int = 9) -> bank.Bank:
    hs = 8 + 8 * n
    head = b"".join(struct.pack(">HHI", w // 8, h, i * w * h) for i in range(n))
    return bank.Bank.parse(struct.pack(">IHH", hs, n, n) + head + bytes([fill]) * (w * h * n))


def _sha(b, tex):
    return hashlib.sha1(b"".join(b.get(t).tobytes() for t in tex)).hexdigest()


def _entry(b, tex, ko, **kw):
    return {"id": "x", "tex": tex, "src_sha1": _sha(b, tex), "ja": "ア", "ko": ko, "state": "needs_review", **kw}


def test_tiles_place_one_syllable_per_tile_and_blank_copies():
    b = _bank(4)
    blank = b.get(3)
    blank[0, 0] = 1
    b.set(3, blank)
    lay = {"id": "x", "kind": "tiles", "blank": 3, "box": [2, 13, 15, 29], "size": 14, "fill": 26, "edge": 30,
           "cells": "가_나"}
    gfxtext.apply(b, _entry(b, [0, 1, 2], "가 나"), lay)
    assert (b.get(1) == b.get(3)).all()                  # '_' = copy of the blank tile
    assert (b.get(0) == 26).any() and (b.get(2) == 26).any()
    assert b.get(0)[0, 0] == 1                           # glyph tiles start from the blank too


def test_tiles_reject_cells_that_do_not_match_translation():
    b = _bank(3)
    lay = {"id": "x", "kind": "tiles", "blank": 2, "box": [2, 13, 15, 29], "size": 14, "fill": 26, "cells": "가다"}
    with pytest.raises(gfxtext.GfxTextError, match="cells"):
        gfxtext.apply(b, _entry(b, [0, 1], "가나"), lay)


def test_text_cleans_then_draws_lines_inside_box():
    b = _bank(1, w=64, h=32, fill=4)
    a = b.get(0)
    a[10:20, 10:50] = 7          # fake source text
    b.set(0, a)
    lay = {"id": "x", "kind": "text", "tex": 0,
           "clean": {"method": "rows", "text_idx": [7], "box": [8, 8, 56, 24]},
           "lines": [{"box": [8, 8, 56, 24], "size": 13, "fill": 1, "edge": 2}]}
    gfxtext.apply(b, _entry(b, [0], "결정"), lay)
    out = b.get(0)
    assert not (out == 7).any()
    assert (out == 1).any()
    assert (out[:8] == 4).all() and (out[24:] == 4).all()


def test_text_line_count_must_match():
    b = _bank(1, w=64, h=32)
    lay = {"id": "x", "kind": "text", "tex": 0, "clean": {"method": "fill", "index": 0, "box": [0, 0, 64, 32]},
           "lines": [{"box": [0, 0, 64, 16], "size": 10, "fill": 1}]}
    with pytest.raises(gfxtext.GfxTextError, match="lines"):
        gfxtext.apply(b, _entry(b, [0], "가\n나"), lay)


def test_source_hash_mismatch_is_rejected():
    b = _bank(1, w=64, h=32)
    e = _entry(b, [0], "가")
    e["src_sha1"] = "0" * 40
    lay = {"id": "x", "kind": "text", "tex": 0, "clean": {"method": "fill", "index": 0, "box": [0, 0, 64, 32]},
           "lines": [{"box": [0, 0, 64, 32], "size": 12, "fill": 1}]}
    with pytest.raises(gfxtext.GfxTextError, match="source"):
        gfxtext.apply(b, e, lay)


def test_empty_translation_is_rejected():
    b = _bank(1, w=64, h=32)
    lay = {"id": "x", "kind": "text", "tex": 0, "clean": {"method": "fill", "index": 0, "box": [0, 0, 64, 32]},
           "lines": [{"box": [0, 0, 64, 32], "size": 12, "fill": 1}]}
    with pytest.raises(gfxtext.GfxTextError, match="translation"):
        gfxtext.apply(b, _entry(b, [0], ""), lay)


def test_apply_all_checks_ids_and_hashes_against_original():
    b = _bank(2, w=64, h=32)
    entries = [_entry(b, [0], "가") | {"id": "a"}, _entry(b, [0], "나") | {"id": "b"}]
    lays = [{"id": "a", "kind": "text", "tex": 0, "clean": {"method": "fill", "index": 0, "box": [0, 0, 64, 16]},
             "lines": [{"box": [0, 0, 64, 16], "size": 12, "fill": 1}]},
            {"id": "b", "kind": "text", "tex": 0, "clean": {"method": "fill", "index": 0, "box": [0, 16, 64, 32]},
             "lines": [{"box": [0, 16, 64, 32], "size": 12, "fill": 1}]}]
    gfxtext.apply_all(b, entries, lays)                  # two labels on one texture: both hashes vs original
    assert (b.get(0)[:16] != 9).any() and (b.get(0)[16:] != 9).any()
    with pytest.raises(gfxtext.GfxTextError, match="layout"):
        gfxtext.apply_all(_bank(1, w=64, h=32), entries[:1], [])


def test_tiles_take_blank_from_original_even_when_blank_is_overwritten_first():
    b = _bank(5)
    # row A uses tiles 0..2 and tile 2 is also the blank template; row B uses 3..4
    entries = [_entry(b, [0, 1, 2], "가나다") | {"id": "a"}, _entry(b, [3, 4], "라_".replace("_", "")) | {"id": "b"}]
    lays = [{"id": "a", "kind": "tiles", "blank": 2, "box": [2, 13, 15, 29], "size": 14, "fill": 26, "cells": "가나다"},
            {"id": "b", "kind": "tiles", "blank": 2, "box": [2, 13, 15, 29], "size": 14, "fill": 26, "cells": "라_"}]
    gfxtext.apply_all(b, entries, lays)
    assert (b.get(4) == 9).all()          # blank copy is the untouched original, not "다"
