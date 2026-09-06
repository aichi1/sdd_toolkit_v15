# converge — 未達要件の追記専用記録（R-17）

## Objective

`outputs/phase-NN/trace-report.md`（`/analyze` の出力）が報告する**未完了だが欠陥ではない要件**
（`planned`、および担当フェーズ完了後にオーナーが先送り/打ち切りを決めたもの）を、
`docs/convergence.md` に**追記専用**で記録する。**既存の記述は一切変更しない。**

## Input Requirements

- `outputs/phase-NN/trace-report.md`（無ければ先に `python3 scripts/trace_check.py --markdown` を実行して得る）
- `docs/convergence.md` §0（記録形式。**このセクションは本スキルが変更しない**）
- `docs/requirements.md` §5（要件と実現フェーズ）

## Output Specification

`docs/convergence.md` の **`## 2. エントリ` セクション末尾への追記のみ**。新規ファイルは作らない。
既存セクション（§0 記録形式、既存の `### Entry:` 見出し）は変更しない。

## Quality Criteria

- [ ] `docs/convergence.md` への変更が**追記のみ**である。`git diff --numstat -- docs/convergence.md` の**削除行が 0**
- [ ] 入力は `outputs/phase-NN/trace-report.md`（`/analyze` の出力）の未完了分類（`planned` / 決定済み `deferred`・`dropped`）
- [ ] 追記したエントリが `docs/convergence.md` §0 の見出し形式・表の 5 列・状態語の語彙（3 語）に従う
- [ ] `assigned`（宣言済み・未完了）を記録していない
- [ ] エントリの末尾に、本スキルを起動した経緯（フェーズ番号・日付）を明記した

## Procedure

### Step 1: 入力を確認する

```bash
python3 scripts/trace_check.py --markdown
```

直近の `outputs/phase-NN/trace-report.md` があればそれも参照し、`planned` の行を洗い出す。

### Step 2: 記録対象を分類する

`docs/convergence.md` §0.3 の語彙に従い、各要件を次のいずれかに分類する。

| 分類 | 記録するか |
|------|-----------|
| `planned` | する（状態 `planned`） |
| `assigned`（宣言済み・未完了） | **しない**。担当フェーズの完了を待つ |
| `crosscutting`（`全`） | しない |
| 欠陥（`not_delivered` 等）でオーナーが先送りを決定 | する（状態 `deferred`。決定日を理由欄に明記） |
| 欠陥でオーナーが打ち切りを決定 | する（状態 `dropped`。決定日を理由欄に明記） |

### Step 3: エントリを作る

`docs/convergence.md` §0.1 / §0.2 の形式に従い、見出し・メタ情報 3 行・5 列の表を作る。
**列の順序・見出し文言・状態語の語彙を変えない。**

### Step 4: 追記する

`## 2. エントリ` の**末尾**に新しいエントリを追加する。既存の `### Entry:` は 1 文字も変更しない。

### Step 5: 追記専用の検証

```bash
git diff --numstat -- docs/convergence.md
```

**2 列目（削除行）が 0 であること。** 0 でなければ Step 4 で既存行を壊している。差分を破棄して Step 4 からやり直す。

### Step 6: 報告する

- 追記したエントリの要件件数と状態語の内訳
- `git diff --numstat` の結果（削除行 0 の確認）
- 記録しなかったもの（`assigned` など）とその理由

## Common Pitfalls

- **`assigned` を「対応済み」でないからと記録する** → 担当フェーズが完了するまでは記録しない（§0.3）。
  完了後に `not_delivered` として `/analyze` が欠陥報告した場合のみ、オーナー決定を経て記録する
- **既存エントリの状態語を書き換えて「更新」する** → R-17 違反。**新しいエントリを追記**する
- **表の列を増減させる・見出し文言を変える** → 次回以降の機械的な読み取りが壊れる。5 列固定
- **状態語を 3 語以外にする（`done` や `postponed` など）** → 語彙は `docs/convergence.md` §0.3 に固定。
  新しい語が必要になったら、それは §0 の改訂であり `.claude/rules/` の改訂と同様にオーナーへ提起する
