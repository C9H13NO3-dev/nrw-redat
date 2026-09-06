"""Pillow's bundled default bitmap font has no umlauts (a missing-glyph box is drawn instead), so every
report figure that titles a panel with German text ("ä"/"ü"/"ß") must use a real TrueType face instead.
`noise_map.title_font()` is that shared helper; `history_maps` reuses `noise_map._decorate` directly and
`climate_maps` imports `title_font` for its own `decorate()`.
"""
from PIL import Image, ImageFont

from redat.report import climate_maps, noise_map


def test_title_font_is_a_real_truetype_face_with_a_mapped_umlaut_glyph():
    font = noise_map.title_font()
    # this host and the production container both ship Liberation Sans, so the TrueType branch — not the
    # bitmap-default fallback — is what runs here.
    assert isinstance(font, ImageFont.FreeTypeFont)
    ae_bbox = font.getmask("ä").getbbox()
    notdef_bbox = font.getmask(chr(0x10FFFF)).getbbox()  # an unmapped codepoint renders as the .notdef box
    assert ae_bbox is not None
    assert ae_bbox != notdef_bbox


def test_noise_map_decorate_renders_umlaut_title_distinctly():
    im_umlaut = Image.new("RGBA", (noise_map.WIDTH, noise_map.HEIGHT), (120, 160, 120, 255))
    im_ascii = im_umlaut.copy()
    out_umlaut = noise_map._decorate(im_umlaut, "Oberflächentemperatur")
    out_ascii = noise_map._decorate(im_ascii, "Oberflachentemperatur")
    assert list(out_umlaut.getdata()) != list(out_ascii.getdata())


def test_climate_maps_decorate_renders_umlaut_title_distinctly():
    im_umlaut = Image.new("RGBA", (climate_maps.WIDTH, climate_maps.HEIGHT), (120, 160, 120, 255))
    im_ascii = im_umlaut.copy()
    out_umlaut = climate_maps.decorate(im_umlaut, "Oberflächentemperatur 13:30 Uhr (Sommer)")
    out_ascii = climate_maps.decorate(im_ascii, "Oberflachentemperatur 13:30 Uhr (Sommer)")
    assert list(out_umlaut.getdata()) != list(out_ascii.getdata())
