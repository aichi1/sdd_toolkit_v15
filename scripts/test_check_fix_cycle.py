#!/usr/bin/env python3
"""
test_check_fix_cycle.py: check_fix_cycle.py の回帰テスト（C-50 / C-51 / R-30 / R-31）

**負のテストを重視する。** 本フェーズ（Phase 12）は「検査する側」を直すため、
検査機構を変える以上、負のテストなしに出さない（`skills/phase-12/SKILL.md`）。

`outputs/phase-07/.validation/` の 11 巡の実データを参考に、Phase 07 クロージング時の
診断（「Builder が 8 回連続で Accept を提示しなかった」）を模した合成フィクスチャを使う。
"""
import json
import tempfile
import unittest
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "check_fix_cycle", str(Path(__file__).parent / "check_fix_cycle.py")
)
cfc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cfc)


def _statuses(results, check):
    return [r["status"] for r in results if r["check"] == check]


# ---------------------------------------------------------------- R-30
class TestCutoffRule(unittest.TestCase):
    """R-30 / C-51: revision_history が 3 巡以上かつ未 pass のとき owner_decision を要求する。"""

    def test_metadata_missing_is_skip(self):
        r = cfc.check_cutoff_rule(None)
        self.assertEqual(_statuses(r, "fix_cycle_cutoff"), ["skip"])

    def test_no_revision_history_passes(self):
        r = cfc.check_cutoff_rule({"validation_status": "pending_validation"})
        self.assertEqual(_statuses(r, "fix_cycle_cutoff"), ["pass"])

    def test_two_cycles_is_below_threshold_and_passes(self):
        """3 巡未満は打ち切り規則の対象外。"""
        md = {
            "validation_status": "NEEDS_REVISION",
            "revision_history": [{"cycle": 1}, {"cycle": 2}],
        }
        r = cfc.check_cutoff_rule(md)
        self.assertEqual(_statuses(r, "fix_cycle_cutoff"), ["pass"])

    def test_negative_three_cycles_unresolved_without_owner_decision_fails(self):
        """**負のテスト**: Phase 07 クロージング診断の再現。

        3 巡以上・未 pass なのに owner_decision が無ければ fail する。
        （実際の Phase 07 は cycle 3 で owner_decision を記録したが、cycle 4〜11 では
        一度も再提示しなかった——その「未提示のまま巡を重ねた」状態を模す）
        """
        md = {
            "validation_status": "NEEDS_REVISION",
            "revision_history": [
                {"cycle": 1, "critical_issues_fixed": ["#1", "#2", "#3"]},
                {"cycle": 2, "critical_issues_fixed": ["#4", "#5", "#6", "#7"]},
                {"cycle": 3, "owner_decision": "(a) 許可リスト方式に切り替える"},
                {"cycle": 4, "critical_issues_fixed": ["#11"]},
            ],
        }
        r = cfc.check_cutoff_rule(md)
        self.assertEqual(_statuses(r, "fix_cycle_cutoff"), ["fail"])

    def test_positive_three_cycles_unresolved_with_owner_decision_on_last_passes(self):
        """**正例**: 最後の要素に owner_decision があれば pass。"""
        md = {
            "validation_status": "NEEDS_REVISION",
            "revision_history": [
                {"cycle": 1}, {"cycle": 2},
                {"cycle": 3, "owner_decision": "(c) 許可リスト方式 + 外部再実行を必須化する"},
            ],
        }
        r = cfc.check_cutoff_rule(md)
        self.assertEqual(_statuses(r, "fix_cycle_cutoff"), ["pass"])

    def test_owner_decision_present_only_on_earlier_cycle_still_fails(self):
        """cycle 3 に owner_decision があっても、以降の巡（最後の要素）に無ければ fail のまま。"""
        md = {
            "validation_status": "NEEDS_REVISION",
            "revision_history": [
                {"cycle": 1}, {"cycle": 2},
                {"cycle": 3, "owner_decision": "(a) 許可リスト方式に切り替える"},
                {"cycle": 4}, {"cycle": 5}, {"cycle": 6},
            ],
        }
        r = cfc.check_cutoff_rule(md)
        self.assertEqual(_statuses(r, "fix_cycle_cutoff"), ["fail"])

    def test_blank_owner_decision_is_invalid(self):
        """**負のテスト**: 空文字列・空白のみの owner_decision は無効（C-42 と同型）。"""
        md = {
            "validation_status": "NEEDS_REVISION",
            "revision_history": [{"cycle": 1}, {"cycle": 2}, {"cycle": 3, "owner_decision": "   "}],
        }
        r = cfc.check_cutoff_rule(md)
        self.assertEqual(_statuses(r, "fix_cycle_cutoff"), ["fail"])

    def test_final_pass_status_is_exempt_even_with_many_unresolved_cycles(self):
        """**過去フェーズを遡及判定しても、最終的に pass していれば違反にしない**。

        完了済みフェーズ（`validation_status == "pass"`）は、途中の巡に owner_decision が
        無くても fail にしない（遡及修正しない設計と整合させる。`docs/io-spec.md` §2.5.2）。
        """
        md = {
            "validation_status": "pass",
            "revision_history": [{"cycle": i} for i in range(1, 12)],
        }
        r = cfc.check_cutoff_rule(md)
        self.assertEqual(_statuses(r, "fix_cycle_cutoff"), ["pass"])

    def test_status_case_variant_is_treated_as_not_pass(self):
        """**負のテスト**: 表記揺れ（"PASS"）は「未 pass」として扱う（完全一致のみ許す）。"""
        md = {
            "validation_status": "PASS",
            "revision_history": [{"cycle": 1}, {"cycle": 2}, {"cycle": 3}],
        }
        r = cfc.check_cutoff_rule(md)
        self.assertEqual(_statuses(r, "fix_cycle_cutoff"), ["fail"])

    def test_last_element_not_a_dict_fails_safely(self):
        md = {
            "validation_status": "NEEDS_REVISION",
            "revision_history": [{"cycle": 1}, {"cycle": 2}, "not-a-dict"],
        }
        r = cfc.check_cutoff_rule(md)
        self.assertEqual(_statuses(r, "fix_cycle_cutoff"), ["fail"])


# ---------------------------------------------------------------- R-31
class TestGateAttribution(unittest.TestCase):
    """R-31 / C-50: Critical Issue の Gate 自己申告フィールドを検査する。"""

    def test_no_critical_section_passes(self):
        text = "# Report\n\n## Suggestions\n\n### Suggestion #1\n- **Gate**: 3-only\n"
        r = cfc.check_gate_attribution(text)
        self.assertEqual(_statuses(r, "gate_field_present"), ["pass"])
        self.assertEqual(_statuses(r, "gate_3only_not_critical"), ["pass"])

    def test_empty_critical_section_passes(self):
        text = "# Report\n\n## 5. Critical Issues（修正必須）\n\n**なし。**\n\n## 6. Suggestions\n"
        r = cfc.check_gate_attribution(text)
        self.assertEqual(_statuses(r, "gate_field_present"), ["pass"])
        self.assertEqual(_statuses(r, "gate_3only_not_critical"), ["pass"])

    def test_all_critical_issues_have_gate_field_passes(self):
        text = (
            "# Report\n\n## Critical Issues\n\n"
            "### Issue #1: 例\n- **Priority**: High / **Gate**: 1\n\n"
            "### Issue #2: 例2\n- **Priority**: Medium / **Gate**: 2\n"
        )
        r = cfc.check_gate_attribution(text)
        self.assertEqual(_statuses(r, "gate_field_present"), ["pass"])

    def test_negative_missing_gate_field_fails(self):
        """**負のテスト**: Gate 欄の無い Critical Issue は fail。"""
        text = (
            "# Report\n\n## Critical Issues\n\n"
            "### Issue #1: Gate 欄が無い\n- **Priority**: High\n- **Fix**: 直す\n"
        )
        r = cfc.check_gate_attribution(text)
        self.assertEqual(_statuses(r, "gate_field_present"), ["fail"])

    def test_negative_gate_3only_classified_as_critical_fails(self):
        """**負のテスト（C-50 の再発防止）**: Gate 3-only を Critical にできない。"""
        text = (
            "# Report\n\n## Critical Issues\n\n"
            "### Issue #1: 用語の不統一\n- **Priority**: Low / **Gate**: 3-only\n"
        )
        r = cfc.check_gate_attribution(text)
        self.assertEqual(_statuses(r, "gate_3only_not_critical"), ["fail"])

    def test_gate_3only_in_suggestions_is_fine(self):
        """Suggestions セクション内の Gate 3-only は許容される（Critical セクションのみ検査）。"""
        text = (
            "# Report\n\n## Critical Issues\n\n**なし。**\n\n"
            "## Suggestions\n\n### Suggestion #1\n- **Priority**: Low / **Gate**: 3-only\n"
        )
        r = cfc.check_gate_attribution(text)
        self.assertEqual(_statuses(r, "gate_field_present"), ["pass"])
        self.assertEqual(_statuses(r, "gate_3only_not_critical"), ["pass"])

    def test_gate_is_not_guessed_from_prose(self):
        """**Gate は自己申告フィールドのみで判定し、文面から推測しない**。

        本文に "Gate" という語や数字が現れても、`**Gate**:` の形でなければ
        検出しない——欠落として扱われ fail する（正規表現で推測しない設計の検証）。
        """
        text = (
            "# Report\n\n## Critical Issues\n\n"
            "### Issue #1: この指摘は Gate 2 相当だと思われる\n- **Fix**: 直す\n"
        )
        r = cfc.check_gate_attribution(text)
        self.assertEqual(_statuses(r, "gate_field_present"), ["fail"])

    def test_multiple_critical_sections_are_all_scanned(self):
        """`## ... Critical Issues ...`（見出しに前後の飾りがある）も検出する。"""
        text = (
            "# Report\n\n## 5. Critical Issues（修正必須）\n\n"
            "### Issue #1: 例\n- **Gate**: 0\n"
        )
        r = cfc.check_gate_attribution(text)
        self.assertEqual(_statuses(r, "gate_field_present"), ["pass"])

    def test_invalid_gate_value_is_not_recognized(self):
        """定義された値（0/1/2/3-only）以外は Gate 欄が無いのと同じに扱う。"""
        text = (
            "# Report\n\n## Critical Issues\n\n"
            "### Issue #1: 例\n- **Gate**: 4\n"
        )
        r = cfc.check_gate_attribution(text)
        self.assertEqual(_statuses(r, "gate_field_present"), ["fail"])

    def test_negative_decoy_gate_in_inline_code_does_not_hide_real_self_report(self):
        """**負のテスト（Phase 12 修正サイクル 1 巡目。Validator Critical #2 の再現手順）**:

        書式例として引用された `- **Gate**: 0`（インラインコード）が本物の自己申告
        `**Gate**: 3-only` より前に出現しても、最初の出現をそのまま採用しない。
        修正前は `extract_gate()` が `"0"` を返し、`gate_3only_not_critical` が
        誤って pass していた。
        """
        text = (
            "# Report\n\n## Critical Issues\n\n"
            "### Issue #1: 何か\n"
            "- **Priority**: High\n"
            "- **Problem**: format example: `- **Gate**: 0` is how you write it\n"
            "- ...\n"
            "- **Gate**: 3-only\n"
        )
        r = cfc.check_gate_attribution(text)
        self.assertEqual(_statuses(r, "gate_3only_not_critical"), ["fail"])

    def test_extract_gate_ignores_decoy_in_inline_code(self):
        block = (
            "### Issue #1: 何か\n"
            "- **Problem**: format example: `- **Gate**: 0` is how you write it\n"
            "- **Gate**: 3-only\n"
        )
        self.assertEqual(cfc.extract_gate(block), "3-only")

    def test_extract_gate_ignores_decoy_in_code_fence(self):
        block = (
            "### Issue #1: 何か\n"
            "```\n- **Gate**: 0\n```\n"
            "- **Gate**: 3-only\n"
        )
        self.assertEqual(cfc.extract_gate(block), "3-only")

    def test_extract_gate_returns_ambiguous_marker_for_two_real_matches(self):
        """デコイではなく本物同士が 2 箇所に出現する場合は「曖昧」として扱う
        （どちらが自己申告か機械的に決められないため）。"""
        block = "### Issue #1\n- **Gate**: 1\n- **Gate**: 2\n"
        self.assertEqual(cfc.extract_gate(block), cfc._AMBIGUOUS_GATE)

    def test_negative_ambiguous_gate_is_treated_as_missing_not_a_silent_pick(self):
        text = (
            "# Report\n\n## Critical Issues\n\n"
            "### Issue #1: 例\n- **Gate**: 1\n- **Gate**: 2\n"
        )
        r = cfc.check_gate_attribution(text)
        self.assertEqual(_statuses(r, "gate_field_present"), ["fail"])


class TestMalformedCriticalSections(unittest.TestCase):
    """**負のテスト（Phase 12 修正サイクル 1 巡目。Validator Critical #3 の再現手順）**:

    `### ` 見出し以外の書式（番号付きリスト等）で書かれた Critical Issue を
    「Critical Issue が無い」と誤って pass しないこと。
    """

    def test_negative_numbered_list_without_headings_is_not_silently_zero(self):
        text = (
            "## Critical Issues\n\n"
            "1. **Location**: foo.md\n"
            "   **Problem**: bar\n"
            "   （Gate 欄なし）\n"
            "2. **Location**: baz.md\n"
            "   **Problem**: qux\n"
            "   （Gate 欄なし）\n"
        )
        r = cfc.check_gate_attribution(text)
        self.assertEqual(_statuses(r, "gate_field_present"), ["fail"])
        self.assertEqual(_statuses(r, "gate_3only_not_critical"), ["fail"])

    def test_malformed_critical_sections_reports_the_offending_heading(self):
        text = (
            "## Critical Issues\n\n"
            "1. **Location**: foo.md\n   **Problem**: bar\n"
        )
        offenders = cfc.malformed_critical_sections(text)
        self.assertEqual(len(offenders), 1)
        self.assertIn("Critical Issues", offenders[0])

    def test_well_formed_headings_are_not_flagged_as_malformed(self):
        text = (
            "## Critical Issues\n\n### Issue #1: 例\n- **Gate**: 1\n"
        )
        self.assertEqual(cfc.malformed_critical_sections(text), [])

    def test_prose_without_issue_markers_is_not_flagged_as_malformed(self):
        """`**Location**` / `**Problem**` が無ければ、`### ` が無くても『Issue 無し』のまま。"""
        text = "## Critical Issues\n\n**なし。**\n"
        self.assertEqual(cfc.malformed_critical_sections(text), [])


class TestSubheadingCriticalSections(unittest.TestCase):
    """v15.1: `###` レベルの Critical Issues 見出しと、太字でない `- Location:` を読む。

    v15.0 の run-phase SKILL.md Step 2.2 の雛形は `## Detailed Findings` の下に
    `### Critical Issues (must fix)` と番号付きリスト（太字なし）を置いていた。
    `##` だけを見て太字の `**Location**` だけを拾う検査は、雛形どおりの報告を
    「Critical Issue 0 件」として素通りさせていた（**偽 PASS**）。
    """

    V150_TEMPLATE_REPORT = (
        "# Validation Report: Phase 1\n\n"
        "## Detailed Findings\n\n"
        "### Critical Issues (must fix)\n"
        "1. 用語の表記が前フェーズと揺れている\n"
        "   - Location: report.md:12\n"
        "   - Expected: 前フェーズと同じ表記\n"
        "   - Actual: 別表記\n"
        "   - Fix: 表記を揃える\n\n"
        "### Suggestions (nice to have)\n"
        "1. なし\n"
    )

    def test_negative_v150_run_phase_template_is_not_silently_zero(self):
        r = cfc.check_gate_attribution(self.V150_TEMPLATE_REPORT)
        self.assertEqual(_statuses(r, "gate_field_present"), ["fail"])
        self.assertEqual(_statuses(r, "gate_3only_not_critical"), ["fail"])

    def test_level3_section_with_level4_issue_blocks_is_parsed(self):
        text = (
            "## Detailed Findings\n\n"
            "### Critical Issues\n\n"
            "#### Issue #1: 価格の欠落\n- **Gate**: 1\n- **Location**: a.md:3\n\n"
            "#### Issue #2: 用語\n- **Gate**: 3-only\n- **Location**: a.md:9\n\n"
            "### Suggestions\n\n#### Suggestion #1: 図\n- **Gate**: 3-only\n"
        )
        self.assertEqual(len(cfc.critical_issue_blocks(text)), 2)
        r = cfc.check_gate_attribution(text)
        self.assertEqual(_statuses(r, "gate_field_present"), ["pass"])
        self.assertEqual(_statuses(r, "gate_3only_not_critical"), ["fail"])

    def test_level3_section_ends_at_next_sibling_heading(self):
        """Suggestions 側の Issue ブロックを Critical に数えない。"""
        text = (
            "### Critical Issues\n\n**なし。**\n\n"
            "### Suggestions\n\n#### S1\n- **Gate**: 3-only\n- **Location**: a.md\n"
        )
        self.assertEqual(cfc.critical_issue_blocks(text), [])
        self.assertEqual(cfc.malformed_critical_sections(text), [])

    def test_issue_title_mentioning_critical_issues_is_not_a_section(self):
        """`### Suggestion #1: Critical Issues の書式…` を Critical セクションと誤認しない。"""
        text = (
            "## Suggestions\n\n"
            "### Suggestion #1: Critical Issues の書式を揃える\n- **Location**: a.md\n"
        )
        self.assertEqual(cfc.critical_issue_blocks(text), [])
        self.assertEqual(cfc.malformed_critical_sections(text), [])

    def test_numbered_prefix_on_subheading_is_accepted(self):
        text = "## 5. 指摘\n\n### 5.1 Critical Issues\n\n1. Location: a.md\n"
        self.assertEqual(len(cfc.malformed_critical_sections(text)), 1)


class TestCycleTrigger(unittest.TestCase):
    """v15.1: revision_history[].opened_by（修正サイクルを開いた根拠）。"""

    def test_metadata_missing_is_skip(self):
        self.assertEqual(_statuses(cfc.check_cycle_trigger(None), "fix_cycle_opened_by"),
                         ["skip"])

    def test_no_cycles_passes(self):
        r = cfc.check_cycle_trigger({"revision_history": []})
        self.assertEqual(_statuses(r, "fix_cycle_opened_by"), ["pass"])

    def test_all_entries_with_closed_set_values_pass(self):
        md = {"revision_history": [{"cycle": 1, "opened_by": "validator_critical"},
                                   {"cycle": 2, "opened_by": "expert_defect"},
                                   {"cycle": 3, "opened_by": "owner_decision"},
                                   {"cycle": 4, "opened_by": "main_session"}]}
        r = cfc.check_cycle_trigger(md)
        self.assertEqual(_statuses(r, "fix_cycle_opened_by"), ["pass"])

    def test_negative_missing_opened_by_fails(self):
        md = {"revision_history": [{"cycle": 1, "opened_by": "validator_critical"},
                                   {"cycle": 2}]}
        r = cfc.check_cycle_trigger(md)
        self.assertEqual(_statuses(r, "fix_cycle_opened_by"), ["fail"])
        self.assertIn("#2", r[0]["message"])

    def test_negative_value_outside_closed_set_fails(self):
        md = {"revision_history": [{"cycle": 1, "opened_by": "reviewer"}]}
        r = cfc.check_cycle_trigger(md)
        self.assertEqual(_statuses(r, "fix_cycle_opened_by"), ["fail"])

    def test_cycle_opened_with_zero_critical_is_not_a_violation(self):
        """Validator が Critical 0 で PASS でも、専門家の指摘やオーナー決定で開いた
        サイクルは正当。件数との突き合わせはしない。"""
        md = {"validation_status": "pass",
              "revision_history": [{"cycle": 1, "opened_by": "expert_defect",
                                    "validator_critical_count": 0}]}
        r = cfc.check_cycle_trigger(md)
        self.assertEqual(_statuses(r, "fix_cycle_opened_by"), ["pass"])


class TestRunChecksIntegration(unittest.TestCase):
    """run_checks(): ファイルシステム経由の統合テスト。"""

    def _phase_dir(self, tmp, n=12):
        d = Path(tmp) / "outputs" / f"phase-{n:02d}"
        (d / ".validation").mkdir(parents=True)
        return d

    def test_missing_metadata_and_report_are_skipped_not_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "outputs").mkdir()
            results = cfc.run_checks(tmp, 12)
            self.assertIn("skip", _statuses(results, "fix_cycle_cutoff"))
            self.assertIn("skip", _statuses(results, "gate_field_present"))
            self.assertEqual([r for r in results if r["status"] == "fail"], [])

    def test_full_pipeline_negative_case(self):
        """メタデータと report.md の両方が違反しているケースを一括検出する。"""
        with tempfile.TemporaryDirectory() as tmp:
            d = self._phase_dir(tmp)
            md = {
                "validation_status": "NEEDS_REVISION",
                "revision_history": [{"cycle": 1}, {"cycle": 2}, {"cycle": 3}],
            }
            (d / ".metadata.json").write_text(json.dumps(md), encoding="utf-8")
            (d / ".validation" / "report.md").write_text(
                "# Report\n\n## Critical Issues\n\n### Issue #1: 例\n- **Fix**: 直す\n",
                encoding="utf-8")
            results = cfc.run_checks(tmp, 12)
            self.assertIn("fail", _statuses(results, "fix_cycle_cutoff"))
            self.assertIn("fail", _statuses(results, "gate_field_present"))

    def test_negative_malformed_metadata_is_fail_not_skip(self):
        """v15.1: 末尾カンマ 1 つで 4 巡・owner_decision 無しの違反が OK にならない。"""
        with tempfile.TemporaryDirectory() as tmp:
            d = self._phase_dir(tmp)
            (d / ".metadata.json").write_text(
                '{"validation_status": "NEEDS_REVISION", "revision_history": '
                '[{"cycle": 1}, {"cycle": 2}, {"cycle": 3}, {"cycle": 4}],}', encoding="utf-8")
            results = cfc.run_checks(tmp, 12)
            self.assertEqual(_statuses(results, "fix_cycle_cutoff"), ["fail"])
            self.assertEqual(_statuses(results, "fix_cycle_opened_by"), ["fail"])

    def test_negative_missing_phase_dir_and_bad_phase_are_exit_2(self):
        import subprocess, sys
        script = str(Path(__file__).parent / "check_fix_cycle.py")
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "outputs").mkdir()
            for phase in ("7", "abc"):
                p = subprocess.run([sys.executable, script, "--phase", phase,
                                    "--project-dir", tmp], capture_output=True, text=True)
                self.assertEqual(p.returncode, 2, (phase, p.stdout, p.stderr))

    def test_full_pipeline_positive_case(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self._phase_dir(tmp)
            md = {"validation_status": "pass", "revision_history": []}
            (d / ".metadata.json").write_text(json.dumps(md), encoding="utf-8")
            (d / ".validation" / "report.md").write_text(
                "# Report\n\n## Critical Issues\n\n**なし。**\n", encoding="utf-8")
            results = cfc.run_checks(tmp, 12)
            self.assertEqual([r for r in results if r["status"] == "fail"], [])


if __name__ == "__main__":
    unittest.main()
