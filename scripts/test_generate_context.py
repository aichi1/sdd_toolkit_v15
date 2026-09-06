#!/usr/bin/env python3
"""
test_generate_context.py: scripts/generate_context.py の --output 削除 (C-33 案C) の回帰テスト

背景: `--output <任意パス>` は Write ツールなしに任意ファイルを上書きできる経路だった（C-33）。
      argparse の省略入力解決により `--o` まで短縮しても書き込めていたため、`--output` を狙い撃ちする
      deny では回避可能で根本対処にならない。よって `--output` オプション自体を削除した（案C）。

テストケース:
- 異常系: `--output <path> "task"` → returncode == 2（argparse の unrecognized arguments エラー）
- 異常系: `--o <path> "task"`（省略形）→ returncode == 2（迂回経路も塞がれていること）
- 正常系: 位置引数の task のみ（--output なし）→ returncode == 0 でファイル生成（後方互換）
- 正常系: `--kb-dir` 併用 → returncode == 0 で指定ディレクトリにファイル生成（後方互換）
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / "generate_context.py"


def run(args, env=None):
    """generate_context.py をプロセスとして起動し (returncode, stdout, stderr) を返す。"""
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)] + args,
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )
    return proc.returncode, proc.stdout, proc.stderr


class TestOutputOptionRemoved(unittest.TestCase):
    """C-33 案C: --output（および省略形 --o）が拒否されること"""

    def test_output_flag_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target = str(Path(tmpdir) / "evil.md")
            code, _out, err = run(["--output", target, "task description"])
            self.assertEqual(code, 2, f"--output が拒否されなかった (stderr={err})")
            self.assertFalse(
                Path(target).exists(), "--output が拒否されたのにファイルが生成された"
            )

    def test_output_abbreviation_rejected(self):
        """argparse の省略入力解決による --o までの短縮迂回も塞がれていること"""
        with tempfile.TemporaryDirectory() as tmpdir:
            target = str(Path(tmpdir) / "evil.md")
            code, _out, err = run(["--o", target, "task description"])
            self.assertEqual(code, 2, f"--o が拒否されなかった (stderr={err})")
            self.assertFalse(
                Path(target).exists(), "--o が拒否されたのにファイルが生成された"
            )


class TestBackwardCompatibility(unittest.TestCase):
    """正当な呼び出し形が従来どおり動作すること（後方互換の証拠）"""

    def test_positional_task_only(self):
        """引数なし（位置引数の task のみ、--kb-dir も --output もなし）→ returncode 0 でファイル生成。

        既定の kb-dir（~/.sdd-knowledge）を汚さないよう、HOME を一時ディレクトリに差し替える。
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            env = os.environ.copy()
            env["HOME"] = tmpdir
            code, out, err = run(["技術調査レポート サンプル"], env=env)
            self.assertEqual(code, 0, f"stderr={err}")
            expected = Path(tmpdir) / ".sdd-knowledge" / "active-context.md"
            self.assertTrue(expected.is_file(), f"{expected} が生成されていない")
            self.assertIn("Active context written to", out)

    def test_kb_dir_combination(self):
        """--kb-dir 併用 → returncode 0 で指定ディレクトリにファイル生成"""
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_dir = str(Path(tmpdir) / "kb")
            env = os.environ.copy()
            code, out, err = run(["--kb-dir", kb_dir, "検索クエリ"], env=env)
            self.assertEqual(code, 0, f"stderr={err}")
            self.assertTrue((Path(kb_dir) / "active-context.md").is_file())
            self.assertIn("Active context written to", out)


if __name__ == "__main__":
    unittest.main()
