#!/usr/bin/env python3
"""
test_aggregate_outputs.py: aggregate_outputs.py の回帰テスト（C-45 / R-33）

C-45: `/finalize` の後勝ち方式は、全フェーズが同名の証跡を持つドッグフーディング型
プロジェクトで旧フェーズの証跡を黙って失う。**負のテストで「同名ファイルが失われないこと」を固定する。**
"""
import tempfile
import unittest
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "aggregate_outputs", str(Path(__file__).parent / "aggregate_outputs.py")
)
ao = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ao)


class _Project:
    """`outputs/phase-01` `outputs/phase-02` を持つ最小プロジェクトを一時ディレクトリに作る。"""

    def __init__(self, tmp):
        self.root = Path(tmp)
        for n in (1, 2):
            d = self.root / "outputs" / f"phase-{n:02d}"
            d.mkdir(parents=True)
            (d / "change-report.md").write_text(f"phase {n} report", encoding="utf-8")
            (d / "patch.diff").write_text(f"phase {n} patch", encoding="utf-8")
            (d / ".metadata.json").write_text("{}", encoding="utf-8")
            (d / ".validation").mkdir()
            (d / ".validation" / "report.md").write_text("validator report", encoding="utf-8")
            (d / "README.md").write_text("per-phase readme (should not aggregate)",
                                         encoding="utf-8")
        # phase-02 だけが持つ固有ファイル（衝突しない）
        (self.root / "outputs" / "phase-02" / "unique.md").write_text(
            "only in phase 2", encoding="utf-8")


class TestConflictPreservation(unittest.TestCase):
    """**負のテスト（C-45 の中核）**: 同名ファイルが後勝ちで失われないこと。"""

    def test_conflicting_filenames_are_both_preserved_with_phase_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = _Project(tmp)
            ao.aggregate_outputs(str(proj.root))
            final = proj.root / "outputs" / "final"
            p1 = final / "phase-01-change-report.md"
            p2 = final / "phase-02-change-report.md"
            self.assertTrue(p1.is_file(), "Phase 01 の change-report.md が失われている")
            self.assertTrue(p2.is_file(), "Phase 02 の change-report.md が失われている")
            self.assertEqual(p1.read_text(encoding="utf-8"), "phase 1 report")
            self.assertEqual(p2.read_text(encoding="utf-8"), "phase 2 report")
            # 後勝ち方式であれば起きていたはずの上書き（旧 phase-01 の内容の消失）が
            # 起きていないことを明示的に確認する
            self.assertNotEqual(p2.read_text(encoding="utf-8"), p1.read_text(encoding="utf-8"))

    def test_undecorated_conflicting_filename_does_not_exist(self):
        """後勝ち方式の産物（接頭辞の無い衝突ファイル）が残らないこと。"""
        with tempfile.TemporaryDirectory() as tmp:
            proj = _Project(tmp)
            ao.aggregate_outputs(str(proj.root))
            final = proj.root / "outputs" / "final"
            self.assertFalse((final / "change-report.md").exists())
            self.assertFalse((final / "patch.diff").exists())

    def test_multiple_conflicting_names_all_get_prefixed(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = _Project(tmp)
            ao.aggregate_outputs(str(proj.root))
            final = proj.root / "outputs" / "final"
            for n in (1, 2):
                self.assertTrue((final / f"phase-{n:02d}-patch.diff").is_file())


class TestNonConflictingFiles(unittest.TestCase):
    def test_unique_file_keeps_original_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = _Project(tmp)
            ao.aggregate_outputs(str(proj.root))
            final = proj.root / "outputs" / "final"
            self.assertTrue((final / "unique.md").is_file())
            self.assertFalse((final / "phase-02-unique.md").exists())


class TestExclusions(unittest.TestCase):
    def test_metadata_and_validation_and_readme_are_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = _Project(tmp)
            ao.aggregate_outputs(str(proj.root))
            final = proj.root / "outputs" / "final"
            self.assertFalse((final / ".metadata.json").exists())
            self.assertFalse((final / "phase-01-.metadata.json").exists())
            self.assertFalse((final / ".validation").exists())
            self.assertFalse((final / "report.md").exists())
            self.assertFalse((final / "README.md").exists())
            self.assertFalse((final / "phase-01-README.md").exists())

    def test_negative_git_zone_backup_is_excluded(self):
        """**負のテスト（Phase 12 修正サイクル 1 巡目。Validator Critical #4 の再現手順）**:

        C-45 のもう一方の実測症状——`outputs/phase-02/git-zone-backup/`（C-23 の退避証跡）
        配下のファイルが、プレフィックスなしのまま `outputs/final/` に混入すること——が
        再現しないことを固定する。
        """
        with tempfile.TemporaryDirectory() as tmp:
            proj = _Project(tmp)
            backup = proj.root / "outputs" / "phase-02" / "git-zone-backup"
            backup.mkdir(parents=True)
            (backup / "some-file.txt:Zone.Identifier").write_text(
                "should never reach outputs/final/", encoding="utf-8")
            result = ao.aggregate_outputs(str(proj.root))
            final = proj.root / "outputs" / "final"
            self.assertFalse((final / "git-zone-backup").exists())
            self.assertFalse(
                any("git-zone-backup" in rel for rel in result["copied"]),
                "git-zone-backup 配下が copied に含まれている",
            )
            self.assertFalse(
                any("git-zone-backup" in rel for rel, _phase, _dest in result["renamed"]),
                "git-zone-backup 配下が renamed に含まれている",
            )


class TestDryRun(unittest.TestCase):
    def test_dry_run_does_not_write_final_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = _Project(tmp)
            result = ao.aggregate_outputs(str(proj.root), dry_run=True)
            self.assertFalse((proj.root / "outputs" / "final").exists())
            # それでも集計結果は返す
            self.assertIn("change-report.md", result["conflicts"])

    def test_dry_run_result_matches_wet_run_conflicts(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = _Project(tmp)
            dry = ao.aggregate_outputs(str(proj.root), dry_run=True)
            wet = ao.aggregate_outputs(str(proj.root), dry_run=False)
            self.assertEqual(dry["conflicts"], wet["conflicts"])


class TestFindConflicts(unittest.TestCase):
    def test_reports_both_phases_for_conflicting_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = _Project(tmp)
            conflicts = ao.find_conflicts(proj.root / "outputs")
            self.assertEqual(sorted(conflicts["change-report.md"]), [1, 2])

    def test_does_not_report_unique_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = _Project(tmp)
            conflicts = ao.find_conflicts(proj.root / "outputs")
            self.assertNotIn("unique.md", conflicts)

    def test_ignores_final_directory_itself(self):
        """`outputs/final/`（`phase-NN` の形をしていない）は集約対象の走査から除外される。"""
        with tempfile.TemporaryDirectory() as tmp:
            proj = _Project(tmp)
            (proj.root / "outputs" / "final").mkdir()
            (proj.root / "outputs" / "final" / "change-report.md").write_text(
                "should not be scanned as a phase", encoding="utf-8")
            conflicts = ao.find_conflicts(proj.root / "outputs")
            self.assertEqual(sorted(conflicts["change-report.md"]), [1, 2])


class TestNestedSubdirectories(unittest.TestCase):
    def test_conflicting_nested_file_is_prefixed_by_basename_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = _Project(tmp)
            for n in (1, 2):
                sub = proj.root / "outputs" / f"phase-{n:02d}" / "dryrun"
                sub.mkdir()
                (sub / "notes.md").write_text(f"phase {n} notes", encoding="utf-8")
            ao.aggregate_outputs(str(proj.root))
            final = proj.root / "outputs" / "final"
            self.assertTrue((final / "dryrun" / "phase-01-notes.md").is_file())
            self.assertTrue((final / "dryrun" / "phase-02-notes.md").is_file())


if __name__ == "__main__":
    unittest.main()
