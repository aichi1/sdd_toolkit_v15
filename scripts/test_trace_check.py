#!/usr/bin/env python3
"""
test_trace_check.py: 要件 → SKILL → outputs のトレーサビリティ検査（R-15）。

**負のテストを先に書く**（`skills/phase-08/SKILL.md` Procedure 3）。
対応表を出すだけなら目視と変わらない。**未対応を検出できることが要点**である。

規約は `docs/requirements.md` §9。**規約を変えるとこのテストが落ちる**ようにしてある。
"""
import json
import unittest
import tempfile
import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "trace_check", str(Path(__file__).resolve().parent / "trace_check.py"))
tc = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(tc)

REQ_HEADER = "## 5. 機能要件（R-ID）\n\n| ID | 要件 | 対応課題 | 実現フェーズ | 検証 |\n|----|------|---------|------------|------|\n"


def _project(tmp, rows, skills=None, outputs=None, phases=None):
    """フィクスチャ。rows は §5 の表の行、skills は {phase: 宣言行}、outputs は {phase: [R-ID]}。"""
    d = Path(tmp)
    (d / "docs").mkdir(parents=True, exist_ok=True)
    (d / "docs" / "requirements.md").write_text(
        "# req\n\n" + REQ_HEADER + rows + "\n\n## 6. 次の節\n", encoding="utf-8")
    for ph, decl in (skills or {}).items():
        sd = d / "skills" / f"phase-{ph}"
        sd.mkdir(parents=True, exist_ok=True)
        (sd / "SKILL.md").write_text(f"# Phase {ph}\n\n{decl}\n\n本文。\n", encoding="utf-8")
    for ph, ids in (outputs or {}).items():
        od = d / "outputs" / f"phase-{ph}"
        od.mkdir(parents=True, exist_ok=True)
        (od / ".metadata.json").write_text(
            json.dumps({"phase": int(ph), "requirements_addressed": ids}), encoding="utf-8")
    (d / "metadata.json").write_text(
        json.dumps({"phases": phases or {}}, ensure_ascii=False), encoding="utf-8")
    return str(d)


def _kinds(findings, kind):
    return sorted(f["reference"] for f in findings if f["kind"] == kind)


# ============================================================ 未対応の検出（負のテスト）
class TestDetectsUnimplemented(unittest.TestCase):
    """**これが Phase 08 の成否を分ける。** 未対応要件を実際に検出できること。"""

    def test_future_phase_requirement_is_planned(self):
        """未来フェーズの要件は `planned`（報告するが欠陥ではない）。"""
        with tempfile.TemporaryDirectory() as t:
            root = _project(t,
                "| R-01 | やること | — | **01** | S-01 |\n"
                "| R-19 | 将来やること | — | 13 | S-11 |\n",
                skills={"01": "> 対応要件: **R-01**"},
                outputs={"01": ["R-01"]},
                phases={"1": {"status": "completed"}})
            f = tc.check_traceability(root)
            self.assertEqual(_kinds(f, "planned"), ["R-19"])
            self.assertEqual(_kinds(f, "overdue"), [])

    def test_completed_phase_missing_requirement_is_overdue(self):
        """**完了したはずのフェーズが要件を宣言していない → overdue（欠陥）。**"""
        with tempfile.TemporaryDirectory() as t:
            root = _project(t,
                "| R-01 | やること | — | **01** | S-01 |\n"
                "| R-02 | 忘れられた要件 | — | **01** | S-01 |\n",
                skills={"01": "> 対応要件: **R-01**"},
                outputs={"01": ["R-01"]},
                phases={"1": {"status": "completed"}})
            self.assertEqual(_kinds(tc.check_traceability(root), "overdue"), ["R-02"])

    def test_detects_unimplemented_from_fixture(self):
        """**未着手フェーズが担当する要件を `planned` として検出する**（SKILL.md Phase 08 QC #2）。

        オーナー決定（2026-09-06、C-55）によりフィクスチャ方式へ移行した。
        旧 `test_real_project_detects_iteration3_requirements` は本プロジェクトの
        **実データ**に対して R-19〜R-26 の未対応検出を固定していたが、
        `/re-init-task` が `skills/phase-11〜15/` を作って `> 対応要件:` を宣言した時点で
        当該要件が `planned` → `assigned` に移り、**負のテストの対象そのものが消えた**。
        検出能力の固定は実データの状態に依存させない。
        """
        with tempfile.TemporaryDirectory() as t:
            root = _project(
                t,
                "| R-01 | 済んだこと | — | **01** | S-01 |\n"
                "| R-02 | 未着手フェーズの担当 | — | 09 | S-02 |\n"
                "| R-03 | 別の未着手フェーズの担当 | — | 09 | S-03 |\n",
                skills={"01": "> 対応要件: **R-01**"},
                outputs={"01": ["R-01"]},
                phases={"1": {"status": "completed"}})
            f = tc.check_traceability(root)
            self.assertEqual(_kinds(f, "planned"), ["R-02", "R-03"])
            # 完了済みの要件は planned に混ざらない
            self.assertNotIn("R-01", _kinds(f, "planned"))

    def test_real_project_has_no_defects(self):
        """**本プロジェクトの実データに欠陥（overdue / orphan / mismatch）が無いこと。**

        実データに対して固定するのは「欠陥 0 件」という**前進しても成立する不変条件**にする。
        「未対応が N 件ある」という状態依存の主張はフィクスチャ側で固定する（C-55）。
        """
        root = str(Path(__file__).resolve().parent.parent)
        f = tc.check_traceability(root)
        for kind in ("overdue", "orphan_skill", "orphan_output", "phase_mismatch", "not_delivered"):
            self.assertEqual(_kinds(f, kind), [], f"実データに {kind} の欠陥がある")


# ============================================================ 孤立の検出
class TestDetectsOrphans(unittest.TestCase):
    def test_skill_declares_unknown_id(self):
        """SKILL が docs に無い ID を宣言している → 孤立。"""
        with tempfile.TemporaryDirectory() as t:
            root = _project(t, "| R-01 | やること | — | **01** | S-01 |\n",
                            skills={"01": "> 対応要件: **R-01, R-99**"},
                            outputs={"01": ["R-01"]}, phases={"1": {"status": "completed"}})
            self.assertEqual(_kinds(tc.check_traceability(root), "orphan_skill"), ["R-99"])

    def test_output_claims_unknown_id(self):
        with tempfile.TemporaryDirectory() as t:
            root = _project(t, "| R-01 | やること | — | **01** | S-01 |\n",
                            skills={"01": "> 対応要件: **R-01**"},
                            outputs={"01": ["R-01", "R-98"]}, phases={"1": {"status": "completed"}})
            self.assertEqual(_kinds(tc.check_traceability(root), "orphan_output"), ["R-98"])

    def test_phase_mismatch(self):
        """docs は Phase 02 と言うが Phase 01 の SKILL が宣言している。"""
        with tempfile.TemporaryDirectory() as t:
            root = _project(t, "| R-01 | やること | — | **02** | S-01 |\n",
                            skills={"01": "> 対応要件: **R-01**", "02": "> 対応要件: なし"},
                            outputs={}, phases={})
            self.assertEqual(_kinds(tc.check_traceability(root), "phase_mismatch"), ["R-01"])

    def test_declared_but_not_delivered(self):
        """SKILL は宣言したが完了フェーズの outputs が申告していない。"""
        with tempfile.TemporaryDirectory() as t:
            root = _project(t, "| R-01 | やること | — | **01** | S-01 |\n",
                            skills={"01": "> 対応要件: **R-01**"},
                            outputs={"01": []}, phases={"1": {"status": "completed"}})
            self.assertEqual(_kinds(tc.check_traceability(root), "not_delivered"), ["R-01"])


# ============================================================ 抽出の限定（Phase 07 の教訓）
class TestExtractionIsStructureLimited(unittest.TestCase):
    """**証跡は決められた 1 行・決められた表**であって散文ではない（§9.4 / Phase 07 #40）。"""

    def test_prose_mention_is_not_a_declaration(self):
        """本文中の「R-19〜R-26 が未対応」を担当宣言と読まないこと。

        本フェーズ自身の SKILL.md がこの形をしている。読み違えると
        **R-19〜R-26 が対応済みに見え、QC #2 の負のテストが空振りする**。
        """
        with tempfile.TemporaryDirectory() as t:
            d = Path(t) / "skills" / "phase-08"
            d.mkdir(parents=True)
            (d / "SKILL.md").write_text(
                "# Phase 08\n\n> 対応要件: **R-15, R-16**\n\n"
                "本文: R-19〜R-26 は未対応のはずであり、それを負例に使う。R-99 も同様。\n",
                encoding="utf-8")
            self.assertEqual(tc.extract_skill_declarations(t), {"08": {"R-15", "R-16"}})

    def test_prose_mention_is_not_a_definition(self):
        """§5 の表の行だけが定義。散文の `R-99` は拾わない。"""
        with tempfile.TemporaryDirectory() as t:
            root = _project(t, "| R-01 | やること | — | **01** | S-01 |\n")
            self.assertEqual(sorted(tc.extract_requirements(root)), ["R-01"])

    def test_only_section_5_table_counts(self):
        """§4（C-ID）や §7（S-ID）の表を R として読まない。"""
        with tempfile.TemporaryDirectory() as t:
            d = Path(t) / "docs"
            d.mkdir(parents=True)
            (d / "requirements.md").write_text(
                "## 4. 課題\n\n| R-77 | 別の表 | — | **01** | x |\n\n"
                + REQ_HEADER + "| R-01 | やること | — | **01** | S-01 |\n"
                + "\n## 6. 次\n\n| R-88 | また別 | — | **01** | x |\n", encoding="utf-8")
            self.assertEqual(sorted(tc.extract_requirements(t)), ["R-01"])

    def test_decoration_does_not_change_id(self):
        """`**R-01**` と `~~R-01~~` と `R-01` は同一（§9.2）。"""
        with tempfile.TemporaryDirectory() as t:
            root = _project(t, "| ~~**R-01**~~ | 取り下げ | — | **01** | S-01 |\n")
            self.assertEqual(sorted(tc.extract_requirements(root)), ["R-01"])

    def test_zero_padding_normalized(self):
        with tempfile.TemporaryDirectory() as t:
            root = _project(t, "| R-1 | ゼロ埋めなし | — | **01** | S-01 |\n")
            self.assertEqual(sorted(tc.extract_requirements(root)), ["R-01"])


# ============================================================ 実現フェーズ列（§9.3）
class TestPhaseColumn(unittest.TestCase):
    def test_all_forms(self):
        self.assertEqual(tc.parse_phase_cell("**01**"), ({1}, False))
        self.assertEqual(tc.parse_phase_cell("**01**, **05**, 10, 14"), ({1, 5, 10, 14}, False))
        self.assertEqual(tc.parse_phase_cell("**全**"), (set(), True))
        self.assertEqual(tc.parse_phase_cell("**01**, 各フェーズ"), ({1}, True))

    def test_parenthetical_note_is_stripped(self):
        """括弧内は注記。**括弧内の数字をフェーズと誤読しない**。"""
        self.assertEqual(
            tc.parse_phase_cell("06（本プロジェクト分は init 時に先行作成）"), ({6}, False))
        self.assertEqual(tc.parse_phase_cell("07 (see 99)"), ({7}, False))

    def test_unknown_token_raises(self):
        """**黙って読み飛ばさない**（§9.3。Phase 07 の C-42 と同じ轍を踏まない）。"""
        with self.assertRaises(tc.ConventionViolation):
            tc.parse_phase_cell("いつか")

    def test_convention_violation_is_reported_not_skipped(self):
        with tempfile.TemporaryDirectory() as t:
            root = _project(t, "| R-01 | やること | — | いつか | S-01 |\n")
            self.assertEqual(_kinds(tc.check_traceability(root), "convention_violation"), ["R-01"])


class TestAssignedButNotDelivered(unittest.TestCase):
    """**宣言済み・未完了**を「対応済み」と見せないこと。

    対応表を出すだけなら目視と変わらない（SKILL.md Common Pitfalls）。
    宣言があるだけで「対応済み」と表示すると、**表が嘘をつく**。
    """

    def test_declared_phase_not_completed_is_assigned(self):
        with tempfile.TemporaryDirectory() as t:
            root = _project(t, "| R-01 | これから | — | **09** | S-01 |\n",
                            skills={"09": "> 対応要件: **R-01**"},
                            outputs={}, phases={"9": {"status": "not_started"}})
            f = tc.check_traceability(root)
            self.assertEqual(_kinds(f, "assigned"), ["R-01"])
            self.assertEqual(_kinds(f, "not_delivered"), [])

    def test_delivered_has_no_finding(self):
        """完了・申告済みなら何も出ない（それが「対応済み」）。"""
        with tempfile.TemporaryDirectory() as t:
            root = _project(t, "| R-01 | やった | — | **01** | S-01 |\n",
                            skills={"01": "> 対応要件: **R-01**"},
                            outputs={"01": ["R-01"]}, phases={"1": {"status": "completed"}})
            self.assertEqual(tc.check_traceability(root), [])


# ============================================================ 横断要件
class TestCrosscutting(unittest.TestCase):
    def test_crosscutting_is_not_unimplemented(self):
        """`全` / `各フェーズ` は特定フェーズの宣言を要求しない（§9.3）。"""
        with tempfile.TemporaryDirectory() as t:
            root = _project(t, "| R-27 | 横断要件 | — | **全** | diff |\n",
                            skills={"01": "> 対応要件: なし"}, outputs={},
                            phases={"1": {"status": "completed"}})
            f = tc.check_traceability(root)
            self.assertEqual(_kinds(f, "overdue"), [])
            self.assertEqual(_kinds(f, "planned"), [])
            self.assertEqual(_kinds(f, "crosscutting"), ["R-27"])


# ============================================================ 出力の形
class TestReportShape(unittest.TestCase):
    def test_finding_has_required_keys(self):
        with tempfile.TemporaryDirectory() as t:
            root = _project(t, "| R-19 | 将来 | — | 13 | S-11 |\n")
            for f in tc.check_traceability(root):
                for k in ("check", "reference", "kind", "message", "phases"):
                    self.assertIn(k, f)

    def test_matrix_covers_every_requirement(self):
        """対応表は**全要件**を含む（不変条件）。

        C-55: 実データに固定してよいのは **不変条件** であって **状態** ではない。
        「29 件以上ある」は開発当時のプロジェクトの**状態**であり、ツールキット単体や
        別のプロジェクトでは成立しない。ここで固定するのは
        「対応表の ID 集合 == 要件の ID 集合」という不変条件と、
        「要件があるのに対応表が空になっていない」という空振りの検出だけにする。
        """
        root = str(Path(__file__).resolve().parent.parent)
        reqs = tc.extract_requirements(root)
        rows = tc.build_matrix(root)
        self.assertEqual(sorted(r["id"] for r in rows), sorted(reqs))
        if reqs:
            self.assertGreater(len(rows), 0, "要件があるのに対応表が空（空振り）")


if __name__ == "__main__":
    unittest.main()
