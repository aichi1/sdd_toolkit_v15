# Memory Policy — 知識ベースと Auto Memory の役割分担

出典: SDD Toolkit 開発プロジェクト（v12→v15）の要件 R-25（C-16）。同プロジェクトの Phase 14 で新規作成。
以下の「本プロジェクト」「本フェーズ時点の実測」は、その開発プロジェクトを指す。

> **前提（C-16 の確認済み事項）**: `.claude/agents/knowledge-curator.md:6` は既に `memory: user` を
> 宣言している。本ドキュメントは「新規導入」ではなく、**既に有効な仕組みの実態を実測し、
> `~/.sdd-knowledge/`（知識ベース）との役割分担を文書化する**もの。

## 1. 二つの仕組み

本プロジェクトは、セッションを跨いで情報を持ち越す仕組みを **2 つ** 使っている。混同すると
重複や陳腐化が起きるため、まず実体を区別する。

### 1.1 `~/.sdd-knowledge/`（知識ベース。KB）

- **実体**: `registry.json`（コンポーネント台帳）、`candidates.jsonl`（改善候補の追記ログ）、
  `retrospectives/*.json`（`/retrospective` の構造化出力）、`starters/`、`docs-archive/`、
  `components/`、`{agents,hooks,rules,skills}-library/` など。git 管理外だが、
  ファイル形式は JSON / Markdown で構造が固定されている
- **書き込み経路は明示的なスクリプトに限定される**: `scripts/knowledge_curator.py`
  （retrospective → 改善候補を `candidates.jsonl` に追記）、`scripts/promote_candidates.py`
  （**ユーザー承認を経て** `registry.json` に反映。knowledge-curator は registry.json を
  直接変更しない）、`scripts/generate_context.py` / `search_knowledge.py`（読み取り専用）
- **読み込み経路**: `/init-task` 時の再利用案の提示、`researcher` エージェントによる検索
- **スコープ**: **プロジェクト横断**。他のどの SDD プロジェクトからも再利用されることを前提にした
  構造化データ

### 1.2 Auto Memory（`memory: <scope>` フィールド。Claude Code 組み込み機能）

- **実体（実測）**: `~/.claude/projects/<プロジェクトディレクトリのスラッグ>/memory/MEMORY.md`
  （目次。各ノートへのリンク一覧）+ 個別ノートファイル（例:
  `~/.claude/projects/<スラッグ>/memory/fix-cycle-stopping-rule.md`）。
  各ノートは frontmatter（`name` / `description` / `metadata.node_type: memory` /
  `metadata.type: feedback` / `metadata.originSessionId` / `metadata.modified`）を持ち、
  本文末尾に `[[関連ノート名]]` の wiki リンクを持つことがある
- **現状 2 件**（本フェーズ時点の実測）: `subagent-model-sonnet.md`（サブエージェントは
  `model: "sonnet"` で呼ぶ）、`fix-cycle-stopping-rule.md`（修正サイクルの打ち切り規則。
  Phase 07 の 11 巡の反省）。**どちらも `originSessionId` がメインセッションのものであり、
  `.claude/agents/knowledge-curator.md` の手順（`/retrospective` 後に自動起動し「自身の
  MEMORY.md に処理履歴を記録」）を経由して書かれたものではない**
- **発見（Phase 14）**: Auto Memory は `memory:` を宣言した特定のサブエージェント専用のノートでは
  なく、**プロジェクトディレクトリ単位で共有される**ストアである。`knowledge-curator.md` が
  `memory: user` を宣言していても、実際にそのファイルへ書き込むのはメインセッションを含む
  任意のエージェントでありうる。この点は `knowledge-curator.md` の記述（「自身の MEMORY.md に
  処理履歴を記録」）とは厳密には一致しない可能性がある——**本フェーズでは `knowledge-curator.md`
  を変更しない**（D-03「1 フェーズ 1 テーマ」。範囲外。§4「未解決の判断事項」に記録した）
- **スコープ**: **プロジェクト単位**。次にこのディレクトリでセッションを開くと自動的に読み込まれる
  （本ファイルの冒頭にも「user's auto-memory, persists across conversations」として提示される）

## 2. 役割分担（規約）

| 観点 | `~/.sdd-knowledge/`（KB） | Auto Memory |
|------|--------------------------|--------------|
| スコープ | プロジェクト横断（再利用資産） | このプロジェクトのディレクトリのみ |
| 書き込み経路 | 明示的スクリプト + ユーザー承認（`promote_candidates.py`） | 任意のセッションが暗黙に追記可能 |
| レビュー | `/init-task` 時に人が選別して取り込む | **レビューされない**（Validator の検証対象外） |
| 内容の粒度 | 構造化データ（JSON）、正式な改善候補 | 短い運用リマインダー（1 ノート数行〜十数行） |
| 想定寿命 | 長期・恒久（starter・registry として蓄積） | 中期（そのプロジェクトが動いている間の橋渡し） |

### 2.1 Auto Memory に書いてよいもの

- **「知らないと同じ失敗を繰り返す」短い運用リマインダー**（例: 現状の2件のように、モデル指定忘れ・
  修正サイクルの打ち切り判断忘れ）
- 次のセッションが `CLAUDE.md` を読む前に思い出すべき、即効性のある注意点

### 2.2 Auto Memory に書いてはいけないもの

- **正式な仕様・決定事項の本体** → `docs/` に書く。Auto Memory は非レビュー・非バージョン管理であり、
  正典（source of truth）になれない
- **retrospective の詳細内容そのもの** → `~/.sdd-knowledge/retrospectives/*.json` に構造化して残す。
  Auto Memory に長文で複製すると、KB 側が更新されても Auto Memory 側が陳腐化したまま残る
- **`.phase-context.json` や `change-report.md` に書くべき、フェーズ固有の判断根拠** →
  Auto Memory はプロジェクト全体のスコープであり、特定フェーズの証跡置き場ではない
- **同じ教訓を KB と Auto Memory の両方に重複して書く** —— 「今すぐこのセッションで使う短い
  リマインダー」は Auto Memory、「将来の別プロジェクトでも再利用される構造化資産」は KB、
  という軸で一度だけ書く

## 3. 安全性への含意

Auto Memory は `/retrospective` のようなユーザー承認ステップを経ずに、セッション中に**暗黙に**
書き込まれうる（実測した 2 件はオーナーの直接指示に基づくものだが、仕組みとしては
任意のセッションが暗黙に追記できる）。**Validator はこの内容を検証対象にしない**——
レビューされない情報がセッションを跨いで持ち越される経路であるため、`docs/` の代替として
扱ってはならない。運用上のリマインダーに留め、`docs/` が定める要件・制約と矛盾する内容を
Auto Memory 側にだけ置かない。

## 4. 未解決の判断事項（Phase 14 で発見・先送り）

- `.claude/agents/knowledge-curator.md` の「自身の MEMORY.md に処理履歴を記録」という記述と、
  実測した Auto Memory の共有ストアとしての実態にずれがある可能性がある。**本フェーズでは
  `knowledge-curator.md` を変更しない**（範囲外。D-03）。次に `knowledge-curator` が実際に
  起動されるとき、または次の `/init-task` / `/re-init-task` 時に見直すことを推奨する
