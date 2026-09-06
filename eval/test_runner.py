#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_runner.py — `eval/runner.py` の回帰テスト（R-19 / R-20）。

**正例と負例の両方を含む**（`skills/phase-11/SKILL.md` Quality Criteria）。
実際の `claude -p` は呼ばない（コスト・非決定性・認証依存を避けるため）。
`subprocess.run` を差し替えて、`docs/io-spec.md` §6 で定義した stream-json 相当の
フィクスチャを与え、`runner.py` がその定義どおりに turns/retries/tool_calls を
計算することを確認する。

素通りする入力を自分で探してから出す（Phase 07 の 10 巡目の教訓）:
- 実行失敗（`claude` が見つからない / タイムアウト）
- Judge の応答が JSON として解釈できない
- `final_result` が存在しない（stream が空 / result 行が無い）
"""
import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import runner as R  # noqa: E402


def _ndjson(events):
    return "\n".join(json.dumps(e) for e in events) + "\n"


def _fake_completed_process(stdout, returncode=0):
    return subprocess.CompletedProcess(args=["claude"], returncode=returncode, stdout=stdout)


# ============================================================ compute_trajectory（正例）
class TestComputeTrajectory(unittest.TestCase):
    def test_counts_turns_retries_tool_calls_from_definition(self):
        """docs/io-spec.md §6: turns=num_turns, retries=denials+is_error件数, tool_calls=tool_use件数。"""
        events = [
            {"type": "system", "subtype": "init"},
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Bash", "input": {}},
            ]}},
            {"type": "user", "message": {"content": [
                {"type": "tool_result", "is_error": True, "content": "boom"},
            ]}},
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Read", "input": {}},
            ]}},
            {"type": "user", "message": {"content": [
                {"type": "tool_result", "is_error": False, "content": "ok"},
            ]}},
            {"type": "result", "num_turns": 3, "permission_denials": [{"tool_name": "Bash"}],
             "session_id": "sess-1", "duration_ms": 4242, "total_cost_usd": 0.05},
        ]
        final = events[-1]
        t = R.compute_trajectory(events, final)
        self.assertEqual(t["turns"], 3)
        # retries = permission_denials(1) + tool_result is_error件数(1) = 2
        self.assertEqual(t["retries"], 2)
        self.assertEqual(t["tool_calls"], 2)
        self.assertEqual(t["session_id"], "sess-1")
        self.assertEqual(t["cost_usd"], 0.05)

    def test_zero_denials_and_zero_errors(self):
        events = [
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "hi"}]}},
            {"type": "result", "num_turns": 1, "permission_denials": [], "session_id": "s", "duration_ms": 10,
             "total_cost_usd": 0.001},
        ]
        t = R.compute_trajectory(events, events[-1])
        self.assertEqual(t["turns"], 1)
        self.assertEqual(t["retries"], 0)
        self.assertEqual(t["tool_calls"], 0)


# ============================================================ compute_trajectory（負例: 取得不能）
class TestComputeTrajectoryMissing(unittest.TestCase):
    def test_final_result_none_yields_unknown_not_guessed(self):
        """final_result が無い(=結果行を得られなかった)場合は unknown。推測値を書かない（§6.5）。"""
        t = R.compute_trajectory(events=[], final_result=None)
        self.assertEqual(t["turns"], "unknown")
        self.assertEqual(t["retries"], "unknown")
        self.assertEqual(t["tool_calls"], "unknown")
        self.assertEqual(t["session_id"], "unknown")

    def test_malformed_permission_denials_yields_unknown_retries(self):
        """permission_denials がリストでない(壊れた出力)場合、決め打ちで0にせず unknown にする。"""
        events = [{"type": "result", "num_turns": 5, "permission_denials": "not-a-list", "session_id": "s"}]
        t = R.compute_trajectory(events, events[-1])
        self.assertEqual(t["turns"], 5)
        self.assertEqual(t["retries"], "unknown")


# ============================================================ run_claude_p（負例: 実行失敗）
class TestRunClaudePFailureModes(unittest.TestCase):
    def test_command_not_found_raises_runner_error(self):
        with mock.patch.object(R.subprocess, "run", side_effect=FileNotFoundError("claude")):
            with self.assertRaises(R.RunnerError):
                R.run_claude_p("hi", cwd="/tmp", model="haiku")

    def test_timeout_returns_no_final_result_not_a_crash(self):
        exc = subprocess.TimeoutExpired(cmd=["claude"], timeout=1, output="partial")
        with mock.patch.object(R.subprocess, "run", side_effect=exc):
            events, final, code, raw = R.run_claude_p("hi", cwd="/tmp", model="haiku", timeout=1)
        self.assertEqual(final, None)
        self.assertEqual(code, -1)

    def test_non_json_noise_lines_are_ignored_not_crashing(self):
        """stream-json 以外の雑音行（進捗表示等）で json.loads が例外を出しても落ちない。"""
        stdout = "Loading...\n" + _ndjson([{"type": "result", "num_turns": 1, "permission_denials": [],
                                             "session_id": "s"}])
        with mock.patch.object(R.subprocess, "run", return_value=_fake_completed_process(stdout)):
            events, final, code, raw = R.run_claude_p("hi", cwd="/tmp", model="haiku")
        self.assertIsNotNone(final)
        self.assertEqual(final["num_turns"], 1)


# ============================================================ Judge 応答の解釈（正例・負例）
class TestExtractJsonObject(unittest.TestCase):
    def test_pure_json(self):
        obj = R.extract_json_object('{"scores": {"correctness": 5}}')
        self.assertEqual(obj["scores"]["correctness"], 5)

    def test_json_with_surrounding_prose_is_still_extracted(self):
        text = "採点結果です。\n{\"scores\": {\"correctness\": 4}}\nご確認ください。"
        obj = R.extract_json_object(text)
        self.assertEqual(obj["scores"]["correctness"], 4)

    def test_malformed_json_returns_none_not_partial_guess(self):
        """Judge 応答不正（負例）: JSON として壊れている場合は None。適当に補完しない。"""
        obj = R.extract_json_object("{scores: not valid json,,,}")
        self.assertIsNone(obj)

    def test_no_braces_returns_none(self):
        self.assertIsNone(R.extract_json_object("採点できませんでした"))

    def test_none_input_returns_none(self):
        self.assertIsNone(R.extract_json_object(None))


# ============================================================ read_agent_body
class TestReadAgentBody(unittest.TestCase):
    def test_strips_frontmatter(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "agent.md"
            p.write_text("---\nname: x\ntools: Read\n---\n\n# 本文\n本文だけ残る\n", encoding="utf-8")
            body = R.read_agent_body(p)
            self.assertNotIn("name: x", body)
            self.assertIn("本文だけ残る", body)

    def test_missing_file_raises_runner_error(self):
        with self.assertRaises(R.RunnerError):
            R.read_agent_body(Path("/nonexistent/eval-judge.md"))

    def test_real_eval_judge_agent_is_read_only(self):
        """本物の .claude/agents/eval-judge.md の frontmatter が読み取り専用ツールのみであること。"""
        real_path = R.ROOT / ".claude" / "agents" / "eval-judge.md"
        text = real_path.read_text(encoding="utf-8")
        self.assertIn("disallowedTools: Write, Edit, Bash", text)
        self.assertNotIn("tools: Read, Glob, Grep, Bash", text)


# ============================================================ run_scenario_live（正例・負例）
class TestRunScenarioLive(unittest.TestCase):
    def test_missing_scenario_raises_runner_error(self):
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises(R.RunnerError):
                R.run_scenario_live("T1_research", "haiku", 60, scenarios_dir=Path(t))

    def test_live_success_produces_deliverable_and_trajectory(self):
        with tempfile.TemporaryDirectory() as scen_root:
            sdir = Path(scen_root) / "T1_research"
            sdir.mkdir(parents=True)
            (sdir / "task.md").write_text("# タスク\nダミー課題\n", encoding="utf-8")

            def fake_run(cmd, cwd, **kwargs):
                # runner が指示した保存先(prompt 内の絶対パス)へ実際にファイルを書く
                out_path = Path(cwd) / "deliverable.md"
                out_path.write_text("# 生成された成果物\n", encoding="utf-8")
                stdout = _ndjson([
                    {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Write"}]}},
                    {"type": "result", "num_turns": 2, "permission_denials": [], "session_id": "sess-live",
                     "duration_ms": 1000, "total_cost_usd": 0.02},
                ])
                return _fake_completed_process(stdout)

            with mock.patch.object(R.subprocess, "run", side_effect=fake_run):
                result = R.run_scenario_live("T1_research", "haiku", 60, scenarios_dir=Path(scen_root))

            self.assertEqual(result["exit_code"], 0)
            self.assertIsNotNone(result["deliverable_text"])
            self.assertEqual(result["trajectory"]["turns"], 2)
            self.assertEqual(result["trajectory"]["tool_calls"], 1)

    def test_deliverable_not_written_is_reported_not_faked(self):
        """成果物が保存されなかった場合、deliverable_text は None のまま（捏造しない）。"""
        with tempfile.TemporaryDirectory() as scen_root:
            sdir = Path(scen_root) / "T1_research"
            sdir.mkdir(parents=True)
            (sdir / "task.md").write_text("# タスク\n", encoding="utf-8")

            stdout = _ndjson([{"type": "result", "num_turns": 1, "permission_denials": [], "session_id": "s"}])
            with mock.patch.object(R.subprocess, "run", return_value=_fake_completed_process(stdout)):
                result = R.run_scenario_live("T1_research", "haiku", 60, scenarios_dir=Path(scen_root))
            self.assertIsNone(result["deliverable_text"])


# ============================================================ run_judge_live（正例・負例）
class TestRunJudgeLive(unittest.TestCase):
    def _fixture_dirs(self, tmp):
        scen_root = Path(tmp) / "scenarios"
        sdir = scen_root / "T1_research"
        sdir.mkdir(parents=True)
        (sdir / "checklist.json").write_text(json.dumps({"checklist": []}), encoding="utf-8")
        rubric_path = Path(tmp) / "rubric.json"
        rubric_path.write_text(json.dumps({"axes": [{"key": "correctness"}]}), encoding="utf-8")
        agent_path = Path(tmp) / "eval-judge.md"
        agent_path.write_text("---\ntools: Read, Glob, Grep\n---\n採点してください\n", encoding="utf-8")
        return scen_root, rubric_path, agent_path

    def test_judge_uses_read_only_tools_flag(self):
        """Judge 呼び出しの引数に --tools Read,Glob,Grep が含まれる（技術的な読み取り専用強制）。"""
        with tempfile.TemporaryDirectory() as t:
            scen_root, rubric_path, agent_path = self._fixture_dirs(t)
            captured_cmd = {}

            def fake_run(cmd, cwd, **kwargs):
                captured_cmd["cmd"] = cmd
                stdout = _ndjson([{"type": "result", "num_turns": 1, "permission_denials": [],
                                    "session_id": "judge-1",
                                    "result": '{"scores": {"correctness": 5}}'}])
                return _fake_completed_process(stdout)

            with mock.patch.object(R.subprocess, "run", side_effect=fake_run):
                result = R.run_judge_live("T1_research", "本文", "haiku", 60,
                                           scenarios_dir=scen_root, rubric_path=rubric_path,
                                           judge_agent_path=agent_path)

            self.assertIn("--tools", captured_cmd["cmd"])
            idx = captured_cmd["cmd"].index("--tools")
            self.assertEqual(captured_cmd["cmd"][idx + 1], "Read,Glob,Grep")
            self.assertNotIn("Bash", captured_cmd["cmd"][idx + 1])
            self.assertEqual(result["score"]["scores"]["correctness"], 5)

    def test_judge_invalid_response_yields_none_score(self):
        """Judge 応答不正（負例）: score.json として解釈できない応答は None であって、既定値の捏造ではない。"""
        with tempfile.TemporaryDirectory() as t:
            scen_root, rubric_path, agent_path = self._fixture_dirs(t)
            stdout = _ndjson([{"type": "result", "num_turns": 1, "permission_denials": [],
                                "session_id": "judge-2", "result": "採点できませんでした（壊れた応答）"}])
            with mock.patch.object(R.subprocess, "run", return_value=_fake_completed_process(stdout)):
                result = R.run_judge_live("T1_research", "本文", "haiku", 60,
                                           scenarios_dir=scen_root, rubric_path=rubric_path,
                                           judge_agent_path=agent_path)
            self.assertIsNone(result["score"])

    def test_missing_checklist_raises_runner_error(self):
        with tempfile.TemporaryDirectory() as t:
            _, rubric_path, agent_path = self._fixture_dirs(t)
            empty_scen_root = Path(t) / "empty-scenarios"
            empty_scen_root.mkdir()
            with self.assertRaises(R.RunnerError):
                R.run_judge_live("T1_research", "本文", "haiku", 60,
                                  scenarios_dir=empty_scen_root, rubric_path=rubric_path,
                                  judge_agent_path=agent_path)


# ============================================================ CSV 出力（第4条: summary.csv に触れない）
class TestTrajectoryCsv(unittest.TestCase):
    def test_appends_header_once_and_rows_after(self):
        with tempfile.TemporaryDirectory() as t:
            csv_path = Path(t) / "summary_trajectory.csv"
            R.append_trajectory_row(R.not_run_row("2026-09-06", "v15.0-smoke", "T1_research", "haiku"), csv_path)
            R.append_trajectory_row(R.not_run_row("2026-09-06", "v15.0-smoke", "T2_implement", "haiku"), csv_path)

            with csv_path.open(encoding="utf-8", newline="") as f:
                reader = list(csv.reader(f))
        self.assertEqual(reader[0], R.TRAJECTORY_HEADER)
        self.assertEqual(len(reader), 3)  # header + 2 rows
        self.assertEqual(reader[1][R.TRAJECTORY_HEADER.index("source")], "not_run")
        self.assertEqual(reader[1][R.TRAJECTORY_HEADER.index("turns")], "unknown")

    def test_never_writes_to_real_summary_csv(self):
        """runner.py のどの関数も eval/summary.csv というパス文字列を扱わない（第4条）。"""
        source = Path(R.__file__).read_text(encoding="utf-8")
        self.assertNotIn('"summary.csv"', source)
        self.assertNotIn("'summary.csv'", source)


# ============================================================ main()（正例・負例を通しで確認）
class TestMainDryRunDefault(unittest.TestCase):
    def test_default_is_not_live_and_records_not_run(self):
        """--live を付けない既定動作。API 呼び出しを一切行わない（安全側のデフォルト）。"""
        with tempfile.TemporaryDirectory() as t:
            csv_path = Path(t) / "summary_trajectory.csv"
            with mock.patch.object(R.subprocess, "run") as mocked:
                code = R.main(["--scenario", "T1_research", "--iteration", "test", "--csv-path", str(csv_path)])
                mocked.assert_not_called()
            self.assertEqual(code, 0)
            with csv_path.open(encoding="utf-8", newline="") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(rows[0]["source"], "not_run")

    def test_live_execution_failure_is_reported_with_nonzero_exit(self):
        """--live 指定時にシナリオ実行自体が失敗したら exit code は非0（黙って PASS 扱いにしない）。"""
        with tempfile.TemporaryDirectory() as t:
            csv_path = Path(t) / "summary_trajectory.csv"
            with mock.patch.object(R.subprocess, "run", side_effect=FileNotFoundError("claude")):
                code = R.main(["--scenario", "T1_research", "--live", "--csv-path", str(csv_path)])
            self.assertNotEqual(code, 0)

    def test_live_timeout_writes_error_source_row(self):
        """タイムアウト等で `run_claude_p` が例外を送出せず
        (events=[], final_result=None, exit_code=-1, raw) を返した場合の経路（Validator Issue #4）。

        `RunnerError` を送出する経路（上記テスト）とは別に、`append_trajectory_row` が実際に
        呼ばれる本番同型の経路を通す。`docs/io-spec.md` §6.6 の3値のうち `source="error"` が
        CSV に書き込まれることをアサートする（`eval/runner.py` は本巡で変更していない。挙動は既存のまま）。
        """
        with tempfile.TemporaryDirectory() as t:
            csv_path = Path(t) / "summary_trajectory.csv"
            with mock.patch.object(
                R.subprocess, "run",
                side_effect=subprocess.TimeoutExpired(cmd=["claude"], timeout=600),
            ):
                code = R.main(["--scenario", "T1_research", "--live", "--csv-path", str(csv_path)])
            self.assertNotEqual(code, 0)
            with csv_path.open(encoding="utf-8", newline="") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["source"], "error")
            self.assertEqual(rows[0]["turns"], "unknown")
            self.assertEqual(rows[0]["retries"], "unknown")
            self.assertEqual(rows[0]["tool_calls"], "unknown")


if __name__ == "__main__":
    unittest.main()
