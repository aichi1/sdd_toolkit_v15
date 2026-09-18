#!/usr/bin/env python3
"""
test_spec_check.py: spec_check.py の回帰テスト（R-14 / Phase 07）

**許可リスト方式**（オーナー決定 2026-09-05）の契約を守る。

経緯:
  当初はヒューリスティック（同じ行の否定語 / 公式ドメインの URL / 文書レベルの宣言 /
  リスト構造）で誤検出を抑えようとした。**Validator との 3 巡で Critical 10 件**が出た。
  修正のたびに新しい回避経路が生まれ、そのつど Validator が
  **プロジェクト外に自作の入力を置いて実測**して示した。

  自然言語の「指示か記録か」を正規表現で判定しようとしたことが原因である。
  オーナー決定によりヒューリスティックを全廃し、次の方式にした:

    実在する / 組み込み / 許可リストに明示 → 報告しない
    それ以外はすべて報告する

  **抑制はすべて `docs/spec-check-allowlist.json` に現れる。**
  「冒頭に一言書けば通る」「URL を置けば通る」といった回避経路の概念そのものが消える。
"""
import unittest
import tempfile
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "spec_check", str(Path(__file__).parent / "spec_check.py")
)
sc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sc)

ALLOW_HEADER = "| 参照 | 対象ファイル | 理由 |\n|------|------------|------|\n"


def _project(tmp, text, commands=None, allowlist_rows="", extra_files=None):
    d = Path(tmp)
    (d / "docs").mkdir(parents=True, exist_ok=True)
    (d / "docs" / "x.md").write_text(text, encoding="utf-8")
    (d / ".claude" / "commands").mkdir(parents=True, exist_ok=True)
    # commands=None は既定の ["run-phase"]。commands=[] は「コマンドを1つも作らない」
    # （Phase 13: skills 単独解決のテストに必要）。
    for c in (["run-phase"] if commands is None else commands):
        f = d / ".claude" / "commands" / f"{c}.md"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("# cmd", encoding="utf-8")
    if allowlist_rows:
        # 許可リストは **JSON**。Markdown は人間向けの説明でパーサは読まない
        import json as _json
        entries = []
        for row in allowlist_rows.strip().splitlines():
            cells = [c.strip().strip("`").strip() for c in row.strip().strip("|").split("|")]
            if len(cells) >= 3:
                entries.append({"ref": cells[0].lstrip("/"), "scope": cells[1], "reason": cells[2]})
        (d / "docs" / "spec-check-allowlist.json").write_text(
            _json.dumps({"entries": entries}, ensure_ascii=False), encoding="utf-8")
    for rel in (extra_files or []):
        f = d / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x", encoding="utf-8")
    return str(d)


def _cmd_ids(tmp, text, **kw):
    return {f["reference"] for f in sc.check_command_references(
        _project(tmp, text, **kw), scan_dirs=["docs"])}


def _file_ids(tmp, text, **kw):
    return {f["reference"] for f in sc.check_file_references(
        _project(tmp, text, **kw), scan_dirs=["docs"])}


# ============================================================ 検出（負のテスト）
class TestDetectsRealDefects(unittest.TestCase):
    """実在した欠陥（C-19 / C-38）を検出できること。"""

    def test_c19_recap(self):
        """C-19: `/recap` は存在しないのに検証手段として書かれていた。"""
        with tempfile.TemporaryDirectory() as t:
            self.assertIn("recap", _cmd_ids(t, "1. `/recap` でセッションを再開する\n"))

    def test_c38_agents(self):
        """C-38: `/agents` ウィザードは 2.1.260 で削除された。

        実文字列は `git show 287452f:docs/plan.md` の 123 行目。
        """
        with tempfile.TemporaryDirectory() as t:
            self.assertIn("agents", _cmd_ids(
                t, "- `validator.md` の frontmatter が Claude Code で正しく"
                   "読み込まれる（`/agents` で表示される）\n"))

    def test_unknown_command(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertIn("made-up", _cmd_ids(t, "`/made-up` を実行する\n"))

    def test_missing_file_path(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertIn("scripts/nope.py", _file_ids(t, "`scripts/nope.py` を実行する\n"))


# ============================================================ 回避経路が消えたこと
class TestNoHeuristicBypass(unittest.TestCase):
    """**ヒューリスティックを全廃したので、過去の回避経路がすべて無効であること。**

    Validator が 3 巡にわたって実測で示した 6 つの回避経路を、
    そのまま回帰テストにする。**すべて検出されなければならない。**
    """

    def _assert_detected(self, text, ref):
        with tempfile.TemporaryDirectory() as t:
            self.assertIn(ref, _cmd_ids(t, text), f"回避経路が復活している: {text!r}")

    def test_bypass_negation_same_line(self):
        """旧: 同じ行に「存在しない」と書けば通った。"""
        self._assert_detected("`/faketool` は存在しない。1. `/faketool` を実行する\n", "faketool")

    def test_bypass_url_on_line(self):
        """旧 exploit1: 同じ行に公式ドメインの URL を置けば通った。"""
        self._assert_detected(
            "1. `/faketool` を実行する。詳細は https://docs.claude.com/en/x を参照。\n", "faketool")

    def test_bypass_declaration_at_top(self):
        """旧 exploit2: 冒頭で宣言すれば以降どこでも通った。"""
        self._assert_detected(
            "> `/faketool` は存在しない。\n\n## 手順\n\n1. `/faketool` を実行する\n", "faketool")

    def test_bypass_quote_marks(self):
        """旧 #5: 引用符で囲めば通った。"""
        self._assert_detected(
            "1. 「/faketool」を実行してください。参考: anthropic.com\n", "faketool")

    def test_bypass_bullet_with_unlisted_verb(self):
        """旧 #6: 箇条書き + 語彙にない動詞で通った。"""
        self._assert_detected(
            "> `/faketool` は存在しない。\n\n- /faketool で処理する\n", "faketool")

    def test_bypass_negation_plus_instruction_same_line(self):
        """旧 #8: 否定語と指示を同じ行に置けば通った。"""
        self._assert_detected("1. `/faketool` を実行すること（現在は存在しない）\n", "faketool")

    def test_bypass_fullwidth_marker_no_space(self):
        """旧 #9: 全角の箇条書き記号 + 空白なしで参照自体が拾われなかった。"""
        self._assert_detected("・/faketool を実行する\n", "faketool")


    def _assert_not_suppressed_by_plan_doc(self, rel):
        """計画文書に書いても抑制されないこと（#22）。"""
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            (d / "docs").mkdir(parents=True, exist_ok=True)
            (d / ".claude" / "commands").mkdir(parents=True, exist_ok=True)
            (d / ".claude" / "commands" / "run-phase.md").write_text("# cmd", encoding="utf-8")
            (d / "docs" / "x.md").write_text("1. `/faketool` を実行する\n", encoding="utf-8")
            (d / rel).parent.mkdir(parents=True, exist_ok=True)
            (d / rel).write_text("将来 `/faketool` を追加する予定。\n", encoding="utf-8")
            refs = {f["reference"] for f in sc.check_command_references(str(d), scan_dirs=["docs"])}
            self.assertIn("faketool", refs, f"{rel} への記載で抑制されている")

    def test_bypass_plan_md_declaration(self):
        """#22: 旧 `planned_commands()` は `docs/plan.md` の記載で抑制していた。

        cycle 3 のオーナー決定でヒューリスティックは全廃された。抑制手段は
        `docs/spec-check-allowlist.json` **のみ**であり、計画文書への記載では抑制されない。
        """
        self._assert_not_suppressed_by_plan_doc("docs/plan.md")

    def test_bypass_claude_md_declaration(self):
        """#22: `CLAUDE.md` への記載でも同様に抑制されない。"""
        self._assert_not_suppressed_by_plan_doc("CLAUDE.md")


# ============================================================ 許可リスト
class TestAllowlist(unittest.TestCase):
    """抑制は許可リストにのみ現れること。"""

    def test_allowed_globally(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertEqual(_cmd_ids(t, "1. `/recap` を実行する\n",
                                      allowlist_rows="| `/recap` | `*` | C-19 の記録 |\n"), set())

    def test_allowed_scoped_to_file(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertEqual(_cmd_ids(t, "1. `/recap` を実行する\n",
                                      allowlist_rows="| `/recap` | `docs/` | 記録 |\n"), set())

    def test_scope_does_not_match_other_file(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertIn("recap", _cmd_ids(t, "1. `/recap` を実行する\n",
                                            allowlist_rows="| `/recap` | `skills/` | 記録 |\n"))

    def test_scope_matches_on_path_boundary(self):
        """**負のテスト**: `docs/tech` が `docs/tech2/` を通さないこと。

        当初は `startswith` で照合しており、`docs/tech` が `docs/tech2/b.md` まで
        許可していた（Validator が Phase 07 の 4 巡目で実測）。
        """
        self.assertTrue(sc._scope_matches("docs/tech/a.md", "docs/tech"))
        self.assertTrue(sc._scope_matches("docs/tech", "docs/tech"))
        self.assertFalse(sc._scope_matches("docs/tech2/b.md", "docs/tech"))
        self.assertTrue(sc._scope_matches("anything.md", "*"))

    def test_markdown_doc_is_never_parsed(self):
        """**負のテスト**: `.md` に何を書いても許可にならない。

        当初は Markdown の表を読んでいたため、
        (a) コードフェンス内の例示（Critical #13）
        (b) `~~~` 形式のフェンス（#17）
        (c) 別見出しの説明用の表（#16）
        (d) 許可リスト文書自身の「経緯を説明する表」（#19。4 行が許可として読まれていた）
        がすべて許可として解釈された。**JSON に移して原理的に解消した。**
        """
        variants = [
            "# 説明\n\n```\n| `/mdtool` | `*` | 例示 |\n```\n",
            "# 説明\n\n~~~\n| `/mdtool` | `*` | 例示 |\n~~~\n",
            "# 説明\n\n## 却下した候補\n\n| 参照 | 対象 | 理由 |\n|---|---|---|\n"
            "| `/mdtool` | `*` | 却下 |\n",
        ]
        for md in variants:
            with tempfile.TemporaryDirectory() as t:
                d = Path(_project(t, "1. `/mdtool` を実行する\n"))
                (d / "docs" / "spec-check-allowlist.md").write_text(md, encoding="utf-8")
                ids = {f["reference"] for f in sc.check_command_references(str(d), scan_dirs=["docs"])}
                self.assertIn("mdtool", ids, f"Markdown を許可として読んではいけない: {md[:30]!r}")

    def test_malformed_json_allows_nothing(self):
        """壊れた JSON は「何も許可しない」に倒す（黙って全通しにしない）。"""
        with tempfile.TemporaryDirectory() as t:
            d = Path(_project(t, "1. `/jsontool` を実行する\n"))
            (d / "docs" / "spec-check-allowlist.json").write_text("{ broken", encoding="utf-8")
            ids = {f["reference"] for f in sc.check_command_references(str(d), scan_dirs=["docs"])}
            self.assertIn("jsontool", ids)

    def test_entry_missing_scope_is_ignored(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(_project(t, "1. `/jsontool` を実行する\n"))
            (d / "docs" / "spec-check-allowlist.json").write_text(
                '{"entries":[{"ref":"jsontool","reason":"理由あり"}]}', encoding="utf-8")
            ids = {f["reference"] for f in sc.check_command_references(str(d), scan_dirs=["docs"])}
            self.assertIn("jsontool", ids)

    def test_entry_without_reason_is_ignored(self):
        """**理由のない行は無効。** 黙って通すための追加を防ぐ。"""
        with tempfile.TemporaryDirectory() as t:
            self.assertIn("recap", _cmd_ids(t, "1. `/recap` を実行する\n",
                                            allowlist_rows="| `/recap` | `*` |  |\n"))

    def test_file_reference_allowed(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertEqual(_file_ids(t, "`scripts/future.py` を作る\n",
                                       allowlist_rows="| `scripts/future.py` | `*` | Phase 08 で作る |\n"),
                             set())

    def test_allowlist_file_itself_is_not_scanned(self):
        """許可リスト自身に書かれた参照を検出しないこと。"""
        with tempfile.TemporaryDirectory() as t:
            d = _project(t, "本文\n", allowlist_rows="| `/recap` | `*` | C-19 の記録 |\n")
            ids = {f["reference"] for f in sc.check_command_references(d, scan_dirs=["docs"])}
            self.assertEqual(ids, set())


# ============================================================ 解決できるもの
class TestResolution(unittest.TestCase):
    def test_existing_command(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertEqual(_cmd_ids(t, "`/run-phase` を実行\n", commands=["run-phase"]), set())

    def test_namespaced_command(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertEqual(_cmd_ids(t, "`/extras:create-deck` を実行\n",
                                      commands=["extras/create-deck"]), set())

    def test_skill_only_command_resolves(self):
        """Phase 13 / C-28: `.claude/commands/` に実体が無く `.claude/skills/<name>/SKILL.md`
        だけが存在するコマンドも解決済みとみなす（一本化後の実態）。

        公式ドキュメント: `.claude/commands/deploy.md` と `.claude/skills/deploy/SKILL.md` は
        どちらも `/deploy` を作り同じように動作する（`docs/requirements.md` C-28 が引用）。
        一本化でコマンド側の実体を削除すると、修正前の実装では大量の偽陽性
        （`/run-phase` 等プロジェクト中の全既存参照）が発生することを実測で確認した。
        """
        with tempfile.TemporaryDirectory() as t:
            self.assertEqual(
                _cmd_ids(t, "`/run-phase` を実行\n", commands=[],
                         extra_files=[".claude/skills/run-phase/SKILL.md"]),
                set())

    def test_skill_only_command_without_frontmatter_still_resolves(self):
        """frontmatter の有無は判定に影響しない（ディレクトリ名だけで解決する）。

        実測（2026-09-06、claude 2.1.263）: `name`/`description` frontmatter が無い
        SKILL.md でも `/<name>` は起動できることを隔離環境で確認済み
        （`docs/tech-stack.md` §7）。`real_commands()` もこれに合わせ、
        frontmatter の中身を一切パースせず、ディレクトリ名の存在だけで判定する。
        """
        with tempfile.TemporaryDirectory() as t:
            d = Path(_project(t, "`/lessons` を参照\n", commands=[]))
            skill_dir = d / ".claude" / "skills" / "lessons"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text("# lessons（frontmatter なし）", encoding="utf-8")
            ids = {f["reference"] for f in sc.check_command_references(str(d), scan_dirs=["docs"])}
            self.assertEqual(ids, set())

    def test_builtin_command(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertEqual(_cmd_ids(t, "`/compact` でコンテキストを圧縮\n"), set())

    def test_url_path_is_not_a_command(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertEqual(_cmd_ids(t, "https://code.claude.com/docs/en/hooks を参照\n"), set())

    def test_file_path_is_not_a_command(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertEqual(_cmd_ids(t, "`.claude/commands/run-phase.md` を編集\n"), set())

    def test_bare_filename_is_not_a_path(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertEqual(_file_ids(t, "`change-report.md` に 6 セクションを書く\n"), set())

    def test_shorthand_requires_allowlist(self):
        """**略記は許可リストに書く。推測で解決しない。**

        当初は「リポジトリ内のどこかに同じ末尾を持つファイルがあれば解決済み」としていたが、
        存在しない `b/c/target.md` が無関係な `a/b/c/target.md` との末尾一致だけで通っていた
        （Validator が Phase 07 の 4 巡目で実測）。処理ごと削除した。
        """
        with tempfile.TemporaryDirectory() as t:
            # 許可リストに無ければ検出される
            self.assertIn("run-phase/SKILL.md",
                          _file_ids(t, "`run-phase/SKILL.md` の Step 2.3\n",
                                    extra_files=[".claude/skills/run-phase/SKILL.md"]))

    def test_shorthand_allowed_by_allowlist(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertEqual(
                _file_ids(t, "`run-phase/SKILL.md` の Step 2.3\n",
                          extra_files=[".claude/skills/run-phase/SKILL.md"],
                          allowlist_rows="| `run-phase/SKILL.md` | `*` | 略記 |\n"), set())

    def test_suffix_match_alone_does_not_resolve(self):
        """**負のテスト**: 末尾一致だけで存在しないパスを解決しないこと。"""
        with tempfile.TemporaryDirectory() as t:
            self.assertIn("b/c/target.md",
                          _file_ids(t, "`b/c/target.md` を参照する\n",
                                    extra_files=["a/b/c/target.md"]))

    def test_path_placeholder(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertEqual(_file_ids(t, "`outputs/phase-NN/change-report.md` を作る\n"), set())


# ============================================================ 要件 ID
class TestRequirementIds(unittest.TestCase):
    """`skills/phase-07/SKILL.md` Procedure Step 4「要件 ID の重複」の検出。"""

    def _ids(self, tmp, text):
        d = Path(tmp) / "docs"
        d.mkdir(parents=True, exist_ok=True)
        (d / "requirements.md").write_text(text, encoding="utf-8")
        return sc.check_requirement_ids(str(tmp))

    def test_detects_duplicate(self):
        with tempfile.TemporaryDirectory() as t:
            f = self._ids(t, "| C-01 | a |\n| C-02 | b |\n| C-01 | c |\n")
            self.assertEqual([x["reference"] for x in f], ["C-01"])
            self.assertEqual(f[0]["kind"], "duplicate_id")

    def test_detects_duplicate_across_decorations(self):
        """`C-01` と `**C-01**` と `~~C-01~~` は同じ ID である。"""
        with tempfile.TemporaryDirectory() as t:
            f = self._ids(t, "| C-01 | a |\n| **C-01** | b |\n| ~~C-01~~ | c |\n")
            self.assertEqual(len(f), 2)

    def test_zero_padding_is_same_id(self):
        """`C-1` と `C-01` は同じ ID として扱う。"""
        with tempfile.TemporaryDirectory() as t:
            self.assertEqual(len(self._ids(t, "| C-1 | a |\n| C-01 | b |\n")), 1)

    def test_no_duplicate_is_clean(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertEqual(self._ids(t, "| C-01 | a |\n| R-01 | b |\n| S-01 | c |\n"), [])

    def test_gap_is_reported(self):
        """**欠番は欠陥**（Phase 08 で `docs/requirements.md` §9.2 が規約を定めた）。

        §9.2 は「取り下げた ID も `~~C-19~~` と残す。番号を再利用しない」と定める。
        したがって欠番は原則として存在しない。
        """
        with tempfile.TemporaryDirectory() as t:
            f = self._ids(t, "| C-01 | a |\n| C-05 | b |\n")
            self.assertEqual([x["reference"] for x in f],
                             ["C-02", "C-03", "C-04"])
            self.assertEqual({x["kind"] for x in f}, {"missing_id"})

    def test_struck_through_id_is_not_a_gap(self):
        """**打ち消し線の ID は欠番ではない。**

        規約が無い時点で欠番を実装していれば、本プロジェクトの
        C-19 / C-20 / C-21 / C-25 を誤検出していた（Phase 07 §8.1 で実測）。
        """
        with tempfile.TemporaryDirectory() as t:
            self.assertEqual(
                self._ids(t, "| C-01 | a |\n| ~~C-02~~ | 取り下げ |\n| C-03 | c |\n"), [])

    def test_gap_per_prefix(self):
        """接頭辞ごとに独立して数える。"""
        with tempfile.TemporaryDirectory() as t:
            f = self._ids(t, "| C-01 | a |\n| C-03 | b |\n| R-01 | c |\n| R-02 | d |\n")
            self.assertEqual([x["reference"] for x in f], ["C-02"])

    def test_real_project_has_no_gaps(self):
        root = str(Path(__file__).resolve().parent.parent)
        self.assertEqual(
            [f for f in sc.check_requirement_ids(root) if f["kind"] == "missing_id"], [])

    def test_prose_mentions_are_not_ids(self):
        """本文中の `C-99` は定義行ではない。"""
        with tempfile.TemporaryDirectory() as t:
            self.assertEqual(self._ids(t, "C-99 について述べる。\n| C-01 | a |\n"), [])

    def test_real_project_has_no_duplicates(self):
        root = str(Path(__file__).resolve().parent.parent)
        self.assertEqual(sc.check_requirement_ids(root), [])

    def _project(self, tmp, req_md, allowlist_entries=None):
        import json as _json
        d = Path(tmp) / "docs"
        d.mkdir(parents=True, exist_ok=True)
        (d / "requirements.md").write_text(req_md, encoding="utf-8")
        if allowlist_entries is not None:
            (d / "spec-check-allowlist.json").write_text(
                _json.dumps({"entries": allowlist_entries}, ensure_ascii=False), encoding="utf-8")
        return sc.check_requirement_ids(str(tmp))

    def test_code_fence_is_not_special(self):
        """#37: **フェンスの特別扱いはしない。** 抑制は許可リストだけ。

        #33 でフェンススキップを入れたが、その判定自体が種別を区別せず入れ子で誤爆し、
        未閉鎖のフェンスでは残り全行を黙って飛ばして exit=0 を返した。
        構造で抑制しようとするたびに穴が開く。
        """
        with tempfile.TemporaryDirectory() as t:
            f = self._project(t, "| C-01 | a |\n\n例:\n\n```\n| C-01 | 重複の例 |\n```\n")
            self.assertEqual([x["reference"] for x in f], ["C-01"])

    def test_nested_fence_does_not_confuse(self):
        """#37(b): 種別混在の入れ子でも判定がぶれない（フェンスを見ないので当然そうなる）。"""
        with tempfile.TemporaryDirectory() as t:
            f = self._project(t, "| C-01 | a |\n~~~\n```\n| C-01 | 例 |\n```\n~~~\n")
            self.assertEqual([x["reference"] for x in f], ["C-01"])

    def test_unclosed_fence_does_not_silence(self):
        """#37(c): **未閉鎖のフェンスで沈黙しない。** これが最も危険な型だった。"""
        with tempfile.TemporaryDirectory() as t:
            f = self._project(t, "| C-01 | a |\n```\n| C-01 | b |\n| C-01 | c |\n")
            self.assertEqual(len(f), 2)

    def test_fenced_example_is_suppressed_by_allowlist(self):
        """フェンス内の例示を通したいなら**許可リストに書く**（抑制は 1 ファイルに現れる）。"""
        with tempfile.TemporaryDirectory() as t:
            self.assertEqual(self._project(
                t, "| C-01 | a |\n```\n| C-01 | 例 |\n```\n",
                [{"ref": "C-01", "scope": "docs/requirements.md", "reason": "説明用の例示"}]), [])

    def test_allowlist_suppresses_duplicate(self):
        """#33: 抑制経路は兄弟の 2 検査と同じ 1 つだけ（許可リスト）。"""
        with tempfile.TemporaryDirectory() as t:
            self.assertEqual(self._project(
                t, "| C-01 | a |\n| C-01 | b |\n",
                [{"ref": "C-01", "scope": "docs/requirements.md", "reason": "意図的な再掲"}]), [])

    def test_allowlist_scope_must_match(self):
        """`scope` が別ファイルなら抑制されない。"""
        with tempfile.TemporaryDirectory() as t:
            f = self._project(
                t, "| C-01 | a |\n| C-01 | b |\n",
                [{"ref": "C-01", "scope": "docs/plan.md", "reason": "別ファイル"}])
            self.assertEqual([x["reference"] for x in f], ["C-01"])


class TestNotACommand(unittest.TestCase):
    """v15.1: 絶対パス・拡張子つきの名前をコマンドと誤認しない（負のテストと陽性対照の組）。"""

    def _refs(self, text):
        with tempfile.TemporaryDirectory() as t:
            return [f["reference"] for f in
                    sc.check_command_references(_project(t, text), scan_dirs=["docs"])]

    def test_absolute_paths_are_not_commands(self):
        self.assertEqual(self._refs("`/home/user/run.sh` と `/usr/bin/git` を使う\n"), [])

    def test_name_with_extension_is_not_a_command(self):
        self.assertEqual(self._refs("ファイル `/notes.md` と `/setup.py`\n"), [])

    def test_no_backtracking_to_a_shorter_prefix(self):
        """`/run-phase/SKILL.md` を `/run` や `/run-phas` として拾わない。"""
        self.assertEqual(self._refs("`/made-up/SKILL.md` を読む\n"), [])

    def test_positive_control_real_unresolved_command_still_reported(self):
        self.assertEqual(self._refs("`/made-up` を実行\n"), ["made-up"])

    def test_positive_control_japanese_right_after_is_still_a_command(self):
        self.assertEqual(self._refs("まず /made-upを実行する\n"), ["made-up"])

    def test_positive_control_sentence_final_period(self):
        self.assertEqual(self._refs("最後に /made-up.\n"), ["made-up"])


class TestExcludesAndResolveRoots(unittest.TestCase):
    """v15.1: 許可リスト JSON の `excludes` と `resolve_roots`（どちらも reason 必須）。"""

    def _write(self, t, data, files):
        import json as _json
        d = Path(t)
        for rel, body in files.items():
            f = d / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(body, encoding="utf-8")
        (d / "docs" / "spec-check-allowlist.json").write_text(
            _json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return str(d)

    def test_excluded_history_file_is_not_scanned(self):
        with tempfile.TemporaryDirectory() as t:
            root = self._write(t, {"excludes": [
                {"scope": "docs/CHANGELOG.md", "reason": "履歴。過去のファイルへの言及は正しい"}]},
                {"docs/CHANGELOG.md": "`docs/gone.md` を削除した\n",
                 "docs/x.md": "`docs/missing.md` を読む\n"})
            excluded = set()
            f = sc.check_file_references(root, ["docs"], excluded)
            self.assertEqual([x["reference"] for x in f], ["docs/missing.md"])
            self.assertEqual(excluded, {"docs/CHANGELOG.md"})

    def test_negative_exclude_without_reason_is_invalid(self):
        with tempfile.TemporaryDirectory() as t:
            root = self._write(t, {"excludes": [{"scope": "docs/CHANGELOG.md", "reason": ""}]},
                               {"docs/CHANGELOG.md": "`docs/gone.md`\n"})
            self.assertEqual(len(sc.check_file_references(root, ["docs"])), 1)

    def test_negative_wildcard_exclude_is_invalid(self):
        """`"*"` で検査全体を黙って止められない。"""
        with tempfile.TemporaryDirectory() as t:
            root = self._write(t, {"excludes": [{"scope": "*", "reason": "全部"}]},
                               {"docs/x.md": "`docs/gone.md` と `/made-up`\n"})
            self.assertEqual(len(sc.check_file_references(root, ["docs"])), 1)
            self.assertEqual(len(sc.check_command_references(root, ["docs"])), 1)

    def test_exclude_uses_path_boundary(self):
        with tempfile.TemporaryDirectory() as t:
            root = self._write(t, {"excludes": [{"scope": "docs/hist", "reason": "履歴"}]},
                               {"docs/hist/a.md": "`docs/gone.md`\n",
                                "docs/history.md": "`docs/gone2.md`\n"})
            self.assertEqual([x["file"] for x in sc.check_file_references(root, ["docs"])],
                             ["docs/history.md"])

    def test_resolve_root_resolves_product_relative_paths(self):
        with tempfile.TemporaryDirectory() as t:
            root = self._write(t, {"resolve_roots": [
                {"path": "product/app", "reason": "製品リポジトリ相対のパス"}]},
                {"product/app/src/core.py": "x",
                 "docs/x.md": "`src/core.py` と `src/nothere.py`\n"})
            f = sc.check_file_references(root, ["docs"])
            self.assertEqual([x["reference"] for x in f], ["src/nothere.py"])

    def test_negative_resolve_root_without_reason_is_ignored(self):
        with tempfile.TemporaryDirectory() as t:
            root = self._write(t, {"resolve_roots": [{"path": "product/app"}]},
                               {"product/app/src/core.py": "x", "docs/x.md": "`src/core.py`\n"})
            self.assertEqual(len(sc.check_file_references(root, ["docs"])), 1)


class TestRobustInputs(unittest.TestCase):
    def test_negative_nonexistent_project_dir_is_exit_2(self):
        import subprocess, sys
        p = subprocess.run([sys.executable, str(Path(__file__).parent / "spec_check.py"),
                            "--project-dir", "/nonexistent/sdd-project"],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 2)

    def test_allowlist_that_is_a_json_list_does_not_crash(self):
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / "docs").mkdir()
            (Path(t) / "docs" / "spec-check-allowlist.json").write_text("[]", encoding="utf-8")
            self.assertEqual(sc.load_allowlist(t), [])
            self.assertEqual(sc.load_excludes(t), [])


class TestFindingShape(unittest.TestCase):
    def test_finding_has_location_and_kind(self):
        with tempfile.TemporaryDirectory() as t:
            f = sc.check_command_references(_project(t, "`/made-up` を実行\n"), scan_dirs=["docs"])
            self.assertTrue(f)
            for key in ("file", "line", "reference", "kind", "message", "context"):
                self.assertIn(key, f[0])
            self.assertEqual(f[0]["file"], "docs/x.md")
            self.assertEqual(f[0]["line"], 1)
            self.assertEqual(f[0]["kind"], "unresolved")


if __name__ == "__main__":
    unittest.main()
