import numpy as np
import pytest

from remix import label

FONT = label.DEFAULT_FONT


def test_draw_text_stays_inside_box_and_uses_given_indices():
    a = np.full((40, 40), 7, np.uint8)
    out = label.draw_text(a, "가", box=(5, 5, 30, 30), size=18, fill=1, edge=2)
    changed = out != a
    ys, xs = np.nonzero(changed)
    assert xs.min() >= 5 and xs.max() < 30 and ys.min() >= 5 and ys.max() < 30
    assert set(np.unique(out[changed])) <= {1, 2}
    assert (out == 1).sum() > 30


def test_draw_text_outline_ring():
    a = np.zeros((30, 30), np.uint8)
    out = label.draw_text(a, "ㅁ", box=(0, 0, 30, 30), size=20, fill=1, outline=5)
    assert (out == 5).any() and (out == 1).any()


def test_draw_text_rejects_overflow():
    with pytest.raises(label.LabelError, match="does not fit"):
        label.draw_text(np.zeros((10, 10), np.uint8), "가나다", box=(0, 0, 10, 10), size=12, fill=1)


def test_draw_text_rejects_missing_glyph():
    with pytest.raises(label.LabelError, match="glyph"):
        label.draw_text(np.zeros((40, 40), np.uint8), "一", box=(0, 0, 40, 40), size=16, fill=1)


def test_draw_text_alignment_left():
    a = np.zeros((20, 60), np.uint8)
    out = label.draw_text(a, "가", box=(0, 0, 60, 20), size=14, fill=1, align="left")
    xs = np.nonzero(out)[1]
    assert xs.min() <= 2


def test_clean_copy_and_fill():
    a = np.full((4, 4), 9, np.uint8)
    src = np.arange(16, dtype=np.uint8).reshape(4, 4)
    out = label.clean(a, {"method": "copy"}, box=(1, 1, 3, 3), source=src)
    assert out[1, 1] == 5 and out[0, 0] == 9
    out = label.clean(a, {"method": "fill", "index": 3}, box=(0, 0, 2, 2))
    assert out[1, 1] == 3 and out[2, 2] == 9


def test_clean_rows_replaces_text_indices_with_row_background():
    a = np.array([[4, 4, 1, 4, 4],
                  [6, 1, 1, 1, 6]], np.uint8)
    out = label.clean(a, {"method": "rows", "text_idx": [1]}, box=(0, 0, 5, 2))
    assert out.tolist() == [[4, 4, 4, 4, 4], [6, 6, 6, 6, 6]]


def test_clean_rows_rejects_row_without_background():
    with pytest.raises(label.LabelError):
        label.clean(np.ones((1, 3), np.uint8), {"method": "rows", "text_idx": [1]}, box=(0, 0, 3, 1))


def test_draw_text_rings_layer_outward():
    a = np.zeros((40, 40), np.uint8)
    out = label.draw_text(a, "ㅣ", box=(0, 0, 40, 40), size=24, fill=1, rings=[5, 6])
    ys, xs = np.nonzero(out == 1)
    y = int(np.median(ys))
    row = out[y]
    xs1 = np.nonzero(row == 1)[0]
    assert row[xs1.min() - 1] == 5 and row[xs1.min() - 2] == 6
    assert row[xs1.max() + 1] == 5 and row[xs1.max() + 2] == 6


def test_draw_text_fill_gradient_by_row():
    a = np.zeros((30, 30), np.uint8)
    grad = [10 + y for y in range(30)]
    out = label.draw_text(a, "ㅁ", box=(0, 0, 30, 30), size=22, fill=grad)
    for y in range(30):
        vals = set(np.unique(out[y])) - {0}
        assert vals <= {10 + y}


def test_draw_text_rings_must_fit_box():
    with pytest.raises(label.LabelError, match="does not fit"):
        label.draw_text(np.zeros((16, 16), np.uint8), "가", box=(0, 0, 16, 16), size=15, fill=1, rings=[2, 3])


def test_draw_text_inner_marks_eroded_core():
    a = np.zeros((40, 40), np.uint8)
    out = label.draw_text(a, "ㅁ", box=(0, 0, 40, 40), size=34, fill=1, inner=9)
    assert (out == 9).any() and (out == 1).any()
    ys, xs = np.nonzero(out == 9)
    for y, x in zip(ys, xs):                       # inner pixels are surrounded by glyph pixels
        assert all(out[y + dy, x + dx] in (1, 9) for dy, dx in ((0, 1), (1, 0), (0, -1), (-1, 0)))


def test_clean_column_copies_reference_column():
    a = np.array([[1, 2, 9, 9, 3],
                  [4, 5, 9, 9, 6]], np.uint8)
    out = label.clean(a, {"method": "column", "ref_x": 1}, box=(2, 0, 4, 2))
    assert out.tolist() == [[1, 2, 2, 2, 3], [4, 5, 5, 5, 6]]


def test_fit_size_shrinks_until_it_fits():
    assert label.fit_size("물고기자리", (0, 0, 48, 12), 12, minimum=7, rings=1) < 12
    with pytest.raises(label.LabelError):
        label.fit_size("물고기자리물고기자리", (0, 0, 20, 12), 12, minimum=7)


def test_draw_text_shadow_sits_below_right_of_glyph():
    a = np.zeros((40, 40), np.uint8)
    out = label.draw_text(a, "ㅣ", box=(0, 0, 40, 40), size=30, fill=1, shadow={"idx": 7, "dx": 2, "dy": 2})
    ys, xs = np.nonzero(out == 7)
    gy, gx = np.nonzero(out == 1)
    assert len(ys) and xs.max() > gx.max() and ys.max() > gy.max()


def test_draw_text_bold_thickens():
    a = np.zeros((40, 40), np.uint8)
    thin = label.draw_text(a, "ㅣ", box=(0, 0, 40, 40), size=26, fill=1)
    bold = label.draw_text(a, "ㅣ", box=(0, 0, 40, 40), size=26, fill=1, bold=2)
    assert (bold == 1).sum() > (thin == 1).sum()


def test_draw_text_extruded_shadow_fills_every_offset_and_bottom_edge():
    a = np.zeros((40, 40), np.uint8)
    out = label.draw_text(a, "ㅡ", box=(0, 0, 40, 40), size=30, fill=1,
                          shadow={"idx": 7, "dx": 0, "dy": 4, "extrude": True, "edge": 8})
    ys, xs = np.nonzero(out == 1)
    x = int(np.median(xs))
    col = out[:, x].tolist()
    bottom = max(y for y in range(40) if col[y] == 1)
    assert col[bottom + 1:bottom + 5] == [7, 7, 7, 7] and col[bottom + 5] == 8


def test_clean_rowmode_flattens_each_row_to_its_most_common_index():
    a = np.array([[1, 2, 1, 1], [3, 3, 9, 4]], np.uint8)
    out = label.clean(a, {"method": "rowmode"}, box=(0, 0, 4, 2))
    assert out.tolist() == [[1, 1, 1, 1], [3, 3, 3, 3]]
