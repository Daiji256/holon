# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "brotli>=1.1.0",
#     "chws-tool>=1.4.0",
#     "fonttools>=4.50.0",
#     "glyphsLib>=6.9.0",
#     "ufo2ft>=3.11.0",
#     "ufoLib2>=0.16.0",
# ]
# ///

"""Build script for Holon Sans Variable Font (CFF2 / OTF + WOFF2).
Supports 3 variable axes:
1. Weight ('wght'): 100 to 700 (Thin to Bold, default 400)
2. Slant ('slnt'): -11.0° to 0.0° (Italic/Oblique to Upright, default 0)
3. Grade ('GRAD'): -100 to +100 (stroke thickness variation without width change, default 0)

Typography features:
- Dual-scale: CJK scaled 0.97x centered in 1000 UPM; Latin/symbols scaled 1.02x
- Contextual half-width spacing (chws / vchw) with fullwidth space (U+3000) compaction
- Safe CJK compatibility ideographs expansion (U+F900..U+FAFF mapped to canonical ideographs)
- Full compliance with SIL OFL 1.1 naming and license rules
"""

from __future__ import annotations

import asyncio
import copy
import math
import re
import sys
import time
import unicodedata
from pathlib import Path

from east_asian_spacing import Builder, Config
from fontTools.designspaceLib import (
    AxisDescriptor,
    DesignSpaceDocument,
    InstanceDescriptor,
    SourceDescriptor,
)
from fontTools.pens.transformPen import TransformPointPen
from fontTools.ttLib import TTFont
from glyphsLib import GSFont, to_designspace
import ufo2ft
import ufoLib2

GLYPHS_PATH = Path("tmp/sources-sans-jp/unzipped/sources/masters/IBM Plex Sans JP.glyphs")
OUTPUT_DIR = Path("fonts")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_VAR_OTF = OUTPUT_DIR / "HolonSans-Variable.otf"
OUTPUT_VAR_WOFF2 = OUTPUT_DIR / "HolonSans-Variable.woff2"

FAMILY_NAME = "Holon Sans"
VENDOR_URL = "https://github.com/Daiji256/holon"
COPYRIGHT_STRING = (
    "Copyright 2026 Daiji Suzuki. "
    "Copyright 2018 IBM Corp. All rights reserved. "
    "Portions Copyright 2021 Sandoll Inc."
)
LICENSE_DESCRIPTION = (
    "This Font Software is licensed under the SIL Open Font License, Version 1.1. "
    "This license is available with a FAQ at: https://openfontlicense.org"
)
LICENSE_URL = "https://openfontlicense.org"

SCALE_SANS = 1.02
SCALE_JP = 0.97
JP_CENTER_X = 500.0
JP_CENTER_Y = 400.0
SLANT_ANGLE = 11.0  # degrees

INITIAL_SYNC_GLYPHS = [
    'yusmall-hira.half', 'A.blackBox', 'A.blackCircled', 'A.roundBlackBox',
    'a-hira.box', 'a-hira.circled', 'a-hira.paren', 'a-hira.roundBox',
    'asmall-hira', 'asmall-hira.hori', 'asmall-hira.prop', 'asmall-hira.prop.vert',
    'asmall-hira.vert', 'ba_i_to-kata', 'ba_i_to-kata.vert', 'baareruSquare',
    'baareruSquare.vert', 'baatsuleftjust', 'baatsuleftjust.vert', 'bareruleftjust',
    'bareruleftjust.vert', 'biruSquare', 'biruSquare.vert', 'de-kata.roundedBox',
    'doruSquare', 'doruSquare.vert', 'ga_ru-kata', 'ga_ru-kata.vert', 'garonSquare',
    'garonSquare.vert', 'guramutonSquare', 'guramutonSquare.vert', 'haitsu',
    'haitsu.vert', 'haituSquare', 'herutsu', 'herutsu.vert', 'hoonSquare',
    'huranSquare', 'huranSquare.vert', 'ininguSquare', 'ininguSquare.vert',
    'kiromeetoruSquare', 'ku-kata.box', 'ku-kata.circled', 'ku-kata.paren',
    'ku-kata.roundBox', 'mahhaSquare', 'mahhaSquare.vert', 'mansyonSquare',
    'meetoruSquare', 'meetoruSquare.vert', 'megatonSquare', 'megatonSquare.vert',
    'mikuronSquare', 'mikuronSquare.vert', 'na-kata.box', 'na-kata.circled',
    'na-kata.paren', 'na-kata.roundBox', 'o-kata.blackBox', 'o-kata.blackCircled',
    'o-kata.roundBlackBox', 'paasentoSquare', 'paasentoSquare.vert', 'pesetaleftjust',
    'pesetaleftjust.vert', 'pikoSquare', 'pikoSquare.vert', 'se_n_ti-kata',
    'se_n_ti-kata.vert', 'sentiSquare.vert', 'sento', 'sento.vert', 'sentoSquare',
    'siringuSquare', 'siringuSquare.vert', 'ta-kata.box', 'ta-kata.circled',
    'ta-kata.paren', 'ta-kata.roundBox', 'uonSquare', 'uonSquare.vert', 'wa-hira',
    'wa-hira.hori', 'wa-hira.prop', 'wa-hira.prop.vert', 'wa-hira.vert',
    'wasmall-hira.half', 'wasmall-hira.half.rotat', 'watto', 'watto.vert',
    'wattoSquare', 'wattoSquare.vert', 'ya-hira.half', 'ya-hira.half.rotat',
    'yusmall-hira.half.rotat'
]


def sync_glyph(ufo_thin, ufo_reg, ufo_bold, gname: str) -> None:
    """Synchronize non-interpolatable glyph outlines from Regular master."""
    if gname in ufo_reg:
        ufo_thin[gname] = ufo_reg[gname].copy()
        ufo_bold[gname] = ufo_reg[gname].copy()


def is_latin_or_symbol(u: int | None) -> bool:
    """Return True if unicode codepoint belongs to Latin, Greek, Cyrillic, or Western symbols."""
    if u is None:
        return False
    if 0x2000 <= u <= 0x200B or u == 0x3000:
        return False  # Keep standard typographic space widths
    if u < 0x02B0:  # Basic Latin, Latin-1, Latin Extended
        return True
    if 0x0370 <= u <= 0x052F:  # Greek, Cyrillic
        return True
    if 0x200C <= u <= 0x23FF:  # General punctuation, currency, math, arrows
        return True
    return False


def apply_dual_scale(ufo: ufoLib2.Font) -> None:
    """Apply dual-scale: Latin 1.02x, Japanese CJK 0.97x centered at (500, 400)."""
    dx_jp = JP_CENTER_X * (1.0 - SCALE_JP)
    dy_jp = JP_CENTER_Y * (1.0 - SCALE_JP)

    for g in ufo:
        unicodes = set(g.unicodes or [])
        if g.unicode is not None:
            unicodes.add(g.unicode)

        if 0x3000 in unicodes or 0x2003 in unicodes or 0x2001 in unicodes:
            g.width = 1000
            continue
        if 0x2000 in unicodes or 0x2002 in unicodes:
            g.width = 500
            continue

        if is_latin_or_symbol(g.unicode):
            for c in g.contours:
                for p in c.points:
                    p.x *= SCALE_SANS
                    p.y *= SCALE_SANS
            g.width = int(round(g.width * SCALE_SANS))
        else:
            for c in g.contours:
                for p in c.points:
                    p.x = p.x * SCALE_JP + dx_jp
                    p.y = p.y * SCALE_JP + dy_jp


def add_cjk_compat_mappings(ufo_list: list[ufoLib2.Font]) -> int:
    """Map missing CJK Compatibility Ideographs (U+F900..U+FAFF) to canonical unified ideographs."""
    code_to_gname = {}
    for g in ufo_list[0]:
        if g.unicodes:
            for u in g.unicodes:
                code_to_gname[u] = g.name

    count = 0
    for code in range(0xF900, 0xFB00):
        if code in code_to_gname:
            continue
        d = unicodedata.normalize("NFKD", chr(code))
        if len(d) == 1 and ord(d) in code_to_gname:
            canonical_gname = code_to_gname[ord(d)]
            for ufo in ufo_list:
                if canonical_gname in ufo:
                    glyph = ufo[canonical_gname]
                    glyph.unicodes = list(glyph.unicodes or []) + [code]
            count += 1
    return count


def make_slanted_master(ufo_src: ufoLib2.Font, name: str) -> ufoLib2.Font:
    """Create a slanted master by applying 11.0° shear."""
    s = math.tan(math.radians(SLANT_ANGLE))
    new_f = ufoLib2.Font()
    new_f.info = copy.deepcopy(ufo_src.info)
    new_f.info.familyName = FAMILY_NAME
    new_f.info.styleName = name
    new_f.features.text = ufo_src.features.text
    new_f.groups = copy.deepcopy(ufo_src.groups)
    new_f.lib = copy.deepcopy(ufo_src.lib)

    for gname in ufo_src.keys():
        src_g = ufo_src[gname]
        ng = new_f.newGlyph(gname)
        ng.width = src_g.width
        ng.height = src_g.height
        ng.verticalOrigin = src_g.verticalOrigin
        ng.unicodes = list(src_g.unicodes or [])

        # Shear: Latin around baseline, CJK around cy=400
        latin = is_latin_or_symbol(src_g.unicode)
        dy_pivot = 0.0 if latin else -JP_CENTER_Y * s

        ppen = ng.getPointPen()
        t_pen = TransformPointPen(ppen, (1.0, 0.0, s, 1.0, dy_pivot, 0.0))
        src_g.drawPoints(t_pen)

    return new_f


def make_grade_master(
    ufo_base: ufoLib2.Font,
    ufo_target: ufoLib2.Font,
    factor: float,
    name: str,
) -> ufoLib2.Font:
    """Create a Grade master by interpolating stroke weight while locking advance widths to base."""
    new_f = ufoLib2.Font()
    new_f.info = copy.deepcopy(ufo_base.info)
    new_f.info.familyName = FAMILY_NAME
    new_f.info.styleName = name
    new_f.features.text = ufo_base.features.text
    new_f.groups = copy.deepcopy(ufo_base.groups)
    new_f.lib = copy.deepcopy(ufo_base.lib)

    for gname in ufo_base.keys():
        g_base = ufo_base[gname]
        ng = new_f.newGlyph(gname)
        ng.width = g_base.width
        ng.height = g_base.height
        ng.verticalOrigin = g_base.verticalOrigin
        ng.unicodes = list(g_base.unicodes or [])

        if gname not in ufo_target:
            g_base.drawPoints(ng.getPointPen())
            continue

        g_tgt = ufo_target[gname]
        # Check contour/point compatibility
        if len(g_base.contours) != len(g_tgt.contours):
            # Fallback to base glyph outline if incompatible
            for c in g_base.contours:
                nc = ng.newContour()
                for p in c.points:
                    nc.appendPoint((p.x, p.y), segmentType=p.segmentType, smooth=p.smooth, name=p.name)
            continue

        # Compute horizontal centering shift to keep glyph centered as stroke thickness changes
        dx = -(factor * (g_tgt.width - g_base.width)) / 2.0

        ppen = ng.getPointPen()
        compatible = True
        for ca, cb in zip(g_base.contours, g_tgt.contours):
            if len(ca.points) != len(cb.points):
                compatible = False
                break
            ppen.beginPath()
            for pa, pb in zip(ca.points, cb.points):
                x = pa.x + factor * (pb.x - pa.x) + dx
                y = pa.y + factor * (pb.y - pa.y)
                ppen.addPoint((x, y), segmentType=pa.segmentType, smooth=pa.smooth, name=pa.name)
            ppen.endPath()

        if not compatible:
            # Fallback
            ng.clearContours()
            for c in g_base.contours:
                nc = ng.newContour()
                for p in c.points:
                    nc.appendPoint((p.x, p.y), segmentType=p.segmentType, smooth=p.smooth, name=p.name)

    return new_f


def update_variable_metadata(font: TTFont) -> None:
    """Update OpenType name, OS/2, head, post tables strictly conforming to SIL OFL 1.1."""
    name_table = font["name"]
    ps_name = "HolonSans-Variable"
    full_name = "Holon Sans"
    unique_id = f"1.000;NONE;{ps_name}"

    name_records = {
        0: COPYRIGHT_STRING,
        1: FAMILY_NAME,
        2: "Regular",
        3: unique_id,
        4: full_name,
        5: "Version 1.000",
        6: ps_name,
        7: "",  # Cleared trademark
        8: "Holon Project",
        9: "Mike Abbink, Paul van der Laan, Pieter van Rosmalen, Sandoll Inc., Daiji Suzuki",
        11: VENDOR_URL,
        12: VENDOR_URL,
        13: LICENSE_DESCRIPTION,
        14: LICENSE_URL,
        16: FAMILY_NAME,
        17: "Regular",
        25: "HolonSans",  # Variations PostScriptName Prefix
    }

    for record in list(name_table.names):
        if record.nameID in name_records:
            name_table.names.remove(record)

    for name_id, val in name_records.items():
        if val:
            name_table.addMultilingualName({"en": val}, nameID=name_id)

    # OS/2 table
    if "OS/2" in font:
        font["OS/2"].usWeightClass = 400
        font["OS/2"].fsSelection = 0x40  # REGULAR
        font["OS/2"].achVendID = "HLON"

    # head & post
    if "head" in font:
        font["head"].macStyle = 0
    if "post" in font:
        font["post"].italicAngle = 0.0

    # Ensure fullwidth space (U+3000) has exact 1000 UPM advance width
    cmap_best = font.getBestCmap()
    if 0x3000 in cmap_best:
        g_3000 = cmap_best[0x3000]
        if "hmtx" in font:
            font["hmtx"][g_3000] = (1000, 0)
        if "vmtx" in font:
            font["vmtx"].metrics[g_3000] = (1000, 880)


async def apply_chws(input_path: Path, output_path: Path) -> None:
    """Inject chws and vchw OpenType feature rules using east_asian_spacing."""
    config = Config.default.clone()
    config.fullwidth_advance = 1000
    builder = Builder(str(input_path), config=config)
    res = await builder.build_and_save(output_path)
    if not res:
        raise RuntimeError(f"Failed to inject chws into {input_path}")


def build_variable_font() -> Path:
    if not GLYPHS_PATH.exists():
        raise FileNotFoundError(f"Source glyphs file not found: {GLYPHS_PATH}")

    print("=== Building Holon Sans Multi-Axis Variable Font (CFF2) ===")
    t0 = time.time()
    font = GSFont(str(GLYPHS_PATH))
    print(f"Loaded Glyphs source in {time.time() - t0:.1f}s.")

    ds = to_designspace(font)
    ufo_thin = ds.sources[0].font
    ufo_reg  = ds.sources[1].font
    ufo_bold = ds.sources[2].font

    # Set family name on base UFOs
    for u in [ufo_thin, ufo_reg, ufo_bold]:
        u.info.familyName = FAMILY_NAME

    # 1. Synchronize initial incompatible special symbols
    print(f"Synchronizing {len(INITIAL_SYNC_GLYPHS)} special symbols...")
    for gname in INITIAL_SYNC_GLYPHS:
        sync_glyph(ufo_thin, ufo_reg, ufo_bold, gname)

    # 2. Dual-scale Japanese (0.97x centered) and Latin (1.02x)
    print("Applying dual-scale balance (0.97x CJK, 1.02x Latin)...")
    for u in [ufo_thin, ufo_reg, ufo_bold]:
        apply_dual_scale(u)

    # 3. Add safe CJK Compatibility Ideographs mappings
    num_compat = add_cjk_compat_mappings([ufo_thin, ufo_reg, ufo_bold])
    print(f"Mapped {num_compat} CJK compatibility ideographs to canonical unified glyphs.")

    # 4. Generate derived masters for Slant (slnt) and Grade (GRAD)
    print("Generating Slanted masters (11.0° shear)...")
    ufo_thin_slnt = make_slanted_master(ufo_thin, "Thin Slanted")
    ufo_reg_slnt  = make_slanted_master(ufo_reg, "Regular Slanted")
    ufo_bold_slnt = make_slanted_master(ufo_bold, "Bold Slanted")

    print("Generating Grade masters (stroke variation with fixed metrics)...")
    # Grade +100: +15% towards Bold; Grade -100: +15% towards Thin
    ufo_reg_grad_pos = make_grade_master(ufo_reg, ufo_bold, 0.15, "Regular Grade+")
    ufo_reg_grad_neg = make_grade_master(ufo_reg, ufo_thin, 0.15, "Regular Grade-")

    # 5. Build multi-axis DesignSpace
    print("Constructing 3-axis DesignSpace (wght, slnt, GRAD)...")
    var_ds = DesignSpaceDocument()

    # Axis: Weight
    ax_wght = AxisDescriptor()
    ax_wght.tag = "wght"
    ax_wght.name = "Weight"
    ax_wght.minimum = 100
    ax_wght.default = 400
    ax_wght.maximum = 700
    ax_wght.map = [(100, 100), (400, 360), (700, 700)]
    var_ds.addAxis(ax_wght)

    # Axis: Slant
    ax_slnt = AxisDescriptor()
    ax_slnt.tag = "slnt"
    ax_slnt.name = "Slant"
    ax_slnt.minimum = -11
    ax_slnt.default = 0
    ax_slnt.maximum = 0
    var_ds.addAxis(ax_slnt)

    # Axis: Grade
    ax_grad = AxisDescriptor()
    ax_grad.tag = "GRAD"
    ax_grad.name = "Grade"
    ax_grad.minimum = -100
    ax_grad.default = 0
    ax_grad.maximum = 100
    var_ds.addAxis(ax_grad)

    # Sources
    sources_config = [
        (ufo_thin,         {"Weight": 100, "Slant": 0,   "Grade": 0},    "Thin"),
        (ufo_reg,          {"Weight": 360, "Slant": 0,   "Grade": 0},    "Regular"),
        (ufo_bold,         {"Weight": 700, "Slant": 0,   "Grade": 0},    "Bold"),
        (ufo_thin_slnt,    {"Weight": 100, "Slant": -11, "Grade": 0},    "Thin Slanted"),
        (ufo_reg_slnt,     {"Weight": 360, "Slant": -11, "Grade": 0},    "Regular Slanted"),
        (ufo_bold_slnt,    {"Weight": 700, "Slant": -11, "Grade": 0},    "Bold Slanted"),
        (ufo_reg_grad_pos, {"Weight": 360, "Slant": 0,   "Grade": 100},  "Regular Grade+"),
        (ufo_reg_grad_neg, {"Weight": 360, "Slant": 0,   "Grade": -100}, "Regular Grade-"),
    ]

    for font_obj, loc, sname in sources_config:
        src = SourceDescriptor()
        src.font = font_obj
        src.location = loc
        src.name = sname
        src.familyName = FAMILY_NAME
        src.styleName = sname
        var_ds.addSource(src)

    # Named Instances
    named_instances = [
        ("Thin", 100, 0),
        ("ExtraLight", 200, 0),
        ("Light", 300, 0),
        ("Regular", 400, 0),
        ("Text", 450, 0),
        ("Medium", 500, 0),
        ("SemiBold", 600, 0),
        ("Bold", 700, 0),
        ("Thin Italic", 100, -11),
        ("ExtraLight Italic", 200, -11),
        ("Light Italic", 300, -11),
        ("Italic", 400, -11),
        ("Text Italic", 450, -11),
        ("Medium Italic", 500, -11),
        ("SemiBold Italic", 600, -11),
        ("Bold Italic", 700, -11),
    ]

    for iname, w_val, s_val in named_instances:
        inst = InstanceDescriptor()
        inst.familyName = FAMILY_NAME
        inst.styleName = iname
        inst.location = {"Weight": w_val, "Slant": s_val, "Grade": 0}
        var_ds.addInstance(inst)

    # 6. Compile CFF2 Variable Font
    intermediate_otf = Path("tmp") / "HolonSans-Variable.intermediate.otf"
    for attempt in range(10):
        try:
            print(f"Compiling CFF2 variable font (attempt {attempt + 1})...")
            var_font = ufo2ft.compileVariableCFF2(var_ds)
            update_variable_metadata(var_font)
            var_font.save(intermediate_otf)
            print(f"Intermediate variable font saved: {intermediate_otf}")
            break
        except Exception as e:
            msg = str(e)
            m = re.search(r"Glyph '([^']+)'", msg)
            if m:
                bad_glyph = m.group(1)
                print(f"Fixing incompatible glyph across masters: '{bad_glyph}'")
                sync_glyph(ufo_thin, ufo_reg, ufo_bold, bad_glyph)
                # Re-derive affected masters for this glyph
                for gname in [bad_glyph]:
                    if gname in ufo_reg:
                        ufo_thin_slnt[gname] = ufo_reg_slnt[gname].copy()
                        ufo_bold_slnt[gname] = ufo_reg_slnt[gname].copy()
                        ufo_reg_grad_pos[gname] = ufo_reg[gname].copy()
                        ufo_reg_grad_neg[gname] = ufo_reg[gname].copy()
                continue
            raise RuntimeError(f"Variable compilation failed: {e}") from e

    # 7. Inject chws / vchw contextual spacing
    print("Injecting chws / vchw contextual spacing...")
    asyncio.run(apply_chws(intermediate_otf, OUTPUT_VAR_OTF))

    # 8. Export WOFF2 web format
    print("Exporting web WOFF2 format...")
    otf_for_woff2 = TTFont(OUTPUT_VAR_OTF)
    otf_for_woff2.flavor = "woff2"
    otf_for_woff2.save(OUTPUT_VAR_WOFF2)

    # Clean intermediate
    if intermediate_otf.exists():
        intermediate_otf.unlink()

    print(f"\n==========================================")
    print(f"Holon Sans Variable Font Build COMPLETE!")
    print(f"  OTF:   {OUTPUT_VAR_OTF} ({OUTPUT_VAR_OTF.stat().st_size:,} bytes)")
    print(f"  WOFF2: {OUTPUT_VAR_WOFF2} ({OUTPUT_VAR_WOFF2.stat().st_size:,} bytes)")
    print(f"==========================================")
    return OUTPUT_VAR_OTF


if __name__ == "__main__":
    build_variable_font()
