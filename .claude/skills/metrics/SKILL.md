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

`CLAUDE.md`「現時点の実測値」節は次のように定めている:

> この表は `python3 scripts/metrics.py --markdown` の出力をそのまま貼ったものである。手で書かない。

このコマンドは、その実測を毎回手で `python3 scripts/metrics.py --markdown` とタイプする代わりに
`/metrics` 一発で呼び出せるようにする。**ファイルを一切変更しない。**

## 手順

1. 次のコマンドを実行する:
   ```bash
   python3 scripts/metrics.py --markdown
   ```
2. 出力をそのままユーザーに提示する（要約や言い換えをしない。CLAUDE.md の注記
   「手で書かない」と同じ理由——実測値と手で書いた値がずれる事故を防ぐ）。
3. コマンドが失敗した場合（exit code が 0 以外）は、標準エラー出力をそのまま提示し、
   `scripts/metrics.py` の存在確認（`ls scripts/metrics.py`）を促す。

## 入力

なし（引数を取らない）。

## 出力

`python3 scripts/metrics.py --markdown` の標準出力（Markdown テーブル）。ファイルへの書き込みはしない。

## 前提

- `scripts/metrics.py` が存在する（既存スクリプト。本フェーズで変更していない）
