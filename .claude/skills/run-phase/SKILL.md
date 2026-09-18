# run-phase - SDDプロジェクトのフェーズ実行

## 目的
Builder / Validator パターンによる品質担保を行いながら、SDD（スペック駆動開発）プロジェクトの1つ以上のフェーズを実行します。

## 前提条件
- `/init-task` によりプロジェクトが初期化済み（`docs/` と `skills/` が存在）
- `CLAUDE.md` が存在
- `metadata.json` が存在

## 入力
- フェーズ番号：単一（例: `"1"`）、範囲（例: `"1-3"`）、または `"all"`
- オプションフラグ:
  - `--review-only`：実行をスキップし、既存出力のみをレビュー
  - `--no-validation`：Validator エージェントをスキップ（高速だが品質低下）
  - `--output-dir`：出力ディレクトリを指定（デフォルト: `./outputs/`）
  - **`--parallel`**（**実験的**）：`depends_on` で依存関係のないフェーズを
    同一レベルとみなし、Builder を同時に起動する。**指定しない限り既定は従来どおりの逐次実行**
    （後方互換。Strategy 1/2/3 は無変更）。詳細は「Phase 0: 準備」Step 0.3 と
    「パフォーマンス最適化 / 並列実行」を参照

## 出力
- 生成された成果物：`./outputs/phase-{N}/`
- 検証レポート：`./outputs/phase-{N}/.validation/`
- フェーズ状態を反映した `metadata.json` の更新

## ワークフロー

### Phase 0: 準備

**Step 0.1: 環境チェック**
```bash
# 必須ファイルの存在確認
- ./docs/ (空でない)
- ./skills/phase-{N}/SKILL.md (要求されたフェーズ分)
- ./CLAUDE.md
- ./metadata.json
```

**Step 0.2: コンテキスト読み込み（トークン効率化）**
- `CLAUDE.md` を読み、プロジェクト概要を把握
- `outputs/.phase-context.json` が存在する場合:
  - このファイルを読み、前Phaseの判断・要約・docs要点を把握
  - docs/ の全ファイル再読み込みは **省略可能**（必要な箇所だけ参照）
- `outputs/.phase-context.json` が存在しない場合（Phase 1 等）:
  - `docs/` 配下の全ファイルをコンテキストに投入
- 対象フェーズの `skills/` 配下 `SKILL.md` を読み込み
- `metadata.json` を確認し、過去フェーズの完了状況を把握

**Step 0.3: 依存関係バリデーション**

要求された各フェーズについて:
- **依存関係の決定**: `metadata.json` の `phases.{N}.depends_on`（整数配列）を読む。
  存在しない場合は既定値 `[N-1]`（直列依存。Phase 1 は `[]`）にフォールバックする。
  `phases` は辞書（キーはフェーズ番号の文字列。`/init-task` ステップ3.2）。例（Phase 3 と 4 が
  どちらも Phase 2 にのみ依存する場合）:
  ```json
  "phases": {
    "3": {"status": "completed", "depends_on": [2]},
    "4": {"status": "completed", "depends_on": [2]}
  }
  ```
  （Phase 3 と 4 は互いに依存しない＝並列実行の候補になれる）
- 前提フェーズ（`depends_on` の各要素）が完了しているか確認
- 依存が欠けている場合は、以下のいずれか:
  - 前提フェーズを自動実行（ユーザー確認あり）、または
  - 明確なエラーメッセージを出して中断
- **`--parallel` 指定時のみ**: 要求範囲内のフェーズを `depends_on` でトポロジカルソートし、
  互いに依存関係のないフェーズの集合（「レベル」）を求める。手順は
  「パフォーマンス最適化 / 並列実行」節を参照

### Phase 1: Builder 実行（フェーズごと）

**Step 1.1: エージェント初期化**
Builder エージェントを以下の条件で起動:
- コンテキスト：`CLAUDE.md`、`docs/`、`skills/phase-{N}/SKILL.md`
- （あれば）前フェーズの出力
- ツール：フル read/write 権限
- 目的：`SKILL.md` に記載された成果物を生成

**Builder エージェントの責務**
1. `SKILL.md` の手順（procedure）セクションを読む
2. 要件のために `docs/` を読む
3. 手順をステップバイステップで実行
4. 成果物を生成
5. `./outputs/phase-{N}/` に保存
6. `./outputs/phase-{N}/.metadata.json` を作成（形式の詳細は `.claude/agents/builder.md`「Builder → Validator の引き継ぎ」）:
```json
{
  "phase": {N},
  "builder_session_id": "{uuid}",
  "started_at": "{ISO timestamp}",
  "completed_at": "{ISO timestamp}",
  "docs_referenced": ["docs/requirements.md"],
  "requirements_addressed": ["R-01", "R-02"],
  "deliverables": [
    {
      "file": "report.md",
      "type": "document",
      "status": "pending_validation"
    }
  ],
  "revision_history": []
}
```
   `requirements_addressed` は `/analyze`（`scripts/trace_check.py`）が読む唯一の申告
   （`docs/rules-reference/requirement-id-convention.md` §5）。

**Builder を 2 段階で起動する（設計判断を含むフェーズで推奨）**:
設計を変える・規約や表（エラーコード一覧、状態遷移など）を新しく決める・権限や安全に関わるフェーズでは、
Builder に**まず方針（10 行程度の決定と、検証方法）だけを書かせて止め**、メインセッションまたは
オーナーが確認してから実装に進ませる。**規約を先に決めてから実装する**ためである
（ツールキット開発・別製品の開発のどちらでも、規約先行のフェーズは修正 0〜1 巡、逆順のフェーズは 3 巡以上だった）。

**Step 1.2: Builder 出力の取り込み**
- 生成された全ファイルを収集
- ファイルパスが `SKILL.md` の期待どおりか確認
- `SKILL.md` の要件チェックリスト（初期版）を作成

### Phase 1.5: 自動プリチェック（Validator 起動前）

**Step 1.5.1: validate-outputs.py の実行**
Builder 完了後、Validator 起動前に自動プリチェックスクリプトを実行する：

```bash
python3 scripts/validate-outputs.py --phase {N}
```

このスクリプトは以下を自動検証する：
1. **成果物ディレクトリ存在**: `outputs/phase-{N}/` が存在するか
2. **メタデータ完全性**: `.metadata.json` が存在し、必須フィールド（phase, deliverables）があるか
3. **成果物ファイル存在**: 隠しファイル以外の成果物が1つ以上あるか。`.metadata.json` の `deliverables` に
   挙げたファイルがすべて存在し、空（0 バイト）でないか（v15.1。Gate 0 は免除不可）
4. **SKILL.md Quality Criteria**: Quality Criteria セクションの項目数を確認
5. **カテゴリ別必須セクション**: metadata.json の category に基づき、テンプレートの必須セクションがキーワードベースで存在するか

**Step 1.5.2: プリチェック結果の処理**
- **PASS**: 全チェック通過 → ファストパス判定（下記）へ進む
- **WARN**: 警告あり → Phase 2（Validator フル検証）へ進む
- **FAIL**: 必須項目欠落 → Builder に差し戻し（Validator の時間を節約）

**Step 1.5.3: ファストパス判定（効率化）**
プリチェック PASS の場合、以下の条件をすべて満たせば **ファストパス**（軽量検証）を適用する：

ファストパス条件：
1. プリチェック結果が **全項目 PASS**（WARN なし）
2. SKILL.md の Quality Criteria が **5項目以下**
3. 成果物ファイルが **3つ以下**

ファストパスの場合（Phase 2 を軽量化）：
- Validator フルエージェントを起動しない
- 代わりにメインセッション内で Quality Criteria を1項目ずつ確認する
- 全項目 Met → 即 PASS（Phase 4 へ）
- 1項目でも Missing → 通常の Phase 2（Validator フル検証）にフォールバック

> **注記（Phase 03 / R-06 / `docs/constitution.md` 第1条）**:
> `small_implementation` では、ファストパスが適用される場合でも**検証コマンド実行を省略しない**。
> ファストパスが省略するのは Validator フルエージェントの起動であり、Step 2.3（実行検証）そのものではない。
> ファストパス時はメインセッションが Step 2.3 相当の検証コマンド実行と `## Executed Verification` の記録を代行する。

ファストパスでない場合：
- 通常どおり Phase 2（Validator フル検証）へ進む

### Phase 2: Validator 実行

**Step 2.0: カテゴリ別検証チェックリストの準備**
Validator 起動時に、以下を検証の入力として渡す：
1. SKILL.md の Quality Criteria（最重要 — 必ず全項目を検証する）
2. プリチェック結果（WARN 項目があればそこを重点チェック）
3. `templates/skills/{category}.md` のテンプレート（存在する場合）
   - テンプレートの「必須セクション構成」を成果物と照合
   - テンプレートの「Quality Criteria」が SKILL.md に反映されているか確認

Validator は SKILL.md の Quality Criteria の **全項目** を1つずつ検証し、検証レポートにチェック結果（Met/Partial/Missing）を記載しなければならない。

**Step 2.1: エージェント初期化**
Validator エージェントを以下の条件で起動:
- コンテキスト：`CLAUDE.md`、`docs/`、`skills/phase-{N}/SKILL.md`
- Builder の出力：`./outputs/phase-{N}/`
- ツール：**成果物を変更しない**。検証コマンドの実行は可、書き込みは `outputs/phase-{N}/.validation/` の中だけ
  （`.claude/agents/validator.md`「ツールアクセス権限」）
- 目的：成果物がすべての要件を満たしているか検証
- **巡番号 R を渡す**（初回 R=1。修正サイクル後の再検証ごとに +1）。Validator は報告を
  `report-round{R}.md` に書く（Step 2.2）

**セッションを再開した場合は、Validator・専門家を起動する前に、前のセッションで起動した
エージェントがまだ動いていないか確認する**（実行中のエージェントの一覧、`.validation/` の最新の
更新時刻）。二重に起動すると、後から起動した方が `hashes-before.txt` を上書きし、先の方の
事前/事後の比較が意味を失う（別製品の開発工程で実際に起きた）。

**Validator エージェントの責務**
1. `SKILL.md` の品質基準（quality criteria）を読む
2. `docs/` の要件を読む
3. Builder の成果物を読む
4. 各要件に対してチェック:
   - ✓ Met：要件を満たす
   - ⚠ Partial：一部満たすが改善が必要
   - ✗ Missing：未対応
5. 検証レポートを生成

**Step 2.1.5: 成果物ハッシュの事前記録（M5 / Phase 14。Step 2.1 完了直後・Step 2.2 より前に実行する）**

Validator が Builder の成果物を読み始める前に、Step 2.3 項目4（ハッシュ照合）で使う「変更前」の
ハッシュをここで記録する。**この位置で記録しないと、Step 2.2（レポート雛形作成）や Step 2.3
項目1〜3（検証コマンドの列挙・実行）の間に成果物が変化しても検出できなくなる**——Step 2.3 の
番号付きリストを 1→2→3→4 と順番どおりに読んで実行すると、項目4の「事前」ハッシュが実質的に
項目1〜3の**後**に取られてしまい、「事前/事後」の意味が失われる（この抜け穴を Phase 14 修正
サイクル 1 巡目で発見し、独立した手順として切り出した）。`.validation/` はこの時点でまだ存在しない
可能性があるため `mkdir -p` する。C-32 の教訓により `__pycache__` を除外し
`PYTHONDONTWRITEBYTECODE=1` を設定する:

```bash
mkdir -p outputs/phase-{N}/.validation
PYTHONDONTWRITEBYTECODE=1 find outputs/phase-{N} -type f -not -path '*/__pycache__/*' \
  -not -path '*/.validation/*' | sort | xargs sha256sum > outputs/phase-{N}/.validation/hashes-before.txt
```

**Step 2.2: 検証レポートの形式**

**巡ごとに別ファイルへ保存し、過去の巡を上書きしない**:

1. `./outputs/phase-{N}/.validation/report-round{R}.md` に書く（既に同名があれば書かない。R を確認する）
2. 同じ内容を `./outputs/phase-{N}/.validation/report.md` にも書く（最新の巡。検査スクリプトはこちらを読む）

> **なぜ**: `report.md` だけを上書きする運用では、フェーズ完了時のコミットに最終巡しか残らない。
> 別製品の開発工程（v15 で 20 フェーズ）では 4 フェーズで過去巡の原文が消え、修正サイクルの原因分析
> （「前の巡の修正が次の指摘を生んだか」）ができなかった。

```markdown
# Validation Report: Phase {N} — Round {R}

**Validator Session**: {uuid}
**Timestamp**: {ISO timestamp}
**Overall Status**: {PASS / NEEDS_REVISION / FAIL}

## Requirements Checklist

### From docs/{file}.md
- [x] Requirement 1: Description
  - **Status**: Met
  - **Evidence**: {specific file/section}
  
- [⚠] Requirement 2: Description
  - **Status**: Partial
  - **Issue**: {what's missing or incorrect}
  - **Suggestion**: {how to fix}

- [ ] Requirement 3: Description
  - **Status**: Missing
  - **Issue**: {what's missing}
  - **Required Action**: {what needs to be added}

### From skills/phase-{N}/SKILL.md Quality Criteria
- [x] Criterion 1: ...
- [⚠] Criterion 2: ...

## Executed Verification
<!-- 全フェーズ必須（docs/io-spec.md §2.6, docs/constitution.md 第1条）。Step 2.3 で記録する -->
| # | コマンド | exit code | 要約(pass/fail 数) | ログ位置 |
|---|---------|-----------|-------------------|---------|
| 1 | `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/ -q -p no:cacheprovider` | 0 | 12 passed | verification.log:1-14 |
| 2 | `diff outputs/phase-{N}/.validation/hashes-before.txt outputs/phase-{N}/.validation/hashes-after.txt` | 0 | 差分なし（Builder 成果物は不変） | verification.log:15 |

<!-- 「検証前後のハッシュ照合: sha256sum 一致」という自主申告の1文は使わない。
     上表の行（実行したコマンドと exit code）がハッシュ照合の証跡そのものである。 -->

## Critical Issues

<!-- 1 件 1 見出し（### Issue #N）。フィールドは .claude/rules/builder-validator.md Validator Rule 3。
     scripts/check_fix_cycle.py が Gate 欄を検査する。Critical が無ければ「**なし。**」と書く -->

### Issue #1: {一行の要約}
- **Gate**: {0 / 1 / 2}（`3-only` は Critical にしない。Suggestions へ）
- **Location**: {file}:{line}
- **Problem**: {何が問題か}
- **Required by**: {docs/ の要件 ID・節、または SKILL.md Quality Criteria の項目}
- **Current state**: {実際の状態}
- **Expected**: {期待される状態}
- **Fix**: {具体的な修正方法}
- **Priority**: {High / Medium}

## Suggestions

### Suggestion #1: {一行の要約}
- **Gate**: {3-only など}
- **Location**: {file}:{line}
- **Benefit**: {なぜ良くなるか}
- **Effort**: {low/medium/high}

## Summary
- Total Requirements: {N}
- Met: {N}
- Partial: {N}
- Missing: {N}

**Recommendation**: {APPROVE / REQUEST_REVISION / REJECT}
```

**Step 2.3: 実行検証（必須）**

`docs/tech-stack.md` または当該 `skills/phase-{N}/SKILL.md` の Quality Criteria に
検証コマンドが定義されている場合、Validator は**必ず実行**する。

1. 検証コマンドを列挙する（無い場合は report に「該当なし」と明記して次へ）
2. 各コマンドを実行し、コマンド行・exit code・標準出力の要約を記録する
3. `.validation/report.md` に `## Executed Verification` セクションを作る（表形式）
4. **実行前後で成果物のハッシュが不変であることを、次のコマンドで機械的に確認する**（M5 / Phase 14。
   従来の「`sha256sum` 一致（Validator による改変なし）」という自主申告の1文をやめ、
   実行して exit code を記録する表の行に置き換える）。「事前」のハッシュは **Step 2.1.5 で
   Step 2.1 完了直後にすでに記録済み**（`hashes-before.txt`）。ここでは「事後」のハッシュのみを
   記録して比較する（C-32 の教訓により `__pycache__` を除外し `PYTHONDONTWRITEBYTECODE=1` を
   設定する。項目1〜3を先に済ませた**あとに**実行してよい）:
   ```bash
   # .validation/report.md を書き終えた直後（Validator 検証の最後。Step 2.1.5 より後）
   PYTHONDONTWRITEBYTECODE=1 find outputs/phase-{N} -type f -not -path '*/__pycache__/*' \
     -not -path '*/.validation/*' | sort | xargs sha256sum > outputs/phase-{N}/.validation/hashes-after.txt

   diff outputs/phase-{N}/.validation/hashes-before.txt outputs/phase-{N}/.validation/hashes-after.txt
   ```
   `diff` の exit code（0 = 不変）を `## Executed Verification` の表に 1 行として記録する
   （`.validation/` 自体は Validator が新規作成するディレクトリのため比較対象から除外する）

**exit code が 0 でないコマンドが 1 つでもあれば、verdict は PASS にできない。**
**上記 M5 の `diff` が 0 以外を返した場合も同様に PASS にできない**
（`Required by: docs/constitution.md 第1条`, `.claude/rules/builder-validator.md` Validator Rules 1）。

> 検証コマンドが定義されていないカテゴリ（`research_report` / `internal_proposal` 等）では、
> `## Executed Verification` に「該当なし」と明記する（**省略と区別する**。`docs/constitution.md` 第1条）。

**Step 2.4: 検証判定**
- すべて Met → Status: PASS
- Critical Issues がある → Status: NEEDS_REVISION
- 根本的な不整合 → Status: FAIL
- **Step 2.3 の Executed Verification で exit code が 0 以外の行が 1 件でもある → PASS にできない**
  （その行を Critical Issues に自動追加。`Required by: docs/constitution.md 第1条`）
- **`docs/tech-stack.md` §4 に定義された当該フェーズのコマンドのうち、`## Executed Verification` に
  行が存在しないものがある → 「未実行: `<command>`」を Critical Issues に追加し PASS にできない**

**Step 2.4.1: 報告の事後検査（メインセッションが実行する）**

Validator が報告を書き終えたら、メインセッションが次の 2 つを実行する。どちらかが exit 0 でなければ、
報告の書式か判定に誤りがある。Validator に差し戻す（成果物の修正サイクルとは数えない）。

```bash
python3 scripts/validate-outputs.py --phase {N} --require-verification   # exit code 列と Overall Status の整合
python3 scripts/check_fix_cycle.py --phase {N}                           # Gate 欄・3-only・opened_by・打ち切り規則
```

> Step 1.5 のプリチェックは Builder 直後（報告がまだ無い時点）に走るため、`Executed Verification` の
> 整合はここで初めて検査される。v15.0 はこの事後検査を手順に持たず、規則だけがあって実行されていなかった。

**Step 2.5: 専門家レビュー（任意。`docs/team.md` とこのフェーズの実際の変更で決める）**

`/init-task` が `.claude/agents/generated/` に召喚した専門家（security / architect / QA / doc-editor など）は、
Validator とは別の種類の欠陥を見つける。別製品の開発工程（v15 で 20 フェーズ）の記録では、
**Validator が PASS を出した後に専門家が実害のある指摘を出した例が 6 フェーズ**あり、
記録に残った指摘のうち「放置すれば欠陥として残った」ものの割合は security が最も高く、architect が続いた
（参考値。対象と工程が違えば変わる）。

1. **誰を呼ぶか**: `docs/team.md` の「いつ/何のために呼ぶか」と、**このフェーズの実際の変更**
   （`git status --porcelain --untracked-files=all` の出力。計画や自己申告ではなく実物。
   `git diff --name-only` は**新規作成した未追跡ファイルと `git add` 済みの変更を含まない**ので使わない）
   から決める。例: 認証・権限・外部入力・
   シェル実行・ファイル書き込みに触れる → security、モジュール境界・スキーマ・公開インターフェース → architect、
   テスト・検証コマンド → QA。**全員を毎回呼ぶことを既定にしない**（小さな変更にはコストが見合わない）。
   メインセッションはいつでも追加してよい。減らすときは理由を `.metadata.json` に残す。
   **過去の High への対応を含む変更なら、それを出した専門家は必ず呼ぶ**
2. **いつ**: Validator と**同じ巡で並行して**起動する（同じ応答の中で複数のエージェントを起動する）。
   Validator の PASS を待ってから呼ぶと、指摘が 2 巡目に偏り、巡が 1 つ増える
3. **出力**: 各専門家は指摘を**自分で** `outputs/phase-{N}/.validation/expert-<agent>-round{R}.md` に書く
   （サブディレクトリにしない。`.claude/rules/file-conventions.md` の 3 階層まで）。
   形式は Validator の Critical Issue と同じ（`Location` / `Required by`（無ければ「無し」） / `Current` /
   `Expected` / `Fix` / 重大度 High・Medium・Low / `Gate` / **再現手順**（そのまま実行できる形））。
   **メインセッションや `change-report.md` で一行要約に圧縮しない**（参照だけを書く）。
   別製品の開発工程では、この原文が 10 フェーズすべてで残っておらず、後から「仕様に書かれていたか」を
   判定できなかった。原文を残すと、Validator が専門家の指摘を読んで独立に再現できる
4. **判定**: フェーズの判定は、Validator と、起動した専門家**全員**が返ってから行う。
   Validator の PASS 単独を判定にしない
5. **High はメインセッションが自分で再現してから** Builder に渡す。再現できない・主張が過大なものは
   理由を添えて差し戻す。`Required by` が「無し」の指摘は Critical にしない（Suggestion。
   `.claude/rules/builder-validator.md` Validator Rule 2 と同じ）。
   ただし**出荷される成果物が事実と違うことを述べている**なら、`Required by` は Gate 1（docs の要件に
   反する誤情報）として扱う

### Phase 3: 修正ループ（必要なら）

**Step 3.1: 検証結果をユーザーに提示**
```
Phase {N} validation completed.
Status: {NEEDS_REVISION}

Critical Issues: {N}
Suggestions: {N}

Options:
1. Auto-fix: Builder エージェントに問題の修正をさせる
2. Review: 詳細な検証レポートを表示
3. Manual: 自分で修正する
4. Accept: 問題が残っていても先へ進む
```

**修正サイクルを開く前の仕分け**（メインセッション）:

- **形式・作法だけの指摘**（引用位置・見出し番号・書式・用語・内部 ID の混入など、内容の正しさに
  関わらないもの）は修正サイクルを開かない。Suggestion として `findings-register.md`
  （`templates/findings-register.md`）に移す。**例外: 出荷される成果物が事実と違うことを述べている**
  なら、形式に見えても内容の欠陥として扱う（その場で直す）
- 修正サイクルを開くなら、その**根拠**を決める。`.metadata.json` の `revision_history[]` の新しい要素に
  `opened_by` として記録させる: `validator_critical`（Validator の Critical）／ `expert_defect`
  （専門家の指摘。`.validation/expert-<agent>-round{R}.md` の ID を添える）／ `owner_decision`
  （オーナーが直すと決めた。理由を 1 文）／ `main_session`（メインセッションの自己検証）。
  **Validator が Critical 0 で PASS でも、専門家の指摘やオーナー決定で開くサイクルは正当**。
  違反は根拠が書かれていないことだけ（`scripts/check_fix_cycle.py` が検査する）

**Step 3.2: Auto-fix 実行**
ユーザーが auto-fix を選んだ場合:
1. Builder エージェントを再起動:
   - 元のコンテキスト
   - 追加入力として検証レポート（`report-round{R}.md`）と、対象にする専門家の指摘ファイル
   - タスク:「指摘された箇所のみ修正」。`opened_by` を渡す
2. Builder が成果物を修正し、`.metadata.json` の `revision_history[]` に要素を足す
   （`cycle` / `opened_by` / `changes`。`.claude/agents/builder.md`「パターン3」）
3. **Builder は報告の前に、指摘を見つけた検査を同じ形で再実行する**（`.claude/agents/builder.md`
   「修正後の再検査」）。再実行したコマンドと exit code が報告に無ければ、Validator を起動しない
4. Validator を再実行（巡番号 R+1。前の巡の `report-round{R}.md` を読ませる）。
   直前の巡で指摘を出した専門家は、その指摘の再検証のために再度起動する
5. PASS になるか最大2回まで反復

> **なぜ再検査を先にするか**: 別製品の開発工程の記録では、2 巡目以降の指摘 66 件のうち
> **25 件（37.9%）が前の巡の修正そのものが生んだ回帰**だった（直したことで別の記録・文言が古くなる型）。
> 巡を駆動していたのは新しい欠陥ではなく回帰である。

**小さな指摘はレビューの巡を回さずに閉じてよい**: 次を**すべて**満たすとき、メインセッションが
修正を確認して閉じ、Validator・専門家の巡をやり直さなくてよい。

- **直前の Validator の判定が PASS（Critical 0）**で、閉じる対象が Suggestion・形式だけの指摘・
  専門家の Medium / Low・記録（`change-report.md`・`verification.log`・`.metadata.json`・登録簿）の訂正に限られる。
  **Validator の Critical と専門家の High の修正には使えない**（文書が成果物のプロジェクトでは
  「文書だけの変更」がそのまま成果物の変更なので、変更の種類ではなく指摘の種類で決める）
- 変更が `.metadata.json` の `deliverables` に挙げた成果物の**内容の主張**（結論・数値・要件への対応）を変えない。
  変えるなら Validator の巡を回す
- 変更したファイルを `git status --porcelain --untracked-files=all` の実出力で確かめる（自己申告にしない）

ただし**機械検査（Step 2.3 の検証コマンド、Step 2.4.1 の事後検査、成果物ハッシュ）は必ず回し直す**。
閉じたときは `revision_history` に `opened_by`（`main_session` か `owner_decision`）・`changes`・`rechecked` を書き、
条件を満たした証拠（上の `git status` の出力と機械検査の exit code）を `verification.log` に**追記**する。
Validator の報告（`.validation/`）は Validator の書き込み先なので、メインセッションは書き換えない。

**Step 3.3: 反復回数の上限と打ち切り**（`.claude/rules/builder-validator.md` Fix Cycle Limits）

- **止めてよい条件**: Gate 0〜2 と機械検査（Step 2.3・Step 2.4.1）がすべて green。
  Gate 3-only の指摘は止める理由にならない（Suggestion として登録簿へ）
- 自動の修正サイクルは 2 回まで。2 回の Builder/Validator サイクル後もまだ NEEDS_REVISION なら
  ユーザーへエスカレーションし、残課題と**根本原因**（SKILL.md の指示不足／docs/ の矛盾／
  Builder と Validator の解釈の食い違い）を示す。見つかった箇所を 1 つずつ直すと同じ欠陥クラスの
  隣の箇所が次の巡で見つかるので、3 巡目に入る前に欠陥クラスを名指しする
- **3 巡目以降は、毎巡「続けて直す」と「現状を受け入れて先へ進む」を対等な選択肢として示す**。
  どちらを選んだかと理由を、`revision_history` の最後の要素の `owner_decision` に書く
  （書かないと `scripts/check_fix_cycle.py` が fail する）

### Phase 4: 完了処理

**Step 4.1: ステータス更新**
`./outputs/phase-{N}/.metadata.json` を更新（**既存のフィールドは残し、次を足す・書き換えるだけ**。
`revision_history` や `requirements_addressed` を消さない）:
```json
{
  "phase": {N},
  "status": "completed",
  "validation_status": "pass",
  "validation_rounds": 1,
  "completed_at": "{ISO timestamp}",
  "deliverables": [...],
  "requirements_addressed": [...],
  "revision_history": [...]
}
```
`validation_rounds` は Validator の巡の数（`report-round{R}.md` の最大の R）。修正サイクルの数は
`revision_history` の要素数で、両者は 1 ずれることが多い。

ルートの `./metadata.json` を更新:
```json
{
  ...
  "phases": {
    "1": {"status": "completed", "completed_at": "..."},
    "{N}": {"status": "completed", "completed_at": "..."}
  },
  "current_phase": {N+1 or "complete"}
}
```

**Step 4.1.5: フェーズ間コンテキスト引き継ぎ**
Phase完了時に `./outputs/.phase-context.json` を作成/更新する。
次Phaseはこのファイルを読むことで、docs/全体の再読み込みを省略できる。

```json
{
  "last_phase": {N},
  "last_phase_summary": "Phase {N}で達成した内容の1-2文要約",
  "key_decisions": ["判断1", "判断2"],
  "output_files": ["outputs/phase-{N}/file1.md", "outputs/phase-{N}/file2.md"],
  "pending_issues": ["未解決の問題があれば記載"],
  "next_phase_hint": "次Phaseで重要な情報や注意点",
  "docs_digest": {
    "scope": "docs/scope.mdの核心を1-2文で",
    "key_requirements": ["要件1", "要件2", "要件3"]
  }
}
```

このファイルはフェーズ完了ごとに上書きされる（最新フェーズの情報のみ保持）。
**したがって `pending_issues` に書いただけの指摘は次のフェーズの完了で消える。** 先送りする指摘
（Suggestion、先送りした専門家の指摘）は `findings-register.md` に ID 付きで移し、
`pending_issues` にはその ID だけを書く（`templates/findings-register.md`）。

**Step 4.1.6: CLAUDE.md の Next Session Starter 更新**（C-31。オーナー決定 2026-09-03）
`.claude/rules/file-conventions.md` は CLAUDE.md を「Phase completion」で更新すると定めている。
フェーズ完了時に以下を必ず更新する（`.phase-context.json` とは別物。人間が最初に読む導線）:

- **現在地**: 完了したフェーズ番号・名称・commit ハッシュ
- **次にやること**: 次の `/run-phase N`（全フェーズ完了なら `/finalize`）
- **次フェーズ開始前の必須確認**: `.claude/`（settings / hooks / skills / agents / rules）を変更した場合は、
  次のフェーズを**新しいセッション**で始め、変更が読み込まれたことを確かめる（同じセッションでは古い定義のまま動く）
- **現時点の実測値**: テスト件数、主要な検証コマンドの結果（**コマンドを実行して出力から書く**。
  記憶や前回の値を書き写さない）
- **未解決の判断事項**: オーナー判断待ちの項目

`.phase-context.json` と食い違う場合は `.phase-context.json` を正とする旨を明記すること。

**Step 4.2: 次アクションのプロンプト**
```
✓ Phase {N} completed successfully.

Deliverables:
  - {file1}
  - {file2}

Next:
  /run-phase {N+1}    - 次フェーズへ進む
  /finalize           - まとめてパッケージ化しアーカイブ
  /retrospective      - 学びの記録
```

## 複数フェーズ実行

範囲指定（例: `/run-phase 1-3` または `/run-phase all`）の場合:

**Strategy 1: 逐次 + チェックポイント**
```
range内の各フェーズについて:
  1. Phase N を実行（Builder + Validator）
  2. PASS → Phase N+1 へ
  3. NEEDS_REVISION → 一時停止
     - 検証課題を提示
     - 「今修正するか、次にスキップするか」を質問
  4. ユーザーが skip を選ぶ → "completed_with_issues" として記録
```

**Strategy 2: バッチモード（高速）**
```
range内の各フェーズについて:
  1. Builder のみ実行（Validatorなし）
  2. 次フェーズへ

すべて完了後:
  1. 全フェーズに対して Validator を実行
  2. 統合検証レポートを提示
  3. 一括修正（batch revision）を提案
```

ユーザーはフラグで戦略を選択可能:
- `/run-phase all --checkpoint` → Strategy 1（安全だが遅い）
- `/run-phase all --batch` → Strategy 2（高速だが最後にレビュー）
- `/run-phase all` → Strategy 3: スマートモード（デフォルト）

**Strategy 3: スマートモード（デフォルト、v6.4〜）**
```
range内の各フェーズについて:
  1. Builder を実行
  2. プリチェックを実行
  3. ファストパス判定:
     - ファストパス適用可 → 軽量検証 → PASS なら自動で次へ
     - ファストパス不可 → Validator フル検証（+ Step 2.5 の専門家）
  4. PASS → 自動で次フェーズへ（ユーザー確認なし）。ただし下記の例外
  5. NEEDS_REVISION → 一時停止してユーザー確認
```

Strategy 3 は Strategy 1 と Strategy 2 の中間。ファストパスが効くフェーズは高速に通過し、問題があるフェーズだけ停止する。

**例外（v15.1）: コードを変更するフェーズ（`small_implementation`、または `.claude/`・`scripts/` を変更したフェーズ）は、
PASS でも自動で次へ進まず、結果の要約（変更ファイル・検証コマンドの結果・残った Suggestion）を示して確認を取る。**
PASS 後に専門家が実害のある指摘を出す例が繰り返し起きており、実装を積み重ねてから気づくと手戻りが大きい
（別製品の開発工程では 20 フェーズすべてを 1 フェーズずつ回した）。`.claude/` を変更したフェーズの後は、
次のフェーズを新しいセッションで始める（Step 4.1.6）。

## エラーハンドリング

**Builder エージェントの失敗**
- タイムアウト（フェーズあたり10分超）→ 部分出力を保存しユーザーに確認
- ツールエラー → ログを残し1回だけ再試行
- 要件が不明確 → 一時停止してユーザーに確認

**Validator エージェントの失敗**
- 成果物が読めない → FAIL としてレポート
- タイムアウト → 検証をスキップし "not_validated" として記録

**依存関係の失敗**
- 前提フェーズ出力が欠けている → 前提フェーズ実行を自動提案
- フェーズ出力が破損 → フェーズ再実行か継続かを提案

## 品質ゲート

フェーズを完了とマークする前に:
- [ ] `SKILL.md` に指定された成果物がすべて存在
- [ ] Validator が正常に実行された（または `--no-validation` を使用）。起動した専門家も全員返っている
- [ ] クリティカルな検証問題が残っていない
- [ ] Step 2.4.1 の事後検査（`validate-outputs.py --require-verification`・`check_fix_cycle.py`）が exit 0
- [ ] 先送りした指摘が `findings-register.md` に ID 付きで移っている
- [ ] `metadata.json` が更新されている

## Builder / Validator エージェント定義

定義の正は `.claude/agents/builder.md`（`sdd-builder`）と `.claude/agents/validator.md`（`sdd-validator`）の
frontmatter と本文である。ここには複製しない（v15.0 はここに古い定義を複製しており、Validator を
「読み取り専用コマンドのみ」と書いて、検証コマンドを実行させる本文・Step 2.3 と食い違っていた）。
専門家は `/init-task` が `.claude/agents/generated/` に生成したもの（`templates/agents/*.md` が原本）。

## パフォーマンス最適化

**コンテキスト管理**
- 開始時に `docs/` を1回読み込み、全フェーズで再利用
- 各フェーズは自分の `SKILL.md` のみを読み込む
- 前フェーズ出力は必要時のみオンデマンドで読み込む

**並列実行（`--parallel` 指定時のみ。**実験的**。既定は逐次）**

1. `metadata.json` の `phases.{N}.depends_on` から依存グラフを作り、トポロジカルソートで
   「レベル」（互いに依存しないフェーズの集合）を求める（Step 0.3 参照）。`depends_on` 未指定の
   フェーズは既定値 `[N-1]` を使う
2. 同一レベル内のフェーズについて、メインセッションが `Task(subagent_type="sdd-builder", ...)` を
   **同一の応答ブロック内で複数回**呼び出す。Claude Code は同じ応答の中の独立したツール呼び出しを
   並行実行する。**ただしサブエージェントの並行起動が実際に重なって動くかは、Claude Code の版と
   環境で確かめていない**。初めて使うときは 2 フェーズ分で起動し、各 Builder の開始・終了時刻が
   重なることを確かめてから使う（確かめるまでは既定の逐次で回す）
3. **共有ファイルへの書き込みは並行実行中の Builder 自身が行わず、全 Builder 完了後にメインセッションが
   1つずつ順番に適用する**: `outputs/.phase-context.json`、ルート `metadata.json`、`CLAUDE.md` の
   Next Session Starter（Step 4.1 / 4.1.5 / 4.1.6）。各 Builder が書くのは自分の
   `outputs/phase-{N}/` 配下のみであり、レベル内のフェーズ同士では衝突しない
4. Validator は従来どおり順次実行する（コンテキスト競合を避ける）
5. **採用しない代替案**: `claude -p` の再帰的サブプロセスによる並列化（`eval/runner.py` と同じ機構）。
   ツールキット開発時に 2 プロセスの並行動作は実測したが、サブプロセスをプロジェクトの `CLAUDE.md` /
   hooks / Auto Memory から隔離しないと与えたプロンプトを無視して自律的な調査を始める（README §5.3
   「自己言及汚染」）。一方で Builder はプロジェクト全体の文脈を必要とするため、隔離と文脈確保が両立しない
6. **フラグを付けなければ常に逐次**（Strategy 1/2/3 は無変更）

**キャッシュ**
- パース済み `SKILL.md` 要件をキャッシュ
- `docs/` 内容をフェーズ間でキャッシュ
- 修正ループ間で検証基準を再利用

## 実行例

```bash
$ /run-phase 1

Loading context...
✓ CLAUDE.md
✓ docs/ (5 files)
✓ skills/phase-01/SKILL.md

Starting Phase 1: Research & Analysis
  └─ Builder agent executing...
     ├─ Reading background requirements
     ├─ Generating market analysis
     └─ Creating comparison table
  ✓ Deliverables saved to outputs/phase-01/

Starting Validation...
  └─ Validator agent reviewing...
     ├─ Checking completeness
     ├─ Verifying format
     └─ Assessing quality
  ⚠ Validation: NEEDS_REVISION (2 issues)

Critical Issues:
  1. Missing: Competitor pricing comparison
  2. Format: Table missing required columns

Auto-fix? [Y/n/review]
```
