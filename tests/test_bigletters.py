import numpy as np
import pytest

from remix import bigletters as bl


def _square(h=20, w=20, box=(5, 5, 15, 15)):
    m = np.zeros((h, w), bool)
    y0, x0, y1, x1 = box
    m[y0:y1, x0:x1] = True
    return m


def test_bevel_layers_follow_light_from_top_left():
    out = bl.bevel(_square())
    assert out[5, 10] == bl.BEVEL_HIGHLIGHT[0]       # top edge
    assert out[10, 5] == bl.BEVEL_HIGHLIGHT[0]       # left edge
    assert out[14, 10] == bl.BEVEL_SHADOW[0]         # bottom edge
    assert out[10, 14] == bl.BEVEL_SHADOW[0]         # right edge
    assert out[10, 10] == bl.BEVEL_BODY              # deep interior
    assert out[4, 10] == bl.BEVEL_OUTLINE            # one pixel outside
    assert out[0, 0] == 0                            # transparent elsewhere


def test_bevel_uses_only_original_letter_indices():
    out = bl.bevel(_square())
    assert set(np.unique(out)) <= {0, bl.BEVEL_OUTLINE, bl.BEVEL_BODY, *bl.BEVEL_HIGHLIGHT, *bl.BEVEL_SHADOW}


def test_art_fill_keeps_original_inside_overlap_and_extends_outside():
    art = np.full((10, 10), bl.ART_BACKGROUND, np.uint8)
    art[2:8, 2:5] = 3          # original letter: left block of index 3
    art[2:8, 5:8] = 9          # and right block of index 9
    new_mask = np.zeros((10, 10), bool)
    new_mask[1:9, 4:9] = True  # Korean glyph overlaps partly, sticks out at top/bottom/right
    out = bl.art_fill(art, new_mask)
    assert out[3, 4] == 3 and out[3, 6] == 9          # overlap keeps original pixels
    assert out[1, 6] == 9 and out[8, 8] == 9          # outside original: nearest original pixel
    assert out[0, 0] == bl.ART_BACKGROUND and out[3, 2] == bl.ART_BACKGROUND  # outside new glyph
    assert set(np.unique(out)) <= {3, 9, bl.ART_BACKGROUND}


def test_art_fill_rejects_empty_original():
    with pytest.raises(bl.BigLetterError):
        bl.art_fill(np.full((4, 4), bl.ART_BACKGROUND, np.uint8), np.ones((4, 4), bool))


def test_glyph_mask_fits_cell_with_margin():
    m = bl.glyph_mask("돌", 128, 149, size=None, margin=4)
    ys, xs = np.nonzero(m)
    assert m.shape == (149, 128)
    assert xs.min() >= 4 and xs.max() <= 128 - 5 and ys.min() >= 4 and ys.max() <= 149 - 5
    assert max(xs.max() - xs.min(), ys.max() - ys.min()) >= 100   # actually fills the cell


def test_glyph_mask_fixed_size_is_centered():
    m = bl.glyph_mask("아", 144, 141, size=110, margin=4)
    ys, xs = np.nonzero(m)
    assert abs((xs.min() + xs.max()) / 2 - 71.5) <= 2
    assert abs((ys.min() + ys.max()) / 2 - 70) <= 2


def test_glyph_mask_rejects_overflow():
    with pytest.raises(bl.BigLetterError):
        bl.glyph_mask("돌", 128, 149, size=300, margin=4)


def test_bold_thickens_strokes_and_still_fits():
    thin = bl.glyph_mask("이", 144, 145, size=100, margin=4)
    bold = bl.glyph_mask("이", 144, 145, size=100, margin=4, bold=4)
    assert bold.sum() > thin.sum() * 1.3
    ys, xs = np.nonzero(bold)
    assert xs.min() >= 4 and ys.min() >= 4 and xs.max() <= 139 and ys.max() <= 140


def test_art_fill_mirrors_texture_across_the_edge():
    art = np.full((12, 12), bl.ART_BACKGROUND, np.uint8)
    for x in range(0, 6):
        art[:, x] = x            # vertical stripes 0..5 in the left half
    mask = np.zeros((12, 12), bool)
    mask[:, :9] = True           # glyph reaches 3 columns beyond the art
    out = bl.art_fill(art, mask)
    assert list(out[5, 6:9]) == [5, 4, 3]   # mirrored, not a repeated edge column
