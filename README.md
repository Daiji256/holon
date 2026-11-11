# Holon

**Holon** は、IBM Plex をベースに和文と欧文の視覚的調和・JIS X 4051 約物ツメ・和文イタリック・バリアブルフォント対応を施した日本語・多言語フォントファミリーです。

## ファミリー概要

- **Holon Sans**: プロポーショナル和欧混植フォント
  - 和欧双方向スケーリング（和文 0.97x / 欧文 1.02x）
  - JIS X 4051 準拠の約物ツメ（`chws` / `vchw`）および縦書き字形置換
  - 本家欧文イタリック + 11.0° オブリーク和文
  - Variable Font 対応（`wght`: 100..700, `GRAD`: -100..+100）

- **Holon Mono**: 2:1 デュオスペース・プログラミングフォント
  - 半角 550 UPM : 全角 1100 UPM の厳密な 2:1 幅比率
  - 罫線素片（Box Drawing）の隙間なし接続
  - エディタ・ターミナル最適化メトリクス
  - 本家欧文イタリック + 9.0° オブリーク和文
  - Variable Font 対応（`wght`: 100..700, `GRAD`: -100..+100）

## ファイル構成

- **`fonts/full/`**: 全文字収録版（Static TTF / WOFF2 各16種、Variable OTF / WOFF2 各2種）
- **`fonts/subset/`**: 常用漢字 2,136 字 + 基本記号・欧文に厳選した軽量サブセット版

## 使い方

### Web フォント (CSS)

```css
@font-face {
  font-family: "Holon Sans";
  src: url("fonts/full/HolonSans-Variable.woff2") format("woff2");
  font-weight: 100 700;
  font-style: normal;
  font-display: swap;
}

body {
  font-family: "Holon Sans", sans-serif;
  font-feature-settings: "chws" 1;
}
```

### エディタ設定 (VS Code)

```json
{
  "editor.fontFamily": "'Holon Mono', monospace",
  "editor.fontLigatures": "'zero'"
}
```

## ビルドとテスト

[uv](https://docs.astral.sh/uv/) を使用してビルドおよびテストを実行します。

```bash
# 全フォント＋サブセット版の一括ビルド (全72フォント / 144ファイル)
uv run build.py --all

# フル版のみ全ビルド (fonts/full)
uv run build.py --full-only

# 常用漢字サブセット版のみの生成 (fonts/subset)
uv run build.py --subset-only

# 生成済みフォント・一時ファイルのクリーンアップ
uv run build.py --clean

# 自動テストの実行
uv run test.py
```

## ライセンス

- **フォント**: [SIL Open Font License 1.1](OFL.txt)
- **ビルド・テストスクリプト**: [MIT License](LICENSE)
