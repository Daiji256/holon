# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "fonttools>=4.50.0",
#     "freetype-py>=2.4.0",
#     "pillow>=10.0.0",
#     "uharfbuzz>=0.39.0",
# ]
# ///

"""Test suite and visual specimen generator for Holon Mono.
Generates high-resolution specimen cards verifying:
1. Strict 2:1 duospace alignment (two halfwidth characters = one fullwidth character)
2. Box drawing characters (U+2500..U+257F) seamlessly connecting in terminal tables
3. Authentic IBM Plex Mono Italic paired with 9.0° slanted Japanese kanji and kana
4. Weight spectrum across all 8 weights (Thin to Bold)
"""

from __future__ import annotations

from pathlib import Path
import freetype
from PIL import Image, ImageDraw
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
    color: tuple[int, int, int] = (220, 220, 230),
) -> int:
    """Render a text run with HarfBuzz shaping and FreeType rasterization."""
    if not text:
        return pos[0]

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

        bx = (x_cursor + p.x_offset) // 64 + slot.bitmap_left
        by = (y_cursor - p.y_offset) // 64 - slot.bitmap_top

        if bitmap.width > 0 and bitmap.rows > 0:
            glyph_img = Image.frombytes(
                "L", (bitmap.width, bitmap.rows), bytes(bitmap.buffer)
            )
            color_img = Image.new(
                "RGBA", (bitmap.width, bitmap.rows), color + (255,)
            )
            image.paste(color_img, (bx, by), glyph_img)

        x_cursor += p.x_advance
        y_cursor += p.y_advance

    return x_cursor // 64


def generate_duospace_specimen(font_path: Path, out_path: Path) -> Path:
    """Card 1: Strict 2:1 duospace alignment and terminal table rendering."""
    w, h = 1440, 1080
    img = Image.new("RGBA", (w, h), (18, 22, 28, 255))
    draw = ImageDraw.Draw(img)

    # Header bar
    draw.rectangle([(0, 0), (w, 80)], fill=(28, 33, 40))
    draw_text_hb(img, font_path, "Holon Mono — 2:1 Duospace Programming Specimen", 24, (50, 48), color=(240, 246, 252))
    draw_text_hb(img, font_path, "Half: 550 UPM | Full: 1100 UPM", 16, (1060, 48), color=(139, 148, 158))

    # Section 1
    draw.rectangle([(50, 105), (w - 50, 145)], fill=(33, 38, 45))
    draw_text_hb(img, font_path, "1. Syntax-Highlighted Code with Japanese Comments & Column Alignment", 15, (65, 130), color=(88, 166, 255))

    code_lines = [
        ('// Rust: Holon Mono は和欧 2:1 等幅なので、インデントや列が完全一致します', (139, 148, 158)),
        ('use std::collections::HashMap; // ハッシュマップの利用', (240, 246, 252)),
        ('', (0, 0, 0)),
        ('/// ユーザープロファイルを管理する構造体', (139, 148, 158)),
        ('#[derive(Debug, Clone, Serialize)]', (255, 166, 87)),
        ('pub struct UserProfile {', (240, 246, 252)),
        ('    pub user_id:   u64,           // 一意識別子 (64bit integer)', (240, 246, 252)),
        ('    pub full_name: String,        // 氏名（全角漢字・仮名対応）', (240, 246, 252)),
        ('    pub role_code: &\'static str, // 権限グループ: "ADMIN" | "USER"', (240, 246, 252)),
        ('    pub is_active: bool,          // 有効フラグ: true = 稼働中', (240, 246, 252)),
        ('}', (240, 246, 252)),
    ]

    curr_y = 170
    for line, color in code_lines:
        if line:
            draw_text_hb(img, font_path, line, 18, (60, curr_y), color=color)
        curr_y += 28

    # Section 2: Table
    curr_y += 15
    draw.rectangle([(50, curr_y), (w - 50, curr_y + 40)], fill=(33, 38, 45))
    draw_text_hb(img, font_path, "2. Box-Drawing Characters (U+2500..U+257F) & Strict Duospace Table Verification", 15, (65, curr_y + 25), color=(88, 166, 255))
    curr_y += 55

    # Columns: 6 + 12 + 24 + 8 + 10 = 60 halfwidth units
    table_lines = [
        "┌──────┬────────────┬────────────────────────┬────────┬──────────┐",
        "│ ID   │ 氏名       │ 所属部署・担当領域     │ 権限   │ 状態     │",
        "├──────┼────────────┼────────────────────────┼────────┼──────────┤",
        "│ 0101 │ 田中　太郎 │ フロントエンド基盤開発 │ ADMIN  │ 稼働中   │",
        "│ 0102 │ 鈴木　一郎 │ クラウドインフラ統括   │ ADMIN  │ 稼働中   │",
        "│ 0103 │ 佐藤　健一 │ 自然言語処理モデル評価 │ MEMBER │ 離席中   │",
        "│ 0104 │ 高橋　美咲 │ セキュリティ監査・運用 │ MEMBER │ 休暇中   │",
        "│ 0105 │ 渡辺　直樹 │ データベース性能チュー │ MEMBER │ 稼働中   │",
        "└──────┴────────────┴────────────────────────┴────────┴──────────┘",
    ]

    for line in table_lines:
        draw_text_hb(img, font_path, line, 18, (60, curr_y), color=(126, 231, 135))
        curr_y += 23

    # Explanation note
    curr_y += 20
    draw.rectangle([(50, curr_y), (w - 50, curr_y + 65)], fill=(28, 33, 40))
    note_1 = "検証ポイント: 全角文字（漢字・仮名・全角スペース U+3000）は半角英数のちょうど2倍幅 (1100 UPM : 550 UPM)。"
    note_2 = "罫線 (┌ ─ ┬ ┐ │ ├ ┼ ┤ └ ┴ ┘) は1ピクセルの隙間もなく接続し、縦罫線 (│) の位置が完全に直立整列します。"
    draw_text_hb(img, font_path, note_1, 14, (65, curr_y + 24), color=(200, 210, 220))
    draw_text_hb(img, font_path, note_2, 14, (65, curr_y + 48), color=(200, 210, 220))

    img.save(out_path)
    print(f"Specimen generated: {out_path}")
    return out_path


def generate_italic_specimen(upright_path: Path, italic_path: Path, out_path: Path) -> Path:
    """Card 2: Upright vs Italic specimen comparing authentic Latin Italic + 9.0° slanted Japanese."""
    w, h = 1440, 850
    img = Image.new("RGBA", (w, h), (18, 22, 28, 255))
    draw = ImageDraw.Draw(img)

    # Header bar
    draw.rectangle([(0, 0), (w, 80)], fill=(28, 33, 40))
    draw_text_hb(img, upright_path, "Holon Mono — Upright vs Italic Comparison", 24, (50, 48), color=(240, 246, 252))
    draw_text_hb(img, upright_path, "Latin: IBM Plex Mono Italic | CJK: 9.0° Oblique", 15, (980, 48), color=(139, 148, 158))

    samples = [
        ("Regular (Upright)", upright_path, [
            "const message: &str = \"Hello, 世界！\"; // 厳密な 2:1 等幅モノスペース",
            "for item in &dataset { process_record(item); } // レコード処理ルーチン",
            "The quick brown fox jumps over the lazy dog. 0123456789",
            "日本語テキスト: 美しいプログラミング環境のための高品質フォント",
        ]),
        ("Italic (Native Latin Italic + 9.0° Slanted CJK)", italic_path, [
            "const message: &str = \"Hello, 世界！\"; // 厳密な 2:1 等幅モノスペース",
            "for item in &dataset { process_record(item); } // レコード処理ルーチン",
            "The quick brown fox jumps over the lazy dog. 0123456789",
            "日本語テキスト: 美しいプログラミング環境のための高品質フォント",
        ]),
    ]

    curr_y = 110
    for title, fpath, lines in samples:
        draw.rectangle([(50, curr_y), (w - 50, curr_y + 36)], fill=(33, 38, 45))
        draw_text_hb(img, fpath, title, 16, (65, curr_y + 25), color=(88, 166, 255))
        curr_y += 50

        for line in lines:
            col = (255, 166, 87) if "Hello" in line else ((126, 231, 135) if "for item" in line else (240, 246, 252))
            draw_text_hb(img, fpath, line, 20, (65, curr_y), color=col)
            curr_y += 36
        curr_y += 30

    img.save(out_path)
    print(f"Specimen generated: {out_path}")
    return out_path


def generate_weights_specimen(out_path: Path) -> Path:
    """Card 3: Weight spectrum across 8 weights (Thin to Bold)."""
    w, h = 1440, 960
    img = Image.new("RGBA", (w, h), (18, 22, 28, 255))
    draw = ImageDraw.Draw(img)

    regular_path = FONTS_DIR / "HolonMono-Regular.ttf"

    draw.rectangle([(0, 0), (w, 80)], fill=(28, 33, 40))
    draw_text_hb(img, regular_path, "Holon Mono — 8 Weight Family Spectrum", 24, (50, 48), color=(240, 246, 252))
    draw_text_hb(img, regular_path, "Thin (100) to Bold (700)", 16, (1150, 48), color=(139, 148, 158))

    weights = [
        ("Thin", 100),
        ("ExtraLight", 200),
        ("Light", 300),
        ("Regular", 400),
        ("Text", 450),
        ("Medium", 500),
        ("SemiBold", 600),
        ("Bold", 700),
    ]

    curr_y = 115
    for wname, wval in weights:
        ttf_path = FONTS_DIR / f"HolonMono-{wname}.ttf"
        if not ttf_path.exists():
            continue

        label = f"{wname:<10} ({wval})"
        sample_text = "Sphinx of black quartz, judge my vow. // 銀河鉄道の夜 0123456789"

        draw_text_hb(img, regular_path, label, 15, (55, curr_y + 18), color=(88, 166, 255))
        draw_text_hb(img, ttf_path, sample_text, 18, (240, curr_y + 18), color=(240, 246, 252))

        # Thin divider line
        draw.line([(50, curr_y + 40), (w - 50, curr_y + 40)], fill=(40, 45, 55))
        curr_y += 50

    img.save(out_path)
    print(f"Specimen generated: {out_path}")
    return out_path


def main():
    regular_path = FONTS_DIR / "HolonMono-Regular.ttf"
    italic_path = FONTS_DIR / "HolonMono-Italic.ttf"

    if regular_path.exists():
        card1 = SPECIMENS_DIR / "specimen_mono_duospace.png"
        generate_duospace_specimen(regular_path, card1)

    if regular_path.exists() and italic_path.exists():
        card2 = SPECIMENS_DIR / "specimen_mono_italic.png"
        generate_italic_specimen(regular_path, italic_path, card2)

    card3 = SPECIMENS_DIR / "specimen_mono_weights.png"
    generate_weights_specimen(card3)


if __name__ == "__main__":
    main()
