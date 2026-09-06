# /analyze — 要件トレーサビリティの分析（読み取り専用）

## Objective

「要件 ID → SKILL.md → outputs」の対応を機械的に検査し、**未対応要件**と**孤立タスク**を報告する（R-16）。
**ファイルを一切変更しない。**

## Input Requirements

- `docs/requirements.md` §5（機能要件の表）と §9（ID 規約）
- `skills/phase-*/SKILL.md` の `> 対応要件:` 行
- `outputs/phase-*/.metadata.json` の `requirements_addressed`
- `metadata.json` の `phases.N.status`（完了判定に使う）

## Output Specification

標準出力のみ。ファイルは作らない。レポートに残す場合は呼び出し側が `--markdown` の出力を貼る。

## Quality Criteria

- [ ] `python3 scripts/trace_check.py` を実行し、結果を報告した
- [ ] **ファイルを一切変更していない**（`git ls-files docs skills .claude | xargs sha256sum` が実行前後で一致）
- [ ] `convention_violation` があれば最初に報告した（他の判定の前提が崩れているため）
- [ ] `planned` / `assigned` を「対応済み」として報告していない
- [ ] 検出できないもの（§「限界」）を明示した

## Procedure

### Step 1: 実行前のハッシュを取る

```bash
git ls-files docs skills .claude | sort | xargs sha256sum > /tmp/analyze-before.sha
```

> **`git ls-files` を使う。** `find` は `.gitignore` を無視するため件数が再現しない（Phase 07 の Critical #7）。

### Step 2: 検査を実行する

```bash
python3 scripts/trace_check.py
python3 scripts/trace_check.py --markdown   # 対応表が必要なら
```

### Step 3: 分類ごとに読む

**欠陥（exit 1 になる）**: `convention_violation` / `overdue` / `orphan_skill` / `orphan_output` /
`phase_mismatch` / `not_delivered`

**欠陥ではない**: `planned`（担当 SKILL がまだ無い） / `assigned`（宣言済み・未完了） / `crosscutting`（`全`）

`convention_violation` が出たら**それを先に直す**。「実現フェーズ」列が読めていない要件は、
他の判定（overdue / phase_mismatch）も信用できない。

### Step 4: ハッシュ照合

```bash
git ls-files docs skills .claude | sort | xargs sha256sum > /tmp/analyze-after.sha
diff /tmp/analyze-before.sha /tmp/analyze-after.sha && echo "変更なし"
```

### Step 5: 報告する

**限界を明示する**（`docs/constitution.md` 第1条。「該当なし」と「省略」を区別する）:

- ID の対応しか見ない。**要件の文章と実装が合っているかは判定しない**
- ID を持たない手順の孤立は検出できない
- C-ID / S-ID は対象外（`scripts/spec_check.py --check requirement_id` が重複・欠番を見る）

## Common Pitfalls

- **`planned` を欠陥として報告する** → 未着手フェーズの担当は予定どおり。騒がない
- **`assigned` を「対応済み」と報告する** → 宣言があるだけで完了ではない。表が嘘をつく
- **ファイルを変更する** → R-16 違反。本コマンドは読み取り専用
- **`find` でハッシュを取る** → `.claude/hooks/.state/` を拾い再現しない。`git ls-files` を使う
- **規約違反を後回しにする** → 読めていない行があると他の判定の前提が崩れる
