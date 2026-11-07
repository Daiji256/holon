# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "brotli>=1.1.0",
#     "fonttools>=4.50.0",
#     "pillow>=10.0.0",
#     "uharfbuzz>=0.39.0",
# ]
# ///

"""Build script for Holon Mono (ホロン・モノ):
A clean, high-precision Japanese-Latin duospace / programming monospace font family.
- Western/Latin from IBM Plex Mono: advance 550 UPM (aspect ratio 0.55 x 1.00)
- Japanese CJK from IBM Plex Sans JP: advance 1100 UPM (aspect ratio 1.10 x 1.00)
- Strict 2:1 duospace character width ratio (1 Japanese character = 2 Latin characters)
- Japanese glyphs scaled to 0.97x (visual harmony with code)
- Latin glyphs scaled horizontally to fit 550 UPM cell, preserving Plex Mono's iconic readability
- Box Drawing (U+2500..U+257F) seamlessly connecting in terminal / editor columns
- Fullwidth space (U+3000) exactly 1100 UPM, Halfwidth space (U+0020) exactly 550 UPM
- Halfwidth Katakana (U+FF61..U+FF9F) centered to 550 UPM cell
- Authentic Italic style: native Plex Mono Italic + 9.0° slanted Japanese ideographs & kana
- OS/2 and hhea metrics aligned to 950 / -225 to prevent clipping in VS Code and terminals
- Fully complies with SIL OFL 1.1 licensing and naming guidelines
- Exports desktop TTF and web WOFF2
"""

from __future__ import annotations

import argparse
import math
import sys
import unicodedata
from pathlib import Path

from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont

# Monospace duospace constants
HALF_WIDTH = 550        # Halfwidth advance width (0.55 * 1000)
FULL_WIDTH = 1100       # Fullwidth advance width (1.10 * 1000, exactly 2 * 550)
SCALE_MONO_X = 550.0 / 600.0   # Horizontal scale for Latin (600 -> 550)
SCALE_MONO_Y = 0.98            # Vertical scale for Latin (harmonic cap-height)
SCALE_JP = 0.97                # Scale for Japanese CJK glyphs
JP_CENTER_X = 500.0            # Horizontal pivot of 1000 UPM CJK box
JP_CENTER_Y = 400.0            # Vertical visual center of CJK ideographs
JP_OFFSET_X = (FULL_WIDTH - 1000.0 * SCALE_JP) / 2.0   # 65.0 UPM
JP_OFFSET_Y = JP_CENTER_Y * (1.0 - SCALE_JP)           # 12.0 UPM
ITALIC_ANGLE = -9.0            # Matching IBM Plex Mono Italic angle (degrees)

FAMILY_NAME = "Holon Mono"
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

WEIGHT_VALUES = {
    "Thin": 100,
    "ExtraLight": 200,
    "Light": 300,
    "Regular": 400,
    "Text": 450,
    "Medium": 500,
    "SemiBold": 600,
    "Bold": 700,
}

UPSTREAM_BASE = Path("tmp/plex/packages")
OUTPUT_DIR = Path("fonts")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def is_latin_or_symbol(code: int) -> bool:
    """Return True if unicode belongs to Latin, Greek, Cyrillic, or Western symbols."""
    if 0x2000 <= code <= 0x200B or code == 0x3000:
        return False  # Handled separately for cell width
    if code < 0x02B0:  # Basic Latin, Latin-1, Latin Extended-A/B
        return True
    if 0x0370 <= code <= 0x052F:  # Greek, Cyrillic
        return True
    if 0x200C <= code <= 0x218F:  # Punctuation, Currency, Letterlike, Number Forms
        return True
    if 0x2190 <= code <= 0x23FF:  # Arrows, Math, Technical
        return True
    if 0x2500 <= code <= 0x257F:  # Box Drawing
        return True
    if 0x2580 <= code <= 0x259F:  # Block Elements
        return True
    if 0x25A0 <= code <= 0x25FF:  # Geometric Shapes
        return True
    if 0xFB00 <= code <= 0xFB4F:  # Alphabetic Presentation Forms (ligatures)
        return True
    return False


def get_source_paths(weight: str, italic: bool = False) -> tuple[Path, Path]:
    """Return paths to (plex_mono_ttf, plex_jp_ttf)."""
    if italic:
        mono_style = "Italic" if weight == "Regular" else f"{weight}Italic"
    else:
        mono_style = weight

    mono_name = f"IBMPlexMono-{mono_style}.ttf"
    jp_name = f"IBMPlexSansJP-{weight}.ttf"

    mono_path = UPSTREAM_BASE / "plex-mono" / "fonts" / "complete" / "ttf" / mono_name
    jp_path = UPSTREAM_BASE / "plex-sans-jp" / "fonts" / "complete" / "ttf" / "hinted" / jp_name

    if not mono_path.exists():
        raise FileNotFoundError(f"IBM Plex Mono source not found: {mono_path}")
    if not jp_path.exists():
        raise FileNotFoundError(f"IBM Plex Sans JP source not found: {jp_path}")

    return mono_path, jp_path


def update_name_table(font: TTFont, weight: str, italic: bool) -> None:
    """Update font naming records in the 'name' table conforming strictly to SIL OFL 1.1."""
    name_table = font["name"]

    style_name = weight
    if italic:
        style_name = f"{weight} Italic" if weight != "Regular" else "Italic"

    ps_suffix = style_name.replace(" ", "")
    ps_name = f"HolonMono-{ps_suffix}"
    full_name = f"{FAMILY_NAME} {style_name}"
    unique_id = f"1.000;NONE;{ps_name}"

    if weight == "Bold" and italic:
        subfamily = "Bold Italic"
    elif weight == "Bold":
        subfamily = "Bold"
    elif italic:
        subfamily = "Italic"
    else:
        subfamily = "Regular"

    name_records = {
        0: COPYRIGHT_STRING,
        1: FAMILY_NAME,
        2: subfamily,
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
        16: FAMILY_NAME,       # Typographic Family
        17: style_name,        # Typographic Subfamily
        20: f"{ps_name}-83pv-RKSJ-H",
    }

    for record in list(name_table.names):
        if record.nameID in name_records:
            name_table.names.remove(record)

    for name_id, val in name_records.items():
        if val:
            name_table.addMultilingualName({"en": val}, nameID=name_id)


def add_vertical_semicolon(font_jp: TTFont) -> None:
    """Add uniFF1B.vert (rotated 90° CW around (550, 400)) and update vert/vrt2 in GSUB."""
    glyf = font_jp["glyf"]
    hmtx = font_jp["hmtx"]
    vmtx = font_jp.get("vmtx")

    if "uniFF1B" not in glyf or "uniFF1B.vert" in glyf:
        return

    glyph_set = font_jp.getGlyphSet()
    rec_pen = DecomposingRecordingPen(glyph_set)
    glyph_set["uniFF1B"].draw(rec_pen)

    tt_pen = TTGlyphPen(None)
    # Center rotation around (550, 400): x' = y + 150, y' = 950 - x
    t_pen = TransformPen(tt_pen, (0.0, -1.0, 1.0, 0.0, 150.0, 950.0))
    rec_pen.replay(t_pen)

    new_glyph = tt_pen.glyph()
    new_glyph.recalcBounds(glyf)

    glyf["uniFF1B.vert"] = new_glyph
    hmtx["uniFF1B.vert"] = (FULL_WIDTH, new_glyph.xMin)

    if vmtx is not None:
        tsb = 880 - (new_glyph.yMax if new_glyph.numberOfContours != 0 else 0)
        vmtx.metrics["uniFF1B.vert"] = (FULL_WIDTH, tsb)

    order = font_jp.getGlyphOrder()
    if "uniFF1B.vert" not in order:
        order.append("uniFF1B.vert")
        font_jp.setGlyphOrder(order)
        font_jp["maxp"].numGlyphs = len(order)
        if font_jp.get("vhea") and vmtx:
            font_jp["vhea"].numOfLongVerMetrics = len(order)

    # Update GSUB vert and vrt2 features
    if "GSUB" in font_jp:
        gsub = font_jp["GSUB"].table
        for rec in gsub.FeatureList.FeatureRecord:
            if rec.FeatureTag in ("vert", "vrt2"):
                for idx in rec.Feature.LookupListIndex:
                    lookup = gsub.LookupList.Lookup[idx]
                    if lookup.LookupType == 1:
                        for st in lookup.SubTable:
                            if hasattr(st, "mapping") and "uniFF1A" in st.mapping:
                                st.mapping["uniFF1B"] = "uniFF1B.vert"


def transform_japanese_glyphs(
    font_jp: TTFont,
    italic: bool,
    scale: float = SCALE_JP,
) -> None:
    """Scale Japanese CJK glyphs to scale (0.97x) and center in 1100 advance cell.
    In Italic mode, apply 9.0° shear matching IBM Plex Mono Italic.
    """
    cmap_jp = font_jp.getBestCmap()
    glyf_table = font_jp["glyf"]
    hmtx_table = font_jp["hmtx"]
    vmtx_table = font_jp.get("vmtx")
    glyph_set = font_jp.getGlyphSet()

    # Collect CJK glyph names
    cjk_gnames = set()
    for code, gname in cmap_jp.items():
        if not is_latin_or_symbol(code):
            cjk_gnames.add(gname)

    # Include vertical punctuation alternates
    for gname in ["uniFF1A.vert", "uniFF1B.vert"]:
        if gname in glyf_table:
            cjk_gnames.add(gname)

    # Offset to center 1000 UPM scaled glyph in 1100 advance cell
    dx = JP_OFFSET_X
    dy = JP_OFFSET_Y

    if italic:
        slant = math.tan(math.radians(-ITALIC_ANGLE))  # 9.0 degrees (approx 0.15838)
        # Combined matrix: M_slant * M_scale with pivot (JP_CENTER_X, JP_CENTER_Y)
        # x' = scale*x + (scale*slant)*y + dx + (dy - JP_CENTER_Y) * slant
        matrix = (
            scale,
            0.0,
            scale * slant,
            scale,
            dx + (dy - JP_CENTER_Y) * slant,
            dy,
        )
    else:
        matrix = (scale, 0.0, 0.0, scale, dx, dy)

    for gname in cjk_gnames:
        if gname not in glyf_table:
            continue
        orig_glyph = glyf_table[gname]
        orig_w, orig_lsb = hmtx_table[gname]

        # Check if halfwidth katakana (uniFF61..uniFF9F)
        # They were 500 UPM in JP font; in Holon Mono they become 550 UPM
        is_hw = (orig_w == 500)

        if orig_glyph.numberOfContours == 0:
            hmtx_table[gname] = (HALF_WIDTH if is_hw else FULL_WIDTH, 0)
            continue

        rec_pen = DecomposingRecordingPen(glyph_set)
        glyph_set[gname].draw(rec_pen)

        tt_pen = TTGlyphPen(None)
        if is_hw:
            # Center 500 UPM halfwidth in 550 cell (+25 UPM)
            hw_matrix = (1.0, 0.0, 0.0, 1.0, 25.0, 0.0)
            rec_pen.replay(TransformPen(tt_pen, hw_matrix))
        else:
            rec_pen.replay(TransformPen(tt_pen, matrix))

        new_glyph = tt_pen.glyph()
        new_glyph.recalcBounds(glyf_table)
        glyf_table[gname] = new_glyph

        if is_hw:
            hmtx_table[gname] = (HALF_WIDTH, orig_lsb + 25)
        else:
            new_lsb = int(round(orig_lsb * scale + dx))
            hmtx_table[gname] = (FULL_WIDTH, new_lsb)

        if vmtx_table is not None:
            tsb = 880 - (new_glyph.yMax if new_glyph.numberOfContours != 0 else 0)
            vmtx_table.metrics[gname] = (FULL_WIDTH, tsb)


def merge_mono_glyphs(
    font_jp: TTFont,
    font_mono: TTFont,
    scale_x: float = SCALE_MONO_X,
    scale_y: float = SCALE_MONO_Y,
) -> None:
    """Extract Latin, symbol, box drawing glyphs from font_mono, scale to 550 advance, and insert into font_jp."""
    cmap_mono = font_mono.getBestCmap()
    cmap_jp = font_jp.getBestCmap()

    glyf_jp = font_jp["glyf"]
    hmtx_jp = font_jp["hmtx"]
    vmtx_jp = font_jp.get("vmtx")
    vhea_jp = font_jp.get("vhea")

    glyph_set_mono = font_mono.getGlyphSet()

    new_cmap_entries = {}
    latin_matrix = (scale_x, 0.0, 0.0, scale_y, 0.0, 0.0)

    for ucode, gname_mono in cmap_mono.items():
        if ucode == 0x3000:
            continue  # Fullwidth space is handled as 1100 UPM from JP

        dest_gname = gname_mono
        if dest_gname in glyf_jp and cmap_jp.get(ucode) != dest_gname:
            dest_gname = f"mono_{gname_mono}"

        rec_pen = DecomposingRecordingPen(glyph_set_mono)
        glyph_set_mono[gname_mono].draw(rec_pen)

        tt_pen = TTGlyphPen(None)
        rec_pen.replay(TransformPen(tt_pen, latin_matrix))

        scaled_glyph = tt_pen.glyph()
        scaled_glyph.recalcBounds(glyf_jp)

        orig_w, orig_lsb = font_mono["hmtx"][gname_mono]
        new_w = HALF_WIDTH  # Strict 550 advance
        new_lsb = int(round(orig_lsb * scale_x))

        glyf_jp[dest_gname] = scaled_glyph
        hmtx_jp[dest_gname] = (new_w, new_lsb)

        if vmtx_jp is not None:
            tsb = 880 - (scaled_glyph.yMax if scaled_glyph.numberOfContours != 0 else 0)
            vmtx_jp.metrics[dest_gname] = (FULL_WIDTH, tsb)

        new_cmap_entries[ucode] = dest_gname

    # Merge alternate glyphs from font_mono (e.g. zero.alt01)
    for gname in ["zero.alt01", "zero.tosf.alt01"]:
        if gname in font_mono["glyf"] and gname not in glyf_jp:
            rec_pen = DecomposingRecordingPen(glyph_set_mono)
            glyph_set_mono[gname].draw(rec_pen)
            tt_pen = TTGlyphPen(None)
            rec_pen.replay(TransformPen(tt_pen, latin_matrix))
            scaled_glyph = tt_pen.glyph()
            scaled_glyph.recalcBounds(glyf_jp)
            orig_w, orig_lsb = font_mono["hmtx"][gname]
            glyf_jp[gname] = scaled_glyph
            hmtx_jp[gname] = (HALF_WIDTH, int(round(orig_lsb * scale_x)))
            if vmtx_jp is not None:
                tsb = 880 - (scaled_glyph.yMax if scaled_glyph.numberOfContours != 0 else 0)
                vmtx_jp.metrics[gname] = (FULL_WIDTH, tsb)

    existing_order = font_jp.getGlyphOrder()
    new_order = existing_order + [
        g for g in new_cmap_entries.values() if g not in existing_order
    ]
    for alt_g in ["zero.alt01", "zero.tosf.alt01"]:
        if alt_g in glyf_jp and alt_g not in new_order:
            new_order.append(alt_g)

    font_jp.setGlyphOrder(new_order)

    for table in font_jp["cmap"].tables:
        if table.isUnicode():
            table.cmap.update(new_cmap_entries)

    font_jp["maxp"].numGlyphs = len(new_order)
    if vhea_jp is not None and vmtx_jp is not None:
        vhea_jp.numOfLongVerMetrics = len(new_order)


def add_cjk_compatibility_mappings(font_jp: TTFont) -> int:
    """Map missing CJK Compatibility Ideographs (U+F900..U+FAFF) to canonical unified ideographs."""
    cmap_jp = font_jp.getBestCmap()
    new_mappings = {}
    for code in range(0xF900, 0xFB00):
        if code in cmap_jp:
            continue
        d = unicodedata.normalize("NFKD", chr(code))
        if len(d) == 1 and ord(d) in cmap_jp:
            new_mappings[code] = cmap_jp[ord(d)]

    for table in font_jp["cmap"].tables:
        if table.isUnicode():
            table.cmap.update(new_mappings)

    return len(new_mappings)


def apply_monospace_metrics(font: TTFont) -> None:
    """Apply terminal and editor compatible monospace metrics:
    - sTypoAscender = 950, sTypoDescender = -225, sTypoLineGap = 0
    - hhea.ascent = 950, hhea.descent = -225, hhea.lineGap = 0
    - usWinAscent = 950, usWinDescent = 225
    - panose.bProportion = 9 (Monospaced)
    - post.isFixedPitch = 0 (duospace standard)
    - remove BASE table to prevent baseline clipping in VS Code and terminals
    """
    os2 = font["OS/2"]
    hhea = font["hhea"]

    os2_ascent = 950
    os2_descent = 225

    os2.sTypoAscender = os2_ascent
    os2.sTypoDescender = -os2_descent
    os2.sTypoLineGap = 0

    hhea.ascent = os2_ascent
    hhea.descent = -os2_descent
    hhea.lineGap = 0

    os2.usWinAscent = os2_ascent
    os2.usWinDescent = os2_descent

    # Set panose proportion to 9 (Monospaced)
    os2.panose.bProportion = 9

    # Set post table duospace flags
    font["post"].isFixedPitch = 0

    # Remove BASE table to prevent baseline clipping issues in VS Code
    if "BASE" in font:
        del font["BASE"]


def build_style(weight: str, italic: bool = False) -> Path:
    """Build a single weight and style of Holon Mono."""
    style_label = f"{weight} Italic" if italic and weight != "Regular" else ("Italic" if italic else weight)
    print(f"=== Building Holon Mono {style_label} ===")

    mono_path, jp_path = get_source_paths(weight, italic)
    font_mono = TTFont(mono_path)
    font_jp = TTFont(jp_path)

    # 1. Transform Japanese glyphs (scale 0.97x, center in 1100 advance cell, 9.0° slant if italic)
    print(f"Transforming Japanese glyphs (advance={FULL_WIDTH}, scale={SCALE_JP}, italic={italic})...")
    transform_japanese_glyphs(font_jp, italic=italic)

    # 2. Add vertical semicolon uniFF1B.vert
    add_vertical_semicolon(font_jp)

    # 3. Merge Latin and symbol glyphs from IBM Plex Mono (advance 550 UPM)
    print(f"Merging Latin glyphs from {mono_path.name} (advance={HALF_WIDTH}, scale_x={SCALE_MONO_X:.4f}, scale_y={SCALE_MONO_Y:.4f})...")
    merge_mono_glyphs(font_jp, font_mono)

    # 4. Map CJK compatibility ideographs
    added_cjk = add_cjk_compatibility_mappings(font_jp)
    if added_cjk > 0:
        print(f"Mapped {added_cjk} CJK compatibility ideographs to canonical forms.")

    # 5. Ensure fullwidth space (U+3000) has exact 1100 UPM advance width
    cmap_best = font_jp.getBestCmap()
    if 0x3000 in cmap_best:
        g_3000 = cmap_best[0x3000]
        font_jp["hmtx"][g_3000] = (FULL_WIDTH, 0)
        if font_jp.get("vmtx") is not None:
            font_jp["vmtx"].metrics[g_3000] = (FULL_WIDTH, 880)

    # 6. Set vendor and style bits
    font_jp["OS/2"].achVendID = b"HLON"
    font_jp["OS/2"].usWeightClass = WEIGHT_VALUES[weight]
    if italic:
        font_jp["OS/2"].fsSelection |= 0x01   # ITALIC
        font_jp["OS/2"].fsSelection &= ~0x40  # Clear REGULAR
        font_jp["head"].macStyle |= 0x02      # Italic
        font_jp["post"].italicAngle = ITALIC_ANGLE
    else:
        font_jp["OS/2"].fsSelection &= ~0x01
        font_jp["head"].macStyle &= ~0x02
        font_jp["post"].italicAngle = 0.0

    if weight == "Bold":
        font_jp["OS/2"].fsSelection |= 0x20   # BOLD
        font_jp["OS/2"].fsSelection &= ~0x40  # Clear REGULAR
        font_jp["head"].macStyle |= 0x01      # Bold

    # 7. Apply monospace metrics & VS Code clipping protection
    apply_monospace_metrics(font_jp)

    # 8. Update font naming records conforming strictly to SIL OFL 1.1
    update_name_table(font_jp, weight, italic)

    # 9. Export final desktop TTF and web WOFF2
    ps_suffix = style_label.replace(" ", "")
    final_ttf_path = OUTPUT_DIR / f"HolonMono-{ps_suffix}.ttf"
    font_jp.save(final_ttf_path)

    final_woff2_path = OUTPUT_DIR / f"HolonMono-{ps_suffix}.woff2"
    ttf_for_woff2 = TTFont(final_ttf_path)
    ttf_for_woff2.flavor = "woff2"
    ttf_for_woff2.save(final_woff2_path)

    print(f"Successfully generated:")
    print(f"  TTF:   {final_ttf_path} ({final_ttf_path.stat().st_size:,} bytes)")
    print(f"  WOFF2: {final_woff2_path} ({final_woff2_path.stat().st_size:,} bytes)")
    return final_ttf_path


def main():
    parser = argparse.ArgumentParser(description="Build Holon Mono font family.")
    parser.add_argument(
        "--weight",
        choices=WEIGHTS + ["all"],
        default="Regular",
        help="Weight to build (default: Regular, or 'all')",
    )
    parser.add_argument(
        "--italic",
        action="store_true",
        help="Build Italic style",
    )
    parser.add_argument(
        "--all-styles",
        action="store_true",
        help="Build all weights and styles (Upright and Italic)",
    )
    args = parser.parse_args()

    if args.all_styles:
        for w in WEIGHTS:
            build_style(w, italic=False)
            build_style(w, italic=True)
    else:
        weights_to_build = WEIGHTS if args.weight == "all" else [args.weight]
        for w in weights_to_build:
            build_style(w, italic=args.italic)


if __name__ == "__main__":
    main()
