import numpy as np
import pytest

from remix import credits, cx


def _page(w=16, h=8, fill=0, mark=None):
    px = np.full((h, w), fill, np.uint8)
    if mark:
        y, x, v = mark
        px[y, x] = v
    return bytes([w // 8, h]) + px.tobytes()


def test_stack_and_split_round_trip():
    pages = [_page(mark=(1, 1, 5)), _page(mark=(7, 15, 6))]
    tall = credits.stack(pages)
    assert tall.shape == (16, 16) and tall[1, 1] == 5 and tall[15, 15] == 6
    assert credits.split(tall, pages) == pages


def test_split_rejects_changed_height():
    pages = [_page(), _page()]
    with pytest.raises(credits.CreditsError):
        credits.split(np.zeros((15, 16), np.uint8), pages)


def test_draw_line_spanning_a_page_boundary():
    pages = [_page(w=64, h=20), _page(w=64, h=20)]
    tall = credits.stack(pages)
    style = {"size": 14, "fill": 12, "edge": 11, "rings": [10]}
    out = credits.draw_line(tall, {"y0": 12, "y1": 28, "ko": "가나"}, style, width=64)
    assert (out[12:20] != 0).any() and (out[20:28] != 0).any()
    assert not (out[:11] != 0).any()


def test_draw_line_rejects_overflow():
    tall = np.zeros((20, 32), np.uint8)
    with pytest.raises(credits.CreditsError):
        credits.draw_line(tall, {"y0": 0, "y1": 12, "ko": "가나다라마바사"}, {"size": 12, "fit": 12, "fill": 1}, width=32)
