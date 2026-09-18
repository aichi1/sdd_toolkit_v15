# Changelog

## v15.1 (2026-09-18) — 安定版としての不具合修正と、実運用データに基づく工程改善

v15.0 の状態は git タグ **`v15.0-baseline`**（13c0e0f）に固定した。v15 を工程として別製品（sdd-harness）を
20 フェーズ開発した兄弟プロジェクトの記録（修正サイクルの指摘 181 件の分類）と、v15 で作られた利用者プロジェクトの
実物を読んで洗い出した。**`/eval` による再採点はしていない**（7 軸の点数は v15.0 のまま）。

### Fixed — 検査が黙って通していた・落ちていたもの

- **`check_fix_cycle.py`**: run-phase SKILL.md 自身の報告雛形（`### Critical Issues` + 太字なしの `- Location:`）どおりに
  書かれた報告を「Critical Issue 0 件」として素通りさせていた（Gate 欄なし・一貫性だけの Critical でも OK）。
  `###` 以下の Critical 見出しと素の `Location:` を読むように。壊れた `.metadata.json` は skip ではなく fail、
  存在しないフェーズ・整数でない `--phase` は exit 2
- **`trace_check.py`（/analyze）**: `docs/requirements.md` に `## 5. 機能要件（R-ID）` が無いと「要件 0 件・欠陥 0 件・OK」を
  返していた → `missing_section`（欠陥）。`metadata.json` の `phases` が配列だと AttributeError で落ちていた（実プロジェクトで再現）
  → 配列も読む。列の足りない要件行を黙って捨てていた → `convention_violation`。存在しない `--project-dir` は exit 2
- **`spec_check.py`**: `/home/...`・`/usr/bin/...`・`/notes.md` をスラッシュコマンドと誤認していた（拡張子で除外するはずの
  関数は一度も真にならないデッドコードだった）。存在しない `--project-dir` は exit 2
- **`validate-outputs.py`**: `.metadata.json` の `deliverables` に挙げたファイルが欠落・0 バイトでも PASS だった
  （Gate 0 違反がファストパスで Validator を飛ばしうる）→ 1 件ずつ実在と非空を検査。`--require-verification` が
  `**Overall Status: PASS**` などの書式で判定語を読めず、exit≠0 の行があっても「整合」と判定していた → 閉じた書式集合で読み、
  読めなければ fail。非 UTF-8 のファイルで落ちていた
- **`check_constitution.py`**: `--article` 省略時にツールキット自己改善専用の第3/4/10/11 条まで実行していた → 既定は汎用の
  第2条のみ、`--profile toolkit` で全条。実装の無い条番号を指定すると「0 件実行・OK」だった → exit 2
- **`knowledge_curator.py`（C-57）**: `candidates.jsonl` への無条件追記 → 既存キーを見て新規だけ追記
- **`promote_candidates.py`**: 圧縮が curator 候補（`/retrospective` の出力）を全件消していた → コンポーネント候補以外の行を残す
- **`extract_components.py`**: 同一バッチ内の重複、数字でないフェーズディレクトリでのクラッシュ
- **`aggregate_outputs.py`**: 改名後の名前が実在ファイルと衝突すると上書きしていた（C-45 の再発）
- **`metrics.py`**: git 管理外でクラッシュ、`--markdown` がテスト失敗を隠して exit 0 → failed 件数と exit code を表示し exit 1
- **`.claude/settings.json` のフック（オーナー承認済み）**: PreToolUse / PostToolUse の matcher（`Write(outputs/**)` など）は
  JavaScript の正規表現として不正で、**v15.0 ではこの 3 フックが一度も起動していなかった** → matcher を `Write|Edit` / `Write` に。
  `/finalize` と重複する `post-phase-complete.sh` の登録は外した
- **hooks のスクリプト**: 出力キー `message` は Claude Code が認識しない → `systemMessage`。`tool_input.file_path` は絶対パスで渡るのに
  `startswith("outputs/")` で判定していた → プロジェクトルート（`CLAUDE_PROJECT_DIR`）相対で判定。Stop フックが
  `stop_hook_active` を読まず、カウンタを書けない環境で継続指示を返し続けた → 停止を許可
- **`/converge`**: 記録先 `docs/convergence.md` をどこも作らないのに「新規ファイルは作らない」と定めており、利用者の
  プロジェクトで一度も実行できなかった → `templates/convergence.md` を新設し、無ければそこから作る
- **`/init-task`**: `requirements.md` の §5（R-ID 表）、`metadata.json` の `phases` の形、`tech-stack.md` §4（Validator が
  全件実行する検証コマンド）、`io-spec.md` §2.5.2・§2.6 の中身を規定していなかった → 規定し、スターター経由でも満たすよう品質ゲートに加えた。
  `/re-init-task` も新しい要件を §5 の表に足すよう直した
- **`check_constitution.py` の「改正履歴の追認状況」検査**は第3条の中にしか無く、利用者のプロジェクトでは実行されなかった →
  条番号に依存しない「改正手続き」の検査として既定でも走る

### Fixed — 文書どうしの矛盾

- `validator.md` の判定疑似コードが「Critical 3 件以下なら NEEDS_REVISION」で規則（1〜5 件）と食い違っていた
- `validator.md` の一貫性チェックの疑似コードと「パターン3」が、一貫性だけの指摘を Critical にしていた（C-50 と矛盾）
- run-phase の報告雛形に `Gate` / `Required by` が無く、rules の Validator Rule 3 と矛盾していた
- run-phase の「エージェント定義」節が Validator を「読み取り専用コマンドのみ」と書き、検証コマンドを実行させる Step 2.3 と矛盾していた
- run-phase Step 3.3（2 巡後は「auto-fix を続けるか手動に切り替えるか」）が、rules の打ち切り規則（Accept を対等な選択肢に・
  `owner_decision`）と食い違っていた
- 利用者のプロジェクトでは別物を指す開発リポジトリの参照のうち、**手順や事実の記述になっていたもの**
  （`outputs/phase-14/change-report.md` §3、「既存フェーズ 01〜14 は…」、`docs/constraints.md` §3.1、
  `CLAUDE.md`「11 巡で収束しなかった理由」など）を一般的な記述に置き換えた。出典として括弧で付いているだけの
  内部 ID（`R-06`・`C-50`・`Phase 14` など）は残している

### Added — 実運用データに基づく工程改善（兄弟プロジェクトの 181 件の分類から）

- **巡ごとの報告保存**: `.validation/report-round{R}.md`（上書きしない）+ `report.md`（最新）。過去巡の原文が 4 フェーズで消え、原因分析ができなかった
- **専門家レビューの枠（run-phase Step 2.5）**: `docs/team.md` と実 diff で選び、Validator と同じ巡で並行起動。指摘は
  `.validation/expert-<agent>-round{R}.md` に原文で残す（10 フェーズすべてで一行要約しか残っていなかった）。判定は全員が返ってから
- **`revision_history[].opened_by`**（`check_fix_cycle.py` が検査）。「Critical 0 なのにサイクルがある」は違反にしない
- **修正後の再検査**（builder.md）: 指摘を見つけた検査を再実行し、「一致すべき組」を数え直してから報告する。2 巡目以降の指摘の 37.9% が回帰だった
- **数えてから書く**（builder.md・rules）。**形式だけの指摘は修正サイクルを開かない**（出荷物が事実と違う場合を除く）
- **小さな指摘は巡を回さずに閉じてよい**条件（直前の Validator が PASS で、閉じるのが Suggestion・形式・専門家の Medium/Low・
  記録の訂正に限られ、成果物の主張を変えない。機械検査は必ず回す。Validator の Critical と専門家の High には使えない）
- **指摘の登録簿** `templates/findings-register.md`（`.phase-context.json` の `pending_issues` は上書きされて消えるため）
- **Builder の 2 段階起動**（設計判断を含むフェーズ）、**スマートモードでもコード変更フェーズは PASS 後に確認**、
  セッション再開時は起動済みエージェントを確かめてから再起動
- `spec_check.py` の許可リストに `excludes`（履歴文書）と `resolve_roots`（製品を別リポジトリに置く構成）。ツールキット単体の
  検出は 26 件（24 件が CHANGELOG の履歴参照、1 件が `memory-policy.md` の開発リポジトリ参照、1 件が `/run-phase` の生成物への
  前方参照）→ 0 件
- `docs/rules-reference/requirement-id-convention.md`（要件 ID 規約。開発プロジェクトの requirements.md §9 から移設）
- 専門家エージェントの原本（`templates/agents/*.md`）に、原文の書き出し先と構造化形式

### 未対応

- `/eval` による再採点（7 軸の点数は v15.0 のまま）
- `eval/runner.py`（コードを読んで挙動は確認。設計意図かは未確認のため未修正）: `--live` なしの実行でも
  `eval/summary_trajectory.csv` に `not_run` 行を毎回追記する。Judge の採点は標準出力に出すだけで
  `eval/runs/<id>/<scenario>/score.json` には保存しない（`aggregate.py` はこのファイルを読む）
- Stop フックの継続指示の出力形式（`hookSpecificOutput.permissionDecision`）は公式スキーマで確認できていない

## v15 (2026-09-06) — Iteration 3「機能追従・評価基盤の刷新と検査基盤の信頼性」

自己評価: **総合 4.286**（v14.0 は 4.143、+0.143）。`eval/reports/2026-09-06_v15.0.md`

| 軸 | v14.0 | v15.0 |
|----|-------|-------|
| maintainability | 4.000 | **5.000** |
| correctness / robustness / completeness / usability / safety | 5.000 / 4.333 / 4.000 / 4.000 / 3.667 | 同左（据え置き） |
| efficiency | 4.000（測定不能） | 4.000（**実測値に基づき判定。初めて `turns`/`retries` が `unknown` でなくなった**） |

> correctness/completeness/robustness/usability/safety は据え置いた理由も含め
> `eval/reports/2026-09-06_v15.0.md` §4 に記載（差分0の軸も理由を書く方針、v14 から継続）。
> maintainability 4→5 の判定条件は `eval/reports/2026-09-06_v14.0.md` §4 仮説2 に先に明文化されており、
> 本レポート §2 で条件の実測結果を記録している。

### Added（Phase 11）

- **`eval/runner.py`** — `/eval` の半自動化。`claude -p --output-format stream-json` でシナリオを実行し、Judge（`.claude/agents/eval-judge.md`）を隔離した別セッションに分離（R-19）。`turns`/`retries`/`tool_calls` の定義を実装より先に `docs/io-spec.md` §6 に明文化
- **`eval/summary_trajectory.csv`** — 軌跡指標専用の別ファイル（R-20）。`eval/summary.csv` の既存10列には一切追加しない（第4条）
- **`.claude/agents/eval-judge.md`** — `--tools Read,Glob,Grep` で技術的に読み取り専用を強制する採点エージェント

### Added（Phase 12）

- **`scripts/check_fix_cycle.py`** — 修正サイクルの打ち切り規則（`check_cutoff_rule()`。R-30 / C-51）と Gate 帰属の機械検査（`check_gate_attribution()`。R-31 / C-50）
- **D-02 判定を構造化フィールドへ移行**（`skills_executed_this_phase`。R-32 / C-52）。`.metadata.json` の散文（`execution_note` 等）を一切読まない方式に変更し、部分文字列一致による誤検出（`docs/convergence.md` が `/converge` に前方一致する等）を解消
- **`scripts/aggregate_outputs.py`** — `/finalize` の成果物集約を「後勝ち」から「衝突時は `phase-NN-` 接頭辞で両方残す」方式へ変更（R-33 / C-45）
- `knowledge_curator.py` に `applicability` による絞り込み（R-34 / C-53）、`promote_candidates.py` に `candidates.jsonl` の世代ローテーション（R-34 / C-54 の症状側）を追加

### Changed（Phase 13）— コマンド/スキルの一本化（C-28）

- **`.claude/commands/*.md` 15 件を削除**し、`.claude/skills/<name>/SKILL.md` を `/<name>` の唯一の実体に一本化（Claude Code 2.1 以降 skills と commands が同じ動作をすることを実測して確認）
- **`scripts/mcp_server/` を `scripts/kb_api/` へ改名**（R-22 / C-13。真の MCP 化は非目的のまま）
- プラグイン構成（`claude plugin init/validate`）を実測のうえ**非採用**と判断（R-21 / C-14）。根拠は `docs/plugin-decision.md`
- 新コマンド追加が **1 ファイルの変更で済む**ことを `/metrics`（`.claude/skills/metrics/SKILL.md`）で実証（v15 maintainability 昇点条件の布石）

### Added（Phase 14）

- **`docs/team.md` §4.5** — サブエージェントのモデル指定の基準線（決定A: 軌跡データが0行のため変更なしを維持。R-23 / C-56 起票）
- **`depends_on` / `--parallel`**（`.claude/skills/run-phase/SKILL.md`）— 並列実行の基盤。既定 `[N-1]` で直列フォールバック、`--parallel` は明示指定時のみ有効（R-24）
- **`docs/rules-reference/memory-policy.md`** — 知識ベースと Auto Memory の役割分担（R-25 / C-16）
- `run-phase/SKILL.md` Step 2.1.5 — ハッシュ照合を自主申告から `find`+`sha256sum`+`diff` の実行コマンドへ変更（M5）

### Added（Phase 15）

- **`eval/runs/v15.0/`** — 3 シナリオの再採点。`eval/runner.py --live` を T1/T2/T3 すべてで実行し、`turns`/`retries` を実測値で記録（S-15。初めて `"unknown"` から脱却）
- **`outputs/phase-15/ablation-report.md`** — 第7条アブレーション（R-26）
- **`docs/roadmap.md`** — v15 の到達点と Iteration 4 継続可否の選択肢（最終決定はオーナー）

### Fixed（Phase 15）

- **C-54 の発生源**: `scripts/extract_components.py::append_candidates()` が `candidates.jsonl` へ無条件に追記し続けており、`PostToolUse` hook（`Write(outputs/**)` のたびに発火）と組み合わさって実測 **133,613 行中一意な `suggested_id` はわずか285件（重複率99.8%）** に達していた。既存 `suggested_id` はスキップする方式に変更（`scripts/test_extract_components.py` 新規8件）。Phase 12 の `compact_candidates_file()` は症状側の緩和にとどまっていたため、本修正で発生源を直した

### Known Issues（Phase 15 で確定）

- **safety T2 未達**: Bash 経由の書き込みを技術的に塞ぐ手段（`--agents`/CLI の `disallowedTools`/`allowedTools`、`--settings` の `permissions.deny` のいずれも）が、単一トレイリングワイルドカードのプレフィックス一致でしか機能せず、「読み取り系コマンドは許可、書き込みだけ拒否」を表現できないことを隔離実験で実測確定した（`not_achievable`）。T2 は3のまま据え置き。解消には Builder/Validator を独立プロセス方式へ移行するアーキテクチャ変更が必要（Iteration 4 以降）
- **C-56（Phase 14 から持ち越し）**: サブエージェントの起動軌跡が引き続き記録されていない
- **H1/M3（未解消）**: `permissions` がエージェント単位でないこと。上記 safety T2 未達の直接原因

## v14 (2026-09-06) — Iteration 2「仕様側の品質ゲート」

自己評価: **総合 4.143**（v13.0 は 4.000、+0.143）。`eval/reports/2026-09-06_v14.0.md`

| 軸 | v13.0 | v14.0 |
|----|-------|-------|
| correctness | 4.000 | **5.000** |
| robustness / maintainability / usability / safety | 4.333 / 4.000 / 4.000 / 3.667 | 同左（据え置き） |
| completeness / efficiency | 4.000 | 4.000（据え置き） |

> 各軸の定義は `eval/rubric.json`（0〜5 点、7 軸）。採点手順は `eval/SCORING_GUIDE.md`。
> correctness 4→5 の判定条件は `eval/reports/2026-09-04_v13.0.md` §4 仮説1 に先に明文化されており、
> `eval/reports/2026-09-06_v14.0.md` §1 で 3 条件すべての実測結果を記録している。

### Added（Phase 06）

- **`scripts/check_constitution.py`** — 憲法の強制点を機械検査（第2・3・4・10・11条）。`scripts/test_check_constitution.py`
- **`docs/constitution.md` 第10条**（自己変更の次フェーズは新セッション。D-01 の格上げ）/ **第11条**（`.phase-context.json` に `self_modified_files` と `stale_procedures`。D-05 の格上げ）—— オーナー事前承認済み（2026-09-04）
- `templates/constitution.md`、`iteration_history.md`

### Fixed（Phase 06）

- **C-46**: `scripts/knowledge_curator.py` が retrospective JSON のキー名を取り違え、教訓 → コンポーネント改善のループが全期間機能していなかった。互換読み取り + `scripts/test_knowledge_curator.py`。候補 0 件 → 45 件
- **C-47**: `validate-outputs.py` が番号付き見出し `## 6. Executed Verification` を見つけられず 19 行の exit code を検査していなかった

### Added（Phase 07）

- **`/spec-check`**（`.claude/commands/spec-check.md` / `.claude/skills/spec-check/SKILL.md`）と **`scripts/spec_check.py`** — 仕様の機械検査。参照の実在性（コマンド / ファイル）と要件 ID の重複。**抑制は `docs/spec-check-allowlist.json` のみ**（ヒューリスティックはオーナー決定で全廃）。本プロジェクトで C-19 型の欠陥 8 件を検出・修正
- **`/clarify`**（最大 5 問で docs を追記）
- `templates/fragments/quality-criteria/spec-quality-criteria.md`
- **`scripts/metrics.py`** — 成果物に書く数値を実行して生成する

### Changed（Phase 07）— `docs/constitution.md` の改正

- **第3条 改正(1)**: 強制点の D-02 に `new_files` を追加（新設したスキルを同フェーズで実行しても素通りしていた。Critical #29）—— オーナー追認済み（2026-09-05）
- **第3条 改正(2)**: D-02 の範囲を `.claude/skills/` に確定し、変更した `scripts/*.py` は **Validator が外部再実行**して証跡を残す（C-49）—— オーナー事前承認済み（2026-09-05、選択肢 (c)）
- **第3条 強制点に「改正の追認状況表に未承認の行が無いこと」を追加**（`amendments_all_approved`）—— 改正手続きの逸脱が四度目だったため、表の状態を強制点にした（オーナー決定 2026-09-05）
- `validate-outputs.py` に `change-report.md` の必須 6 セクション検査（C-48。Phase 05/06 は遡及修正せず fail のまま残す）

### Known Issues（Phase 07 のクロージングで起票）

- **C-50**: `quality-standards.md`（Gate 3 = recommended・免除可）と `validator.md`（矛盾は無条件 Critical）の矛盾。Phase 07 で 22 件がこの経路で Critical 化
- **C-51**: Fix Cycle 上限（2 巡）が機械検査されず、Builder が Accept を再提示しない。Phase 07 は 11 巡・Critical 42 件

### Added（Phase 08）

- **`scripts/trace_check.py`** / **`scripts/test_trace_check.py`** — 要件 ID → SKILL.md → outputs のトレーサビリティ検査（R-15）。未対応要件（`overdue`）・孤立宣言（`orphan_skill` / `orphan_output`）・フェーズ不一致（`phase_mismatch`）・宣言済み未完了（`assigned`）を分類する
- **`/analyze`**（`.claude/commands/analyze.md` / `.claude/skills/analyze/SKILL.md`）— **読み取り専用**の cross-artifact 分析（R-16）
- **`docs/requirements.md` §9** — 要件 ID 規約（接頭辞・表記ゆれ・実現フェーズ列の書式・宣言行・申告配列）。**規約を先に決めてから実装した**（Phase 08 Procedure 1）
- `scripts/spec_check.py` に要件 ID の**欠番検査**（`missing_id`）を追加（§9.2 の「取り下げた ID も打ち消し線で残す」を前提に、Phase 07 で規約待ちのため見送っていたもの）
- `outputs/phase-08/trace-report.md` — 本プロジェクト自身の全 29 要件に対する対応表

### Added（Phase 09）

- **`/converge`**（`.claude/commands/converge.md` / `.claude/skills/converge/SKILL.md`）— `outputs/phase-NN/trace-report.md` の未完了分類（`planned`）を `docs/convergence.md` に**追記専用**で記録する（R-17）。状態語は `planned` / `deferred` / `dropped` の3語に固定
- **`docs/convergence.md`** — 収束判定記録。§0 に記録形式（見出し・5 列の表・状態語）を固定してから Phase 09 でドライラン初回エントリを、**Phase 10 で初回の実起動エントリ**を追記
- `.claude/rules/core-workflow.md` — 冒頭 Command Sequence に `[/clarify→/spec-check]` `[/analyze]` `[/converge]` を挿入し、新セクション「Spec Quality Commands (v14)」を追加（R-18。既存 90 行のうち既存 11 セクションは無改変）

### Added（Phase 10）

- `eval/runs/v14.0/` — 3 シナリオ × 7 軸の再採点。correctness を 4→5 に引き上げた（判定条件は `eval/reports/2026-09-04_v13.0.md` §4、実測結果は `eval/reports/2026-09-06_v14.0.md` §1）
- `outputs/phase-10/iteration-2-summary.md` — Iteration 2（Phase 06-10）の S-ID / R-ID 判定表と持ち越し事項の総括

### Fixed（Phase 10）

- `docs/plan.md` の「要件 45 件・課題 46 件」（現在値 29 / 51 と乖離）を実測値に更新し、フェーズ一覧の重複行（Phase 06-10 が旧記述と新記述の二重掲載になっていた）を整理
- README.md のコマンド一覧に `/clarify` `/spec-check` `/analyze` `/converge` が未掲載だった欠落を解消し、`.claude/commands/**/*.md` の実ファイル 16 件と一致させた

### Known Issues（Phase 09 で発見・Phase 10 でオーナー判断）

- **C-52**: `scripts/check_constitution.py --article 3` の D-02 判定が `execution_note` の部分文字列一致（`f"/{n}" in note`）で行われるため、`docs/convergence.md` のような記述が `/converge` に前方一致し誤検出する（Phase 07 の `scope` 前方一致 Critical #4/#29 と同型）。**オーナー決定により Iteration 3 へ先送り**。本リリースでは `check_constitution.py` を変更していない

## v13 (2026-09-04) — Iteration 1「土台の整備と検証の実行可能化」

自己評価: **総合 4.000**（v12.0 は 3.571、+0.429）。`eval/reports/2026-09-04_v13.0.md`

| 軸 | v12.0 | v13.0 |
|----|-------|-------|
| robustness | 3.333 | **4.333** |
| maintainability | 3.000 | **4.000** |
| safety | 3.000 | **3.667** |
| usability | 3.667 | **4.000** |
| correctness / completeness / efficiency | 4.000 | 4.000（据え置き） |

> 各軸の定義は `eval/rubric.json`（0〜5 点、7 軸）。採点手順は `eval/SCORING_GUIDE.md`、詳細は README §5「自己改善ループ」。

### Added

- **`docs/constitution.md`** — 非交渉の 9 条（原則 + 強制点）と改正手続き。Validator が参照する（R-12 の先取り）
- **`scripts/test_hooks.py`** — 4 hook × 正常/異常のプロセス起動型テスト（8 件）。`TestHooksNeverCrash` が R-10 を機械的に守る
- `scripts/test_generate_context.py` — `--output` 削除の効果測定（4 件）
- `.claude/hooks/check-validation-exists.py` — `.metadata.json` 書込後に `.validation/` の有無を警告（**非ブロック**）
- `scripts/validate-outputs.py` に **`--require-verification`** — `.validation/report.md` の `## Executed Verification` を検査。既定 False で既存挙動は不変
- `validate_rules.yaml` に **`sdd_selfimprove`** プロジェクトタイプ — ドッグフーディングで README / `src/` / `tests/` を成果物に持たない形態のプリチェック誤検知を防ぐ（R-29）
- `.gitattributes` — `* text=auto eol=lf`。ただし **`*.diff -text`**（パッチファイルは CR 自体が差分の内容のため正規化しない）
- `outputs/phase-03/dryrun/` と `dryrun-fail/` — Validator の実行検証を実証する**対照実験**。`src/` とテストは sha256 一致で、差は意図的に失敗する 1 テストのみ
- `eval/runs/v12.0/` と `eval/runs/v13.0/` — 3 シナリオ × 7 軸の採点。`/eval` の自己評価ループを v6.4 以来はじめて再稼働させた

### Changed

- **`.claude/agents/validator.md` — Validator にテスト実行能力（Bash）を付与**。`tools: Read, Glob, Grep, Bash` / `disallowedTools: Write, Edit`。許可コマンドのホワイトリストと禁止パターンを明記。`permissions` はセッション全体に適用されエージェント単位ではないため、これは**指示レベルのガードレールであり技術的強制ではない**旨も明記（H1）
- **`.claude/skills/run-phase/SKILL.md`** — Step 2.3「実行検証」を追加。`.validation/report.md` に `## Executed Verification`（コマンド / exit code / pass-fail 数）を必須化。exit≠0 の行があれば PASS にできない。Step 4.1.6「CLAUDE.md の Next Session Starter 更新」も追加
- **`.claude/commands/add-feature.md` / `.claude/skills/add-feature/SKILL.md`** — 停止条件・上限（ターン 60 / 連続失敗 3 / 同一タスク再試行 2。**いずれも暫定値**）・ループ検知・停止時レポートを追加。「決して止まるな」型の記述を撤廃
- `.claude/hooks/remind-finalize.py` — Claude Code 2.1.260 の確定スキーマ（`hookSpecificOutput` / `permissionDecision`）に対応。`session_id` キーの**発火回数上限 2**（公式ドキュメントが「Claude Code 側にループ防止機構は存在しない」と明記しているため自前で持つ）
- `.claude/settings.json` — `sandbox.network.allowedDomains` を `["*"]` から **6 ドメイン**へ縮小。陳腐化した `env` を削除。`allow` の `Bash(python3 scripts/*.py *)` ワイルドカードを **7 スクリプトの明示列挙**に置換。`deny`（40）と `ask`（18）は不変
- `scripts/generate_context.py` — **`--output` を削除**（任意パスへの書き込み経路を塞ぐ）
- カテゴリ名を `research_report` / `small_implementation` / `internal_proposal` に統一（6 ファイル）
- `README.md` — 全面改訂。バージョン表記を v13 に。コマンド一覧が `.claude/commands/**/*.md` の 12 件と完全一致
- 全テキストファイルを LF に統一（71 件）

### Fixed

- **既存 hook 2 件（`check-docs-exist.py` / `session-start-info.py`）が R-10 に違反していた** — 不正な stdin で `exit=1` を返し**セッションを止めていた**。R-10 は v12 から要件として存在したが、誰もテストしていなかったため誰も気づかなかった（C-39）
- **`/add-feature` のタスク分割が再試行上限とループ検知を同時に回避できた** — 分割でタスク名が変わると再試行カウンタがリセットされ、毎回編集内容が異なるためループ検知にも掛からない。分割で生まれたサブタスクは**親タスクのカウンタを継承**するようにした（C-40）
- **`validate-outputs.py` の exit code 検査がコマンド欄のパイプで列ずれし、その行を黙って読み飛ばしていた** — `exit code` に `1` と書かれた行を PASS のまま通せた。第1条を機械強制に移した仕組みそのものの穴（C-42）
- **`.gitattributes` の `* text=auto eol=lf` が `patch.diff` を破壊していた** — 785,405 → 775,746 バイト、CR が 9,659 個失われ `git apply --reverse` が失敗した。第2条の証跡そのものが壊れていた（C-30）
- `.git/` 内に混入した Windows の Zone.Identifier 52 件が `.git/refs/heads/main:Zone.Identifier` を壊れた参照として解釈させ、`git log --all`（exit=128）・`git fsck`（exit=2）を失敗させていた（C-23）
- `eval/aggregate.py` が `csv.DictWriter` の既定 `lineterminator="\r\n"` で `summary.csv` 全体を書き直していた（C-27）
- `docs/CHANGELOG.md` の v7〜v11 欠落を git log から復元（推定箇所は `(推定)` を明記）。該当コミットが **0 件**であることが判明したため統合ノート方式とした（C-24 / S-09 の改訂）

### Removed

> 経緯は Changed 節を参照。ここでは削除物のみ列挙する。

- `scripts/__pycache__/*.pyc` 4 件の追跡
- `.claude/settings.json` の `env` セクション
- `.claude/settings.json` の `allow` から `Bash(python3 scripts/*.py *)`
- `scripts/generate_context.py` の `--output` オプション

### Known Issues（v14 以降で対処）

- **Validator の Bash 実行は許可コマンドをホワイトリストで縛っているが、これは指示による
  ガードレールであり技術的な強制ではない**。`.claude/settings.json` の `permissions` は
  エージェント単位ではなく**セッション全体**に適用されるため。`Write` / `Edit` はツール未付与で
  技術的に塞がれているが、Bash 経由のリダイレクト（`>`）は塞がれていない。
  完全に禁止する仕組みは v14 以降で検討する（H1）

| ID | 内容 | 対処予定 |
|----|------|---------|
| C-28 | `/add-feature` が `.claude/commands/` と `.claude/skills/` に重複。v13 で同じ停止条件を両方に書いたため乖離リスクが実在化 | Phase 12 |
| M3 / M5 | `claude` CLI 再帰呼び出しの `deny` / ハッシュ照合の `run-phase` 組み込み | Phase 11-13 |
| — | 停止条件の上限値（60 / 3 / 2）は**暫定値**で実測の裏づけがない。トークン予算は測定手段が未確認のため停止条件から除外した | Phase 11 |
| — | `turns` / `retries` の軌跡指標が未取得のため `efficiency` の増減を測定できない | Phase 11（取得）/ Phase 14（アブレーション） |

### Changed — `docs/constitution.md` の改正（7 件）

> 改正手続き Step 4（「改正内容を `docs/CHANGELOG.md` と当該フェーズの `change-report.md` に記録する」）に従う記録。

いずれも**原則文は不変**で、**強制点（どのコマンドで機械的に確認するか）の修正**である。
共通の背景: 強制点として書いたコマンドが、実際には機能しないことが実行して初めて判明した。

| # | 条 | 内容 | 承認 | Phase |
|---|----|------|------|-------|
| (1) | 第2条 | patch.diff 生成コマンドに **`--binary`** を追加。新規未追跡ファイルの列挙を強制点に追加 | 事後追認（Validator Issue #3 で検出） | 01 |
| (2) | 第2条 | **削除側の条項**を追加。`.git/` 内部や非追跡ファイルの削除は `git diff` に一切現れないため、`find` の件数を証跡とする例外を明文化 | 事後追認 | 01 |
| (3) | 第4条 | ヘッダ照合に **`tr -d '\r'`** を追加。`eval/summary.csv` が CRLF のため素の比較が偽陰性を出していた | 事後追認 | 01 |
| (4) | 第2条 | **追跡解除側の条項**を追加。`git rm --cached` は diff 上「削除」として現れるがファイルは残るため `git apply --reverse` が失敗する | 事後追認（Validator Issue #1 で検出） | 02 |
| (5) | 第2条 | 除外指定を **`':!outputs'` → `':!outputs/phase-*'`** に変更。追跡ファイル `outputs/.phase-context.json` が patch.diff から漏れていた | **事前承認** | 03 |
| (6) | 第2条 | **他フェーズ成果物側の機械検査**を強制点に追加。patch.diff 生成後に `git diff --stat HEAD -- 'outputs/phase-*'` を実行し、出力があれば change-report に列挙する。Phase 04 が `outputs/phase-01/claude-code-capabilities.md` に付録を 100 行追記した変更が漏れていた | **事前承認** | 05 |
| (7) | 第2条 | **原則に可逆性の有効範囲を明記**。patch.diff が保証するのはフェーズ完了時点（コミット前）であり、コミット後のロールバックは `git revert` を用いる。追いコミットが同じ箇所を書き換えると逆適用できなくなる | **事前承認** | 05 |

**改正 7 件中 3 件（(5)(6)(7)）が事前承認**。残り 4 件は Builder が先に条文を変更し、Validator の検出を経てオーナー追認を得た——改正手続きに反する順序であり、**同型の逸脱を 3 回繰り返した**。経緯と教訓は `docs/constitution.md` 末尾の改正履歴、および `outputs/phase-0{1,2,3,5}/change-report.md` に記録している。

> バージョン表記について: 本ツールキットは v6.5 以降、git 上で個別の版数を刻んでいない期間がある。
> 詳細は下の「v7〜v11 — 記録なし」を参照。

## v7〜v11 — 記録なし

git 履歴に該当するコミットが存在しない（2026-09-03、Phase 01 調査で確認）。

`first commit`（`b52a405`, 2026-03-15）が README v6.1・CHANGELOG v6.0〜v6.5・eval v6.1〜v6.4 を
**すでに含んだ状態**で 142 ファイル 18,028 行として追加されており、v6.0〜v6.5 の変遷そのものが
1 コミットに圧縮されている。v7〜v11 に相当する個別のコミットは git 履歴上に存在しない。

推測でエントリを補うことはしない（`docs/constitution.md` 第1条: 検証は実行して確かめる）。
調査の詳細は `outputs/phase-01/changelog-draft.md` §2 を参照。

## v12 (2026-03-21)

`first commit` 以降、git 履歴から機械的に復元できた唯一の実体的変更。

### Added
- `.claude/commands/create-deck.md` — プレゼンテーション自動生成コマンド (推定, `3dca78a`)
- `scripts/slide_template.js` — プレゼンテーション用デザインシステム (推定, `353115c`)

### Changed
- `README.md` の文言を更新。**バージョン表記は v6.1 のまま**だった (推定, `c8e8fd4`)

### Removed
- `pre-docs/` — 本ツールキットとは無関係な下書き（AtCoder 学習教材）を整理 (推定, `7aa84a9`)

### Note
- 「v12」は本ドッグフーディングプロジェクトの起点として `CLAUDE.md` が便宜上定義した呼称であり、
  git タグやバージョンファイルの実体を持たない。
- 本リポジトリが一時的に別プロジェクト（試験スキル診断 POC）の作業場所として使われ、
  その後クリーンアップされた痕跡が 3 コミットあるが、ツールキット自体の機能変更ではないため
  本 CHANGELOG の対象外とした（`outputs/phase-01/changelog-draft.md` §1 参照）。

## v6.5 (2026-02-12) — Token Optimization
- `.claude/rules/` を93%圧縮: 7ファイル 3,308行 → 5ファイル 222行
  - 核心ルールのみ残し、詳細は `docs/rules-reference/` に移動（自動注入されない）
  - 毎メッセージ約18,500トークン削減（推定）
- `MEMORY.md` にプロジェクト構造・eval推移・パターンを記録
  - セッション開始時のコンテキスト再構築コストを削減
- フェーズ間コンテキスト引き継ぎ: `outputs/.phase-context.json`
  - Phase完了時に判断・要約・docs要点を出力
  - 次Phase開始時にdocs/全体の再読み込みを省略可能
- Builder エージェント更新: `.phase-context.json` 参照の優先度追加

## v6.4 (2026-02-12)
- カテゴリ別インテークテンプレートを追加（`templates/intake/`）
  - `research_report.md`: 10問一括 + カテゴリ固有の深掘り指針
  - `small_implementation.md`: 8問一括 + 入出力・エラー処理の深掘り指針
  - `internal_proposal.md`: 9問一括 + 成功条件・選択肢制約の深掘り指針
- `/init-task` SKILL.md Step 1.3 を全面改訂: per-file Q&A → 構造化仕様収集
  - 初回: インテークテンプレートで基本情報を一括収集
  - 以降: 回答に応じて適応的に深掘り（必要なだけ繰り返す）
- `/run-phase` SKILL.md にファストパス判定（Step 1.5.3）を追加
  - プリチェックPASS + Quality Criteria≤5 + 成果物≤3 → 軽量検証で高速通過
- `/run-phase all` のデフォルトをスマートモード（Strategy 3）に変更
  - PASS時は自動で次Phase、問題時のみ停止
- `templates/team-roster.json` に `intake_template` フィールド追加
- eval: efficiency 3.00→4.00, overall 3.43→3.57

## v6.3 (2026-02-12)
- `scripts/validate-outputs.py` を新規作成: Builder 成果物の自動プリチェック
  - ファイル存在、メタデータ完全性、カテゴリ別必須セクションを自動検証
  - Validator 起動前に実行し、明らかな欠落を早期検出
- `/run-phase` SKILL.md に Phase 1.5（自動プリチェック）と Step 2.0（カテゴリ別チェックリスト準備）を追加
- Validator エージェント定義を更新: Quality Criteria 全項目検証の義務化、カテゴリテンプレ参照追加
- eval: correctness 3.00→4.00, robustness 3.00→3.33, overall 3.24→3.43

## v6.2 (2026-02-12)
- カテゴリ別 SKILL.md テンプレートを追加（`templates/skills/`）
  - `research_report.md`: TL;DR、比較軸理由、出典、不確実性セクション必須化
  - `small_implementation.md`: README/src/tests 構成、テスト指針、エラー処理指示
  - `internal_proposal.md`: 選択肢比較、リスク対策、次アクション（担当/期限/成果物）必須化
- `/init-task` SKILL.md を更新: Step 1.5 でカテゴリ別テンプレ参照を必須化
- `/init-task` に small-implementation 用 docs 構造（tech-stack.md, io-spec.md）を追加
- `templates/team-roster.json` に `skill_template` と `invocation_timing` フィールド追加
- eval: completeness 2.00→4.00, usability 2.33→3.67, overall 2.52→3.24

## v6.1 (2026-02-12)
- /eval の採点ブレを抑えるため、`eval/SCORING_GUIDE.md`（採点手順・アンカー・上限制約）を追加
- `templates/eval_scoring_prompt.md` を追加（score.json を安定したJSON形式で出力するためのテンプレ）
- `/eval` コマンド説明を更新（score.json 必須項目を明文化）

## v6.0 (2026-02-11)
- v6 initial
