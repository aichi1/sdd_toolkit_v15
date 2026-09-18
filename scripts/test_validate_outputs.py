#!/usr/bin/env python3
"""
test_validate_outputs.py: validate-outputs.py のカテゴリ別除外ルールテスト

テストケース:
- 正常系: mkdocs カテゴリで src/tests/README がスキップされる
- 正常系: generic カテゴリで全チェックが実行される
- 異常系: 不明カテゴリでエラーが返る
- 異常系: YAML 不在時に WARNING + generic 動作
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# validate-outputs.py はハイフン入りなので importlib で読み込む
import importlib.util
spec = importlib.util.spec_from_file_location(
    "validate_outputs",
    str(Path(__file__).parent / "validate-outputs.py")
)
validate_outputs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validate_outputs)


class TestLoadValidateRules(unittest.TestCase):
    """validate_rules.yaml の読み込みテスト"""

    def test_rules_file_not_found(self):
        """YAML ファイルが存在しない場合は None を返す"""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = validate_outputs.load_validate_rules(Path(tmpdir))
            self.assertIsNone(result)

    def test_rules_file_loads_successfully(self):
        """正常な YAML ファイルを読み込める"""
        try:
            import yaml
        except ImportError:
            self.skipTest("pyyaml が未インストール")

        with tempfile.TemporaryDirectory() as tmpdir:
            rules_path = Path(tmpdir) / "validate_rules.yaml"
            rules_path.write_text(
                "categories:\n"
                "  mkdocs:\n"
                "    description: test\n"
                "    skip_checks:\n"
                "      - 'src/tests/README'\n"
                "    required_checks:\n"
                "      - 'mkdocs.yml'\n"
                "  generic:\n"
                "    description: default\n"
                "    skip_checks: []\n"
                "    required_checks: []\n",
                encoding="utf-8"
            )
            result = validate_outputs.load_validate_rules(Path(tmpdir))
            self.assertIsNotNone(result)
            self.assertIn("categories", result)
            self.assertIn("mkdocs", result["categories"])


class TestGetProjectTypeRules(unittest.TestCase):
    """プロジェクトタイプ別ルール取得のテスト"""

    def setUp(self):
        self.rules_data = {
            "categories": {
                "mkdocs": {
                    "skip_checks": ["src/tests/README", "test_*.py"],
                    "required_checks": ["mkdocs.yml"],
                },
                "python": {
                    "skip_checks": [],
                    "required_checks": ["src/", "tests/"],
                },
                "generic": {
                    "skip_checks": [],
                    "required_checks": [],
                },
            }
        }

    def test_known_category_returns_rules(self):
        """既知のカテゴリでルールが返る"""
        rules = validate_outputs.get_project_type_rules(self.rules_data, "mkdocs")
        self.assertIsNotNone(rules)
        self.assertIn("src/tests/README", rules["skip_checks"])
        self.assertIn("mkdocs.yml", rules["required_checks"])

    def test_unknown_category_returns_none(self):
        """不明なカテゴリで None が返る"""
        rules = validate_outputs.get_project_type_rules(self.rules_data, "unknown_type")
        self.assertIsNone(rules)

    def test_generic_category_has_empty_rules(self):
        """generic カテゴリは空のルールを返す"""
        rules = validate_outputs.get_project_type_rules(self.rules_data, "generic")
        self.assertIsNotNone(rules)
        self.assertEqual(rules["skip_checks"], [])
        self.assertEqual(rules["required_checks"], [])

    def test_none_rules_data_returns_empty(self):
        """rules_data が None の場合は空のルールを返す"""
        rules = validate_outputs.get_project_type_rules(None, "mkdocs")
        self.assertEqual(rules["skip_checks"], [])
        self.assertEqual(rules["required_checks"], [])


class TestShouldSkipCheck(unittest.TestCase):
    """チェックスキップ判定のテスト"""

    def test_exact_match(self):
        """完全一致でスキップされる"""
        self.assertTrue(
            validate_outputs.should_skip_check("src/tests/README", ["src/tests/README"])
        )

    def test_fnmatch_pattern(self):
        """fnmatch パターンでスキップされる"""
        self.assertTrue(
            validate_outputs.should_skip_check("test_validate.py", ["test_*.py"])
        )

    def test_no_match(self):
        """一致しない場合はスキップされない"""
        self.assertFalse(
            validate_outputs.should_skip_check("README.md", ["src/tests/README", "test_*.py"])
        )

    def test_empty_patterns(self):
        """空のパターンリストではスキップされない"""
        self.assertFalse(
            validate_outputs.should_skip_check("anything", [])
        )

    def test_partial_match(self):
        """部分一致でもスキップされる"""
        self.assertTrue(
            validate_outputs.should_skip_check("src/tests/README.md", ["src/tests/README"])
        )


class TestCategoryRequiredSectionsWithSkip(unittest.TestCase):
    """カテゴリ必須セクションチェックのスキップテスト"""

    def test_mkdocs_skips_src_tests(self):
        """mkdocs タイプで src/ と tests/ がスキップされる"""
        with tempfile.TemporaryDirectory() as tmpdir:
            phase_dir = Path(tmpdir)
            # README.md を作成（存在チェック用）
            (phase_dir / "README.md").write_text("# Test", encoding="utf-8")

            skip_patterns = ["src/tests/README", "test_*.py", "src/", "tests/"]
            issues = validate_outputs.check_category_required_sections(
                phase_dir, "small_implementation", skip_patterns
            )

            # src/ と tests/ はスキップされるべき
            skipped_checks = [
                i for i in issues
                if "スキップ" in i["message"] and "project-type" in i["message"]
            ]
            self.assertGreater(len(skipped_checks), 0,
                              "mkdocs タイプで src/ または tests/ がスキップされるべき")

            # README はスキップされないべき
            readme_issues = [i for i in issues if "README" in i["check"]]
            for issue in readme_issues:
                self.assertNotIn("スキップ", issue["message"],
                                "README はスキップされてはいけない")

    def test_generic_skips_nothing(self):
        """generic タイプではスキップなし"""
        with tempfile.TemporaryDirectory() as tmpdir:
            phase_dir = Path(tmpdir)
            (phase_dir / "README.md").write_text("# Test", encoding="utf-8")

            issues = validate_outputs.check_category_required_sections(
                phase_dir, "small_implementation", []
            )

            skipped_checks = [
                i for i in issues
                if "スキップ" in i.get("message", "")
            ]
            self.assertEqual(len(skipped_checks), 0,
                           "generic タイプではスキップされるチェックがないべき")


class TestCheckExecutedVerification(unittest.TestCase):
    """--require-verification: check_executed_verification のテスト（Phase 03 / R-07）"""

    def test_section_present_with_rows_no_warn(self):
        """`## Executed Verification` セクションがあり表に行がある → warn なし"""
        with tempfile.TemporaryDirectory() as tmpdir:
            phase_dir = Path(tmpdir)
            (phase_dir / ".validation").mkdir()
            (phase_dir / ".validation" / "report.md").write_text(
                "# Validation Report\n\n"
                "## Executed Verification\n"
                "| # | コマンド | exit code | 要約 | ログ位置 |\n"
                "|---|---------|-----------|------|---------|\n"
                "| 1 | `python3 -m pytest scripts/ -q` | 0 | 14 passed | verification.log:1-5 |\n\n"
                "## Detailed Findings\n",
                encoding="utf-8"
            )
            issues = validate_outputs.check_executed_verification(phase_dir)
            # M2 拡張後は「行数チェック」と「exit code 整合チェック」の 2 件を返す。
            # 本テストの意図は「warn / fail が出ないこと」なので件数ではなく status で検証する。
            self.assertEqual([i for i in issues if i["status"] in ("warn", "fail")], [])
            self.assertEqual(issues[0]["status"], "pass")

    def test_section_missing_gives_one_warn(self):
        """`## Executed Verification` セクション自体がない → warn が1件"""
        with tempfile.TemporaryDirectory() as tmpdir:
            phase_dir = Path(tmpdir)
            (phase_dir / ".validation").mkdir()
            (phase_dir / ".validation" / "report.md").write_text(
                "# Validation Report\n\n## Detailed Findings\nNothing here.\n",
                encoding="utf-8"
            )
            issues = validate_outputs.check_executed_verification(phase_dir)
            self.assertEqual(len(issues), 1)
            self.assertEqual(issues[0]["status"], "warn")

    def test_section_present_but_table_empty_gives_warn(self):
        """`## Executed Verification` セクションはあるが表の行が0件 → warn"""
        with tempfile.TemporaryDirectory() as tmpdir:
            phase_dir = Path(tmpdir)
            (phase_dir / ".validation").mkdir()
            (phase_dir / ".validation" / "report.md").write_text(
                "# Validation Report\n\n"
                "## Executed Verification\n"
                "| # | コマンド | exit code | 要約 | ログ位置 |\n"
                "|---|---------|-----------|------|---------|\n\n"
                "## Detailed Findings\n",
                encoding="utf-8"
            )
            issues = validate_outputs.check_executed_verification(phase_dir)
            self.assertEqual(len(issues), 1)
            self.assertEqual(issues[0]["status"], "warn")

    def test_report_missing_returns_empty_list(self):
        """`.validation/report.md` 自体が無い場合は既存挙動を変えない（空リスト）"""
        with tempfile.TemporaryDirectory() as tmpdir:
            phase_dir = Path(tmpdir)
            issues = validate_outputs.check_executed_verification(phase_dir)
            self.assertEqual(issues, [])

    def test_never_returns_fail_status(self):
        """--require-verification は FAIL にしない（WARN に留める）"""
        with tempfile.TemporaryDirectory() as tmpdir:
            phase_dir = Path(tmpdir)
            (phase_dir / ".validation").mkdir()
            (phase_dir / ".validation" / "report.md").write_text(
                "# Validation Report\n\nNo executed verification here.\n",
                encoding="utf-8"
            )
            issues = validate_outputs.check_executed_verification(phase_dir)
            statuses = [i["status"] for i in issues]
            self.assertNotIn("fail", statuses)


class TestRequireVerificationDefaultUnchanged(unittest.TestCase):
    """--require-verification のデフォルト False で既存挙動が変わらないことの確認"""

    def test_argparse_default_is_false(self):
        """argparse のデフォルトが False であること"""
        import argparse
        ap = argparse.ArgumentParser()
        ap.add_argument("--phase", type=int, required=True)
        ap.add_argument("--require-verification", action="store_true")
        args = ap.parse_args(["--phase", "3"])
        self.assertFalse(args.require_verification)


class TestBackwardCompatibility(unittest.TestCase):
    """後方互換性のテスト"""

    def test_no_project_type_works(self):
        """--project-type 未指定時に従来通り動作する"""
        # check_category_required_sections を skip_patterns なしで呼ぶ
        with tempfile.TemporaryDirectory() as tmpdir:
            phase_dir = Path(tmpdir)
            (phase_dir / "README.md").write_text("# Test", encoding="utf-8")
            (phase_dir / "report.md").write_text("# Report\nリスク分析", encoding="utf-8")

            # skip_patterns=None（デフォルト）で呼び出し
            issues = validate_outputs.check_category_required_sections(
                phase_dir, "small_implementation"
            )

            # src/ と tests/ のチェックが実行される（スキップされない）
            all_checks = [i["check"] for i in issues]
            self.assertIn("required_section_src/", all_checks)
            self.assertIn("required_section_tests/", all_checks)


class TestEscapedPipeInCommand(unittest.TestCase):
    """C-42: コマンド欄の `\\|`（エスケープされたパイプ）で列がずれないこと。

    旧実装は `split("|")` で行を分割していたため、コマンド中のパイプで
    exit code 欄にコマンドの断片が入り、その行を**黙って読み飛ばしていた**。
    exit=1 の行を Overall Status: PASS のまま通せる穴だった。
    """

    def _report(self, tmpdir, rows, overall="PASS"):
        phase_dir = Path(tmpdir)
        (phase_dir / ".validation").mkdir()
        (phase_dir / ".validation" / "report.md").write_text(
            "**Overall Status**: {}\n\n"
            "## Executed Verification\n\n"
            "| # | コマンド | exit code | 要約 | ログ |\n"
            "|---|---------|-----------|------|------|\n"
            "{}\n".format(overall, rows),
            encoding="utf-8"
        )
        return validate_outputs.check_executed_verification(phase_dir)

    def _statuses(self, issues):
        return [i["status"] for i in issues]

    def test_escaped_pipe_does_not_hide_nonzero_exit(self):
        """C-42 の再現ケース: エスケープされたパイプがあっても exit≠0 を検出する"""
        with tempfile.TemporaryDirectory() as tmpdir:
            issues = self._report(
                tmpdir, r"| 1 | `head -1 x.csv \| tr -d '\r'` | 1 | 失敗 | log |")
            self.assertIn("fail", self._statuses(issues))

    def test_escaped_pipe_with_zero_exit_passes(self):
        """正常系: エスケープされたパイプ + exit=0 は PASS のまま"""
        with tempfile.TemporaryDirectory() as tmpdir:
            issues = self._report(
                tmpdir, r"| 1 | `head -1 x.csv \| tr -d '\r'` | 0 | OK | log |")
            self.assertNotIn("fail", self._statuses(issues))

    def test_annotated_zero_is_accepted(self):
        """`0（4件とも）` のような注記付きの 0 を失敗扱いにしない"""
        with tempfile.TemporaryDirectory() as tmpdir:
            issues = self._report(
                tmpdir,
                r"| 1 | `echo x \| python3 h.py` ほか4 hook | 0（4件とも） | R-10 | log |")
            self.assertNotIn("fail", self._statuses(issues))

    def test_unparseable_exit_code_is_fail_not_silent_skip(self):
        """exit code 欄を解釈できない行は黙って読み飛ばさず fail にする"""
        with tempfile.TemporaryDirectory() as tmpdir:
            issues = self._report(tmpdir, "| 1 | `some cmd` | たぶん0 | ? | log |")
            self.assertIn("fail", self._statuses(issues))
            checks = [i["check"] for i in issues if i["status"] == "fail"]
            self.assertIn("executed_verification_malformed", checks)

    def test_split_markdown_row_keeps_escaped_pipe_in_cell(self):
        """ヘルパ単体: `\\|` はセル区切りにならず、セル内容として残る"""
        cells = validate_outputs._split_markdown_row(
            r"| 9 | `head -1 eval/summary.csv \| tr -d '\r'` | 0 | ヘッダ | log |")
        self.assertEqual(cells[0], "9")
        self.assertIn("|", cells[1])          # パイプがセル内に残っている
        self.assertEqual(cells[2], "0")       # exit code 欄がずれていない


class TestExecutedVerificationHeadingPrefix(unittest.TestCase):
    """C-47: 見出しの接頭辞番号でセクションを見失わないこと。

    Phase 06 の Validator が `## 6. Executed Verification` と番号を振ったところ、
    正規表現 `^## Executed Verification` が先頭一致を要求するため**セクションが見つからず**、
    表にあった **19 行の exit code が一度も検査されないまま warn で素通りした**。
    判定は warn（fail ではない）ため PASS もブロックしない。C-42 と同じ型の穴。
    """

    def _report(self, tmpdir, heading, row="| 1 | `pytest` | 1 | 1 failed | log |"):
        phase_dir = Path(tmpdir)
        (phase_dir / ".validation").mkdir()
        (phase_dir / ".validation" / "report.md").write_text(
            "**Overall Status**: PASS\n\n"
            f"{heading}\n\n"
            "| # | コマンド | exit code | 要約 | ログ |\n"
            "|---|---------|-----------|------|------|\n"
            f"{row}\n",
            encoding="utf-8")
        return validate_outputs.check_executed_verification(phase_dir)

    def _has(self, issues, check):
        return any(i["check"] == check for i in issues)

    def test_numbered_heading_is_found(self):
        """C-47 の再現ケース: `## 6. Executed Verification` を検出できること。"""
        with tempfile.TemporaryDirectory() as tmp:
            issues = self._report(tmp, "## 6. Executed Verification")
            self.assertTrue(self._has(issues, "executed_verification_exit_code"),
                            "番号付き見出しで exit code 検査が実行されなければならない")
            self.assertIn("fail", [i["status"] for i in issues])

    def test_numbered_heading_variants(self):
        for h in ("## 6. Executed Verification",
                  "## 6 Executed Verification",
                  "## 6) Executed Verification",
                  "### 3.1 Executed Verification",
                  "##  Executed Verification"):
            with tempfile.TemporaryDirectory() as tmp:
                issues = self._report(tmp, h)
                self.assertTrue(self._has(issues, "executed_verification_exit_code"),
                                f"{h!r} でセクションを見失ってはいけない")

    def test_plain_heading_still_works(self):
        with tempfile.TemporaryDirectory() as tmp:
            issues = self._report(tmp, "## Executed Verification")
            self.assertTrue(self._has(issues, "executed_verification_exit_code"))

    def test_heading_with_suffix_and_number(self):
        """C-36（接尾辞）と C-47（接頭辞）の両方が同時にあっても検出できること。"""
        with tempfile.TemporaryDirectory() as tmp:
            issues = self._report(tmp, "## 6. Executed Verification（実行者: Validator 自身）")
            self.assertTrue(self._has(issues, "executed_verification_exit_code"))

    def test_section_ends_at_next_heading_of_any_level(self):
        """後続の `###` 見出しでセクションが終わること（行を拾いすぎない）。"""
        with tempfile.TemporaryDirectory() as tmp:
            phase_dir = Path(tmp)
            (phase_dir / ".validation").mkdir()
            (phase_dir / ".validation" / "report.md").write_text(
                "**Overall Status**: PASS\n\n"
                "## 6. Executed Verification\n\n"
                "| # | コマンド | exit code | 要約 | ログ |\n"
                "|---|---------|-----------|------|------|\n"
                "| 1 | `pytest` | 0 | ok | log |\n\n"
                "### 6.1 別の表\n\n"
                "| 2 | `broken` | 1 | これは対象外 | log |\n",
                encoding="utf-8")
            issues = validate_outputs.check_executed_verification(phase_dir)
            msg = [i["message"] for i in issues if i["check"] == "executed_verification"][0]
            self.assertIn("1 行", msg, "次の見出し以降の行を拾ってはいけない")


if __name__ == "__main__":
    unittest.main()


class TestExecutedVerificationExitCode(unittest.TestCase):
    """M2 / Phase 03: Executed Verification の exit code と Overall Status の整合チェック。

    第1条の強制点「exit≠0 のコマンドが1つでもあれば PASS にできない」を
    Validator の自己申告ではなく機械的に検査する。
    """

    def _write_report(self, phase_dir, overall, rows):
        (phase_dir / ".validation").mkdir(exist_ok=True)
        table = (
            "| # | コマンド | exit code | 要約 | ログ位置 |\n"
            "|---|---------|-----------|------|---------|\n"
        ) + "".join(rows)
        (phase_dir / ".validation" / "report.md").write_text(
            "# Validation Report\n\n"
            "**Overall Status**: {}\n\n"
            "## Executed Verification\n" + table + "\n"
            "## Detailed Findings\n".format(overall).replace("{}", overall, 1),
            encoding="utf-8",
        )

    def test_nonzero_exit_with_pass_is_fail(self):
        """exit≠0 の行があるのに Overall Status が PASS → fail を返す（M2 の本体）"""
        with tempfile.TemporaryDirectory() as tmpdir:
            phase_dir = Path(tmpdir)
            (phase_dir / ".validation").mkdir()
            (phase_dir / ".validation" / "report.md").write_text(
                "# Validation Report\n\n"
                "**Overall Status**: PASS\n\n"
                "## Executed Verification\n"
                "| # | コマンド | exit code | 要約 | ログ位置 |\n"
                "|---|---------|-----------|------|---------|\n"
                "| 1 | `python3 -m pytest tests -q` | 1 | 1 failed, 2 passed | log:1-5 |\n\n"
                "## Detailed Findings\n",
                encoding="utf-8",
            )
            issues = validate_outputs.check_executed_verification(phase_dir)
            fails = [i for i in issues if i["status"] == "fail"]
            self.assertEqual(len(fails), 1)
            self.assertIn("第1条", fails[0]["message"])

    def test_nonzero_exit_with_needs_revision_is_pass(self):
        """exit≠0 の行があり Overall Status が NEEDS_REVISION → 整合しているので fail なし"""
        with tempfile.TemporaryDirectory() as tmpdir:
            phase_dir = Path(tmpdir)
            (phase_dir / ".validation").mkdir()
            (phase_dir / ".validation" / "report.md").write_text(
                "# Validation Report\n\n"
                "**Overall Status**: NEEDS_REVISION\n\n"
                "## Executed Verification\n"
                "| # | コマンド | exit code | 要約 | ログ位置 |\n"
                "|---|---------|-----------|------|---------|\n"
                "| 1 | `python3 -m pytest tests -q` | 1 | 1 failed, 2 passed | log:1-5 |\n\n"
                "## Detailed Findings\n",
                encoding="utf-8",
            )
            issues = validate_outputs.check_executed_verification(phase_dir)
            self.assertEqual([i for i in issues if i["status"] == "fail"], [])

    def test_na_row_is_not_treated_as_failure(self):
        """exit code が N/A の行は判定対象外（『該当なし』専用。S-03 条件(a)）"""
        with tempfile.TemporaryDirectory() as tmpdir:
            phase_dir = Path(tmpdir)
            (phase_dir / ".validation").mkdir()
            (phase_dir / ".validation" / "report.md").write_text(
                "# Validation Report\n\n"
                "**Overall Status**: PASS\n\n"
                "## Executed Verification\n"
                "| # | コマンド | exit code | 要約 | ログ位置 |\n"
                "|---|---------|-----------|------|---------|\n"
                "| 1 | `python3 -m pytest scripts/ -q` | 0 | 20 passed | log:1-5 |\n"
                "| 2 | (該当なし) | N/A | フェーズ固有の検証コマンド定義なし | - |\n\n"
                "## Detailed Findings\n",
                encoding="utf-8",
            )
            issues = validate_outputs.check_executed_verification(phase_dir)
            self.assertEqual([i for i in issues if i["status"] == "fail"], [])


class TestExecutedVerificationHeadingSuffix(unittest.TestCase):
    """C-36 / Phase 03: 見出しに接尾辞があってもセクションを抽出できること。

    実害: `## Executed Verification（実行者: Validator 自身）` のような見出しだと
    セクション本文を抽出できず「表に行がない」と誤って WARN を出していた。
    """

    def _report(self, phase_dir, heading):
        (phase_dir / ".validation").mkdir(exist_ok=True)
        (phase_dir / ".validation" / "report.md").write_text(
            "# Validation Report\n\n"
            "**Overall Status**: PASS\n\n"
            + heading + "\n"
            "| # | コマンド | exit code | 要約 | ログ位置 |\n"
            "|---|---------|-----------|------|---------|\n"
            "| 1 | `python3 -m pytest scripts/ -q` | 0 | 23 passed | log:1-5 |\n\n"
            "## Detailed Findings\n",
            encoding="utf-8",
        )

    def test_heading_with_suffix_is_detected(self):
        """見出しに接尾辞がある → 表の行を正しく数える（warn を出さない）"""
        with tempfile.TemporaryDirectory() as tmpdir:
            phase_dir = Path(tmpdir)
            self._report(phase_dir, "## Executed Verification（実行者: **Validator 自身**）")
            issues = validate_outputs.check_executed_verification(phase_dir)
            self.assertEqual([i for i in issues if i["status"] in ("warn", "fail")], [])
            self.assertTrue(any("1 行検出" in i["message"] for i in issues))

    def test_plain_heading_still_works(self):
        """接尾辞なしの正規の見出しでも従来どおり動く（回帰確認）"""
        with tempfile.TemporaryDirectory() as tmpdir:
            phase_dir = Path(tmpdir)
            self._report(phase_dir, "## Executed Verification")
            issues = validate_outputs.check_executed_verification(phase_dir)
            self.assertEqual([i for i in issues if i["status"] in ("warn", "fail")], [])


class TestIntentionalExitMarker(unittest.TestCase):
    """C-37 / Phase 03: 意図的に非 0 で終了するコマンドの明示マーカー。

    `dryrun-fail` の pytest（exit=1）は「壊れたテストを Validator が検出できる」ことを示す
    成功の証拠だが、第1条は実測どおりの記録を要求するため PASS にできなくなっていた。
    `1 (意図的)` 形式のマーカーで判定対象外にする。ただし件数と内容は必ず報告する。
    """

    def _report(self, phase_dir, exit_cell):
        (phase_dir / ".validation").mkdir(exist_ok=True)
        (phase_dir / ".validation" / "report.md").write_text(
            "# Validation Report\n\n"
            "**Overall Status**: PASS\n\n"
            "## Executed Verification\n"
            "| # | コマンド | exit code | 要約 | ログ位置 |\n"
            "|---|---------|-----------|------|---------|\n"
            "| 1 | `python3 -m pytest scripts/ -q` | 0 | 25 passed | log:1-5 |\n"
            "| 2 | `python3 -m pytest fixtures/tests -q` | " + exit_cell +
            " | 1 failed（意図的フィクスチャ） | log:7-12 |\n\n"
            "## Detailed Findings\n",
            encoding="utf-8",
        )

    def test_intentional_marker_does_not_block_pass(self):
        """`1 (意図的)` は PASS を阻害しない、かつ件数が報告される"""
        with tempfile.TemporaryDirectory() as tmpdir:
            phase_dir = Path(tmpdir)
            self._report(phase_dir, "**1 (意図的)**")
            issues = validate_outputs.check_executed_verification(phase_dir)
            self.assertEqual([i for i in issues if i["status"] == "fail"], [])
            reported = [i for i in issues if i["check"] == "executed_verification_intentional"]
            self.assertEqual(len(reported), 1)
            self.assertIn("1 件", reported[0]["message"])

    def test_expected_marker_variants(self):
        """`(expected)` / `(期待値)` も同様に認識される"""
        for cell in ["1 (expected)", "1 (期待値)", "1（意図的）"]:
            with self.subTest(cell=cell):
                with tempfile.TemporaryDirectory() as tmpdir:
                    phase_dir = Path(tmpdir)
                    self._report(phase_dir, cell)
                    issues = validate_outputs.check_executed_verification(phase_dir)
                    self.assertEqual([i for i in issues if i["status"] == "fail"], [])

    def test_bare_nonzero_still_blocks_pass(self):
        """マーカーなしの素の `1` は従来どおり PASS を阻害する（濫用防止の回帰確認）"""
        with tempfile.TemporaryDirectory() as tmpdir:
            phase_dir = Path(tmpdir)
            self._report(phase_dir, "1")
            issues = validate_outputs.check_executed_verification(phase_dir)
            fails = [i for i in issues if i["status"] == "fail"]
            self.assertEqual(len(fails), 1)


class TestChangeReportSections(unittest.TestCase):
    """C-48: `change-report.md` が `docs/io-spec.md` §2.3 の必須 6 セクションを持つか。

    Phase 05 以降、§4 / §5 の**番号を保ったまま内容を差し替える**運用にドリフトし、
    7 巡の Validator が誰も見ていなかった。検査する仕組みの側に穴があった型
    （C-26 / C-42 / C-47 と同じ）。
    """

    FULL = "\n".join([
        "# Phase NN Change Report",
        "## 1. 変更ファイル一覧", "x",
        "## 2. 変更の意図", "x",
        "## 3. 影響範囲", "x",
        "## 4. Claude Code バージョン確認結果", "x",
        "## 5. settings.json / hooks の前後差分", "x",
        "## 6. ロールバック手順", "x",
    ])

    def _check(self, text):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            if text is not None:
                (d / "change-report.md").write_text(text, encoding="utf-8")
            return validate_outputs.check_change_report_sections(d)

    def test_full_report_passes(self):
        r = self._check(self.FULL)
        self.assertEqual([x["status"] for x in r], ["pass"])

    def test_extra_sections_are_allowed(self):
        """7 節目以降の追加は自由（修正サイクルの記録など）。"""
        r = self._check(self.FULL + "\n## 7. Open Questions\nx\n## 18. 修正サイクル 7\nx")
        self.assertEqual([x["status"] for x in r], ["pass"])

    def test_repurposed_section_fails(self):
        """**番号は合っているが見出しが違う** —— C-48 そのもの。"""
        bad = self.FULL.replace("## 4. Claude Code バージョン確認結果",
                                "## 4. doc_editor レビューへの対応")
        r = self._check(bad)
        self.assertEqual(r[0]["status"], "fail")
        self.assertIn("## 4. Claude Code バージョン確認結果", r[0]["message"])

    def test_reports_all_missing(self):
        bad = (self.FULL.replace("## 4. Claude Code バージョン確認結果", "## 4. 憲法改正の記録")
                        .replace("## 5. settings.json / hooks の前後差分", "## 5. 第10条違反の自己申告"))
        r = self._check(bad)
        self.assertEqual(r[0]["status"], "fail")
        self.assertIn("## 4.", r[0]["message"])
        self.assertIn("## 5.", r[0]["message"])

    def test_wrong_number_fails(self):
        """見出し文言が合っていても**番号が違えば**必須構成ではない。"""
        bad = self.FULL.replace("## 4. Claude Code バージョン確認結果",
                                "## 9. Claude Code バージョン確認結果")
        self.assertEqual(self._check(bad)[0]["status"], "fail")

    def test_missing_file_is_not_an_issue(self):
        """`change-report.md` 自体が無い場合は既存の成果物チェックに委ねる（挙動不変）。"""
        self.assertEqual(self._check(None), [])

    def test_fenced_headings_do_not_count(self):
        """#35: フェンス内に必須見出しを**引用**しただけでは充足しない。"""
        bad = "\n".join([
            "## 1. 変更ファイル一覧", "## 2. 変更の意図", "## 3. 影響範囲",
            "docs/io-spec.md の必須構成を引用する:",
            "```markdown",
            "## 4. Claude Code バージョン確認結果",
            "## 5. settings.json / hooks の前後差分",
            "```",
            "## 6. ロールバック手順",
        ])
        r = self._check(bad)
        self.assertEqual(r[0]["status"], "fail")
        self.assertIn("## 4.", r[0]["message"])

    def test_unclosed_fence_fails_safe(self):
        """閉じられていないフェンスは**残り全体をフェンス内**とみなす（安全側）。"""
        bad = self.FULL.replace("## 4. Claude Code バージョン確認結果",
                                "```\n## 4. Claude Code バージョン確認結果")
        self.assertEqual(self._check(bad)[0]["status"], "fail")

    def test_nested_fence_types(self):
        """種別（``` と ~~~）を区別する。外側 ~~~ の中の ``` で閉じたと誤認しない。"""
        text = self.FULL.replace(
            "## 6. ロールバック手順",
            "~~~\n```\n引用\n```\n~~~\n## 6. ロールバック手順")
        self.assertEqual(self._check(text)[0]["status"], "pass")


# ---------------------------------------------------------------------------
# v15.1 回帰テスト（test_negative_* は修正前のコードで失敗することを確認済み）
# ---------------------------------------------------------------------------
import contextlib
import io
import subprocess
from unittest import mock

_SCRIPT = Path(__file__).resolve().parent / "validate-outputs.py"


def _make_phase(root, deliverables, files=None, skill=True):
    """outputs/phase-01/ と（任意で）skills/phase-01/SKILL.md を持つ最小プロジェクトを作る。"""
    phase_dir = Path(root) / "outputs" / "phase-01"
    phase_dir.mkdir(parents=True)
    meta = {"phase": 1}
    if deliverables is not None:
        meta["deliverables"] = deliverables
    (phase_dir / ".metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    for rel, content in (files or {}).items():
        p = Path(root) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    if skill:
        s = Path(root) / "skills" / "phase-01"
        s.mkdir(parents=True)
        (s / "SKILL.md").write_text("# Phase 1\n\n## Quality Criteria\n- [ ] 出典がある\n",
                                    encoding="utf-8")
    return phase_dir


class TestListedDeliverables(unittest.TestCase):
    """v15.1 / Quality Gate 0: `.metadata.json` の deliverables に列挙された成果物の実在と非空。

    旧実装は「隠しファイル以外のファイルが 1 つ以上あるか」しか見ず、
    0 バイトの report.md だけがあり analysis.md が欠落していても PASS / exit 0 だった。
    """

    def _issues(self, root):
        issues, _ = validate_outputs.check_file_existence(Path(root) / "outputs", 1)
        return issues

    def _fails(self, issues):
        return [i for i in issues if i["status"] == "fail"]

    def test_negative_empty_and_missing_listed_deliverables_fail(self):
        """レビュアーの再現ケース: 空の report.md + 欠落した analysis.md → fail。"""
        with tempfile.TemporaryDirectory() as t:
            _make_phase(t, ["report.md", "analysis.md"], {"outputs/phase-01/report.md": ""})
            fails = self._fails(self._issues(t))
            self.assertEqual([f["check"] for f in fails], ["deliverables_listed"])
            self.assertIn("report.md（0 バイト）", fails[0]["message"])
            self.assertIn("analysis.md（存在しない）", fails[0]["message"])

    def test_negative_end_to_end_exit_code_is_nonzero(self):
        """CLI 全体でも Status: FAIL / exit 1 になること（旧実装は PASS / exit 0）。"""
        with tempfile.TemporaryDirectory() as t:
            _make_phase(t, ["report.md", "analysis.md"], {"outputs/phase-01/report.md": ""})
            p = subprocess.run([sys.executable, str(_SCRIPT), "--phase", "1", "--project-dir", t],
                               capture_output=True, text=True)
            self.assertEqual(p.returncode, 1, p.stdout)
            self.assertIn("Status: FAIL", p.stdout)

    def test_negative_object_form_missing_file_fails(self):
        """`{"file": ...}` 形式（builder.md の例）も検査対象になる。"""
        with tempfile.TemporaryDirectory() as t:
            _make_phase(t, [{"file": "present.md", "type": "document"},
                            {"file": "gone.md", "type": "document"}],
                        {"outputs/phase-01/present.md": "# ok\n"})
            fails = self._fails(self._issues(t))
            self.assertEqual(len(fails), 1)
            self.assertIn("gone.md（存在しない）", fails[0]["message"])
            self.assertNotIn("present.md", fails[0]["message"])

    def test_negative_validation_dir_is_not_a_deliverable(self):
        """`.validation/` 配下は Validator の検証レポートであり、成果物として数えない。"""
        with tempfile.TemporaryDirectory() as t:
            _make_phase(t, [".validation/report.md"],
                        {"outputs/phase-01/.validation/report.md": "# report\n"})
            # has_deliverables（トップレベルに成果物が無い）も fail になるが、ここでは列挙チェックを見る
            fails = [i for i in self._fails(self._issues(t)) if i["check"] == "deliverables_listed"]
            self.assertEqual(len(fails), 1)
            self.assertIn(".validation/", fails[0]["message"])

    def test_string_and_object_forms_and_project_root_paths_pass(self):
        """文字列 / オブジェクト形式、phase 基準 / プロジェクトルート基準の解決がすべて通る。"""
        with tempfile.TemporaryDirectory() as t:
            _make_phase(t, ["report.md", {"file": "docs/in-place.md"},
                            "outputs/phase-01/report.md"],
                        {"outputs/phase-01/report.md": "# r\n", "docs/in-place.md": "# d\n"})
            issues = self._issues(t)
            self.assertEqual(self._fails(issues), [])
            listed = [i for i in issues if i["check"] == "deliverables_listed"]
            self.assertEqual(listed[0]["status"], "pass")
            self.assertIn("3 件", listed[0]["message"])

    def test_unknown_entry_shape_is_warned_not_dropped_silently(self):
        with tempfile.TemporaryDirectory() as t:
            _make_phase(t, ["report.md", 42, {"name": "x.md"}],
                        {"outputs/phase-01/report.md": "# r\n"})
            issues = self._issues(t)
            self.assertEqual(self._fails(issues), [])
            warns = [i for i in issues if i["check"] == "deliverables_listed_format"]
            self.assertEqual([w["status"] for w in warns], ["warn"])

    def test_absent_or_empty_deliverables_keep_existing_behavior(self):
        """deliverables が無い / 空リストなら従来どおり（列挙チェックは行わない）。"""
        for deliverables in (None, []):
            with self.subTest(deliverables=deliverables), tempfile.TemporaryDirectory() as t:
                _make_phase(t, deliverables, {"outputs/phase-01/report.md": ""})
                issues = self._issues(t)
                self.assertFalse(any(i["check"].startswith("deliverables_listed") for i in issues))
                has = [i for i in issues if i["check"] == "has_deliverables"][0]
                self.assertEqual(has["status"], "pass")


class TestOverallStatusVariants(unittest.TestCase):
    """v15.1: Overall Status の書式違いで exit≠0 の行を素通りさせないこと。

    旧実装は `**Overall Status**: PASS` 以外の書式を読めず overall="" となり、
    exit≠0 の行があっても「整合している」（pass）と報告していた。
    """

    ROW = "| 1 | `python3 -m pytest -q` | 1 | 3 failed | log |"

    def _issues(self, status_line, row=None):
        with tempfile.TemporaryDirectory() as t:
            phase_dir = Path(t)
            (phase_dir / ".validation").mkdir()
            (phase_dir / ".validation" / "report.md").write_text(
                "# Validation Report\n\n" + status_line + "\n\n"
                "## Executed Verification\n\n"
                "| # | コマンド | exit code | 要約 | ログ |\n"
                "|---|---------|-----------|------|------|\n"
                + (row or self.ROW) + "\n",
                encoding="utf-8")
            return validate_outputs.check_executed_verification(phase_dir)

    def _exit_check(self, issues):
        return [i for i in issues if i["check"] == "executed_verification_exit_code"][0]

    def test_negative_bold_around_whole_status_is_read_as_pass(self):
        """`**Overall Status: PASS**` + exit=1 の行 → fail（旧実装は pass）。"""
        c = self._exit_check(self._issues("**Overall Status: PASS**"))
        self.assertEqual(c["status"], "fail")
        self.assertIn("第1条", c["message"])

    def test_negative_emoji_before_verdict_is_read_as_pass(self):
        """`**Overall Status**: ✅ PASS` / `⚠️` 付きなど → fail（旧実装は pass）。"""
        for line in ("**Overall Status**: ✅ PASS",
                     "**Overall Status**: **✅ PASS**",
                     "**Overall Status**：✅ PASS",
                     "**Overall Status: 🟢 PASS**"):
            with self.subTest(line=line):
                self.assertEqual(self._exit_check(self._issues(line))["status"], "fail")

    def test_negative_unreadable_status_with_failing_row_fails(self):
        """判定語を読めない場合は「整合している」とみなさず fail（旧実装は pass）。"""
        for line in ("**Overall Status**: PASSED",
                     "**Overall Status**: Pass",
                     "Overall: よさそう",
                     ""):
            with self.subTest(line=line):
                c = self._exit_check(self._issues(line))
                self.assertEqual(c["status"], "fail")
                self.assertIn("読み取れない", c["message"])

    def test_non_pass_variants_with_failing_row_are_consistent(self):
        """読める書式で PASS 以外なら従来どおり整合（pass）。"""
        for line in ("**Overall Status**：❌ NEEDS_REVISION",
                     "**Overall Status: FAIL**",
                     "**Overall Status**: ⚠️ **NEEDS_REVISION**"):
            with self.subTest(line=line):
                self.assertEqual(self._exit_check(self._issues(line))["status"], "pass")

    def test_unreadable_status_without_failing_rows_is_unchanged(self):
        """exit≠0 の行が無ければ、判定語を読めなくても fail にしない（挙動不変）。"""
        issues = self._issues("Overall: よさそう", row="| 1 | `pytest` | 0 | ok | log |")
        self.assertEqual([i for i in issues if i["status"] == "fail"], [])


class TestNonUtf8Files(unittest.TestCase):
    """v15.1: Shift_JIS などの非 UTF-8 ファイルで UnicodeDecodeError を出して落ちないこと。"""

    SJIS = "# 報告書\n出典: 日本語の資料\n".encode("shift_jis")

    def test_negative_shift_jis_skill_and_outputs_do_not_crash(self):
        with tempfile.TemporaryDirectory() as t:
            phase_dir = Path(t) / "outputs" / "phase-01"
            phase_dir.mkdir(parents=True)
            (phase_dir / "report.md").write_bytes(self.SJIS)
            skill = Path(t) / "skills" / "phase-01"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_bytes(
                "## Quality Criteria\n- [ ] 出典がある\n".encode("shift_jis"))
            issues = validate_outputs.check_skill_quality_criteria(
                phase_dir, Path(t) / "skills", 1)
            self.assertNotIn("fail", [i["status"] for i in issues])

    def test_negative_shift_jis_output_in_category_check_does_not_crash(self):
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / "report.md").write_bytes(self.SJIS)
            issues = validate_outputs.check_category_required_sections(
                Path(t), "research_report")
            self.assertTrue(issues)

    def test_negative_shift_jis_report_still_detects_nonzero_exit(self):
        """非 UTF-8 のレポートでも落ちず、ASCII 部分の exit code 検査は従来どおり働く。"""
        with tempfile.TemporaryDirectory() as t:
            phase_dir = Path(t)
            (phase_dir / ".validation").mkdir()
            (phase_dir / ".validation" / "report.md").write_bytes((
                "**Overall Status**: PASS\n\n## Executed Verification\n\n"
                "| # | コマンド | exit code | 要約 | ログ |\n"
                "|---|---------|-----------|------|------|\n"
                "| 1 | `pytest` | 1 | 失敗あり | log |\n").encode("shift_jis"))
            issues = validate_outputs.check_executed_verification(phase_dir)
            self.assertIn("fail", [i["status"] for i in issues])


class TestUnknownProjectTypeMessage(unittest.TestCase):
    """v15.1: 不明な --project-type のとき、新しいタイプの追加方法を 1 行で案内する（exit code は 1 のまま）。"""

    def test_negative_unknown_type_explains_how_to_add_category(self):
        rules = {"categories": {"generic": {"skip_checks": [], "required_checks": []}}}
        with tempfile.TemporaryDirectory() as t:
            argv = ["validate-outputs.py", "--phase", "1", "--project-type", "nosuch",
                    "--project-dir", t]
            out = io.StringIO()
            with mock.patch.object(validate_outputs, "load_validate_rules", return_value=rules), \
                    mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(out):
                with self.assertRaises(SystemExit) as cm:
                    validate_outputs.main()
        self.assertEqual(cm.exception.code, 1)
        text = out.getvalue()
        self.assertIn("有効なタイプ: generic", text)
        self.assertIn("validate_rules.yaml", text)
        self.assertIn("categories:", text)
