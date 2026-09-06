---
name: spec-check
description: 仕様（docs/ と skills/）の品質をチェックリストで判定する。ファイルは一切変更しない
---

# spec-check — 仕様の品質チェック

## 目的

**実装前に**仕様の欠陥を検出する。特に「**存在しないものを参照している仕様**」を捕まえる。

## 前提

- `scripts/spec_check.py` が存在する
- `docs/` と `skills/` が存在する

## 制約（最重要）

**ファイルを一切変更しない。** 実行前後で `docs/` と `skills/` の sha256 が不変でなければならない。
修正は `/clarify` または手動で行う。本スキルは**報告するだけ**である。

## 手順

### Step 1: 機械検査

```bash
python3 scripts/spec_check.py
```

exit code が 1 なら欠陥がある。`--json` で機械可読な出力が得られる。

### Step 2: 各件の判断

報告された件を 2 つに分ける。

| 判断 | 対処 |
|------|------|
| **真の欠陥** —— 存在しないものを指示として参照している | **参照を直す**（実在するものに変える、または記述を消す） |
| **前方参照** —— これから作るもの | `docs/spec-check-allowlist.json` に `reason` 付きで追加する |

> **抑制手段は許可リスト 1 つだけである。** 文書冒頭に「存在しない」と宣言しても、
> `docs/plan.md` や `CLAUDE.md` に「これから作る」と書いても、**報告は消えない**
> （`scripts/test_spec_check.py` の `TestNoHeuristicBypass` が回帰テストとして固定している）。
> これは cycle 3 のオーナー決定「ヒューリスティックを全廃し、抑制はすべて許可リストに現れる」による。

許可リストへの追加は次の形（`docs/spec-check-allowlist.json` の `entries` 配列）:

```json
{
  "ref": "analyze",
  "scope": "docs/plan.md",
  "reason": "Phase 08 で作成予定のコマンド",
  "section": "Iteration 2 / 3 の成果物（前方参照）"
}
```

- `scope` は**必要最小限のパス**にする。`"*"` は全ファイルで抑制するため、検出能力を失わせうる
- `reason` と `scope` が欠けたエントリは**無効**として無視され、抑制されない
- **前方参照は、実物を作った時点で該当エントリを消す**（消し忘れると検出が永久に効かなくなる）
- `docs/spec-check-allowlist.md` は**人間向けの説明**であり、パーサは読まない

### Step 3: チェックリストによる目視確認

`templates/fragments/quality-criteria/spec-quality-criteria.md` の各項目を確認する。
機械検査できない項目（曖昧さ、範囲の明確さなど）はここで見る。

### Step 4: ハッシュ照合

```bash
# **git ls-files を使う。** find は .gitignore を無視するため、
# `.claude/hooks/.state/`（hook の発火ごとに増える）を拾ってしまい件数が再現しない
git ls-files docs skills .claude | sort | xargs sha256sum > /tmp/before.sha
python3 scripts/spec_check.py > /dev/null
git ls-files docs skills .claude | sort | xargs sha256sum > /tmp/after.sha
diff /tmp/before.sha /tmp/after.sha && echo "変更なし"
```

**この照合を報告に含める。** R-14 の「ファイルを変更しない」は自己申告ではなく実測で示す。
**対象と件数を明記すること。** `find` と `git ls-files` で件数が変わるため、
どちらで何件を照合したかを書かないと再現できない。

### Step 5: 報告

- 検出件数と内訳（真の欠陥 / 前方参照）
- 各件の判断と根拠
- ハッシュ照合の結果
- **ファイルを変更していないこと**

## Quality Criteria

- [ ] `python3 scripts/spec_check.py` を実行し、結果を報告した
- [ ] 報告された各件を「真の欠陥」「前方参照」に分類した
- [ ] `spec-quality-criteria.md` のチェックリストを確認した
- [ ] **実行前後のハッシュ照合を行い、変更がないことを示した**
- [ ] **ファイルを一切変更していない**

## Common Pitfalls

- **報告された件をそのまま欠陥として扱う** → 前方参照が混ざる。分類してから判断する
- **ファイルを直してしまう** → R-14 違反。本スキルは報告のみ
- **機械検査だけで済ませる** → 曖昧さや範囲の問題は Step 3 の目視でしか見えない
- **ハッシュ照合を省く** → 「変更していない」を自己申告にしない
