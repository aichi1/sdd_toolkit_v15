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
import json
import unittest
import tempfile
import importlib.util
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
