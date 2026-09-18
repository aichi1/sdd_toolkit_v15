#!/usr/bin/env python3
"""
test_check_constitution.py: check_constitution.py の回帰テスト（R-12 / Phase 06）

**負のテストを重視する。** C-42 の教訓:
  機械チェックを置くだけでは足りない。そのチェック自体が正しいことを、
  **わざと違反する入力**を通して確かめる。C-42 では exit code 検査が
  「exit=1 と書かれた行を pass 判定にする」ことを実証して初めて穴が判明した。

各条項について「違反する入力で fail になる」ことと
「正しい入力で pass になる」ことの両方をテストする。
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "check_constitution", str(Path(__file__).parent / "check_constitution.py")
)
cc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cc)


def _statuses(results, check=None):
    return [r["status"] for r in results if check is None or r["check"] == check]


class TestSelfModificationDetection(unittest.TestCase):
    """`.claude/` 配下の変更を検出できること。"""

    def test_detects_settings_json(self):
        self.assertTrue(cc.has_self_modification(
            {"in_place_changes": ["docs/plan.md", ".claude/settings.json"]}))

    def test_detects_hooks(self):
        self.assertTrue(cc.has_self_modification(
            {"in_place_changes": [".claude/hooks/remind-finalize.py"]}))

    def test_detects_with_annotation(self):
        """in_place_changes は「path（説明）」形式のこともある。"""
        self.assertTrue(cc.has_self_modification(
            {"in_place_changes": [".claude/agents/validator.md（禁止パターン追加）"]}))

    def test_detects_new_files_under_claude(self):
        """**Validator が Phase 07 で検出**: 新規作成も自己変更である。

        `.claude/commands/` へのファイル**追加**は `new_files` に記録されるため、
        `in_place_changes` だけを見ていると「自己変更なし」と判定していた。
        その結果、第10条の機械強制が空振りしていた。
        """
        self.assertTrue(cc.has_self_modification(
            {"in_place_changes": ["docs/plan.md"],
             "new_files": [".claude/commands/spec-check.md"]}))

    def test_detects_new_skill_directory(self):
        self.assertTrue(cc.has_self_modification(
            {"new_files": [".claude/skills/clarify/SKILL.md"]}))

    def test_new_files_outside_claude_is_not_self_modification(self):
        self.assertFalse(cc.has_self_modification(
            {"new_files": ["scripts/spec_check.py", "docs/x.md"]}))

    def test_no_false_positive_on_scripts(self):
        self.assertFalse(cc.has_self_modification(
            {"in_place_changes": ["scripts/validate-outputs.py", "docs/requirements.md"]}))

    def test_empty_metadata(self):
        self.assertFalse(cc.has_self_modification({}))
        self.assertFalse(cc.has_self_modification(None))


class TestModifiedSkillNames(unittest.TestCase):
    def test_extracts_skill_name(self):
        self.assertEqual(
            cc.modified_skill_names({"in_place_changes": [".claude/skills/add-feature/SKILL.md"]}),
            {"add-feature"})

    def test_multiple_skills(self):
        self.assertEqual(
            cc.modified_skill_names({"in_place_changes": [
                ".claude/skills/add-feature/SKILL.md",
                ".claude/skills/run-phase/SKILL.md"]}),
            {"add-feature", "run-phase"})

    def test_ignores_non_skill_paths(self):
        self.assertEqual(
            cc.modified_skill_names({"in_place_changes": [".claude/hooks/x.py"]}), set())

    def test_detects_newly_created_skill(self):
        """#29: **新規作成したスキル**も第3条 / D-02 の対象である。

        `has_self_modification()` は #4 で `new_files` を見るよう直されたのに、
        兄弟関数である本関数は `in_place_changes` しか見ていなかった。
        そのフェーズで新設したスキルを同じフェーズで実行しても素通りしていた。
        """
        self.assertEqual(
            cc.modified_skill_names({"new_files": [".claude/skills/spec-check/SKILL.md"]}),
            {"spec-check"})

    def test_merges_both_keys(self):
        self.assertEqual(
            cc.modified_skill_names({
                "in_place_changes": [".claude/skills/run-phase/SKILL.md"],
                "new_files": [".claude/skills/clarify/SKILL.md"]}),
            {"run-phase", "clarify"})


class _Fixture:
    """検査対象の最小プロジェクトを一時ディレクトリに作る。"""

    def __init__(self, tmp):
        self.root = Path(tmp)
        (self.root / ".claude" / "hooks").mkdir(parents=True)
        (self.root / "outputs").mkdir()
        (self.root / ".claude" / "settings.json").write_text('{"permissions": {}}',
                                                             encoding="utf-8")
        self.phase_dir(6).mkdir(parents=True)

    def phase_dir(self, n):
        return self.root / "outputs" / f"phase-{n:02d}"

    def metadata(self, n, **kw):
        (self.phase_dir(n)).mkdir(parents=True, exist_ok=True)
        (self.phase_dir(n) / ".metadata.json").write_text(
            json.dumps(kw, ensure_ascii=False), encoding="utf-8")

    def context(self, **kw):
        (self.root / "outputs" / ".phase-context.json").write_text(
            json.dumps(kw, ensure_ascii=False), encoding="utf-8")

    def hook(self, name, crashes=False):
        body = ("import sys, json\n"
                + ("json.load(sys.stdin)\n" if crashes
                   else "try:\n    json.load(sys.stdin)\nexcept Exception:\n    pass\n")
                + "sys.exit(0)\n")
        (self.root / ".claude" / "hooks" / name).write_text(body, encoding="utf-8")

    def verification_log(self, n, text):
        (self.phase_dir(n) / "verification.log").write_text(text, encoding="utf-8")


class TestPhaseScripts(unittest.TestCase):
    """第3条 改正(2): そのフェーズが作った/変えた `scripts/*.py`。"""

    def test_collects_both_keys(self):
        self.assertEqual(
            cc.phase_scripts({"in_place_changes": ["scripts/a.py", "CLAUDE.md"],
                              "new_files": ["scripts/b.py", ".claude/commands/x.md"]}),
            {"scripts/a.py", "scripts/b.py"})

    def test_ignores_non_scripts(self):
        self.assertEqual(
            cc.phase_scripts({"new_files": ["docs/x.py", "scripts/y.md", "outputs/phase-07/"]}),
            set())

    def test_empty(self):
        self.assertEqual(cc.phase_scripts({}), set())
        self.assertEqual(cc.phase_scripts(None), set())


class TestUnapprovedAmendments(unittest.TestCase):
    """第3条 強制点: 改正履歴の追認状況表に未承認の行が無いこと。

    改正手続きの逸脱は Phase 01・02・07 で**四度**起き、毎回 Validator が事後に検出した。
    四度目のオーナー決定（2026-09-05）で**表の状態を強制点にした**。
    """

    HEAD = ("## 改正履歴の追認状況\n\n"
            "| 改正 | 条 | 日付 | 承認 |\n|------|----|------|------|\n")

    def _write(self, tmp, rows, tail=""):
        d = Path(tmp) / "docs"
        d.mkdir(parents=True, exist_ok=True)
        (d / "constitution.md").write_text(self.HEAD + rows + tail, encoding="utf-8")
        return cc.unapproved_amendments(str(tmp))

    def test_all_approved(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertEqual(self._write(t,
                "| A | 第2条 | 2026-09-03 | **オーナー追認済み（2026-09-03）** |\n"
                "| B | 第3条 | 2026-09-04 | **オーナー事前承認済み（2026-09-04）** |\n"
                "| C | 第10条 | 2026-09-04 | **オーナー決定済み（選択肢 (b)）** |\n"), [])

    def test_detects_unapproved(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertEqual(self._write(t,
                "| A | 第2条 | 2026-09-03 | **オーナー追認済み** |\n"
                "| B | 第3条 | 2026-09-05 | **オーナー未承認（事後報告）** |\n"), ["B"])

    def test_stops_at_next_section(self):
        """表の後ろの節にある文章を行として拾わない。"""
        with tempfile.TemporaryDirectory() as t:
            self.assertEqual(self._write(t,
                "| A | 第2条 | 2026-09-03 | **オーナー追認済み** |\n",
                "\n## 改正手続き\n\n| これは | 別の | 表 | 未承認 |\n"), [])

    def test_missing_table(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t) / "docs"
            d.mkdir(parents=True)
            (d / "constitution.md").write_text("# 憲法\n", encoding="utf-8")
            self.assertIsNone(cc.unapproved_amendments(str(t)))


class TestArticle3ScriptRerun(unittest.TestCase):
    """第3条 改正(2): 変更したスクリプトを Validator が再実行した証跡。

    **テストモジュールは名指しでは走らない。** `python3 -m pytest scripts/ -q` の
    一括実行で走るため、表に `pytest` があれば再実行されているとみなす
    （この検査自身が初回実行でこの点を取りこぼして fail を出した）。
    """

    def _run(self, tmp, scripts, ev_body):
        pd = Path(tmp) / "outputs" / "phase-07"
        (pd / ".validation").mkdir(parents=True, exist_ok=True)
        (pd / ".metadata.json").write_text(
            json.dumps({"phase": 7, "new_files": scripts}, ensure_ascii=False), encoding="utf-8")
        (pd / ".validation" / "report.md").write_text(
            "# r\n\n## 7. Executed Verification\n\n" + ev_body, encoding="utf-8")
        (Path(tmp) / ".claude").mkdir(exist_ok=True)
        (Path(tmp) / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
        res = cc.check_article_3(str(tmp), 7)
        return {r["check"]: r for r in res}["phase_scripts_rerun_by_validator"]

    def test_named_script_counts(self):
        with tempfile.TemporaryDirectory() as t:
            r = self._run(t, ["scripts/spec_check.py"], "| 1 | `python3 scripts/spec_check.py` | 0 |")
            self.assertEqual(r["status"], "pass")

    def test_test_module_covered_by_pytest(self):
        with tempfile.TemporaryDirectory() as t:
            r = self._run(t, ["scripts/test_foo.py"], "| 1 | `python3 -m pytest scripts/ -q` | 0 |")
            self.assertEqual(r["status"], "pass")

    def test_test_module_without_pytest_fails(self):
        with tempfile.TemporaryDirectory() as t:
            r = self._run(t, ["scripts/test_foo.py"], "| 1 | `git status` | 0 |")
            self.assertEqual(r["status"], "fail")

    def test_unrun_script_fails(self):
        with tempfile.TemporaryDirectory() as t:
            r = self._run(t, ["scripts/never_run.py"], "| 1 | `python3 -m pytest scripts/ -q` | 0 |")
            self.assertEqual(r["status"], "fail")
            self.assertIn("never_run.py", r["message"])

    def test_negation_in_prose_does_not_count(self):
        """#36: 「実行していない」という**否定文**で pass してはいけない。

        散文ではなく、**コマンドの形をしたバッククォート span** だけを見る。
        """
        with tempfile.TemporaryDirectory() as t:
            r = self._run(t, ["scripts/spec_check.py"],
                          "`scripts/spec_check.py` は今回**実行していない**。")
            self.assertEqual(r["status"], "fail")

    def test_pytest_mentioned_in_prose_does_not_count(self):
        """#36: 「pytest は回していない」でテストモジュールを pass させない。"""
        with tempfile.TemporaryDirectory() as t:
            r = self._run(t, ["scripts/test_foo.py"], "時間の都合で `pytest` は回していない。")
            self.assertEqual(r["status"], "fail")

    def test_command_span_counts(self):
        """コマンドの形をしていれば pass（`python3` / `pytest` / `git` などで始まる）。"""
        with tempfile.TemporaryDirectory() as t:
            r = self._run(t, ["scripts/spec_check.py"],
                          "| 3 | `python3 scripts/spec_check.py --check requirement_id` | 0 | OK |")
            self.assertEqual(r["status"], "pass")

    def test_backtick_command_in_prose_does_not_count(self):
        """#40: **表の行だけが証跡**。散文中のコマンドは数えない。

        #36 の修正後も「`python3 scripts/spec_check.py` は実行していない」という
        **正しい形のコマンドを含む否定文**で pass していた。
        """
        with tempfile.TemporaryDirectory() as t:
            r = self._run(t, ["scripts/spec_check.py"],
                          "今回 `python3 scripts/spec_check.py --json` は実行していない。")
            self.assertEqual(r["status"], "fail")

    def test_command_in_later_section_does_not_count(self):
        """#40: セクションの終端で切る。後続の節のコマンドは数えない。"""
        body = ("| 1 | `git status --porcelain` | 0 | OK |\n"
                "\n## 8. Suggestions\n\n"
                "次回は `python3 scripts/spec_check.py --json` を使うとよい。\n")
        with tempfile.TemporaryDirectory() as t:
            r = self._run(t, ["scripts/spec_check.py"], body)
            self.assertEqual(r["status"], "fail")

    def test_pytest_in_later_section_does_not_count(self):
        body = ("| 1 | `git status --porcelain` | 0 | OK |\n"
                "\n## 8. Suggestions\n\n"
                "`python3 -m pytest scripts/ -q` を回すとよい。\n")
        with tempfile.TemporaryDirectory() as t:
            r = self._run(t, ["scripts/test_foo.py"], body)
            self.assertEqual(r["status"], "fail")

    def test_env_prefixed_command_counts(self):
        """`env` や環境変数の前置きがあっても数える（正当な実行を落とさない）。"""
        with tempfile.TemporaryDirectory() as t:
            r = self._run(t, ["scripts/spec_check.py"],
                          "| 1 | `PYTHONDONTWRITEBYTECODE=1 python3 scripts/spec_check.py` | 0 | OK |")
            self.assertEqual(r["status"], "pass")


class TestArticle3(unittest.TestCase):
    """第3条: D-02（変更中のスキルを実行しない）と D-04（safe-mode 起動可能性）。"""

    def test_positive_settings_json_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _Fixture(tmp); f.metadata(6, in_place_changes=[])
            r = cc.check_article_3(str(f.root), 6)
            self.assertIn("pass", _statuses(r, "settings_json_valid"))

    def test_negative_settings_json_broken(self):
        """**負のテスト**: settings.json が壊れていれば fail になること。"""
        with tempfile.TemporaryDirectory() as tmp:
            f = _Fixture(tmp); f.metadata(6, in_place_changes=[])
            (f.root / ".claude" / "settings.json").write_text("{ broken", encoding="utf-8")
            r = cc.check_article_3(str(f.root), 6)
            self.assertIn("fail", _statuses(r, "settings_json_valid"))

    def test_positive_hooks_never_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _Fixture(tmp); f.metadata(6, in_place_changes=[])
            f.hook("safe.py", crashes=False)
            r = cc.check_article_3(str(f.root), 6)
            self.assertIn("pass", _statuses(r, "hooks_never_crash"))

    def test_negative_crashing_hook_is_detected(self):
        """**負のテスト**: 不正入力で落ちる hook があれば fail になること（C-39 と同型）。"""
        with tempfile.TemporaryDirectory() as tmp:
            f = _Fixture(tmp); f.metadata(6, in_place_changes=[])
            f.hook("safe.py", crashes=False)
            f.hook("crashy.py", crashes=True)
            r = cc.check_article_3(str(f.root), 6)
            self.assertIn("fail", _statuses(r, "hooks_never_crash"))

    def test_legacy_phase_is_skipped_even_if_execution_note_says_executed(self):
        """Phase 12 未満（旧形式）は D-02 構造化フィールドの適用対象外 → skip。

        C-52 の改正（決定B）前は、この入力（`execution_note` に `/run-phase` を含む）は
        部分文字列一致で fail していた。**過去フェーズの証跡は遡及修正しない**ため、
        Phase 12 未満は判定そのものをスキップする（`execution_note` は一切読まない）。
        """
        with tempfile.TemporaryDirectory() as tmp:
            f = _Fixture(tmp)
            f.metadata(6, in_place_changes=[".claude/skills/run-phase/SKILL.md"],
                       execution_note="本フェーズでは /run-phase を実行して検証した")
            r = cc.check_article_3(str(f.root), 6)
            self.assertEqual(_statuses(r, "modified_skill_not_executed"), ["skip"])

    def test_legacy_phase_without_structured_field_does_not_crash(self):
        """**後方互換**: 旧 `.metadata.json`（`skills_executed_this_phase` フィールド無し）が読める。

        R-32: 新フィールドがスキーマ後方互換であることを示す。
        """
        with tempfile.TemporaryDirectory() as tmp:
            f = _Fixture(tmp)
            f.metadata(11, in_place_changes=[".claude/agents/eval-judge.md"],
                       execution_note="旧形式のメタデータ。skills_executed_this_phase を持たない")
            r = cc.check_article_3(str(f.root), 11)
            self.assertEqual(_statuses(r, "modified_skill_not_executed"), ["skip"])

    def test_phase_12_negative_declared_skill_executed(self):
        """**負のテスト（R-32 / 構造化フィールド）**: Phase 12 以降、`skills_executed_this_phase` に
        変更したスキル名が含まれていれば fail。"""
        with tempfile.TemporaryDirectory() as tmp:
            f = _Fixture(tmp)
            f.metadata(12, in_place_changes=[".claude/skills/run-phase/SKILL.md"],
                       skills_executed_this_phase=["run-phase"])
            r = cc.check_article_3(str(f.root), 12)
            self.assertEqual(_statuses(r, "modified_skill_not_executed"), ["fail"])

    def test_phase_12_positive_declared_empty(self):
        """Phase 12 以降、`skills_executed_this_phase` が空配列なら pass。"""
        with tempfile.TemporaryDirectory() as tmp:
            f = _Fixture(tmp)
            f.metadata(12, in_place_changes=[".claude/skills/run-phase/SKILL.md"],
                       skills_executed_this_phase=[])
            r = cc.check_article_3(str(f.root), 12)
            self.assertEqual(_statuses(r, "modified_skill_not_executed"), ["pass"])

    def test_phase_12_missing_field_fails(self):
        """**負のテスト**: Phase 12 以降で `skills_executed_this_phase` フィールドが無ければ fail。

        フィールドを省けば検査を回避できる、という新しい穴を開けないための設計（C-42 と同型）。
        """
        with tempfile.TemporaryDirectory() as tmp:
            f = _Fixture(tmp)
            f.metadata(12, in_place_changes=[".claude/skills/run-phase/SKILL.md"])
            r = cc.check_article_3(str(f.root), 12)
            self.assertEqual(_statuses(r, "modified_skill_not_executed"), ["fail"])

    def test_phase_12_missing_field_is_fine_when_no_skill_modified(self):
        """スキルを変更していないフェーズでは `skills_executed_this_phase` が無くても pass。"""
        with tempfile.TemporaryDirectory() as tmp:
            f = _Fixture(tmp)
            f.metadata(12, in_place_changes=["docs/requirements.md"])
            r = cc.check_article_3(str(f.root), 12)
            self.assertEqual(_statuses(r, "modified_skill_not_executed"), ["pass"])

    def test_phase_12_regression_prefix_match_in_prose_does_not_cause_false_positive(self):
        """**C-52 の回帰テスト**: ファイル名が `/{skill}` に前方一致するが実行していないケース。

        旧実装は `execution_note` を部分文字列一致で読んでいたため、`docs/convergence.md` への
        言及（`convergence` が `converge` に前方一致）だけで `converge` を「実行した」と
        誤検出していた。新実装は `execution_note` を一切読まないため、このケースで pass する。
        """
        with tempfile.TemporaryDirectory() as tmp:
            f = _Fixture(tmp)
            f.metadata(
                12,
                new_files=[".claude/skills/converge/SKILL.md"],
                skills_executed_this_phase=[],
                execution_note=(
                    "本フェーズは docs/convergence.md の初回エントリを Builder が手で作成した"
                    "（ドライラン。/converge は起動していない）"
                ),
            )
            r = cc.check_article_3(str(f.root), 12)
            self.assertEqual(_statuses(r, "modified_skill_not_executed"), ["pass"])

    def test_phase_12_gate_check_ignores_deviations_field(self):
        """構造化フィールド移行後は `deviations` も一切読まない。"""
        with tempfile.TemporaryDirectory() as tmp:
            f = _Fixture(tmp)
            f.metadata(
                12,
                in_place_changes=[".claude/skills/run-phase/SKILL.md"],
                skills_executed_this_phase=[],
                deviations=["/run-phase を実行して確認した"],
            )
            r = cc.check_article_3(str(f.root), 12)
            self.assertEqual(_statuses(r, "modified_skill_not_executed"), ["pass"])


class TestArticle10(unittest.TestCase):
    """第10条: 自己変更は次のセッションで確かめる（D-01）。"""

    def test_skipped_before_phase_6(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _Fixture(tmp)
            r = cc.check_article_10(str(f.root), 5)
            self.assertEqual(_statuses(r, "new_session_after_self_modify"), ["skip"])

    def test_phase_6_is_skipped_because_previous_phase_predates_the_article(self):
        """条文の「遡及適用しない」に従い、Phase 05→06 の遷移は判定対象外（オーナー決定 (b)）。

        判定材料は**前フェーズの自己変更**である。Phase 05 は第10条が存在しない時点の
        フェーズなので、その振る舞いを裁くのは遡及適用にあたる。
        当初の実装は現フェーズだけを見ており、Phase 06 自身を違反にしていた。
        """
        with tempfile.TemporaryDirectory() as tmp:
            f = _Fixture(tmp)
            f.metadata(5, session="same", in_place_changes=[".claude/settings.json"])
            f.metadata(6, session="same")
            r = cc.check_article_10(str(f.root), 6)
            self.assertEqual(_statuses(r, "new_session_after_self_modify"), ["skip"])
            self.assertNotIn("fail", _statuses(r))

    def test_phase_7_is_judged(self):
        """Phase 06→07 は前フェーズが適用開始以降なので判定対象になる。"""
        with tempfile.TemporaryDirectory() as tmp:
            f = _Fixture(tmp)
            f.metadata(6, session="same", in_place_changes=[".claude/settings.json"])
            f.metadata(7, session="same")
            f.verification_log(7, "$ echo x | python3 .claude/hooks/a.py\n"
                                  "$ echo x | python3 .claude/hooks/b.py\n")
            r = cc.check_article_10(str(f.root), 7)
            self.assertIn("fail", _statuses(r, "new_session_after_self_modify"))

    def test_pass_when_previous_phase_had_no_self_modification(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _Fixture(tmp)
            f.metadata(6, session="s1", in_place_changes=["docs/plan.md"])
            f.metadata(7, session="s1")
            r = cc.check_article_10(str(f.root), 7)
            self.assertIn("pass", _statuses(r, "new_session_after_self_modify"))

    def test_negative_same_session_after_self_modification(self):
        """**負のテスト**: 自己変更の次フェーズが同一セッションなら fail。"""
        with tempfile.TemporaryDirectory() as tmp:
            f = _Fixture(tmp)
            f.metadata(6, session="same-session",
                       in_place_changes=[".claude/settings.json"])
            f.metadata(7, session="same-session")
            f.verification_log(7, "$ echo x | python3 .claude/hooks/a.py\n"
                                  "$ echo x | python3 .claude/hooks/b.py\n")
            r = cc.check_article_10(str(f.root), 7)
            self.assertIn("fail", _statuses(r, "new_session_after_self_modify"))

    def test_positive_new_session_with_hook_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _Fixture(tmp)
            f.metadata(6, session="old-session",
                       in_place_changes=[".claude/settings.json"])
            f.metadata(7, session="new-session")
            f.verification_log(7, "$ echo x | python3 .claude/hooks/a.py\n"
                                  "$ echo x | python3 .claude/hooks/b.py\n")
            r = cc.check_article_10(str(f.root), 7)
            self.assertNotIn("fail", _statuses(r))

    def test_negative_missing_hook_verification(self):
        """**負のテスト**: セッションは変わったが動作確認の証跡がなければ fail。"""
        with tempfile.TemporaryDirectory() as tmp:
            f = _Fixture(tmp)
            f.metadata(6, session="old", in_place_changes=[".claude/hooks/x.py"])
            f.metadata(7, session="new")
            f.verification_log(7, "$ python3 -m pytest scripts/ -q\n")
            r = cc.check_article_10(str(f.root), 7)
            self.assertIn("fail", _statuses(r, "self_modify_verified"))


class TestArticle11(unittest.TestCase):
    """第11条: 引き継ぎは機械が読める形で残す（D-05）。"""

    def test_negative_missing_keys(self):
        """**負のテスト**: 必須キーが欠けていれば fail。"""
        with tempfile.TemporaryDirectory() as tmp:
            f = _Fixture(tmp)
            f.context(last_phase=6)
            f.metadata(6, in_place_changes=[])
            r = cc.check_article_11(str(f.root), 6)
            self.assertIn("fail", _statuses(r, "phase_context_keys"))

    def test_positive_keys_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _Fixture(tmp)
            f.context(last_phase=6, self_modified_files=[], stale_procedures=[])
            f.metadata(6, in_place_changes=[])
            r = cc.check_article_11(str(f.root), 6)
            self.assertNotIn("fail", _statuses(r))

    def test_negative_empty_when_self_modified(self):
        """**負のテスト**: 自己変更があるのに self_modified_files が空なら fail。"""
        with tempfile.TemporaryDirectory() as tmp:
            f = _Fixture(tmp)
            f.context(last_phase=6, self_modified_files=[], stale_procedures=["x"])
            f.metadata(6, in_place_changes=[".claude/settings.json"])
            r = cc.check_article_11(str(f.root), 6)
            self.assertIn("fail", _statuses(r, "self_modified_files_recorded"))

    def test_negative_missing_context_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _Fixture(tmp)
            f.metadata(6, in_place_changes=[])
            r = cc.check_article_11(str(f.root), 6)
            self.assertIn("fail", _statuses(r, "phase_context_keys"))


class TestArticle11PhaseAwareness(unittest.TestCase):
    """**Validator が Phase 07 で検出**: 第11条が前フェーズの残骸で pass していた。

    `.phase-context.json` はフェーズ完了ごとに上書きされる**単一ファイル**である。
    フェーズを見ずに中身を数えると、前フェーズの記録で偽の pass になる。
    """

    def test_stale_context_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _Fixture(tmp)
            f.context(last_phase=6, self_modified_files=["x"], stale_procedures=["y"])
            f.metadata(7, in_place_changes=[".claude/settings.json"])
            r = cc.check_article_11(str(f.root), 7)
            self.assertIn("fail", _statuses(r, "phase_context_is_current"))

    def test_current_context_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _Fixture(tmp)
            f.context(last_phase=7, self_modified_files=["x"], stale_procedures=["y"])
            f.metadata(7, in_place_changes=[".claude/settings.json"])
            r = cc.check_article_11(str(f.root), 7)
            self.assertNotIn("fail", _statuses(r))

    def test_missing_last_phase_is_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _Fixture(tmp)
            f.context(self_modified_files=["x"], stale_procedures=["y"])
            f.metadata(7, in_place_changes=[])
            r = cc.check_article_11(str(f.root), 7)
            self.assertIn("fail", _statuses(r, "phase_context_is_current"))


class TestNoSilentSkip(unittest.TestCase):
    """C-42 の教訓: 判定できなかった項目を黙って pass にしないこと。"""

    def test_unreadable_metadata_is_skip_not_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _Fixture(tmp)   # .metadata.json を作らない
            r = cc.check_article_3(str(f.root), 6)
            s = _statuses(r, "modified_skill_not_executed")
            self.assertEqual(s, ["skip"], "判定不能を pass にしてはいけない")

    def test_exception_in_check_becomes_fail(self):
        """検査中の例外を黙って握りつぶさないこと。"""
        original = cc.CHECKS[11]
        try:
            cc.CHECKS[11] = lambda root, phase: (_ for _ in ()).throw(RuntimeError("boom"))
            r = cc.run_checks("/nonexistent", 6, {11})
            self.assertIn("fail", _statuses(r, "check_error"))
        finally:
            cc.CHECKS[11] = original


class TestCliProfiles(unittest.TestCase):
    """v15.1: `--article` 省略時は汎用の第2条のみ。未実装の条番号は実行エラー（exit 2）。"""

    SCRIPT = str(Path(__file__).parent / "check_constitution.py")

    def _run(self, *args):
        with tempfile.TemporaryDirectory() as tmp:
            p = subprocess.run([sys.executable, self.SCRIPT, "--project-dir", tmp, "--json", *args],
                               capture_output=True, text=True)
            return p.returncode, p.stdout

    def _articles(self, out):
        return sorted({r["article"] for r in json.loads(out)})

    def test_default_runs_only_generic_article_2(self):
        """既定は第2条と、条番号に依存しない改正手続きの検査（article 0）だけ。"""
        _rc, out = self._run("--phase", "3")
        self.assertEqual(self._articles(out), [0, 2])

    def test_generic_profile_reports_unapproved_amendments(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "docs"
            d.mkdir()
            (d / "constitution.md").write_text(
                "## 改正履歴の追認状況\n\n| 改正 | 条 | 日付 | 承認 |\n|---|---|---|---|\n"
                "| (1) | 第2条 | 2026-09-18 | 未承認 |\n", encoding="utf-8")
            p = subprocess.run([sys.executable, self.SCRIPT, "--project-dir", tmp, "--json",
                                "--phase", "3"], capture_output=True, text=True)
            r = [x for x in json.loads(p.stdout) if x["check"] == "amendments_all_approved"]
            self.assertEqual([x["status"] for x in r], ["fail"])

    def test_profile_toolkit_runs_all_articles(self):
        _rc, out = self._run("--phase", "3", "--profile", "toolkit")
        self.assertEqual(self._articles(out), sorted(cc.CHECKS))

    def test_negative_unimplemented_article_is_exit_2_not_ok(self):
        rc, _out = self._run("--phase", "3", "--article", "1")
        self.assertEqual(rc, 2)

    def test_negative_non_integer_phase_is_exit_2(self):
        rc, _out = self._run("--phase", "abc")
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
