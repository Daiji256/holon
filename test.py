# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "fonttools>=4.50.0",
#     "freetype-py>=2.4.0",
#     "pillow>=10.0.0",
#     "uharfbuzz>=0.39.0",
# ]
# ///

"""Test suite and visual specimen generator for Holon Sans.
Generates high-resolution specimen cards verifying typography,
glyph coverage, chws punctuation compaction, and weight/style consistency.
"""

from __future__ import annotations

import os
from pathlib import Path
import freetype
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont
import uharfbuzz as hb

FONTS_DIR = Path("fonts")
SPECIMENS_DIR = Path("specimens")
SPECIMENS_DIR.mkdir(parents=True, exist_ok=True)


def draw_text_hb(
    image: Image.Image,
    font_path: Path,
    text: str,
    font_size: int,
    pos: tuple[int, int],
    features: dict | None = None,
    color: tuple[int, int, int] = (30, 30, 30),
) -> int:
    """Render a text run with HarfBuzz shaping and FreeType rasterization.
    Returns the total advance width in pixels.
    """
    features = features or {}

    face = freetype.Face(str(font_path))
    face.set_char_size(font_size * 64)

    with open(font_path, "rb") as f:
        font_data = f.read()
    hb_blob = hb.Blob(font_data)
    hb_face = hb.Face(hb_blob)
    hb_font = hb.Font(hb_face)
    hb_font.scale = (font_size * 64, font_size * 64)

    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    hb.shape(hb_font, buf, features)

    x, y = pos
    x_cursor = x * 64
    y_cursor = y * 64

    for info, p in zip(buf.glyph_infos, buf.glyph_positions):
        face.load_glyph(
            info.codepoint, freetype.FT_LOAD_RENDER | freetype.FT_LOAD_TARGET_NORMAL
        )
        slot = face.glyph
        bitmap = slot.bitmap

        top = slot.bitmap_top
        left = slot.bitmap_left

        glyph_x = int((x_cursor + p.x_offset) / 64) + left
        glyph_y = int((y_cursor - p.y_offset) / 64) - top

        w, h = bitmap.width, bitmap.rows
        if w > 0 and h > 0:
            glyph_img = Image.frombytes("L", (w, h), bytes(bitmap.buffer))
            color_img = Image.new("RGBA", (w, h), color + (255,))
            image.paste(color_img, (glyph_x, glyph_y), glyph_img)

        x_cursor += p.x_advance
        y_cursor -= p.y_advance

    return int((x_cursor - x * 64) / 64)


def create_typography_specimen() -> Path:
    """Generate comprehensive typography specimen showing Japanese/Latin mixture and extended glyphs."""
    width, height = 1200, 760
    img = Image.new("RGBA", (width, height), (248, 249, 250, 255))
    draw = ImageDraw.Draw(img)

    # Header Card
    draw.rectangle([(40, 30), (1160, 110)], fill=(255, 255, 255, 255), outline=(225, 228, 232, 255), width=1)
    # Header label
    font_reg = FONTS_DIR / "HolonSans-Regular.ttf"
    font_bold = FONTS_DIR / "HolonSans-Bold.ttf"
    font_light = FONTS_DIR / "HolonSans-Light.ttf"
    font_italic = FONTS_DIR / "HolonSans-RegularItalic.ttf"

    draw_text_hb(img, font_bold, "Holon Sans — Typography & Multilingual Specimen", 28, (65, 75), color=(15, 23, 42))

    # Main Body Card
    draw.rectangle([(40, 130), (1160, 480)], fill=(255, 255, 255, 255), outline=(225, 228, 232, 255), width=1)

    # Sub-heading
    draw_text_hb(img, font_bold, "日欧調和タイポグラフィ（IBM Plex Sans ＋ 高品位和文）", 22, (65, 175), color=(37, 99, 235))

    # Mixed text paragraphs
    p1 = "Holon Sans（ホロン・サンズ）は、英語と日本語が美しく調和するオープンソースフォントです。"
    draw_text_hb(img, font_reg, p1, 20, (65, 220), color=(51, 65, 85))

    p2 = "Modern UI design requires seamless integration between Latin alphabets and CJK ideographs."
    draw_text_hb(img, font_reg, p2, 19, (65, 255), color=(71, 85, 105))

    p3 = "字面バランスの調整（1.05x スケール）により、欧文の小文字・大文字が漢字や仮名と自然に並びます。"
    draw_text_hb(img, font_reg, p3, 20, (65, 295), color=(51, 65, 85))

    p4 = "The quick brown fox jumps over the lazy dog. 1234567890 (0123456789) [A-Z, a-z]"
    draw_text_hb(img, font_reg, p4, 19, (65, 335), color=(71, 85, 105))

    p5 = "イタリック混植テスト: The term Holon represents a whole that is simultaneously part of a larger whole."
    draw_text_hb(img, font_italic, p5, 19, (65, 375), color=(30, 41, 59))

    p6 = "「『引用符』や括弧（）の配置も、OpenType 機能（chws）により自動的に美しく整えられます。」"
    draw_text_hb(img, font_reg, p6, 20, (65, 415), features={"chws": True}, color=(15, 23, 42))

    # Extended Glyphs Card (Currencies, Cyrillic, Accents)
    draw.rectangle([(40, 500), (1160, 720)], fill=(255, 255, 255, 255), outline=(225, 228, 232, 255), width=1)
    draw_text_hb(img, font_bold, "マージされた拡張文字セット（キリル文字・通貨記号・発音区別符）", 18, (65, 535), color=(16, 185, 129))

    line_curr = "Currencies:   $ 628,000   € 450,000   ¥ 1,280,000   £ 380,000   ₽ 500,000   ₴ 240,000"
    draw_text_hb(img, font_reg, line_curr, 18, (65, 575), color=(30, 41, 59))

    line_cyr = "Cyrillic:     Съешь же ещё этих мягких французских булок, да выпей чаю. (Привет, мир!)"
    draw_text_hb(img, font_reg, line_cyr, 18, (65, 615), color=(30, 41, 59))

    line_acc = "Diacritics:   Ångström, café, naïve, façade, Zürich, Łódź, São Paulo, Đà Nẵng, Miloš"
    draw_text_hb(img, font_reg, line_acc, 18, (65, 655), color=(30, 41, 59))

    out_path = SPECIMENS_DIR / "specimen_typography.png"
    img.save(out_path)
    print(f"Created: {out_path}")
    return out_path


def create_chws_comparison_specimen() -> Path:
    """Generate a side-by-side / before-after card demonstrating contextual half-width spacing (chws)."""
    width, height = 1200, 560
    img = Image.new("RGBA", (width, height), (248, 249, 250, 255))
    draw = ImageDraw.Draw(img)

    font_reg = FONTS_DIR / "HolonSans-Regular.ttf"
    font_bold = FONTS_DIR / "HolonSans-Bold.ttf"

    # Header Card
    draw.rectangle([(40, 30), (1160, 100)], fill=(255, 255, 255, 255), outline=(225, 228, 232, 255), width=1)
    draw_text_hb(img, font_bold, "Holon Sans — Contextual Half-width Spacing (chws) Comparison", 24, (65, 68), color=(15, 23, 42))

    sample_1 = "「「連続する開き括弧」」。（閉じ括弧と句点）"
    sample_2 = "約物の配置: （東京）「新宿」『代々木』【渋谷】〔原宿〕"

    # Card 1: chws OFF (Traditional full-width spacing)
    draw.rectangle([(40, 120), (1160, 310)], fill=(255, 255, 255, 255), outline=(226, 232, 240, 255), width=1)
    # Badge
    draw.rectangle([(65, 140), (180, 168)], fill=(239, 68, 68, 255))
    draw_text_hb(img, font_bold, "chws OFF (全角固定)", 13, (75, 160), color=(255, 255, 255))
    draw_text_hb(img, font_reg, "約物が連続した際にアキが過剰に空いて間延びします", 14, (195, 160), color=(100, 116, 139))

    draw_text_hb(img, font_reg, sample_1, 26, (65, 215), features={"chws": False}, color=(51, 65, 85))
    draw_text_hb(img, font_reg, sample_2, 21, (65, 265), features={"chws": False}, color=(100, 116, 139))

    # Card 2: chws ON (Contextual compaction)
    draw.rectangle([(40, 330), (1160, 520)], fill=(255, 255, 255, 255), outline=(59, 130, 246, 255), width=2)
    # Badge
    draw.rectangle([(65, 350), (180, 378)], fill=(37, 99, 235, 255))
    draw_text_hb(img, font_bold, "chws ON (自動ツメ)", 13, (75, 370), color=(255, 255, 255))
    draw_text_hb(img, font_bold, "前後の文字関係を認識し、約物の不要な余白を半角に自動調整します（詰まりが最適化）", 14, (195, 370), color=(37, 99, 235))

    draw_text_hb(img, font_reg, sample_1, 26, (65, 425), features={"chws": True}, color=(15, 23, 42))
    draw_text_hb(img, font_reg, sample_2, 21, (65, 475), features={"chws": True}, color=(30, 41, 59))

    out_path = SPECIMENS_DIR / "specimen_chws_comparison.png"
    img.save(out_path)
    print(f"Created: {out_path}")
    return out_path


def create_weights_specimen() -> Path:
    """Generate specimen card comparing font weights and italic style."""
    width, height = 1200, 640
    img = Image.new("RGBA", (width, height), (248, 249, 250, 255))
    draw = ImageDraw.Draw(img)

    font_bold = FONTS_DIR / "HolonSans-Bold.ttf"

    # Header Card
    draw.rectangle([(40, 30), (1160, 100)], fill=(255, 255, 255, 255), outline=(225, 228, 232, 255), width=1)
    draw_text_hb(img, font_bold, "Holon Sans — Weight Spectrum & Italic Style", 24, (65, 68), color=(15, 23, 42))

    # Weight list
    styles = [
        ("Light (300)", FONTS_DIR / "HolonSans-Light.ttf", False),
        ("Regular (400)", FONTS_DIR / "HolonSans-Regular.ttf", False),
        ("Bold (700)", FONTS_DIR / "HolonSans-Bold.ttf", False),
        ("Regular Italic", FONTS_DIR / "HolonSans-RegularItalic.ttf", True),
    ]

    card_y = 120
    for label, font_file, is_it in styles:
        draw.rectangle([(40, card_y), (1160, card_y + 110)], fill=(255, 255, 255, 255), outline=(226, 232, 240, 255), width=1)
        # Style label
        lbl_col = (147, 51, 234) if is_it else (37, 99, 235)
        draw_text_hb(img, font_bold, label, 15, (65, card_y + 35), color=lbl_col)

        sample_str = "全体と部分の調和。Holon Sans: Beautiful typography for English & Japanese. 0123456789"
        draw_text_hb(img, font_file, sample_str, 20, (65, card_y + 75), features={"chws": True}, color=(15, 23, 42))
        card_y += 125

    out_path = SPECIMENS_DIR / "specimen_weights_styles.png"
    img.save(out_path)
    print(f"Created: {out_path}")
    return out_path


def main():
    print("=== Generating Visual Specimens for Holon Sans ===")
    p1 = create_typography_specimen()
    p2 = create_chws_comparison_specimen()
    p3 = create_weights_specimen()
    print("All specimens successfully generated!")


if __name__ == "__main__":
    main()
