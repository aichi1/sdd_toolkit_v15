# 要件 ID 規約（`/analyze`・`/converge`・`spec_check.py` が読む書式）

`scripts/trace_check.py`（`/analyze`）と `scripts/spec_check.py`（`/spec-check`）は、**この規約に従って書かれた行だけ**を読む。
散文から ID を推測しない。規約の外で書かれた要件は**検査されない**か、`trace_check.py` が
`missing_section` / `convention_violation` として報告する。

`/init-task` は `docs/requirements.md` をこの規約どおりに生成する（`.claude/skills/init-task/SKILL.md` ステップ1.2a）。

> v15.0 まではこの規約がツールキット開発プロジェクトの `docs/requirements.md` §9 にしか無く、
> 利用者のプロジェクトでは `## 4. 機能要件` のような見出しで要件が書かれて、`/analyze` が
> 「要件 0 件・欠陥 0 件・OK」を返していた。v15.1 でこのファイルに移した。

## 1. 接頭辞

| 接頭辞 | 意味 | 定義場所（**唯一の正**） | 機械検査 |
|-------|------|------------------------|---------|
| `R-NN` | **機能要件**。実現すべきこと | `docs/requirements.md` の `## 5. 機能要件（R-ID）` の表 | `trace_check.py` |
| `C-NN` | **課題・制約**。解消したら記述を更新し、ID は再利用しない | `docs/requirements.md` の表（節は任意） | `spec_check.py --check requirement_id` |
| `S-NN` | **成功条件**。プロジェクトの完了判定 | `docs/requirements.md` の表（節は任意） | 同上 |

これ以外の接頭辞（`N-NN` 非機能要件、`H-N` 仮説など）を使ってもよいが、機械検査の対象外であることを
`docs/requirements.md` に明記する（**「規約が無い」と「規約の対象外」を区別する**）。

## 2. 表記

- **書式は `X-NN`。番号は 2 桁ゼロ埋め**（`R-1` ではなく `R-01`）。`trace_check.py` は `R-1` と `R-01` を同一視する
- **装飾は意味を変えない** —— `**R-01**`（重要）と `~~R-07~~`（取り下げ）は装飾なしと**同一の ID**
- **定義行は表の行**（`|` で始まる行）で、1 列目のセルが ID だけであること。散文中の言及は定義ではない
- **取り下げた ID は削除せず `~~R-07~~` と打ち消し線で残す**。番号を再利用しない

## 3. `## 5. 機能要件（R-ID）` の表

見出しは**この文字列と完全一致**させる（番号・全角括弧を含む）。`trace_check.py` はこの見出しから
次の `## ` 見出しの直前までの表だけを読む。

```markdown
## 5. 機能要件（R-ID）

| ID | 要件 | 対応課題 | 実現フェーズ | 検証 |
|----|------|---------|------------|------|
| R-01 | CSV を読み込み、列名を検証する | C-01 | 01 | S-01 |
| R-02 | 集計結果を Markdown 表で出力する | — | 02, 03 | S-02 |
| R-03 | すべての出力に生成日時を入れる | — | 全 | S-02 |
```

列の順序は固定（`trace_check.py` は 1 列目を ID、2 列目を要件、4 列目を実現フェーズとして読む）。
3 列目・5 列目は関連 ID を書く欄で、無ければ `—`。

### 3.1「実現フェーズ」列の書式

| 形 | 例 | 意味 |
|----|----|------|
| フェーズ番号 | `**01**` / `07` | そのフェーズで実現する |
| カンマ区切り | `01, 05` | 複数フェーズにまたがる |
| `全` / `各フェーズ` | `全` / `01, 各フェーズ` | **横断要件**。特定フェーズの SKILL への宣言を要求しない |
| 括弧注記 | `03（Phase 02 の結果次第）` | 括弧内は**注記**。括弧を除去してから解釈する |

**これ以外のトークンがあれば `trace_check.py` は `convention_violation` を報告し exit 1 を返す**（黙って読み飛ばさない）。

## 4. `skills/phase-NN/SKILL.md` の宣言

各 SKILL.md は**冒頭の引用行 1 行**で担当要件を宣言する:

```markdown
> 対応要件: **R-01, R-02** / 成功条件: **S-01**
```

**`> 対応要件:` で始まる行だけ**が宣言である。本文中に現れる R-ID は宣言ではない。

## 5. `outputs/phase-NN/.metadata.json` の申告

完了したフェーズは、実際に対応した R-ID を `requirements_addressed` に **JSON の配列**で記録する
（Builder が書く。`.claude/agents/builder.md`「Builder → Validator の引き継ぎ」）。

```json
{ "requirements_addressed": ["R-01", "R-02"] }
```

## 6. `trace_check.py` の分類

| kind | 意味 | 欠陥か |
|------|------|--------|
| `missing_section` | `docs/requirements.md` があるのに `## 5. 機能要件（R-ID）` の見出しが無い | **欠陥** |
| `convention_violation` | 「実現フェーズ」列が §3.1 の外 | **欠陥** |
| `overdue` | 完了済みフェーズが担当のはずなのに SKILL.md に宣言が無い | **欠陥** |
| `orphan_skill` / `orphan_output` | SKILL.md / `.metadata.json` が表に無い ID を挙げている | **欠陥** |
| `phase_mismatch` | 表の実現フェーズと宣言フェーズが食い違う | **欠陥** |
| `not_delivered` | 宣言はあるが、完了フェーズの `requirements_addressed` に無い | **欠陥** |
| `planned` / `assigned` / `crosscutting` | 未着手・進行中・横断 | 欠陥ではない |

フェーズの完了判定はルート `metadata.json` の `phases`（辞書。キーはフェーズ番号の文字列）の
`status` が `completed` で始まるかで行う（`/init-task` ステップ3.2）。
