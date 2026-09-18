#!/usr/bin/env python3
"""
test_hooks.py: .claude/hooks/*.py の単体テスト（プロセス起動型）

対象 4 hook（check-docs-exist.py / remind-finalize.py / session-start-info.py /
check-validation-exists.py）× 正常/異常 = 8 件以上。各 hook は subprocess で起動し、
stdin に JSON を流して stdout の JSON と exit code を検証する（R-10: 不正入力でも exit 0）。
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / ".claude" / "hooks"


def run_hook(name, payload, timeout=20, env=None):
    """hook をプロセスとして起動し (exit_code, stdout, stderr) を返す。

    `CLAUDE_PROJECT_DIR` はテストを走らせているセッションから継承しない（v15.1 の hook は
    これをプロジェクトルートとして優先するため）。必要なテストだけ env で渡す。
    """
    base = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
    base.update(env or {})
    proc = subprocess.run(
        [sys.executable, str(HOOKS / name)],
        input=payload,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=base,
    )
    return proc.returncode, proc.stdout, proc.stderr


class TestHooksNeverCrash(unittest.TestCase):
    """R-10: 不正な stdin でも exit 0（ターンを止めない）"""

    def test_invalid_json_does_not_stop_turn(self):
        for name in [
            "check-docs-exist.py",
            "remind-finalize.py",
            "session-start-info.py",
            "check-validation-exists.py",
        ]:
            with self.subTest(hook=name):
                code, _out, _err = run_hook(name, "not-a-json")
                self.assertEqual(code, 0, "{} が非ゼロ終了した".format(name))


class TestCheckDocsExist(unittest.TestCase):
    """PreToolUse: outputs/ 書込前に docs/ の存在・仕様ファイルの充足を確認する"""

    def test_docs_complete_no_warning(self):
        """docs/_manifest.json の required_files が揃っていれば警告なし exit 0（正常系）"""
        with tempfile.TemporaryDirectory() as tmpdir:
            docs_dir = Path(tmpdir) / "docs"
            docs_dir.mkdir()
            (docs_dir / "requirements.md").write_text("# req", encoding="utf-8")
            (docs_dir / "_manifest.json").write_text(
                json.dumps({"required_files": ["requirements.md"]}), encoding="utf-8"
            )
            payload = json.dumps(
                {"cwd": tmpdir, "tool_input": {"file_path": "outputs/phase-01/foo.md"}}
            )
            code, out, _err = run_hook("check-docs-exist.py", payload)
            self.assertEqual(code, 0)
            self.assertNotIn("SDD警告", out)

    def test_manifest_missing_required_file_warns(self):
        """docs/_manifest.json の required_files に欠落があれば警告する"""
        with tempfile.TemporaryDirectory() as tmpdir:
            docs_dir = Path(tmpdir) / "docs"
            docs_dir.mkdir()
            (docs_dir / "_manifest.json").write_text(
                json.dumps({"required_files": ["requirements.md"]}), encoding="utf-8"
            )
            payload = json.dumps(
                {"cwd": tmpdir, "tool_input": {"file_path": "outputs/phase-01/foo.md"}}
            )
            code, out, _err = run_hook("check-docs-exist.py", payload)
            self.assertEqual(code, 0)
            message = json.loads(out)["systemMessage"]
            self.assertIn("SDD警告", message)
            self.assertIn("requirements.md", message)


class TestRemindFinalize(unittest.TestCase):
    """Stop: 確定スキーマ（hookSpecificOutput.permissionDecision）で継続指示を返す"""

    @staticmethod
    def _make_project(tmpdir):
        outputs_dir = Path(tmpdir) / "outputs" / "phase-01"
        outputs_dir.mkdir(parents=True)
        (outputs_dir / "report.md").write_text("dummy", encoding="utf-8")

    def test_pending_finalize_returns_hook_specific_output(self):
        """未完了フェーズ（成果物ありだが /finalize 未実行）→ 確定スキーマで継続指示（正常系）"""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_project(tmpdir)
            payload = json.dumps({"cwd": tmpdir, "session_id": "test-session-remind-1"})
            code, out, _err = run_hook("remind-finalize.py", payload)
            self.assertEqual(code, 0)
            data = json.loads(out)
            hook_output = data["hookSpecificOutput"]
            self.assertEqual(hook_output["hookEventName"], "Stop")
            self.assertEqual(hook_output["permissionDecision"], "deny")
            self.assertIn("additionalContext", hook_output)
            self.assertIn("permissionDecisionReason", hook_output)
            # 旧スキーマ（decision: "block"）への回帰がないこと
            self.assertNotIn("decision", data)

    def test_fire_count_limit_stops_permission_decision(self):
        """K-06: 同一 session_id で上限 2 回を超えたら permissionDecision を返さない"""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_project(tmpdir)
            payload = json.dumps({"cwd": tmpdir, "session_id": "test-session-remind-2"})

            results = []
            for _ in range(3):
                code, out, _err = run_hook("remind-finalize.py", payload)
                self.assertEqual(code, 0)
                results.append(json.loads(out))

            self.assertIn("hookSpecificOutput", results[0])
            self.assertIn("hookSpecificOutput", results[1])
            # 3 回目（上限 2 回を超過）は permissionDecision を含まない（リマインドのみ）
            self.assertNotIn("hookSpecificOutput", results[2])


class TestSessionStartInfo(unittest.TestCase):
    """SessionStart: 知識ベースの状態を要約表示する"""

    def test_normal_startup_exits_zero(self):
        """通常起動 → 情報表示 exit 0（正常系）"""
        payload = json.dumps({"cwd": str(ROOT)})
        code, _out, _err = run_hook("session-start-info.py", payload)
        self.assertEqual(code, 0)


class TestCheckValidationExists(unittest.TestCase):
    """PostToolUse: .metadata.json 書込後に .validation/ の有無を警告する（非ブロック）"""

    def test_missing_validation_warns(self):
        """.validation/ 無し → 警告 exit 0（正常系）"""
        with tempfile.TemporaryDirectory() as tmpdir:
            phase_dir = Path(tmpdir) / "outputs" / "phase-09"
            phase_dir.mkdir(parents=True)
            payload = json.dumps(
                {"cwd": tmpdir, "tool_input": {"file_path": "outputs/phase-09/.metadata.json"}}
            )
            code, out, _err = run_hook("check-validation-exists.py", payload)
            self.assertEqual(code, 0)
            message = json.loads(out)["systemMessage"]
            self.assertIn("SDD警告", message)
            self.assertIn(".validation", message)

    def test_validation_present_no_warning(self):
        """.validation/ が既にあれば警告しない（非ブロックの対照ケース）"""
        with tempfile.TemporaryDirectory() as tmpdir:
            phase_dir = Path(tmpdir) / "outputs" / "phase-09"
            (phase_dir / ".validation").mkdir(parents=True)
            payload = json.dumps(
                {"cwd": tmpdir, "tool_input": {"file_path": "outputs/phase-09/.metadata.json"}}
            )
            code, out, _err = run_hook("check-validation-exists.py", payload)
            self.assertEqual(code, 0)
            self.assertEqual(out, "")


class TestHooksV151(unittest.TestCase):
    """v15.1: 絶対パス・プロジェクト外・CLAUDE_PROJECT_DIR・出力キー・Stop の停止保証。"""

    @staticmethod
    def _empty_docs(tmpdir):
        (Path(tmpdir) / "docs").mkdir()

    def test_negative_absolute_path_under_outputs_is_checked(self):
        """Claude Code は file_path を絶対パスで渡す。v15.0 は startswith("outputs/") で素通りしていた。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._empty_docs(tmpdir)
            payload = json.dumps({"cwd": tmpdir, "tool_input": {
                "file_path": str(Path(tmpdir) / "outputs" / "phase-01" / "a.md")}})
            code, out, _err = run_hook("check-docs-exist.py", payload)
            self.assertEqual(code, 0)
            self.assertIn("SDD警告", json.loads(out)["systemMessage"])

    def test_path_outside_project_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._empty_docs(tmpdir)
            payload = json.dumps({"cwd": tmpdir, "tool_input": {
                "file_path": "/elsewhere/outputs/phase-01/a.md"}})
            code, out, _err = run_hook("check-docs-exist.py", payload)
            self.assertEqual((code, out), (0, ""))

    def test_path_not_under_outputs_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._empty_docs(tmpdir)
            payload = json.dumps({"cwd": tmpdir, "tool_input": {
                "file_path": str(Path(tmpdir) / "docs" / "x.md")}})
            code, out, _err = run_hook("check-docs-exist.py", payload)
            self.assertEqual((code, out), (0, ""))

    def test_claude_project_dir_takes_precedence_over_cwd(self):
        """セッションの cwd がサブディレクトリでもプロジェクトルートで判定する。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._empty_docs(tmpdir)
            payload = json.dumps({"cwd": str(Path(tmpdir) / "docs"), "tool_input": {
                "file_path": str(Path(tmpdir) / "outputs" / "phase-01" / "a.md")}})
            code, out, _err = run_hook("check-docs-exist.py", payload,
                                       env={"CLAUDE_PROJECT_DIR": tmpdir})
            self.assertIn("SDD警告", json.loads(out)["systemMessage"])

    def test_validation_hook_absolute_path_and_non_metadata_ignored(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "outputs" / "phase-02").mkdir(parents=True)
            md = str(Path(tmpdir) / "outputs" / "phase-02" / ".metadata.json")
            code, out, _err = run_hook("check-validation-exists.py",
                                       json.dumps({"cwd": tmpdir, "tool_input": {"file_path": md}}))
            self.assertIn(".validation", json.loads(out)["systemMessage"])
            other = str(Path(tmpdir) / "docs" / ".metadata.json")
            code, out, _err = run_hook("check-validation-exists.py",
                                       json.dumps({"cwd": tmpdir, "tool_input": {"file_path": other}}))
            self.assertEqual((code, out), (0, ""))

    def test_no_hook_prints_the_unrecognized_message_key(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._empty_docs(tmpdir)
            payload = json.dumps({"cwd": tmpdir, "tool_input": {"file_path": "outputs/phase-01/a.md"}})
            _code, out, _err = run_hook("check-docs-exist.py", payload)
            self.assertNotIn("message", json.loads(out))

    @staticmethod
    def _pending_project(tmpdir):
        d = Path(tmpdir) / "outputs" / "phase-01"
        d.mkdir(parents=True)
        (d / "report.md").write_text("x", encoding="utf-8")

    def test_negative_stop_hook_active_allows_stop(self):
        """stop_hook_active が真なら継続指示（hookSpecificOutput）を出さない。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._pending_project(tmpdir)
            payload = json.dumps({"cwd": tmpdir, "session_id": "s-active",
                                  "stop_hook_active": True})
            code, out, _err = run_hook("remind-finalize.py", payload)
            self.assertEqual(code, 0)
            data = json.loads(out)
            self.assertNotIn("hookSpecificOutput", data)
            self.assertIn("systemMessage", data)

    def test_negative_unwritable_counter_does_not_loop(self):
        """カウンタを書けない環境で継続指示を返し続けない（上限到達として扱う）。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._pending_project(tmpdir)
            hooks_dir = Path(tmpdir) / ".claude" / "hooks"
            hooks_dir.mkdir(parents=True)
            # .state を「ファイル」にしておくと makedirs が失敗する（chmod に頼らない）
            (hooks_dir / ".state").write_text("not a dir", encoding="utf-8")
            payload = json.dumps({"cwd": tmpdir, "session_id": "s-unwritable"})
            for _ in range(3):
                code, out, _err = run_hook("remind-finalize.py", payload)
                self.assertEqual(code, 0)
                self.assertNotIn("hookSpecificOutput", json.loads(out))


if __name__ == "__main__":
    unittest.main()
