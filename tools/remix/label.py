"""Graphic-text editing on palette-index textures: clean the source text, draw Korean.

Text is rendered with anti-aliasing and mapped onto palette indices: coverage >= CORE -> fill,
SOFT <= coverage < CORE -> edge (or fill when no edge index is given), optional one-pixel outline
ring around the glyphs. Only pixels inside the given box are written.
"""
from collections import Counter

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage

DEFAULT_FONT = "/usr/share/fonts/truetype/nanum/NanumSquareRoundEB.ttf"
CORE, SOFT = 150, 60


class LabelError(ValueError):
    pass


def _check_glyphs(font: ImageFont.FreeTypeFont, text: str) -> None:
    ref = font.getmask("￿")
    ref = (ref.size, bytes(ref))
    bad = [c for c in set(text) if not c.isspace() and (font.getmask(c).size, bytes(font.getmask(c))) == ref]
    if bad:
        raise LabelError(f"font has no glyph for {''.join(sorted(bad))!r}")


def draw_text(pixels: np.ndarray, text: str, box: tuple[int, int, int, int], size: int, fill,
              edge=None, outline: int | None = None, align: str = "center",
              dx: int = 0, dy: int = 0, font: str = DEFAULT_FONT, rings: list[int] | None = None,
              inner: int | None = None) -> np.ndarray:
    """box = (x0, y0, x1, y1), exclusive end. fill/edge: an index, or one index per box row
    (vertical gradient). rings: indices of successive one-pixel rings around the glyphs, innermost
    first (outline=n is rings=[n]). inner: index for core pixels whose four neighbours are also
    core (a centre line on bold glyphs). Returns a new array."""
    rings = list(rings or []) + ([outline] if outline is not None else [])
    f = ImageFont.truetype(font, size)
    _check_glyphs(f, text)
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    l, t, r, b = f.getbbox(text)
    pad = len(rings)
    if r - l + 2 * pad > w or b - t + 2 * pad > h:
        raise LabelError(f"{text!r} at {size}px ({r - l}x{b - t}) does not fit the {w}x{h} box")
    if align == "center":
        tx = (w - (r - l)) / 2 - l
    elif align == "left":
        tx = pad - l
    elif align == "right":
        tx = w - pad - r
    else:
        raise LabelError(f"unknown align {align}")
    ty = (h - (b - t)) / 2 - t
    im = Image.new("L", (w, h))
    ImageDraw.Draw(im).text((round(tx) + dx, round(ty) + dy), text, font=f, fill=255)
    cov = np.array(im)
    ink = cov >= SOFT
    if pad:
        border = np.zeros_like(ink)
        border[0] = border[-1] = True
        border[:, 0] = border[:, -1] = True
        if (ink & border).any() or (pad > 1 and (ndimage.binary_dilation(ink, iterations=pad - 1) & border).any()):
            raise LabelError(f"{text!r}: rings would leave the box")

    def per_row(v):
        if isinstance(v, (list, tuple)):
            if len(v) != h:
                raise LabelError(f"gradient has {len(v)} rows, box has {h}")
            return np.broadcast_to(np.array(v, np.uint8)[:, None], (h, w))
        return np.full((h, w), v, np.uint8)

    fills = per_row(fill)
    edges = fills if edge is None else per_row(edge)
    out = pixels.copy()
    sub = out[y0:y1, x0:x1]
    covered = ink
    for idx in rings:
        ring = ndimage.binary_dilation(covered) & ~covered
        sub[ring] = idx
        covered = covered | ring
    soft = (cov >= SOFT) & (cov < CORE)
    sub[soft] = edges[soft]
    core = cov >= CORE
    sub[core] = fills[core]
    if inner is not None:
        sub[ndimage.binary_erosion(core)] = inner
    return out


def fit_size(text: str, box: tuple[int, int, int, int], size: int, minimum: int, rings: int = 0,
             font: str = DEFAULT_FONT) -> int:
    """Largest size <= size (down to minimum) at which text plus rings fits the box."""
    w, h = box[2] - box[0], box[3] - box[1]
    for s in range(size, minimum - 1, -1):
        l, t, r, b = ImageFont.truetype(font, s).getbbox(text)
        if r - l + 2 * rings <= w and b - t + 2 * rings <= h:
            return s
    raise LabelError(f"{text!r} does not fit the {w}x{h} box even at {minimum}px")


def clean(pixels: np.ndarray, spec: dict, box: tuple[int, int, int, int],
          source: np.ndarray | None = None) -> np.ndarray:
    """Remove source text inside box. spec: {"method": "copy"} (from source, same shape),
    {"method": "fill", "index": n}, {"method": "column", "ref_x": x} (every column takes column x),
    {"method": "rows", "text_idx": [...]} (each text pixel takes
    the most common non-text index of its row inside the box)."""
    x0, y0, x1, y1 = box
    out = pixels.copy()
    m = spec["method"]
    if m == "copy":
        if source is None or source.shape != pixels.shape:
            raise LabelError("copy clean needs a source texture of the same size")
        out[y0:y1, x0:x1] = source[y0:y1, x0:x1]
    elif m == "column":
        out[y0:y1, x0:x1] = pixels[y0:y1, spec["ref_x"]][:, None]
    elif m == "fill":
        out[y0:y1, x0:x1] = spec["index"]
    elif m == "rows":
        text = set(spec["text_idx"])
        for y in range(y0, y1):
            row = out[y, x0:x1]
            bg = [int(v) for v in row if int(v) not in text]
            if not bg and any(int(v) in text for v in row):
                raise LabelError(f"row {y} has no background pixel to restore from")
            if bg:
                fill = Counter(bg).most_common(1)[0][0]
                row[np.isin(row, list(text))] = fill
    else:
        raise LabelError(f"unknown clean method {m}")
    return out
