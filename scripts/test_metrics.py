#!/usr/bin/env python3
"""
test_metrics.py: `scripts/metrics.py` の計数が正しいことを固定する。

背景（Phase 07 / Validator 6 巡目 Suggestion #13）:
  `metrics.py` は「成果物に書く数値を手で書かない」ための道具である。
  その計数自体が壊れると、**壊れたことに気づけないまま成果物へ伝播する**
  （Critical #3 / #11 / #19 / #20 と同じ型が、より検出しにくい形で再発する）。

  特に危険なのは「正規表現が空振りしても 0 を返して静かに通る」ことである。
  そのため各計数について **0 でない期待値** を持つフィクスチャで検証する。
"""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import unittest
import tempfile
import importlib.util
from pathlib import Path
from unittest import mock

_SPEC = importlib.util.spec_from_file_location(
    "metrics", str(Path(__file__).resolve().parent / "metrics.py"))
mt = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(mt)


class TestCountAllowlist(unittest.TestCase):
    """`ref` / `scope` / `reason` を欠くエントリは無効（抑制もされない）。"""

    def _write(self, tmp, entries):
        d = Path(tmp) / "docs"
        d.mkdir(parents=True, exist_ok=True)
        (d / "spec-check-allowlist.json").write_text(
            json.dumps({"entries": entries}, ensure_ascii=False), encoding="utf-8")
        return str(tmp)

    def test_counts_valid_only(self):
        with tempfile.TemporaryDirectory() as t:
            root = self._write(t, [
                {"ref": "a", "scope": "docs/x.md", "reason": "r", "section": "形式"},
                {"ref": "b", "scope": "*", "reason": "r", "section": "形式"},
                {"ref": "c", "scope": "docs/x.md"},                      # reason なし → 無効
                {"ref": "d", "reason": "r"},                             # scope なし → 無効
                {"scope": "docs/x.md", "reason": "r"},                   # ref なし → 無効
            ])
            self.assertEqual(mt.count_allowlist(root), (2, 0))

    def test_counts_forward_refs(self):
        with tempfile.TemporaryDirectory() as t:
            root = self._write(t, [
                {"ref": "a", "scope": "docs/x.md", "reason": "r", "section": "形式"},
                {"ref": "b", "scope": "docs/x.md", "reason": "r",
                 "section": "Iteration 2 / 3 の成果物（前方参照）"},
                {"ref": "c", "scope": "docs/x.md", "reason": "r",
                 "section": "Iteration 2 / 3 の成果物（前方参照）"},
            ])
            self.assertEqual(mt.count_allowlist(root), (3, 2))

    def test_agrees_with_spec_check_loader(self):
        """`spec_check.load_allowlist()` と同じ判定であること（二重定義のずれ防止）。"""
        spec = importlib.util.spec_from_file_location(
            "spec_check", str(Path(__file__).resolve().parent / "spec_check.py"))
        sc = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sc)
        root = str(Path(__file__).resolve().parent.parent)
        self.assertEqual(mt.count_allowlist(root)[0], len(sc.load_allowlist(root)))


class TestCountPermissions(unittest.TestCase):
    def test_counts_three_buckets(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t) / ".claude"
            d.mkdir(parents=True)
            (d / "settings.json").write_text(json.dumps(
                {"permissions": {"allow": ["a", "b"], "deny": ["c"], "ask": []}}), encoding="utf-8")
            self.assertEqual(mt.count_permissions(t), {"allow": 2, "deny": 1, "ask": 0})


class TestMaxIssueId(unittest.TestCase):
    def test_picks_max_not_last(self):
        """表の並び順ではなく **最大値** を返すこと。"""
        with tempfile.TemporaryDirectory() as t:
            d = Path(t) / "docs"
            d.mkdir(parents=True)
            (d / "requirements.md").write_text(
                "| C-9 | x |\n| **C-47** | y |\n| C-12 | z |\n", encoding="utf-8")
            self.assertEqual(mt.max_issue_id(t), 47)

    def test_ignores_non_table_mentions(self):
        """本文中の `C-99` は課題表ではないので拾わない。"""
        with tempfile.TemporaryDirectory() as t:
            d = Path(t) / "docs"
            d.mkdir(parents=True)
            (d / "requirements.md").write_text(
                "C-99 について述べる。\n| C-3 | x |\n", encoding="utf-8")
            self.assertEqual(mt.max_issue_id(t), 3)


class TestCountArticles(unittest.TestCase):
    def test_counts_headings_only(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t) / "docs"
            d.mkdir(parents=True)
            (d / "constitution.md").write_text(
                "## 第1条: a\n本文で第2条に言及する\n## 第2条: b\n### 第3条 は見出しレベルが違う\n",
                encoding="utf-8")
            self.assertEqual(mt.count_articles(t), 2)


class TestRealProject(unittest.TestCase):
    """このリポジトリの実データに対して **空振り（黙って 0 を返す）** が起きないこと。

    C-55: 実データに固定してよいのは **不変条件** であって **状態** ではない。
    ツールキット単体（`/init-task` を実行する前）では `docs/` に仕様ファイルが無く、
    0 が**正しい答え**になる。したがって「入力が存在するのに 0 が返る」ことだけを欠陥とみなし、
    入力が無い場合は 0 が返ることを積極的に確かめる。
    """

    def test_no_silent_zero(self):
        root = Path(__file__).resolve().parent.parent
        r = str(root)

        # settings.json はツールキット本体に必ずあるので、常に非 0 を要求する
        for k, v in mt.count_permissions(r).items():
            self.assertGreater(v, 0, f"permissions.{k} が 0（settings.json の解析が空振りした）")

        # 許可リスト: entries があれば非 0、無ければ 0。どちらも「空振りでない」ことの検査になる
        alw = root / "docs" / "spec-check-allowlist.json"
        if alw.is_file():
            entries = json.loads(alw.read_text(encoding="utf-8")).get("entries", [])
            n, fwd = mt.count_allowlist(r)
            self.assertGreaterEqual(fwd, 0)
            if entries:
                self.assertGreater(n, 0, "entries があるのに有効エントリ 0（空振り）")
            else:
                self.assertEqual(n, 0, "entries が空なのに 0 以外が返った")

        # 課題 ID と憲法の条数: 出所となる仕様ファイルがあるときだけ非 0 を要求する
        if (root / "docs" / "requirements.md").is_file():
            self.assertGreater(mt.max_issue_id(r), 0, "requirements.md があるのに課題 ID が 0（空振り）")
        if (root / "docs" / "constitution.md").is_file():
            self.assertGreater(mt.count_articles(r), 0, "constitution.md があるのに条数が 0（空振り）")


class TestOutsideGitRepo(unittest.TestCase):
    """v15.1: git リポジトリの外でも落ちず、`git ls-files` の件数を None で返すこと。

    旧実装は `git ls-files ... | wc -l` の出力（`0` + git の stderr）を int() して ValueError で落ちた。
    """

    def test_negative_collect_outside_git_repo_does_not_crash(self):
        cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as t:
            # 上位ディレクトリがたまたま git 管理下でも、確実に「git 管理外」にする
            env = {"GIT_DIR": str(Path(t) / "no-such-git-dir"), "GIT_CEILING_DIRECTORIES": t}
            try:
                with mock.patch.dict(os.environ, env):
                    m = mt.collect(t)
            finally:
                os.chdir(cwd)          # collect() は chdir する
        self.assertIsNone(m["tracked_files_docs_skills_claude"])

    @unittest.skipUnless(shutil.which("git"), "git が無い")
    def test_count_tracked_files_in_git_repo(self):
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / "docs").mkdir()
            (Path(t) / "docs" / "a.md").write_text("x", encoding="utf-8")
            (Path(t) / "other.md").write_text("x", encoding="utf-8")
            env = {"GIT_CEILING_DIRECTORIES": str(Path(t).parent)}
            with mock.patch.dict(os.environ, env):
                subprocess.run(["git", "init", "-q"], cwd=t, check=True)
                subprocess.run(["git", "add", "."], cwd=t, check=True)
                self.assertEqual(mt.count_tracked_files(t), 1)   # docs/a.md のみ


class TestPytestFailureVisible(unittest.TestCase):
    """v15.1: `--markdown` が pytest の失敗を隠さないこと。

    旧実装の表は passed 件数だけで exit 0 だった。failed 件数と exit code の行を足し、
    pytest が非 0 ならスクリプトも非 0 で終わる（**意図的な契約変更**）。
    既存の行とラベルは変えない（README / docs が引用している）。
    """

    BASE = {"pytest_passed": 10, "spec_check_findings": 0, "permissions": None}

    def _main(self, metrics, *flags):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(mt, "collect", return_value=dict(metrics)), \
                mock.patch.object(sys, "argv", ["metrics.py", *flags]), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = mt.main()
        return rc, out.getvalue(), err.getvalue()

    def test_negative_markdown_reports_failures_and_exits_nonzero(self):
        rc, out, err = self._main(dict(self.BASE, pytest_failed=3, pytest_exit=1), "--markdown")
        self.assertNotEqual(rc, 0)
        self.assertIn("| `python3 -m pytest scripts/ -q` の failed 件数 | **3** |", out)
        self.assertIn("| `python3 -m pytest scripts/ -q` の exit code | **1** |", out)
        self.assertIn("exit 1", err)

    def test_negative_uncountable_failures_are_shown_as_na(self):
        """収集エラーなどで failed を数えられなくても行を省略しない。"""
        rc, out, _ = self._main(dict(self.BASE, pytest_failed=None, pytest_exit=2), "--markdown")
        self.assertNotEqual(rc, 0)
        self.assertIn("| `python3 -m pytest scripts/ -q` の failed 件数 | **n/a** |", out)

    def test_green_run_keeps_existing_rows_and_exit_zero(self):
        rc, out, err = self._main(dict(self.BASE, pytest_failed=0, pytest_exit=0), "--markdown")
        self.assertEqual(rc, 0)
        self.assertIn("| `python3 -m pytest scripts/ -q` | **10** |", out)   # 既存の行はそのまま
        self.assertIn("| `python3 scripts/spec_check.py` の検出件数 | **0** |", out)
        self.assertEqual(err, "")

    def test_json_mode_also_exits_nonzero_on_pytest_failure(self):
        rc, out, _ = self._main(dict(self.BASE, pytest_failed=1, pytest_exit=1), "--json")
        self.assertNotEqual(rc, 0)
        self.assertEqual(json.loads(out)["pytest_failed"], 1)

    def test_pytest_failed_count(self):
        self.assertEqual(mt.pytest_failed_count(
            "FAILED a.py::t - 9 failed?\n3 failed, 10 passed in 1.0s\n", 1), 3)
        self.assertEqual(mt.pytest_failed_count("10 passed in 1.0s\n", 0), 0)
        # 失敗したのに 0 を返して静かに通らない
        self.assertIsNone(mt.pytest_failed_count("ERROR: file or directory not found\n", 4))


if __name__ == "__main__":
    unittest.main()
