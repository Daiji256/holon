# holon

[![](https://data.jsdelivr.com/v1/stats/packages/gh/Daiji256/holon/badge)](https://www.jsdelivr.com/package/gh/Daiji256/holon)

**Holon Sans** および **Holon Mono** は、IBM Plex Sans / IBM Plex Mono（欧文・記号）と IBM Plex Sans JP（和文）を統合し、和欧の視覚的バランス調整・JIS X 4051 準拠の約物自動ツメ（`chws` / `vchw`）・和文イタリック・バリアブルフォント対応を施した日本語・多言語フォントファミリーです。

## 特徴

- **Holon Sans（プロポーショナルゴシック）**:
  - **双方向スケーリング調和**: 和文（漢字・仮名・全角約物）を `0.97x` に引き締めて中央配置し、欧文・記号を `1.02x` に拡大することで、混植時のサイズ感と黒みを自然に調和させています。
  - **JIS X 4051 準拠の約物半角ツメ（`chws` / `vchw`）**: 連続する括弧・句読点に加え、中点類（`・` `：` `；`）相互の二分ツメ、中点類と括弧の四分ツメ、全角空白（`U+3000`）やコロン＋半角空白の空き量調整を横書き・縦書きの双方で自動適用します。
  - **縦書き完全対応（`vert` / `vrt2` / `vchw`）**: 全角セミコロン（`；` → `uniFF1B.vert`）の 90° 回転配置を含む縦書き字形置換と縦書き約物ツメに対応しています。
  - **和文イタリック（11.0° オブリーク）**: 本家 IBM Plex Sans Italic の流麗な欧文イタリックに、11.0° 傾斜させた和文グリフ（縦書き字形・異体字含む）を組み合わせています。
  - **CJK 互換漢字補完**: Unicode NFKD 正規等価に基づき、`U+F900`〜`U+FAFF` の CJK 互換漢字 346 字を正規統合漢字へ安全にマッピングしています。

- **Holon Sans Variable（2ファイル分離バリアブルフォント）**:
  - Google Fonts 標準の直立（`HolonSans-Variable`）・イタリック（`HolonSans-Italic-Variable`）2ファイル構成（STAT テーブルによる相互リンク済み）。
  - **Weight 軸（`wght`: `100`〜`700`）**: Thin から Bold まで無段階のウェイト調整に対応。
  - **Grade 軸（`GRAD`: `-100`〜`+100`）**: 文字の送り幅（レイアウト）を1ピクセルも変えずに線の太さのみを増減させ、ダークモード時の光の膨張（ハレーション）補正やホバー時の太字化に最適です。

- **Holon Mono（2:1 デュオスペース・プログラミングフォント）**:
  - **厳密な 2:1 幅比率（半角 `550 UPM` : 全角 `1100 UPM`）**: 英数字2文字と日本語1文字・全角スペース（`U+3000`）の列幅が完全一致し、ターミナルやエディタでのテーブル・インデントが1ピクセルもズレません。
  - **罫線素片（Box Drawing `U+2500`〜`U+257F`）のシームレス接続**: ターミナル罫線が隙間なく直立・接続します。
  - **エディタ・ターミナル最適化メトリクス**: `OS/2`・`hhea` メトリクスを `950 / -225` に統一し、`BASE` テーブルおよびプロポーショナルカーニング・合字を排除することで VS Code や各種ターミナルでの上下クリッピングや桁ズレを防止しています。
  - **和文イタリック（9.0° オブリーク）**: IBM Plex Mono Italic に合わせた 9.0° 傾斜の和文グリフを収録。

- **Holon Mono Variable（2ファイル分離バリアブルフォント）**:
  - 直立（`HolonMono-Variable`）・イタリック（`HolonMono-Italic-Variable`）2ファイル構成（STAT テーブルによる相互リンク済み）。
  - **Weight 軸（`wght`: `100`〜`700`）**: 無段階のウェイト調整に対応しつつ、半角 550 UPM / 全角 1100 UPM のセル幅を 1 ピクセルも動かしません。
  - **Grade 軸（`GRAD`: `-100`〜`+100`）**: 文字の送り幅（列揃え）を完全に固定したまま線の太さ（黒み）のみを光学補正。ダークモード時の白文字の光の膨張（ハレーション）抑制や、モバイルアプリでの微妙な太さ調整に最適です。

## ファミリー構成

| ファミリー | 種別 | ウェイト / スタイル | ファイル名 |
| --- | --- | --- | --- |
| **Holon Sans** | Static (`TTF` / `WOFF2`) | `Thin` (100), `ExtraLight` (200), `Light` (300), `Regular` (400), `Text` (450), `Medium` (500), `SemiBold` (600), `Bold` (700) × Upright / Italic | `HolonSans-<Style>.ttf`<br>`HolonSans-<Style>.woff2` |
| **Holon Sans Variable** | Variable (`OTF` / `WOFF2`) | `wght` `100..700`, `GRAD` `-100..100` × Upright / Italic | `HolonSans-Variable.{otf,woff2}`<br>`HolonSans-Italic-Variable.{otf,woff2}` |
| **Holon Mono** | Static (`TTF` / `WOFF2`) | `Thin` (100) 〜 `Bold` (700) × Upright / Italic | `HolonMono-<Style>.ttf`<br>`HolonMono-<Style>.woff2` |
| **Holon Mono Variable** | Variable (`OTF` / `WOFF2`) | `wght` `100..700`, `GRAD` `-100..100` × Upright / Italic | `HolonMono-Variable.{otf,woff2}`<br>`HolonMono-Italic-Variable.{otf,woff2}` |

## 利用方法

### CSS の設定例（Holon Sans バリアブルフォント）

```css
@font-face {
  font-family: "Holon Sans";
  src: url("fonts/HolonSans-Variable.woff2") format("woff2");
  font-weight: 100 700;
  font-style: normal;
  font-display: swap;
}

@font-face {
  font-family: "Holon Sans";
  src: url("fonts/HolonSans-Italic-Variable.woff2") format("woff2");
  font-weight: 100 700;
  font-style: italic;
  font-display: swap;
}

body {
  font-family: "Holon Sans", sans-serif;
  font-feature-settings: "chws" 1;
}

/* ダークモード時の光学補正（レイアウト幅を変えずに線を少し細くする） */
@media (prefers-color-scheme: dark) {
  body {
    font-variation-settings: "GRAD" -50;
  }
}

/* 縦書きレイアウト */
.vertical-text {
  writing-mode: vertical-rl;
  font-feature-settings: "vchw" 1;
}
```

### CSS の設定例（Holon Mono バリアブルフォント）

```css
@font-face {
  font-family: "Holon Mono";
  src: url("fonts/HolonMono-Variable.woff2") format("woff2");
  font-weight: 100 700;
  font-style: normal;
  font-display: swap;
}

@font-face {
  font-family: "Holon Mono";
  src: url("fonts/HolonMono-Italic-Variable.woff2") format("woff2");
  font-weight: 100 700;
  font-style: italic;
  font-display: swap;
}

pre, code {
  font-family: "Holon Mono", monospace;
}

/* ダークモード時の光学補正（文字揃え・桁幅を保ったまま黒みを少し抑える） */
@media (prefers-color-scheme: dark) {
  pre, code {
    font-variation-settings: "GRAD" -50;
  }
}
```

### エディタ・ターミナルの設定例（Holon Mono）

```json
{
  "editor.fontFamily": "'Holon Mono', monospace",
  "editor.fontLigatures": "'zero'"
}
```

## ビルドとテスト

ビルドおよびテストには [uv](https://docs.astral.sh/uv/) を使用します（PEP 723 インラインメタデータにより依存パッケージは自動解決され、初回実行時にピン留めされた上流ソースが `tmp/` に自動ダウンロード・SHA-256 検証されます）。

```bash
# 基本スタイルのビルド（Holon Sans: Regular）
uv run build.py

# ファミリー・ウェイト・スタイルを指定してビルド
uv run build.py --family sans --weight Regular
uv run build.py --family sans --weight Regular --italic
uv run build.py --family mono --all-styles
uv run build.py --family mono-variable
uv run build.py --family sans-variable
uv run build.py --family variable

# 全ファミリー・全スタイルの完全ビルド（Static & Variable）
uv run build.py --family all --all-styles

# 出力先ディレクトリの指定（デフォルト: fonts/）
uv run build.py --family sans --weight Regular --output-dir dist/

# 自動検証テストスイート＆標本画像（specimens/*.png）の生成
uv run test.py
```

## ライセンス

- **フォント**: SIL Open Font License 1.1（`OFL.txt` — フォントバイナリ公開時に同梱）
- **ビルド・テストスクリプト**: [MIT License](LICENSE)
