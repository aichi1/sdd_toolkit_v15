# 将来カテゴリ候補（現在は未サポート）

> 2026-09-03（Phase 02 / R-02 / C-02）に `.claude/skills/init-task/SKILL.md` から削除したカテゴリの記録。
> **本ファイルは S-07 の grep 対象（`.claude` / `templates` / `docs/rules-reference`）の外に置いている。**
> 理由: S-07 は「旧カテゴリ名がアクティブな指示から排除されていること」を測る基準であり、
> 意図的に保存した削除記録まで 0 件を要求すると、記録を残すこと自体が不可能になるため。

`templates/team-roster.json` が定義する正式カテゴリは次の 3 つのみである。

| カテゴリ | 用途 |
|---------|------|
| `research_report` | 調査・比較・ファクト整理・社内向けレポート |
| `small_implementation` | 小規模な実装（CLI/スクリプト/API など） |
| `internal_proposal` | 社内提案（稟議、導入、ロードマップ、選定） |

以下は v12 以前の `/init-task` に記載があったが、`team-roster.json` に対応する specialists・
intake テンプレート・SKILL テンプレートが存在しないため **2026-09-03（Phase 02 / R-02 / C-02）で削除した**。
将来サポートする場合の docs 構成案として、ここに記録を残す。

### network-design（ネットワーク設計）

```text
docs/
├── requirements.md    # ネットワーク要件
├── topology.md        # トポロジの希望
├── constraints.md     # 予算・納期・既存インフラ
├── security.md        # セキュリティ要件
└── scalability.md     # 成長（拡張）見込み
```

サポートするには次が必要:
1. `templates/team-roster.json` の `task_types` にエントリを追加（specialists と invocation_timing）
2. `templates/intake/network_design.md`（ワンショット仕様収集テンプレート）
3. `templates/skills/network_design.md`（必須セクション構成 + Quality Criteria）
4. `scripts/validate-outputs.py` の `required_sections` にキーワード定義を追加
5. `~/.sdd-knowledge/starters/network-design/` は既に存在する（過去プロジェクト由来）

> 参考: `~/.sdd-knowledge/retrospectives/2026-02-20_network-design_home-network-refresh.json` に
> 実プロジェクトの振り返りが残っている。復活させる場合の一次資料になる。
