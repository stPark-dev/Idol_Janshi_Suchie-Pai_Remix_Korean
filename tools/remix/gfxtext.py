"""Apply translation entries to graphic text in a sprite bank (translation/*.json + assets/*/layout.json).

Layout kinds:
  tiles - one syllable per texture ("cells": "캐릭터_선택__", '_' = blank texture), every texture
          starts from the blank texture and the glyph is drawn inside "box".
  text  - clean the source text in one texture, then draw each line of the translation ('\\n').
"""
import hashlib

import numpy as np

from . import label
from .bank import Bank


class GfxTextError(ValueError):
    pass


def _sha(textures: dict[int, np.ndarray], tex: list[int]) -> str:
    return hashlib.sha1(b"".join(textures[t].tobytes() for t in tex)).hexdigest()


def apply(b: Bank, entry: dict, lay: dict, original: dict[int, np.ndarray] | None = None) -> None:
    orig = original or {t: b.get(t) for t in entry["tex"]}
    if _sha(orig, entry["tex"]) != entry["src_sha1"]:
        raise GfxTextError(f"{entry['id']}: source texture does not match src_sha1")
    ko = entry.get("ko", "")
    if not ko.strip() and not entry.get("blank"):
        raise GfxTextError(f"{entry['id']}: empty translation (set \"blank\": true to clear on purpose)")
    font = lay.get("font", label.DEFAULT_FONT)
    try:
        if lay["kind"] == "tiles":
            cells = lay["cells"]
            if len(cells) != len(entry["tex"]) or cells.replace("_", "") != ko.replace(" ", ""):
                raise GfxTextError(f"{entry['id']}: cells {cells!r} do not spell {ko!r} over {len(entry['tex'])} tiles")
            # the blank template may itself be one of the rewritten tiles: always start from the original
            blank = original[lay["blank"]] if original and lay["blank"] in original else b.get(lay["blank"])
            for t, ch in zip(entry["tex"], cells):
                px = blank if ch == "_" else label.draw_text(blank, ch, tuple(lay["box"]), lay["size"],
                                                             lay["fill"], lay.get("edge"), lay.get("outline"),
                                                             font=font)
                b.set(t, px)
        elif lay["kind"] == "text":
            lines = ko.split("\n") if ko.strip() else [""] * len(lay["lines"])
            if len(lines) != len(lay["lines"]):
                raise GfxTextError(f"{entry['id']}: {len(lines)} lines but layout has {len(lay['lines'])}")
            t = lay["tex"]
            px = b.get(t)
            for cl in (lay["clean"] if isinstance(lay["clean"], list) else [lay["clean"]]):
                px = label.clean(px, cl, tuple(cl["box"]), b.get(cl["source"]) if "source" in cl else None)
            for text, ln in zip(lines, lay["lines"]):
                if text:
                    size = ln["size"]
                    if "fit" in ln:
                        size = label.fit_size(text, tuple(ln["box"]), size, ln["fit"],
                                              len(ln.get("rings") or []) + (1 if ln.get("outline") is not None else 0)
                                              + ln.get("bold", 0)
                                              + max(abs(ln.get("shadow", {}).get("dx", 0)), abs(ln.get("shadow", {}).get("dy", 0))),
                                              ln.get("font", font))
                    px = label.draw_text(px, text, tuple(ln["box"]), size, ln["fill"], ln.get("edge"),
                                         ln.get("outline"), ln.get("align", "center"), ln.get("dx", 0),
                                         ln.get("dy", 0), font=ln.get("font", font), rings=ln.get("rings"),
                                         inner=ln.get("inner"), bold=ln.get("bold", 0),
                                         shadow=ln.get("shadow"))
            b.set(t, px)
        else:
            raise GfxTextError(f"{entry['id']}: unknown layout kind {lay['kind']}")
    except label.LabelError as e:
        raise GfxTextError(f"{entry['id']}: {e}") from None


def apply_all(b: Bank, entries: list[dict], layouts: list[dict]) -> None:
    """Every entry needs exactly one layout; all source hashes are checked against the untouched bank."""
    lay = {l["id"]: l for l in layouts}
    if len(lay) != len(layouts):
        raise GfxTextError("duplicate layout ids")
    missing = [e["id"] for e in entries if e["id"] not in lay]
    if missing:
        raise GfxTextError(f"no layout for {missing}")
    original = {i: b.get(i) for i in range(len(b.textures))}
    for e in entries:
        apply(b, e, lay[e["id"]], original)
