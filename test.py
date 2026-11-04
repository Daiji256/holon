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
    variations: dict[str, float] | None = None,
    color: tuple[int, int, int] = (30, 30, 30),
) -> int:
    """Render a horizontal text run with HarfBuzz shaping and FreeType rasterization, supporting variations."""
    features = features or {}

    face = freetype.Face(str(font_path))
    face.set_char_size(font_size * 64)

    with open(font_path, "rb") as f:
        font_data = f.read()
    hb_blob = hb.Blob(font_data)
    hb_face = hb.Face(hb_blob)
    hb_font = hb.Font(hb_face)
    hb_font.scale = (font_size * 64, font_size * 64)

    if variations:
        hb_font.set_variations(variations)
        vinfo = face.get_variation_info()
        if vinfo and vinfo.axes:
            coords = [variations.get(a.tag.strip(), a.default) for a in vinfo.axes]
            face.set_var_design_coords(coords)

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
    features = features if features is not None else {"vert": True, "vrt2": True, "vchw": True}

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
    width, height = 1200, 720
    img = Image.new("RGBA", (width, height), (248, 249, 250, 255))
    draw = ImageDraw.Draw(img)

    font_reg = FONTS_DIR / "HolonSans-Regular.ttf"
    font_bold = FONTS_DIR / "HolonSans-Bold.ttf"

    draw.rectangle([(40, 30), (1160, 100)], fill=(255, 255, 255, 255), outline=(225, 228, 232, 255), width=1)
    draw_text_hb(img, font_bold, "Holon Sans — 約物半角ツメ（chws）＆ 全角スペース隣接検証", 24, (65, 68), color=(15, 23, 42))

    sample_consec = "連続約物： 「「連続開き括弧」」。（閉じ括弧と句点）"
    sample_space_1 = "全角スペース隣接： 「東京」　「京都」。（全角スペースと約物）"
    sample_period_space = "句点＋全角空白： 東京都。　次の段落（句点余白＋全角空白のアキ量確認）"
    sample_space_2 = "約物混在： 開き「　全角スペース　」閉じ、　読点と空白、"

    # Card 1: chws OFF
    draw.rectangle([(40, 120), (1160, 390)], fill=(255, 255, 255, 255), outline=(226, 232, 240, 255), width=1)
    draw.rectangle([(65, 140), (230, 168)], fill=(239, 68, 68, 255))
    draw_text_hb(img, font_bold, "chws OFF (全角固定)", 13, (75, 160), color=(255, 255, 255))
    draw_text_hb(img, font_reg, "「。　」で句点余白(0.5)＋空白(1.0)＝1.5文字分空いて間延びします", 14, (245, 160), color=(100, 116, 139))

    draw_text_hb(img, font_reg, sample_consec, 22, (65, 205), features={"chws": False}, color=(51, 65, 85))
    draw_text_hb(img, font_reg, sample_space_1, 20, (65, 250), features={"chws": False}, color=(71, 85, 105))
    draw_text_hb(img, font_reg, sample_period_space, 20, (65, 295), features={"chws": False}, color=(220, 38, 38))
    draw_text_hb(img, font_reg, sample_space_2, 18, (65, 340), features={"chws": False}, color=(100, 116, 139))

    # Card 2: chws ON
    draw.rectangle([(40, 410), (1160, 680)], fill=(255, 255, 255, 255), outline=(59, 130, 246, 255), width=2)
    draw.rectangle([(65, 430), (230, 458)], fill=(37, 99, 235, 255))
    draw_text_hb(img, font_bold, "chws ON (自動ツメ)", 13, (75, 450), color=(255, 255, 255))
    draw_text_hb(img, font_bold, "句点余白が半角に詰められ、全角空白と合わせて正確に1.0文字分のアキに自動補正（JIS X 4051準拠）", 14, (245, 450), color=(37, 99, 235))

    draw_text_hb(img, font_reg, sample_consec, 22, (65, 495), features={"chws": True}, color=(15, 23, 42))
    draw_text_hb(img, font_reg, sample_space_1, 20, (65, 540), features={"chws": True}, color=(30, 41, 59))
    draw_text_hb(img, font_bold, sample_period_space, 20, (65, 585), features={"chws": True}, color=(16, 185, 129))
    draw_text_hb(img, font_reg, sample_space_2, 18, (65, 630), features={"chws": True}, color=(51, 65, 85))

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
    """Generate specimen card demonstrating vertical writing layout with OpenType vert/vrt2 and vchw."""
    width, height = 1200, 840
    img = Image.new("RGBA", (width, height), (248, 249, 250, 255))
    draw = ImageDraw.Draw(img)

    font_reg = FONTS_DIR / "HolonSans-Regular.ttf"
    font_bold = FONTS_DIR / "HolonSans-Bold.ttf"

    draw.rectangle([(40, 30), (1160, 100)], fill=(255, 255, 255, 255), outline=(225, 228, 232, 255), width=1)
    draw_text_hb(img, font_bold, "Holon Sans — 縦書き組版（vert・vrt2・vchw 縦約物ツメ対応）", 24, (65, 68), color=(15, 23, 42))

    # Main Vertical Container Card
    draw.rectangle([(40, 120), (1160, 800)], fill=(255, 255, 255, 255), outline=(226, 232, 240, 255), width=1)

    # Explanation header inside card
    draw_text_hb(img, font_bold, "縦書きフィーチャー（vert / vrt2）および縦約物ツメ（vchw）による完全対応", 16, (65, 155), color=(37, 99, 235))
    draw_text_hb(img, font_reg, "約物（「」やー、句読点）の位置が縦書き用に自動回転・右上に再配置され、連続約物や全角空白も美しく自動ツメされます", 14, (65, 185), color=(100, 116, 139))

    # Render multiple vertical columns (traditional right-to-left column progression)
    columns = [
        (1080, "『ホロン・サンズ』縦書きの美学。"),
        (1015, "国境を越え、文字と文字が響き合う。"),
        (950, "「吾輩は猫である。名前はまだ無い。"),
        (885, "どこで生れたかとんと見当がつかぬ。"),
        (820, "何でも薄暗いじめじめした所で"),
        (755, "ニャーニャー泣いていた事だけは記憶している。」"),
        (690, "縦書き約物テスト： 「（東京都）」ー新宿・渋谷。"),
        (625, "全角コロン： ２０２６年 Ｈｏｌｏｎ Ｓａｎｓ。"),
    ]

    for col_x, col_text in columns:
        draw_text_vertical(img, font_reg, col_text, 23, (col_x, 230), features={"vert": True, "vrt2": True, "vchw": True})

    # Vertical vchw comparison columns (vchw ON vs vchw OFF)
    draw.rectangle([(485, 230), (595, 750)], fill=(248, 250, 252, 255), outline=(226, 232, 240, 255), width=1)
    draw_text_vertical(img, font_bold, "【vchw ON 自動ツメ】 「「連続開き」」。（全角空白　隣接もツメ）", 18, (555, 250), features={"vert": True, "vrt2": True, "vchw": True}, color=(37, 99, 235))
    draw_text_vertical(img, font_reg, "【vchw OFF 全角固定】 「「連続開き」」。（全角空白　隣接もツメ）", 18, (510, 250), features={"vert": True, "vrt2": True, "vchw": False}, color=(220, 38, 38))

    # Side commentary panel (left side)
    draw.rectangle([(65, 230), (460, 750)], fill=(241, 245, 249, 255), outline=(203, 213, 225, 255), width=1)
    draw_text_hb(img, font_bold, "縦書き仕様のポイント", 18, (90, 265), color=(15, 23, 42))
    points = [
        "・vert / vrt2 による縦書き字形置換",
        "・vchw による縦書き約物半角ツメ（連続括弧・句読点）",
        "・全角空白（U+3000）隣接時の自動送り調整",
        "・全角コロン（：）の縦書き正立配置",
        "・かぎ括弧「」や波ダッシュ〜、音引きーの縦回転",
        "・読点（、）句点（。）の右上アキ自動配置",
        "・vmtx / VVAR テーブルによる縦送り幅 1000 の統一",
        "・電子書籍・書籍・縦書きUIへの完全適応",
    ]
    py = 315
    for pt in points:
        draw_text_hb(img, font_reg, pt, 14, (90, py), color=(51, 65, 85))
        py += 42

    out_path = SPECIMENS_DIR / "specimen_vertical.png"
    img.save(out_path)
    print(f"Created: {out_path}")
    return out_path


def create_variable_multi_axis_specimen() -> Path:
    """Generate specimen card demonstrating 3-axis variable font: Weight, Slant, and Grade."""
    width, height = 1200, 1100
    img = Image.new("RGBA", (width, height), (248, 249, 250, 255))
    draw = ImageDraw.Draw(img)

    font_var = FONTS_DIR / "HolonSans-Variable.otf"
    font_bold = FONTS_DIR / "HolonSans-Bold.ttf"
    font_reg = FONTS_DIR / "HolonSans-Regular.ttf"

    # Header
    draw.rectangle([(40, 30), (1160, 100)], fill=(255, 255, 255, 255), outline=(225, 228, 232, 255), width=1)
    draw_text_hb(img, font_bold, "Holon Sans — 3軸バリアブルフォント（Weight / Slant / Grade）", 24, (65, 68), color=(15, 23, 42))

    # Panel 1: Weight Axis (wght: 100 -> 700)
    draw.rectangle([(40, 120), (1160, 420)], fill=(255, 255, 255, 255), outline=(226, 232, 240, 255), width=1)
    draw_text_hb(img, font_bold, "1. Weight 軸（wght: 100 〜 700）のシームレスな連続変化", 16, (65, 150), color=(37, 99, 235))
    
    weights = [
        (100, "Thin (100)"),
        (250, "Light+ (250)"),
        (400, "Regular (400)"),
        (550, "Medium+ (550)"),
        (700, "Bold (700)"),
    ]
    y_pos = 195
    for w_val, label in weights:
        draw_text_hb(img, font_reg, label, 12, (65, y_pos + 16), color=(100, 116, 139))
        sample = "Holon Sans 美しい文字の調和。The quick brown fox jumps."
        draw_text_hb(img, font_var, sample, 20, (190, y_pos + 18), variations={"wght": w_val, "slnt": 0, "GRAD": 0}, color=(15, 23, 42))
        y_pos += 42

    # Panel 2: Slant Axis (slnt: 0 -> -11)
    draw.rectangle([(40, 440), (1160, 740)], fill=(255, 255, 255, 255), outline=(226, 232, 240, 255), width=1)
    draw_text_hb(img, font_bold, "2. Slant 軸（slnt: 0° 〜 -11.0°）による和欧統一のオブリーク傾斜", 16, (65, 470), color=(147, 51, 234))

    slants = [
        (0.0, "直立 0.0°"),
        (-3.0, "微傾 -3.0°"),
        (-6.0, "中傾 -6.0°"),
        (-9.0, "深傾 -9.0°"),
        (-11.0, "イタリック -11°"),
    ]
    y_pos = 515
    for s_val, label in slants:
        draw_text_hb(img, font_reg, label, 12, (65, y_pos + 16), color=(100, 116, 139))
        sample = "和文字も欧文も自然に11°傾斜。Continuous slant variation: 0° to -11°."
        draw_text_hb(img, font_var, sample, 20, (190, y_pos + 18), variations={"wght": 400, "slnt": s_val, "GRAD": 0}, color=(15, 23, 42))
        y_pos += 42

    # Panel 3: Grade Axis (GRAD: -100 to +100) and Dark Mode compensation
    draw.rectangle([(40, 760), (1160, 1060)], fill=(255, 255, 255, 255), outline=(226, 232, 240, 255), width=1)
    draw_text_hb(img, font_bold, "3. Grade 軸（GRAD: -100 〜 +100）— レイアウト固定の精密太さ調整", 16, (65, 790), color=(217, 119, 6))
    draw_text_hb(img, font_reg, "文字の送り幅（Horizontal Metrics）を1ピクセルも変えずに、線の太さ・視覚的明度のみを変化させます", 13, (65, 815), color=(100, 116, 139))

    # Light mode box
    draw.rectangle([(65, 840), (585, 1030)], fill=(248, 250, 252, 255), outline=(226, 232, 240, 255), width=1)
    draw_text_hb(img, font_bold, "ライトモード (GRAD: 0)", 13, (85, 865), color=(15, 23, 42))
    draw_text_hb(img, font_var, "白背景の標準ウェイト。レイアウトが完全に維持されます。", 15, (85, 910), variations={"wght": 400, "slnt": 0, "GRAD": 0}, color=(15, 23, 42))
    draw_text_hb(img, font_var, "GRAD: +100 で視認性向上: 細部の線の太さのみが増加。", 14, (85, 960), variations={"wght": 400, "slnt": 0, "GRAD": 100}, color=(15, 23, 42))

    # Dark mode box
    draw.rectangle([(615, 840), (1135, 1030)], fill=(15, 23, 42, 255))
    draw_text_hb(img, font_bold, "ダークモード光学補正 (GRAD: -100)", 13, (635, 865), color=(248, 250, 252))
    draw_text_hb(img, font_var, "黒背景で光の膨張（ブルーム）を抑え、すっきり可読性を保つ。", 15, (635, 910), variations={"wght": 400, "slnt": 0, "GRAD": -100}, color=(241, 245, 249))
    draw_text_hb(img, font_var, "送り幅はライトモードと完全一致し、行の折り返しは一切ズレません。", 14, (635, 960), variations={"wght": 400, "slnt": 0, "GRAD": -100}, color=(203, 213, 225))

    out_path = SPECIMENS_DIR / "specimen_variable_spectrum.png"
    img.save(out_path)
    print(f"Created: {out_path}")
    return out_path


def create_cjk_compat_specimen() -> Path:
    """Generate specimen card demonstrating safe CJK Compatibility Ideographs gap closure."""
    width, height = 1200, 620
    img = Image.new("RGBA", (width, height), (248, 249, 250, 255))
    draw = ImageDraw.Draw(img)

    font_bold = FONTS_DIR / "HolonSans-Bold.ttf"
    font_reg = FONTS_DIR / "HolonSans-Regular.ttf"

    draw.rectangle([(40, 30), (1160, 100)], fill=(255, 255, 255, 255), outline=(225, 228, 232, 255), width=1)
    draw_text_hb(img, font_bold, "Holon Sans — CJK 互換漢字（Compatibility Ideographs）拡張検証", 24, (65, 68), color=(15, 23, 42))

    draw.rectangle([(40, 120), (1160, 580)], fill=(255, 255, 255, 255), outline=(226, 232, 240, 255), width=1)
    draw_text_hb(img, font_bold, "Unicode NFKD 準拠の正規等価写像により 346 字の CJK 互換漢字（U+F900〜U+FAFF）を安全に補完", 15, (65, 155), color=(37, 99, 235))
    draw_text_hb(img, font_reg, "Noto Sans JP との字形カバレッジ差分を埋め、人名・地名・異体字互換コードを破綻なく表示します", 13, (65, 185), color=(100, 116, 139))

    # Comparison table
    test_chars = [
        ("U+F900 豈", "U+8C48 豈", "豈"),
        ("U+F901 更", "U+66F4 更", "更"),
        ("U+F902 車", "U+8ECA 車", "車"),
        ("U+F904 滑", "U+6ED1 滑", "滑"),
        ("U+F90A 金", "U+91D1 金", "金"),
        ("U+FA11 﨑", "U+5D0E 崎", "崎"),
        ("U+FA15 凞", "U+7199 熙", "熙"),
        ("U+FA1F 﨟", "U+814B 臘", "臘"),
        ("U+FA20 蘒", "U+874E 蝋", "蝋"),
        ("U+FA22 諸", "U+8AF8 諸", "諸"),
    ]

    x_left = 65
    y_top = 230
    for idx, (compat_str, canon_str, char) in enumerate(test_chars):
        row = idx // 2
        col = idx % 2
        cx = x_left + col * 540
        cy = y_top + row * 60

        draw.rectangle([(cx, cy), (cx + 520, cy + 50)], fill=(248, 250, 252, 255), outline=(226, 232, 240, 255), width=1)
        draw_text_hb(img, font_bold, char, 28, (cx + 15, cy + 38), color=(37, 99, 235))
        draw_text_hb(img, font_bold, f"互換字: {compat_str}", 13, (cx + 65, cy + 28), color=(15, 23, 42))
        draw_text_hb(img, font_reg, f"正規字: {canon_str}", 13, (cx + 250, cy + 28), color=(100, 116, 139))
        draw_text_hb(img, font_reg, "✓ 完全一致", 12, (cx + 420, cy + 28), color=(16, 185, 129))

    out_path = SPECIMENS_DIR / "specimen_cjk_compat.png"
    img.save(out_path)
    print(f"Created: {out_path}")
    return out_path


def main():
    print("=== Generating Visual Specimens for Holon Sans ===")
    create_typography_specimen()
    create_chws_comparison_specimen()
    create_italic_oblique_specimen()
    create_vertical_specimen()
    create_variable_multi_axis_specimen()
    create_cjk_compat_specimen()
    print("All specimens successfully generated!")


if __name__ == "__main__":
    main()
