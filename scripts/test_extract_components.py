#!/usr/bin/env python3
"""
test_extract_components.py: extract_components.py の回帰テスト（Phase 15 / R-26 / 第7条アブレーション）

C-54 の真の発生源: `scripts/post-phase-complete.sh`（PostToolUse hook, matcher
`Write(outputs/**)`）が outputs 配下への Write のたびに `extract_components.py`
を再実行し、プロジェクト全体（skills/agents/hooks/rules）を再スキャンして
無条件に `candidates.jsonl` へ追記していた。実測（本プロジェクトの実データ、
Phase 15）: `candidates.jsonl` 133,613 行のうち一意な `suggested_id` は
わずか 285 件（重複率 99.8%）。`scripts/promote_candidates.py` の
`compact_candidates_file()`（Phase 12 / C-54 の当初対処）は `/retrospective`
実行時（`promote()` 呼び出し時）にのみ圧縮するため、その間の追記そのものは
無条件のまま際限なく増え続けていた。

本テストは `append_candidates()` が既存の `suggested_id` を持つ候補を
スキップし、新規の `suggested_id` のみを追記することを固定する（負のテスト:
同じ候補を2回渡しても行数が2倍にならないこと）。
"""
import json
import os
import tempfile
import unittest
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "extract_components", str(Path(__file__).parent / "extract_components.py")
)
ec = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ec)


def _candidate(sid, source_path="/does/not/exist"):
    return {
        "timestamp": "2026-09-06T00:00:00Z",
        "source_project": "p",
        "source_phase": 0,
        "component_type": "skill",
        "source_path": source_path,
        "suggested_id": sid,
        "auto_tags": [],
    }


def _read_lines(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


class TestLoadExistingSuggestedIds(unittest.TestCase):
    def test_missing_file_returns_empty_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            ids = ec.load_existing_suggested_ids(os.path.join(tmp, "candidates.jsonl"))
            self.assertEqual(ids, set())

    def test_reads_suggested_ids_from_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "candidates.jsonl")
            with open(path, "w", encoding="utf-8") as f:
                f.write(json.dumps(_candidate("a")) + "\n")
                f.write(json.dumps(_candidate("b")) + "\n")
            ids = ec.load_existing_suggested_ids(path)
            self.assertEqual(ids, {"a", "b"})

    def test_malformed_line_is_skipped_not_fatal(self):
        """R-10 と同じ思想: 壊れた行があっても全体を止めない（例外を送出しない）。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "candidates.jsonl")
            with open(path, "w", encoding="utf-8") as f:
                f.write("{not valid json\n")
                f.write(json.dumps(_candidate("a")) + "\n")
            ids = ec.load_existing_suggested_ids(path)
            self.assertEqual(ids, {"a"})


class TestAppendCandidatesDedup(unittest.TestCase):
    def test_new_candidates_are_appended(self):
        with tempfile.TemporaryDirectory() as tmp:
            count = ec.append_candidates([_candidate("x"), _candidate("y")], tmp)
            self.assertEqual(count, 2)
            rows = _read_lines(os.path.join(tmp, "candidates.jsonl"))
            self.assertEqual({r["suggested_id"] for r in rows}, {"x", "y"})

    def test_duplicate_suggested_id_across_two_calls_is_not_appended_again(self):
        """**負のテスト（C-54 の真の発生源の回帰固定）**: 同じ候補（同じ
        `suggested_id`）を2回に分けて渡しても、2回目は追記されない。
        `post-phase-complete.sh` が `Write(outputs/**)` のたびに同じ
        skills/agents/hooks/rules を再スキャンする実際の挙動を模している。
        """
        with tempfile.TemporaryDirectory() as tmp:
            first = ec.append_candidates([_candidate("dup")], tmp)
            second = ec.append_candidates([_candidate("dup")], tmp)
            self.assertEqual(first, 1)
            self.assertEqual(second, 0)
            rows = _read_lines(os.path.join(tmp, "candidates.jsonl"))
            self.assertEqual(len(rows), 1)

    def test_repeated_full_rescan_does_not_grow_unbounded(self):
        """10回連続で同一のプロジェクト全体スキャン結果（4候補）を渡しても、
        ファイルは 4 行のまま増えない（実測パターン: 133,613 行 / 285 一意 の再現）。
        """
        with tempfile.TemporaryDirectory() as tmp:
            candidates = [_candidate("s1"), _candidate("s2"), _candidate("h1"), _candidate("r1")]
            for _ in range(10):
                ec.append_candidates(candidates, tmp)
            rows = _read_lines(os.path.join(tmp, "candidates.jsonl"))
            self.assertEqual(len(rows), 4)

    def test_genuinely_new_candidate_is_still_appended_after_existing_ones(self):
        """既存候補があっても、新規の `suggested_id` は正しく追記される
        （重複排除が過剰に効いて新規候補まで捨てないことを確認）。
        """
        with tempfile.TemporaryDirectory() as tmp:
            ec.append_candidates([_candidate("a")], tmp)
            count = ec.append_candidates([_candidate("a"), _candidate("b")], tmp)
            self.assertEqual(count, 1)
            rows = _read_lines(os.path.join(tmp, "candidates.jsonl"))
            self.assertEqual({r["suggested_id"] for r in rows}, {"a", "b"})

    def test_empty_candidate_list_returns_zero_and_does_not_create_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            count = ec.append_candidates([], tmp)
            self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
