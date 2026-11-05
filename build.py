# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "brotli>=1.1.0",
#     "chws-tool>=1.4.0",
#     "fonttools>=4.50.0",
#     "pillow>=10.0.0",
#     "uharfbuzz>=0.39.0",
# ]
# ///

"""Build script for Holon Sans:
- Scales Japanese CJK glyphs to 0.97x (centered in fullwidth box)
- Scales Latin/symbols glyphs to 1.02x (from IBM Plex Sans)
- Applies 11.0 degree italic slant (oblique) to Japanese CJK glyphs in Italic style
- Injects OpenType chws / vchw contextual spacing (with fullwidth space compaction)
- Fully complies with SIL OFL 1.1 metadata and copyright requirements
- Exports desktop TTF and web WOFF2
"""

from __future__ import annotations

import argparse
import asyncio
import math
import sys
import unicodedata
from pathlib import Path

from east_asian_spacing import Builder, Config
from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont

# Scaling and typography constants
SCALE_SANS = 1.02       # Slightly larger Latin
SCALE_JP = 0.97         # Slightly smaller Japanese CJK
JP_CENTER_X = 500.0     # Horizontal center of 1000 UPM
JP_CENTER_Y = 400.0     # Visual center height of CJK ideographs
ITALIC_ANGLE = -11.0    # Matching IBM Plex Sans Italic angle (degrees)

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
        return False  # Keep standard typographic space widths
    if code < 0x02B0:  # Basic Latin, Latin-1, Latin Extended-A/B
        return True
    if 0x0370 <= code <= 0x052F:  # Greek, Cyrillic
        return True
    if 0x200C <= code <= 0x218F:  # Punctuation, Currency, Letterlike, Number Forms
        return True
    if 0x2190 <= code <= 0x23FF:  # Arrows, Math, Technical
        return True
    return False


def get_source_paths(weight: str, italic: bool = False) -> tuple[Path, Path]:
    """Return paths to (plex_sans_ttf, plex_jp_ttf)."""
    if italic:
        sans_style = "Italic" if weight == "Regular" else f"{weight}Italic"
    else:
        sans_style = weight

    sans_name = f"IBMPlexSans-{sans_style}.ttf"
    jp_name = f"IBMPlexSansJP-{weight}.ttf"

    sans_path = UPSTREAM_BASE / "plex-sans" / "fonts" / "complete" / "ttf" / sans_name
    jp_path = UPSTREAM_BASE / "plex-sans-jp" / "fonts" / "complete" / "ttf" / "hinted" / jp_name

    if not sans_path.exists():
        raise FileNotFoundError(f"IBM Plex Sans source not found: {sans_path}")
    if not jp_path.exists():
        raise FileNotFoundError(f"IBM Plex Sans JP source not found: {jp_path}")

    return sans_path, jp_path


def update_name_table(font: TTFont, weight: str, italic: bool) -> None:
    """Update font naming records in the 'name' table conforming strictly to SIL OFL 1.1."""
    name_table = font["name"]

    style_name = weight
    if italic:
        style_name = f"{weight} Italic" if weight != "Regular" else "Italic"

    ps_suffix = style_name.replace(" ", "")
    ps_name = f"HolonSans-{ps_suffix}"
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
    """Add uniFF1B.vert (rotated 90° CW around (500, 378)) and update vert/vrt2 in GSUB."""
    glyf = font_jp["glyf"]
    hmtx = font_jp["hmtx"]
    vmtx = font_jp.get("vmtx")

    if "uniFF1B" not in glyf or "uniFF1B.vert" in glyf:
        return

    # Draw uniFF1B with 90° CW rotation around (500, 378)
    # x' = y + 122
    # y' = 878 - x
    glyph_set = font_jp.getGlyphSet()
    rec_pen = DecomposingRecordingPen(glyph_set)
    glyph_set["uniFF1B"].draw(rec_pen)

    tt_pen = TTGlyphPen(None)
    t_pen = TransformPen(tt_pen, (0.0, -1.0, 1.0, 0.0, 122.0, 878.0))
    rec_pen.replay(t_pen)

    new_glyph = tt_pen.glyph()
    new_glyph.recalcBounds(glyf)

    glyf["uniFF1B.vert"] = new_glyph
    hmtx["uniFF1B.vert"] = (1000, new_glyph.xMin)

    if vmtx is not None:
        tsb = 880 - (new_glyph.yMax if new_glyph.numberOfContours != 0 else 0)
        vmtx.metrics["uniFF1B.vert"] = (1000, tsb)

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


def transform_cjk_glyphs(
    font_jp: TTFont,
    italic: bool,
    scale: float = SCALE_JP,
) -> None:
    """Scale Japanese CJK glyphs to scale (0.97x) with center pivot (500, 400).
    In Italic mode, also apply 11.0 degree shear (slant).
    """
    cmap_jp = font_jp.getBestCmap()
    glyf_table = font_jp["glyf"]
    glyph_set = font_jp.getGlyphSet()

    # Find glyph names for CJK/Japanese characters
    cjk_gnames = set()
    for code, gname in cmap_jp.items():
        if not is_latin_or_symbol(code):
            cjk_gnames.add(gname)

    # Include vertical punctuation alternates so they are scaled and slanted consistently
    for gname in ["uniFF1A.vert", "uniFF1B.vert"]:
        if gname in glyf_table:
            cjk_gnames.add(gname)

    # Compute transformation matrix
    # Center pivot (cx, cy) = (500, 400)
    dx = JP_CENTER_X * (1.0 - scale)
    dy = JP_CENTER_Y * (1.0 - scale)

    if italic:
        slant = math.tan(math.radians(-ITALIC_ANGLE))  # 11.0 degrees
        # Combined matrix: M_slant * M_scale with pivot cy
        # x'' = scale*x + (scale*slant)*y + dx + (dy - cy)*slant
        # y'' = scale*y + dy
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
        if orig_glyph.numberOfContours == 0:
            continue

        rec_pen = DecomposingRecordingPen(glyph_set)
        glyph_set[gname].draw(rec_pen)

        tt_pen = TTGlyphPen(None)
        t_pen = TransformPen(tt_pen, matrix)
        rec_pen.replay(t_pen)

        new_glyph = tt_pen.glyph()
        new_glyph.recalcBounds(glyf_table)
        glyf_table[gname] = new_glyph


def merge_sans_glyphs(
    font_jp: TTFont,
    font_sans: TTFont,
    scale: float = SCALE_SANS,
) -> None:
    """Extract all Latin/symbol glyphs from font_sans, scale by 1.02x, and insert into font_jp."""
    cmap_sans = font_sans.getBestCmap()
    cmap_jp = font_jp.getBestCmap()

    glyf_jp = font_jp["glyf"]
    hmtx_jp = font_jp["hmtx"]
    vmtx_jp = font_jp.get("vmtx")
    vhea_jp = font_jp.get("vhea")

    glyph_set_sans = font_sans.getGlyphSet()

    new_cmap_entries = {}

    for ucode, gname_sans in cmap_sans.items():
        dest_gname = gname_sans
        # If gname exists in JP and belongs to a different char, give unique name
        if dest_gname in glyf_jp and cmap_jp.get(ucode) != dest_gname:
            dest_gname = f"ext_{gname_sans}"

        rec_pen = DecomposingRecordingPen(glyph_set_sans)
        glyph_set_sans[gname_sans].draw(rec_pen)

        tt_pen = TTGlyphPen(None)
        t_pen = TransformPen(tt_pen, (scale, 0.0, 0.0, scale, 0.0, 0.0))
        rec_pen.replay(t_pen)

        scaled_glyph = tt_pen.glyph()
        scaled_glyph.recalcBounds(glyf_jp)

        orig_w, orig_lsb = font_sans["hmtx"][gname_sans]
        if ucode in (0x2001, 0x2003, 0x3000):
            new_w = 1000
            new_lsb = 0
        elif ucode in (0x2000, 0x2002):
            new_w = 500
            new_lsb = 0
        else:
            new_w = int(round(orig_w * scale))
            new_lsb = int(round(orig_lsb * scale))

        glyf_jp[dest_gname] = scaled_glyph
        hmtx_jp[dest_gname] = (new_w, new_lsb)

        if vmtx_jp is not None:
            tsb = 880 - (scaled_glyph.yMax if scaled_glyph.numberOfContours != 0 else 0)
            vmtx_jp.metrics[dest_gname] = (1000, tsb)

        new_cmap_entries[ucode] = dest_gname

    existing_order = font_jp.getGlyphOrder()
    new_order = existing_order + [
        g for g in new_cmap_entries.values() if g not in existing_order
    ]
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


def install_enhanced_chws() -> None:
    """Enhance east_asian_spacing GlyphSets with comprehensive JIS X 4051 yakumono rules:
    - Middle dots and colons/semicolons (・：；) adjacent to each other compacted to half_em (360 UPM gap)
    - Middle dots and colons adjacent to opening brackets compacted to quad_em (250 UPM gap)
    - Middle dots and colons adjacent to closing brackets compacted to quad_em (250 UPM gap)
    - Middle dots and colons adjacent to fullwidth space compacted to 1.0 em total
    - Fullwidth colon (：) followed by ASCII space compacted to avoid redundant gap
    - Vertical flow (vchw) applies exact matching vertical rules
    """
    from east_asian_spacing.spacing import (
        GlyphSets, Font,
        PairPosBuilder, SinglePosBuilder, ChainContextPosBuilder, ChainContextualRule
    )
    from fontTools.otlLib.builder import buildValue

    def custom_build_chws_lookup(self, font: Font, lookups, pos: GlyphSets.PosValues):
        self.assert_font(font)
        lookup_indices = []
        ttfont = font.ttfont
        glyph_order = set(ttfont.getGlyphOrder())
        em = font.fullwidth_advance
        half_em = math.floor(em / 2)
        quad_em = math.floor(half_em / 2)

        # In vertical flow, ensure uniFF1B and uniFF1B.vert are recognized in pos.middle
        if font.is_vertical:
            for g in ("uniFF1B.vert", "uniFF1B"):
                if g in glyph_order and g not in pos.middle:
                    pos.middle = pos.middle + (g,)

        if font.is_vertical:
            half_left_val = buildValue({"YAdvance": -half_em})
            quad_left_val = buildValue({"YAdvance": -quad_em})
            half_right_val = buildValue({"YPlacement": half_em, "YAdvance": -half_em})
            quad_right_val = buildValue({"YPlacement": quad_em, "YAdvance": -quad_em})
        else:
            half_left_val = buildValue({"XAdvance": -half_em})
            quad_left_val = buildValue({"XAdvance": -quad_em})
            half_right_val = buildValue({"XPlacement": -half_em, "XAdvance": -half_em})
            quad_right_val = buildValue({"XPlacement": -quad_em, "XAdvance": -quad_em})

        # 1. Type 2 Pair Positioning (adjust 1st glyph)
        pair_pos_builder = PairPosBuilder(ttfont, None)

        # Rule 1a: left (closing brackets, comma, period) followed by left, right, middle, space
        pair_pos_builder.addClassPair(
            None, pos.left, half_left_val,
            pos.left + pos.right + pos.middle + pos.space + pos.na_left, None
        )

        # Rule 1b: middle (・：；) followed by middle (・：；) -> compact 1st middle by half_em
        if pos.middle:
            pair_pos_builder.addClassPair(
                None, pos.middle, half_left_val,
                pos.middle, None
            )

            # Rule 1c: middle (・：；) followed by space (　) -> compact 1st middle by half_em
            if pos.space:
                pair_pos_builder.addClassPair(
                    None, pos.middle, half_left_val,
                    pos.space, None
                )

            # Rule 1d: middle (・：；) followed by left (closing brackets) -> compact middle by quad_em (四分アキ)
            if pos.left:
                pair_pos_builder.addClassPair(
                    None, pos.middle, quad_left_val,
                    pos.left, None
                )

        # Rule 1e: colon followed by ASCII space
        if "uniFF1A" in glyph_order and "space" in glyph_order:
            pair_pos_builder.addGlyphPair(
                None, "uniFF1A", half_left_val,
                "space", None
            )
        if "uniFF1A.vert" in glyph_order and "space" in glyph_order:
            pair_pos_builder.addGlyphPair(
                None, "uniFF1A.vert", half_left_val,
                "space", None
            )
        if "uniFF1B.vert" in glyph_order and "space" in glyph_order:
            pair_pos_builder.addGlyphPair(
                None, "uniFF1B.vert", half_left_val,
                "space", None
            )

        lookup = pair_pos_builder.build()
        assert lookup
        lookup_indices.append(len(lookups))
        lookups.append(lookup)

        # 2. Single Pos Lookups for chaining context (adjust 2nd glyph)
        single_pos_lookup_right = self._build_single_pos_lookup(
            font, lookups, ((pos.right, half_right_val),)
        )
        single_pos_lookup_mid_half = self._build_single_pos_lookup(
            font, lookups, ((pos.middle, half_right_val),)
        )
        single_pos_lookup_mid_quad = self._build_single_pos_lookup(
            font, lookups, ((pos.middle, quad_right_val),)
        )

        # 3. Type 8 Chain Contextual Positioning
        chain_builder = ChainContextPosBuilder(ttfont, None)

        # Rule 2a: right opening bracket after right, middle, space
        chain_builder.rules.append(
            ChainContextualRule(
                [pos.right + pos.middle + pos.space + pos.na_right],
                [pos.right], [], [[single_pos_lookup_right]]
            )
        )

        # Rule 2b: middle after opening bracket -> shift middle by quad_em (四分アキ)
        if pos.right and pos.middle:
            chain_builder.rules.append(
                ChainContextualRule(
                    [pos.right],
                    [pos.middle], [], [[single_pos_lookup_mid_quad]]
                )
            )

        # Rule 2c: middle after fullwidth space -> shift middle by half_em
        if pos.space and pos.middle:
            chain_builder.rules.append(
                ChainContextualRule(
                    [pos.space],
                    [pos.middle], [], [[single_pos_lookup_mid_half]]
                )
            )

        lookup2 = chain_builder.build()
        assert lookup2
        lookup_indices.append(len(lookups))
        lookups.append(lookup2)

        return lookup_indices

    GlyphSets._build_chws_lookup = custom_build_chws_lookup


async def apply_chws(input_path: Path, output_path: Path) -> None:
    """Inject chws and vchw OpenType feature rules using east_asian_spacing with enhanced JIS X 4051 rules."""
    install_enhanced_chws()
    config = Config.default.clone()
    config.fullwidth_advance = 1000
    builder = Builder(str(input_path), config=config)
    res = await builder.build_and_save(output_path)
    if not res:
        raise RuntimeError(f"Failed to inject chws into {input_path}")


def build_style(weight: str, italic: bool = False) -> Path:
    """Build one font variant (e.g. Regular or Bold Italic)."""
    style_label = f"{weight} Italic" if italic else weight
    print(f"\n--- Building Holon Sans {style_label} ---")

    sans_path, jp_path = get_source_paths(weight, italic)
    font_sans = TTFont(sans_path)
    font_jp = TTFont(jp_path)

    # 0. Add vertical semicolon (uniFF1B.vert) before CJK transform so it scales/slants consistently
    add_vertical_semicolon(font_jp)

    # 1. Transform Japanese CJK glyphs (0.97x scale + optional 11° slant)
    print(f"Transforming CJK glyphs (scale={SCALE_JP}, italic={italic})...")
    transform_cjk_glyphs(font_jp, italic=italic, scale=SCALE_JP)

    # 2. Extract and scale Latin/symbols from IBM Plex Sans (1.02x scale)
    print(f"Merging Latin/symbol glyphs from IBM Plex Sans (scale={SCALE_SANS})...")
    merge_sans_glyphs(font_jp, font_sans, scale=SCALE_SANS)

    # 3. Add safe CJK Compatibility Ideographs mappings
    num_compat = add_cjk_compatibility_mappings(font_jp)
    print(f"Mapped {num_compat} CJK compatibility ideographs to canonical unified glyphs.")

    # 3. Set OS/2 weight class and style flags
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

    # 4. Update font naming records conforming strictly to SIL OFL 1.1
    update_name_table(font_jp, weight, italic)

    # 4.5 Ensure fullwidth space (U+3000) has exact 1000 UPM advance width
    cmap_best = font_jp.getBestCmap()
    if 0x3000 in cmap_best:
        g_3000 = cmap_best[0x3000]
        font_jp["hmtx"][g_3000] = (1000, 0)
        if font_jp.get("vmtx") is not None:
            font_jp["vmtx"].metrics[g_3000] = (1000, 880)

    # 5. Temporary intermediate font before chws injection
    ps_suffix = style_label.replace(" ", "")
    intermediate_path = Path("tmp") / f"HolonSans-{ps_suffix}.intermediate.ttf"
    font_jp.save(intermediate_path)

    # 6. Inject chws / vchw contextual spacing
    final_ttf_path = OUTPUT_DIR / f"HolonSans-{ps_suffix}.ttf"
    print(f"Injecting chws / vchw contextual spacing...")
    asyncio.run(apply_chws(intermediate_path, final_ttf_path))

    # 7. Also export WOFF2 format for web
    final_woff2_path = OUTPUT_DIR / f"HolonSans-{ps_suffix}.woff2"
    ttf_for_woff2 = TTFont(final_ttf_path)
    ttf_for_woff2.flavor = "woff2"
    ttf_for_woff2.save(final_woff2_path)

    # Clean intermediate
    if intermediate_path.exists():
        intermediate_path.unlink()

    print(f"Successfully generated:")
    print(f"  TTF:   {final_ttf_path} ({final_ttf_path.stat().st_size:,} bytes)")
    print(f"  WOFF2: {final_woff2_path} ({final_woff2_path.stat().st_size:,} bytes)")
    return final_ttf_path


def main():
    parser = argparse.ArgumentParser(description="Build Holon Sans font family.")
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
