"""Opening big letters (TITL_CG.CX #5-#16, survey 3.4): Korean glyphs in the original cell styles.

Scroll letters (#5-#10) use a bevel made of the indices the original glyphs use: outline 13,
highlight 14/1/2/3 toward the top-left, body 4, shadow 9/7/5 toward the bottom-right.
Art letters (#11-#16) show character art inside the glyph on background index 15; the art is the
original cell's own pixels, extended to the new glyph shape by mirroring the art across its edge
(nearest original pixel where the mirror image falls outside the art).
"""
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage

FONT = "/usr/share/fonts/truetype/nanum/NanumSquareRoundEB.ttf"

BEVEL_OUTLINE = 13
BEVEL_HIGHLIGHT = (14, 1, 2, 3)   # depth 1..4 from a top/left edge
BEVEL_SHADOW = (9, 7, 5)          # depth 1..3 from a bottom/right edge
BEVEL_BODY = 4
ART_BACKGROUND = 15


class BigLetterError(ValueError):
    pass


def _disk(r: int) -> np.ndarray:
    y, x = np.ogrid[-r:r + 1, -r:r + 1]
    return x * x + y * y <= r * r + r


def _render(text: str, size: int, bold: int = 0) -> np.ndarray:
    """Glyph mask cropped to its ink; bold = extra stroke radius in pixels (round dilation)."""
    font = ImageFont.truetype(FONT, size)
    l, t, r, b = font.getbbox(text)
    pad = 2 + bold
    im = Image.new("L", (r - l + 2 * pad, b - t + 2 * pad))
    ImageDraw.Draw(im).text((pad - l, pad - t), text, font=font, fill=255)
    a = np.array(im) >= 128
    if bold:
        a = ndimage.binary_dilation(a, structure=_disk(bold))
    ys, xs = np.nonzero(a)
    return a[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def glyph_mask(text: str, width: int, height: int, size: int | None, margin: int, bold: int = 0) -> np.ndarray:
    """Glyph mask centered in a width x height cell; size None = largest that fits the margins."""
    room_w, room_h = width - 2 * margin, height - 2 * margin
    if size is None:
        size = 8
        while True:
            g = _render(text, size + 1, bold)
            if g.shape[1] > room_w or g.shape[0] > room_h:
                break
            size += 1
    g = _render(text, size, bold)
    if g.shape[1] > room_w or g.shape[0] > room_h:
        raise BigLetterError(f"{text!r} at {size}px ({g.shape[1]}x{g.shape[0]}) overflows {width}x{height}")
    out = np.zeros((height, width), bool)
    y0, x0 = (height - g.shape[0]) // 2, (width - g.shape[1]) // 2
    out[y0:y0 + g.shape[0], x0:x0 + g.shape[1]] = g
    return out


def _shift(m: np.ndarray, d: int) -> np.ndarray:
    """mask value at (y - d, x - d); outside the image counts as empty."""
    out = np.zeros_like(m)
    h, w = m.shape
    if d >= 0:
        out[d:, d:] = m[:h - d, :w - d]
    else:
        out[:h + d, :w + d] = m[-d:, -d:]
    return out


def bevel(mask: np.ndarray) -> np.ndarray:
    out = np.zeros(mask.shape, np.uint8)
    out[ndimage.binary_dilation(mask) & ~mask] = BEVEL_OUTLINE
    out[mask] = BEVEL_BODY
    for k in range(len(BEVEL_SHADOW), 0, -1):          # deeper first, shallower overwrite
        out[mask & ~_shift(mask, -k)] = BEVEL_SHADOW[k - 1]
    for k in range(len(BEVEL_HIGHLIGHT), 0, -1):
        out[mask & ~_shift(mask, k)] = BEVEL_HIGHLIGHT[k - 1]
    return out


def art_fill(art: np.ndarray, new_mask: np.ndarray) -> np.ndarray:
    old = art != ART_BACKGROUND
    if not old.any():
        raise BigLetterError("original cell has no art pixels")
    _, (iy, ix) = ndimage.distance_transform_edt(~old, return_indices=True)
    h, w = art.shape
    py, px = np.indices(art.shape)
    # mirror across the edge of the original art: p -> 2q - p + sign(p - q)
    ry = 2 * iy - py + np.sign(py - iy)
    rx = 2 * ix - px + np.sign(px - ix)
    inside = (ry >= 0) & (ry < h) & (rx >= 0) & (rx < w)
    ry, rx = np.where(inside, ry, iy), np.where(inside, rx, ix)
    mirrored = art[ry, rx]
    fill = np.where(mirrored != ART_BACKGROUND, mirrored, art[iy, ix])
    out = np.full(art.shape, ART_BACKGROUND, np.uint8)
    out[new_mask] = np.where(old, art, fill)[new_mask]
    return out
