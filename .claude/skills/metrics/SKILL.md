---
name: metrics
description: python3 scripts/metrics.py --markdown を実行し、テスト件数・許可リスト件数・条数などの実測値を表示する。読み取り専用（ファイルを一切変更しない）
allowed-tools: Bash
---

# /metrics — 実測値の表示（読み取り専用）

> **Phase 13 で新規追加**（C-28 / R-21 の maintainability 昇点条件の実証。
> 「新しいコマンドを 1 つ追加する手順が 1 箇所の変更で済む」ことを実際に示すために作った。
> `.claude/commands/metrics.md` は存在しない。**このファイル 1 つが唯一の実体**）。

## 目的

**ツールキット自身の保守用コマンド**である。測るのはツールキットの `scripts/` のテスト件数・
`spec_check.py` の検出件数・許可リスト・`.claude/` の構成など（利用者のプロジェクトの製品テストではない）。
README・CHANGELOG・`CLAUDE.md` に書く数値は、この出力をそのまま貼る。**手で書かない**
（ツールキット開発では、手で書いた数値が実体からずれる失敗を 5 回繰り返した）。

このコマンドは、その実測を毎回手で `python3 scripts/metrics.py --markdown` とタイプする代わりに
`/metrics` 一発で呼び出せるようにする。**ファイルを一切変更しない。**

## 手順

1. 次のコマンドを実行する:
   ```bash
   python3 scripts/metrics.py --markdown
   ```
2. 出力をそのままユーザーに提示する（要約や言い換えをしない）。
3. exit code が 0 以外なら、**テストが失敗している**（v15.1 から pytest の失敗で exit 1 になる。
   表の「failed 件数」「exit code」の行と、標準エラー出力の `ERROR:` 行をそのまま提示する）か、
   スクリプト自体が動いていない（`ls scripts/metrics.py`）。数値を書き写す前に原因を直す。

## 入力

なし（引数を取らない）。

## 出力

`python3 scripts/metrics.py --markdown` の標準出力（Markdown テーブル）。ファイルへの書き込みはしない。

## 前提

- `scripts/metrics.py` が存在する（既存スクリプト。本フェーズで変更していない）
