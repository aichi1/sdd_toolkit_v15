# SDD Toolkit v15.1 — Spec-Driven Development for Claude Code

Claude Code で、タスクを **仕様 → 成果物生成 → 検証 → 完了処理 → 知見蓄積** の流れで進めるためのプロジェクトテンプレートです。

> 目的: Claude に「順序立てて考え、仕様を作り、成果物を生成し、検証し、最後に知見を残す」運用を定着させる

設計の中核は 2 つです。

- **Builder / Validator の分離** —— 生成する主体と評価する主体を別エージェントにする。Builder は自己採点しない
- **フェーズ間の構造化ハンドオフ** —— `outputs/.phase-context.json` が次フェーズへの正典になる

**このディレクトリはツールキット本体だけを含みます。** `/init-task` を実行すると、ここに `docs/`（仕様）・`skills/`（手順）・`CLAUDE.md`・`metadata.json` が生成され、プロジェクトとして動き始めます。

---

## クイックスタート

```bash
cd /home/aida/sdd_toolkit_v15
git init && git add -A && git commit -m "init: SDD Toolkit v15"   # 第2条（可逆性）に git が必要
claude
```

Claude Code のセッションで:

```
/init-task 「やりたいことを 1〜3 文で書く」
```

`/init-task` はタスクを 3 カテゴリ（`research_report` / `small_implementation` / `internal_proposal`）に分類し、`~/.sdd-knowledge/starters/` に confidence 0.7 以上の一致があればそれを土台にして仕様一式を生成します。あとは `/run-phase 1` から順に進めます。

**最初に確認すること**:

```bash
python3 -m pytest scripts/ -q          # 379 passed（v15.1）
python3 scripts/metrics.py --markdown  # 実測値の表。数値は手で書かずここから引く（テスト失敗時は exit 1）
```

---

## 1. コマンド一覧

`.claude/skills/<name>/SKILL.md` の実ファイルに 1 対 1 で対応します（**16 個**）。Claude Code 2.1 以降 `.claude/commands/*.md` と `.claude/skills/<name>/SKILL.md` はどちらも `/<name>` を作り同じように動作するため、本体コマンドは skills 側 1 箇所に統一してあります（C-28）。

**新しいコマンドを足すときは `.claude/skills/<name>/SKILL.md` を 1 ファイル作るだけです。** 他の登録作業はありません。

### 中核ワークフロー（この順に使う）

| コマンド | 役割 |
|---------|------|
| `/init-task` | タスクを 3 カテゴリに分類し、`docs/`・`skills/`・`CLAUDE.md`・`metadata.json` を生成。専門家エージェントを `.claude/agents/generated/` に召喚する |
| `/run-phase N` | Builder がフェーズの成果物を生成 → プリチェック → Validator が検証。`N` は単一（`1`）・範囲（`1-3`）・`all` |
| `/re-init-task` | 現イテレーション完了後、差分インテークで次イテレーションのフェーズを追加する |
| `/finalize` | `outputs/` を `~/.sdd-knowledge/` へアーカイブし、スターターを抽出・更新する |
| `/retrospective` | 構造化された振り返りを行い、教訓を `~/.sdd-knowledge/retrospectives/` に蓄積する |

### 仕様側の品質ゲート（任意）

`docs/` の曖昧さと未対応を実装の前後で機械的に検出します。すべて任意で、成果物を生成しません（`/clarify` と `/converge` は追記のみ）。

| コマンド | いつ | 役割 | 書き込み先 |
|---------|------|------|-----------|
| `/clarify` | フェーズ実行前 | 曖昧な箇所を最大 5 問で解消 | `docs/` に追記 |
| `/spec-check` | フェーズ実行前 | 参照の実在性・要件 ID の重複を機械検査（`scripts/spec_check.py`） | なし（読み取り専用） |
| `/analyze` | フェーズ実行後 | 要件 ↔ SKILL ↔ outputs の対応を検査（`scripts/trace_check.py`） | なし（読み取り専用） |
| `/converge` | イテレーション終了前 | 未達要件（`planned`/`deferred`/`dropped`）を記録 | `docs/convergence.md` に追記のみ |

順序は `/clarify` → `/spec-check`（曖昧さを消してから機械検査する）、`/analyze` → `/converge`（トレース結果が `/converge` の入力）。

### 補助・自己評価

| コマンド | 役割 |
|---------|------|
| `/update-docs` | `docs/` の充実度を診断し、対話的に補完・整合チェックする |
| `/lessons [category]` | 蓄積された教訓を検索・参照する |
| `/metrics` | `python3 scripts/metrics.py --markdown` の実測値を表示する（読み取り専用） |
| `/add-feature [名前]` | フェーズ workflow の外で、アドホックな機能追加を `.steering/` で管理する |
| `/eval <iteration_id>` | 固定 3 シナリオ（T1/T2/T3）を 7 軸で採点し、履歴化・レポート化する |
| `/plot` | `eval/history/` からグラフを生成する（matplotlib が無ければスキップ） |
| `/improve-toolkit <iteration_id>` | ツールキット改良 → 評価 → 記録を一連で行う |
| `/extras:create-deck` | Markdown からプレゼン HTML を生成する（SDD ワークフロー外のユーティリティ） |

---

## 2. ディレクトリ構成

```text
.
├── .claude/
│   ├── agents/              # 常設エージェント（6）
│   │   ├── planner.md            カテゴリ選定・WBS・方針
│   │   ├── researcher.md         知識ベースからの再利用案
│   │   ├── builder.md            成果物生成（自己採点しない）
│   │   ├── validator.md          要件照合と検証（成果物を変更しない。検証コマンドは実行する）
│   │   ├── eval-judge.md         シナリオ成果物の採点（生成しない）
│   │   ├── knowledge-curator.md  知見の反映
│   │   └── generated/            /init-task が召喚する専門家（gitignore 対象）
│   ├── commands/extras/     # SDD ワークフロー外のユーティリティのみ
│   ├── hooks/               # PreToolUse / PostToolUse / Stop / SessionStart（4）
│   ├── rules/               # 自動注入される中核ルール（5。圧縮済み）
│   ├── skills/              # 各コマンドの実体（16）
│   └── settings.json        # sandbox / permissions / hooks
├── docs/                    # ツールキット自身の文書
│   ├── CHANGELOG.md              版ごとの変更履歴
│   ├── rules-reference/          rules の詳細版（自動注入されない。9 ファイル。要件 ID 規約を含む）
│   ├── spec-check-allowlist.json spec_check.py が読む唯一の許可リスト
│   ├── spec-check-allowlist.md   その人間向け説明（パーサは読まない）
│   ├── self-improvement.md / scenario-review-guide.md / future-categories.md
│   └── （/init-task が requirements.md・plan.md・team.md・tech-stack.md・
│         io-spec.md・constraints.md・constitution.md・_manifest.json を追加生成する）
├── eval/                    # 自己評価（ツールキット自身を測る）
│   ├── rubric.json               7 軸の定義（変更しない）
│   ├── SCORING_GUIDE.md          採点手順・アンカー・上限制約
│   ├── scenarios/                固定 3 シナリオ（追加のみ。変更・削除しない）
│   ├── runner.py                 claude -p でシナリオを実行し軌跡を実測
│   ├── aggregate.py              runs/ → history/ + summary.csv
│   ├── history/ reports/         集計履歴と版ごとのレポート
│   └── summary.csv               時系列の 7 軸スコア（既存列を変更しない）
├── scripts/                 # 検証・知識ベース・ユーティリティ（28 / うちテスト 12）
├── templates/               # 生成テンプレート（34。convergence.md・findings-register.md を含む）
├── validate_rules.yaml      # プロジェクトタイプ別のプリチェック除外ルール
└── （/init-task が skills/・outputs/・CLAUDE.md・metadata.json を作る）
```

**`docs/` は What（仕様）、`skills/` は How（手順）** という分離が原則です。`docs/` が正であり、変われば `skills/` を追随させます。

---

## 3. ランブック

### 3.1 新規プロジェクトを立ち上げる

1. **git を初期化する。** `patch.diff` による可逆性（憲法第2条）が git に依存します
2. `/init-task 「タスク記述」` —— カテゴリ判定 → スターター照合 → `docs/` `skills/` `CLAUDE.md` `metadata.json` 生成
3. **`/clarify` → `/spec-check` を回す。** ここで `docs/` の曖昧さを潰しておくと、後のフェーズの修正サイクルが目に見えて減ります
4. `/run-phase 1` から順に進める

### 3.2 1 フェーズを回す

1. **Builder** が `skills/phase-NN/SKILL.md` の手順どおりに成果物を生成し、`outputs/phase-NN/` と `.metadata.json` に保存する
2. **プリチェック** `python3 scripts/validate-outputs.py --phase N [--project-type TYPE]`
   —— FAIL なら Validator を起動せず Builder に差し戻す（時間の節約）
3. **ファストパス判定** —— プリチェック全 PASS かつ Quality Criteria 5 項目以下かつ成果物 3 件以下なら、Validator フルエージェントを起動せずメインセッションで軽量検証する
4. **Validator** が Quality Criteria の全項目を Met / Partial / Missing で判定し、`.validation/report-round{R}.md`
   （巡ごと。上書きしない）と `.validation/report.md`（最新の巡）を作る
5. **専門家レビュー（任意）** —— `docs/team.md` と**実際の変更**（`git status --porcelain --untracked-files=all`）から選んだ専門家を、
   Validator と**同じ巡で並行**して起動する。指摘は `.validation/expert-<agent>-round{R}.md` に原文で残す。
   判定は全員が返ってから
6. **事後検査** `validate-outputs.py --phase N --require-verification` と `check_fix_cycle.py --phase N`
7. PASS → `outputs/.phase-context.json` を更新して次フェーズへ。先送りした指摘は `findings-register.md` へ

複数フェーズ:

| 指定 | 戦略 |
|------|------|
| `/run-phase all` | スマートモード（既定）。ファストパスが効くフェーズは高速通過、問題があるフェーズだけ停止。**コードを変更するフェーズ（`small_implementation` など）は PASS でも確認を挟む**（v15.1） |
| `/run-phase all --checkpoint` | 逐次 + 各フェーズでユーザー確認（安全だが遅い） |
| `/run-phase all --batch` | Builder のみ先に全実行し、最後にまとめて検証（高速だがレビューが後） |
| `/run-phase 1-4 --parallel` | **実験的**。`metadata.json` の `depends_on` で依存の無いフェーズを同時起動する。**Task ツール経由の並行実行は未検証**。使う前に 2 フェーズ分で開始・終了時刻が重なることを確かめること |

### 3.3 修正サイクルをどこで止めるか（最重要）

**修正サイクルは「Critical 0」では止まりません。** 敵対的な Validator と拡大する対象があれば必ず何か出ます。

> **止める条件は「Gate 0〜2 と機械検査がすべて green であること」です。**
> Gate 3（一貫性）だけを根拠とする指摘は Suggestion に落として先へ進みます。

- Gate 0（基本的完全性）/ Gate 1（docs 要件）/ Gate 2（SKILL.md 品質基準）は**免除不可**
- Gate 3（一貫性）は **recommended・既定で免除可**。`3-only` の指摘を Critical にしてはいけません
- **3 巡目以降は「現状を受け入れて先へ進む」を毎巡、対等な選択肢として提示する**こと。`.metadata.json` の `revision_history` 最終エントリに `owner_decision` を書かないと `scripts/check_fix_cycle.py` が違反として検出します
- **修正サイクルを開いた根拠を `revision_history[].opened_by` に書く**（`validator_critical` / `expert_defect` / `owner_decision` / `main_session`）。Validator が Critical 0 でも、専門家の指摘やオーナー決定で開くサイクルは正当です。違反は根拠が無いことだけ
- **修正したら、その指摘を見つけた検査を再実行してから報告する**。別製品の開発工程では、2 巡目以降の指摘の 38% が前の巡の修正が生んだ回帰でした
- 形式・作法だけの指摘（引用位置・見出し・書式・用語）は修正サイクルを開かず `findings-register.md` へ。ただし出荷物が事実と違うことを述べているなら内容の欠陥です

```bash
python3 scripts/check_fix_cycle.py --phase N   # 打ち切り規則と Gate 帰属を機械検査する
```

> この規則はツールキットに**最初からあった**もので、使っていなかっただけでした。開発プロジェクトの Phase 07 は
> これを使わずに **12 巡**し、Critical 42 件のうち 18 件（43%）は SKILL.md の範囲外でした。
> 機械検査に落とした以降のフェーズは 1〜2 巡で収束しています。

### 3.4 イテレーションを終える

```
[/analyze]        要件 ↔ SKILL ↔ outputs のトレーサビリティ検査
[/converge]       未達要件を docs/convergence.md に追記（既存行は書き換えない）
/finalize         ~/.sdd-knowledge/ へアーカイブ + スターター更新 + outputs/final/ へ集約
/retrospective    教訓を構造化して蓄積
```

続ける場合は `/re-init-task` で次イテレーションのフェーズを追加します。**次のイテレーションで取り組む項目は 1〜2 個に絞ってください。**

### 3.5 よくある詰まり

| 症状 | 原因と対処 |
|------|-----------|
| プリチェックが README / src / tests を要求して FAIL する | カテゴリ既定の必須セクション。`--project-type` を指定するか `validate_rules.yaml` に型を足す |
| `git apply --reverse --check patch.diff` が exit 1 | `patch.diff` 生成後にファイルを変更した。**順序は「全ファイル変更 → patch.diff 再生成 → 検証 → 記録」**。コミット済みなら第2条の対象外（`git revert` を使う） |
| `patch.diff` を戻してもテスト数が減らない | `git diff HEAD` は**未追跡ファイルを含みません**。新規追加したファイルは別途削除する必要があります |
| `spec_check.py` が意図的な参照を欠陥と報告する | `docs/spec-check-allowlist.json` に 1 件足し、**reason を必ず書く**（空だと無効）。前方参照は実物を作った時点で削除する。履歴文書はファイル単位の `excludes`、製品を別リポジトリに置く構成は `resolve_roots` で宣言する（v15.1） |
| `/analyze` が `missing_section` を報告する | `docs/requirements.md` に `## 5. 機能要件（R-ID）` の見出しと表が無い。規約は `docs/rules-reference/requirement-id-convention.md`。v15.0 はこの場合「要件 0 件・OK」を黙って返していた |
| `/converge` の記録先が無い | 初回の `/converge` が `templates/convergence.md` から `docs/convergence.md` を作る。独自形式の既存ファイルは書き換えずに止まる |
| hooks でセッションが止まる | hooks は例外を握って exit 0 する設計です。壊れたら `claude --safe-mode` で起動し `git apply --reverse` |
| Validator が検証コマンドを実行しない | `docs/tech-stack.md` §4 に定義したコマンドは全件実行が必須。未実行は Critical になります |
| サブエージェントに権限で禁じたはずの操作ができてしまう | **既知の制約**。§5 を参照 |

---

## 4. 憲法（Constitution）

`/init-task` は `templates/constitution.md` を土台に `docs/constitution.md` を生成します。**非交渉のルールを条文にし、機械検査に落とす**のが狙いです。開発プロジェクトで実際に使った 11 条は次のとおりです。

| 条 | 原則 | 強制点の例 |
|----|------|-----------|
| 第1条 | 検証は実行して確かめる | `verification.log` にコマンド行と exit code がある |
| 第2条 | 変更は必ず可逆 | `git apply --reverse --check patch.diff` が exit 0 |
| 第3条 | 自分自身を壊さない | 1 フェーズ 1 テーマ／変更中のスキルを同じフェーズで実行しない |
| 第4条 | 後方互換を壊さない | `eval/scenarios/`・`summary.csv` 既存列・`rubric.json` 7 軸 |
| 第5条 | 依存を増やさない | 新規 pip 依存なし |
| 第6条 | 権限は絞る方向にしか動かさない | `deny` を緩めない／`allowedDomains` は縮小のみ |
| 第7条 | 足すだけでなく消す | 効果が測れなければ削除 or 既定オフ |
| 第8条 | バージョン依存機能は確認してから使う | `claude --version` + 実測 |
| 第9条 | 指摘は仕様を引用する | `Required by:` の無い Issue を出さない |
| 第10条 | 自己変更の次フェーズは新セッションで開始する | `.metadata.json` の `session` を照合 |
| 第11条 | `.phase-context.json` に自己変更を記録する | `self_modified_files` / `stale_procedures` |

```bash
python3 scripts/check_constitution.py --phase N                   # 第2条（汎用）のみ。既定
python3 scripts/check_constitution.py --phase N --profile toolkit # 下表の全条（ツールキット自己改善用）
```

> **第3/4/10/11 条の検査はツールキット自己改善プロジェクトの条文に固定されています。** 利用者のプロジェクトでは
> 条番号の意味が違うため、v15.1 から既定では実行しません（v15.0 は `--article` 省略時に全条を実行していた）。

**矛盾を見つけたら Validator がオーナーへエスカレーションします。Builder が独断で条項を曲げてはいけません。**

---

## 5. 既知の制約（必ず読む）

### 5.1 サブエージェントの権限は「指示レベル」にとどまる

**Claude Code 2.1.263 では、「読み取り系コマンドは許可しつつ Bash の書き込みだけを技術的に塞ぐ」ことができません。**

隔離環境で 4 系統を実測した結果です。

| 方式 | 結果 |
|------|------|
| `--agents` JSON の `tools` / `disallowedTools` にコマンドパターン | **塞げない**（`permission_denials: []` でファイルが実際に書き換わる） |
| CLI `--disallowedTools "Bash(echo * > *)"` | **塞げない** |
| `--settings '{"permissions":{"deny":["Bash(echo * > *)"]}}'` | **塞げない** |
| `--disallowedTools "Bash"`（ツール名の完全一致） | **塞げる**（ただし Bash が丸ごと使えなくなる） |

パターンは**単一の末尾ワイルドカードによる前方一致**しか効かず、許可パターンの末尾に `> file` を足せば同じパターンに一致してしまいます。したがって `.claude/agents/validator.md` の「Validator は読み取り専用」は**指示レベルの制約**であり、技術的な強制ではありません。

`eval/runner.py` の Judge は例外で、`--tools Read,Glob,Grep` によって Write/Edit/Bash を**技術的に**選べなくしています（呼び出し側から絞る方式）。

### 5.2 自己申告は、具体的で自信に満ちているほど危うい

権限で拒否されたコマンドについて、モデルが「`echo LOCAL_OK > ./local.txt` — **Exit code: 0**（succeeded, file created）」と**具体的な exit code つきで虚偽の成功を報告**した生 API 応答が記録されています。

> **証跡は「実行したコマンド行と exit code」であって、結果の要約ではありません。**
> 「詳細は `verification.log` を参照」と書いたなら、**本当にそこにあるか grep して確かめてください。**

### 5.3 `claude -p` の再帰呼び出しと自己言及汚染

`claude -p` の再帰呼び出しは `deny` で塞がれていません。ただし cwd をプロジェクト直下のままにすると、プロジェクト自身の `CLAUDE.md` / hooks / Auto Memory を読み込み、与えたプロンプトを無視して自律的な調査を始めます。`eval/runner.py` は cwd を一時ディレクトリにし `--setting-sources user` を付けることでこれを回避しています。

### 5.4 セッション ID の測り方

第10条（自己変更の次フェーズは新セッション）の判定に使うセッション ID は、**`/tmp/claude-*/<project-slug>/` 配下で mtime が最新のディレクトリ名**で測ります。

```bash
ls -ldt --time-style=+%Y-%m-%dT%H:%M:%S /tmp/claude-*/<project-slug>/*/ | head -1
```

`ls -t ~/.claude/projects/*/*.jsonl` と**環境が示す scratchpad パス**は、どちらも再開・コンパクション後に**再開元の UUID を保持する**ため使えません（両方とも実際に誤判定を起こしました）。

### 5.5 `knowledge_curator.py` の重複追記（C-57）— v15.1 で修正済み

v15.0 では `scripts/knowledge_curator.py` が `~/.sdd-knowledge/candidates.jsonl` へ無条件に追記し、さらに
`scripts/promote_candidates.py` の圧縮が `suggested_id` を持たない curator 候補（`/retrospective` の出力）を
**次の `/finalize` で全件消していました**。v15.1 で両方を直しました（追記は既存のキーを見て新規だけ、
圧縮はコンポーネント候補以外の行を元の順序のまま残す）。

**v15.0 から作ったプロジェクトは、プロジェクト内の `scripts/` の古い写しを使い続けます**（`post-phase-complete.sh` と
`/finalize` はプロジェクトの `scripts/` を優先する）。直したい場合は、該当スクリプトを v15.1 のものに差し替えてください。

---

## 6. 設計上の教訓（15 フェーズの実運用から）

このツールキットは自分自身を 3 イテレーション・15 フェーズかけて改良しました。効いた原則を挙げます。

**規約を先に決めてから実装する。** 逆順にすると実装が規約を決めてしまいます。規約先行のフェーズは修正 0 巡で通り、逆順のフェーズは 12 巡しました。

**自然言語の判断を正規表現で解こうとしない。** ヒューリスティックで誤検出を抑えようとすると、回避経路が生まれ続けます（3 巡の修正で 10 件の穴）。**許可リストや明示的な宣言で解けないか先に考える。** 許可リスト方式にしたところ、抑制はすべて 1 つの JSON に現れ、回避経路という概念自体が消えました。

**証跡は「決められた 1 行・決められた表」であって散文ではない。** 検査の対象範囲を構造で狭めると、自然言語の判定を一切しないで済みます。広い範囲に賢い判定を置かないこと。

**新しく作った検査は、「素通りする入力」を自分で探してから出す。** フェンス内の引用で偽 PASS を出し、「実行していない」という否定文で pass した実例があります。

**仕様どうしが食い違っているとき、どちらが正しいかを Builder が選んではいけない。** 選んだ結果が妥当に見えるときほど危険です。オーナーへ提起し、決定を機械検査に落とします。

**「解消済み」と書けるのは発生源を塞いだときだけ。** 症状側の緩和なら「緩和」と書きます。追記ファイルの肥大化を「解消済み」と記録した対処が実は圧縮だけで、無条件追記の発生源が 3 フェーズ後まで残っていました。

**同じ欠陥パターンは 3 階層で再発する。** 同じ関数 / 同じファイルの別フィールド / **別ファイルの兄弟関数**。1 つ直したら残り 2 階層を必ず走査してください。開発プロジェクトで 3 回とも起きました。

**数値は計測スクリプトの出力を引く。手で書かない。** `python3 scripts/metrics.py --markdown` の出力をそのまま貼ります。手で書いた数値が実体からずれる失敗を 5 回繰り返しました。

**役割の違うレビュアーを重ねると、違う種類の欠陥が見つかる。** doc_editor は 6 フェーズ連続で Validator の見落としを独立検出しました。

**実測できるようになったからといって機械的に点を上げない。** 測れるようになった結果、据え置く・下げる判断もありえます。

---

## 7. 知識ベース

`~/.sdd-knowledge/`（ローカル環境にのみ作成されます）。

```text
~/.sdd-knowledge/
├── starters/            カテゴリ別の再利用テンプレート（confidence スコア付き）
├── retrospectives/      振り返り JSON + summary.json
├── docs-archive/        完了プロジェクトのアーカイブ
├── skills-library/ agents-library/ hooks-library/ rules-library/
├── search-index/        BM25 インデックス
└── active-context.md    /init-task が生成する当該タスク向けの抜粋
```

**再利用のループ**:

```
/init-task がタスク記述を受け取る
   ↓  scripts/generate_context.py が関連コンポーネントと教訓を抽出
   ↓  starters/ に confidence > 0.7 の一致があればそれを土台にする
プロジェクト実行
   ↓
/finalize が docs-archive/ へ保存し starters/ を更新
/retrospective が retrospectives/ に教訓を追加
   ↓
次のプロジェクトの /init-task がそれを読む
```

---

## 8. 自己評価ループ

ツールキット自身を改良し、**同じ土俵で効果を測る**仕組みです（モデルの重みは更新しません）。

```
改良テーマを決める
   ↓
/improve-toolkit <id>                       変更を実装
   ↓
python3 eval/runner.py --iteration <id> --live   シナリオを実行し軌跡（turns/retries/tool_calls）を実測
   ↓
/eval <id>                                  7 軸で採点 → eval/runs/<id>/*/score.json
   ↓
python3 eval/aggregate.py --iteration <id>  → eval/history/ と eval/summary.csv
   ↓
eval/reports/<date>_<id>.md に前回比と根拠を残す
```

評価軸（`eval/rubric.json`、0〜5 点）: `correctness` / `completeness` / `efficiency` / `robustness` / `maintainability` / `usability` / `safety`

採点のブレを抑えるため、**必ず `eval/SCORING_GUIDE.md` の手順・アンカー・上限制約に従ってください。証拠のない点数は付けません。**

### 比較可能性の担保（第4条）

- `eval/scenarios/` の 3 シナリオは**追加のみ**（既存を変更・削除しない）
- `eval/summary.csv` の既存 10 列と `eval/rubric.json` の 7 軸定義は変更しない
- **点を上げる条件を先に決める。** 前回のレポートに「次回この軸を上げるには何が必要か」を書き、次回はそれを満たしたかで判断します。**後から緩めないこと。**

### 履歴

| 版 | 日付 | 総合 | 主な変更 |
|----|------|------|---------|
| **v15.1** | 2026-09-18 | 未評価 | 安定版としての不具合修正（検査スクリプトの偽 PASS・クラッシュ、フックの出力キー・パス判定・停止保証、`/analyze`・`/converge` が利用者のプロジェクトで動かない問題）と、別製品の開発工程（v15 で 20 フェーズ）の実測に基づく工程改善（巡ごとの報告保存、専門家レビューの枠と原文保存、`opened_by`、修正後の再検査、数えてから書く、指摘の登録簿）。`/eval` による再採点はしていない。詳細は `docs/CHANGELOG.md` |
| v15 | 2026-09-06 | **4.286** | `eval/runner.py`（`/eval` 半自動化・Judge 分離）、コマンド/スキルの二層重複を一本化（C-28）、修正サイクル打ち切りと Gate 帰属の機械検査、`depends_on` / `--parallel`、`memory-policy.md`。新コマンド追加が 1 ファイルで済み `trace_check.py` / pytest が非退行であることを実測し **maintainability を 4→5**。`efficiency` は `runner.py --live` の実測値で初めて根拠付きで判定（4 のまま据え置き）。safety の Bash 書き込み技術的封鎖は隔離実験で `not_achievable` と確定し据え置き |
| v14 | 2026-09-06 | 4.143 | 仕様側の品質ゲート（`/clarify` `/spec-check` `/analyze` `/converge`）。`trace_check.py` が未対応要件を、`spec_check.py` が矛盾を検出できることを実測し **correctness を 4→5** |
| v13 | 2026-09-04 | 4.000 | Validator にテスト実行能力を付与、`/add-feature` の停止条件化、衛生・整合性の回復 |
| v12 | 2026-09-03 | 3.571 | ベースライン取得 |
| v6.4 | 2026-02-12 | 3.571 | — |

詳細は `docs/CHANGELOG.md` と `eval/reports/` を参照してください。

---

## 9. hooks（自動ガード）

`.claude/settings.json` に定義されています。

| イベント（matcher） | スクリプト | 動作 |
|---------|-----------|------|
| PreToolUse（`Write\|Edit`） | `check-docs-exist.py` | `outputs/` への書き込みのときだけ、`docs/_manifest.json` の `required_files` を検証し、不足があれば**警告**（ブロックしない） |
| PostToolUse（`Write`） | `check-validation-exists.py` | `outputs/phase-NN/.metadata.json` への書き込みのときだけ、`.validation/` の有無を確認し、不足があれば**警告** |
| Stop | `remind-finalize.py` | 成果物があるのに `/finalize` 未実行ならリマインド（`stop_hook_active` の間は停止を許可） |
| SessionStart | `session-start-info.py` | 知識ベースのスターター・教訓の有無を表示 |

hooks は**例外でセッションを止めません**（try/except で握り、警告出力に留めて exit 0）。
警告は `systemMessage`（利用者に表示される）で返します。パスの判定はスクリプト側で、`CLAUDE_PROJECT_DIR`
からの相対パスに直して行います（matcher はツール名だけを見る）。**`settings.json` や hooks を変えたら、
新しいセッションで確かめてください**（同じセッションには古い定義が残ることがある）。

### 9.1 v15.0 では PreToolUse / PostToolUse の 3 フックが一度も起動していなかった（v15.1 で修正）

v15.0 の matcher `Write(outputs/**)`・`Write(outputs/**)|Edit(outputs/**)`・`Write(outputs/**/.metadata.json)` は、
Claude Code がツール名と照合する**正規表現として不正**でした（`/**` の二重の量指定子。`node -e 'new RegExp("Write(outputs/**)")'`
で再現）。Claude Code 2.1.276 は不正な matcher を「一致しない」と扱うため、3 本とも起動していませんでした
（仮に有効な正規表現でも、ツール名 `Write` とは一致しない）。v15.1 でオーナー承認のうえ次のように直しました。

- PreToolUse の matcher を `Write|Edit`、PostToolUse（`check-validation-exists.py`）の matcher を `Write` に。
  パスの絞り込みはスクリプト側で行う
- `scripts/post-phase-complete.sh`（コンポーネント候補の自動抽出）の PostToolUse 登録を外した。`/finalize` が同じ
  `extract_components.py` を実行しており、v15.0 では一度も動いていなかった（「効果が測れなければ削除」）。
  スクリプト自体は残してあり、手で実行できる

## 10. 前提条件と注意

- **Claude Code 2.1.263** で動作確認しています
  - 2.1.259 → 2.1.260 の間に **`/agents` ウィザードが削除**されています。サブエージェント定義の確認は frontmatter を直接読むか、実際に起動して確かめてください
- **Python 3.10+**（標準ライブラリ優先。既存依存: PyYAML / FastAPI、任意: matplotlib）
- **Linux / WSL** を主対象（macOS でも動作を壊さない方針）
- `.claude/settings.json` は**プロジェクトスコープ**です。個人設定は `.claude/settings.local.json`（gitignore 対象）に置きます
- `.claude/agents/generated/` はプロジェクト固有の生成物であり gitignore 対象です。`/init-task` が再生成します
- Windows で zip 展開したファイルに `*:Zone.Identifier` が混ざることがあります。`.gitignore` で除外しています

### このディレクトリの初期状態（実測値）

```
python3 -m pytest scripts/ -q     → 379 passed
python3 scripts/spec_check.py     → 0 件（docs/CHANGELOG.md は excludes で走査対象外。出力末尾に表示される）
python3 scripts/trace_check.py    → 要件 0 件 / 欠陥 0 件（docs/requirements.md が無いため。/init-task 後は §5 の表を読む）
```

v15.0 の README は「`spec_check.py` の 26 件は `/init-task` を実行すると解消する」と書いていましたが、実際には大半が
開発リポジトリにしか無いファイル（`docs/roadmap.md` など）への `docs/CHANGELOG.md` の履歴参照で、`/init-task` 後も
残り続けていました。v15.1 で履歴文書をファイル単位の `excludes` に宣言し、0 件から始まるようにしました。

### 開発リポジトリとの関係

このディレクトリは、ツールキットを v12 → v15 に改良した自己改善プロジェクトから**ツールキット本体だけを取り出した**ものです。
v15.1 は、v15 を工程として別製品（sdd-harness）を開発した兄弟プロジェクトの実測を取り込んだ安定版です。v15.0 の状態は git タグ `v15.0-baseline` で参照できます。以下は開発リポジトリ側に残しています。

- そのプロジェクトの `docs/`（requirements / plan / team / tech-stack / io-spec / constraints / constitution / convergence / roadmap）
- `skills/phase-01` 〜 `phase-15`、`outputs/`（全 15 フェーズの `patch.diff` / `change-report.md` / `verification.log` / `.validation/`）
- `eval/runs/`（シナリオ別の採点記録）、`CLAUDE.md`、`metadata.json`、`retrospective.md`、`finalization-report.md`

**取り出しにあたって加えた変更**は 2 件です。どちらも「実データの*状態*に固定していたテストを*不変条件*に直す」もので、ツールキット単体で pytest が通るようにするための最小修正です（C-55）。

- `scripts/test_metrics.py::TestRealProject::test_no_silent_zero` —— 入力ファイルが存在するときだけ非 0 を要求する形に変更
- `scripts/test_trace_check.py::test_matrix_covers_every_requirement` —— 「29 件以上」という状態の固定をやめ、「対応表の ID 集合 == 要件の ID 集合」という不変条件と空振り検出だけを残した
