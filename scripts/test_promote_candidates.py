#!/usr/bin/env python3
"""
test_promote_candidates.py: promote_candidates.py の回帰テスト（C-54 / R-34）

C-54: `candidates.jsonl` が追記専用のまま肥大化する（実測: 133,613 行）。
`scripts/promote_candidates.py` は読み込み時に重複排除するが、ファイル自体は
増え続ける。**負のテストで「行数が単調増加しないこと」を固定する。**

v15.1: 圧縮（`compact_candidates_file()`）がコンポーネント候補だけを書き戻していたため、
`suggested_id` を持たない `knowledge_curator.py` の改善候補（`/retrospective` の出力）が
次の `/finalize` で全件消えていた。**負のテストで「圧縮がそれ以外の行を消さないこと」を固定する。**
"""
import json
import os
import tempfile
import unittest
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "promote_candidates", str(Path(__file__).parent / "promote_candidates.py")
)
pc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pc)


def _candidate(sid, ts="t0", component_type="skill"):
    return {
        "timestamp": ts,
        "action": "update_metadata",
        "component_id": f"comp-{sid}",
        "suggested_id": sid,
        "component_type": component_type,
        "source_path": "/does/not/exist/for/this/test",
        "source_project": "p",
    }


def _write_lines(path, dicts):
    with open(path, "w", encoding="utf-8") as f:
        for d in dicts:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")


def _count_lines(path):
    with open(path, encoding="utf-8") as f:
        return sum(1 for _ in f)


class TestCompactCandidatesFile(unittest.TestCase):
    """`compact_candidates_file()` 単体の振る舞い。"""

    def test_writes_one_line_per_unique_id(self):
        with tempfile.TemporaryDirectory() as kb:
            unique = {"a": _candidate("a"), "b": _candidate("b")}
            pc.compact_candidates_file(kb, unique)
            path = os.path.join(kb, "candidates.jsonl")
            self.assertEqual(_count_lines(path), 2)

    def test_overwrites_existing_larger_file(self):
        """既存の（肥大化した）ファイルを、重複排除後の内容だけに置き換える。"""
        with tempfile.TemporaryDirectory() as kb:
            path = os.path.join(kb, "candidates.jsonl")
            _write_lines(path, [_candidate("dup", ts=f"t{i}") for i in range(50)])
            self.assertEqual(_count_lines(path), 50)

            pc.compact_candidates_file(kb, {"dup": _candidate("dup", ts="latest")})
            self.assertEqual(_count_lines(path), 1)
            with open(path, encoding="utf-8") as f:
                self.assertEqual(json.loads(f.readline())["timestamp"], "latest")

    def test_empty_unique_produces_empty_file(self):
        with tempfile.TemporaryDirectory() as kb:
            path = os.path.join(kb, "candidates.jsonl")
            _write_lines(path, [_candidate("x")])
            pc.compact_candidates_file(kb, {})
            self.assertEqual(_count_lines(path), 0)


class TestPromoteCompactionIntegration(unittest.TestCase):
    """`promote()` 実行後の candidates.jsonl の行数（C-54 の実測シナリオの再現）。"""

    def test_line_count_does_not_grow_unboundedly_across_repeated_runs(self):
        """**負のテスト（C-54 の中核）**: 同じ教訓が繰り返し追記されても行数は単調増加しない。

        実測: 1 回の /finalize + /retrospective で 79 行増え、133,613 行まで肥大化した。
        本テストは「同一 suggested_id の候補が繰り返し追記される」状況を模す。
        """
        with tempfile.TemporaryDirectory() as kb:
            path = os.path.join(kb, "candidates.jsonl")
            _write_lines(path, [_candidate("dup-id", ts=f"t{i}") for i in range(100)])

            pc.promote(kb, dry_run=False)
            lines_after_run1 = _count_lines(path)

            # 2回目の /finalize + /retrospective を模して、さらに同じ候補を追記する
            with open(path, "a", encoding="utf-8") as f:
                for i in range(100):
                    f.write(json.dumps(_candidate("dup-id", ts=f"u{i}")) + "\n")
            pc.promote(kb, dry_run=False)
            lines_after_run2 = _count_lines(path)

            self.assertLess(lines_after_run1, 100,
                           "1回目の promote() 後も候補が圧縮されていない")
            self.assertLess(lines_after_run2, 100,
                           "2回目の promote() 後、行数が肥大化している")
            self.assertEqual(lines_after_run1, lines_after_run2,
                            "重複IDが繰り返し追記されても行数は単調増加してはならない")

    def test_line_count_grows_only_with_new_distinct_ids(self):
        """新しい suggested_id が増えたときだけ行数が増える（無制限の重複蓄積は増えない）。"""
        with tempfile.TemporaryDirectory() as kb:
            path = os.path.join(kb, "candidates.jsonl")
            _write_lines(path, [_candidate("id-1")])
            pc.promote(kb, dry_run=False)
            after_first = _count_lines(path)
            self.assertEqual(after_first, 1)

            # 新しい教訓（新しい suggested_id）が1件追加される
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(_candidate("id-2")) + "\n")
            pc.promote(kb, dry_run=False)
            after_second = _count_lines(path)
            self.assertEqual(after_second, 2)

    def test_dry_run_does_not_modify_candidates_file(self):
        """dry-run はレジストリだけでなく candidates.jsonl も変更しない。"""
        with tempfile.TemporaryDirectory() as kb:
            path = os.path.join(kb, "candidates.jsonl")
            _write_lines(path, [_candidate(f"id-{i}") for i in range(10)])
            before = Path(path).read_text(encoding="utf-8")

            pc.promote(kb, dry_run=True)

            after = Path(path).read_text(encoding="utf-8")
            self.assertEqual(before, after)


def _curator_record(component_id, lesson, ts="t0", source="retro-project"):
    """`knowledge_curator.py` が書く改善候補の形（`suggested_id` / `component_type` を持たない）。"""
    return {
        "timestamp": ts,
        "action": "update_metadata",
        "component_id": component_id,
        "component_name": "",
        "lesson_source": source,
        "lesson_description": lesson,
        "suggested_changes": {"add_tags": ["pytest"], "update_quality_criteria": None,
                              "adjust_effectiveness": 0.0},
        "priority": "medium",
    }


def _raw_lines(path):
    with open(path, encoding="utf-8") as f:
        return [line.rstrip("\n") for line in f if line.strip()]


class TestCompactionPreservesNonComponentLines(unittest.TestCase):
    """v15.1: 圧縮がコンポーネント候補以外の行（/retrospective の出力など）を消さないこと。"""

    def test_negative_promote_preserves_curator_candidates(self):
        """**負のテスト（v15.1）**: `/retrospective` の curator 候補が次の `/finalize` で消えない。

        旧実装は `suggested_id` を持つ候補だけを書き戻していたため、curator 候補は全件消えた。
        元の行のまま・元の順序で残ることを確かめる。
        """
        with tempfile.TemporaryDirectory() as kb:
            path = os.path.join(kb, "candidates.jsonl")
            cur_a = _curator_record("skill-alpha-v1", "lesson A")
            cur_b = _curator_record("skill-beta-v1", "lesson B")
            _write_lines(path, [cur_a, _candidate("dup"), cur_b, _candidate("dup", ts="t1")])
            raw_a, _, raw_b, _ = _raw_lines(path)

            pc.promote(kb, dry_run=False)

            lines = _raw_lines(path)
            self.assertIn(raw_a, lines, "curator 候補 A が圧縮で消えた")
            self.assertIn(raw_b, lines, "curator 候補 B が圧縮で消えた")
            self.assertLess(lines.index(raw_a), lines.index(raw_b), "元の順序が保たれていない")
            rows = [json.loads(line) for line in lines]
            self.assertEqual([r.get("suggested_id") for r in rows].count("dup"), 1)
            self.assertEqual(len(lines), 3)

    def test_negative_curator_duplicates_are_compacted_by_their_own_key(self):
        """**負のテスト（v15.1）**: curator 候補は捨てず、自身のキーで重複排除して 1 行残す。

        timestamp だけが違う再実行分（C-57 修正前に溜まった重複）は 1 行にまとまり、
        最初の行がそのまま残る。教訓が違う候補は別行として残る。
        """
        with tempfile.TemporaryDirectory() as kb:
            path = os.path.join(kb, "candidates.jsonl")
            _write_lines(path, [
                _curator_record("skill-alpha-v1", "lesson A", ts="t0"),
                _curator_record("skill-alpha-v1", "lesson A", ts="t1"),
                _curator_record("skill-alpha-v1", "lesson Z", ts="t2"),
            ])
            first_raw = _raw_lines(path)[0]

            pc.promote(kb, dry_run=False)

            lines = _raw_lines(path)
            self.assertEqual(len(lines), 2)
            self.assertEqual(lines[0], first_raw)
            self.assertEqual(json.loads(lines[1])["lesson_description"], "lesson Z")

    def test_negative_compaction_keeps_unparseable_lines(self):
        """**負のテスト（v15.1）**: JSON として読めない行を黙って捨てない（そのまま残す）。"""
        with tempfile.TemporaryDirectory() as kb:
            path = os.path.join(kb, "candidates.jsonl")
            _write_lines(path, [_candidate("a")])
            with open(path, "a", encoding="utf-8") as f:
                f.write("{truncated line from a crashed writer\n")

            pc.promote(kb, dry_run=False)

            lines = _raw_lines(path)
            self.assertIn("{truncated line from a crashed writer", lines)
            self.assertEqual(len(lines), 2)

    def test_negative_non_object_json_line_does_not_crash_and_is_kept(self):
        """**負のテスト（v15.1）**: object でない JSON 行（`[1, 2]` 等）で promote() が落ちない。"""
        with tempfile.TemporaryDirectory() as kb:
            path = os.path.join(kb, "candidates.jsonl")
            _write_lines(path, [[1, 2], _candidate("a"), "plain string"])

            pc.promote(kb, dry_run=False)

            lines = _raw_lines(path)
            self.assertIn("[1, 2]", lines)
            self.assertIn('"plain string"', lines)
            self.assertEqual(len(lines), 3)

    def test_component_candidates_are_still_deduplicated(self):
        """コンポーネント候補の重複排除（C-54）は従来どおり効く。"""
        with tempfile.TemporaryDirectory() as kb:
            path = os.path.join(kb, "candidates.jsonl")
            _write_lines(path, [_curator_record("c", "l")]
                         + [_candidate("dup", ts=f"t{i}") for i in range(20)])
            pc.promote(kb, dry_run=False)
            self.assertEqual(_count_lines(path), 2)


if __name__ == "__main__":
    unittest.main()
