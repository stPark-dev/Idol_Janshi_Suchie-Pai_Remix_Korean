"""Fit an owner-supplied logo into a fixed sprite cell and map it onto existing palette entries."""
from PIL import Image


class LogoError(ValueError):
    pass


def fit(src: Image.Image, width: int, height: int) -> Image.Image:
    """Crop transparent margins, scale to fit the cell keeping the aspect ratio, center it."""
    im = src.convert("RGBA")
    box = im.getbbox()
    if box is None:
        raise LogoError("logo image is fully transparent")
    im = im.crop(box)
    s = min(width / im.width, height / im.height)
    w, h = max(1, round(im.width * s)), max(1, round(im.height * s))
    im = im.resize((w, h), Image.LANCZOS)
    out = Image.new("RGBA", (width, height))
    out.paste(im, ((width - w) // 2, (height - h) // 2))
    return out


def quantize(im: Image.Image, palette: dict[int, tuple[int, int, int]]) -> list[int]:
    """Alpha < 128 -> index 0 (transparent); otherwise the nearest allowed palette index."""
    if 0 in palette or not palette:
        raise LogoError("palette must list opaque indices only (index 0 is transparent)")
    out = []
    for r, g, b, a in im.convert("RGBA").getdata():
        if a < 128:
            out.append(0)
            continue
        out.append(min(palette, key=lambda k: 3 * (palette[k][0] - r) ** 2
                       + 4 * (palette[k][1] - g) ** 2 + 2 * (palette[k][2] - b) ** 2))
    return out
