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
Generates high-resolution specimen cards verifying:
1. Typography & Latin/CJK balance (0.97x CJK, 1.02x Latin)
2. Contextual half-width spacing (chws) including Ideographic Space (U+3000)
3. Italic style with 11.0° oblique slant applied to Japanese ideographs and kana
4. Vertical writing layout with vertical glyph substitutions (vert/vrt2)
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
    """Render a horizontal text run with HarfBuzz shaping and FreeType rasterization."""
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


def draw_text_vertical(
    image: Image.Image,
    font_path: Path,
    text: str,
    font_size: int,
    pos: tuple[int, int],
    features: dict | None = None,
    color: tuple[int, int, int] = (30, 30, 30),
) -> int:
    """Render a vertical text run with HarfBuzz shaping (TTB) and FreeType rasterization."""
    features = features or {"vert": True, "vrt2": True}

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
    buf.direction = "ttb"
    buf.script = "Hani"
    buf.language = "ja"
    hb.shape(hb_font, buf, features)

    x, y = pos
    x_cursor = x * 64
    y_cursor = y * 64

    for info, p in zip(buf.glyph_infos, buf.glyph_positions):
        face.load_glyph(
            info.codepoint,
            freetype.FT_LOAD_RENDER | freetype.FT_LOAD_TARGET_NORMAL | freetype.FT_LOAD_VERTICAL_LAYOUT,
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

    return int((y_cursor - y * 64) / 64)


def create_typography_specimen() -> Path:
    """Generate comprehensive typography specimen showing Japanese/Latin mixture and extended glyphs."""
    width, height = 1200, 780
    img = Image.new("RGBA", (width, height), (248, 249, 250, 255))
    draw = ImageDraw.Draw(img)

    font_reg = FONTS_DIR / "HolonSans-Regular.ttf"
    font_bold = FONTS_DIR / "HolonSans-Bold.ttf"
    font_italic = FONTS_DIR / "HolonSans-RegularItalic.ttf"

    # Header Card
    draw.rectangle([(40, 30), (1160, 110)], fill=(255, 255, 255, 255), outline=(225, 228, 232, 255), width=1)
    draw_text_hb(img, font_bold, "Holon Sans — Typography & Visual Balance Specimen", 28, (65, 75), color=(15, 23, 42))

    # Main Body Card
    draw.rectangle([(40, 130), (1160, 500)], fill=(255, 255, 255, 255), outline=(225, 228, 232, 255), width=1)

    draw_text_hb(img, font_bold, "双方向スケーリング調整: 和文字 0.97x（縮小） ＋ 欧文字 1.02x（拡大）", 22, (65, 175), color=(37, 99, 235))

    p1 = "Holon Sans（ホロン・サンズ）は、和文の圧迫感を抑え、欧文との美しい調和を追求したフォントです。"
    draw_text_hb(img, font_reg, p1, 20, (65, 220), color=(51, 65, 85))

    p2 = "Modern UI design requires seamless balance between Latin alphabets and Japanese kanji/kana."
    draw_text_hb(img, font_reg, p2, 19, (65, 260), color=(71, 85, 105))

    p3 = "和文字を0.97倍に引き締めて中央配置し、欧文を1.02倍に調整。双方が一方的に拡大・縮小されない自然な混植です。"
    draw_text_hb(img, font_reg, p3, 20, (65, 305), color=(51, 65, 85))

    p4 = "Sphinx of black quartz, judge my vow. 1234567890 (0123456789) [A-Z, a-z] {+ - * / = % &}"
    draw_text_hb(img, font_reg, p4, 19, (65, 345), color=(71, 85, 105))

    p5 = "イタリック混植テスト: 全体と部分の哲学。The term Holon represents a whole that is part of a larger whole."
    draw_text_hb(img, font_italic, p5, 19, (65, 390), color=(30, 41, 59))

    p6 = "「『美しい約物の配置』と（洗練された組版）が、アプリの体験価値を一段階引き上げます。」"
    draw_text_hb(img, font_reg, p6, 20, (65, 435), features={"chws": True}, color=(15, 23, 42))

    # Extended Glyphs Card
    draw.rectangle([(40, 520), (1160, 740)], fill=(255, 255, 255, 255), outline=(225, 228, 232, 255), width=1)
    draw_text_hb(img, font_bold, "マージされた拡張文字セット（キリル文字・通貨記号・発音区別符）", 18, (65, 555), color=(16, 185, 129))

    line_curr = "Currencies:   $ 628,000   € 450,000   ¥ 1,280,000   £ 380,000   ₽ 500,000   ₴ 240,000"
    draw_text_hb(img, font_reg, line_curr, 18, (65, 595), color=(30, 41, 59))

    line_cyr = "Cyrillic:     Съешь же ещё этих мягких французских булок, да выпей чаю. (Привет, мир!)"
    draw_text_hb(img, font_reg, line_cyr, 18, (65, 635), color=(30, 41, 59))

    line_acc = "Diacritics:   Ångström, café, naïve, façade, Zürich, Łódź, São Paulo, Đà Nẵng, Miloš"
    draw_text_hb(img, font_reg, line_acc, 18, (65, 675), color=(30, 41, 59))

    out_path = SPECIMENS_DIR / "specimen_typography.png"
    img.save(out_path)
    print(f"Created: {out_path}")
    return out_path


def create_chws_comparison_specimen() -> Path:
    """Generate specimen card demonstrating chws compaction including fullwidth space (U+3000)."""
    width, height = 1200, 680
    img = Image.new("RGBA", (width, height), (248, 249, 250, 255))
    draw = ImageDraw.Draw(img)

    font_reg = FONTS_DIR / "HolonSans-Regular.ttf"
    font_bold = FONTS_DIR / "HolonSans-Bold.ttf"

    draw.rectangle([(40, 30), (1160, 100)], fill=(255, 255, 255, 255), outline=(225, 228, 232, 255), width=1)
    draw_text_hb(img, font_bold, "Holon Sans — 約物半角ツメ（chws）＆ 全角スペース隣接検証", 24, (65, 68), color=(15, 23, 42))

    sample_consec = "連続約物: 「「連続開き括弧」」。（閉じ括弧と句点）"
    sample_space_1 = "全角スペース隣接: 「東京」　「京都」。（全角スペースと約物）"
    sample_space_2 = "約物混在: 開き「　全角スペース　」閉じ、　読点と空白、"

    # Card 1: chws OFF
    draw.rectangle([(40, 120), (1160, 370)], fill=(255, 255, 255, 255), outline=(226, 232, 240, 255), width=1)
    draw.rectangle([(65, 140), (210, 168)], fill=(239, 68, 68, 255))
    draw_text_hb(img, font_bold, "chws OFF (全角固定)", 13, (75, 160), color=(255, 255, 255))
    draw_text_hb(img, font_reg, "約物同士や全角スペースが並んだ時に、不要な余白が重複して間延びします", 14, (225, 160), color=(100, 116, 139))

    draw_text_hb(img, font_reg, sample_consec, 24, (65, 215), features={"chws": False}, color=(51, 65, 85))
    draw_text_hb(img, font_reg, sample_space_1, 22, (65, 265), features={"chws": False}, color=(71, 85, 105))
    draw_text_hb(img, font_reg, sample_space_2, 20, (65, 315), features={"chws": False}, color=(100, 116, 139))

    # Card 2: chws ON
    draw.rectangle([(40, 390), (1160, 640)], fill=(255, 255, 255, 255), outline=(59, 130, 246, 255), width=2)
    draw.rectangle([(65, 410), (210, 438)], fill=(37, 99, 235, 255))
    draw_text_hb(img, font_bold, "chws ON (自動ツメ)", 13, (75, 430), color=(255, 255, 255))
    draw_text_hb(img, font_bold, "前後の約物や全角スペース（U+3000）を認識し、余白を自動的に半角に詰めて美しく整えます", 14, (225, 430), color=(37, 99, 235))

    draw_text_hb(img, font_reg, sample_consec, 24, (65, 485), features={"chws": True}, color=(15, 23, 42))
    draw_text_hb(img, font_reg, sample_space_1, 22, (65, 535), features={"chws": True}, color=(30, 41, 59))
    draw_text_hb(img, font_reg, sample_space_2, 20, (65, 585), features={"chws": True}, color=(51, 65, 85))

    out_path = SPECIMENS_DIR / "specimen_chws_comparison.png"
    img.save(out_path)
    print(f"Created: {out_path}")
    return out_path


def create_italic_oblique_specimen() -> Path:
    """Generate specimen card demonstrating 11.0 degree oblique slant on Japanese characters."""
    width, height = 1200, 560
    img = Image.new("RGBA", (width, height), (248, 249, 250, 255))
    draw = ImageDraw.Draw(img)

    font_reg = FONTS_DIR / "HolonSans-Regular.ttf"
    font_it = FONTS_DIR / "HolonSans-RegularItalic.ttf"
    font_bold = FONTS_DIR / "HolonSans-Bold.ttf"

    draw.rectangle([(40, 30), (1160, 100)], fill=(255, 255, 255, 255), outline=(225, 228, 232, 255), width=1)
    draw_text_hb(img, font_bold, "Holon Sans — 和文イタリック（11.0° オブリーク傾斜）", 24, (65, 68), color=(15, 23, 42))

    # Upright Card
    draw.rectangle([(40, 120), (1160, 310)], fill=(255, 255, 255, 255), outline=(226, 232, 240, 255), width=1)
    draw_text_hb(img, font_bold, "Regular (直立・Upright)", 16, (65, 155), color=(37, 99, 235))
    sample_text = "日本語も英語も美しく傾斜。Holon Sans: Expressive typography with 11° slant. 0123456789"
    draw_text_hb(img, font_reg, sample_text, 22, (65, 210), color=(15, 23, 42))
    draw_text_hb(img, font_reg, "「吾輩は猫である。名前はまだ無い。」 The quick brown fox jumps over the lazy dog.", 19, (65, 255), color=(71, 85, 105))

    # Italic Card
    draw.rectangle([(40, 330), (1160, 520)], fill=(255, 255, 255, 255), outline=(147, 51, 234, 255), width=2)
    draw_text_hb(img, font_bold, "Regular Italic (欧文イタリック ＋ 和文11.0° オブリーク)", 16, (65, 365), color=(147, 51, 234))
    draw_text_hb(img, font_it, sample_text, 22, (65, 420), color=(15, 23, 42))
    draw_text_hb(img, font_it, "「吾輩は猫である。名前はまだ無い。」 The quick brown fox jumps over the lazy dog.", 19, (65, 465), color=(71, 85, 105))

    out_path = SPECIMENS_DIR / "specimen_italic_oblique.png"
    img.save(out_path)
    print(f"Created: {out_path}")
    return out_path


def create_vertical_specimen() -> Path:
    """Generate specimen card demonstrating vertical writing layout with OpenType vert/vrt2."""
    width, height = 1200, 840
    img = Image.new("RGBA", (width, height), (248, 249, 250, 255))
    draw = ImageDraw.Draw(img)

    font_reg = FONTS_DIR / "HolonSans-Regular.ttf"
    font_bold = FONTS_DIR / "HolonSans-Bold.ttf"

    draw.rectangle([(40, 30), (1160, 100)], fill=(255, 255, 255, 255), outline=(225, 228, 232, 255), width=1)
    draw_text_hb(img, font_bold, "Holon Sans — 縦書き組版（Vertical Layout / vert・vrt2 対応）", 24, (65, 68), color=(15, 23, 42))

    # Main Vertical Container Card
    draw.rectangle([(40, 120), (1160, 800)], fill=(255, 255, 255, 255), outline=(226, 232, 240, 255), width=1)

    # Explanation header inside card
    draw_text_hb(img, font_bold, "縦書きフィーチャー（vert / vrt2）および縦書きメトリクス（vmtx / vhea）による完全対応", 16, (65, 155), color=(37, 99, 235))
    draw_text_hb(img, font_reg, "約物（「」やー、句読点）の位置が縦書き用に自動回転・右上に再配置されます", 14, (65, 185), color=(100, 116, 139))

    # Render multiple vertical columns (traditional right-to-left column progression)
    columns = [
        (1050, "『ホロン・サンズ』縦書きの美学。"),
        (980, "国境を越え、文字と文字が響き合う。"),
        (910, "「吾輩は猫である。名前はまだ無い。"),
        (840, "どこで生れたかとんと見当がつかぬ。"),
        (770, "何でも薄暗いじめじめした所で"),
        (700, "ニャーニャー泣いていた事だけは記憶している。」"),
        (630, "縦書き約物テスト: 「（東京都）」ー新宿・渋谷。"),
        (560, "数字とアルファベット: ２０２６年 Ｈｏｌｏｎ Ｓａｎｓ。"),
    ]

    for col_x, col_text in columns:
        draw_text_vertical(img, font_reg, col_text, 24, (col_x, 230), features={"vert": True, "vrt2": True})

    # Side commentary panel (left side)
    draw.rectangle([(65, 230), (480, 750)], fill=(241, 245, 249, 255), outline=(203, 213, 225, 255), width=1)
    draw_text_hb(img, font_bold, "縦書き仕様のポイント", 18, (90, 265), color=(15, 23, 42))
    points = [
        "・vert / vrt2 による縦書き字形置換",
        "・かぎ括弧「」や波ダッシュ〜、音引きーの縦回転",
        "・読点（、）句点（。）の右上アキ自動配置",
        "・vmtx テーブルによる縦送り幅 1000 の統一",
        "・全角英数・記号の縦組み垂直アライメント",
        "・電子書籍・書籍・縦書きUIへの完全適応",
    ]
    py = 315
    for pt in points:
        draw_text_hb(img, font_reg, pt, 15, (90, py), color=(51, 65, 85))
        py += 45

    out_path = SPECIMENS_DIR / "specimen_vertical.png"
    img.save(out_path)
    print(f"Created: {out_path}")
    return out_path


def main():
    print("=== Generating Visual Specimens for Holon Sans ===")
    p1 = create_typography_specimen()
    p2 = create_chws_comparison_specimen()
    p3 = create_italic_oblique_specimen()
    p4 = create_vertical_specimen()
    print("All specimens successfully generated!")


if __name__ == "__main__":
    main()
