# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "brotli>=1.1.0",
#     "fonttools>=4.50.0",
#     "freetype-py>=2.4.0",
#     "pillow>=10.0.0",
#     "pytest>=8.0.0",
#     "uharfbuzz>=0.39.0",
# ]
# ///

from __future__ import annotations

import collections
import itertools
import os
import sys
import unicodedata
from pathlib import Path
from typing import Any

import freetype
import pytest
import uharfbuzz as hb
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw

WEIGHTS = ["Thin", "ExtraLight", "Light", "Regular", "Text", "Medium", "SemiBold", "Bold"]
WEIGHT_VALS = {"Thin": 100, "ExtraLight": 200, "Light": 300, "Regular": 400, "Text": 450, "Medium": 500, "SemiBold": 600, "Bold": 700}
PANOSE_VALS = {"Thin": 2, "ExtraLight": 3, "Light": 4, "Regular": 5, "Text": 5, "Medium": 6, "SemiBold": 7, "Bold": 8}
UPSTREAM_JP_PATH = Path("tmp/plex/packages/plex-sans-jp/fonts/complete/ttf/unhinted/IBMPlexSansJP-Regular.ttf")
SPECIMENS_DIR = Path("specimens")

ALL_EXPECTED = [
    f"{fam}-{('Italic' if it else 'Regular') if w == 'Regular' else f'{w}{it}'}.{ext}"
    for fam in ("HolonSans", "HolonMono") for w in WEIGHTS for it in ("", "Italic") for ext in ("ttf", "woff2")
] + [f"{fam}{it}-Variable.{ext}" for fam in ("HolonSans", "HolonMono") for it in ("", "-Italic") for ext in ("otf", "woff2")]
DESKTOP_FONTS = [f for f in ALL_EXPECTED if f.endswith((".ttf", ".otf"))]
VARIABLE_FONTS = ["HolonSans-Variable.otf", "HolonSans-Italic-Variable.otf", "HolonMono-Variable.otf", "HolonMono-Italic-Variable.otf"]
SANS_REP_FONTS = ["HolonSans-Regular.ttf", "HolonSans-Italic.ttf", "HolonSans-Variable.otf", "HolonSans-Italic-Variable.otf"]
QUADRANT_FONTS = ["HolonSans-Regular.ttf", "HolonMono-Regular.ttf", "HolonSans-Variable.otf", "HolonMono-Variable.otf"]

_CACHE_TT: dict[Path, TTFont] = {}
_CACHE_HB: dict[Path, hb.Face] = {}


def _compute_jis_x_0208() -> set[int]:
    cps: set[int] = set()
    for enc in ("iso2022_jp", "euc_jp", "shift_jis"):
        for b1 in range(0x20, 0x100):
            for b2 in range(0x20, 0x100):
                try:
                    if len(c := bytes([b1, b2]).decode(enc)) == 1:
                        cps.add(ord(c))
                except (UnicodeDecodeError, LookupError):
                    continue
    return cps


JIS_X_0208_CPS = _compute_jis_x_0208()


def get_tt(p: Path) -> TTFont:
    if p not in _CACHE_TT:
        _CACHE_TT[p] = TTFont(p)
    return _CACHE_TT[p]


def get_hb(p: Path) -> hb.Face:
    if p not in _CACHE_HB:
        _CACHE_HB[p] = hb.Face(hb.Blob.from_file_path(str(p)))
    return _CACHE_HB[p]


def shape(p: Path, text: str, feat: dict[str, bool] | None = None, var: dict[str, float] | None = None, vert: bool = False, upm: int = 1000):
    font = hb.Font(get_hb(p))
    font.scale = (upm, upm)
    if var:
        font.set_variations(var)
    buf = hb.Buffer()
    buf.add_str(text)
    if vert:
        buf.direction, buf.script, buf.language = "ttb", "Hani", "ja"
    else:
        buf.guess_segment_properties()
    hb.shape(font, buf, feat if feat is not None else ({"vert": True, "vrt2": True} if vert else {}))
    return list(buf.glyph_infos), list(buf.glyph_positions)


def draw_text_hb(img: Image.Image, p: Path, text: str, sz: int, pos: tuple[int, int], feat=None, var=None, col=(30, 30, 30), vert=False):
    if not text:
        return pos[1] if vert else pos[0]
    face = freetype.Face(str(p))
    face.set_char_size(sz * 64)
    if var and face.get_variation_info() and face.get_variation_info().axes:
        face.set_var_design_coords([var.get(a.tag.strip(), a.default) for a in face.get_variation_info().axes])
    infos, positions = shape(p, text, feat, var, vert, upm=1000)
    x_cur, y_cur = 0, 0
    for info, pos_i in zip(infos, positions):
        face.load_glyph(info.codepoint, freetype.FT_LOAD_RENDER | freetype.FT_LOAD_TARGET_NORMAL)
        bm = face.glyph.bitmap
        if bm.width > 0 and bm.rows > 0:
            gx = pos[0] + round((x_cur + pos_i.x_offset) * sz / 1000) + face.glyph.bitmap_left
            gy = pos[1] + round((y_cur - pos_i.y_offset) * sz / 1000) - face.glyph.bitmap_top
            img.paste(Image.new("RGBA", (bm.width, bm.rows), col + (255,)), (gx, gy), Image.frombytes("L", (bm.width, bm.rows), bytes(bm.buffer)))
        x_cur += pos_i.x_advance
        y_cur -= pos_i.y_advance
    return round(y_cur * sz / 1000) if vert else round(x_cur * sz / 1000)


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--fonts-dir", action="store", default=None, help="Directory containing font binaries")
    parser.addoption("--specimens", action="store_true", default=False, help="Generate visual specimen PNG cards")


@pytest.fixture(scope="session")
def fonts_dir(pytestconfig: pytest.Config) -> Path:
    p = Path(pytestconfig.getoption("--fonts-dir", default=None) or os.environ.get("HOLON_FONTS_DIR", "fonts"))
    assert p.is_dir(), f"Fonts dir not found: {p}"
    return p


# --- 1. File Completeness, WOFF2 Parity, Compact Metrics & OpenType Metadata ---

def test_font_family_completeness(fonts_dir: Path) -> None:
    missing = [f for f in ALL_EXPECTED if not (fonts_dir / f).exists()]
    assert not missing, f"Missing {len(missing)} expected fonts in {fonts_dir}: {missing[:4]}"


@pytest.mark.parametrize("d_name", DESKTOP_FONTS)
def test_woff2_parity_post3_and_compact_metrics(fonts_dir: Path, d_name: str) -> None:
    dp, wp = fonts_dir / d_name, fonts_dir / (d_name.rsplit(".", 1)[0] + ".woff2")
    if not dp.exists():
        pytest.skip(f"{d_name} not built")
    assert wp.exists() and dp.stat().st_size > 100_000 and wp.stat().st_size < dp.stat().st_size
    fd, fw = get_tt(dp), get_tt(wp)
    assert fd["post"].formatType == 3.0 and fd["maxp"].numGlyphs == fw["maxp"].numGlyphs
    assert fd.getBestCmap() == fw.getBestCmap() and set(fd.keys()) == set(fw.keys())
    assert not any(t in fd for t in ("DSIG", "fpgm", "prep", "cvt "))
    # Verify modal advance glyph clustering compacted hmtx and vmtx
    is_mono = "HolonMono" in d_name
    assert fd["hhea"].numberOfHMetrics < (2200 if is_mono else 4500), f"{d_name} hmtx not compacted: {fd['hhea'].numberOfHMetrics}"
    assert fd["vhea"].numberOfVMetrics == 1 if is_mono else fd["vhea"].numberOfVMetrics < 4500


@pytest.mark.parametrize("d_name", DESKTOP_FONTS)
def test_opentype_metadata_and_tables(fonts_dir: Path, d_name: str) -> None:
    p = fonts_dir / d_name
    if not p.exists():
        pytest.skip(f"{d_name} not built")
    font = get_tt(p)
    name_tbl = font["name"]
    names = {r.nameID: r.toUnicode() for r in name_tbl.names if r.platformID == 3}
    for rec in name_tbl.names:
        v = rec.toUnicode()
        if rec.nameID != 0:
            assert "ibm" not in v.lower() and "plex" not in v.lower(), f"Trademark in {d_name} #{rec.nameID}: {v}"

    assert "SIL Open Font License" in names.get(13, "")
    assert "Copyright 2018 IBM Corp. All rights reserved." in names.get(0, "") and "Sandoll" not in names.get(0, "")
    if "Mono" in d_name:
        assert "Copyright 2017 IBM Corp. All rights reserved." in names.get(0, "")
    assert "Wujin Sim" in names.get(9, "") and "Daiji Suzuki" in names.get(9, "")
    assert 20 not in names
    assert "meta" in font and "Jpan" in font["meta"].data.get("dlng", "")
    assert "GDEF" in font and font["GDEF"].table.GlyphClassDef and "STAT" in font
    if d_name.endswith(".ttf"):
        assert "gasp" in font

    os2, head, hhea, post = font["OS/2"], font["head"], font["hhea"], font["post"]
    is_var, is_it = "Variable" in d_name, "Italic" in d_name
    w_name = "Regular" if is_var else next(w for w in WEIGHTS if w in d_name or (w == "Regular" and d_name.endswith("-Italic.ttf")))
    assert os2.achVendID == "HLON" and os2.fsType == 0 and abs(head.fontRevision - 1.0) < 1e-3
    assert os2.usWeightClass == WEIGHT_VALS[w_name] and os2.panose.bWeight == PANOSE_VALS[w_name]
    # Strict OpenType OS/2 fsSelection verification: Bit 7 (USE_TYPO_METRICS) & Bit 8 (WWS) always set; Bit 6 (REGULAR) only on Regular upright
    assert (os2.fsSelection & 0x180) == 0x180
    assert bool(os2.fsSelection & 0x40) == (w_name == "Regular" and not is_it)
    assert bool(os2.fsSelection & 0x20) == (w_name == "Bold") and bool(head.macStyle & 0x01) == (w_name == "Bold")
    assert bool(os2.fsSelection & 0x01) == is_it and bool(head.macStyle & 0x02) == is_it
    if is_it:
        assert abs(post.italicAngle - (-9.0 if "HolonMono" in d_name else -11.0)) < 0.1 and hhea.caretSlopeRun > 0
    else:
        assert post.italicAngle == 0.0 and hhea.caretSlopeRun == 0

    if not is_var:
        base_fam = "Holon Sans" if "HolonSans" in d_name else "Holon Mono"
        if w_name in ("Regular", "Bold"):
            assert names[1] == base_fam and names[2] == ("Bold Italic" if (w_name == "Bold" and is_it) else ("Italic" if is_it else w_name))
        else:
            assert names[1] == f"{base_fam} {w_name}" and names[2] == ("Italic" if is_it else "Regular")
            assert names.get(16) == base_fam and names.get(17) == f"{w_name}{' Italic' if is_it else ''}"


def test_unique_identifiers_and_family_metrics(fonts_dir: Path) -> None:
    files = sorted(fonts_dir.glob("*.ttf")) + sorted(fonts_dir.glob("*.otf"))
    if not files:
        pytest.skip("No fonts found")
    seen_ps, seen_uid, by_fam = {}, {}, collections.defaultdict(dict)
    for p in files:
        font = get_tt(p)
        names = {r.nameID: r.toUnicode() for r in font["name"].names if r.platformID == 3}
        ps, uid = names.get(6, ""), names.get(3, "")
        assert ps and ps not in seen_ps and uid and uid not in seen_uid
        seen_ps[ps] = seen_uid[uid] = p.name
        fam = "HolonMono" if "HolonMono" in p.name else "HolonSans"
        os2, hhea = font["OS/2"], font["hhea"]
        by_fam[fam][p.name] = (hhea.ascent, hhea.descent, hhea.lineGap, os2.sTypoAscender, os2.sTypoDescender, os2.sTypoLineGap)
    for fam, fmap in by_fam.items():
        ref_m = next(iter(fmap.values()))
        assert all(m == ref_m for m in fmap.values()), f"{fam} vertical metrics mismatch"


def test_ofl_license_text(fonts_dir: Path) -> None:
    ofl_p = fonts_dir / "OFL.txt"
    if not ofl_p.exists():
        pytest.skip("OFL.txt not present in fonts-dir")
    content = ofl_p.read_bytes()
    assert b"SIL OPEN FONT LICENSE Version 1.1" in content and b"Daiji Suzuki" in content
    lic_src = Path("tmp/plex/packages/plex-sans-jp/LICENSE.txt")
    if lic_src.exists():
        assert lic_src.read_bytes() in content


# --- 2. Glyph Bounds, Clipping, Repertoire & Authentic Italic ---

@pytest.mark.parametrize("d_name", [f for f in DESKTOP_FONTS if f.endswith(".ttf")])
def test_glyph_bounds_within_win_clipping(fonts_dir: Path, d_name: str) -> None:
    p = fonts_dir / d_name
    if not p.exists():
        pytest.skip(f"{d_name} not built")
    font = get_tt(p)
    os2, head, cmap, glyf = font["OS/2"], font["head"], font.getBestCmap(), font["glyf"]
    if "HolonMono" in d_name:
        assert head.yMax <= os2.usWinAscent and head.yMin >= -os2.usWinDescent
    else:
        for cp in (JIS_X_0208_CPS | set(range(0x20, 0x180)) | set(range(0x3040, 0x3100))):
            if cp in cmap and glyf[cmap[cp]].numberOfContours > 0:
                g = glyf[cmap[cp]]
                assert g.yMax <= os2.usWinAscent and g.yMin >= -os2.usWinDescent, f"{d_name} U+{cp:04X} clipped"


@pytest.mark.parametrize("font_name", ["HolonSans-Regular.ttf", "HolonMono-Regular.ttf"])
def test_cmap_outlines_and_jis_x_0208_coverage(fonts_dir: Path, font_name: str) -> None:
    p = fonts_dir / font_name
    if not p.exists():
        pytest.skip(f"{font_name} not built")
    font = get_tt(p)
    cmap, glyf = font.getBestCmap(), font["glyf"]
    empty = [
        f"U+{cp:04X}" for cp, g in cmap.items()
        if cp < 0x110000 and unicodedata.category(chr(cp)) not in ("Zs", "Zl", "Zp", "Cc", "Cf")
        and cp not in (0x20, 0xA0, 0x3000) and glyf[g].numberOfContours == 0
    ]
    assert not empty, f"{font_name} has empty outlines: {empty[:5]}"
    missing_jis = [cp for cp in JIS_X_0208_CPS if cp not in cmap]
    assert not missing_jis, f"{font_name} missing {len(missing_jis)} JIS X 0208 chars"


@pytest.mark.parametrize("font_name", QUADRANT_FONTS)
def test_cjk_compatibility_ideographs(fonts_dir: Path, font_name: str) -> None:
    p = fonts_dir / font_name
    if not p.exists():
        pytest.skip(f"{font_name} not built")
    cmap = get_tt(p).getBestCmap()
    present = sum(
        1 for code in range(0xF900, 0xFB00)
        if len(d := unicodedata.normalize("NFKD", chr(code))) == 1 and ord(d) in cmap and code in cmap
    )
    assert present >= 456 and cmap[0xFA11] != cmap[0x5D0E] and cmap[0xF900] == cmap[0x8C48]


def test_authentic_italic_structure(fonts_dir: Path) -> None:
    fr, fi = fonts_dir / "HolonSans-Regular.ttf", fonts_dir / "HolonSans-Italic.ttf"
    if not (fr.exists() and fi.exists()):
        pytest.skip("Sans Regular/Italic not present")
    gr = get_tt(fr)["glyf"][get_tt(fr).getBestCmap()[ord("f")]]
    gi = get_tt(fi)["glyf"][get_tt(fi).getBestCmap()[ord("f")]]
    assert gr.yMin >= 0 and gi.yMin < -100, f"Italic 'f' not cursive: yMin={gi.yMin}"


# --- 3. Mono Duospace Grid, Cross-Weight Invariance, EAW & Box Drawing ---

@pytest.mark.parametrize("mname", [f for f in DESKTOP_FONTS if "HolonMono" in f])
def test_mono_duospace_advances_and_features(fonts_dir: Path, mname: str) -> None:
    p = fonts_dir / mname
    if not p.exists():
        pytest.skip(f"{mname} not built")
    font = get_tt(p)
    assert not [(g, w) for g, (w, _) in font["hmtx"].metrics.items() if w not in (0, 550, 1100)]
    assert not [(g, h) for g, (h, _) in font["vmtx"].metrics.items() if h != 1100]
    assert "GPOS" not in font and "BASE" not in font and font["post"].isFixedPitch == 1
    os2 = font["OS/2"]
    assert (os2.sTypoAscender, os2.sTypoDescender, os2.sTypoLineGap, os2.panose.bProportion) == (950, -225, 0, 9)
    for s, cells in [("//", 2), ("AV", 2), ("fi", 2), ("0123456789", 10), ("ｶﾀｶﾅ", 4), ("日本語", 6), ("Hello, 世界！", 13)]:
        assert sum(pos.x_advance for pos in shape(p, s)[1]) == cells * 550
    assert shape(p, "0", feat={"zero": False})[0][0].codepoint != shape(p, "0", feat={"zero": True})[0][0].codepoint
    gsub = {r.FeatureTag for r in font["GSUB"].table.FeatureList.FeatureRecord}
    assert {"ccmp", "locl", "vert", "vrt2", "fwid", "zero"}.issubset(gsub)


def test_mono_cross_weight_and_variable_width_invariance(fonts_dir: Path) -> None:
    """Verify 100% of glyphs in Holon Mono have identical advance widths across all static weights and VF axes."""
    ref_p = fonts_dir / "HolonMono-Regular.ttf"
    if not ref_p.exists():
        pytest.skip("HolonMono-Regular.ttf not built")
    ref_f = get_tt(ref_p)
    ref_cmap, ref_hmtx = ref_f.getBestCmap(), ref_f["hmtx"].metrics
    for w in WEIGHTS:
        for it in ("", "Italic"):
            name = f"HolonMono-{('Italic' if it else 'Regular') if w == 'Regular' else f'{w}{it}'}.ttf"
            p = fonts_dir / name
            if not p.exists():
                continue
            f = get_tt(p)
            cmap, hmtx = f.getBestCmap(), f["hmtx"].metrics
            diffs = [f"U+{u:04X}" for u, g in cmap.items() if u in ref_cmap and hmtx[g][0] != ref_hmtx[ref_cmap[u]][0]]
            assert not diffs, f"{name} width mismatch vs Regular: {diffs[:5]}"

    for vname in ("HolonMono-Variable.otf", "HolonMono-Italic-Variable.otf"):
        vp = fonts_dir / vname
        if not vp.exists():
            continue
        vf = get_tt(vp)
        for tag in ("HVAR", "VVAR"):
            for vd in vf[tag].table.VarStore.VarData:
                assert not [it for it in vd.Item if any(it)], f"{vname} {tag} has non-zero advance deltas"


@pytest.mark.parametrize("mname", ["HolonMono-Regular.ttf", "HolonMono-Variable.otf"])
def test_mono_east_asian_width(fonts_dir: Path, mname: str) -> None:
    p = fonts_dir / mname
    if not p.exists():
        pytest.skip(f"{mname} not built")
    font = get_tt(p)
    cmap = font.getBestCmap()
    hb_font = hb.Font(get_hb(p))
    hb_font.scale = (1000, 1000)
    if "Variable" in mname:
        hb_font.set_variations({"wght": 400, "GRAD": 0})
    viol = [
        f"U+{cp:04X} ({chr(cp)}): {hb_font.get_glyph_h_advance(font.getGlyphID(g))}"
        for cp, g in cmap.items() if cp < 0x110000
        and unicodedata.east_asian_width(chr(cp)) in ("W", "F")
        and hb_font.get_glyph_h_advance(font.getGlyphID(g)) != 1100
    ]
    assert not viol, f"{mname} EAW=W/F violations: {viol[:5]}"


def test_mono_box_and_block_snaps(fonts_dir: Path) -> None:
    p = fonts_dir / "HolonMono-Regular.ttf"
    if not p.exists():
        pytest.skip("HolonMono-Regular.ttf not built")
    glyf, cmap = get_tt(p)["glyf"], get_tt(p).getBestCmap()
    gh, gv, gb = glyf[cmap[0x2500]], glyf[cmap[0x2502]], glyf[cmap[0x2588]]
    assert gh.xMin <= 0 and gh.xMax >= 550 and gv.yMin <= -225 and gv.yMax >= 950
    assert (gb.xMin, gb.xMax, gb.yMin, gb.yMax) == (0, 550, -225, 950)
    assert glyf[cmap[0x2580]].yMax == 950
    heights = [glyf[cmap[cp]].yMax - glyf[cmap[cp]].yMin for cp in range(0x2581, 0x2589)]
    assert all(glyf[cmap[cp]].yMin == -225 for cp in range(0x2581, 0x2589))
    assert all(h2 > h1 > 0 for h1, h2 in itertools.pairwise(heights)), f"Non-increasing heights: {heights}"


@pytest.mark.parametrize("mname", ["HolonMono-Regular.ttf", "HolonMono-Variable.otf"])
def test_mono_box_drawing_grid_continuity(fonts_dir: Path, mname: str) -> None:
    """Verify that vertical lines and crosses connect with 0px gap at line height dy=21."""
    p = fonts_dir / mname
    if not p.exists():
        pytest.skip(f"{mname} not built")
    img = Image.new("RGBA", (120, 120), (0, 0, 0, 255))
    var_dict = {"wght": 400, "GRAD": 0} if "Variable" in mname else None
    draw_text_hb(img, p, "│", 18, (30, 30), var=var_dict, col=(255, 255, 255))
    draw_text_hb(img, p, "┼", 18, (30, 30 + 21), var=var_dict, col=(255, 255, 255))
    pixels = img.load()
    stem_x = next((x for x in range(25, 45) if pixels[x, 30][0] > 100), None)
    assert stem_x is not None, f"Stem column not found in {mname}"
    gap_y = [y for y in range(25, 55) if pixels[stem_x, y][0] < 30]
    assert not gap_y, f"{mname} vertical gap found in box drawing at y={gap_y}"


# --- 4. Vertical Writing (vert/vrt2/vhea/vmtx/VORG), chws/vchw & GPOS Shaping ---

@pytest.mark.parametrize("sname", SANS_REP_FONTS)
def test_chws_and_vchw_compaction(fonts_dir: Path, sname: str) -> None:
    p = fonts_dir / sname
    if not p.exists():
        pytest.skip(f"{sname} not built")
    for text, exp in [("「『", -500), ("』。", -500), ("・：；", -1000), ("「・」", -500), ("。　", -500), ("： 東京", -500)]:
        assert sum(pos.x_advance for pos in shape(p, text, feat={"chws": True})[1]) - sum(pos.x_advance for pos in shape(p, text, feat={"chws": False})[1]) == exp
    for text in ("あ「", "」あ", "。あ", "「", "」", "（", "）", "あ、", "か。"):
        assert sum(pos.x_advance for pos in shape(p, text, feat={"chws": True})[1]) == sum(pos.x_advance for pos in shape(p, text, feat={"chws": False})[1])
    for text, exp in [("「『", -500), ("』。", -500), ("・：；", -1000), ("「・」", -500), ("。　", -500), ("： A", -500)]:
        assert sum(-pos.y_advance for pos in shape(p, text, feat={"vert": True, "vchw": True}, vert=True)[1]) - sum(-pos.y_advance for pos in shape(p, text, feat={"vert": True, "vchw": False}, vert=True)[1]) == exp


@pytest.mark.parametrize("fname", ["HolonSans-Regular.ttf", "HolonSans-Italic.ttf", "HolonSans-Variable.otf", "HolonMono-Regular.ttf", "HolonMono-Variable.otf"])
def test_vertical_writing_substitutions_and_metrics(fonts_dir: Path, fname: str) -> None:
    """Verify vert/vrt2 glyph substitutions for yakumono, brackets, and small kana, plus vhea/vmtx/VORG."""
    p = fonts_dir / fname
    if not p.exists():
        pytest.skip(f"{fname} not built")
    vert_chars = "、。「」『』（）【】〔〕〈〉《》［］｛｝ー〜―…‥：；ぁぃぅぇぉっゃゅょァィゥェォッャュョ"
    for ch in vert_chars:
        gid_h = shape(p, ch, vert=False)[0][0].codepoint
        gid_v = shape(p, ch, vert=True)[0][0].codepoint
        assert gid_h != gid_v, f"{fname} missing vertical substitution for '{ch}' (U+{ord(ch):04X})"

    font = get_tt(p)
    assert "vhea" in font and "vmtx" in font
    assert font["vhea"].ascent == 500 and font["vhea"].descent == -500
    if fname.endswith(".otf"):
        assert "VORG" in font and font["VORG"].defaultVertOriginY == 880
    full_w = 1100 if "Mono" in fname else 1000
    cmap, hmtx, vmtx = font.getBestCmap(), font["hmtx"].metrics, font["vmtx"].metrics
    for u in ((0x3000,) if "Mono" in fname else (0x2015, 0x2025, 0x2026, 0x2103, 0x3000)):
        assert hmtx[cmap[u]][0] == full_w and vmtx[cmap[u]][0] == full_w


@pytest.mark.parametrize("sname", [f for f in DESKTOP_FONTS if "HolonSans" in f])
def test_sans_gpos_and_gsub_feature_parity(fonts_dir: Path, sname: str) -> None:
    """Verify Static and Variable Sans have identical GSUB/GPOS features and active kern/palt/vpal/fwid shaping."""
    p = fonts_dir / sname
    if not p.exists():
        pytest.skip(f"{sname} not built")
    font = get_tt(p)
    assert "BASE" in font
    gpos_feats = {r.FeatureTag for r in font["GPOS"].table.FeatureList.FeatureRecord}
    assert {"chws", "vchw", "halt", "vhal", "kern", "palt", "vkrn", "vpal"}.issubset(gpos_feats)
    if UPSTREAM_JP_PATH.exists():
        up_gsub = {r.FeatureTag for r in get_tt(UPSTREAM_JP_PATH)["GSUB"].table.FeatureList.FeatureRecord}
        assert up_gsub.issubset({r.FeatureTag for r in font["GSUB"].table.FeatureList.FeatureRecord})

    # Active shaping verification for kern, palt, vpal, and fwid
    assert sum(pos.x_advance for pos in shape(p, "AV", feat={"kern": True})[1]) < sum(pos.x_advance for pos in shape(p, "AV", feat={"kern": False})[1])
    assert sum(pos.x_advance for pos in shape(p, "「あ」", feat={"palt": True})[1]) < sum(pos.x_advance for pos in shape(p, "「あ」", feat={"palt": False})[1])
    assert sum(-pos.y_advance for pos in shape(p, "「あ」", feat={"vert": True, "vpal": True}, vert=True)[1]) < sum(-pos.y_advance for pos in shape(p, "「あ」", feat={"vert": True, "vpal": False}, vert=True)[1])
    assert sum(pos.x_advance for pos in shape(p, "123", feat={"fwid": True})[1]) == 3000
    info_plain, pos_plain = shape(p, "0", feat={"zero": False})
    info_slashed, pos_slashed = shape(p, "0", feat={"zero": True})
    assert info_plain[0].codepoint != info_slashed[0].codepoint
    assert pos_plain[0].x_advance == pos_slashed[0].x_advance == 612



# --- 5. Variable Fonts: fvar, avar, STAT, GRAD & Static Parity ---

@pytest.mark.parametrize("vname", VARIABLE_FONTS)
def test_variable_axes_avar_and_stat(fonts_dir: Path, vname: str) -> None:
    p = fonts_dir / vname
    if not p.exists():
        pytest.skip(f"{vname} not built")
    vf = get_tt(p)
    assert all(t in vf for t in ("STAT", "fvar", "avar", "HVAR", "VVAR"))
    axes = {a.axisTag: (a.minValue, a.defaultValue, a.maxValue) for a in vf["fvar"].axes}
    assert axes["wght"] == (100.0, 400.0, 700.0) and axes["GRAD"] == (-100.0, 0.0, 100.0)
    assert len(vf["avar"].segments["wght"]) >= 7
    assert [a.AxisTag for a in vf["STAT"].table.DesignAxisRecord.Axis] == ["wght", "GRAD", "ital"]
    insts = {vf["name"].getDebugName(i.subfamilyNameID): i.coordinates["wght"] for i in vf["fvar"].instances}
    for wn, wv in WEIGHT_VALS.items():
        matched = [c for name, c in insts.items() if name in (wn, f"{wn} Italic", "Italic" if wn == "Regular" else "")]
        assert matched and abs(matched[0] - float(wv)) < 1.0


@pytest.mark.parametrize("vname", VARIABLE_FONTS)
def test_variable_grad_advance_and_optical_density(fonts_dir: Path, vname: str) -> None:
    """Verify GRAD preserves advance widths across the repertoire while strictly modulating ink density."""
    p = fonts_dir / vname
    if not p.exists():
        pytest.skip(f"{vname} not built")
    vf = get_tt(p)
    hb_font = hb.Font(get_hb(p))
    hb_font.scale = (1000, 1000)
    cmap, is_mono, diffs = vf.getBestCmap(), "Mono" in vname, []
    for cp in list(cmap.keys())[::16]:
        gid = vf.getGlyphID(cmap[cp])
        advs = []
        for g in (-100, 0, 100):
            hb_font.set_variations({"wght": 400, "GRAD": g})
            advs.append(hb_font.get_glyph_h_advance(gid))
        if not (advs[0] == advs[1] == advs[2]) or (is_mono and advs[1] not in (0, 550, 1100)):
            diffs.append(f"U+{cp:04X}")
    assert not diffs, f"{vname} GRAD altered advances: {diffs[:4]}"

    face = freetype.Face(str(p))
    face.set_char_size(24 * 64)
    for ch in ("a", "w", "x", "v", "y", "A", "0", "あ", "森"):
        inks = []
        for grad in (-100, 0, 100):
            face.set_var_design_coords([400, grad])
            face.load_char(ch, freetype.FT_LOAD_RENDER | freetype.FT_LOAD_TARGET_NORMAL)
            inks.append(sum(face.glyph.bitmap.buffer))
        assert inks[0] <= inks[1] <= inks[2] and inks[2] > inks[0], f"{vname} '{ch}' ink not scaling with GRAD: {inks}"


def test_static_vf_advance_parity(fonts_dir: Path) -> None:
    pairs = [
        ("HolonSans-Regular.ttf", "HolonSans-Variable.otf", 3),
        ("HolonSans-Italic.ttf", "HolonSans-Italic-Variable.otf", 3),
        ("HolonMono-Regular.ttf", "HolonMono-Variable.otf", 0),
        ("HolonMono-Italic.ttf", "HolonMono-Italic-Variable.otf", 0),
    ]
    for s_name, v_name, tol in pairs:
        sp, vp = fonts_dir / s_name, fonts_dir / v_name
        if not (sp.exists() and vp.exists()):
            pytest.skip(f"{s_name} or {v_name} not built")
        fs, fv = get_tt(sp), get_tt(vp)
        cmap_s, cmap_v = fs.getBestCmap(), fv.getBestCmap()
        font_s, font_v = hb.Font(get_hb(sp)), hb.Font(get_hb(vp))
        font_s.scale = font_v.scale = (1000, 1000)
        font_v.set_variations({"wght": 400, "GRAD": 0})
        viol = [
            (hex(cp), font_s.get_glyph_h_advance(fs.getGlyphID(cmap_s[cp])), font_v.get_glyph_h_advance(fv.getGlyphID(cmap_v[cp])))
            for cp in set(cmap_s).intersection(cmap_v)
            if abs(font_s.get_glyph_h_advance(fs.getGlyphID(cmap_s[cp])) - font_v.get_glyph_h_advance(fv.getGlyphID(cmap_v[cp]))) > tol
        ]
        assert not viol, f"{s_name} vs {v_name} advance mismatch ({len(viol)} chars): {viol[:5]}"


@pytest.mark.parametrize("vname", VARIABLE_FONTS)
def test_variable_weight_monotonicity_fine_grained(fonts_dir: Path, vname: str) -> None:
    """Verify that font weights strictly scale monotonically across wght 100..700 for key glyphs."""
    p = fonts_dir / vname
    if not p.exists():
        pytest.skip(f"{vname} not built")
    face = freetype.Face(str(p))
    face.set_char_size(24 * 64)
    wght_steps = [100, 200, 300, 400, 500, 600, 700]

    # Representative character set including variable interpolation stress-test glyphs (a, w, x, v, y)
    for ch in ("a", "w", "x", "v", "y", "f", "g", "0", "8", "あ", "森"):
        inks = []
        for w in wght_steps:
            face.set_var_design_coords([w, 0])
            face.load_char(ch, freetype.FT_LOAD_RENDER | freetype.FT_LOAD_TARGET_NORMAL)
            inks.append(sum(face.glyph.bitmap.buffer))
        for i in range(len(inks) - 1):
            assert inks[i] < inks[i + 1], f"{vname} '{ch}' weight not monotonic: {inks}"
        assert inks[-1] >= 1.8 * inks[0], f"{vname} '{ch}' insufficient weight expansion: {inks[0]} -> {inks[-1]}"

    if "Mono" in vname:
        for light_ch, heavy_ch in (("│", "┃"), ("┼", "╋")):
            face.set_var_design_coords([400, 0])
            face.load_char(light_ch, freetype.FT_LOAD_RENDER | freetype.FT_LOAD_TARGET_NORMAL)
            ink_l = sum(face.glyph.bitmap.buffer)
            face.load_char(heavy_ch, freetype.FT_LOAD_RENDER | freetype.FT_LOAD_TARGET_NORMAL)
            ink_h = sum(face.glyph.bitmap.buffer)
            assert ink_h >= 1.7 * ink_l


# --- 6. Declarative Visual Specimen Engine ---

def _render_card(p_out: Path, w: int, h: int, title: str, title_f: Path, els: list[Any], dark: bool = False) -> Path:
    img = Image.new("RGBA", (w, h), (18, 22, 28, 255) if dark else (248, 249, 250, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle([(40, 25), (w - 40, 95)], fill=(28, 33, 40) if dark else (255, 255, 255), outline=(48, 54, 61) if dark else (225, 228, 232))
    draw_text_hb(img, title_f, title, 24, (65, 68), col=(240, 246, 252) if dark else (15, 23, 42))
    for el in els:
        cmd = el[0]
        if cmd == "rect":
            draw.rectangle(el[1], fill=el[2], outline=el[3] if len(el) > 3 else None, width=el[4] if len(el) > 4 else 1)
        elif cmd == "t":
            f, txt, sz, pos = el[1], el[2], el[3], el[4]
            col = el[5] if len(el) > 5 else ((240, 246, 252) if dark else (15, 23, 42))
            draw_text_hb(img, f, txt, sz, pos, feat=el[6] if len(el) > 6 else None, var=el[7] if len(el) > 7 else None, col=col, vert=el[8] if len(el) > 8 else False)
        elif cmd == "lines":
            f, lines, sz, x, sy, dy = el[1], el[2], el[3], el[4], el[5], el[6]
            col = el[7] if len(el) > 7 else ((240, 246, 252) if dark else (15, 23, 42))
            for i, line in enumerate(lines):
                draw_text_hb(img, f, line, sz, (x, sy + i * dy), col=col)
    SPECIMENS_DIR.mkdir(parents=True, exist_ok=True)
    img.save(p_out)
    return p_out


def generate_all_glyphs_contact_sheet(p_font: Path, p_out: Path, title: str) -> Path:
    """Generate high-density contact sheet containing 100% of all glyphs in the font."""
    face = freetype.Face(str(p_font))
    num_glyphs = face.num_glyphs
    cols = 140
    rows = (num_glyphs + cols - 1) // cols
    cell_w, cell_h, header_h = 18, 20, 100
    img_w, img_h = cols * cell_w + 80, rows * cell_h + header_h + 40

    img = Image.new("RGBA", (img_w, img_h), (255, 255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle([(40, 20), (img_w - 40, 85)], fill=(248, 250, 252), outline=(226, 232, 240))
    draw_text_hb(img, p_font, title, 20, (60, 48), col=(15, 23, 42))
    draw.text((60, 60), f"Total Glyphs: {num_glyphs:,}  |  Grid: {cols} columns x {rows} rows  |  100% Complete Repertoire", fill=(100, 116, 139))

    face.set_char_size(12 * 64)
    for gid in range(num_glyphs):
        face.load_glyph(gid, freetype.FT_LOAD_RENDER | freetype.FT_LOAD_TARGET_NORMAL)
        bm = face.glyph.bitmap
        r, c = gid // cols, gid % cols
        if bm.width > 0 and bm.rows > 0:
            gx = 40 + c * cell_w + (cell_w - bm.width) // 2
            gy = header_h + r * cell_h + 14 - face.glyph.bitmap_top
            glyph_img = Image.frombytes("L", (bm.width, bm.rows), bytes(bm.buffer))
            img.paste(Image.new("RGBA", (bm.width, bm.rows), (30, 41, 59, 255)), (gx, gy), glyph_img)

    SPECIMENS_DIR.mkdir(parents=True, exist_ok=True)
    img.save(p_out)
    return p_out


def generate_all_specimens(fonts_dir: Path) -> list[Path]:
    sr, sb, si = fonts_dir / "HolonSans-Regular.ttf", fonts_dir / "HolonSans-Bold.ttf", fonts_dir / "HolonSans-Italic.ttf"
    sv, siv = fonts_dir / "HolonSans-Variable.otf", fonts_dir / "HolonSans-Italic-Variable.otf"
    mr, mi, mv = fonts_dir / "HolonMono-Regular.ttf", fonts_dir / "HolonMono-Italic.ttf", fonts_dir / "HolonMono-Variable.otf"
    out = []

    out.append(_render_card(SPECIMENS_DIR / "specimen_typography.png", 1200, 780, "Holon Sans — Typography & Visual Balance", sb, [
        ("rect", [(40, 120), (1160, 500)], (255, 255, 255), (225, 228, 232)),
        ("t", sb, "双方向スケーリング調整: 和文字 0.97x ＋ 欧文字 1.02x", 22, (65, 165), (37, 99, 235)),
        ("lines", sr, ["Holon Sans（ホロン・サンズ）は、和文の圧迫感を抑え、欧文との美しい調和を追求したフォントです。",
                       "Modern UI design requires seamless balance between Latin alphabets and Japanese kanji/kana.",
                       "和文字を0.97倍に引き締めて中央配置し、欧文を1.02倍に調整。双方が一方的に拡大・縮小されない自然な混植です。",
                       "Sphinx of black quartz, judge my vow. 1234567890 (0123456789) [A-Z, a-z] {+ - * / = % &}"], 19, 65, 210, 42, (51, 65, 85)),
        ("t", si, "イタリック混植テスト: 全体と部分の哲学。The term Holon represents a whole that is part of a larger whole.", 19, (65, 380), (30, 41, 59)),
        ("t", sr, "「『美しい約物の配置』と（洗練された組版）が、アプリの体験価値を一段階引き上げます。」", 20, (65, 425), (15, 23, 42), {"chws": True}),
        ("rect", [(40, 520), (1160, 740)], (255, 255, 255), (225, 228, 232)),
        ("t", sb, "マージされた拡張文字セット（キリル文字・通貨記号・発音区別符）", 18, (65, 555), (16, 185, 129)),
        ("lines", sr, ["Currencies:   $ 628,000   € 450,000   ¥ 1,280,000   £ 380,000   ₽ 500,000   ₴ 240,000",
                       "Cyrillic:     Съешь же ещё этих мягких французских булок, da выпей чаю. (Привет, мир!)",
                       "Diacritics:   Ångström, café, naïve, façade, Zürich, Łódź, São Paulo, Đà Nẵng, Miloš"], 18, 65, 595, 40, (30, 41, 59)),
    ]))

    c_els = [("rect", [(40, 115), (1160, 465)], (255, 255, 255), (226, 232, 240)), ("rect", [(65, 135), (230, 163)], (239, 68, 68)), ("t", sb, "chws OFF (全角固定)", 13, (75, 155), (255, 255, 255)),
             ("rect", [(40, 485), (1160, 835)], (255, 255, 255), (59, 130, 246), 2), ("rect", [(65, 505), (230, 533)], (37, 99, 235)), ("t", sb, "chws ON (自動ツメ)", 13, (75, 525), (255, 255, 255))]
    for i, (s, hi) in enumerate([("中点類・コロン連続： ・：；　および　・・・・　（連続中点類の自動二分ツメ）", True),
                                 ("中点と括弧： 「・」「：」「；」　項目：「東京」　（括弧との四分・二分ツメ）", False),
                                 ("連続約物： 「「連続開き括弧」」。（閉じ括弧と句点）", False),
                                 ("句点＋全角空白： 東京都。　次の段落（句点余白＋全角空白のアキ量確認）", True),
                                 ("約物混在： 開き「　全角スペース　」閉じ、　読点と空白、", False)]):
        c_els.append(("t", sr, s, 20 if i < 4 else 18, (65, 200 + i * 45), (220, 38, 38) if hi else (51, 65, 85), {"chws": False}))
        c_els.append(("t", sb if hi else sr, s, 20 if i < 4 else 18, (65, 570 + i * 45), (16, 185, 129) if hi else (15, 23, 42), {"chws": True}))
    out.append(_render_card(SPECIMENS_DIR / "specimen_chws_comparison.png", 1200, 870, "Holon Sans — 約物半角ツメ（chws）＆ 空白検証", sb, c_els))

    s_top, s_bot = "日本語も英語も美しく傾斜。Holon Sans: Expressive typography with 11° slant. 0123456789", "「吾輩は猫である。名前はまだ無い。」 The quick brown fox jumps over the lazy dog."
    out.append(_render_card(SPECIMENS_DIR / "specimen_italic_oblique.png", 1200, 560, "Holon Sans — 和文イタリック（11.0° オブリーク傾斜）", sb, [
        ("rect", [(40, 115), (1160, 305)], (255, 255, 255), (226, 232, 240)), ("t", sb, "Regular (直立・Upright)", 16, (65, 150), (37, 99, 235)),
        ("t", sr, s_top, 22, (65, 205)), ("t", sr, s_bot, 19, (65, 250), (71, 85, 105)),
        ("rect", [(40, 325), (1160, 515)], (255, 255, 255), (147, 51, 234), 2), ("t", sb, "Italic (欧文イタリック ＋ 和文11.0° オブリーク)", 16, (65, 360), (147, 51, 234)),
        ("t", si, s_top, 22, (65, 415)), ("t", si, s_bot, 19, (65, 460), (71, 85, 105)),
    ]))

    v_cols = [(1080, "『ホロン・サンズ』縦書きの美学。"), (1015, "国境を越え、文字と文字が響き合う。"), (950, "「吾輩は猫である。名前はまだ無い。"), (885, "どこで生れたかとんと見当がつかぬ。"),
              (820, "何でも薄暗いじめじめした所で"), (755, "ニャーニャー泣いていた事だけは記憶している。」"), (690, "縦書き約物テスト：「（東京都）」ー新宿・渋谷。"), (625, "項目１：定義；項目２：検証；結び。・：；")]
    v_els = [("rect", [(40, 115), (1160, 795)], (255, 255, 255), (226, 232, 240)),
             ("t", sb, "縦書きフィーチャー（vert / vrt2）および縦約物ツメ（vchw）による完全対応", 16, (65, 150), (37, 99, 235))] + [
        ("t", sr, txt, 23, (x, 225), (15, 23, 42), None, None, True) for x, txt in v_cols
    ] + [("rect", [(440, 195), (595, 755)], (248, 250, 252), (226, 232, 240)),
         ("t", sb, "vchw ON", 14, (525, 225), (37, 99, 235)), ("t", sb, "vchw OFF", 14, (452, 225), (220, 38, 38)),
         ("t", sb, "「『連続』」。・：；「・」", 22, (555, 260), (37, 99, 235), {"vert": True, "vchw": True}, None, True),
         ("t", sr, "「『連続』」。・：；「・」", 22, (480, 260), (220, 38, 38), {"vert": True, "vchw": False}, None, True)]
    out.append(_render_card(SPECIMENS_DIR / "specimen_vertical.png", 1200, 840, "Holon Sans — 縦書き組版（vert・vrt2・vchw 対応）", sb, v_els))

    var_els = [
        ("rect", [(40, 115), (1360, 480)], (255, 255, 255), (226, 232, 240)),
        ("t", sb, "1. 直立バリアブルフォント（HolonSans-Variable.otf）: 全7ウエイト段階補間スペクトラム", 16, (65, 145), (37, 99, 235)),
        ("rect", [(40, 500), (1360, 865)], (255, 255, 255), (226, 232, 240)),
        ("t", sb, "2. イタリックバリアブルフォント（HolonSans-Italic-Variable.otf）: 和欧11.0°傾斜 全7ウエイト補間", 16, (65, 530), (147, 51, 234)),
    ]
    wght_spectrum = [(100, "Thin (100)"), (200, "ExtraLight (200)"), (300, "Light (300)"), (400, "Regular (400)"),
                     (500, "Medium (500)"), (600, "SemiBold (600)"), (700, "Bold (700)")]
    for i, (w_val, label) in enumerate(wght_spectrum):
        y_r, y_i = 180 + i * 40, 565 + i * 40
        var_els.append(("t", sr, f"{label:<16}", 12, (65, y_r + 2), (100, 116, 139)))
        var_els.append(("t", sv, "a w x v y  A B C  0 1 8  あいうえお  森国鬱  The quick brown fox", 18, (210, y_r), (15, 23, 42), None, {"wght": w_val, "GRAD": 0}))
        var_els.append(("t", sr, f"{label:<16}", 12, (65, y_i + 2), (100, 116, 139)))
        var_els.append(("t", siv, "a w x v y  A B C  0 1 8  あいうえお  森国鬱  The quick brown fox", 18, (210, y_i), (15, 23, 42), None, {"wght": w_val, "GRAD": 0}))

    var_els.extend([
        ("rect", [(40, 885), (1360, 1185)], (255, 255, 255), (226, 232, 240)),
        ("t", sb, "3. Grade 軸（GRAD: -100 〜 +100）— レイアウト固定の精密太さ調整", 16, (65, 915), (217, 119, 6)),
        ("rect", [(65, 965), (685, 1155)], (248, 250, 252), (226, 232, 240)),
        ("t", sv, "白背景の標準ウェイト (GRAD: 0)。レイアウト完全維持。", 15, (85, 1035), (15, 23, 42), None, {"wght": 400, "GRAD": 0}),
        ("t", sv, "GRAD: +100 で視認性向上: 細部の線の太さのみが増加。", 14, (85, 1085), (15, 23, 42), None, {"wght": 400, "GRAD": 100}),
        ("rect", [(715, 965), (1335, 1155)], (15, 23, 42)),
        ("t", sv, "黒背景で光の膨張を抑え、すっきり可読性を保つ (GRAD: -100)。", 15, (735, 1035), (241, 245, 249), None, {"wght": 400, "GRAD": -100}),
    ])
    out.append(_render_card(SPECIMENS_DIR / "specimen_variable_spectrum.png", 1400, 1230, "Holon Sans — 2ファイル分離バリアブルフォント（全ウエイト段階補間）", sb, var_els))

    cjk_els = [("rect", [(40, 115), (1160, 575)], (255, 255, 255), (226, 232, 240)),
               ("t", sb, "JIS X 0213 固有互換漢字（﨑・福・諸 等）＋ 非JIS CJK互換漢字 346字 ＝ 計468字完全網羅", 16, (65, 160), (37, 99, 235)),
               ("t", sr, "人名・地名・公文書等で用いられる互換漢字（U+F900..U+FAFF）の豆腐化（.notdef）を完全に防止します。", 14, (65, 193), (71, 85, 105))]
    for idx, (cp_s, can_s, ch) in enumerate([("U+F900 豈", "U+8C48 豈", "豈"), ("U+F901 更", "U+66F4 更", "更"), ("U+F902 車", "U+8ECA 車", "車"),
                                             ("U+F904 滑", "U+6ED1 滑", "滑"), ("U+F90A 金", "U+91D1 金", "金"), ("U+FA11 﨑", "U+5D0E 崎", "﨑"),
                                             ("U+FA15 凞", "U+7199 熙", "凞"), ("U+FA1F 﨟", "U+814B 臘", "﨟"), ("U+FA20 蘒", "U+874E 蝋", "蘒"), ("U+FA22 諸", "U+8AF8 諸", "諸")]):
        cx, cy = 65 + (idx % 2) * 540, 225 + (idx // 2) * 60
        cjk_els.extend([("rect", [(cx, cy), (cx + 520, cy + 50)], (248, 250, 252), (226, 232, 240)), ("t", sb, ch, 28, (cx + 15, cy + 38), (37, 99, 235)),
                        ("t", sb, f"互換字: {cp_s}", 13, (cx + 65, cy + 28)), ("t", sr, f"正規字: {can_s}", 13, (cx + 250, cy + 28), (100, 116, 139))])
    out.append(_render_card(SPECIMENS_DIR / "specimen_cjk_compat.png", 1200, 620, "Holon Sans — CJK 互換漢字拡張検証", sb, cjk_els))

    rep_els = []
    for i, (title, samp) in enumerate([("ASCII & 欧文基本記号", "0123456789 ABCDEFGHIJKLMNOPQRSTUVWXYZ abcdefghijklmnopqrstuvwxyz !\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~"),
                                       ("全角英数・全角記号 (JIS X 0208)", "０１２３４５６７８９ ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ ＋−＝＜＞！＠＃＄％＆＊"),
                                       ("ひらがな・カタカナ・半角カナ", "あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわをん アイウエオ ｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄﾅﾆﾇﾈﾉ"),
                                       ("約物・括弧類・句読点", "「」『』【】〔〕〈〉《》“”…―〜・：；、。！？（）［］｛｝※〒→←↑↓"),
                                       ("多言語（ギリシャ・キリル・通貨記号）", "ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣＴΥΦΧΨΩ αβγδεζηθικλμνξοπρστυφχψω БГДЖЗИЙЛПФЦЧШЩЪЫЬЭЮЯ бгджзийли $ € ¥ £ ₽ ₩ ฿ ¢"),
                                       ("常用漢字・難読・人名用・異体字", "森羅万象 鬱蒼 髑髏 薔薇 檸檬 麒麟 翡翠 躊躇 挨拶 邂逅 魑魅魍魎 葛飾 祇園 茨城 辻堂 鷗外 髙橋 﨑山 諸星 福島")]):
        cy = 115 + i * 135
        rep_els.extend([("rect", [(40, cy), (1360, cy + 115)], (255, 255, 255), (226, 232, 240)), ("t", sb, title, 15, (65, cy + 32), (37, 99, 235)), ("t", sr, samp, 16, (65, cy + 75))])
    out.append(_render_card(SPECIMENS_DIR / "specimen_character_repertoire.png", 1400, 980, "Holon Sans — 包括的文字種別レパートリー検証", sb, rep_els))

    mono_els = [("t", mr, "Half: 550 UPM | Full: 1100 UPM", 16, (1060, 48), (139, 148, 158)),
                ("lines", mr, ["// Rust: Holon Mono は和欧 2:1 等幅なので、インデントや列が完全一致します", "use std::collections::HashMap; pub struct UserProfile {",
                               "    pub user_id:   u64,           // 一意識別子 (64bit integer)", "    pub full_name: String,        // 氏名（全角漢字・仮名対応）",
                               '    pub role_code: &\'static str,  // 権限グループ: "ADMIN" | "USER"', "    pub is_active: bool,          // 有効フラグ: true = 稼働中", "}"], 18, 60, 140, 30, (240, 246, 252)),
                ("lines", mr, ["┌──────┬────────────┬────────────────────────┬────────┬──────────┐", "│ ID   │ 氏名       │ 所属部署・担当領域     │ 権限   │ 状態     │",
                               "├──────┼────────────┼────────────────────────┼────────┼──────────┤", "│ 0101 │ 田中　太郎 │ フロントエンド基盤開発 │ ADMIN  │ 稼働中   │",
                               "│ 0102 │ 鈴木　一郎 │ クラウドインフラ統括   │ ADMIN  │ 稼働中   │", "│ 0103 │ 佐藤　健一 │ 自然言語処理モデル評価 │ MEMBER │ 離席中   │",
                               "│ 0104 │ 高橋　美咲 │ セキュリティ監査・運用 │ MEMBER │ 休暇中   │", "└──────┴────────────┴────────────────────────┴────────┴──────────┘"], 18, 60, 440, 21, (126, 231, 135))]
    out.append(_render_card(SPECIMENS_DIR / "specimen_mono_duospace.png", 1440, 800, "Holon Mono — 2:1 Duospace Programming Specimen", mr, mono_els, dark=True))

    it_els = []
    for i, (title, fp) in enumerate([("Regular (Upright)", mr), ("Italic (Native Latin Italic + 9.0° Slanted CJK)", mi)]):
        cy = 115 + i * 180
        it_els.extend([("rect", [(50, cy), (1390, cy + 36)], (33, 38, 45)), ("t", fp, title, 16, (65, cy + 25), (88, 166, 255)),
                       ("lines", fp, ['const message: &str = "Hello, 世界！"; // 厳密な 2:1 等幅モノスペース', "for item in &dataset { process_record(item); } // レコード処理ルーチン",
                                      "The quick brown fox jumps over the lazy dog. 0123456789"], 20, 65, cy + 55, 38, (240, 246, 252))])
    out.append(_render_card(SPECIMENS_DIR / "specimen_mono_italic.png", 1440, 720, "Holon Mono — Upright vs Italic Comparison", mr, it_els, dark=True))

    mw_els = [("t", mr, f"{wn:<10} ({wv})", 15, (55, 133 + i * 52), (88, 166, 255)) for i, (wn, wv) in enumerate(WEIGHT_VALS.items()) if (fonts_dir / f"HolonMono-{wn}.ttf").exists()]
    for i, (wn, _) in enumerate(WEIGHT_VALS.items()):
        wp = fonts_dir / f"HolonMono-{wn}.ttf"
        if wp.exists():
            mw_els.append(("t", wp, "Sphinx of black quartz, judge my vow. // 銀河鉄道の夜 0123456789", 18, (240, 133 + i * 52), (240, 246, 252)))
    out.append(_render_card(SPECIMENS_DIR / "specimen_mono_weights.png", 1440, 620, "Holon Mono — 8 Weight Family Spectrum", mr, mw_els, dark=True))

    mv_els = [("t", mr, "2-File Architecture (Roman / Italic)", 15, (1100, 48), (139, 148, 158)),
              ("rect", [(50, 110), (1390, 470)], (24, 29, 36), (48, 54, 61)), ("t", mr, "1. Weight 軸（wght: 100 〜 700）無段階連続変化 — 厳密 2:1 幅維持", 16, (75, 135), (88, 166, 255))]
    for i, (wval, lbl) in enumerate([(100, "Thin 100"), (250, "Wght 250"), (400, "Regular 400"), (550, "Wght 550"), (700, "Bold 700")]):
        mv_els.extend([("t", mr, f"{lbl:<12}", 14, (75, 187 + i * 48), (139, 148, 158)), ("t", mv, "fn calc(x: i32) -> i32 { x * 2 } // 厳密な 550/1100 UPM 列位置完全一致", 18, (230, 187 + i * 48), (240, 246, 252), None, {"wght": wval, "GRAD": 0})])
    mv_els.extend([("rect", [(50, 500), (1390, 910)], (24, 29, 36), (48, 54, 61)), ("t", mr, "2. Grade 軸（GRAD: -100 〜 +100）— 送り幅を 1px も変えない線の太さ光学補正", 16, (75, 525), (126, 231, 135)),
                   ("rect", [(75, 560), (700, 880)], (255, 255, 255)), ("t", mr, "ライトモード表示 (GRAD: 0..+100)", 14, (95, 585), (15, 23, 42)),
                   ("t", mv, 'let msg = "Hello, 世界！";', 18, (95, 665), (15, 23, 42), None, {"wght": 400, "GRAD": 0}), ("t", mv, 'let msg = "Hello, 世界！";', 18, (95, 775), (15, 23, 42), None, {"wght": 400, "GRAD": 100}),
                   ("rect", [(740, 560), (1365, 880)], (13, 17, 23)), ("t", mr, "ダークモード光学補正 (GRAD: -100)", 14, (760, 585), (240, 246, 252)),
                   ("t", mv, 'let msg = "Hello, 世界！";', 18, (760, 665), (240, 246, 252), None, {"wght": 400, "GRAD": 0}), ("t", mv, 'let msg = "Hello, 世界！";', 18, (760, 775), (240, 246, 252), None, {"wght": 400, "GRAD": -100})])
    out.append(_render_card(SPECIMENS_DIR / "specimen_mono_variable.png", 1440, 960, "Holon Mono Variable — Weight & Grade Axis Specimen", mr, mv_els, dark=True))

    out.append(_render_card(SPECIMENS_DIR / "specimen_mono_code_programming.png", 1440, 920, "Holon Mono — 実践プログラミングコード・演算子記号組版", mr, [
        ("t", mr, "Rust / TypeScript 2:1 Duospace", 16, (1100, 48), (139, 148, 158)),
        ("rect", [(50, 115), (1390, 151)], (33, 38, 45)), ("t", mr, "Rust: パターンマッチングとエラー処理 (演算子: =>, ->, ::, ?)", 15, (65, 140), (88, 166, 255)),
        ("rect", [(50, 165), (1390, 395)], (13, 17, 23)),
        ("lines", mr, ['match fetch_user_record(&db_pool, user_id).await {', '    Ok(Some(record)) if record.is_active => {',
                       '        let token: String = auth::generate_session(&record)?; // 認証トークン生成', '        println!("[SUCCESS] ユーザー {} がログインしました", record.name);',
                       '        Ok(HttpResponse::Ok().json(token))', '    }', '    _ => Err(AppError::Unauthorized("無効な認証資格情報です")),', '}'], 17, 70, 187, 26, (240, 246, 252)),
        ("rect", [(50, 430), (1390, 466)], (33, 38, 45)), ("t", mr, "TypeScript: ジェネリクスと非同期処理 (演算子: ===, !==, <=, >=, ??, =>)", 15, (65, 455), (88, 166, 255)),
        ("rect", [(50, 480), (1390, 680)], (13, 17, 23)),
        ("lines", mr, ['export async function queryMetrics<T extends DataRecord>(endpoint: string, options?: RequestConfig): Promise<QueryResult<T>> {',
                       '  const res = await fetch(`${API_BASE}/${endpoint}`, { ...options });', '  if (res.status !== 200) throw new HttpError(res.statusText ?? "通信エラー");',
                       '  return await res.json() as QueryResult<T>; // 和欧混植コメント完全整列', '}'], 17, 70, 502, 26, (240, 246, 252)),
    ], dark=True))

    out.append(_render_card(SPECIMENS_DIR / "specimen_mono_terminal_tui.png", 1440, 680, "Holon Mono — ターミナル TUI & システムステータス", mr, [
        ("lines", mr, ["→  holon git:(main) git status (working tree clean)", "→  holon systemctl status holon-duospace", "● holon-duospace.service - Holon Duospace Font Engine (Active: running)"], 18, 50, 115, 28, (240, 246, 252)),
        ("lines", mr, ["┌──────────────────────────────────┬───────────┬───────────────┬────────────────────────┐",
                       "│ サービス名                       │ ステータス│ 応答速度(RTT) │ 稼働ホスト             │",
                       "├──────────────────────────────────┼───────────┼───────────────┼────────────────────────┤",
                       "│ 認証・セッション管理基盤 (OAuth) │ [ 稼働中 ]│ 0.62 ms       │ ap-northeast-1a-prod-1 │",
                       "│ ベクトル検索エンジン (Qdrant)    │ [ 稼働中 ]│ 4.18 ms       │ ap-northeast-1c-prod-4 │",
                       "│ 非同期ジョブキュー (BullMQ)      │ [ 稼働中 ]│ 1.05 ms       │ ap-northeast-1d-prod-2 │",
                       "└──────────────────────────────────┴───────────┴───────────────┴────────────────────────┘"], 18, 50, 240, 21, (126, 231, 135)),
    ], dark=True))

    out.append(_render_card(SPECIMENS_DIR / "specimen_mono_box_drawing_matrix.png", 1440, 620, "Holon Mono — 罫線・ブロック要素全種接続マトリクス", mr, [
        ("lines", mr, ["// 1. 単線・二重線・太線・角丸の組み合わせと交差", "┌─┬─┐ ┏━┳━┓ ╔═╦═╗ ╭─┬─╮ ┌┬┐ ┏┳┓ ╔╦╗ ╭┬╮",
                       "│ │ │ ┃ ┃ ┃ ║ ║ ║ │ │ │ ├┼┤ ┣╋┫ ╠╬╣ ├┼┤", "├─┼─┤ ┣━╋━┫ ╠═╬═╣ ├─┼─┤ └┴┘ ┗┻┛ ╚╩╝ ╰┴╯",
                       "└─┴─┘ ┗━┻━┛ ╚═╩═╝ ╰─┴─╯  ※ すべての角と交差点が 1px の隙間なく連結"], 18, 60, 125, 21, (126, 231, 135)),
        ("lines", mr, ["// 2. ブロック要素（U+2580..U+259F）とプログレスバー", "█ ▀ ▄ ▌ ▐ ░ ▒ ▓   ▂ ▃ ▄ ▅ ▆ ▇ █ ▏ ▎ ▍ ▌ ▋ ▊ ▉ █",
                       "[████████████████████████████████████████████████████████] 100% Complete",
                       "[████████████████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░]  35% Initializing"], 18, 60, 260, 28, (126, 231, 135)),
    ], dark=True))

    out.append(generate_all_glyphs_contact_sheet(sv, SPECIMENS_DIR / "specimen_all_glyphs_sans.png", "Holon Sans — 全グリフコンタクトシート (Complete Repertoire Contact Sheet)"))
    out.append(generate_all_glyphs_contact_sheet(mr, SPECIMENS_DIR / "specimen_all_glyphs_mono.png", "Holon Mono — 全グリフコンタクトシート (Complete Repertoire Contact Sheet)"))
    return out


def test_specimen_generation(fonts_dir: Path, pytestconfig: pytest.Config) -> None:
    if not pytestconfig.getoption("--specimens", default=False):
        pytest.skip("Specimen generation skipped (run with --specimens)")
    paths = generate_all_specimens(fonts_dir)
    assert len(paths) == 16 and all(p.exists() and p.stat().st_size > 10_000 for p in paths)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, *sys.argv[1:]], plugins=[sys.modules[__name__]]))
