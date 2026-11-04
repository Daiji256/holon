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
Merges IBM Plex Sans (Latin/symbols) and IBM Plex Sans JP (Japanese)
with 1.05x scaling adjustment, chws contextual spacing injection,
and complete metadata customization for SIL OFL 1.1 compliance.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import sys
from pathlib import Path
from typing import Optional

from east_asian_spacing import Builder, Config
from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables._c_m_a_p import CmapSubtable

# Constants
SCALE_FACTOR = 1.05  # Scale factor matching IBM Plex Sans JP Latin metrics
FAMILY_NAME = "Holon Sans"
VENDOR_URL = "https://github.com/Daiji256/holon"
COPYRIGHT_STRING = "Copyright 2026 Daiji Suzuki. Copyright 2018 IBM Corp. All rights reserved."
LICENSE_DESCRIPTION = "This Font Software is licensed under the SIL Open Font License, Version 1.1."
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


def get_source_paths(weight: str, italic: bool = False) -> tuple[Path, Path]:
    """Return paths to (plex_sans_ttf, plex_jp_ttf)."""
    if italic:
        sans_style = "Italic" if weight == "Regular" else f"{weight}Italic"
    else:
        sans_style = weight

    sans_name = f"IBMPlexSans-{sans_style}.ttf"
    jp_name = f"IBMPlexSansJP-{weight}.ttf"  # JP has no native italic

    sans_path = UPSTREAM_BASE / "plex-sans" / "fonts" / "complete" / "ttf" / sans_name
    jp_path = UPSTREAM_BASE / "plex-sans-jp" / "fonts" / "complete" / "ttf" / "hinted" / jp_name

    if not sans_path.exists():
        raise FileNotFoundError(f"IBM Plex Sans source not found: {sans_path}")
    if not jp_path.exists():
        raise FileNotFoundError(f"IBM Plex Sans JP source not found: {jp_path}")

    return sans_path, jp_path


def update_name_table(font: TTFont, weight: str, italic: bool) -> None:
    """Update font naming records in the 'name' table."""
    name_table = font["name"]

    style_name = weight
    if italic:
        style_name = f"{weight} Italic" if weight != "Regular" else "Italic"

    # PostScript names cannot contain spaces or special characters
    ps_suffix = style_name.replace(" ", "")
    ps_name = f"HolonSans-{ps_suffix}"
    full_name = f"{FAMILY_NAME} {style_name}"
    unique_id = f"1.000;NONE;{ps_name}"

    # Determine standard 4-style subfamily (Regular, Italic, Bold, Bold Italic)
    if weight == "Bold" and italic:
        subfamily = "Bold Italic"
    elif weight == "Bold":
        subfamily = "Bold"
    elif italic:
        subfamily = "Italic"
    else:
        subfamily = "Regular"

    # Records to set: (nameID, string_value)
    name_records = {
        0: COPYRIGHT_STRING,
        1: FAMILY_NAME,
        2: subfamily,
        3: unique_id,
        4: full_name,
        5: "Version 1.000",
        6: ps_name,
        7: "",  # Clear trademark
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

    # Remove existing conflicting records and apply new ones
    for record in list(name_table.names):
        if record.nameID in name_records:
            name_table.names.remove(record)

    # Add records for Platform 3 (Windows Unicode) and Platform 1 (Macintosh Roman)
    for name_id, val in name_records.items():
        if val:
            name_table.addMultilingualName({"en": val}, nameID=name_id)


def merge_and_scale_glyphs(
    font_jp: TTFont,
    font_sans: TTFont,
    unicodes_to_merge: set[int],
    scale: float = SCALE_FACTOR,
) -> None:
    """Extract glyphs from font_sans for unicodes_to_merge, scale them by scale factor,

    and insert them into font_jp.
    """
    cmap_sans = font_sans.getBestCmap()
    cmap_jp = font_jp.getBestCmap()

    glyf_table_jp = font_jp["glyf"]
    hmtx_table_jp = font_jp["hmtx"]
    vmtx_table_jp = font_jp.get("vmtx")
    vhea_table_jp = font_jp.get("vhea")

    glyph_set_sans = font_sans.getGlyphSet()

    new_cmap_entries = {}

    for ucode in sorted(unicodes_to_merge):
        if ucode not in cmap_sans:
            continue
        gname_sans = cmap_sans[ucode]

        # Use unique name prefix if name exists in JP
        dest_gname = gname_sans
        if dest_gname in glyf_table_jp:
            dest_gname = f"ext_{gname_sans}"

        # Decompose any composite glyphs and scale outline coordinates
        rec_pen = DecomposingRecordingPen(glyph_set_sans)
        glyph_set_sans[gname_sans].draw(rec_pen)

        tt_pen = TTGlyphPen(None)
        t_pen = TransformPen(tt_pen, (scale, 0, 0, scale, 0, 0))
        rec_pen.replay(t_pen)

        scaled_glyph = tt_pen.glyph()
        # Recalculate bounding box
        scaled_glyph.recalcBounds(glyf_table_jp)

        # Scale advance width and LSB
        orig_width, orig_lsb = font_sans["hmtx"][gname_sans]
        new_width = int(round(orig_width * scale))
        new_lsb = int(round(orig_lsb * scale))

        # Add to JP font tables
        glyf_table_jp[dest_gname] = scaled_glyph
        hmtx_table_jp[dest_gname] = (new_width, new_lsb)

        # If vertical metrics exist, compute default vertical metrics
        if vmtx_table_jp is not None:
            # Standard Japanese CJK vertical advance is 1000
            # top side bearing: default baseline origin is 880
            tsb = 880 - (scaled_glyph.yMax if scaled_glyph.numberOfContours != 0 else 0)
            vmtx_table_jp.metrics[dest_gname] = (1000, tsb)

        new_cmap_entries[ucode] = dest_gname

    # Add new glyphs to glyph order
    existing_order = font_jp.getGlyphOrder()
    new_order = existing_order + [
        g for g in new_cmap_entries.values() if g not in existing_order
    ]
    font_jp.setGlyphOrder(new_order)

    # Update vhea numOfLongVerMetrics if present
    if vhea_table_jp is not None and vmtx_table_jp is not None:
        vhea_table_jp.numOfLongVerMetrics = len(new_order)

    # Update cmap subtables
    for table in font_jp["cmap"].tables:
        if table.isUnicode():
            table.cmap.update(new_cmap_entries)

    # Update maxp numGlyphs
    font_jp["maxp"].numGlyphs = len(new_order)


async def apply_chws(input_path: Path, output_path: Path) -> None:
    """Inject chws and vchw OpenType feature rules using east_asian_spacing."""
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

    cmap_sans = font_sans.getBestCmap()
    cmap_jp = font_jp.getBestCmap()

    # Determine which unicodes need to be transferred from Sans to JP
    if italic:
        # For Italic: all ASCII and Latin glyphs from Sans Italic replace JP upright Latin
        # so that Latin is properly italicized while CJK remains upright
        unicodes_to_merge = set(cmap_sans.keys())
    else:
        # For Upright: transfer unicodes that are missing in JP
        unicodes_to_merge = set(cmap_sans.keys()) - set(cmap_jp.keys())

    print(f"Transferring {len(unicodes_to_merge)} glyphs from IBM Plex Sans to JP...")
    merge_and_scale_glyphs(font_jp, font_sans, unicodes_to_merge, scale=SCALE_FACTOR)

    # Set OS/2 weight class and style flags
    font_jp["OS/2"].usWeightClass = WEIGHT_VALUES[weight]
    if italic:
        font_jp["OS/2"].fsSelection |= 0x01  # ITALIC
        font_jp["OS/2"].fsSelection &= ~0x40 # Clear REGULAR
        font_jp["head"].macStyle |= 0x02     # Italic
        font_jp["post"].italicAngle = -11.0
    else:
        font_jp["OS/2"].fsSelection &= ~0x01
        font_jp["head"].macStyle &= ~0x02
        font_jp["post"].italicAngle = 0.0

    if weight == "Bold":
        font_jp["OS/2"].fsSelection |= 0x20  # BOLD
        font_jp["OS/2"].fsSelection &= ~0x40 # Clear REGULAR
        font_jp["head"].macStyle |= 0x01     # Bold

    # Update font naming records
    update_name_table(font_jp, weight, italic)

    # Temporary intermediate font before chws injection
    ps_suffix = style_label.replace(" ", "")
    intermediate_path = Path("tmp") / f"HolonSans-{ps_suffix}.intermediate.ttf"
    font_jp.save(intermediate_path)

    # Inject chws
    final_ttf_path = OUTPUT_DIR / f"HolonSans-{ps_suffix}.ttf"
    print(f"Injecting chws / vchw contextual spacing...")
    asyncio.run(apply_chws(intermediate_path, final_ttf_path))

    # Also export WOFF2 format for web
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
