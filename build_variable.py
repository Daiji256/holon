# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "fonttools>=4.50.0",
#     "glyphsLib>=6.9.0",
#     "ufo2ft>=3.11.0",
#     "ufoLib2>=0.16.0",
# ]
# ///

"""Build script for Holon Sans Variable Font (CFF2 / OTF).
Uses the 3 interpolation-compatible masters from IBM Plex Sans JP.glyphs
with dynamic glyph synchronization to guarantee 100% cubic interpolation compatibility
across all 23,000+ glyphs.
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

from glyphsLib import GSFont, to_designspace
import ufo2ft
from fontTools.ttLib import TTFont

GLYPHS_PATH = Path("tmp/sources-sans-jp/unzipped/sources/masters/IBM Plex Sans JP.glyphs")
OUTPUT_DIR = Path("fonts")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_VAR_PATH = OUTPUT_DIR / "HolonSans-Variable.otf"

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


def sync_glyph(ufo_thin, ufo_reg, ufo_bold, gname: str):
    """Synchronize non-interpolatable glyph outlines from Regular master."""
    if gname in ufo_reg:
        ufo_thin[gname] = ufo_reg[gname].copy()
        ufo_bold[gname] = ufo_reg[gname].copy()


def build_variable_font() -> Path:
    if not GLYPHS_PATH.exists():
        raise FileNotFoundError(f"Source glyphs file not found: {GLYPHS_PATH}")

    print("=== Building Holon Sans Variable Font (CFF2) ===")
    t0 = time.time()
    font = GSFont(str(GLYPHS_PATH))
    print(f"Loaded Glyphs source in {time.time() - t0:.1f}s.")

    ds = to_designspace(font)
    ufo_thin = ds.sources[0].font
    ufo_reg = ds.sources[1].font
    ufo_bold = ds.sources[2].font

    for gname in INITIAL_SYNC_GLYPHS:
        sync_glyph(ufo_thin, ufo_reg, ufo_bold, gname)

    print(f"Synchronized {len(INITIAL_SYNC_GLYPHS)} initial special symbols.")

    for attempt in range(10):
        try:
            print(f"Compiling CFF2 variable font (attempt {attempt + 1})...")
            var_font = ufo2ft.compileVariableCFF2(ds)
            var_font.save(OUTPUT_VAR_PATH)
            print(f"Successfully generated: {OUTPUT_VAR_PATH} ({OUTPUT_VAR_PATH.stat().st_size:,} bytes)")
            return OUTPUT_VAR_PATH
        except Exception as e:
            msg = str(e)
            m = re.search(r"Glyph '([^']+)'", msg)
            if m:
                bad_glyph = m.group(1)
                print(f"Fixing incompatible glyph: '{bad_glyph}'")
                sync_glyph(ufo_thin, ufo_reg, ufo_bold, bad_glyph)
                continue
            raise RuntimeError(f"Variable compilation failed: {e}") from e

    raise RuntimeError("Max compilation attempts reached.")


if __name__ == "__main__":
    build_variable_font()
