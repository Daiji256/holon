# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "fonttools>=4.68.0",
#     "freetype-py>=2.5.1",
#     "pillow>=13.0.0",
#     "pytest>=9.2.0",
#     "uharfbuzz>=0.57.0",
# ]
# ///

from __future__ import annotations

import collections
import hashlib
import itertools
import sys
import unicodedata
import zipfile
from pathlib import Path

import freetype
import pytest
import uharfbuzz as hb
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw

WEIGHTS = [
    "Thin",
    "ExtraLight",
    "Light",
    "Regular",
    "Text",
    "Medium",
    "SemiBold",
    "Bold",
]
WEIGHT_VALS = {
    "Thin": 100,
    "ExtraLight": 200,
    "Light": 300,
    "Regular": 400,
    "Text": 450,
    "Medium": 500,
    "SemiBold": 600,
    "Bold": 700,
}
PANOSE_VALS = {
    "Thin": 2,
    "ExtraLight": 3,
    "Light": 4,
    "Regular": 5,
    "Text": 5,
    "Medium": 6,
    "SemiBold": 7,
    "Bold": 8,
}
UPSTREAM_JP_PATH = Path(
    "tmp/plex/packages/plex-sans-jp/fonts/complete/ttf/unhinted/IBMPlexSansJP-Regular.ttf"
)
SPECIMENS_DIR = Path("specimens")

ALL_EXPECTED = [
    f"{fam}-{('Italic' if it else 'Regular') if w == 'Regular' else f'{w}{it}'}.ttf"
    for fam in ("HolonSans", "HolonMono")
    for w in WEIGHTS
    for it in ("", "Italic")
] + [
    f"{fam}{it}-Variable.otf"
    for fam in ("HolonSans", "HolonMono")
    for it in ("", "-Italic")
]
DESKTOP_FONTS = ALL_EXPECTED
VARIABLE_FONTS = [
    "HolonSans-Variable.otf",
    "HolonSans-Italic-Variable.otf",
    "HolonMono-Variable.otf",
    "HolonMono-Italic-Variable.otf",
]
SANS_REP_FONTS = [
    "HolonSans-Regular.ttf",
    "HolonSans-Italic.ttf",
    "HolonSans-Variable.otf",
    "HolonSans-Italic-Variable.otf",
]
QUADRANT_FONTS = [
    "HolonSans-Regular.ttf",
    "HolonMono-Regular.ttf",
    "HolonSans-Variable.otf",
    "HolonMono-Variable.otf",
]

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


def shape(
    p: Path,
    text: str,
    feat: dict[str, bool] | None = None,
    var: dict[str, float] | None = None,
    vert: bool = False,
    upm: int = 1000,
):
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
    hb.shape(
        font,
        buf,
        feat if feat is not None else ({"vert": True, "vrt2": True} if vert else {}),
    )
    return list(buf.glyph_infos), list(buf.glyph_positions)


def draw_text_hb(
    img: Image.Image,
    p: Path,
    text: str,
    sz: int,
    pos: tuple[int, int],
    feat=None,
    var=None,
    col=(30, 30, 30),
    vert=False,
):
    if not text:
        return pos[1] if vert else pos[0]
    face = freetype.Face(str(p))
    face.set_char_size(sz * 64)
    if var and face.get_variation_info() and face.get_variation_info().axes:
        face.set_var_design_coords(
            [var.get(a.tag.strip(), a.default) for a in face.get_variation_info().axes]
        )
    infos, positions = shape(p, text, feat, var, vert, upm=1000)
    x_cur, y_cur = 0, 0
    for info, pos_i in zip(infos, positions):
        face.load_glyph(
            info.codepoint, freetype.FT_LOAD_RENDER | freetype.FT_LOAD_TARGET_NORMAL
        )
        bm = face.glyph.bitmap
        if bm.width > 0 and bm.rows > 0:
            gx = (
                pos[0]
                + round((x_cur + pos_i.x_offset) * sz / 1000)
                + face.glyph.bitmap_left
            )
            gy = (
                pos[1]
                + round((y_cur - pos_i.y_offset) * sz / 1000)
                - face.glyph.bitmap_top
            )
            img.paste(
                Image.new("RGBA", (bm.width, bm.rows), (*col, 255)),
                (gx, gy),
                Image.frombytes("L", (bm.width, bm.rows), bytes(bm.buffer)),
            )
        x_cur += pos_i.x_advance
        y_cur -= pos_i.y_advance
    return round(y_cur * sz / 1000) if vert else round(x_cur * sz / 1000)


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--fonts-dir",
        action="store",
        default=None,
        help="Directory containing font binaries",
    )
    parser.addoption(
        "--specimens",
        action="store_true",
        default=False,
        help="Generate visual specimen PNG cards",
    )


@pytest.fixture(scope="session")
def fonts_dir(pytestconfig: pytest.Config) -> Path:
    cli_dir = pytestconfig.getoption("--fonts-dir", default=None)
    p = Path(cli_dir) if cli_dir else Path("fonts/full")
    assert p.is_dir(), f"Fonts dir not found: {p}"
    return p


# --- 1. File Completeness, Post 3.0, Compact Metrics & OpenType Metadata ---


def test_font_family_completeness(fonts_dir: Path) -> None:
    missing = [f for f in ALL_EXPECTED if not (fonts_dir / f).exists()]
    assert not missing, (
        f"Missing {len(missing)} expected fonts in {fonts_dir}: {missing[:4]}"
    )
    unexpected_woff = list(fonts_dir.glob("*.woff*"))
    assert not unexpected_woff, (
        f"Unexpected WOFF/WOFF2 files in {fonts_dir}: {unexpected_woff}"
    )


@pytest.mark.parametrize("d_name", DESKTOP_FONTS)
def test_post3_and_compact_metrics(fonts_dir: Path, d_name: str) -> None:
    dp = fonts_dir / d_name
    if not dp.exists():
        pytest.skip(f"{d_name} not built")
    assert dp.stat().st_size > 100_000
    fd = get_tt(dp)
    assert fd["post"].formatType == 3.0
    assert not any(t in fd for t in ("DSIG", "fpgm", "prep", "cvt "))
    # Verify modal advance glyph clustering compacted hmtx and vmtx
    is_mono = "HolonMono" in d_name
    assert fd["hhea"].numberOfHMetrics < (2200 if is_mono else 4500), (
        f"{d_name} hmtx not compacted: {fd['hhea'].numberOfHMetrics}"
    )
    assert (
        fd["vhea"].numberOfVMetrics == 1
        if is_mono
        else fd["vhea"].numberOfVMetrics < 4500
    )


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
            assert "ibm" not in v.lower() and "plex" not in v.lower(), (
                f"Trademark in {d_name} #{rec.nameID}: {v}"
            )

    assert "SIL Open Font License" in names.get(13, "")
    assert "Copyright 2018 IBM Corp. All rights reserved." in names.get(
        0, ""
    ) and "Sandoll" not in names.get(0, "")
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
    w_name = (
        "Regular"
        if is_var
        else next(
            w
            for w in WEIGHTS
            if w in d_name or (w == "Regular" and d_name.endswith("-Italic.ttf"))
        )
    )
    assert (
        os2.achVendID == "HLON"
        and os2.fsType == 0
        and abs(head.fontRevision - 1.0) < 1e-3
    )
    assert (
        os2.usWeightClass == WEIGHT_VALS[w_name]
        and os2.panose.bWeight == PANOSE_VALS[w_name]
    )
    # Strict OpenType OS/2 fsSelection verification: Bit 7 (USE_TYPO_METRICS) & Bit 8 (WWS) always set; Bit 6 (REGULAR) only on Regular upright
    assert (os2.fsSelection & 0x180) == 0x180
    assert bool(os2.fsSelection & 0x40) == (w_name == "Regular" and not is_it)
    assert bool(os2.fsSelection & 0x20) == (w_name == "Bold") and bool(
        head.macStyle & 0x01
    ) == (w_name == "Bold")
    assert bool(os2.fsSelection & 0x01) == is_it and bool(head.macStyle & 0x02) == is_it
    if is_it:
        assert (
            abs(post.italicAngle - (-9.0 if "HolonMono" in d_name else -11.0)) < 0.1
            and hhea.caretSlopeRun > 0
        )
    else:
        assert post.italicAngle == 0.0 and hhea.caretSlopeRun == 0

    if not is_var:
        base_fam = "Holon Sans" if "HolonSans" in d_name else "Holon Mono"
        if w_name in ("Regular", "Bold"):
            assert names[1] == base_fam and names[2] == (
                "Bold Italic"
                if (w_name == "Bold" and is_it)
                else ("Italic" if is_it else w_name)
            )
        else:
            assert names[1] == f"{base_fam} {w_name}" and names[2] == (
                "Italic" if is_it else "Regular"
            )
            assert (
                names.get(16) == base_fam
                and names.get(17) == f"{w_name}{' Italic' if is_it else ''}"
            )


def test_unique_identifiers_and_family_metrics(fonts_dir: Path) -> None:
    files = sorted(fonts_dir.glob("*.ttf")) + sorted(fonts_dir.glob("*.otf"))
    if not files:
        pytest.skip("No fonts found")
    seen_ps, seen_uid, by_fam = {}, {}, collections.defaultdict(dict)
    for p in files:
        font = get_tt(p)
        names = {
            r.nameID: r.toUnicode() for r in font["name"].names if r.platformID == 3
        }
        ps, uid = names.get(6, ""), names.get(3, "")
        assert ps and ps not in seen_ps and uid and uid not in seen_uid
        seen_ps[ps] = seen_uid[uid] = p.name
        fam = "HolonMono" if "HolonMono" in p.name else "HolonSans"
        os2, hhea = font["OS/2"], font["hhea"]
        by_fam[fam][p.name] = (
            hhea.ascent,
            hhea.descent,
            hhea.lineGap,
            os2.sTypoAscender,
            os2.sTypoDescender,
            os2.sTypoLineGap,
        )
    for fam, fmap in by_fam.items():
        ref_m = next(iter(fmap.values()))
        assert all(m == ref_m for m in fmap.values()), (
            f"{fam} vertical metrics mismatch"
        )


def _verify_ofl_bytes(content: bytes) -> None:
    prefix = b"Copyright 2026 Daiji Suzuki.\r\n"
    assert content.startswith(prefix)
    upstream_part = content.removeprefix(prefix)
    assert b"SIL OPEN FONT LICENSE Version 1.1" in upstream_part
    assert (
        hashlib.sha256(upstream_part).hexdigest()
        == "7e6b2818edbd8f6a01ae80641cc8f16a51080d08fb4e532be3a0b6f74adb07da"
    )


def test_ofl_license_text(fonts_dir: Path) -> None:
    assert not Path("OFL.txt").exists(), (
        "Root OFL.txt should not exist; include OFL.txt only in generated artifacts"
    )
    ofl_p = fonts_dir / "OFL.txt"
    assert ofl_p.exists(), f"{ofl_p} must exist in generated font directory"
    content = ofl_p.read_bytes()
    _verify_ofl_bytes(content)

    subset_dir = Path("fonts/subset")
    if subset_dir.is_dir() and any(subset_dir.glob("*.ttf")):
        subset_ofl = subset_dir / "OFL.txt"
        assert subset_ofl.exists(), f"{subset_ofl} must exist in subset font directory"
        assert subset_ofl.read_bytes() == content


def test_release_archives(fonts_dir: Path) -> None:
    dist_dir = Path("dist")
    if not dist_dir.is_dir():
        pytest.skip("dist/ not built (run build.py --package or --package-only)")
    zips = sorted(dist_dir.glob("Holon*.zip"))
    if not zips:
        pytest.skip("No release ZIP archives in dist/")

    expected_ofl = (fonts_dir / "OFL.txt").read_bytes()
    _verify_ofl_bytes(expected_ofl)

    expected_groups = {
        f"{fam}-{kind}{sub}": [
            f for f in ALL_EXPECTED if f.startswith(fam) and f.endswith(ext)
        ]
        for fam in ("HolonSans", "HolonMono")
        for kind, ext in (("Static", ".ttf"), ("Variable", ".otf"))
        for sub in ("", "-Subset")
    }

    matched_keys: set[str] = set()
    for zp in zips:
        stem = zp.stem
        group_key = next(
            (
                k
                for k in sorted(expected_groups, key=len, reverse=True)
                if stem == k or stem.startswith(f"{k}-")
            ),
            None,
        )
        assert group_key is not None, f"Unexpected release ZIP name: {zp.name}"
        matched_keys.add(group_key)

        with zipfile.ZipFile(zp, "r") as zf:
            names = set(zf.namelist())
            expected_entries = {f"{stem}/OFL.txt"} | {
                f"{stem}/{fname}" for fname in expected_groups[group_key]
            }
            assert names == expected_entries, (
                f"Unexpected archive entries in {zp}: "
                f"missing={expected_entries - names}, extra={names - expected_entries}"
            )
            assert zf.read(f"{stem}/OFL.txt") == expected_ofl

    if Path("fonts/subset").is_dir() and any(Path("fonts/subset").glob("*.ttf")):
        assert matched_keys == set(expected_groups), (
            f"Missing expected release ZIP groups: {set(expected_groups) - matched_keys}"
        )


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
        for cp in JIS_X_0208_CPS | set(range(0x20, 0x180)) | set(range(0x3040, 0x3100)):
            if cp in cmap and glyf[cmap[cp]].numberOfContours > 0:
                g = glyf[cmap[cp]]
                assert g.yMax <= os2.usWinAscent and g.yMin >= -os2.usWinDescent, (
                    f"{d_name} U+{cp:04X} clipped"
                )


@pytest.mark.parametrize(
    "font_name", ["HolonSans-Regular.ttf", "HolonMono-Regular.ttf"]
)
def test_cmap_outlines_and_jis_x_0208_coverage(fonts_dir: Path, font_name: str) -> None:
    p = fonts_dir / font_name
    if not p.exists():
        pytest.skip(f"{font_name} not built")
    font = get_tt(p)
    cmap, glyf = font.getBestCmap(), font["glyf"]
    empty = [
        f"U+{cp:04X}"
        for cp, g in cmap.items()
        if cp < 0x110000
        and unicodedata.category(chr(cp)) not in ("Zs", "Zl", "Zp", "Cc", "Cf")
        and cp not in (0x20, 0xA0, 0x3000)
        and glyf[g].numberOfContours == 0
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
        1
        for code in range(0xF900, 0xFB00)
        if len(d := unicodedata.normalize("NFKD", chr(code))) == 1
        and ord(d) in cmap
        and code in cmap
    )
    assert (
        present >= 456 and cmap[0xFA11] != cmap[0x5D0E] and cmap[0xF900] == cmap[0x8C48]
    )


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
    assert not [
        (g, w) for g, (w, _) in font["hmtx"].metrics.items() if w not in (0, 550, 1100)
    ]
    assert not [(g, h) for g, (h, _) in font["vmtx"].metrics.items() if h != 1100]
    assert "GPOS" not in font and "BASE" not in font and font["post"].isFixedPitch == 1
    os2 = font["OS/2"]
    assert (
        os2.sTypoAscender,
        os2.sTypoDescender,
        os2.sTypoLineGap,
        os2.panose.bProportion,
    ) == (950, -225, 0, 9)
    for s, cells in [
        ("//", 2),
        ("AV", 2),
        ("fi", 2),
        ("0123456789", 10),
        ("ｶﾀｶﾅ", 4),
        ("日本語", 6),
        ("Hello, 世界！", 13),
    ]:
        assert sum(pos.x_advance for pos in shape(p, s)[1]) == cells * 550
    assert (
        shape(p, "0", feat={"zero": False})[0][0].codepoint
        != shape(p, "0", feat={"zero": True})[0][0].codepoint
    )
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
            diffs = [
                f"U+{u:04X}"
                for u, g in cmap.items()
                if u in ref_cmap and hmtx[g][0] != ref_hmtx[ref_cmap[u]][0]
            ]
            assert not diffs, f"{name} width mismatch vs Regular: {diffs[:5]}"

    for vname in ("HolonMono-Variable.otf", "HolonMono-Italic-Variable.otf"):
        vp = fonts_dir / vname
        if not vp.exists():
            continue
        vf = get_tt(vp)
        for tag in ("HVAR", "VVAR"):
            for vd in vf[tag].table.VarStore.VarData:
                assert not [it for it in vd.Item if any(it)], (
                    f"{vname} {tag} has non-zero advance deltas"
                )


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
        for cp, g in cmap.items()
        if cp < 0x110000
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
    heights = [
        glyf[cmap[cp]].yMax - glyf[cmap[cp]].yMin for cp in range(0x2581, 0x2589)
    ]
    assert all(glyf[cmap[cp]].yMin == -225 for cp in range(0x2581, 0x2589))
    assert all(h2 > h1 > 0 for h1, h2 in itertools.pairwise(heights)), (
        f"Non-increasing heights: {heights}"
    )


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
    for text, exp in [
        ("「『", -500),
        ("』。", -500),
        ("・：；", -1000),
        ("「・」", -500),
        ("。　", -500),
        ("： 東京", -500),
    ]:
        assert (
            sum(pos.x_advance for pos in shape(p, text, feat={"chws": True})[1])
            - sum(pos.x_advance for pos in shape(p, text, feat={"chws": False})[1])
            == exp
        )
    for text in ("あ「", "」あ", "。あ", "「", "」", "（", "）", "あ、", "か。"):
        assert sum(
            pos.x_advance for pos in shape(p, text, feat={"chws": True})[1]
        ) == sum(pos.x_advance for pos in shape(p, text, feat={"chws": False})[1])
    for text, exp in [
        ("「『", -500),
        ("』。", -500),
        ("・：；", -1000),
        ("「・」", -500),
        ("。　", -500),
        ("： A", -500),
    ]:
        assert (
            sum(
                -pos.y_advance
                for pos in shape(p, text, feat={"vert": True, "vchw": True}, vert=True)[
                    1
                ]
            )
            - sum(
                -pos.y_advance
                for pos in shape(
                    p, text, feat={"vert": True, "vchw": False}, vert=True
                )[1]
            )
            == exp
        )


@pytest.mark.parametrize(
    "fname",
    [
        "HolonSans-Regular.ttf",
        "HolonSans-Italic.ttf",
        "HolonSans-Variable.otf",
        "HolonMono-Regular.ttf",
        "HolonMono-Variable.otf",
    ],
)
def test_vertical_writing_substitutions_and_metrics(
    fonts_dir: Path, fname: str
) -> None:
    """Verify vert/vrt2 glyph substitutions for yakumono, brackets, and small kana, plus vhea/vmtx/VORG."""
    p = fonts_dir / fname
    if not p.exists():
        pytest.skip(f"{fname} not built")
    vert_chars = "、。「」『』（）【】〔〕〈〉《》［］｛｝ー〜―…‥：；ぁぃぅぇぉっゃゅょァィゥェォッャュョ"
    for ch in vert_chars:
        gid_h = shape(p, ch, vert=False)[0][0].codepoint
        gid_v = shape(p, ch, vert=True)[0][0].codepoint
        assert gid_h != gid_v, (
            f"{fname} missing vertical substitution for '{ch}' (U+{ord(ch):04X})"
        )

    font = get_tt(p)
    assert "vhea" in font and "vmtx" in font
    assert font["vhea"].ascent == 500 and font["vhea"].descent == -500
    if fname.endswith(".otf"):
        assert "VORG" in font and font["VORG"].defaultVertOriginY == 880
    full_w = 1100 if "Mono" in fname else 1000
    cmap, hmtx, vmtx = font.getBestCmap(), font["hmtx"].metrics, font["vmtx"].metrics
    for u in (0x3000,) if "Mono" in fname else (0x2015, 0x2025, 0x2026, 0x2103, 0x3000):
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
    assert {"chws", "vchw", "halt", "vhal", "kern", "palt", "vkrn", "vpal"}.issubset(
        gpos_feats
    )
    if UPSTREAM_JP_PATH.exists():
        up_gsub = {
            r.FeatureTag
            for r in get_tt(UPSTREAM_JP_PATH)["GSUB"].table.FeatureList.FeatureRecord
        }
        assert up_gsub.issubset(
            {r.FeatureTag for r in font["GSUB"].table.FeatureList.FeatureRecord}
        )

    # Active shaping verification for kern, palt, vpal, and fwid
    assert sum(pos.x_advance for pos in shape(p, "AV", feat={"kern": True})[1]) < sum(
        pos.x_advance for pos in shape(p, "AV", feat={"kern": False})[1]
    )
    assert sum(
        pos.x_advance for pos in shape(p, "「あ」", feat={"palt": True})[1]
    ) < sum(pos.x_advance for pos in shape(p, "「あ」", feat={"palt": False})[1])
    assert sum(
        -pos.y_advance
        for pos in shape(p, "「あ」", feat={"vert": True, "vpal": True}, vert=True)[1]
    ) < sum(
        -pos.y_advance
        for pos in shape(p, "「あ」", feat={"vert": True, "vpal": False}, vert=True)[1]
    )
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
    axes = {
        a.axisTag: (a.minValue, a.defaultValue, a.maxValue) for a in vf["fvar"].axes
    }
    assert axes["wght"] == (100.0, 400.0, 700.0) and axes["GRAD"] == (
        -100.0,
        0.0,
        100.0,
    )
    assert len(vf["avar"].segments["wght"]) >= 7
    assert [a.AxisTag for a in vf["STAT"].table.DesignAxisRecord.Axis] == [
        "wght",
        "GRAD",
        "ital",
    ]
    insts = {
        vf["name"].getDebugName(i.subfamilyNameID): i.coordinates["wght"]
        for i in vf["fvar"].instances
    }
    for wn, wv in WEIGHT_VALS.items():
        matched = [
            c
            for name, c in insts.items()
            if name in (wn, f"{wn} Italic", "Italic" if wn == "Regular" else "")
        ]
        assert matched and abs(matched[0] - float(wv)) < 1.0


def test_static_stat_single_axis_value(fonts_dir: Path) -> None:
    """Verify static fonts only declare their own weight in STAT table (single wght AxisValue) to prevent Windows misidentification."""
    checked = 0
    for fname, exp_w in [
        ("HolonSans-Regular.ttf", 400.0),
        ("HolonSans-Bold.ttf", 700.0),
    ]:
        p = fonts_dir / fname
        if not p.exists():
            continue
        font = get_tt(p)
        stat = font["STAT"].table
        assert stat.DesignAxisCount == 2
        axis_values = stat.AxisValueArray.AxisValue
        wght_values = [v for v in axis_values if v.AxisIndex == 0]
        assert len(wght_values) == 1, (
            f"{fname} must have exactly one STAT entry for 'wght', got {len(wght_values)}"
        )
        assert wght_values[0].Value == exp_w
        checked += 1
    assert checked > 0


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
        if not (advs[0] == advs[1] == advs[2]) or (
            is_mono and advs[1] not in (0, 550, 1100)
        ):
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
        assert inks[0] <= inks[1] <= inks[2] and inks[2] > inks[0], (
            f"{vname} '{ch}' ink not scaling with GRAD: {inks}"
        )


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
            (
                hex(cp),
                font_s.get_glyph_h_advance(fs.getGlyphID(cmap_s[cp])),
                font_v.get_glyph_h_advance(fv.getGlyphID(cmap_v[cp])),
            )
            for cp in set(cmap_s).intersection(cmap_v)
            if abs(
                font_s.get_glyph_h_advance(fs.getGlyphID(cmap_s[cp]))
                - font_v.get_glyph_h_advance(fv.getGlyphID(cmap_v[cp]))
            )
            > tol
        ]
        assert not viol, (
            f"{s_name} vs {v_name} advance mismatch ({len(viol)} chars): {viol[:5]}"
        )


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
        assert inks[-1] >= 1.8 * inks[0], (
            f"{vname} '{ch}' insufficient weight expansion: {inks[0]} -> {inks[-1]}"
        )

    if "Mono" in vname:
        for light_ch, heavy_ch in (("│", "┃"), ("┼", "╋")):
            face.set_var_design_coords([400, 0])
            face.load_char(
                light_ch, freetype.FT_LOAD_RENDER | freetype.FT_LOAD_TARGET_NORMAL
            )
            ink_l = sum(face.glyph.bitmap.buffer)
            face.load_char(
                heavy_ch, freetype.FT_LOAD_RENDER | freetype.FT_LOAD_TARGET_NORMAL
            )
            ink_h = sum(face.glyph.bitmap.buffer)
            assert ink_h >= 1.7 * ink_l


# --- 6. Declarative Visual Specimen Engine ---


def create_specimen_canvas(
    w: int, h: int, title: str, subtitle: str, f_title: Path, f_sub: Path
) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGBA", (w, h), (255, 255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw_text_hb(img, f_title, title, 22, (48, 48), col=(17, 24, 39))
    draw_text_hb(img, f_sub, subtitle, 13, (48, 72), col=(107, 114, 128))
    draw.line([(48, 88), (w - 48, 88)], fill=(229, 231, 235), width=1)
    return img, draw


def save_specimen(img: Image.Image, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        with Image.open(out_path) as existing:
            if (
                existing.size == img.size
                and existing.convert(img.mode).tobytes() == img.tobytes()
            ):
                return out_path
    img.save(out_path)
    return out_path


def render_sans_weights(fonts_dir: Path, out_path: Path) -> Path:
    sr = fonts_dir / "HolonSans-Regular.ttf"
    sb = fonts_dir / "HolonSans-Bold.ttf"
    img, draw = create_specimen_canvas(
        1300,
        880,
        "Holon Sans — Weights & Styles",
        "8 static weights (100–700) × Upright / Italic (11.0° Oblique CJK + True Latin Italic)",
        sb,
        sr,
    )
    sample_text = "Sphinx of black quartz, judge my vow. 0123456789 美しい調和と組版"
    y = 118
    for wn in WEIGHTS:
        wval = WEIGHT_VALS[wn]
        f_up = fonts_dir / f"HolonSans-{wn}.ttf"
        it_name = (
            "HolonSans-Italic.ttf" if wn == "Regular" else f"HolonSans-{wn}Italic.ttf"
        )
        f_it = fonts_dir / it_name
        if not (f_up.exists() and f_it.exists()):
            continue
        draw_text_hb(
            img,
            sb if wval >= 500 else sr,
            f"{wn:<10} {wval}",
            13,
            (48, y + 4),
            col=(107, 114, 128),
        )
        draw_text_hb(img, f_up, sample_text, 16, (200, y + 4), col=(17, 24, 39))
        draw_text_hb(
            img,
            sb if wval >= 500 else sr,
            f"{wn:<10} Italic",
            13,
            (48, y + 32),
            col=(156, 163, 175),
        )
        draw_text_hb(img, f_it, sample_text, 16, (200, y + 32), col=(31, 41, 55))
        y += 66
        if wn != WEIGHTS[-1]:
            draw.line([(48, y - 10), (1252, y - 10)], fill=(243, 244, 246), width=1)
            y += 18
    return save_specimen(img, out_path)


def render_sans_chws(fonts_dir: Path, out_path: Path) -> Path:
    sr = fonts_dir / "HolonSans-Regular.ttf"
    sb = fonts_dir / "HolonSans-Bold.ttf"
    img, draw = create_specimen_canvas(
        1300,
        840,
        "Holon Sans — Contextual Half-width Spacing (chws)",
        "JIS X 4051 contextual spacing for Japanese punctuation: OFF (unadjusted) vs ON (half-width spacing)",
        sb,
        sr,
    )
    samples = [
        (
            "1. 連続開き括弧・閉じ括弧と句点 (Consecutive brackets & punctuation)",
            "「「連続開き括弧」」。 (閉じ括弧と句点の二分ツメ)",
        ),
        (
            "2. 中点類相互の二分ツメ (・: ; ) (Consecutive middle dots / colons)",
            "中点連続：・・；；および・・・・ (中点類の自動二分ツメ)",
        ),
        (
            "3. 括弧と中点類の空き調整 (Brackets with middle dots / colons)",
            "括弧と中点：「・」「：」「；」 項目：「東京」「京都」",
        ),
        (
            "4. 句点＋全角空白のアキ量調整 (Period followed by full-width space)",
            "東京都。　次の段落 (句点余白＋全角空白のアキ量確認)",
        ),
        (
            "5. 和欧・約物混植 (Mixed Japanese and Western typography)",
            "「Holon Sans」: Ver 1.0 (2026) —— 『約物半角ツメ検証』。",
        ),
    ]
    y = 120
    for title, text in samples:
        draw_text_hb(img, sb, title, 13, (48, y), col=(55, 65, 81))
        y += 30
        draw_text_hb(img, sr, "[chws OFF]", 12, (48, y + 2), col=(156, 163, 175))
        adv_off = draw_text_hb(
            img, sr, text, 18, (140, y + 2), feat={"chws": False}, col=(55, 65, 81)
        )
        y += 34
        draw_text_hb(img, sb, "[chws ON ]", 12, (48, y + 2), col=(37, 99, 235))
        adv_on = draw_text_hb(
            img, sr, text, 18, (140, y + 2), feat={"chws": True}, col=(17, 24, 39)
        )
        x_off = 140 + adv_off
        x_on = 140 + adv_on
        draw.line([(x_off, y - 32), (x_off, y + 18)], fill=(220, 38, 38), width=1)
        draw.line([(x_on, y - 4), (x_on, y + 18)], fill=(37, 99, 235), width=1)
        draw.line([(x_on, y + 18), (x_off, y + 18)], fill=(220, 38, 38), width=1)
        y += 40
        if title != samples[-1][0]:
            draw.line([(48, y - 12), (1252, y - 12)], fill=(243, 244, 246), width=1)
            y += 10
    return save_specimen(img, out_path)


def render_sans_vertical(fonts_dir: Path, out_path: Path) -> Path:
    sr = fonts_dir / "HolonSans-Regular.ttf"
    sb = fonts_dir / "HolonSans-Bold.ttf"
    img, draw = create_specimen_canvas(
        1300,
        840,
        "Holon Sans — Vertical Layout (vert, vrt2 & vchw)",
        "Vertical glyph substitution (vert / vrt2) and vertical contextual spacing (vchw)",
        sb,
        sr,
    )
    cols = [
        (
            "1. 句読点・長音",
            "縦書き置換：句読点（、。）長音符（ー）波線（〜）ダッシュ（——）",
            1200,
            1150,
        ),
        (
            "2. 各種括弧類",
            "「開き括弧」『二重括弧』（丸括弧）［大括弧］【隅付き括弧】",
            1080,
            1045,
        ),
        (
            "3. セミコロン回転",
            "項目１：：定義；；項目２：：検証；；項目３：：結び。・・；；",
            960,
            915,
        ),
        ("4. 和欧混植", "Holon Sans 2026年 縦書きテキストと約物の調和。", 840, 810),
    ]
    for label, text, tx, hx in cols:
        draw_text_hb(img, sb, label, 12, (hx, 120), col=(55, 65, 81))
        draw_text_hb(img, sr, text, 18, (tx, 160), vert=True, col=(17, 24, 39))

    # Section 5: vchw
    draw_text_hb(img, sb, "5. 縦約物ツメ (vchw)", 12, (620, 120), col=(55, 65, 81))
    vchw_test = "「『（［連続約物］）） 』」。・・「・」"
    draw_text_hb(img, sr, "[vchw OFF]", 11, (710, 150), col=(156, 163, 175))
    adv_off = draw_text_hb(
        img,
        sr,
        vchw_test,
        18,
        (710, 180),
        feat={"vert": True, "vrt2": True, "vchw": False},
        vert=True,
        col=(55, 65, 81),
    )
    draw_text_hb(img, sb, "[vchw ON ]", 11, (620, 150), col=(37, 99, 235))
    adv_on = draw_text_hb(
        img,
        sr,
        vchw_test,
        18,
        (620, 180),
        feat={"vert": True, "vrt2": True, "vchw": True},
        vert=True,
        col=(17, 24, 39),
    )

    y_off = 180 + adv_off
    y_on = 180 + adv_on
    draw.line([(590, y_on), (645, y_on)], fill=(37, 99, 235), width=1)
    draw.line([(590, y_off), (735, y_off)], fill=(220, 38, 38), width=1)

    sep_x = 540
    draw.line([(sep_x, 120), (sep_x, 780)], fill=(229, 231, 235), width=1)

    # Section 6: Literature passage
    draw_text_hb(img, sb, "6. 文学組版サンプル", 12, (410, 120), col=(55, 65, 81))
    lines_lit = [
        "吾輩は猫である。名前はまだ無い。",
        "どこで生れたかとんと見当がつかぬ。",
        "何でも薄暗いじめじめした所で",
        "ニャーニャー泣いていた事だけは記憶している。",
    ]
    lx = 420
    for line in lines_lit:
        draw_text_hb(img, sr, line, 18, (lx, 160), vert=True, col=(17, 24, 39))
        lx -= 75

    return save_specimen(img, out_path)


def render_sans_variable(fonts_dir: Path, out_path: Path) -> Path:
    sr = fonts_dir / "HolonSans-Regular.ttf"
    sb = fonts_dir / "HolonSans-Bold.ttf"
    sv = fonts_dir / "HolonSans-Variable.otf"
    img, draw = create_specimen_canvas(
        1300,
        1160,
        "Holon Sans — Variable Font Axes (wght & GRAD)",
        "Fine-grained weight interpolation (50 & 25 intervals) and layout-preserving optical grade adjustment",
        sb,
        sr,
    )

    # Section 1: 50-interval weight spectrum across full range (100..700)
    draw_text_hb(
        img,
        sb,
        "1. Full Range Weight Spectrum (wght: 100..700 in 50-unit intervals)",
        13,
        (48, 120),
        col=(55, 65, 81),
    )
    steps_50 = [100, 150, 200, 250, 300, 350, 400, 450, 500, 550, 600, 650, 700]
    y = 150
    for wval in steps_50:
        is_major = wval % 100 == 0
        lbl_col = (17, 24, 39) if is_major else (156, 163, 175)
        txt_col = (17, 24, 39)
        draw_text_hb(
            img, sb if is_major else sr, f"wght {wval:>3}", 12, (48, y + 2), col=lbl_col
        )
        draw_text_hb(
            img,
            sv,
            "a w x v y f g 0 8 あ 森 鬱   Sphinx of black quartz, judge my vow.",
            16,
            (170, y + 2),
            var={"wght": wval, "GRAD": 0},
            col=txt_col,
        )
        y += 27

    draw.line([(48, y + 8), (1252, y + 8)], fill=(229, 231, 235), width=1)
    y += 28

    # Section 2: Fine 25-interval tuning in core reading weight range (350..500)
    draw_text_hb(
        img,
        sb,
        "2. Fine-grained Weight Tuning (wght: 350..500 in 25-unit intervals)",
        13,
        (48, y),
        col=(55, 65, 81),
    )
    steps_25 = [350, 375, 400, 425, 450, 475, 500]
    y += 26
    for wval in steps_25:
        is_std = wval in (400, 500)
        lbl_col = (37, 99, 235) if is_std else (107, 114, 128)
        draw_text_hb(
            img, sb if is_std else sr, f"wght {wval:>3}", 12, (48, y + 2), col=lbl_col
        )
        draw_text_hb(
            img,
            sv,
            "微細ウェイト調整: 和欧の黒みと視覚的階調を25単位で制御 (Holon Sans 2026)",
            17,
            (170, y + 2),
            var={"wght": wval, "GRAD": 0},
            col=(17, 24, 39),
        )
        y += 30

    draw.line([(48, y + 8), (1252, y + 8)], fill=(229, 231, 235), width=1)
    y += 28

    # Section 3: Grade Axis (GRAD: -100..+100) with advance width invariance
    draw_text_hb(
        img,
        sb,
        "3. Grade Axis (GRAD: -100..+100) — Advance Width Invariance",
        13,
        (48, y),
        col=(55, 65, 81),
    )
    grad_text = "The quick brown fox jumps over the lazy dog. 視覚的バランス 012345"

    grad_steps = [-100, -50, 0, 50, 100]
    y += 28
    y_start_grad = y
    adv_grad = 0
    for gval in grad_steps:
        sign_str = f"{gval:+4}" if gval != 0 else "   0"
        is_default = gval == 0
        lbl_col = (
            (37, 99, 235)
            if is_default
            else ((17, 24, 39) if abs(gval) == 100 else (107, 114, 128))
        )
        draw_text_hb(
            img,
            sb if is_default else sr,
            f"[GRAD: {sign_str}]",
            12,
            (48, y + 2),
            col=lbl_col,
        )
        adv = draw_text_hb(
            img,
            sv,
            grad_text,
            17,
            (170, y + 2),
            var={"wght": 400, "GRAD": gval},
            col=(17, 24, 39),
        )
        if not adv_grad:
            adv_grad = adv
        y += 30

    # Red alignment guidelines across all 5 GRAD values (-100..+100)
    x_start = 170
    x_end = 170 + adv_grad
    draw.line(
        [(x_start, y_start_grad - 4), (x_start, y - 4)], fill=(220, 38, 38), width=1
    )
    draw.line([(x_end, y_start_grad - 4), (x_end, y - 4)], fill=(220, 38, 38), width=1)

    # Dark background box for halation test
    y += 25
    draw.rectangle([(48, y), (1252, y + 130)], fill=(17, 24, 39))
    draw_text_hb(
        img,
        sr,
        "// Dark Mode Halation Optical Compensation (GRAD: -50, -100)",
        12,
        (72, y + 20),
        col=(156, 163, 175),
    )
    dark_text = "Dark mode halation test: 白文字の光の膨張（ハレーション）抑制と可読性維持 012345"
    draw_text_hb(img, sr, "[GRAD:    0]", 12, (72, y + 48), col=(156, 163, 175))
    draw_text_hb(
        img,
        sv,
        dark_text,
        15,
        (190, y + 48),
        var={"wght": 400, "GRAD": 0},
        col=(243, 244, 246),
    )
    draw_text_hb(img, sb, "[GRAD:  -50]", 12, (72, y + 74), col=(147, 197, 253))
    draw_text_hb(
        img,
        sv,
        dark_text,
        15,
        (190, y + 74),
        var={"wght": 400, "GRAD": -50},
        col=(243, 244, 246),
    )
    draw_text_hb(img, sb, "[GRAD: -100]", 12, (72, y + 100), col=(96, 165, 250))
    draw_text_hb(
        img,
        sv,
        dark_text,
        15,
        (190, y + 100),
        var={"wght": 400, "GRAD": -100},
        col=(243, 244, 246),
    )

    return save_specimen(img, out_path)


def render_sans_features(fonts_dir: Path, out_path: Path) -> Path:
    sr = fonts_dir / "HolonSans-Regular.ttf"
    sb = fonts_dir / "HolonSans-Bold.ttf"
    img, draw = create_specimen_canvas(
        1300,
        840,
        "Holon Sans — OpenType Features & Extended Repertoire",
        "CJK compatibility kanji mappings, dotted zero (zero), and extended repertoire",
        sb,
        sr,
    )

    # Section 1: CJK Compatibility Kanji
    draw_text_hb(
        img,
        sb,
        "1. CJK Compatibility Kanji Mappings (U+F900..U+FAFF) — No Missing Glyphs",
        13,
        (48, 120),
        col=(55, 65, 81),
    )
    compat_samples = [
        ("﨑", "U+FA11\ncf. 崎 (U+5D0E)"),
        ("凞", "U+FA15\ncf. 凞 (U+51DE)"),
        ("﨟", "U+FA1F\ncf. 臈 (U+81C8)"),
        ("蘒", "U+FA20\ncf. 蘒 (U+8612)"),
        ("諸", "U+FA22\ncf. 諸 (U+8AF8)"),
        ("豈", "U+F900\n→ 豈 (U+8C48)"),
        ("更", "U+F901\n→ 更 (U+66F4)"),
        ("車", "U+F902\n→ 車 (U+8ECA)"),
        ("滑", "U+F904\n→ 滑 (U+6ED1)"),
        ("金", "U+F90A\n→ 金 (U+91D1)"),
    ]
    cx = 48
    cy = 160
    for idx, (ch, desc) in enumerate(compat_samples):
        draw_text_hb(img, sb, ch, 28, (cx, cy), col=(17, 24, 39))
        lines = desc.split("\n")
        draw_text_hb(img, sb, lines[0], 11, (cx + 44, cy + 2), col=(17, 24, 39))
        draw_text_hb(img, sr, lines[1], 10, (cx + 44, cy + 18), col=(107, 114, 128))
        cx += 245
        if (idx + 1) % 5 == 0:
            cx = 48
            cy += 70

    draw.line([(48, 305), (1252, 305)], fill=(229, 231, 235), width=1)

    # Section 2: Dotted / Slashed zero
    draw_text_hb(
        img,
        sb,
        "2. Slashed / Dotted Zero (zero feature) — Numeric Disambiguation",
        13,
        (48, 330),
        col=(55, 65, 81),
    )
    z_text = "0123456789 0 vs O (Capital Oh) 00:00 $0.00"
    draw_text_hb(img, sr, "[zero OFF]", 12, (48, 370), col=(156, 163, 175))
    draw_text_hb(
        img, sr, z_text, 22, (180, 370), feat={"zero": False}, col=(55, 65, 81)
    )
    draw_text_hb(img, sb, "[zero ON ]", 12, (48, 415), col=(37, 99, 235))
    draw_text_hb(img, sr, z_text, 22, (180, 415), feat={"zero": True}, col=(17, 24, 39))

    draw.line([(48, 465), (1252, 465)], fill=(229, 231, 235), width=1)

    # Section 3: Extended Repertoire
    draw_text_hb(
        img, sb, "3. Extended Repertoire & Symbols", 13, (48, 490), col=(55, 65, 81)
    )
    rep_items = [
        (
            "Currencies",
            "$ 628,000  € 450,000  ¥ 1,280,000  £ 380,000  ₽ 500,000  ₴ 240,000  ₩ 890,000",
        ),
        (
            "Diacritics",
            "Ångström, café, naïve, façade, Zürich, Łódź, São Paulo, Đà Nẵng, Miloš, Gödel",
        ),
        (
            "Cyrillic",
            "Съешь же ещё этих мягких французских булок, да выпей чаю. (Привет, мир!)",
        ),
        ("Greek", "ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ  αβγδεζηθικλμνξοπρστυφχψω"),
        (
            "Punctuation",
            "「」『』【】〔〕〈〉《》“”…―〜・：；、。！？（）［］｛｝※〒→←↑↓",
        ),
        (
            "Kanji",
            "森羅万象 鬱蒼 髑髏 薔薇 檸檬 麒麟 翡翠 躊躇 挨拶 邂逅 魑魅魍魎 葛飾 祇園 茨城 辻堂 鷗外 髙橋",
        ),
    ]
    ry = 525
    for label, samp in rep_items:
        draw_text_hb(img, sb, label, 12, (48, ry + 4), col=(107, 114, 128))
        draw_text_hb(img, sr, samp, 16, (180, ry + 4), col=(17, 24, 39))
        ry += 42

    return save_specimen(img, out_path)


def render_mono_weights(fonts_dir: Path, out_path: Path) -> Path:
    mr = fonts_dir / "HolonMono-Regular.ttf"
    mb = fonts_dir / "HolonMono-Bold.ttf"
    img, draw = create_specimen_canvas(
        1300,
        880,
        "Holon Mono — Weights & Styles",
        "8 static weights (100–700) × Upright / Italic (9.0° Oblique CJK + True Latin Italic)",
        mb,
        mr,
    )
    sample_text = (
        "pub fn calculate(rate: f64) -> Result<u64, Error> { // 2:1 等幅 0123456789 }"
    )
    y = 118
    for wn in WEIGHTS:
        wval = WEIGHT_VALS[wn]
        f_up = fonts_dir / f"HolonMono-{wn}.ttf"
        it_name = (
            "HolonMono-Italic.ttf" if wn == "Regular" else f"HolonMono-{wn}Italic.ttf"
        )
        f_it = fonts_dir / it_name
        if not (f_up.exists() and f_it.exists()):
            continue
        draw_text_hb(
            img,
            mb if wval >= 500 else mr,
            f"{wn:<10} {wval}",
            13,
            (48, y + 4),
            col=(107, 114, 128),
        )
        draw_text_hb(img, f_up, sample_text, 16, (200, y + 4), col=(17, 24, 39))
        draw_text_hb(
            img,
            mb if wval >= 500 else mr,
            f"{wn:<10} Italic",
            13,
            (48, y + 32),
            col=(156, 163, 175),
        )
        draw_text_hb(img, f_it, sample_text, 16, (200, y + 32), col=(55, 65, 81))
        y += 66
        if wn != WEIGHTS[-1]:
            draw.line([(48, y - 10), (1252, y - 10)], fill=(243, 244, 246), width=1)
            y += 18
    return save_specimen(img, out_path)


def render_mono_duospace(fonts_dir: Path, out_path: Path) -> Path:
    mr = fonts_dir / "HolonMono-Regular.ttf"
    mb = fonts_dir / "HolonMono-Bold.ttf"
    img, draw = create_specimen_canvas(
        1300,
        840,
        "Holon Mono — 2:1 Duospace Alignment (550 / 1100 UPM)",
        "Exact 2:1 width ratio between half-width ASCII (550 UPM) and full-width CJK (1100 UPM)",
        mb,
        mr,
    )

    # Section 1: Column alignment grid
    draw_text_hb(
        img,
        mb,
        "1. Column Alignment & Metric Ratio Verification",
        13,
        (48, 120),
        col=(55, 65, 81),
    )
    ruler = "----+----1----+----2----+----3----+----4----+----5----+----6----+----7----+----8"
    ascii_line = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcdefgh"
    hankaku_k = "ｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄﾅﾆﾇﾈﾉﾊﾋﾌﾍﾎﾏﾐﾑﾒﾓﾔﾕﾖﾗﾘﾙﾚﾛﾜｦﾝ0123456789abcdefghijklmnopqrstuvwx"
    kana_line = "あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらり"
    kanji_line = "森羅万象春夏秋冬東西南北天地玄黄宇宙洪荒日月盈昃辰宿列張寒来暑往秋収冬蔵閏余成歳"

    y = 150
    draw_text_hb(img, mr, ruler, 14, (48, y), col=(156, 163, 175))
    draw_text_hb(img, mr, ascii_line, 14, (48, y + 24), col=(31, 41, 55))
    draw_text_hb(img, mr, hankaku_k, 14, (48, y + 48), col=(55, 65, 81))
    draw_text_hb(img, mr, kana_line, 14, (48, y + 72), col=(17, 24, 39))
    draw_text_hb(img, mr, kanji_line, 14, (48, y + 96), col=(17, 24, 39))

    # Space comparison
    draw_text_hb(
        img,
        mr,
        "[  ] 半角空白 2 文字 (550 × 2 = 1100 UPM)",
        14,
        (48, y + 130),
        col=(55, 65, 81),
    )
    draw_text_hb(
        img,
        mr,
        "[　] 全角空白 1 文字 (1100 UPM / U+3000)",
        14,
        (48, y + 154),
        col=(55, 65, 81),
    )

    draw.line([(48, 350), (1252, 350)], fill=(229, 231, 235), width=1)

    # Section 2: Table layout with seamless dy
    draw_text_hb(
        img,
        mb,
        "2. Mixed-Script Table Layout (Seamless Box Drawing)",
        13,
        (48, 375),
        col=(55, 65, 81),
    )
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
    ty = 405
    for line in table_lines:
        draw_text_hb(img, mr, line, 18, (48, ty), col=(17, 24, 39))
        ty += 21

    draw.line([(48, 600), (1252, 600)], fill=(229, 231, 235), width=1)

    # Section 3: Indentation and alignment in code with Japanese
    draw_text_hb(
        img,
        mb,
        "3. Column Indentation with Japanese Comments & Identifiers",
        13,
        (48, 625),
        col=(55, 65, 81),
    )
    code_lines = [
        "struct Record { id: u64, name: &'static str } // 2:1 等幅による正確なインデント保持",
        "let records = vec![",
        '    Record { id: 1001, name: "東京支社" }, // 4 漢字 (8 半角幅)',
        '    Record { id: 1002, name: "OSAKA   " }, // 8 ASCII  (8 半角幅)',
        '    Record { id: 1003, name: "名古屋市" }, // 4 漢字 (8 半角幅)',
        "];",
    ]
    cy = 655
    for line in code_lines:
        draw_text_hb(img, mr, line, 15, (48, cy), col=(17, 24, 39))
        cy += 24

    return save_specimen(img, out_path)


def render_mono_box_drawing(fonts_dir: Path, out_path: Path) -> Path:
    mr = fonts_dir / "HolonMono-Regular.ttf"
    mb = fonts_dir / "HolonMono-Bold.ttf"
    img, draw = create_specimen_canvas(
        1300,
        840,
        "Holon Mono — Box Drawing & Block Elements (U+2500..U+259F)",
        "Continuous, gap-free rendering across glyph bounding boxes in terminal & TUI environments",
        mb,
        mr,
    )

    # Section 1: Box Drawing Matrix
    draw_text_hb(
        img,
        mb,
        "1. Box Drawing Matrix (U+2500..U+257F) — Seamless 21px Line Height",
        13,
        (48, 120),
        col=(55, 65, 81),
    )
    box_matrix = [
        "┌─┬─┐  ┏━┳━┓  ╔═╦═╗  ╭─┬─╮  ┌┬┐ ┏┳┓ ╔╦╗ ╭┬╮",
        "│ │ │  ┃ ┃ ┃  ║ ║ ║  │ │ │  ├┼┤ ┣╋┫ ╠╬╣ ├┼┤",
        "├─┼─┤  ┣━╋━┫  ╠═╬═╣  ├─┼─┤  └┴┘ ┗┻┛ ╚╩╝ ╰┴╯",
        "└─┴─┘  ┗━┻━┛  ╚═╩═╝  ╰─┴─╯",
    ]
    by = 150
    for line in box_matrix:
        draw_text_hb(img, mr, line, 18, (48, by), col=(17, 24, 39))
        by += 21

    # Continuous lines
    draw_text_hb(
        img,
        mr,
        "Light:   ──────────────────────────────────────────────────────────",
        15,
        (48, 255),
        col=(31, 41, 55),
    )
    draw_text_hb(
        img,
        mr,
        "Heavy:   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        15,
        (48, 280),
        col=(17, 24, 39),
    )
    draw_text_hb(
        img,
        mr,
        "Double:  ══════════════════════════════════════════════════════════",
        15,
        (48, 305),
        col=(17, 24, 39),
    )
    draw_text_hb(
        img,
        mr,
        "Dashed:  ╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌",
        15,
        (48, 330),
        col=(55, 65, 81),
    )

    draw.line([(48, 370), (1252, 370)], fill=(229, 231, 235), width=1)

    # Section 2: TUI Window Sample (All lines exactly 77 cells wide, middle column at exact index 41)
    draw_text_hb(
        img,
        mb,
        "2. Terminal & TUI Window Dialog Sample (Precise Corners & Joints)",
        13,
        (48, 395),
        col=(55, 65, 81),
    )
    tui_window = [
        "┌─[ System Monitor : HolonOS v2.4 ]─────────────────────────────────────────┐",
        "│ Process: holon-daemon (PID: 4892)                   Uptime: 14d 08h 22m   │",
        "├────────────────────────────────────────┬──────────────────────────────────┤",
        "│ CPU [████████████████░░░░░░░░] 64.2%   │ Memory [██████████░░░░░░] 48.0%  │",
        "│ Disk I/O: 124.5 MB/s (Read: 82%)       │ Network: 1.2 Gbps (Active)       │",
        "├────────────────────────────────────────┴──────────────────────────────────┤",
        "│ Press [F1] Help   [F5] Refresh   [F8] Log Detail   [F10] Exit             │",
        "└───────────────────────────────────────────────────────────────────────────┘",
    ]
    wy = 425
    for line in tui_window:
        draw_text_hb(img, mr, line, 16, (48, wy), col=(17, 24, 39))
        wy += 19

    draw.line([(48, 600), (1252, 600)], fill=(229, 231, 235), width=1)

    # Section 3: Block Elements
    draw_text_hb(
        img,
        mb,
        "3. Block Elements (U+2580..U+259F) — Full UPM Vertical & Horizontal Span",
        13,
        (48, 625),
        col=(55, 65, 81),
    )
    blocks = "█ ▀ ▄ ▌ ▐ ░ ▒ ▓   ▂ ▃ ▄ ▅ ▆ ▇ █ ▏ ▎ ▍ ▌ ▋ ▊ ▉ █"
    draw_text_hb(img, mr, blocks, 18, (48, 655), col=(17, 24, 39))
    draw_text_hb(
        img,
        mr,
        "[████████████████████████████████████████] 100% Complete",
        15,
        (48, 700),
        col=(17, 24, 39),
    )
    draw_text_hb(
        img,
        mr,
        "[████████████████████░░░░░░░░░░░░░░░░░░░░]  50% In progress",
        15,
        (48, 730),
        col=(55, 65, 81),
    )

    return save_specimen(img, out_path)


def render_mono_variable(fonts_dir: Path, out_path: Path) -> Path:
    mr = fonts_dir / "HolonMono-Regular.ttf"
    mb = fonts_dir / "HolonMono-Bold.ttf"
    mv = fonts_dir / "HolonMono-Variable.otf"
    img, draw = create_specimen_canvas(
        1300,
        1160,
        "Holon Mono — Variable Font Axes (wght & GRAD)",
        "Fine-grained weight interpolation (50 & 25 intervals) and exact cell-width preservation (550 / 1100 UPM)",
        mb,
        mr,
    )

    # Section 1: 50-interval weight spectrum across full range (100..700)
    draw_text_hb(
        img,
        mb,
        "1. Full Range Weight Spectrum (wght: 100..700 in 50-unit intervals)",
        13,
        (48, 120),
        col=(55, 65, 81),
    )
    code_sample = "fn process_record(id: u64, name: &str) -> bool { // 550/1100 UPM 列幅完全維持 }"
    steps_50 = [100, 150, 200, 250, 300, 350, 400, 450, 500, 550, 600, 650, 700]
    y = 150
    adv_first = 0
    for wval in steps_50:
        is_major = wval % 100 == 0
        lbl_col = (17, 24, 39) if is_major else (156, 163, 175)
        draw_text_hb(
            img, mb if is_major else mr, f"wght {wval:>3}", 12, (48, y + 2), col=lbl_col
        )
        adv = draw_text_hb(
            img,
            mv,
            code_sample,
            15,
            (170, y + 2),
            var={"wght": wval, "GRAD": 0},
            col=(17, 24, 39),
        )
        if not adv_first:
            adv_first = adv
        y += 27

    # Vertical guidelines to prove width invariance across all 13 weights
    draw.line([(170, 142), (170, y)], fill=(220, 38, 38), width=1)
    draw.line(
        [(170 + adv_first, 142), (170 + adv_first, y)], fill=(220, 38, 38), width=1
    )

    draw.line([(48, y + 8), (1252, y + 8)], fill=(229, 231, 235), width=1)
    y += 28

    # Section 2: Fine 25-interval tuning in core reading weight range (350..500)
    draw_text_hb(
        img,
        mb,
        "2. Fine-grained Weight Tuning (wght: 350..500 in 25-unit intervals)",
        13,
        (48, y),
        col=(55, 65, 81),
    )
    steps_25 = [350, 375, 400, 425, 450, 475, 500]
    code_fine = 'let status = "ACTIVE"; // 25単位微細ウェイト調整: 文字幅は完全に不変 0123456789'
    y += 26
    adv_fine = 0
    for wval in steps_25:
        is_std = wval in (400, 500)
        lbl_col = (37, 99, 235) if is_std else (107, 114, 128)
        draw_text_hb(
            img, mb if is_std else mr, f"wght {wval:>3}", 12, (48, y + 2), col=lbl_col
        )
        adv = draw_text_hb(
            img,
            mv,
            code_fine,
            15,
            (170, y + 2),
            var={"wght": wval, "GRAD": 0},
            col=(17, 24, 39),
        )
        if not adv_fine:
            adv_fine = adv
        y += 30

    draw.line(
        [(170, y - (len(steps_25) * 30) - 4), (170, y)], fill=(220, 38, 38), width=1
    )
    draw.line(
        [(170 + adv_fine, y - (len(steps_25) * 30) - 4), (170 + adv_fine, y)],
        fill=(220, 38, 38),
        width=1,
    )

    draw.line([(48, y + 8), (1252, y + 8)], fill=(229, 231, 235), width=1)
    y += 28

    # Section 3: Grade Axis (GRAD: -100..+100) — Optical Density Adjustment & Width Invariance
    draw_text_hb(
        img,
        mb,
        "3. Grade Axis (GRAD: -100..+100) — Optical Density Adjustment & Width Invariance",
        13,
        (48, y),
        col=(55, 65, 81),
    )
    grad_text = (
        "let config = parse_env(); // 送り幅不変の光学補正・線の太さ調整 0123456789"
    )

    grad_steps = [-100, -50, 0, 50, 100]
    y += 28
    y_start_grad = y
    adv_mg = 0
    for gval in grad_steps:
        sign_str = f"{gval:+4}" if gval != 0 else "   0"
        is_default = gval == 0
        lbl_col = (
            (37, 99, 235)
            if is_default
            else ((17, 24, 39) if abs(gval) == 100 else (107, 114, 128))
        )
        draw_text_hb(
            img,
            mb if is_default else mr,
            f"[GRAD: {sign_str}]",
            12,
            (48, y + 2),
            col=lbl_col,
        )
        adv = draw_text_hb(
            img,
            mv,
            grad_text,
            15,
            (170, y + 2),
            var={"wght": 400, "GRAD": gval},
            col=(17, 24, 39),
        )
        if not adv_mg:
            adv_mg = adv
        y += 30

    draw.line([(170, y_start_grad - 4), (170, y - 4)], fill=(220, 38, 38), width=1)
    draw.line(
        [(170 + adv_mg, y_start_grad - 4), (170 + adv_mg, y - 4)],
        fill=(220, 38, 38),
        width=1,
    )

    # Dark background box
    y += 25
    draw.rectangle([(48, y), (1252, y + 130)], fill=(17, 24, 39))
    draw_text_hb(
        img,
        mr,
        "// Dark Mode Halation Optical Compensation (GRAD: -50, -100)",
        12,
        (72, y + 20),
        col=(156, 163, 175),
    )
    dark_code = "let config = parse_env(); // ハレーション抑制光学補正 0123456789"
    draw_text_hb(img, mr, "[GRAD:    0]", 12, (72, y + 48), col=(156, 163, 175))
    draw_text_hb(
        img,
        mv,
        dark_code,
        15,
        (190, y + 48),
        var={"wght": 400, "GRAD": 0},
        col=(243, 244, 246),
    )
    draw_text_hb(img, mb, "[GRAD:  -50]", 12, (72, y + 74), col=(147, 197, 253))
    draw_text_hb(
        img,
        mv,
        dark_code,
        15,
        (190, y + 74),
        var={"wght": 400, "GRAD": -50},
        col=(243, 244, 246),
    )
    draw_text_hb(img, mb, "[GRAD: -100]", 12, (72, y + 100), col=(96, 165, 250))
    draw_text_hb(
        img,
        mv,
        dark_code,
        15,
        (190, y + 100),
        var={"wght": 400, "GRAD": -100},
        col=(243, 244, 246),
    )

    return save_specimen(img, out_path)


def render_mono_code(fonts_dir: Path, out_path: Path) -> Path:
    mr = fonts_dir / "HolonMono-Regular.ttf"
    mb = fonts_dir / "HolonMono-Bold.ttf"
    img, draw = create_specimen_canvas(
        1300,
        840,
        "Holon Mono — Code Typography & Syntax Features",
        "Programming character disambiguation, slashed zero (zero), operators, and code layout",
        mb,
        mr,
    )

    # Section 1: Character Disambiguation & zero
    draw_text_hb(
        img,
        mb,
        "1. Character Disambiguation & Slashed Zero (zero feature)",
        13,
        (48, 120),
        col=(55, 65, 81),
    )
    disambig = (
        "0 vs O vs o  |  1 vs l vs I vs |  |  S vs 5  |  B vs 8  |  Z vs 2  |  ` vs '"
    )
    draw_text_hb(img, mr, disambig, 17, (48, 150), col=(31, 41, 55))

    z_code = "0123456789  0x10FF  100_000  0.00  const PORT = 8080;"
    draw_text_hb(img, mr, "[zero OFF]", 13, (48, 195), col=(156, 163, 175))
    draw_text_hb(
        img, mr, z_code, 20, (180, 195), feat={"zero": False}, col=(55, 65, 81)
    )
    draw_text_hb(img, mb, "[zero ON ]", 13, (48, 235), col=(37, 99, 235))
    draw_text_hb(img, mr, z_code, 20, (180, 235), feat={"zero": True}, col=(17, 24, 39))

    draw.line([(48, 275), (1252, 275)], fill=(229, 231, 235), width=1)

    # Section 2: Programming Operators & Delimiters
    draw_text_hb(
        img,
        mb,
        "2. Programming Operators & Delimiters",
        13,
        (48, 305),
        col=(55, 65, 81),
    )
    ops1 = "=>  ->  ::  !=  ==  ===  !==  <=  >=  &&  ||  ??  +=  -=  *=  /="
    ops2 = "()  []  {}  <>  ;  :  ,  .  /  \\  ~  ^  &  *  %  $  #  @  !  ?"
    draw_text_hb(img, mr, ops1, 16, (48, 340), col=(17, 24, 39))
    draw_text_hb(img, mr, ops2, 16, (48, 370), col=(55, 65, 81))

    draw.line([(48, 410), (1252, 410)], fill=(229, 231, 235), width=1)

    # Section 3: Practical Code Snippet
    draw_text_hb(
        img,
        mb,
        "3. Syntax Layout with Mixed Japanese Comments (Rust)",
        13,
        (48, 435),
        col=(55, 65, 81),
    )
    rust_code = [
        "// ユーザー認証およびセッション情報の非同期フェッチ処理",
        "pub async fn authenticate_user(pool: &DbPool, req: AuthRequest) -> Result<Session, AppError> {",
        '    let user = sqlx::query_as!(User, "SELECT * FROM users WHERE email = $1", req.email)',
        "        .fetch_optional(pool)",
        "        .await?",
        '        .ok_or(AppError::NotFound("指定されたユーザーが存在しません"))?;',
        "",
        "    if !crypto::verify_password(&req.password, &user.password_hash)? {",
        '        return Err(AppError::Unauthorized("パスワードが一致しません"));',
        "    }",
        "",
        "    let token = jwt::generate_token(&user.id, Role::Admin)?; // 認可トークン発行",
        "    println!(\"[AUTH] ユーザー '{}' のログインに成功しました\", user.name);",
        "    Ok(Session { user_id: user.id, token, is_active: true })",
        "}",
    ]
    cy = 465
    for line in rust_code:
        col = (107, 114, 128) if line.startswith("//") else (17, 24, 39)
        draw_text_hb(img, mr, line, 15, (48, cy), col=col)
        cy += 25

    return save_specimen(img, out_path)


def generate_all_specimens(fonts_dir: Path) -> list[Path]:
    generators = [
        ("specimen_sans_weights.png", render_sans_weights),
        ("specimen_sans_chws.png", render_sans_chws),
        ("specimen_sans_vertical.png", render_sans_vertical),
        ("specimen_sans_variable.png", render_sans_variable),
        ("specimen_sans_features.png", render_sans_features),
        ("specimen_mono_weights.png", render_mono_weights),
        ("specimen_mono_duospace.png", render_mono_duospace),
        ("specimen_mono_box_drawing.png", render_mono_box_drawing),
        ("specimen_mono_variable.png", render_mono_variable),
        ("specimen_mono_code.png", render_mono_code),
    ]
    out = []
    for fname, gen in generators:
        p = gen(fonts_dir, SPECIMENS_DIR / fname)
        out.append(p)
    return out


def test_specimen_generation(fonts_dir: Path) -> None:
    paths = generate_all_specimens(fonts_dir)
    assert len(paths) == 10 and all(
        p.exists() and p.stat().st_size > 10_000 for p in paths
    )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, *sys.argv[1:]], plugins=[sys.modules[__name__]]))
