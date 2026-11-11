# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "brotli>=1.1.0",
#     "cffsubr>=0.3.0",
#     "fonttools>=4.50.0",
# ]
# ///

"""Holon Font Subsetter.

Subsets Holon Sans and Holon Mono (both Static and Variable, Upright and Italic)
to a curated, lightweight character set:
- Joyo Kanji (2,136 characters)
- Basic Latin (ASCII: 95 characters)
- Latin-1 Supplement (Accented Latin & European characters: 96 characters)
- Hiragana (full set with voiced/semi-voiced & iteration marks)
- Katakana (full set with voiced/semi-voiced, prolong mark & middle dot)
- Essential CJK punctuation, brackets & typographical symbols
- Mathematical, currency, optical & UI symbols (including ∞, ·, ±, ×, ÷, EV, °)
- UI navigation arrows and geometric shapes (←, →, ↑, ↓, ▲, ▼, ■, ●, etc.)

Generates both Desktop (TTF/OTF) and Web (WOFF2) formats.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import os
import shutil
import sys
import time
from pathlib import Path

import cffsubr
from fontTools.otlLib.optimize import compact as compact_otl
from fontTools.subset import Options as SubsetOptions, Subsetter
from fontTools.ttLib import TTFont, newTable

# Safe OpenType layout features for Monospace to prevent advance width distortion
MONO_SAFE_FEATURES = [
    "ccmp", "locl", "vert", "vrt2", "vkna", "hkna", "jp78", "jp83", "jp90",
    "nlck", "trad", "hojo", "expt", "ruby", "fwid", "zero", "ss01", "ss02", "ss03", "ss04",
]


def load_subset_unicodes(chars_file: Path) -> set[int]:
    """Load unicode code points from character file."""
    if not chars_file.exists():
        raise FileNotFoundError(f"Character file not found: {chars_file}")
    with open(chars_file, "r", encoding="utf-8") as f:
        content = f.read()
    unicodes = {ord(c) for c in content}
    # Ensure ASCII space is included
    unicodes.add(0x0020)
    return unicodes


def subset_single_font(
    src_path: Path,
    out_dir: Path,
    unicodes: set[int],
) -> tuple[str, int, int, int]:
    """Subset a single font file into desktop and WOFF2 formats.

    Returns (filename, orig_bytes, desktop_bytes, woff2_bytes).
    """
    is_mono = "Mono" in src_path.name
    is_variable = "Variable" in src_path.name

    out_name = src_path.name
    out_desktop = out_dir / out_name
    out_woff2 = out_dir / (src_path.stem + ".woff2")

    font = TTFont(src_path)

    opts = SubsetOptions()
    opts.layout_features = MONO_SAFE_FEATURES if is_mono else ["*"]
    opts.name_IDs = ["*"]
    opts.name_languages = ["*"]
    opts.notdef_outline = True
    opts.glyph_names = False
    opts.hinting = False
    opts.drop_tables += ["DSIG", "meta"]

    subsetter = Subsetter(options=opts)
    subsetter.populate(unicodes=unicodes)
    subsetter.subset(font)

    # Re-inject clean language metadata
    meta = newTable("meta")
    meta.data = {"dlng": "Jpan, Latn", "slng": "Jpan, Latn"}
    font["meta"] = meta

    if out_desktop.suffix == ".ttf":
        gasp = newTable("gasp")
        gasp.gaspRange = {0xFFFF: 15}
        font["gasp"] = gasp
        if "glyf" in font:
            glyf = font["glyf"]
            if outlined := [glyf[g] for g in font.getGlyphOrder() if getattr(glyf[g], "numberOfContours", 0) != 0]:
                font["head"].yMax, font["head"].yMin = max(g.yMax for g in outlined), min(g.yMin for g in outlined)
        if is_mono:
            font["OS/2"].usWinAscent = max(950, font["head"].yMax)
            font["OS/2"].usWinDescent = max(225, -font["head"].yMin)

    if "GPOS" in font:
        compact_otl(font, level=7)

    # Export WOFF2
    font.flavor = "woff2"
    font.save(out_woff2)
    font.flavor = None

    # Subroutinize CFF / CFF2 for maximum compression
    if "CFF2" in font or "CFF " in font:
        cffsubr.subroutinize(font)

    # Export Desktop
    font.save(out_desktop)

    orig_sz = src_path.stat().st_size
    desk_sz = out_desktop.stat().st_size
    woff_sz = out_woff2.stat().st_size

    return out_name, orig_sz, desk_sz, woff_sz


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate subset fonts for Holon Sans and Holon Mono.")
    parser.add_argument("--input-dir", type=Path, default=Path("fonts"), help="Input fonts directory (default: fonts)")
    parser.add_argument("--output-dir", type=Path, default=Path("fonts/subset"), help="Output directory (default: fonts/subset)")
    parser.add_argument("--chars-file", type=Path, default=Path("subset_chars.txt"), help="Character list file (default: subset_chars.txt)")
    parser.add_argument("--pattern", type=str, default="", help="Filter fonts matching pattern (e.g. 'Regular', 'Variable')")
    parser.add_argument("--workers", type=int, default=os.cpu_count() or 4, help="Number of parallel worker processes")
    args = parser.parse_args()

    if not args.input_dir.exists():
        print(f"Error: Input directory {args.input_dir} does not exist.", file=sys.stderr)
        sys.exit(1)

    unicodes = load_subset_unicodes(args.chars_file)
    print(f"Loaded {len(unicodes):,} target characters from {args.chars_file}")

    args.output_dir.mkdir(parents=True, exist_ok=True)

    # Copy license if available
    ofl_src = args.input_dir / "OFL.txt"
    if ofl_src.exists():
        shutil.copy2(ofl_src, args.output_dir / "OFL.txt")

    # Collect source fonts (*.ttf and *.otf)
    candidates = sorted([
        p for p in args.input_dir.iterdir()
        if p.is_file() and p.suffix in (".ttf", ".otf")
    ])

    if args.pattern:
        candidates = [p for p in candidates if args.pattern in p.name]

    if not candidates:
        print(f"No matching font files found in {args.input_dir}.", file=sys.stderr)
        sys.exit(1)

    print(f"Subsetting {len(candidates)} font files to {args.output_dir} using {args.workers} workers...")
    t0 = time.time()

    results: list[tuple[str, int, int, int]] = []
    with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(subset_single_font, src, args.output_dir, unicodes): src
            for src in candidates
        }
        for future in concurrent.futures.as_completed(futures):
            res = future.result()
            results.append(res)
            name, orig_sz, desk_sz, woff_sz = res
            pct = (1.0 - desk_sz / orig_sz) * 100
            print(f"  [OK] {name:32s}: {orig_sz/1024/1024:5.2f} MB -> {desk_sz/1024/1024:5.2f} MB ({pct:5.1f}% off) | WOFF2: {woff_sz/1024/1024:5.2f} MB")

    results.sort(key=lambda x: x[0])
    elapsed = time.time() - t0

    tot_orig = sum(r[1] for r in results)
    tot_desk = sum(r[2] for r in results)
    tot_woff = sum(r[3] for r in results)
    tot_pct = (1.0 - tot_desk / tot_orig) * 100

    print("\n" + "=" * 80)
    print(f"Subsetting complete in {elapsed:.1f}s!")
    print(f"Total Desktop Size: {tot_orig/1024/1024:.1f} MB -> {tot_desk/1024/1024:.1f} MB ({tot_pct:.1f}% reduction)")
    print(f"Total WOFF2 Size:   {tot_woff/1024/1024:.1f} MB")
    print(f"Output directory:   {args.output_dir}")
    print("=" * 80)


if __name__ == "__main__":
    main()
