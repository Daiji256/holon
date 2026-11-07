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

"""Unified build script for Holon Sans (Static & Variable) and Holon Mono.

Features:
- Automatic upstream download pinned by immutable Git commit hash & release tags with SHA-256 verification
- Holon Sans: Dual-scale (Japanese CJK 0.97x, Latin/symbols 1.02x), 11.0° Italic, JIS X 4051 chws/vchw
- Holon Sans Variable: 2-file Variable Fonts (Roman & Italic) with wght (100..700) and GRAD (-100..+100)
- Holon Mono: Strict 2:1 duospace (550 / 1100 UPM), 9.0° Italic, box-drawing alignment, terminal metrics
- Subsetter & post format 3.0 optimization removing unreferenced glyphs and redundant tables
- Strict compliance with SIL OFL 1.1 metadata and naming requirements
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import math
import re
import time
import unicodedata
import urllib.request
import zipfile
from pathlib import Path

from east_asian_spacing import Builder, Config
from fontTools.designspaceLib import (
    AxisDescriptor,
    DesignSpaceDocument,
    InstanceDescriptor,
    SourceDescriptor,
)
from fontTools.otlLib.builder import buildStatTable, buildValue
from fontTools.pens.recordingPen import DecomposingRecordingPen, DecomposingRecordingPointPen
from fontTools.pens.transformPen import TransformPen, TransformPointPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.subset import Options as SubsetOptions, Subsetter
from fontTools.ttLib import TTFont
from glyphsLib import GSFont, to_designspace
import ufo2ft
import ufoLib2

# ---------------------------------------------------------------------------
# Constants & Metadata
# ---------------------------------------------------------------------------

SANS_FAMILY = "Holon Sans"
MONO_FAMILY = "Holon Mono"
VENDOR_ID = "HLON"
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
SANS_ITALIC_ANGLE = -11.0

HALF_WIDTH = 550
FULL_WIDTH = 1100
SCALE_MONO_X = HALF_WIDTH / 600.0
SCALE_MONO_Y = 0.98
MONO_JP_OFFSET_X = (FULL_WIDTH - 1000.0 * SCALE_JP) / 2.0  # 65.0
MONO_JP_OFFSET_Y = JP_CENTER_Y * (1.0 - SCALE_JP)          # 12.0
MONO_ITALIC_ANGLE = -9.0

WEIGHTS = ["Thin", "ExtraLight", "Light", "Regular", "Text", "Medium", "SemiBold", "Bold"]
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

# Fullwidth Japanese punctuation in U+2000..U+23FF that must remain 1000 UPM in Holon Sans
JP_FULLWIDTH_SYMBOLS = {0x2015, 0x2025, 0x2026, 0x2103}

# Safe GSUB features for Holon Mono (excluding proportional/ligature features)
MONO_SAFE_FEATURES = [
    "vert", "vrt2", "vkna", "hkna", "jp78", "jp83", "jp90",
    "nlck", "trad", "hojo", "expt", "ruby", "fwid", "zero",
    "ss01", "ss02", "ss03", "ss04",
]

OUTPUT_DIR = Path("fonts")
TMP_DIR = Path("tmp")

# ---------------------------------------------------------------------------
# Pinned Upstream Commit Hash, Release Tags & SHA-256 Checksums
# ---------------------------------------------------------------------------

UPSTREAM_PLEX_COMMIT = "71f558992315a12ca1f06a2215d57962a1992162"

TTF_SHA256: dict[str, str] = {
    # IBM Plex Sans (16 styles)
    "plex-sans/fonts/complete/ttf/IBMPlexSans-Thin.ttf": "d2fdd87b43039f5e05c7749b6b7937837d074bbf14af2d26dba09b67abf6aca1",
    "plex-sans/fonts/complete/ttf/IBMPlexSans-ThinItalic.ttf": "e1056650d0a4511372fa44f539a65c92e2ede7fe19ff5560c05e4490275c41a8",
    "plex-sans/fonts/complete/ttf/IBMPlexSans-ExtraLight.ttf": "c13105ca8fb60874c8db103e8ff058f0dfa0e2194e20ee5c9b0f8b7dd5e1fe85",
    "plex-sans/fonts/complete/ttf/IBMPlexSans-ExtraLightItalic.ttf": "b8a4390ab03889949e6621f7ad635b459c0e520db70fccd833034103b6cf6d3f",
    "plex-sans/fonts/complete/ttf/IBMPlexSans-Light.ttf": "2218b5f3f1fc9d3a793343f45c3be5ee7eae9584a7a52391bb8cf2d37622b3e0",
    "plex-sans/fonts/complete/ttf/IBMPlexSans-LightItalic.ttf": "54ad6d58d163b6b1f850fcbab3c46a1ed6c1ec3050524abb904c076a52c6bb1a",
    "plex-sans/fonts/complete/ttf/IBMPlexSans-Regular.ttf": "975dcda37d80f038dcd143c22e33ca2d97a0cc5a929aace1c749153b0fe1afa5",
    "plex-sans/fonts/complete/ttf/IBMPlexSans-Italic.ttf": "a9c6ef9942c49e49d11e11a6dacc0b3a087978757e9b22a06b8ac22a6400fb15",
    "plex-sans/fonts/complete/ttf/IBMPlexSans-Text.ttf": "4abc4919d313b56a5e3ffdb249ed2450392a5df21478aa4e25ff23901398b1fb",
    "plex-sans/fonts/complete/ttf/IBMPlexSans-TextItalic.ttf": "622e67ffee610160f135c3636825625095cb112b83275ee88752648fad56d89c",
    "plex-sans/fonts/complete/ttf/IBMPlexSans-Medium.ttf": "331c8639d7598b2cde62a911a71db195e30cb655cd6bdf2e324a7e984955f907",
    "plex-sans/fonts/complete/ttf/IBMPlexSans-MediumItalic.ttf": "9928852bf60d82fdbbfe30eac86bcecd611e4188f0fa4d98938560659fa99c64",
    "plex-sans/fonts/complete/ttf/IBMPlexSans-SemiBold.ttf": "a20caf8286023a6a7a85e40b1d2a4ae9fc3e3b1f9eda8f4c542dd4986af67bb1",
    "plex-sans/fonts/complete/ttf/IBMPlexSans-SemiBoldItalic.ttf": "147106b619423a82b40f6d64bace074ad5b786e59f48023bda69d63b1755fb82",
    "plex-sans/fonts/complete/ttf/IBMPlexSans-Bold.ttf": "9e6c74a889a700d707613d24548fe4ffa6bc59559a0689d2cf9e133bdcdafb2f",
    "plex-sans/fonts/complete/ttf/IBMPlexSans-BoldItalic.ttf": "0e3142ba2ef31fe5c02f0c6c36424f251609cd6b73880076e21c2e81931ba2b9",
    # IBM Plex Mono (16 styles)
    "plex-mono/fonts/complete/ttf/IBMPlexMono-Thin.ttf": "171c32cbb133646b6d5e16d0ffbbd39f1ade134932d8a21cefc61e1669fd072e",
    "plex-mono/fonts/complete/ttf/IBMPlexMono-ThinItalic.ttf": "9bb7624f34ec3f7443ce1189b94f0c4321360c6beb846f4bc618daa194ce5ed3",
    "plex-mono/fonts/complete/ttf/IBMPlexMono-ExtraLight.ttf": "4b6acddc27bf7b98c5d28764d0617fc76b7f34c403583145237356e738327c54",
    "plex-mono/fonts/complete/ttf/IBMPlexMono-ExtraLightItalic.ttf": "cd88e7df6e06b14bce0ce8a4b4530cc6791e3d27e8b6955bf553158200559f02",
    "plex-mono/fonts/complete/ttf/IBMPlexMono-Light.ttf": "feca3787130b6e71a0edb1cfc17c2ae7780443888554207a8981de43ef755d36",
    "plex-mono/fonts/complete/ttf/IBMPlexMono-LightItalic.ttf": "eaf46dcb971a93849643c9f1249bbaf9abf92d712227ff6ce68ef48dc3df69e6",
    "plex-mono/fonts/complete/ttf/IBMPlexMono-Regular.ttf": "7c6fbddca4b700be918f5f6183d9bd4464fa427fe435f0b480d77fe2bb8c5a43",
    "plex-mono/fonts/complete/ttf/IBMPlexMono-Italic.ttf": "a55368deb953f594ac18336a1029009ed820e2d9abbb57ad601f61e22bec072b",
    "plex-mono/fonts/complete/ttf/IBMPlexMono-Text.ttf": "bb43e352f1d4aeedfd9e2e33449660a2b9473010d57a6013ceff976242ea5456",
    "plex-mono/fonts/complete/ttf/IBMPlexMono-TextItalic.ttf": "bdfc5b6ea2ffba1880313c73773630c85fa3a6e56d7f7a777da52702e7d65532",
    "plex-mono/fonts/complete/ttf/IBMPlexMono-Medium.ttf": "98fbd727aae340b236955879dabed4d991aac9e8e90b3b2a67ce4a59221cc97c",
    "plex-mono/fonts/complete/ttf/IBMPlexMono-MediumItalic.ttf": "100852349a441076bb03aca3a3c7786eaf5d59a91dca3e4677ee8337805817fb",
    "plex-mono/fonts/complete/ttf/IBMPlexMono-SemiBold.ttf": "f04d7c488ddf7d1fa99f2574efc3406ea4cbe17bb1af3a1ab960f84d0c96a172",
    "plex-mono/fonts/complete/ttf/IBMPlexMono-SemiBoldItalic.ttf": "d2039ddfa9236d642fafae5aa46446c54eb7961b3771a1ca3e9bba960172b9bb",
    "plex-mono/fonts/complete/ttf/IBMPlexMono-Bold.ttf": "74e5eedcfa4596497d34e19023cabdabd3a8c852b903007a5654a59591a72ffb",
    "plex-mono/fonts/complete/ttf/IBMPlexMono-BoldItalic.ttf": "c8b00068fd2fd69bbcf62059148623f09d19e9ada8bf9e8caf1aedd01347046a",
    # IBM Plex Sans JP unhinted (8 weights)
    "plex-sans-jp/fonts/complete/ttf/unhinted/IBMPlexSansJP-Thin.ttf": "aa28c0a68a8040c7082a85d34b1fef0e31d726cfc904db1ac542b349797a71e9",
    "plex-sans-jp/fonts/complete/ttf/unhinted/IBMPlexSansJP-ExtraLight.ttf": "40ed45b01a733c0c797017a9b5498a4a4d05cdb3beb09eb78010dc7d74a1555f",
    "plex-sans-jp/fonts/complete/ttf/unhinted/IBMPlexSansJP-Light.ttf": "6d265357c213600e1f129b5662d474b266a163564205cbdb8e0bb9b0fc2b5c70",
    "plex-sans-jp/fonts/complete/ttf/unhinted/IBMPlexSansJP-Regular.ttf": "0168493ae143d16e4c0d374c090b1ee5eab9ee475536d2e429368dbcfc4a6abe",
    "plex-sans-jp/fonts/complete/ttf/unhinted/IBMPlexSansJP-Text.ttf": "34d906500faca7a7995eddc5171ef2b04813bc809b7125d8525ca54ea2a5cb60",
    "plex-sans-jp/fonts/complete/ttf/unhinted/IBMPlexSansJP-Medium.ttf": "ed9257c94b0a540bac56a0faa70ec554b18ea7271fa4f0d33512583dd4bf9c0c",
    "plex-sans-jp/fonts/complete/ttf/unhinted/IBMPlexSansJP-SemiBold.ttf": "3ae17af73062926b013afdec8949923a8adfd4ec8c4f689876c0a359e63e4ceb",
    "plex-sans-jp/fonts/complete/ttf/unhinted/IBMPlexSansJP-Bold.ttf": "070c08915b21a9484e31a73594e4aae69991e4477959a96a6ab4031f4e30ec9f",
}

ZIP_SOURCES = {
    "sans-jp": {
        "tag": "@ibm/plex-sans-jp@3.0.0",
        "url": "https://github.com/IBM/plex/releases/download/%40ibm/plex-sans-jp%403.0.0/sources.zip",
        "sha256": "4ac6374873b634a9dc19cd2b8f40e9acfe55ea37c269c08c0dcdb9b2abdce3de",
        "zip_path": TMP_DIR / "sources-sans-jp" / "sources.zip",
        "extract_dir": TMP_DIR / "sources-sans-jp" / "unzipped",
        "target_path": TMP_DIR / "sources-sans-jp" / "unzipped" / "sources" / "masters" / "IBM Plex Sans JP.glyphs",
    },
    "sans": {
        "tag": "@ibm/plex-sans@1.1.0",
        "url": "https://github.com/IBM/plex/releases/download/%40ibm/plex-sans%401.1.0/sources.zip",
        "sha256": "a9ac380518b3e6b91409e65ea3274d7f7d19db9b474507c66750287c7b4d614d",
        "zip_path": TMP_DIR / "sources-sans" / "sources.zip",
        "extract_dir": TMP_DIR / "sources-sans" / "unzipped",
        "target_path": TMP_DIR / "sources-sans" / "unzipped" / "sources" / "masters" / "IBM Plex Sans-Regular.ufo",
    },
    "mono-variable": {
        "tag": "@ibm/plex-mono-variable@1.0.0",
        "url": "https://github.com/IBM/plex/releases/download/%40ibm/plex-mono-variable%401.0.0/sources.zip",
        "sha256": "cead332365e44b09552581533bae5dcbbd6e6ac80265afa915981260ba75eef3",
        "zip_path": TMP_DIR / "sources-mono-variable" / "sources.zip",
        "extract_dir": TMP_DIR / "sources-mono-variable" / "unzipped",
        "target_path": TMP_DIR / "sources-mono-variable" / "unzipped" / "source" / "IBM Plex Mono Var-Regular.ufo",
    },
}

INITIAL_SYNC_GLYPHS = [
    "yusmall-hira.half", "A.blackBox", "A.blackCircled", "A.roundBlackBox",
    "a-hira.box", "a-hira.circled", "a-hira.paren", "a-hira.roundBox",
    "asmall-hira", "asmall-hira.hori", "asmall-hira.prop", "asmall-hira.prop.vert",
    "asmall-hira.vert", "ba_i_to-kata", "ba_i_to-kata.vert", "baareruSquare",
    "baareruSquare.vert", "baatsuleftjust", "baatsuleftjust.vert", "bareruleftjust",
    "bareruleftjust.vert", "biruSquare", "biruSquare.vert", "de-kata.roundedBox",
    "doruSquare", "doruSquare.vert", "ga_ru-kata", "ga_ru-kata.vert", "garonSquare",
    "garonSquare.vert", "guramutonSquare", "guramutonSquare.vert", "haitsu",
    "haitsu.vert", "haituSquare", "herutsu", "herutsu.vert", "hoonSquare",
    "huranSquare", "huranSquare.vert", "ininguSquare", "ininguSquare.vert",
    "kiromeetoruSquare", "ku-kata.box", "ku-kata.circled", "ku-kata.paren",
    "ku-kata.roundBox", "mahhaSquare", "mahhaSquare.vert", "mansyonSquare",
    "meetoruSquare", "meetoruSquare.vert", "megatonSquare", "megatonSquare.vert",
    "mikuronSquare", "mikuronSquare.vert", "na-kata.box", "na-kata.circled",
    "na-kata.paren", "na-kata.roundBox", "o-kata.blackBox", "o-kata.blackCircled",
    "o-kata.roundBlackBox", "paasentoSquare", "paasentoSquare.vert", "pesetaleftjust",
    "pesetaleftjust.vert", "pikoSquare", "pikoSquare.vert", "se_n_ti-kata",
    "se_n_ti-kata.vert", "sentiSquare.vert", "sento", "sento.vert", "sentoSquare",
    "siringuSquare", "siringuSquare.vert", "ta-kata.box", "ta-kata.circled",
    "ta-kata.paren", "ta-kata.roundBox", "uonSquare", "uonSquare.vert", "wa-hira",
    "wa-hira.hori", "wa-hira.prop", "wa-hira.prop.vert", "wa-hira.vert",
    "wasmall-hira.half", "wasmall-hira.half.rotat", "watto", "watto.vert",
    "wattoSquare", "wattoSquare.vert", "ya-hira.half", "ya-hira.half.rotat",
    "yusmall-hira.half.rotat",
]

CJK_MARKERS = (
    "hira", "kata", ".vert", ".hori",
    ".jp78", ".jp83", ".jp90", ".trad", ".nlck", ".hojo", ".expt", ".ruby",
    "Square", "leftjust", ".circled", ".paren", ".box", ".roundBox",
    ".blackBox", ".blackCircled", ".roundBlackBox", ".roundedBox",
    ".qartwidth", ".thirdwidths", "comb_kana", "T_E_L", "K_K", "s_e_c", "m_i_n",
    "watto", "sento", "peeji", "haitsu", "herutsu", "koopo", "inchi", "yaado", "hoon",
    "blackScissors", ".full", ".prop",
)


# ---------------------------------------------------------------------------
# Upstream Downloading & Verification
# ---------------------------------------------------------------------------

def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _download_with_sha256(url: str, dest: Path, expected_sha256: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_dest = dest.with_suffix(dest.suffix + ".tmp")
    print(f"Downloading {url} -> {dest}...")
    req = urllib.request.Request(url, headers={"User-Agent": "HolonFontBuilder/1.0"})
    with urllib.request.urlopen(req) as resp, open(tmp_dest, "wb") as out:
        while chunk := resp.read(1 << 20):
            out.write(chunk)
    actual = _sha256_file(tmp_dest)
    if actual != expected_sha256:
        tmp_dest.unlink(missing_ok=True)
        raise RuntimeError(f"SHA-256 mismatch for {url}: expected {expected_sha256}, got {actual}")
    tmp_dest.replace(dest)


def ensure_ttf_source(rel_path: str) -> Path:
    """Return local path to an upstream TTF, downloading from pinned commit hash if needed."""
    expected_sha = TTF_SHA256[rel_path]
    local_path = TMP_DIR / "plex" / "packages" / rel_path
    if local_path.exists() and _sha256_file(local_path) == expected_sha:
        return local_path
    url = f"https://raw.githubusercontent.com/IBM/plex/{UPSTREAM_PLEX_COMMIT}/packages/{rel_path}"
    _download_with_sha256(url, local_path, expected_sha)
    return local_path


def ensure_variable_sources(for_family: str = "sans") -> tuple[Path, Path]:
    """Ensure variable font master sources (.glyphs and Sans/Mono .ufo) exist in tmp/."""
    keys = ("sans-jp", "sans") if for_family == "sans" else (
        ("sans-jp", "mono-variable") if for_family == "mono" else ("sans-jp", "sans", "mono-variable")
    )
    for key in keys:
        info = ZIP_SOURCES[key]
        if info["target_path"].exists():
            continue
        zip_path: Path = info["zip_path"]
        if not zip_path.exists() or _sha256_file(zip_path) != info["sha256"]:
            _download_with_sha256(info["url"], zip_path, info["sha256"])
        print(f"Extracting {zip_path} ({info['tag']})...")
        info["extract_dir"].mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(info["extract_dir"])
    second_key = "mono-variable" if for_family == "mono" else "sans"
    return ZIP_SOURCES["sans-jp"]["target_path"], ZIP_SOURCES[second_key]["target_path"].parent


# ---------------------------------------------------------------------------
# Shared Glyph & OpenType Helpers
# ---------------------------------------------------------------------------

def is_cjk_glyph(gname: str, u: int | None = None, box_is_latin: bool = False) -> bool:
    """Classify whether a glyph (encoded or unencoded) belongs to Japanese/CJK metrics."""
    if any(m in gname for m in CJK_MARKERS):
        return True
    if gname.startswith(("cid", "u1F", "u20", "u30", "uniFE1")):
        return True
    if gname.endswith((".half", ".italic", ".rotat", ".sups", ".subs", ".numr", ".dnom", ".ordn", ".nut")):
        return False

    if u is not None:
        if 0x2000 <= u <= 0x200B or u == 0x3000:
            return False
        if not box_is_latin and u in JP_FULLWIDTH_SYMBOLS:
            return True
        if box_is_latin and (0x2500 <= u <= 0x25FF or 0xFB00 <= u <= 0xFB4F):
            return False
        if u < 0x02B0 or 0x0370 <= u <= 0x052F or 0x200C <= u <= 0x23FF:
            return False
        return True

    m = re.match(r"^uni([0-9A-Fa-f]{4})", gname)
    if m:
        return is_cjk_glyph("", int(m.group(1), 16), box_is_latin=box_is_latin)
    return False


def _transform_tt_glyph(glyph_set, gname: str, matrix: tuple[float, ...], glyf_table):
    rec_pen = DecomposingRecordingPen(glyph_set)
    glyph_set[gname].draw(rec_pen)
    tt_pen = TTGlyphPen(None)
    rec_pen.replay(TransformPen(tt_pen, matrix))
    g = tt_pen.glyph()
    g.recalcBounds(glyf_table)
    return g


def add_vertical_semicolon(font_jp: TTFont) -> None:
    """Add uniFF1B.vert (rotated 90° CW around (500, 378)) and update vert/vrt2 in GSUB.
    Must be called BEFORE CJK scaling/slanting so uniFF1B.vert transforms identically to uniFF1A.vert.
    """
    glyf = font_jp["glyf"]
    hmtx = font_jp["hmtx"]
    vmtx = font_jp.get("vmtx")

    if "uniFF1B" not in glyf or "uniFF1B.vert" in glyf:
        return

    new_glyph = _transform_tt_glyph(
        font_jp.getGlyphSet(), "uniFF1B", (0.0, -1.0, 1.0, 0.0, 122.0, 878.0), glyf
    )
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


def add_cjk_compatibility_mappings(font_jp: TTFont) -> int:
    """Map missing CJK Compatibility Ideographs (U+F900..U+FAFF) to canonical unified ideographs."""
    cmap_jp = font_jp.getBestCmap()
    new_mappings = {}
    for code in range(0xF900, 0xFB00):
        if code not in cmap_jp:
            d = unicodedata.normalize("NFKD", chr(code))
            if len(d) == 1 and ord(d) in cmap_jp:
                new_mappings[code] = cmap_jp[ord(d)]
    for table in font_jp["cmap"].tables:
        if table.isUnicode():
            table.cmap.update(new_mappings)
    return len(new_mappings)


def style_names(weight: str, italic: bool) -> tuple[str, str, str]:
    """Return (style_name, ps_suffix, ribbon_subfamily) consistently across all families."""
    if italic:
        style_name = "Italic" if weight == "Regular" else f"{weight} Italic"
    else:
        style_name = weight
    ps_suffix = style_name.replace(" ", "")
    if weight == "Bold" and italic:
        subfamily = "Bold Italic"
    elif weight == "Bold":
        subfamily = "Bold"
    elif italic:
        subfamily = "Italic"
    else:
        subfamily = "Regular"
    return style_name, ps_suffix, subfamily


def apply_opentype_metadata(
    font: TTFont,
    family_name: str,
    weight: str,
    italic: bool,
    italic_angle: float,
    is_variable: bool = False,
) -> str:
    """Update name, OS/2, head, hhea, vhea, and post tables conforming strictly to SIL OFL 1.1.
    Returns the PostScript suffix (e.g. 'Regular', 'Italic', 'BoldItalic', 'Variable').
    """
    family_compact = family_name.replace(" ", "")
    if is_variable:
        style_name = "Italic" if italic else "Regular"
        ps_suffix = "Italic-Variable" if italic else "Variable"
        ps_name = f"{family_compact}-{'ItalicVariable' if italic else 'Variable'}"
        subfamily = style_name
    else:
        style_name, ps_suffix, subfamily = style_names(weight, italic)
        ps_name = f"{family_compact}-{ps_suffix}"

    full_name = f"{family_name} {style_name}"
    unique_id = f"1.000;{VENDOR_ID};{ps_name}"

    name_records: dict[int, str] = {
        0: COPYRIGHT_STRING,
        1: family_name,
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
        16: family_name,
        17: style_name,
        20: f"{ps_name}-83pv-RKSJ-H" if not is_variable else "",
        25: f"{family_compact}{'Italic' if italic else ''}" if is_variable else "",
    }

    name_table = font["name"]
    for record in list(name_table.names):
        if record.nameID in name_records:
            name_table.names.remove(record)
    for name_id, val in name_records.items():
        if val:
            name_table.addMultilingualName({"en": val}, nameID=name_id)

    # OS/2 table
    os2 = font["OS/2"]
    os2.achVendID = VENDOR_ID
    os2.usWeightClass = WEIGHT_VALUES.get(weight, 400)
    os2.fsType = 0  # Installable Embedding
    os2.fsSelection |= 0x80  # Bit 7: USE_TYPO_METRICS
    if italic:
        os2.fsSelection |= 0x01   # ITALIC
        os2.fsSelection &= ~0x40  # Clear REGULAR
    else:
        os2.fsSelection &= ~0x01
        if weight != "Bold":
            os2.fsSelection |= 0x40  # REGULAR
    if weight == "Bold":
        os2.fsSelection |= 0x20   # BOLD
        os2.fsSelection &= ~0x40  # Clear REGULAR
    else:
        os2.fsSelection &= ~0x20

    # head & post
    head = font["head"]
    head.fontRevision = 1.0
    head.macStyle = (0x02 if italic else 0) | (0x01 if weight == "Bold" else 0)
    font["post"].italicAngle = italic_angle if italic else 0.0

    # hhea caret slope for Italic
    hhea = font["hhea"]
    if italic:
        hhea.caretSlopeRise = 1000
        hhea.caretSlopeRun = int(round(1000.0 * math.tan(math.radians(-italic_angle))))
    else:
        hhea.caretSlopeRise = 1
        hhea.caretSlopeRun = 0

    return ps_suffix


def install_enhanced_chws() -> None:
    """Enhance east_asian_spacing GlyphSets with comprehensive JIS X 4051 yakumono rules."""
    from east_asian_spacing.spacing import (
        ChainContextPosBuilder,
        ChainContextualRule,
        Font,
        GlyphSets,
        PairPosBuilder,
    )

    def custom_build_chws_lookup(self, font: Font, lookups, pos: GlyphSets.PosValues):
        self.assert_font(font)
        lookup_indices = []
        ttfont = font.ttfont
        glyph_order = set(ttfont.getGlyphOrder())
        em = font.fullwidth_advance
        half_em = math.floor(em / 2)
        quad_em = math.floor(half_em / 2)

        if font.is_vertical:
            for g in ("uniFF1B.vert", "semicolon.full.vert", "uniFF1B"):
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

        pair_pos_builder = PairPosBuilder(ttfont, None)
        pair_pos_builder.addClassPair(
            None, pos.left, half_left_val,
            pos.left + pos.right + pos.middle + pos.space + pos.na_left, None,
        )
        if pos.middle:
            pair_pos_builder.addClassPair(None, pos.middle, half_left_val, pos.middle, None)
            if pos.space:
                pair_pos_builder.addClassPair(None, pos.middle, half_left_val, pos.space, None)
            if pos.left:
                pair_pos_builder.addClassPair(None, pos.middle, quad_left_val, pos.left, None)

        for sp_g in ("space", "space.rotat"):
            if sp_g in glyph_order:
                for col_g in ("uniFF1A", "uniFF1B", "uniFF1A.vert", "uniFF1B.vert", "semicolon.full.vert"):
                    if col_g in glyph_order:
                        pair_pos_builder.addGlyphPair(None, col_g, half_left_val, sp_g, None)

        lookup = pair_pos_builder.build()
        assert lookup
        lookup_indices.append(len(lookups))
        lookups.append(lookup)

        single_pos_lookup_right = self._build_single_pos_lookup(
            font, lookups, ((pos.right, half_right_val),)
        )
        single_pos_lookup_mid_half = self._build_single_pos_lookup(
            font, lookups, ((pos.middle, half_right_val),)
        )
        single_pos_lookup_mid_quad = self._build_single_pos_lookup(
            font, lookups, ((pos.middle, quad_right_val),)
        )

        chain_builder = ChainContextPosBuilder(ttfont, None)
        chain_builder.rules.append(
            ChainContextualRule(
                [pos.right + pos.middle + pos.space + pos.na_right],
                [pos.right], [], [[single_pos_lookup_right]],
            )
        )
        if pos.right and pos.middle:
            chain_builder.rules.append(
                ChainContextualRule([pos.right], [pos.middle], [], [[single_pos_lookup_mid_quad]])
            )
        if pos.space and pos.middle:
            chain_builder.rules.append(
                ChainContextualRule([pos.space], [pos.middle], [], [[single_pos_lookup_mid_half]])
            )

        lookup2 = chain_builder.build()
        assert lookup2
        lookup_indices.append(len(lookups))
        lookups.append(lookup2)
        return lookup_indices

    GlyphSets._build_chws_lookup = custom_build_chws_lookup


async def apply_chws(input_path: Path, output_path: Path) -> None:
    """Inject chws and vchw OpenType feature rules using east_asian_spacing."""
    install_enhanced_chws()
    config = Config.default.clone()
    config.fullwidth_advance = 1000
    builder = Builder(str(input_path), config=config)
    res = await builder.build_and_save(output_path)
    if not res:
        raise RuntimeError(f"Failed to inject chws into {input_path}")


def subset_and_export(
    font_path: Path,
    out_desktop: Path,
    out_woff2: Path,
    layout_features: list[str] | None = None,
) -> None:
    """Remove unreferenced glyphs, drop obsolete tables, set post 3.0, and export desktop + WOFF2."""
    font = TTFont(font_path)
    opts = SubsetOptions()
    opts.layout_features = layout_features if layout_features is not None else ["*"]
    opts.name_IDs = ["*"]
    opts.name_languages = ["*"]
    opts.notdef_outline = True
    opts.glyph_names = False  # post format 3.0
    opts.hinting = False      # remove unused fpgm/prep/cvt
    opts.drop_tables += ["DSIG"]

    subsetter = Subsetter(options=opts)
    subsetter.populate(unicodes=font.getBestCmap().keys())
    subsetter.subset(font)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    font.save(out_desktop)
    font.flavor = "woff2"
    font.save(out_woff2)

    if font_path != out_desktop and font_path.exists():
        font_path.unlink()

    print(f"  Desktop: {out_desktop} ({out_desktop.stat().st_size:,} bytes, {font['maxp'].numGlyphs:,} glyphs)")
    print(f"  WOFF2:   {out_woff2} ({out_woff2.stat().st_size:,} bytes)")


# ---------------------------------------------------------------------------
# 1. Holon Sans Static Builder
# ---------------------------------------------------------------------------

def build_sans_style(weight: str, italic: bool = False) -> Path:
    style_name, _, _ = style_names(weight, italic)
    print(f"\n=== Building {SANS_FAMILY} {style_name} ===")

    sans_style = ("Italic" if weight == "Regular" else f"{weight}Italic") if italic else weight
    sans_path = ensure_ttf_source(f"plex-sans/fonts/complete/ttf/IBMPlexSans-{sans_style}.ttf")
    jp_path = ensure_ttf_source(f"plex-sans-jp/fonts/complete/ttf/unhinted/IBMPlexSansJP-{weight}.ttf")

    font_sans = TTFont(sans_path)
    font_jp = TTFont(jp_path)

    # 1. Add vertical semicolon before glyph transformations
    add_vertical_semicolon(font_jp)

    cmap_sans = font_sans.getBestCmap()
    cmap_jp = font_jp.getBestCmap()
    rev_cmap_jp = {g: u for u, g in cmap_jp.items()}

    glyf_jp = font_jp["glyf"]
    hmtx_jp = font_jp["hmtx"]
    vmtx_jp = font_jp.get("vmtx")
    glyph_set_sans = font_sans.getGlyphSet()
    glyph_set_jp = font_jp.getGlyphSet()

    # 2. Merge Latin/symbol glyphs from IBM Plex Sans (1.02x scale)
    new_cmap_entries: dict[int, str] = {}
    replaced_glyphs: set[str] = set()
    sans_matrix = (SCALE_SANS, 0.0, 0.0, SCALE_SANS, 0.0, 0.0)

    for ucode, gname_sans in cmap_sans.items():
        if ucode < 0x0020 or ucode >= 0xE000 or ucode in JP_FULLWIDTH_SYMBOLS or ucode == 0x3000:
            continue

        dest_gname = gname_sans
        if dest_gname not in replaced_glyphs:
            scaled_glyph = _transform_tt_glyph(glyph_set_sans, gname_sans, sans_matrix, glyf_jp)
            orig_w, orig_lsb = font_sans["hmtx"][gname_sans]
            if ucode in (0x2001, 0x2003):
                new_w, new_lsb = 1000, 0
            elif ucode in (0x2000, 0x2002):
                new_w, new_lsb = 500, 0
            else:
                new_w = 0 if orig_w == 0 else int(round(orig_w * SCALE_SANS))
                new_lsb = int(round(orig_lsb * SCALE_SANS))

            glyf_jp[dest_gname] = scaled_glyph
            hmtx_jp[dest_gname] = (new_w, new_lsb)
            if vmtx_jp is not None:
                tsb = 880 - (scaled_glyph.yMax if scaled_glyph.numberOfContours != 0 else 0)
                vmtx_jp.metrics[dest_gname] = (1000, tsb)
            replaced_glyphs.add(dest_gname)

        new_cmap_entries[ucode] = dest_gname

    # Also copy key alternate Latin glyphs (slashed zero, single-story a/g, fi/fl)
    for alt_g in ("zero.alt01", "a.alt01", "g.alt01", "fi", "fl"):
        if alt_g in font_sans["glyf"]:
            scaled_glyph = _transform_tt_glyph(glyph_set_sans, alt_g, sans_matrix, glyf_jp)
            orig_w, orig_lsb = font_sans["hmtx"][alt_g]
            new_w = int(round(orig_w * SCALE_SANS))
            new_lsb = int(round(orig_lsb * SCALE_SANS))
            glyf_jp[alt_g] = scaled_glyph
            hmtx_jp[alt_g] = (new_w, new_lsb)
            if vmtx_jp is not None:
                tsb = 880 - (scaled_glyph.yMax if scaled_glyph.numberOfContours != 0 else 0)
                vmtx_jp.metrics[alt_g] = (1000, tsb)
            replaced_glyphs.add(alt_g)
            if alt_g == "zero.alt01" and "zero.zero" in glyf_jp:
                glyf_jp["zero.zero"] = copy.deepcopy(scaled_glyph)
                hmtx_jp["zero.zero"] = (new_w, new_lsb)
                if vmtx_jp is not None:
                    vmtx_jp.metrics["zero.zero"] = (1000, tsb)
                replaced_glyphs.add("zero.zero")

    # 3. Transform remaining glyphs in font_jp (both encoded & unencoded CJK and remaining JP Latin)
    slant = math.tan(math.radians(-SANS_ITALIC_ANGLE)) if italic else 0.0
    dy_cjk = JP_CENTER_Y * (1.0 - SCALE_JP)

    for gname in list(glyf_jp.keys()):
        if gname in replaced_glyphs or gname == ".notdef":
            continue
        orig_glyph = glyf_jp[gname]
        orig_w, orig_lsb = hmtx_jp[gname]
        u = rev_cmap_jp.get(gname)

        if orig_glyph.numberOfContours == 0:
            continue

        if is_cjk_glyph(gname, u, box_is_latin=False):
            cx = orig_w / 2.0 if orig_w > 0 else JP_CENTER_X
            dx = cx * (1.0 - SCALE_JP)
            matrix = (
                SCALE_JP, 0.0, SCALE_JP * slant, SCALE_JP,
                dx + (dy_cjk - JP_CENTER_Y) * slant, dy_cjk,
            )
            new_w = orig_w
        else:
            matrix = (SCALE_SANS, 0.0, SCALE_SANS * slant, SCALE_SANS, 0.0, 0.0)
            new_w = orig_w if gname.endswith(".rotat") else int(round(orig_w * SCALE_SANS))

        new_glyph = _transform_tt_glyph(glyph_set_jp, gname, matrix, glyf_jp)
        glyf_jp[gname] = new_glyph
        hmtx_jp[gname] = (new_w, new_glyph.xMin)

        if vmtx_jp is not None:
            tsb = 880 - (new_glyph.yMax if new_glyph.numberOfContours != 0 else 0)
            v_adv = vmtx_jp.metrics.get(gname, (1000, tsb))[0]
            vmtx_jp.metrics[gname] = (v_adv, tsb)

    # Update glyph order and cmap
    existing_order = font_jp.getGlyphOrder()
    new_order = existing_order + [g for g in new_cmap_entries.values() if g not in existing_order]
    font_jp.setGlyphOrder(new_order)
    font_jp["maxp"].numGlyphs = len(new_order)
    for table in font_jp["cmap"].tables:
        if table.isUnicode():
            table.cmap.update(new_cmap_entries)

    add_cjk_compatibility_mappings(font_jp)

    # Ensure fullwidth space (U+3000) is exact 1000 UPM
    cmap_best = font_jp.getBestCmap()
    if 0x3000 in cmap_best:
        g_3000 = cmap_best[0x3000]
        hmtx_jp[g_3000] = (1000, 0)
        if vmtx_jp is not None:
            vmtx_jp.metrics[g_3000] = (1000, 880)

    ps_suffix = apply_opentype_metadata(font_jp, SANS_FAMILY, weight, italic, SANS_ITALIC_ANGLE)

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    inter_path = TMP_DIR / f"HolonSans-{ps_suffix}.inter.ttf"
    chws_path = TMP_DIR / f"HolonSans-{ps_suffix}.chws.ttf"
    font_jp.save(inter_path)

    asyncio.run(apply_chws(inter_path, chws_path))
    inter_path.unlink(missing_ok=True)

    final_ttf = OUTPUT_DIR / f"HolonSans-{ps_suffix}.ttf"
    final_woff2 = OUTPUT_DIR / f"HolonSans-{ps_suffix}.woff2"
    subset_and_export(chws_path, final_ttf, final_woff2, layout_features=["*"])
    return final_ttf


# ---------------------------------------------------------------------------
# 2. Holon Mono Static Builder
# ---------------------------------------------------------------------------

def build_mono_style(weight: str, italic: bool = False) -> Path:
    style_name, _, _ = style_names(weight, italic)
    print(f"\n=== Building {MONO_FAMILY} {style_name} ===")

    mono_style = ("Italic" if weight == "Regular" else f"{weight}Italic") if italic else weight
    mono_path = ensure_ttf_source(f"plex-mono/fonts/complete/ttf/IBMPlexMono-{mono_style}.ttf")
    jp_path = ensure_ttf_source(f"plex-sans-jp/fonts/complete/ttf/unhinted/IBMPlexSansJP-{weight}.ttf")

    font_mono = TTFont(mono_path)
    font_jp = TTFont(jp_path)

    # 1. Add vertical semicolon BEFORE glyph transformations (fixes Italic vertical shear distortion)
    add_vertical_semicolon(font_jp)

    cmap_mono = font_mono.getBestCmap()
    cmap_jp = font_jp.getBestCmap()
    rev_cmap_jp = {g: u for u, g in cmap_jp.items()}

    glyf_jp = font_jp["glyf"]
    hmtx_jp = font_jp["hmtx"]
    vmtx_jp = font_jp.get("vmtx")
    glyph_set_mono = font_mono.getGlyphSet()
    glyph_set_jp = font_jp.getGlyphSet()

    # 2. Merge Latin, symbol, and box-drawing glyphs from IBM Plex Mono (550 UPM cell)
    new_cmap_entries: dict[int, str] = {}
    replaced_glyphs: set[str] = set()
    mono_matrix = (SCALE_MONO_X, 0.0, 0.0, SCALE_MONO_Y, 0.0, 0.0)

    for ucode, gname_mono in cmap_mono.items():
        if ucode < 0x0020 or ucode >= 0xE000 or ucode == 0x3000:
            continue

        dest_gname = gname_mono
        if dest_gname not in replaced_glyphs:
            scaled_glyph = _transform_tt_glyph(glyph_set_mono, gname_mono, mono_matrix, glyf_jp)
            orig_w, orig_lsb = font_mono["hmtx"][gname_mono]
            new_w = 0 if orig_w == 0 else HALF_WIDTH
            new_lsb = int(round(orig_lsb * SCALE_MONO_X))

            glyf_jp[dest_gname] = scaled_glyph
            hmtx_jp[dest_gname] = (new_w, new_lsb)
            if vmtx_jp is not None:
                tsb = 880 - (scaled_glyph.yMax if scaled_glyph.numberOfContours != 0 else 0)
                vmtx_jp.metrics[dest_gname] = (FULL_WIDTH, tsb)
            replaced_glyphs.add(dest_gname)

        new_cmap_entries[ucode] = dest_gname

    # Copy Mono stylistic alternates (dotted/slashed zero, a.alt01, g.alt01)
    for alt_g in ("zero.alt01", "zero.tosf.alt01", "a.alt01", "g.alt01"):
        if alt_g in font_mono["glyf"]:
            scaled_glyph = _transform_tt_glyph(glyph_set_mono, alt_g, mono_matrix, glyf_jp)
            _, orig_lsb = font_mono["hmtx"][alt_g]
            new_lsb = int(round(orig_lsb * SCALE_MONO_X))
            glyf_jp[alt_g] = scaled_glyph
            hmtx_jp[alt_g] = (HALF_WIDTH, new_lsb)
            if vmtx_jp is not None:
                tsb = 880 - (scaled_glyph.yMax if scaled_glyph.numberOfContours != 0 else 0)
                vmtx_jp.metrics[alt_g] = (FULL_WIDTH, tsb)
            replaced_glyphs.add(alt_g)
            if alt_g == "zero.alt01" and "zero.zero" in glyf_jp:
                glyf_jp["zero.zero"] = copy.deepcopy(scaled_glyph)
                hmtx_jp["zero.zero"] = (HALF_WIDTH, new_lsb)
                if vmtx_jp is not None:
                    vmtx_jp.metrics["zero.zero"] = (FULL_WIDTH, tsb)
                replaced_glyphs.add("zero.zero")

    # 3. Transform all remaining glyphs in font_jp to strict 550 or 1100 UPM cells
    slant = math.tan(math.radians(-MONO_ITALIC_ANGLE)) if italic else 0.0
    full_matrix = (
        SCALE_JP, 0.0, SCALE_JP * slant, SCALE_JP,
        MONO_JP_OFFSET_X + (MONO_JP_OFFSET_Y - JP_CENTER_Y) * slant,
        MONO_JP_OFFSET_Y,
    )

    for gname in list(glyf_jp.keys()):
        if gname in replaced_glyphs:
            continue
        orig_glyph = glyf_jp[gname]
        orig_w, orig_lsb = hmtx_jp[gname]
        u = rev_cmap_jp.get(gname)

        if orig_w == 0:
            continue

        # Determine if halfwidth (550) or fullwidth (1100)
        is_hw = (
            orig_w == 500
            or u in (0x2000, 0x2002, 0x2004, 0x2005, 0x2006, 0x2007, 0x2008, 0x2009, 0x200A)
            or (orig_w < 850 and not is_cjk_glyph(gname, u, box_is_latin=True))
        )
        target_w = HALF_WIDTH if is_hw else FULL_WIDTH

        if orig_glyph.numberOfContours == 0:
            hmtx_jp[gname] = (target_w, 0)
            if vmtx_jp is not None:
                vmtx_jp.metrics[gname] = (FULL_WIDTH, 880)
            continue

        if is_hw:
            sx = 1.0 if orig_w <= 500 else 500.0 / orig_w
            sy = 1.0 if orig_w == 500 else SCALE_MONO_Y
            dx = (HALF_WIDTH - orig_w * sx) / 2.0
            mat = (sx, 0.0, sy * slant, sy, dx, 0.0)
        else:
            mat = full_matrix

        new_glyph = _transform_tt_glyph(glyph_set_jp, gname, mat, glyf_jp)
        glyf_jp[gname] = new_glyph
        hmtx_jp[gname] = (target_w, new_glyph.xMin)

        if vmtx_jp is not None:
            tsb = 880 - (new_glyph.yMax if new_glyph.numberOfContours != 0 else 0)
            vmtx_jp.metrics[gname] = (FULL_WIDTH, tsb)

    # Update glyph order and cmap
    existing_order = font_jp.getGlyphOrder()
    new_order = existing_order + [
        g for g in list(new_cmap_entries.values()) + ["zero.alt01", "zero.tosf.alt01", "a.alt01", "g.alt01"]
        if g in glyf_jp and g not in existing_order
    ]
    font_jp.setGlyphOrder(new_order)
    font_jp["maxp"].numGlyphs = len(new_order)
    for table in font_jp["cmap"].tables:
        if table.isUnicode():
            table.cmap.update(new_cmap_entries)

    add_cjk_compatibility_mappings(font_jp)

    # Ensure fullwidth space (U+3000) is exact 1100 UPM and ASCII space (U+0020) is 550 UPM
    cmap_best = font_jp.getBestCmap()
    if 0x3000 in cmap_best:
        g_3000 = cmap_best[0x3000]
        hmtx_jp[g_3000] = (FULL_WIDTH, 0)
        if vmtx_jp is not None:
            vmtx_jp.metrics[g_3000] = (FULL_WIDTH, 880)

    # 4. Clean up OpenType tables for strict monospace / duospace integrity
    if "GPOS" in font_jp:
        del font_jp["GPOS"]
    if "BASE" in font_jp:
        del font_jp["BASE"]
    if "GSUB" in font_jp:
        gsub = font_jp["GSUB"].table
        vert_lookups: list[int] = []
        for rec in gsub.FeatureList.FeatureRecord:
            if rec.FeatureTag == "vert":
                vert_lookups = list(rec.Feature.LookupListIndex)
                break
        for rec in gsub.FeatureList.FeatureRecord:
            if rec.FeatureTag == "vrt2" and vert_lookups:
                rec.Feature.LookupListIndex = list(vert_lookups)
            elif rec.FeatureTag == "zero":
                for lidx in rec.Feature.LookupListIndex:
                    for st in gsub.LookupList.Lookup[lidx].SubTable:
                        if hasattr(st, "mapping"):
                            st.mapping = {"zero": "zero.alt01"}

    # 5. Apply terminal & editor compatible vertical metrics (950 / -225)
    os2 = font_jp["OS/2"]
    hhea = font_jp["hhea"]
    os2.sTypoAscender = hhea.ascent = os2.usWinAscent = 950
    os2.sTypoDescender = hhea.descent = -225
    os2.usWinDescent = 225
    os2.sTypoLineGap = hhea.lineGap = 0
    os2.panose.bProportion = 9
    font_jp["post"].isFixedPitch = 0

    ps_suffix = apply_opentype_metadata(font_jp, MONO_FAMILY, weight, italic, MONO_ITALIC_ANGLE)

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    inter_path = TMP_DIR / f"HolonMono-{ps_suffix}.inter.ttf"
    font_jp.save(inter_path)

    final_ttf = OUTPUT_DIR / f"HolonMono-{ps_suffix}.ttf"
    final_woff2 = OUTPUT_DIR / f"HolonMono-{ps_suffix}.woff2"
    subset_and_export(inter_path, final_ttf, final_woff2, layout_features=MONO_SAFE_FEATURES)
    return final_ttf


# ---------------------------------------------------------------------------
# 3. Holon Sans Variable Font Builder
# ---------------------------------------------------------------------------

def _merge_missing_sans_ufo_glyphs(
    ufo_thin: ufoLib2.Font,
    ufo_reg: ufoLib2.Font,
    ufo_bold: ufoLib2.Font,
    sans_masters_dir: Path,
) -> int:
    """Merge the 269 Latin/symbol glyphs present in IBM Plex Sans UFOs but missing from JP Glyphs."""
    sans_t = ufoLib2.Font.open(sans_masters_dir / "IBM Plex Sans-Thin.ufo")
    sans_r = ufoLib2.Font.open(sans_masters_dir / "IBM Plex Sans-Regular.ufo")
    sans_b = ufoLib2.Font.open(sans_masters_dir / "IBM Plex Sans-Bold.ufo")

    existing_unicodes = {u for g in ufo_reg for u in (g.unicodes or ([g.unicode] if g.unicode is not None else []))}
    added = 0

    for g_r in sans_r:
        u = g_r.unicode
        if u is None or u in existing_unicodes or u < 0x0020 or u >= 0xE000:
            continue
        gname = g_r.name
        if gname in ufo_reg:
            gname = f"ext_{gname}"

        decomposed: list[ufoLib2.objects.Glyph] = []
        sigs: list[list[tuple[int, list[str | None]]]] = []
        for s_ufo in (sans_t, sans_r, sans_b):
            src_g = s_ufo[g_r.name] if g_r.name in s_ufo else g_r
            dg = ufoLib2.objects.Glyph(name=gname, width=src_g.width, height=1000, unicodes=[u])
            dg.verticalOrigin = 880
            rpen = DecomposingRecordingPointPen(s_ufo)
            src_g.drawPoints(rpen)
            rpen.replay(dg.getPointPen())
            decomposed.append(dg)
            sigs.append([(len(c.points), [p.segmentType for p in c.points]) for c in dg.contours])

        if sigs[0] == sigs[1] == sigs[2]:
            ufo_thin[gname], ufo_reg[gname], ufo_bold[gname] = decomposed
        elif sigs[1] == sigs[2]:
            ufo_thin[gname] = decomposed[1].copy()
            ufo_reg[gname] = decomposed[1]
            ufo_bold[gname] = decomposed[2]
        else:
            ufo_thin[gname] = decomposed[1].copy()
            ufo_reg[gname] = decomposed[1]
            ufo_bold[gname] = decomposed[1].copy()

        for dst_ufo in (ufo_thin, ufo_reg, ufo_bold):
            if "public.glyphOrder" in dst_ufo.lib:
                 dst_ufo.lib["public.glyphOrder"].append(gname)
        added += 1

    return added


def _add_vertical_semicolon_to_ufo(ufo: ufoLib2.Font) -> None:
    src_name = "semicolon.full" if "semicolon.full" in ufo else ("uniFF1B" if "uniFF1B" in ufo else None)
    if not src_name:
        return
    vert_name = f"{src_name}.vert"
    if vert_name in ufo:
        return

    src_g = ufo[src_name]
    ng = ufo.newGlyph(vert_name)
    ng.width = 1000
    ng.height = 1000
    ng.verticalOrigin = 880
    src_g.drawPoints(TransformPointPen(ng.getPointPen(), (0.0, -1.0, 1.0, 0.0, 122.0, 878.0)))

    # Register PostScript production name so ufo2ft renames semicolon.full.vert -> uniFF1B.vert
    ufo.lib.setdefault("public.postscriptNames", {})[vert_name] = "uniFF1B.vert"
    if "public.glyphOrder" in ufo.lib and vert_name not in ufo.lib["public.glyphOrder"]:
        ufo.lib["public.glyphOrder"].append(vert_name)

    fea = ufo.features.text or ""
    fea = re.sub(
        r"(feature\s+(?:vert|vrt2)\s*\{[^}]*?sub\s+colon\.full\s+by\s+colon\.full\.vert;)",
        r"\1\n    sub semicolon.full by semicolon.full.vert;",
        fea,
    )
    fea = re.sub(
        r"(feature\s+(?:vert|vrt2)\s*\{[^}]*?sub\s+uniFF1A\s+by\s+uniFF1A\.vert;)",
        r"\1\n    sub uniFF1B by uniFF1B.vert;",
        fea,
    )
    ufo.features.text = fea


def _apply_ufo_dual_scale(ufo: ufoLib2.Font) -> None:
    """Apply dual-scale to UFO: Latin 1.02x around (0, 0), CJK 0.97x centered at (width/2, 400)."""
    dy_jp = JP_CENTER_Y * (1.0 - SCALE_JP)

    for g in ufo:
        unicodes = set(g.unicodes or [])
        if g.unicode is not None:
            unicodes.add(g.unicode)

        if unicodes & {0x3000, 0x2003, 0x2001}:
            g.width = 1000
            continue
        if unicodes & {0x2000, 0x2002}:
            g.width = 500
            continue

        if is_cjk_glyph(g.name, g.unicode, box_is_latin=False):
            cx = g.width / 2.0 if g.width > 0 else JP_CENTER_X
            dx_jp = cx * (1.0 - SCALE_JP)
            for c in g.contours:
                for p in c.points:
                    p.x = p.x * SCALE_JP + dx_jp
                    p.y = p.y * SCALE_JP + dy_jp
        else:
            for c in g.contours:
                for p in c.points:
                    p.x *= SCALE_SANS
                    p.y *= SCALE_SANS
            if not g.name.endswith(".rotat"):
                g.width = int(round(g.width * SCALE_SANS))


def _apply_ufo_mono_cjk_transform(ufo: ufoLib2.Font, italic: bool = False) -> None:
    """Transform UFO glyphs to strict Holon Mono duospace metrics:
    - Japanese / CJK glyphs: scaled 0.97x, centered in 1100 UPM cell (offset (65, 12)).
      If italic, apply 9.0° shear around JP_CENTER_Y (400).
    - Fullwidth space (U+3000): width 1100 UPM.
    - Halfwidth symbols / non-CJK: width 550 or 1100 UPM.
    """
    slant = math.tan(math.radians(-MONO_ITALIC_ANGLE)) if italic else 0.0

    for g in ufo:
        unicodes = set(g.unicodes or [])
        if g.unicode is not None:
            unicodes.add(g.unicode)

        if unicodes & {0x3000, 0x2003, 0x2001}:
            g.width = FULL_WIDTH
            continue
        if unicodes & {0x2000, 0x2002}:
            g.width = HALF_WIDTH
            continue

        is_cjk = is_cjk_glyph(g.name, g.unicode, box_is_latin=True)
        if is_cjk:
            g.width = FULL_WIDTH
            for c in g.contours:
                for p in c.points:
                    px = p.x * SCALE_JP + MONO_JP_OFFSET_X
                    py = p.y * SCALE_JP + MONO_JP_OFFSET_Y
                    if italic:
                        px += (py - JP_CENTER_Y) * slant
                    p.x = px
                    p.y = py
        else:
            if g.width == 500 or (0 < g.width < 850):
                g.width = HALF_WIDTH
            elif g.width > 0:
                g.width = FULL_WIDTH


def _merge_mono_variable_latin(
    ufo_jp: ufoLib2.Font,
    ufo_mono: ufoLib2.Font,
    italic: bool = False,
) -> None:
    """Merge IBM Plex Mono Var Latin/symbol/box-drawing glyphs into Japanese UFO master."""
    ufo_jp.kerning.clear()
    ufo_mono.kerning.clear()

    # Build unicode to glyph name mapping in JP UFO to prevent duplicate unicode mappings
    u_to_jp_gname = {}
    for g in ufo_jp:
        for u in (g.unicodes or []):
            u_to_jp_gname[u] = g.name

    for g_mono in ufo_mono:
        unicodes = set(g_mono.unicodes or [])
        if g_mono.unicode is not None:
            unicodes.add(g_mono.unicode)

        if 0x3000 in unicodes:
            continue

        # Prevent duplicate unicode mapping: remove unicode from existing JP glyph if different
        for u in unicodes:
            if u in u_to_jp_gname and u_to_jp_gname[u] != g_mono.name:
                old_gname = u_to_jp_gname[u]
                if old_gname in ufo_jp:
                    old_g = ufo_jp[old_gname]
                    old_g.unicodes = [x for x in (old_g.unicodes or []) if x != u]

        is_box = bool(unicodes & set(range(0x2500, 0x2580))) or "bxd" in g_mono.name or "block" in g_mono.name

        ng = copy.deepcopy(g_mono)
        if ng.width > 0:
            ng.width = HALF_WIDTH

        for c in ng.contours:
            for p in c.points:
                px = p.x * SCALE_MONO_X
                py = p.y * SCALE_MONO_Y
                if is_box:
                    # Snap box drawing vertical boundaries to strict 950 and -225
                    if p.y >= 900:
                        py = 950.0
                    elif p.y <= -200:
                        py = -225.0
                p.x = px
                p.y = py

        ufo_jp[ng.name] = ng


def _make_slanted_master(ufo_src: ufoLib2.Font, name: str) -> ufoLib2.Font:
    """Create a slanted UFO master by applying 11.0° shear (CJK around cy=400, Latin around cy=0)."""
    s = math.tan(math.radians(-SANS_ITALIC_ANGLE))
    new_f = ufoLib2.Font()
    new_f.info = copy.deepcopy(ufo_src.info)
    new_f.info.familyName = SANS_FAMILY
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

        cjk = is_cjk_glyph(gname, src_g.unicode, box_is_latin=False)
        dy_pivot = -JP_CENTER_Y * s if cjk else 0.0
        src_g.drawPoints(TransformPointPen(ng.getPointPen(), (1.0, 0.0, s, 1.0, dy_pivot, 0.0)))

    return new_f


def _make_grade_master(
    ufo_base: ufoLib2.Font,
    ufo_target: ufoLib2.Font,
    factor: float,
    name: str,
    family_name: str = SANS_FAMILY,
) -> ufoLib2.Font:
    """Create a Grade master by interpolating stroke weight while locking advance widths to base."""
    new_f = ufoLib2.Font()
    new_f.info = copy.deepcopy(ufo_base.info)
    new_f.info.familyName = family_name
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

        if gname not in ufo_target or len(g_base.contours) != len(ufo_target[gname].contours):
            g_base.drawPoints(ng.getPointPen())
            continue

        g_tgt = ufo_target[gname]
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
            ng.clearContours()
            g_base.drawPoints(ng.getPointPen())

    return new_f


def _make_variable_designspace(
    ufo_thin: ufoLib2.Font,
    ufo_reg: ufoLib2.Font,
    ufo_bold: ufoLib2.Font,
    ufo_grad_pos: ufoLib2.Font,
    ufo_grad_neg: ufoLib2.Font,
    italic: bool,
    family_name: str = SANS_FAMILY,
) -> DesignSpaceDocument:
    var_ds = DesignSpaceDocument()

    ax_wght = AxisDescriptor()
    ax_wght.tag = "wght"
    ax_wght.name = "Weight"
    ax_wght.minimum, ax_wght.default, ax_wght.maximum = 100, 400, 700
    ax_wght.map = [(100, 100), (400, 360), (700, 700)]
    var_ds.addAxis(ax_wght)

    ax_grad = AxisDescriptor()
    ax_grad.tag = "GRAD"
    ax_grad.name = "Grade"
    ax_grad.minimum, ax_grad.default, ax_grad.maximum = -100, 0, 100
    var_ds.addAxis(ax_grad)

    style_suffix = " Italic" if italic else ""
    for font_obj, loc, sname in [
        (ufo_thin,     {"Weight": 100, "Grade": 0},    f"Thin{style_suffix}"),
        (ufo_reg,      {"Weight": 360, "Grade": 0},    f"Regular{style_suffix}"),
        (ufo_bold,     {"Weight": 700, "Grade": 0},    f"Bold{style_suffix}"),
        (ufo_grad_pos, {"Weight": 360, "Grade": 100},  f"Regular{style_suffix} Grade+"),
        (ufo_grad_neg, {"Weight": 360, "Grade": -100}, f"Regular{style_suffix} Grade-"),
    ]:
        src = SourceDescriptor()
        src.font = font_obj
        src.location = loc
        src.name = src.styleName = sname
        src.familyName = family_name
        var_ds.addSource(src)

    for w_name in WEIGHTS:
        iname, _, _ = style_names(w_name, italic)
        inst = InstanceDescriptor()
        inst.familyName = family_name
        inst.styleName = iname
        inst.location = {"Weight": WEIGHT_VALUES[w_name], "Grade": 0}
        var_ds.addInstance(inst)

    return var_ds


def _compile_and_export_vf(
    var_ds: DesignSpaceDocument,
    italic: bool,
    masters: list[ufoLib2.Font],
    family_name: str = SANS_FAMILY,
) -> Path:
    style_label = "Italic" if italic else "Roman"
    family_compact = family_name.replace(" ", "")
    is_mono = (family_name == MONO_FAMILY)
    ufo_thin, ufo_reg, ufo_bold, ufo_grad_pos, ufo_grad_neg = masters
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    inter_otf = TMP_DIR / f"{family_compact}-{style_label}-Variable.inter.otf"
    chws_otf = TMP_DIR / f"{family_compact}-{style_label}-Variable.chws.otf"

    for attempt in range(20):
        try:
            print(f"Compiling CFF2 variable font ({family_name} {style_label}, attempt {attempt + 1})...")
            var_font = ufo2ft.compileVariableCFF2(var_ds)
            break
        except Exception as e:
            m = re.search(r"Glyph '([^']+)'", str(e))
            if m and m.group(1) in ufo_reg:
                bad = m.group(1)
                print(f"Synchronizing non-interpolatable glyph across masters: '{bad}'")
                for m_ufo in (ufo_thin, ufo_bold, ufo_grad_pos, ufo_grad_neg):
                    m_ufo[bad] = ufo_reg[bad].copy()
                continue
            raise RuntimeError(f"Variable compilation failed ({family_name} {style_label}): {e}") from e

    italic_angle = MONO_ITALIC_ANGLE if is_mono else SANS_ITALIC_ANGLE
    ps_suffix = apply_opentype_metadata(
        var_font, family_name, "Regular", italic, italic_angle, is_variable=True
    )

    if is_mono:
        # Strict monospace / duospace adjustments
        cmap_best = var_font.getBestCmap()
        if 0x3000 in cmap_best:
            g_3000 = cmap_best[0x3000]
            var_font["hmtx"][g_3000] = (FULL_WIDTH, 0)
            if "vmtx" in var_font:
                var_font["vmtx"].metrics[g_3000] = (FULL_WIDTH, 880)
        if 0x0020 in cmap_best:
            g_0020 = cmap_best[0x0020]
            var_font["hmtx"][g_0020] = (HALF_WIDTH, 0)
            if "vmtx" in var_font:
                var_font["vmtx"].metrics[g_0020] = (FULL_WIDTH, 880)

        os2 = var_font["OS/2"]
        hhea = var_font["hhea"]
        os2.sTypoAscender = hhea.ascent = os2.usWinAscent = 950
        os2.sTypoDescender = hhea.descent = -225
        os2.usWinDescent = 225
        os2.sTypoLineGap = hhea.lineGap = 0
        os2.panose.bProportion = 9
        var_font["post"].isFixedPitch = 0

        if "GPOS" in var_font:
            del var_font["GPOS"]
        if "BASE" in var_font:
            del var_font["BASE"]
    else:
        # Sans: Ensure U+3000 fullwidth space is exact 1000 UPM
        cmap_best = var_font.getBestCmap()
        if 0x3000 in cmap_best:
            g_3000 = cmap_best[0x3000]
            var_font["hmtx"][g_3000] = (1000, 0)
            if "vmtx" in var_font:
                var_font["vmtx"].metrics[g_3000] = (1000, 880)

    # Build cross-file linked STAT table
    stat_axes = [
        dict(
            tag="wght",
            name="Weight",
            ordering=0,
            values=[
                dict(value=100, name="Thin"),
                dict(value=200, name="ExtraLight"),
                dict(value=300, name="Light"),
                dict(value=400, name="Regular", flags=0x2, linkedValue=700),
                dict(value=450, name="Text"),
                dict(value=500, name="Medium"),
                dict(value=600, name="SemiBold"),
                dict(value=700, name="Bold"),
            ],
        ),
        dict(
            tag="GRAD",
            name="Grade",
            ordering=1,
            values=[dict(value=0, name="Normal", flags=0x2)],
        ),
        dict(
            tag="ital",
            name="Italic",
            ordering=2,
            values=[
                dict(value=1.0, name="Italic", flags=0)
                if italic
                else dict(value=0.0, name="Regular", flags=0x2, linkedValue=1.0)
            ],
        ),
    ]
    buildStatTable(var_font, stat_axes)

    out_otf = OUTPUT_DIR / f"{family_compact}-{ps_suffix}.otf"
    out_woff2 = OUTPUT_DIR / f"{family_compact}-{ps_suffix}.woff2"

    if is_mono:
        var_font.save(inter_otf)
        subset_and_export(inter_otf, out_otf, out_woff2, layout_features=MONO_SAFE_FEATURES)
        inter_otf.unlink(missing_ok=True)
    else:
        var_font.save(inter_otf)
        print(f"Injecting chws / vchw contextual spacing ({style_label})...")
        asyncio.run(apply_chws(inter_otf, chws_otf))
        inter_otf.unlink(missing_ok=True)
        subset_and_export(chws_otf, out_otf, out_woff2, layout_features=["*"])
        chws_otf.unlink(missing_ok=True)

    return out_otf


def build_sans_variable_fonts(style: str = "both") -> list[Path]:
    glyphs_path, sans_masters_dir = ensure_variable_sources("sans")
    print("\n=== Building Holon Sans Variable Fonts (2-File Architecture) ===")
    t0 = time.time()
    gs_font = GSFont(str(glyphs_path))
    print(f"Loaded Glyphs source in {time.time() - t0:.1f}s.")

    ds = to_designspace(gs_font)
    ufo_thin, ufo_reg, ufo_bold = ds.sources[0].font, ds.sources[1].font, ds.sources[2].font
    ufos = [ufo_thin, ufo_reg, ufo_bold]

    for u in ufos:
        u.info.familyName = SANS_FAMILY
        _add_vertical_semicolon_to_ufo(u)

    for gname in INITIAL_SYNC_GLYPHS:
        if gname in ufo_reg:
            ufo_thin[gname] = ufo_reg[gname].copy()
            ufo_bold[gname] = ufo_reg[gname].copy()

    added_latin = _merge_missing_sans_ufo_glyphs(ufo_thin, ufo_reg, ufo_bold, sans_masters_dir)
    print(f"Merged {added_latin} additional Latin/symbol glyphs from IBM Plex Sans UFO masters.")

    for u in ufos:
        _apply_ufo_dual_scale(u)

    # Map CJK Compatibility Ideographs (U+F900..U+FAFF)
    code_to_gname = {u: g.name for g in ufo_reg for u in (g.unicodes or [])}
    for code in range(0xF900, 0xFB00):
        if code not in code_to_gname:
            d = unicodedata.normalize("NFKD", chr(code))
            if len(d) == 1 and ord(d) in code_to_gname:
                cg = code_to_gname[ord(d)]
                for ufo in ufos:
                    if cg in ufo:
                        ufo[cg].unicodes = list(ufo[cg].unicodes or []) + [code]

    built: list[Path] = []
    if style in ("roman", "both"):
        ufo_gp = _make_grade_master(ufo_reg, ufo_bold, 0.15, "Regular Grade+", family_name=SANS_FAMILY)
        ufo_gn = _make_grade_master(ufo_reg, ufo_thin, 0.15, "Regular Grade-", family_name=SANS_FAMILY)
        ds_rom = _make_variable_designspace(ufo_thin, ufo_reg, ufo_bold, ufo_gp, ufo_gn, italic=False, family_name=SANS_FAMILY)
        built.append(_compile_and_export_vf(ds_rom, False, [ufo_thin, ufo_reg, ufo_bold, ufo_gp, ufo_gn], family_name=SANS_FAMILY))

    if style in ("italic", "both"):
        u_t_it = _make_slanted_master(ufo_thin, "Thin Italic")
        u_r_it = _make_slanted_master(ufo_reg, "Regular Italic")
        u_b_it = _make_slanted_master(ufo_bold, "Bold Italic")
        u_gp_it = _make_grade_master(u_r_it, u_b_it, 0.15, "Regular Italic Grade+", family_name=SANS_FAMILY)
        u_gn_it = _make_grade_master(u_r_it, u_t_it, 0.15, "Regular Italic Grade-", family_name=SANS_FAMILY)
        ds_it = _make_variable_designspace(u_t_it, u_r_it, u_b_it, u_gp_it, u_gn_it, italic=True, family_name=SANS_FAMILY)
        built.append(_compile_and_export_vf(ds_it, True, [u_t_it, u_r_it, u_b_it, u_gp_it, u_gn_it], family_name=SANS_FAMILY))

    return built


def build_mono_variable_fonts(style: str = "both") -> list[Path]:
    glyphs_path, mono_masters_dir = ensure_variable_sources("mono")
    print("\n=== Building Holon Mono Variable Fonts (2-File Architecture) ===")
    t0 = time.time()
    gs_font = GSFont(str(glyphs_path))
    print(f"Loaded Glyphs source in {time.time() - t0:.1f}s.")

    ds = to_designspace(gs_font)
    u_jp_thin, u_jp_reg, u_jp_bold = ds.sources[0].font, ds.sources[1].font, ds.sources[2].font

    for u in (u_jp_thin, u_jp_reg, u_jp_bold):
        u.info.familyName = MONO_FAMILY
        _add_vertical_semicolon_to_ufo(u)

    for gname in INITIAL_SYNC_GLYPHS:
        if gname in u_jp_reg:
            u_jp_thin[gname] = u_jp_reg[gname].copy()
            u_jp_bold[gname] = u_jp_reg[gname].copy()

    code_to_gname = {u: g.name for g in u_jp_reg for u in (g.unicodes or [])}
    for code in range(0xF900, 0xFB00):
        if code not in code_to_gname:
            d = unicodedata.normalize("NFKD", chr(code))
            if len(d) == 1 and ord(d) in code_to_gname:
                cg = code_to_gname[ord(d)]
                for ufo in (u_jp_thin, u_jp_reg, u_jp_bold):
                    if cg in ufo:
                        ufo[cg].unicodes = list(ufo[cg].unicodes or []) + [code]

    built: list[Path] = []

    if style in ("roman", "both"):
        u_t = copy.deepcopy(u_jp_thin)
        u_r = copy.deepcopy(u_jp_reg)
        u_b = copy.deepcopy(u_jp_bold)

        for u in (u_t, u_r, u_b):
            _apply_ufo_mono_cjk_transform(u, italic=False)

        mo_t = ufoLib2.Font.open(mono_masters_dir / "IBM Plex Mono Var-Thin.ufo")
        mo_r = ufoLib2.Font.open(mono_masters_dir / "IBM Plex Mono Var-Regular.ufo")
        mo_b = ufoLib2.Font.open(mono_masters_dir / "IBM Plex Mono Var-Bold.ufo")

        _merge_mono_variable_latin(u_t, mo_t, italic=False)
        _merge_mono_variable_latin(u_r, mo_r, italic=False)
        _merge_mono_variable_latin(u_b, mo_b, italic=False)

        u_gp = _make_grade_master(u_r, u_b, 0.15, "Regular Grade+", family_name=MONO_FAMILY)
        u_gn = _make_grade_master(u_r, u_t, 0.15, "Regular Grade-", family_name=MONO_FAMILY)
        ds_rom = _make_variable_designspace(u_t, u_r, u_b, u_gp, u_gn, italic=False, family_name=MONO_FAMILY)
        built.append(_compile_and_export_vf(ds_rom, False, [u_t, u_r, u_b, u_gp, u_gn], family_name=MONO_FAMILY))

    if style in ("italic", "both"):
        u_t_it = copy.deepcopy(u_jp_thin)
        u_r_it = copy.deepcopy(u_jp_reg)
        u_b_it = copy.deepcopy(u_jp_bold)

        for u in (u_t_it, u_r_it, u_b_it):
            _apply_ufo_mono_cjk_transform(u, italic=True)

        mo_t_it = ufoLib2.Font.open(mono_masters_dir / "IBM Plex Mono Var-Thin Italic.ufo")
        mo_r_it = ufoLib2.Font.open(mono_masters_dir / "IBM Plex Mono Var-Italic.ufo")
        mo_b_it = ufoLib2.Font.open(mono_masters_dir / "IBM Plex Mono Var-Bold Italic.ufo")

        _merge_mono_variable_latin(u_t_it, mo_t_it, italic=True)
        _merge_mono_variable_latin(u_r_it, mo_r_it, italic=True)
        _merge_mono_variable_latin(u_b_it, mo_b_it, italic=True)

        u_gp_it = _make_grade_master(u_r_it, u_b_it, 0.15, "Regular Italic Grade+", family_name=MONO_FAMILY)
        u_gn_it = _make_grade_master(u_r_it, u_t_it, 0.15, "Regular Italic Grade-", family_name=MONO_FAMILY)
        ds_it = _make_variable_designspace(u_t_it, u_r_it, u_b_it, u_gp_it, u_gn_it, italic=True, family_name=MONO_FAMILY)
        built.append(_compile_and_export_vf(ds_it, True, [u_t_it, u_r_it, u_b_it, u_gp_it, u_gn_it], family_name=MONO_FAMILY))

    return built


def build_variable_fonts(family: str = "all", style: str = "both") -> list[Path]:
    built: list[Path] = []
    if family in ("sans", "sans-variable", "all"):
        built.extend(build_sans_variable_fonts(style=style))
    if family in ("mono", "mono-variable", "all"):
        built.extend(build_mono_variable_fonts(style=style))
    return built


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Build Holon Sans (Static & Variable) and Holon Mono (Static & Variable).")
    parser.add_argument(
        "--family",
        choices=["sans", "mono", "sans-variable", "mono-variable", "variable", "all"],
        default="sans",
        help="Font family to build (default: sans; use 'variable' for both VFs, 'all' for full suite)",
    )
    parser.add_argument(
        "--weight",
        choices=WEIGHTS + ["all"],
        default="Regular",
        help="Weight to build for static fonts (default: Regular, or 'all')",
    )
    parser.add_argument(
        "--italic",
        action="store_true",
        help="Build Italic style for static fonts",
    )
    parser.add_argument(
        "--all-styles",
        action="store_true",
        help="Build all weights and styles (Upright and Italic)",
    )
    parser.add_argument(
        "--var-style",
        choices=["roman", "italic", "both"],
        default="both",
        help="Variable font style to build when --family is variable, mono-variable, sans-variable or all (default: both)",
    )
    args = parser.parse_args()

    weights = WEIGHTS if (args.all_styles or args.weight == "all") else [args.weight]

    if args.family in ("sans", "all"):
        for w in weights:
            if args.all_styles:
                build_sans_style(w, italic=False)
                build_sans_style(w, italic=True)
            else:
                build_sans_style(w, italic=args.italic)

    if args.family in ("mono", "all"):
        for w in weights:
            if args.all_styles:
                build_mono_style(w, italic=False)
                build_mono_style(w, italic=True)
            else:
                build_mono_style(w, italic=args.italic)

    if args.family in ("sans-variable", "mono-variable", "variable", "all"):
        target_vf_family = "sans" if args.family == "sans-variable" else ("mono" if args.family == "mono-variable" else "all")
        build_variable_fonts(family=target_vf_family, style=args.var_style)


if __name__ == "__main__":
    main()
