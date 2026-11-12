# Holon

Holon は、IBM Plex をベースに和文と欧文の視覚的調整・約物ツメ・和文イタリック・バリアブルフォント対応を施したフォントファミリーです。

## ファミリー概要

- Holon Sans: プロポーショナル和欧混植フォント
  - 和欧双方向スケーリング（和文 0.97x / 欧文 1.02x）
  - 約物ツメ（`chws` / `vchw`）および縦書き字形置換
  - 欧文イタリック + 11° オブリーク和文
  - バリアブルフォント対応（`wght`: 100..700, `GRAD`: -100..+100）
- Holon Mono: 2:1 デュオスペース・プログラミングフォント
  - 半角 550 UPM : 全角 1100 UPM の厳密な 2:1 幅比率
  - 欧文イタリック + 9° オブリーク和文
  - バリアブルフォント対応（`wght`: 100..700, `GRAD`: -100..+100）

## 配布パッケージ

ファミリー（Holon Sans / Holon Mono）ごとに以下の ZIP アーカイブを提供します。

- `Holon*-Static.zip`: Static TTF（8 ウェイト × Upright / Italic）
- `Holon*-Variable.zip`: Variable OTF（Upright / Italic）
- `Holon*-Static-Subset.zip` / `Holon*-Variable-Subset.zip`: 常用漢字・基本記号・欧文のみを含む軽量サブセット版

## ビルドとテスト

[uv](https://docs.astral.sh/uv/) を使用してビルドおよびテストを実行します。

全フォント・パッケージの生成:

```bash
uv run build.py --all --package
```

テストの実行:

```bash
uv run test.py
```

## ライセンス

- フォント: [SIL Open Font License 1.1](https://openfontlicense.org/)
- ソースコード等: [MIT License](LICENSE)
