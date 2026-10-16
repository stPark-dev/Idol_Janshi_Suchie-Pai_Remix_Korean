import pytest
from PIL import Image

from remix import logo

PAL = {2: (144, 0, 24), 4: (248, 200, 0), 15: (248, 248, 248)}


def test_fit_keeps_aspect_and_centers():
    src = Image.new("RGBA", (300, 100), (248, 200, 0, 255))
    out = logo.fit(src, 120, 21)
    assert out.size == (120, 21)
    box = out.getbbox()
    w = box[2] - box[0]
    assert box[1] == 0 and box[3] == 21
    assert 60 <= w <= 66                       # 300:100 scaled to height 21 -> 63 wide
    assert abs(box[0] - (120 - box[2])) <= 1   # centered


def test_fit_crops_transparent_margin():
    src = Image.new("RGBA", (400, 400))
    src.paste(Image.new("RGBA", (200, 100), (255, 255, 255, 255)), (100, 150))
    out = logo.fit(src, 64, 32)
    assert out.getbbox() == (0, 0, 64, 32)


def test_quantize_maps_to_nearest_allowed_and_transparent():
    im = Image.new("RGBA", (4, 1))
    im.putdata([(0, 0, 0, 0), (250, 250, 250, 255), (150, 10, 30, 255), (240, 190, 10, 200)])
    assert logo.quantize(im, PAL) == [0, 15, 2, 4]


def test_quantize_rejects_palette_with_index_zero():
    with pytest.raises(logo.LogoError):
        logo.quantize(Image.new("RGBA", (1, 1)), {0: (0, 0, 0)})
