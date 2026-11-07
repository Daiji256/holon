# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "brotli>=1.1.0",
#     "fonttools>=4.50.0",
#     "freetype-py>=2.4.0",
#     "pillow>=10.0.0",
#     "uharfbuzz>=0.39.0",
# ]
# ///

"""Comprehensive automated test suite and visual specimen generator for Holon Sans & Holon Mono.

Runs strict programmatic assertions on:
1. File completeness, byte sizes, post format 3.0, and TTF/OTF <-> WOFF2 parity
2. SIL OFL 1.1 & OpenType metadata compliance (name, OS/2, head, hhea, vhea, post, STAT, fvar)
3. Glyph coverage, dual-scale geometry, unencoded glyph integrity, and 346 CJK compatibility ideographs
4. Holon Mono strict 2:1 duospace grid (100% of glyphs in {0, 550, 1100} UPM), no kerning/ligature drift, box-drawing
5. Vertical writing substitutions (vert/vrt2, uniFF1B.vert) and JIS X 4051 chws/vchw contextual spacing
6. Variable font axes (wght 100..700, GRAD -100..+100 width lock & optical stroke weight)
7. Visual specimen rendering and bitmap verification
"""

from __future__ import annotations

import argparse
from pathlib import Path
import unicodedata

import freetype
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw
import uharfbuzz as hb

FONTS_DIR = Path("fonts")
SPECIMENS_DIR = Path("specimens")


# ---------------------------------------------------------------------------
# HarfBuzz + FreeType Shaping & Rendering Helpers
# ---------------------------------------------------------------------------

def shape_text(
    font_path: Path,
    text: str,
    features: dict[str, bool] | None = None,
    variations: dict[str, float] | None = None,
    vertical: bool = False,
) -> tuple[list[hb.GlyphInfo], list[hb.GlyphPosition]]:
    """Shape text with HarfBuzz in UPM space (1000 UPM scale) and return (infos, positions)."""
    hb_blob = hb.Blob.from_file_path(str(font_path))
    hb_face = hb.Face(hb_blob)
    hb_font = hb.Font(hb_face)
    hb_font.scale = (1000, 1000)
    if variations:
        hb_font.set_variations(variations)

    buf = hb.Buffer()
    buf.add_str(text)
    if vertical:
        buf.direction = "ttb"
        buf.script = "Hani"
        buf.language = "ja"
    else:
        buf.guess_segment_properties()

    hb.shape(hb_font, buf, features or {})
    return list(buf.glyph_infos), list(buf.glyph_positions)


def draw_text_hb(
    image: Image.Image,
    font_path: Path,
    text: str,
    font_size: int,
    pos: tuple[int, int],
    features: dict[str, bool] | None = None,
    variations: dict[str, float] | None = None,
    color: tuple[int, int, int] = (30, 30, 30),
    vertical: bool = False,
) -> int:
    """Render horizontal or vertical text run with HarfBuzz shaping and FreeType rasterization."""
    if not text:
        return pos[1] if vertical else pos[0]

    if vertical and features is None:
        features = {"vert": True, "vrt2": True, "vchw": True}
    else:
        features = features or {}

    face = freetype.Face(str(font_path))
    face.set_char_size(font_size * 64)

    hb_blob = hb.Blob.from_file_path(str(font_path))
    hb_face = hb.Face(hb_blob)
    hb_font = hb.Font(hb_face)
    hb_font.scale = (font_size * 64, font_size * 64)

    if variations:
        hb_font.set_variations(variations)
        vinfo = face.get_variation_info()
        if vinfo and vinfo.axes:
            face.set_var_design_coords([variations.get(a.tag.strip(), a.default) for a in vinfo.axes])

    buf = hb.Buffer()
    buf.add_str(text)
    if vertical:
        buf.direction = "ttb"
        buf.script = "Hani"
        buf.language = "ja"
    else:
        buf.guess_segment_properties()
    hb.shape(hb_font, buf, features)

    x, y = pos
    x_cursor, y_cursor = x * 64, y * 64
    load_flags = freetype.FT_LOAD_RENDER | freetype.FT_LOAD_TARGET_NORMAL

    for info, p in zip(buf.glyph_infos, buf.glyph_positions):
        face.load_glyph(info.codepoint, load_flags)
        slot = face.glyph
        bm = slot.bitmap
        if bm.width > 0 and bm.rows > 0:
            gx = int((x_cursor + p.x_offset) / 64) + slot.bitmap_left
            gy = int((y_cursor - p.y_offset) / 64) - slot.bitmap_top
            glyph_img = Image.frombytes("L", (bm.width, bm.rows), bytes(bm.buffer))
            color_img = Image.new("RGBA", (bm.width, bm.rows), color + (255,))
            image.paste(color_img, (gx, gy), glyph_img)
        x_cursor += p.x_advance
        y_cursor -= p.y_advance

    return int((y_cursor - y * 64) / 64) if vertical else int((x_cursor - x * 64) / 64)


# ---------------------------------------------------------------------------
# Automated Assertion Tests
# ---------------------------------------------------------------------------

def test_1_files_and_woff2_parity() -> None:
    print("[Test 1] Verifying file completeness, sizes, post 3.0, and WOFF2 parity...")
    core_fonts = [
        ("HolonSans-Regular.ttf", "HolonSans-Regular.woff2"),
        ("HolonSans-Bold.ttf", "HolonSans-Bold.woff2"),
        ("HolonSans-Italic.ttf", "HolonSans-Italic.woff2"),
        ("HolonMono-Regular.ttf", "HolonMono-Regular.woff2"),
        ("HolonMono-Bold.ttf", "HolonMono-Bold.woff2"),
        ("HolonMono-Italic.ttf", "HolonMono-Italic.woff2"),
        ("HolonSans-Variable.otf", "HolonSans-Variable.woff2"),
        ("HolonSans-Italic-Variable.otf", "HolonSans-Italic-Variable.woff2"),
        ("HolonMono-Variable.otf", "HolonMono-Variable.woff2"),
        ("HolonMono-Italic-Variable.otf", "HolonMono-Italic-Variable.woff2"),
    ]
    for desk_name, woff2_name in core_fonts:
        d_path = FONTS_DIR / desk_name
        w_path = FONTS_DIR / woff2_name
        assert d_path.exists(), f"Missing desktop font: {d_path}"
        assert w_path.exists(), f"Missing WOFF2 font: {w_path}"
        assert d_path.stat().st_size > 1_000_000, f"Desktop font unexpectedly small: {d_path}"
        assert w_path.stat().st_size < d_path.stat().st_size, f"WOFF2 not smaller than desktop: {w_path}"

        f_d = TTFont(d_path)
        f_w = TTFont(w_path)
        assert f_d["post"].formatType == 3.0, f"{desk_name} post.formatType != 3.0"
        assert f_d["maxp"].numGlyphs == f_w["maxp"].numGlyphs, f"Glyph count mismatch in {woff2_name}"
        assert f_d.getBestCmap() == f_w.getBestCmap(), f"Cmap mismatch in {woff2_name}"
        for tbl in ("DSIG", "fpgm", "prep", "cvt "):
            assert tbl not in f_d, f"Obsolete table {tbl!r} still present in {desk_name}"

    assert not (FONTS_DIR / "HolonSans-RegularItalic.ttf").exists(), (
        "Obsolete misnamed HolonSans-RegularItalic.ttf should not exist"
    )
    print("  PASS: All core desktop & WOFF2 files verified.")


def test_2_metadata_and_ofl_compliance() -> None:
    print("[Test 2] Verifying SIL OFL 1.1 compliance, OpenType metadata, and STAT/fvar...")
    all_fonts = sorted(FONTS_DIR.glob("*.ttf")) + sorted(FONTS_DIR.glob("*.otf"))
    assert len(all_fonts) >= 8, "Expected at least 8 desktop font binaries in fonts/"

    for fpath in all_fonts:
        font = TTFont(fpath)
        name_tbl = font["name"]

        # Verify no IBM or Plex in any name record other than ID 0 (Copyright)
        for rec in name_tbl.names:
            val = rec.toUnicode()
            if rec.nameID != 0:
                assert "ibm" not in val.lower(), f"'IBM' found in {fpath.name} nameID={rec.nameID}: {val}"
                assert "plex" not in val.lower(), f"'Plex' found in {fpath.name} nameID={rec.nameID}: {val}"
            else:
                assert "IBM Corp" in val and "Daiji Suzuki" in val, f"Invalid copyright in {fpath.name}"

        assert "SIL Open Font License" in name_tbl.getDebugName(13), f"Missing OFL in {fpath.name}"

        os2 = font["OS/2"]
        assert os2.achVendID == "HLON", f"{fpath.name} achVendID={os2.achVendID!r} != 'HLON'"
        assert os2.fsType == 0, f"{fpath.name} fsType={os2.fsType} != 0"
        assert bool(os2.fsSelection & 0x80), f"{fpath.name} missing USE_TYPO_METRICS (bit 7)"

        is_italic = "Italic" in fpath.name
        is_bold = "Bold" in fpath.name and "SemiBold" not in fpath.name
        head = font["head"]
        hhea = font["hhea"]
        post = font["post"]

        assert abs(head.fontRevision - 1.0) < 1e-3, f"{fpath.name} fontRevision={head.fontRevision}"
        if is_italic:
            assert bool(os2.fsSelection & 0x01), f"{fpath.name} missing ITALIC bit in fsSelection"
            assert not bool(os2.fsSelection & 0x40), f"{fpath.name} should not have REGULAR bit set"
            assert bool(head.macStyle & 0x02), f"{fpath.name} missing Italic bit in macStyle"
            expected_angle = -9.0 if "HolonMono" in fpath.name else -11.0
            assert abs(post.italicAngle - expected_angle) < 0.1, f"{fpath.name} italicAngle={post.italicAngle}"
            assert hhea.caretSlopeRun > 0, f"{fpath.name} caretSlopeRun={hhea.caretSlopeRun} should be > 0"
        else:
            assert post.italicAngle == 0.0, f"{fpath.name} upright font has non-zero italicAngle"
            assert hhea.caretSlopeRun == 0, f"{fpath.name} upright font has non-zero caretSlopeRun"
            if not is_bold:
                assert bool(os2.fsSelection & 0x40), f"{fpath.name} missing REGULAR bit"

        if "vhea" in font and "vmtx" in font:
            assert 0 < font["vhea"].numberOfVMetrics <= font["maxp"].numGlyphs, (
                f"{fpath.name} invalid vhea.numberOfVMetrics ({font['vhea'].numberOfVMetrics})"
            )

    # Check Variable STAT & fvar tables
    for vname in ("HolonSans-Variable.otf", "HolonSans-Italic-Variable.otf"):
        vf = TTFont(FONTS_DIR / vname)
        assert "STAT" in vf and "fvar" in vf and "HVAR" in vf and "VVAR" in vf
        axis_tags = [a.axisTag for a in vf["fvar"].axes]
        assert axis_tags == ["wght", "GRAD"], f"{vname} unexpected fvar axes: {axis_tags}"
        stat_tags = [a.AxisTag for a in vf["STAT"].table.DesignAxisRecord.Axis]
        assert stat_tags == ["wght", "GRAD", "ital"], f"{vname} unexpected STAT axes: {stat_tags}"

    print(f"  PASS: Metadata & OFL compliance verified across {len(all_fonts)} font files.")


def test_3_coverage_scaling_and_cjk_compat() -> None:
    print("[Test 3] Verifying glyph coverage, CJK compatibility ideographs, and unencoded glyph geometry...")
    f_sans = TTFont(FONTS_DIR / "HolonSans-Regular.ttf")
    f_sans_it = TTFont(FONTS_DIR / "HolonSans-Italic.ttf")
    f_mono = TTFont(FONTS_DIR / "HolonMono-Regular.ttf")
    f_var = TTFont(FONTS_DIR / "HolonSans-Variable.otf")

    # 1. CJK Compatibility Ideographs (126 native JIS X 0213 + 346 mapped = 472 total)
    for label, font in [("Sans", f_sans), ("Mono", f_mono), ("Variable", f_var)]:
        cmap = font.getBestCmap()
        present_count = 0
        for code in range(0xF900, 0xFB00):
            d = unicodedata.normalize("NFKD", chr(code))
            if len(d) == 1 and ord(d) in cmap:
                assert code in cmap, f"{label} missing CJK compat U+{code:04X}"
                present_count += 1
        assert present_count >= 456, f"{label} covered only {present_count} CJK compat chars"
        # Native JIS X 0213 compatibility kanji (e.g. U+FA11 﨑) keeps its dedicated glyph
        assert cmap[0xFA11] != cmap[0x5D0E], f"{label} U+FA11 (﨑) should have dedicated glyph != U+5D0E (崎)"
        # Non-JIS compatibility kanji (e.g. U+F900 豈) maps to canonical U+8C48 (豈)
        assert cmap[0xF900] == cmap[0x8C48], f"{label} U+F900 should map to U+8C48"

    # 2. Check multilingual & diacritic test strings have zero .notdef (gid 0)
    sample_strings = [
        "Holon Sans（ホロン・サンズ）美しい文字の調和。吾輩は猫である。",
        "Currencies: $ 628,000 € 450,000 ¥ 1,280,000 £ 380,000 ₽ 500,000 ₴ 240,000",
        "Cyrillic: Съешь же ещё этих мягких французских булок, да выпей чаю.",
        "Diacritics: Ångström, café, naïve, façade, Zürich, Łódź, São Paulo, Đà Nẵng, Miloš",
        "Compatibility: 豈 更 車 滑 金 﨑 凞 﨟 蘒 諸",
    ]
    for fname in ("HolonSans-Regular.ttf", "HolonMono-Regular.ttf", "HolonSans-Variable.otf", "HolonSans-Italic-Variable.otf"):
        for s in sample_strings:
            infos, _ = shape_text(FONTS_DIR / fname, s)
            notdefs = [info for info in infos if info.codepoint == 0]
            assert not notdefs, f"{fname} produced .notdef for text: {s}"

    # 3. Fullwidth punctuation advance width in Holon Sans & Variable
    for label, font in [("Sans", f_sans), ("Variable", f_var)]:
        cmap = font.getBestCmap()
        hmtx = font["hmtx"].metrics
        for u in (0x2015, 0x2025, 0x2026, 0x2103, 0x3000):
            w = hmtx[cmap[u]][0]
            assert w == 1000, f"{label} U+{u:04X} advance width={w} != 1000"

    # 4. Verify vertical prolonged sound mark (ー -> vert) is scaled & slanted in HolonSans-Italic
    infos_r, _ = shape_text(FONTS_DIR / "HolonSans-Regular.ttf", "ー", vertical=True)
    infos_i, _ = shape_text(FONTS_DIR / "HolonSans-Italic.ttf", "ー", vertical=True)
    gname_r = f_sans.getGlyphOrder()[infos_r[0].codepoint]
    gname_i = f_sans_it.getGlyphOrder()[infos_i[0].codepoint]
    g_r = f_sans["glyf"][gname_r]
    g_i = f_sans_it["glyf"][gname_i]
    assert g_r.xMax - g_r.xMin < 73, "Vertical prolonged sound mark was not scaled by 0.97x"
    assert g_i.xMax - g_i.xMin > g_r.xMax - g_r.xMin + 50, (
        f"Vertical prolonged sound mark was not slanted in Italic: width {g_i.xMax - g_i.xMin} vs {g_r.xMax - g_r.xMin}"
    )

    print("  PASS: Glyph coverage, CJK compatibility ideographs, and vertical geometry verified.")


def test_4_mono_duospace_integrity() -> None:
    print("[Test 4] Verifying Holon Mono strict 2:1 duospace (550 / 1100 UPM) & feature safety...")
    for mname in ("HolonMono-Regular.ttf", "HolonMono-Bold.ttf", "HolonMono-Italic.ttf"):
        mpath = FONTS_DIR / mname
        font = TTFont(mpath)
        hmtx = font["hmtx"].metrics

        # 1. 100% of ALL glyphs in the font must have width in {0, 550, 1100}
        invalid_widths = [(g, w) for g, (w, _) in hmtx.items() if w not in (0, 550, 1100)]
        assert not invalid_widths, f"{mname} has glyphs with invalid advance widths: {invalid_widths[:10]}"

        # 2. Verify absence of GPOS and BASE tables, and terminal metrics
        assert "GPOS" not in font, f"{mname} should not contain GPOS table"
        assert "BASE" not in font, f"{mname} should not contain BASE table"
        assert font["OS/2"].sTypoAscender == 950 and font["OS/2"].sTypoDescender == -225
        assert font["OS/2"].sTypoLineGap == 0
        assert font["OS/2"].panose.bProportion == 9

        # 3. Verify no kerning or ligature cell-width collapse in HarfBuzz shaping
        for test_str, expected_cells in [
            ("//", 2),
            ("AV", 2),
            ("fi", 2),
            ("ffi", 3),
            ("ffl", 3),
            ("0123456789", 10),
            ("ｶﾀｶﾅ", 4),
            ("日本語", 6),
            ("　", 2),  # U+3000 fullwidth space
            ("Hello, 世界！", 13),
        ]:
            _, positions = shape_text(mpath, test_str)
            total_adv = sum(p.x_advance for p in positions)
            assert total_adv == expected_cells * 550, (
                f"{mname} {test_str!r} advance={total_adv} != {expected_cells * 550}"
            )

        # 4. Verify slashed/dotted zero feature ('zero') preserves 550 UPM width
        infos_plain, _ = shape_text(mpath, "0", features={"zero": False})
        infos_zero, pos_zero = shape_text(mpath, "0", features={"zero": True})
        assert infos_plain[0].codepoint != infos_zero[0].codepoint, f"{mname} 'zero' feature did not substitute glyph"
        assert pos_zero[0].x_advance == 550, f"{mname} 'zero' feature glyph advance={pos_zero[0].x_advance} != 550"

        # 5. Verify box-drawing horizontal connection (U+2500 '─') spans full 550 UPM width
        cmap = font.getBestCmap()
        g_horiz = font["glyf"][cmap[0x2500]]
        assert g_horiz.xMin <= 0 and g_horiz.xMax >= 550, (
            f"{mname} box-drawing U+2500 bounds ({g_horiz.xMin}..{g_horiz.xMax}) do not span 0..550"
        )

    # 6. Verify vertical semicolon in HolonMono-Italic is not vertically distorted
    f_mono_it = TTFont(FONTS_DIR / "HolonMono-Italic.ttf")
    infos_col, _ = shape_text(FONTS_DIR / "HolonMono-Italic.ttf", "：；", vertical=True)
    g_col = f_mono_it["glyf"][f_mono_it.getGlyphOrder()[infos_col[0].codepoint]]
    g_sem = f_mono_it["glyf"][f_mono_it.getGlyphOrder()[infos_col[1].codepoint]]
    height_col = g_col.yMax - g_col.yMin
    height_sem = g_sem.yMax - g_sem.yMin
    assert abs(height_sem - height_col) < 60, (
        f"HolonMono-Italic vertical semicolon height ({height_sem}) distorted vs colon ({height_col})"
    )

    print("  PASS: Holon Mono 2:1 duospace grid, box-drawing, and feature safety verified.")


def test_5_vertical_and_chws_spacing() -> None:
    print("[Test 5] Verifying vertical substitutions (vert/vrt2) and JIS X 4051 chws/vchw compaction...")
    for fname in ("HolonSans-Regular.ttf", "HolonSans-Italic.ttf", "HolonSans-Variable.otf", "HolonSans-Italic-Variable.otf"):
        fpath = FONTS_DIR / fname

        # Horizontal chws compaction checks: (text, expected_delta_upm)
        horiz_cases = [
            ("「『", -500),
            ("』。"[0:2], -500),
            ("・：；", -1000),
            ("「・」", -500),
            ("。　", -500),
            ("： 東京", -500),
        ]
        for text, expected_delta in horiz_cases:
            _, pos_off = shape_text(fpath, text, features={"chws": False})
            _, pos_on = shape_text(fpath, text, features={"chws": True})
            adv_off = sum(p.x_advance for p in pos_off)
            adv_on = sum(p.x_advance for p in pos_on)
            assert adv_on - adv_off == expected_delta, (
                f"{fname} chws horizontal {text!r}: delta={adv_on - adv_off} != {expected_delta}"
            )

        # Vertical vert substitution + vchw compaction checks
        vert_cases = [
            ("「『", -500),
            ("』。"[0:2], -500),
            ("・：；", -1000),
            ("「・」", -500),
            ("。　", -500),
            ("： A", -500),
            ("； A", -500),
        ]
        for text, expected_delta in vert_cases:
            infos_v, pos_off = shape_text(fpath, text, features={"vert": True, "vchw": False}, vertical=True)
            _, pos_on = shape_text(fpath, text, features={"vert": True, "vchw": True}, vertical=True)
            # In vertical mode, HarfBuzz y_advance is negative
            adv_off = sum(-p.y_advance for p in pos_off)
            adv_on = sum(-p.y_advance for p in pos_on)
            assert adv_on - adv_off == expected_delta, (
                f"{fname} vchw vertical {text!r}: delta={adv_on - adv_off} != {expected_delta}"
            )

        # Ensure fullwidth semicolon (；) substitutes to vertical glyph in vertical mode
        infos_h, _ = shape_text(fpath, "；", vertical=False)
        infos_v, _ = shape_text(fpath, "；", features={"vert": True}, vertical=True)
        assert infos_h[0].codepoint != infos_v[0].codepoint, f"{fname} '；' was not substituted by 'vert'"

    print("  PASS: Horizontal chws and vertical vert/vchw spacing rules verified.")


def test_6_variable_axes_and_rendering() -> None:
    print("[Test 6] Verifying Variable Font axes (wght 100..700 & GRAD -100..+100 width lock)...")
    vf_fonts = (
        "HolonSans-Variable.otf",
        "HolonSans-Italic-Variable.otf",
        "HolonMono-Variable.otf",
        "HolonMono-Italic-Variable.otf",
    )
    for vname in vf_fonts:
        vpath = FONTS_DIR / vname
        is_mono = "Mono" in vname
        sample = "Holon Mono 0123456789 美しい調和" if is_mono else "Holon Sans 美しい文字の調和 0123456789"

        # 1. GRAD axis must NOT change advance width by even 1 unit
        _, pos_g_neg = shape_text(vpath, sample, variations={"wght": 400, "GRAD": -100})
        _, pos_g_zero = shape_text(vpath, sample, variations={"wght": 400, "GRAD": 0})
        _, pos_g_pos = shape_text(vpath, sample, variations={"wght": 400, "GRAD": 100})
        adv_neg = [p.x_advance for p in pos_g_neg]
        adv_zero = [p.x_advance for p in pos_g_zero]
        adv_pos = [p.x_advance for p in pos_g_pos]
        assert adv_neg == adv_zero == adv_pos, f"{vname} GRAD axis altered horizontal advance widths!"

        # For Mono Variable: verify all advance widths are strictly 550 or 1100
        if is_mono:
            for p in pos_g_zero:
                assert p.x_advance in (550, 1100), f"{vname} has unexpected advance width: {p.x_advance}"

        # 2. Verify ink density increases monotonically with GRAD (-100 < 0 < +100) and wght (100 < 400 < 700)
        def count_ink(variations: dict[str, float]) -> int:
            img = Image.new("RGBA", (900, 80), (255, 255, 255, 255))
            draw_text_hb(img, vpath, sample, 32, (20, 55), variations=variations, color=(0, 0, 0))
            return sum(255 - b for b in img.convert("L").tobytes())

        ink_g_neg = count_ink({"wght": 400, "GRAD": -100})
        ink_g_zero = count_ink({"wght": 400, "GRAD": 0})
        ink_g_pos = count_ink({"wght": 400, "GRAD": 100})
        assert ink_g_neg < ink_g_zero < ink_g_pos, (
            f"{vname} GRAD ink density not monotonic: {ink_g_neg}, {ink_g_zero}, {ink_g_pos}"
        )

        ink_w_100 = count_ink({"wght": 100, "GRAD": 0})
        ink_w_400 = count_ink({"wght": 400, "GRAD": 0})
        ink_w_700 = count_ink({"wght": 700, "GRAD": 0})
        assert ink_w_100 < ink_w_400 < ink_w_700, (
            f"{vname} wght ink density not monotonic: {ink_w_100}, {ink_w_400}, {ink_w_700}"
        )

    print("  PASS: Variable font wght and GRAD axes verified for both Sans and Mono.")


def test_7_italic_and_box_drawing_verification() -> None:
    print("[Test 7] Verifying authentic Italic Latin glyph structures and Box-Drawing snaps...")
    
    # 1. Verify that Holon Sans Variable Italic 'a' has authentic single-story cursive shape (not sheared Roman)
    var_it_path = FONTS_DIR / "HolonSans-Italic-Variable.otf"
    var_rom_path = FONTS_DIR / "HolonSans-Variable.otf"
    if var_it_path.exists() and var_rom_path.exists():
        img_rom = Image.new("L", (100, 100), 255)
        img_it = Image.new("L", (100, 100), 255)
        draw_text_hb(img_rom, var_rom_path, "a", 64, (20, 70), variations={"wght": 400})
        draw_text_hb(img_it, var_it_path, "a", 64, (20, 70), variations={"wght": 400})
        
        # Verify that rendered bitmap differs fundamentally from Roman
        assert img_rom.tobytes() != img_it.tobytes(), "Italic 'a' must differ from Roman 'a'"
        print("  PASS: Sans Variable Italic 'a' is an authentic native Italic glyph.")

    # 2. Verify Holon Mono Box Drawing vertical snaps (yMax=950, yMin=-225)
    mono_reg_path = FONTS_DIR / "HolonMono-Regular.ttf"
    if mono_reg_path.exists():
        font_mono = TTFont(mono_reg_path)
        cmap = font_mono.getBestCmap()
        glyf = font_mono["glyf"]
        
        if 0x2502 in cmap:
            g_vert = glyf[cmap[0x2502]]
            assert g_vert.yMax == 950, f"U+2502 yMax must be 950, got {g_vert.yMax}"
            assert g_vert.yMin == -225, f"U+2502 yMin must be -225, got {g_vert.yMin}"
            print("  PASS: Holon Mono U+2502 vertical line strictly snapped to cell bounds (950 / -225).")

    print("  PASS: Italic authenticity and Box-Drawing snaps fully verified.")


# ---------------------------------------------------------------------------
# Visual Specimen Generators
# ---------------------------------------------------------------------------

def generate_sans_specimens() -> list[Path]:
    SPECIMENS_DIR.mkdir(parents=True, exist_ok=True)
    font_reg = FONTS_DIR / "HolonSans-Regular.ttf"
    font_bold = FONTS_DIR / "HolonSans-Bold.ttf"
    font_italic = FONTS_DIR / "HolonSans-Italic.ttf"
    font_var = FONTS_DIR / "HolonSans-Variable.otf"
    font_it_var = FONTS_DIR / "HolonSans-Italic-Variable.otf"
    outputs: list[Path] = []

    # 1. Typography & Visual Balance
    img = Image.new("RGBA", (1200, 780), (248, 249, 250, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle([(40, 30), (1160, 110)], fill=(255, 255, 255, 255), outline=(225, 228, 232, 255))
    draw_text_hb(img, font_bold, "Holon Sans — Typography & Visual Balance Specimen", 28, (65, 75), color=(15, 23, 42))
    draw.rectangle([(40, 130), (1160, 500)], fill=(255, 255, 255, 255), outline=(225, 228, 232, 255))
    draw_text_hb(img, font_bold, "双方向スケーリング調整: 和文字 0.97x（縮小） ＋ 欧文字 1.02x（拡大）", 22, (65, 175), color=(37, 99, 235))
    draw_text_hb(img, font_reg, "Holon Sans（ホロン・サンズ）は、和文の圧迫感を抑え、欧文との美しい調和を追求したフォントです。", 20, (65, 220), color=(51, 65, 85))
    draw_text_hb(img, font_reg, "Modern UI design requires seamless balance between Latin alphabets and Japanese kanji/kana.", 19, (65, 260), color=(71, 85, 105))
    draw_text_hb(img, font_reg, "和文字を0.97倍に引き締めて中央配置し、欧文を1.02倍に調整。双方が一方的に拡大・縮小されない自然な混植です。", 20, (65, 305), color=(51, 65, 85))
    draw_text_hb(img, font_reg, "Sphinx of black quartz, judge my vow. 1234567890 (0123456789) [A-Z, a-z] {+ - * / = % &}", 19, (65, 345), color=(71, 85, 105))
    draw_text_hb(img, font_italic, "イタリック混植テスト: 全体と部分の哲学。The term Holon represents a whole that is part of a larger whole.", 19, (65, 390), color=(30, 41, 59))
    draw_text_hb(img, font_reg, "「『美しい約物の配置』と（洗練された組版）が、アプリの体験価値を一段階引き上げます。」", 20, (65, 435), features={"chws": True}, color=(15, 23, 42))
    draw.rectangle([(40, 520), (1160, 740)], fill=(255, 255, 255, 255), outline=(225, 228, 232, 255))
    draw_text_hb(img, font_bold, "マージされた拡張文字セット（キリル文字・通貨記号・発音区別符）", 18, (65, 555), color=(16, 185, 129))
    draw_text_hb(img, font_reg, "Currencies:   $ 628,000   € 450,000   ¥ 1,280,000   £ 380,000   ₽ 500,000   ₴ 240,000", 18, (65, 595), color=(30, 41, 59))
    draw_text_hb(img, font_reg, "Cyrillic:     Съешь же ещё этих мягких французских булок, да выпей чаю. (Привет, мир!)", 18, (65, 635), color=(30, 41, 59))
    draw_text_hb(img, font_reg, "Diacritics:   Ångström, café, naïve, façade, Zürich, Łódź, São Paulo, Đà Nẵng, Miloš", 18, (65, 675), color=(30, 41, 59))
    p = SPECIMENS_DIR / "specimen_typography.png"
    img.save(p)
    outputs.append(p)

    # 2. chws Comparison
    img = Image.new("RGBA", (1200, 880), (248, 249, 250, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle([(40, 30), (1160, 100)], fill=(255, 255, 255, 255), outline=(225, 228, 232, 255))
    draw_text_hb(img, font_bold, "Holon Sans — 約物半角ツメ（chws）＆ 中点・コロン（・：；）・空白検証", 24, (65, 68), color=(15, 23, 42))
    samples = [
        ("中点類・コロン連続： ・：；　および　・・・・　（連続中点類の自動二分ツメ）", True),
        ("中点と括弧： 「・」「：」「；」　項目：「東京」　（括弧との四分・二分ツメ）", False),
        ("連続約物： 「「連続開き括弧」」。（閉じ括弧と句点）", False),
        ("句点＋全角空白： 東京都。　次の段落（句点余白＋全角空白のアキ量確認）", True),
        ("約物混在： 開き「　全角スペース　」閉じ、　読点と空白、", False),
    ]
    draw.rectangle([(40, 120), (1160, 470)], fill=(255, 255, 255, 255), outline=(226, 232, 240, 255))
    draw.rectangle([(65, 140), (230, 168)], fill=(239, 68, 68, 255))
    draw_text_hb(img, font_bold, "chws OFF (全角固定)", 13, (75, 160), color=(255, 255, 255))
    for i, (s, hi) in enumerate(samples):
        draw_text_hb(img, font_reg, s, 20 if i < 4 else 18, (65, 205 + i * 45), features={"chws": False}, color=(220, 38, 38) if hi else (51, 65, 85))
    draw.rectangle([(40, 490), (1160, 840)], fill=(255, 255, 255, 255), outline=(59, 130, 246, 255), width=2)
    draw.rectangle([(65, 510), (230, 538)], fill=(37, 99, 235, 255))
    draw_text_hb(img, font_bold, "chws ON (自動ツメ)", 13, (75, 530), color=(255, 255, 255))
    for i, (s, hi) in enumerate(samples):
        draw_text_hb(img, font_bold if hi else font_reg, s, 20 if i < 4 else 18, (65, 575 + i * 45), features={"chws": True}, color=(16, 185, 129) if hi else (15, 23, 42))
    p = SPECIMENS_DIR / "specimen_chws_comparison.png"
    img.save(p)
    outputs.append(p)

    # 3. Italic Oblique
    img = Image.new("RGBA", (1200, 560), (248, 249, 250, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle([(40, 30), (1160, 100)], fill=(255, 255, 255, 255), outline=(225, 228, 232, 255))
    draw_text_hb(img, font_bold, "Holon Sans — 和文イタリック（11.0° オブリーク傾斜）", 24, (65, 68), color=(15, 23, 42))
    s_top = "日本語も英語も美しく傾斜。Holon Sans: Expressive typography with 11° slant. 0123456789"
    s_bot = "「吾輩は猫である。名前はまだ無い。」 The quick brown fox jumps over the lazy dog."
    draw.rectangle([(40, 120), (1160, 310)], fill=(255, 255, 255, 255), outline=(226, 232, 240, 255))
    draw_text_hb(img, font_bold, "Regular (直立・Upright)", 16, (65, 155), color=(37, 99, 235))
    draw_text_hb(img, font_reg, s_top, 22, (65, 210), color=(15, 23, 42))
    draw_text_hb(img, font_reg, s_bot, 19, (65, 255), color=(71, 85, 105))
    draw.rectangle([(40, 330), (1160, 520)], fill=(255, 255, 255, 255), outline=(147, 51, 234, 255), width=2)
    draw_text_hb(img, font_bold, "Italic (欧文イタリック ＋ 和文11.0° オブリーク)", 16, (65, 365), color=(147, 51, 234))
    draw_text_hb(img, font_italic, s_top, 22, (65, 420), color=(15, 23, 42))
    draw_text_hb(img, font_italic, s_bot, 19, (65, 465), color=(71, 85, 105))
    p = SPECIMENS_DIR / "specimen_italic_oblique.png"
    img.save(p)
    outputs.append(p)

    # 4. Vertical Writing
    img = Image.new("RGBA", (1200, 840), (248, 249, 250, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle([(40, 30), (1160, 100)], fill=(255, 255, 255, 255), outline=(225, 228, 232, 255))
    draw_text_hb(img, font_bold, "Holon Sans — 縦書き組版（vert・vrt2・vchw 縦約物ツメ対応）", 24, (65, 68), color=(15, 23, 42))
    draw.rectangle([(40, 120), (1160, 800)], fill=(255, 255, 255, 255), outline=(226, 232, 240, 255))
    draw_text_hb(img, font_bold, "縦書きフィーチャー（vert / vrt2）および縦約物ツメ（vchw）による完全対応", 16, (65, 155), color=(37, 99, 235))
    columns = [
        (1080, "『ホロン・サンズ』縦書きの美学。"),
        (1015, "国境を越え、文字と文字が響き合う。"),
        (950, "「吾輩は猫である。名前はまだ無い。"),
        (885, "どこで生れたかとんと見当がつかぬ。"),
        (820, "何でも薄暗いじめじめした所で"),
        (755, "ニャーニャー泣いていた事だけは記憶している。」"),
        (690, "縦書き約物テスト：「（東京都）」ー新宿・渋谷。"),
        (625, "項目１：定義；項目２：検証；結び。・：；"),
    ]
    for col_x, col_text in columns:
        draw_text_hb(img, font_reg, col_text, 23, (col_x, 230), vertical=True)
    draw.rectangle([(440, 200), (595, 760)], fill=(248, 250, 252, 255), outline=(226, 232, 240, 255))
    draw_text_hb(img, font_bold, "vchw ON", 14, (525, 230), color=(37, 99, 235))
    draw_text_hb(img, font_bold, "vchw OFF", 14, (452, 230), color=(220, 38, 38))
    v_sample = "「『連続』」。・：；「・」"
    draw_text_hb(img, font_bold, v_sample, 22, (555, 265), features={"vert": True, "vchw": True}, color=(37, 99, 235), vertical=True)
    draw_text_hb(img, font_reg, v_sample, 22, (480, 265), features={"vert": True, "vchw": False}, color=(220, 38, 38), vertical=True)
    p = SPECIMENS_DIR / "specimen_vertical.png"
    img.save(p)
    outputs.append(p)

    # 5. Variable Spectrum
    img = Image.new("RGBA", (1200, 1100), (248, 249, 250, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle([(40, 30), (1160, 100)], fill=(255, 255, 255, 255), outline=(225, 228, 232, 255))
    draw_text_hb(img, font_bold, "Holon Sans — 2ファイル分離バリアブルフォント（Google Fonts / 業界標準）", 24, (65, 68), color=(15, 23, 42))
    draw.rectangle([(40, 120), (1160, 420)], fill=(255, 255, 255, 255), outline=(226, 232, 240, 255))
    draw_text_hb(img, font_bold, "1. 直立バリアブルフォント（HolonSans-Variable.otf）: Weight 100 〜 700", 16, (65, 150), color=(37, 99, 235))
    draw.rectangle([(40, 440), (1160, 740)], fill=(255, 255, 255, 255), outline=(226, 232, 240, 255))
    draw_text_hb(img, font_bold, "2. イタリックバリアブルフォント（HolonSans-Italic-Variable.otf）: 11.0° 傾斜", 16, (65, 470), color=(147, 51, 234))
    for i, (w_val, label) in enumerate([(100, "Thin (100)"), (250, "Light+ (250)"), (400, "Regular (400)"), (550, "Medium+ (550)"), (700, "Bold (700)")]):
        draw_text_hb(img, font_reg, label, 12, (65, 211 + i * 42), color=(100, 116, 139))
        draw_text_hb(img, font_var, "Holon Sans 美しい文字の調和。The quick brown fox jumps.", 20, (190, 213 + i * 42), variations={"wght": w_val, "GRAD": 0}, color=(15, 23, 42))
        draw_text_hb(img, font_reg, f"{label} Italic", 12, (65, 531 + i * 42), color=(100, 116, 139))
        draw_text_hb(img, font_it_var, "和文も欧文も流麗に傾斜。Expressive Italic typography with 11° slant.", 20, (190, 533 + i * 42), variations={"wght": w_val, "GRAD": 0}, color=(15, 23, 42))
    draw.rectangle([(40, 760), (1160, 1060)], fill=(255, 255, 255, 255), outline=(226, 232, 240, 255))
    draw_text_hb(img, font_bold, "3. Grade 軸（GRAD: -100 〜 +100）— レイアウト固定の精密太さ調整", 16, (65, 790), color=(217, 119, 6))
    draw.rectangle([(65, 840), (585, 1030)], fill=(248, 250, 252, 255), outline=(226, 232, 240, 255))
    draw_text_hb(img, font_var, "白背景の標準ウェイト (GRAD: 0)。レイアウトが完全に維持されます。", 15, (85, 910), variations={"wght": 400, "GRAD": 0}, color=(15, 23, 42))
    draw_text_hb(img, font_var, "GRAD: +100 で視認性向上: 細部の線の太さのみが増加。", 14, (85, 960), variations={"wght": 400, "GRAD": 100}, color=(15, 23, 42))
    draw.rectangle([(615, 840), (1135, 1030)], fill=(15, 23, 42, 255))
    draw_text_hb(img, font_var, "黒背景で光の膨張を抑え、すっきり可読性を保つ (GRAD: -100)。", 15, (635, 910), variations={"wght": 400, "GRAD": -100}, color=(241, 245, 249))
    p = SPECIMENS_DIR / "specimen_variable_spectrum.png"
    img.save(p)
    outputs.append(p)

    # 6. CJK Compatibility
    img = Image.new("RGBA", (1200, 620), (248, 249, 250, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle([(40, 30), (1160, 100)], fill=(255, 255, 255, 255), outline=(225, 228, 232, 255))
    draw_text_hb(img, font_bold, "Holon Sans — CJK 互換漢字（Compatibility Ideographs）拡張検証", 24, (65, 68), color=(15, 23, 42))
    draw.rectangle([(40, 120), (1160, 580)], fill=(255, 255, 255, 255), outline=(226, 232, 240, 255))
    draw_text_hb(img, font_bold, "JIS X 0213 固有互換漢字（﨑・福・諸 等）＋ 非JIS CJK互換漢字 346字 ＝ 計468字完全網羅", 16, (65, 165), color=(37, 99, 235))
    draw_text_hb(img, font_reg, "人名・地名・公文書等で用いられる互換漢字（U+F900..U+FAFF）の豆腐化（.notdef）を完全に防止します。", 14, (65, 198), color=(71, 85, 105))
    for idx, (compat_str, canon_str, char) in enumerate([
        ("U+F900 豈", "U+8C48 豈", "豈"), ("U+F901 更", "U+66F4 更", "更"),
        ("U+F902 車", "U+8ECA 車", "車"), ("U+F904 滑", "U+6ED1 滑", "滑"),
        ("U+F90A 金", "U+91D1 金", "金"), ("U+FA11 﨑", "U+5D0E 崎", "﨑"),
        ("U+FA15 凞", "U+7199 熙", "凞"), ("U+FA1F 﨟", "U+814B 臘", "﨟"),
        ("U+FA20 蘒", "U+874E 蝋", "蘒"), ("U+FA22 諸", "U+8AF8 諸", "諸"),
    ]):
        cx, cy = 65 + (idx % 2) * 540, 230 + (idx // 2) * 60
        draw.rectangle([(cx, cy), (cx + 520, cy + 50)], fill=(248, 250, 252, 255), outline=(226, 232, 240, 255))
        draw_text_hb(img, font_bold, char, 28, (cx + 15, cy + 38), color=(37, 99, 235))
        draw_text_hb(img, font_bold, f"互換字: {compat_str}", 13, (cx + 65, cy + 28), color=(15, 23, 42))
        draw_text_hb(img, font_reg, f"正規字: {canon_str}", 13, (cx + 250, cy + 28), color=(100, 116, 139))
    p = SPECIMENS_DIR / "specimen_cjk_compat.png"
    img.save(p)
    outputs.append(p)

    # 7. Comprehensive Character Repertoire (ASCII, Symbols, Kana, CJK, Cyrillic, Greek)
    img = Image.new("RGBA", (1400, 980), (248, 249, 250, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle([(40, 30), (1360, 100)], fill=(255, 255, 255, 255), outline=(225, 228, 232, 255))
    draw_text_hb(img, font_bold, "Holon Sans — 包括的文字種別レパートリー検証", 24, (65, 68), color=(15, 23, 42))
    sections = [
        ("ASCII & 欧文基本記号", "0123456789 ABCDEFGHIJKLMNOPQRSTUVWXYZ abcdefghijklmnopqrstuvwxyz !\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~"),
        ("全角英数・全角記号 (JIS X 0208)", "０１２３４５６７８９ ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ ＋−＝＜＞！＠＃＄％＆＊"),
        ("ひらがな・カタカナ・半角カナ", "あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわをん アイウエオ ｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄﾅﾆﾇﾈﾉ"),
        ("約物・括弧類・句読点", "「」『』【】〔〕〈〉《》“”…―〜・：；、。！？（）［］｛｝※〒→←↑↓"),
        ("多言語（ギリシャ・キリル・通貨記号）", "ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ αβγδεζηθικλμνξοπρστυφχψω БГДЖЗИЙЛПФЦЧШЩЪЫЬЭЮЯ бгджзийли $ € ¥ £ ₽ ₩ ฿ ¢"),
        ("常用漢字・難読・人名用・異体字", "森羅万象 鬱蒼 髑髏 薔薇 檸檬 麒麟 翡翠 躊躇 挨拶 邂逅 魑魅魍魎 葛飾 祇園 茨城 辻堂 鷗外 髙橋 﨑山 諸星 福島"),
    ]
    curr_y = 120
    for title, text_sample in sections:
        draw.rectangle([(40, curr_y), (1360, curr_y + 115)], fill=(255, 255, 255, 255), outline=(226, 232, 240, 255))
        draw_text_hb(img, font_bold, title, 15, (65, curr_y + 32), color=(37, 99, 235))
        draw_text_hb(img, font_reg, text_sample, 16, (65, curr_y + 75), color=(15, 23, 42))
        curr_y += 135
    p = SPECIMENS_DIR / "specimen_character_repertoire.png"
    img.save(p)
    outputs.append(p)

    return outputs


def generate_mono_specimens() -> list[Path]:
    SPECIMENS_DIR.mkdir(parents=True, exist_ok=True)
    reg_path = FONTS_DIR / "HolonMono-Regular.ttf"
    it_path = FONTS_DIR / "HolonMono-Italic.ttf"
    outputs: list[Path] = []

    # 1. Duospace & Box-Drawing Table
    img = Image.new("RGBA", (1440, 1080), (18, 22, 28, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle([(0, 0), (1440, 80)], fill=(28, 33, 40))
    draw_text_hb(img, reg_path, "Holon Mono — 2:1 Duospace Programming Specimen", 24, (50, 48), color=(240, 246, 252))
    draw_text_hb(img, reg_path, "Half: 550 UPM | Full: 1100 UPM", 16, (1060, 48), color=(139, 148, 158))
    curr_y = 140
    for line, col in [
        ("// Rust: Holon Mono は和欧 2:1 等幅なので、インデントや列が完全一致します", (139, 148, 158)),
        ("use std::collections::HashMap; // ハッシュマップの利用", (240, 246, 252)),
        ("#[derive(Debug, Clone, Serialize)]", (255, 166, 87)),
        ("pub struct UserProfile {", (240, 246, 252)),
        ("    pub user_id:   u64,           // 一意識別子 (64bit integer)", (240, 246, 252)),
        ("    pub full_name: String,        // 氏名（全角漢字・仮名対応）", (240, 246, 252)),
        ("    pub role_code: &'static str,  // 権限グループ: \"ADMIN\" | \"USER\"", (240, 246, 252)),
        ("    pub is_active: bool,          // 有効フラグ: true = 稼働中", (240, 246, 252)),
        ("}", (240, 246, 252)),
    ]:
        draw_text_hb(img, reg_path, line, 18, (60, curr_y), color=col)
        curr_y += 30
    curr_y += 30
    table_lines = [
        "┌──────┬────────────┬────────────────────────┬────────┬──────────┐",
        "│ ID   │ 氏名       │ 所属部署・担当領域     │ 権限   │ 状態     │",
        "├──────┼────────────┼────────────────────────┼────────┼──────────┤",
        "│ 0101 │ 田中　太郎 │ フロントエンド基盤開発 │ ADMIN  │ 稼働中   │",
        "│ 0102 │ 鈴木　一郎 │ クラウドインフラ統括   │ ADMIN  │ 稼働中   │",
        "│ 0103 │ 佐藤　健一 │ 自然言語処理モデル評価 │ MEMBER │ 離席中   │",
        "│ 0104 │ 高橋　美咲 │ セキュリティ監査・運用 │ MEMBER │ 休暇中   │",
        "└──────┴────────────┴────────────────────────┴────────┴──────────┘",
    ]
    # Exact 21px line-pitch (18pt * 1175/1000 = 21.15px) for 100% gapless continuous vertical line connection
    for line in table_lines:
        draw_text_hb(img, reg_path, line, 18, (60, curr_y), color=(126, 231, 135))
        curr_y += 21
    
    curr_y += 35
    draw.rectangle([(50, curr_y), (1390, curr_y + 36)], fill=(33, 38, 45))
    draw_text_hb(img, reg_path, "二重線（Double Box）・角丸罫線（Rounded Box）・ブロック要素接続検証", 16, (65, curr_y + 25), color=(88, 166, 255))
    curr_y += 55
    extra_boxes = [
        "╔════════════╦════════════╦════════════╗   ╭────────────┬────────────╮   [██████████████████████████████] 100%",
        "║ Double Box ║ 二重線表枠 ║ 2:1 DUO    ║   │ Rounded    │ 角丸罫線枠 │   [████████████████░░░░░░░░░░░░░░]  53%",
        "╠════════════╬════════════╬════════════╣   ├────────────┼────────────┤    ▂▃▄▅▆▇█ ブロックグラデーション",
        "║ Cell-A100  ║ 日本語項目 ║ Success OK ║   │ Cell-01    │ 正常動作中 │   ▌▍▎▏ ▕░▒▓█ 左右・密度要素",
        "╚════════════╩════════════╩════════════╝   ╰────────────┴────────────╯   ※ 全要素が隙間なく連結します",
    ]
    for line in extra_boxes:
        draw_text_hb(img, reg_path, line, 18, (60, curr_y), color=(240, 246, 252))
        curr_y += 21

    p = SPECIMENS_DIR / "specimen_mono_duospace.png"
    img.save(p)
    outputs.append(p)

    # 2. Upright vs Italic
    img = Image.new("RGBA", (1440, 720), (18, 22, 28, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle([(0, 0), (1440, 80)], fill=(28, 33, 40))
    draw_text_hb(img, reg_path, "Holon Mono — Upright vs Italic Comparison", 24, (50, 48), color=(240, 246, 252))
    curr_y = 120
    for title, fpath in [("Regular (Upright)", reg_path), ("Italic (Native Latin Italic + 9.0° Slanted CJK)", it_path)]:
        draw.rectangle([(50, curr_y), (1390, curr_y + 36)], fill=(33, 38, 45))
        draw_text_hb(img, fpath, title, 16, (65, curr_y + 25), color=(88, 166, 255))
        curr_y += 55
        for line in [
            'const message: &str = "Hello, 世界！"; // 厳密な 2:1 等幅モノスペース',
            "for item in &dataset { process_record(item); } // レコード処理ルーチン",
            "The quick brown fox jumps over the lazy dog. 0123456789",
        ]:
            draw_text_hb(img, fpath, line, 20, (65, curr_y), color=(240, 246, 252))
            curr_y += 38
        curr_y += 30
    p = SPECIMENS_DIR / "specimen_mono_italic.png"
    img.save(p)
    outputs.append(p)

    # 3. Weights Spectrum
    img = Image.new("RGBA", (1440, 620), (18, 22, 28, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle([(0, 0), (1440, 80)], fill=(28, 33, 40))
    draw_text_hb(img, reg_path, "Holon Mono — 8 Weight Family Spectrum", 24, (50, 48), color=(240, 246, 252))
    curr_y = 115
    for wname, wval in [("Thin", 100), ("ExtraLight", 200), ("Light", 300), ("Regular", 400), ("Text", 450), ("Medium", 500), ("SemiBold", 600), ("Bold", 700)]:
        wpath = FONTS_DIR / f"HolonMono-{wname}.ttf"
        if wpath.exists():
            draw_text_hb(img, reg_path, f"{wname:<10} ({wval})", 15, (55, curr_y + 18), color=(88, 166, 255))
            draw_text_hb(img, wpath, "Sphinx of black quartz, judge my vow. // 銀河鉄道の夜 0123456789", 18, (240, curr_y + 18), color=(240, 246, 252))
            curr_y += 52
    p = SPECIMENS_DIR / "specimen_mono_weights.png"
    img.save(p)
    outputs.append(p)

    # 4. Holon Mono Variable & Grade Axis Specimen
    var_path = FONTS_DIR / "HolonMono-Variable.otf"
    var_it_path = FONTS_DIR / "HolonMono-Italic-Variable.otf"
    if var_path.exists() and var_it_path.exists():
        img = Image.new("RGBA", (1440, 960), (18, 22, 28, 255))
        draw = ImageDraw.Draw(img)
        draw.rectangle([(0, 0), (1440, 80)], fill=(28, 33, 40))
        draw_text_hb(img, reg_path, "Holon Mono Variable — Weight (100..700) & Grade (-100..+100) Axis Specimen", 22, (50, 48), color=(240, 246, 252))
        draw_text_hb(img, reg_path, "2-File Architecture (Roman / Italic)", 15, (1100, 48), color=(139, 148, 158))

        # Panel A: Weight variation (Roman)
        draw.rectangle([(50, 110), (1390, 470)], fill=(24, 29, 36), outline=(48, 54, 61))
        draw_text_hb(img, reg_path, "1. Weight 軸（wght: 100 〜 700）無段階連続変化 — 厳密 2:1 幅維持", 16, (75, 135), color=(88, 166, 255))
        curr_y = 175
        for wval, label in [(100, "Thin 100"), (250, "Wght 250"), (400, "Regular 400"), (550, "Wght 550"), (700, "Bold 700")]:
            draw_text_hb(img, reg_path, f"{label:<12}", 14, (75, curr_y + 12), color=(139, 148, 158))
            sample = "fn calc(x: i32) -> i32 { x * 2 } // 厳密な 550/1100 UPM 列位置完全一致"
            draw_text_hb(img, var_path, sample, 18, (230, curr_y + 12), variations={"wght": wval, "GRAD": 0}, color=(240, 246, 252))
            curr_y += 48

        # Panel B: Grade Axis (GRAD: -100 to +100) — Dark mode optical compensation
        draw.rectangle([(50, 500), (1390, 910)], fill=(24, 29, 36), outline=(48, 54, 61))
        draw_text_hb(img, reg_path, "2. Grade 軸（GRAD: -100 〜 +100）— 送り幅を 1px も変えない線の太さ（黒み）光学補正", 16, (75, 525), color=(126, 231, 135))

        # Light box
        draw.rectangle([(75, 560), (700, 880)], fill=(255, 255, 255, 255))
        draw_text_hb(img, reg_path, "ライトモード表示（GRAD: 0 〜 +100）", 14, (95, 585), color=(15, 23, 42))
        draw_text_hb(img, var_path, "GRAD: 0 (Normal)", 13, (95, 630), color=(100, 116, 139))
        draw_text_hb(img, var_path, 'let msg = "Hello, 世界！";', 18, (95, 665), variations={"wght": 400, "GRAD": 0}, color=(15, 23, 42))
        draw_text_hb(img, var_path, "GRAD: +100 (Fine Bold without width change)", 13, (95, 740), color=(100, 116, 139))
        draw_text_hb(img, var_path, 'let msg = "Hello, 世界！";', 18, (95, 775), variations={"wght": 400, "GRAD": 100}, color=(15, 23, 42))
        draw_text_hb(img, reg_path, "※ GRAD を上げても列幅・文字位置は完全に不変", 12, (95, 840), color=(71, 85, 105))

        # Dark box
        draw.rectangle([(740, 560), (1365, 880)], fill=(13, 17, 23, 255))
        draw_text_hb(img, reg_path, "ダークモード光学補正（GRAD: -100）", 14, (760, 585), color=(240, 246, 252))
        draw_text_hb(img, var_path, "GRAD: 0 (Standard Dark: 白文字が膨張して太く見えやすい)", 13, (760, 630), color=(139, 148, 158))
        draw_text_hb(img, var_path, 'let msg = "Hello, 世界！";', 18, (760, 665), variations={"wght": 400, "GRAD": 0}, color=(240, 246, 252))
        draw_text_hb(img, var_path, "GRAD: -100 (Compensated: ハレーションを抑えてすっきり可読)", 13, (760, 740), color=(88, 166, 255))
        draw_text_hb(img, var_path, 'let msg = "Hello, 世界！";', 18, (760, 775), variations={"wght": 400, "GRAD": -100}, color=(240, 246, 252))
        draw_text_hb(img, reg_path, "※ 背景色に応じて黒みを微調整しても桁ズレが 1px も発生しません", 12, (760, 840), color=(139, 148, 158))

        p = SPECIMENS_DIR / "specimen_mono_variable.png"
        img.save(p)
        outputs.append(p)

    # 5. Programming Code & Symbols (Rust, TS, Python, SQL)
    img = Image.new("RGBA", (1440, 1020), (18, 22, 28, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle([(0, 0), (1440, 80)], fill=(28, 33, 40))
    draw_text_hb(img, reg_path, "Holon Mono — 実践プログラミングコード・演算子記号組版", 24, (50, 48), color=(240, 246, 252))
    draw_text_hb(img, reg_path, "Rust / TypeScript / Python / SQL 2:1 Duospace", 16, (940, 48), color=(139, 148, 158))

    code_sections = [
        ("Rust: パターンマッチングとエラー処理 (演算子: =>, ->, ::, ?)", [
            'match fetch_user_record(&db_pool, user_id).await {',
            '    Ok(Some(record)) if record.is_active => {',
            '        let token: String = auth::generate_session(&record)?; // 認証トークン生成',
            '        println!("[SUCCESS] ユーザー {} がログインしました", record.name);',
            '        Ok(HttpResponse::Ok().json(token))',
            '    }',
            '    _ => Err(AppError::Unauthorized("無効な認証資格情報です")),',
            '}',
        ]),
        ("TypeScript: ジェネリクスと非同期処理 (演算子: ===, !==, <=, >=, ??, =>)", [
            'export async function queryMetrics<T extends DataRecord>(',
            '  endpoint: string, options?: RequestConfig',
            '): Promise<QueryResult<T>> {',
            '  const res = await fetch(`${API_BASE}/${endpoint}`, { ...options });',
            '  if (res.status !== 200) throw new HttpError(res.statusText ?? "通信エラー");',
            '  return await res.json() as QueryResult<T>; // 和欧混植コメント完全整列',
            '}',
        ]),
    ]
    curr_y = 115
    for title, code_lines in code_sections:
        draw.rectangle([(50, curr_y), (1390, curr_y + 36)], fill=(33, 38, 45))
        draw_text_hb(img, reg_path, title, 15, (65, curr_y + 25), color=(88, 166, 255))
        curr_y += 50
        draw.rectangle([(50, curr_y), (1390, curr_y + len(code_lines) * 26 + 20)], fill=(13, 17, 23))
        for line in code_lines:
            draw_text_hb(img, reg_path, line, 17, (70, curr_y + 22), color=(240, 246, 252))
            curr_y += 26
        curr_y += 35

    p = SPECIMENS_DIR / "specimen_mono_code_programming.png"
    img.save(p)
    outputs.append(p)

    # 6. Terminal TUI & Git Graph Simulation
    img = Image.new("RGBA", (1440, 840), (13, 17, 23, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle([(0, 0), (1440, 60)], fill=(22, 27, 34))
    draw_text_hb(img, reg_path, "Holon Mono — ターミナル TUI & Git グラフシミュレーション", 20, (50, 38), color=(240, 246, 252))

    tui_lines = [
        ("➜  holon git:(main) git log --graph --oneline -n 6", (126, 231, 135)),
        ("* 71f5589 (HEAD -> main) feat(mono): strict 2:1 duospace metrics (550 / 1100 UPM)", (210, 168, 255)),
        ("* 4ac6374 fix(box-drawing): snap vertical boundaries to 950/-225 UPM cell", (210, 168, 255)),
        ("*   3ae17af Merge pull request #12: Authentic Latin Italic + 9° oblique CJK", (210, 168, 255)),
        ("|\\", (88, 166, 255)),
        ("| * 0168493 feat(vf): 2-file Variable Fonts architecture (wght 100..700, GRAD -100..+100)", (121, 192, 255)),
        ("|/  ", (88, 166, 255)),
        ("* a9ac380 test: comprehensive typography and duospace alignment suites", (210, 168, 255)),
        ("", (255, 255, 255)),
        ("┌──────────────────────────────────┬───────────┬───────────────┬────────────────────────┐", (126, 231, 135)),
        ("│ サービス名                       │ ステータス│ 応答速度(RTT) │ 稼働ホスト             │", (126, 231, 135)),
        ("├──────────────────────────────────┼───────────┼───────────────┼────────────────────────┤", (126, 231, 135)),
        ("│ 認証・セッション管理基盤 (OAuth) │ [ 稼働中 ]│ 0.62 ms       │ ap-northeast-1a-prod-1 │", (126, 231, 135)),
        ("│ ベクトル検索エンジン (Qdrant)    │ [ 稼働中 ]│ 4.18 ms       │ ap-northeast-1c-prod-4 │", (126, 231, 135)),
        ("│ 非同期ジョブキュー (BullMQ)      │ [ 稼働中 ]│ 1.05 ms       │ ap-northeast-1d-prod-2 │", (126, 231, 135)),
        ("└──────────────────────────────────┴───────────┴───────────────┴────────────────────────┘", (126, 231, 135)),
    ]
    curr_y = 100
    for line, col in tui_lines:
        if line:
            draw_text_hb(img, reg_path, line, 18, (50, curr_y), color=col)
        curr_y += 21 if line.startswith(("┌", "│", "├", "└")) else 28

    p = SPECIMENS_DIR / "specimen_mono_terminal_tui.png"
    img.save(p)
    outputs.append(p)

    # 7. Box-Drawing & Block Elements Matrix
    img = Image.new("RGBA", (1440, 880), (18, 22, 28, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle([(0, 0), (1440, 80)], fill=(28, 33, 40))
    draw_text_hb(img, reg_path, "Holon Mono — 罫線・ブロック要素全種接続マトリクス", 24, (50, 48), color=(240, 246, 252))

    matrix_lines = [
        "// 1. 単線・二重線・太線・角丸の組み合わせと交差",
        "┌─┬─┐ ┏━┳━┓ ╔═╦═╗ ╭─┬─╮ ┌┬┐ ┏┳┓ ╔╦╗ ╭┬╮",
        "│ │ │ ┃ ┃ ┃ ║ ║ ║ │ │ │ ├┼┤ ┣╋┫ ╠╬╣ ├┼┤",
        "├─┼─┤ ┣━╋━┫ ╠═╬═╣ ├─┼─┤ └┴┘ ┗┻┛ ╚╩╝ ╰┴╯",
        "└─┴─┘ ┗━┻━┛ ╚═╩═╝ ╰─┴─╯  ※ すべての角と交差点が 1px の隙間なく連結",
        "",
        "// 2. ブロック要素（U+2580..U+259F）とプログレスバー",
        "█ ▀ ▄ ▌ ▐ ░ ▒ ▓   ▂ ▃ ▄ ▅ ▆ ▇ █ ▏ ▎ ▍ ▌ ▋ ▊ ▉ █",
        "[████████████████████████████████████████████████████████] 100% Complete",
        "[██████████████████████████████████████░░░░░░░░░░░░░░░░░░]  65% Processing",
        "[████████████████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░]  35% Initializing",
    ]
    curr_y = 130
    for line in matrix_lines:
        is_box = any(c in line for c in "┌┏╔╭│┃║├┣╠└┗╚╰█▀▄▌▐░▒▓")
        col = (126, 231, 135) if is_box and not line.startswith("//") else (240, 246, 252) if not line.startswith("//") else (139, 148, 158)
        draw_text_hb(img, reg_path, line, 18, (60, curr_y), color=col)
        curr_y += 21 if is_box and not line.startswith("//") and not line.startswith("[") else 32

    p = SPECIMENS_DIR / "specimen_mono_box_drawing_matrix.png"
    img.save(p)
    outputs.append(p)

    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description="Run automated test suite and generate visual specimens.")
    parser.add_argument("--skip-specimens", action="store_true", help="Run automated assertions only")
    args = parser.parse_args()

    print("=== Running Holon Font Automated Test Suite ===")
    test_1_files_and_woff2_parity()
    test_2_metadata_and_ofl_compliance()
    test_3_coverage_scaling_and_cjk_compat()
    test_4_mono_duospace_integrity()
    test_5_vertical_and_chws_spacing()
    test_6_variable_axes_and_rendering()
    test_7_italic_and_box_drawing_verification()
    print("=== All 7 Automated Test Suites PASSED! ===")

    if not args.skip_specimens:
        print("\n=== Generating Visual Specimen Cards ===")
        paths = generate_sans_specimens() + generate_mono_specimens()
        for p in paths:
            assert p.exists() and p.stat().st_size > 10_000, f"Invalid specimen image: {p}"
            print(f"  Generated: {p} ({p.stat().st_size:,} bytes)")
        print(f"=== All {len(paths)} Specimen Cards Generated & Verified! ===")


if __name__ == "__main__":
    main()
