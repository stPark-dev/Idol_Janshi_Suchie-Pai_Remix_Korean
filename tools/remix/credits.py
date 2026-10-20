"""Staff roll (BADGRAPH.CX #0-#16 = GOODEND.CX #7-#23, docs/initial-survey.md 3.14).

The roll is 17 single images (152x240, 8bpp, transparent background) shown one after another,
so lines can cross a page boundary. Pages are stacked into one tall image, lines are redrawn at
their original rows, and the tall image is cut back into pages of the original sizes.
"""
import numpy as np

from . import label


class CreditsError(ValueError):
    pass


def stack(pages: list[bytes]) -> np.ndarray:
    imgs = []
    for raw in pages:
        w, h = raw[0] * 8, raw[1]
        if len(raw) != 2 + w * h:
            raise CreditsError("credit page is not an 8bpp single image")
        imgs.append(np.frombuffer(raw[2:], np.uint8).reshape(h, w))
    if len({i.shape[1] for i in imgs}) != 1:
        raise CreditsError("credit pages differ in width")
    return np.vstack(imgs).copy()


def split(tall: np.ndarray, pages: list[bytes]) -> list[bytes]:
    heights = [raw[1] for raw in pages]
    if tall.shape[0] != sum(heights):
        raise CreditsError("tall image height changed")
    out, y = [], 0
    for raw, h in zip(pages, heights):
        out.append(bytes([raw[0], h]) + tall[y:y + h].astype(np.uint8).tobytes())
        y += h
    return out


def draw_line(tall: np.ndarray, line: dict, style: dict, width: int) -> np.ndarray:
    """line: {"y0", "y1", "ko", optional "x0"/"x1"/"align"}; style: label.draw_text options."""
    box = (line.get("x0", 0), line["y0"], line.get("x1", width), line["y1"])
    size = style["size"]
    rings = style.get("rings") or []
    try:
        if "fit" in style:
            size = label.fit_size(line["ko"], box, size, style["fit"], len(rings), style.get("font", label.DEFAULT_FONT))
        return label.draw_text(tall, line["ko"], box, size, style["fill"], style.get("edge"),
                               align=line.get("align", style.get("align", "center")),
                               font=style.get("font", label.DEFAULT_FONT), rings=rings)
    except label.LabelError as e:
        raise CreditsError(f"line at rows {line['y0']}-{line['y1']}: {e}") from None
