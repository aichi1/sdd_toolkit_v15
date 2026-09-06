#!/usr/bin/env python3
"""
metrics.py: 成果物に書く数値を**実行して**生成する。

背景（Phase 07 / Critical #3, #11, #19, #20）:
  成果物に手で書いた数値が実体からずれる失敗を**4 回**繰り返した。

    #3  「8 件、修正済み」→ 実際は注記を足しただけ（8 insertions / 0 deletions）
    #11 `spec-check-report.md` が古い方式のまま「4 件」→ 実際は 0 件
    #19 「許可リスト 38 件」→ 実際は 34 件
    #20 CLAUDE.md が「132 passed」→ **その数字はどの実行にも存在しない**

  いずれも「実装を変えたあとに記録を更新しなかった」「数え直さずに書いた」ことによる。
  **数値は手で書かず、本スクリプトの出力を引く。**

使い方:
  python3 scripts/metrics.py              # 人が読む形式
  python3 scripts/metrics.py --json       # 機械可読
  python3 scripts/metrics.py --markdown   # 成果物に貼る表
"""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path


def _run(cmd):
    p = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def count_allowlist(root: str) -> tuple:
    """許可リストの (有効エントリ数, うち前方参照数)。

    `ref` / `scope` / `reason` のいずれかを欠くエントリは **無効**（抑制もされない）。
    `spec_check.load_allowlist()` と同じ判定であること。
    """
    d = json.loads((Path(root) / "docs" / "spec-check-allowlist.json").read_text(encoding="utf-8"))
    valid = [e for e in d.get("entries", [])
             if e.get("ref") and e.get("scope") and e.get("reason")]
    fwd = [e for e in valid if "前方参照" in str(e.get("section", ""))]
    return len(valid), len(fwd)


def count_permissions(root: str) -> dict:
    s = json.loads((Path(root) / ".claude" / "settings.json").read_text(encoding="utf-8"))["permissions"]
    return {k: len(s.get(k, [])) for k in ("allow", "deny", "ask")}


def max_issue_id(root: str):
    """`docs/requirements.md` の課題表から最大の C-NN を返す。"""
    s = (Path(root) / "docs" / "requirements.md").read_text(encoding="utf-8")
    ids = sorted({int(x) for x in re.findall(r"\| \*{0,2}C-(\d+)\*{0,2} \|", s)})
    return max(ids) if ids else None


def count_articles(root: str) -> int:
    s = (Path(root) / "docs" / "constitution.md").read_text(encoding="utf-8")
    return len(re.findall(r"^## 第\d+条", s, re.MULTILINE))


def collect(root: str) -> dict:
    os.chdir(root)
    env = "PYTHONDONTWRITEBYTECODE=1 "
    m = {}

    rc, out = _run(env + "python3 -m pytest scripts/ -q")
    n = re.search(r"(\d+) passed", out)
    m["pytest_passed"] = int(n.group(1)) if n else None
    m["pytest_exit"] = rc

    for name, path in (("test_spec_check", "scripts/test_spec_check.py"),
                       ("test_check_constitution", "scripts/test_check_constitution.py"),
                       ("test_knowledge_curator", "scripts/test_knowledge_curator.py"),
                       ("test_validate_outputs", "scripts/test_validate_outputs.py"),
                       ("test_hooks", "scripts/test_hooks.py")):
        if Path(path).is_file():
            _, o = _run(env + f"python3 -m pytest {path} -q")
            g = re.search(r"(\d+) passed", o)
            m[f"{name}_count"] = int(g.group(1)) if g else None

    rc, out = _run(env + "python3 scripts/spec_check.py")
    g = re.search(r"Result: (\d+) 件", out)
    m["spec_check_findings"] = int(g.group(1)) if g else None
    m["spec_check_exit"] = rc

    try:
        m["allowlist_entries"], m["allowlist_forward_refs"] = count_allowlist(root)
    except Exception:
        m["allowlist_entries"] = None
        m["allowlist_forward_refs"] = None

    try:
        m["permissions"] = count_permissions(root)
    except Exception:
        m["permissions"] = None

    m["commands"] = len(list(Path(".claude/commands").rglob("*.md"))) \
        if Path(".claude/commands").is_dir() else None
    m["hooks"] = len(list(Path(".claude/hooks").glob("*.py"))) \
        if Path(".claude/hooks").is_dir() else None

    try:
        m["issues_max"] = max_issue_id(root)
    except Exception:
        m["issues_max"] = None

    try:
        m["constitution_articles"] = count_articles(root)
    except Exception:
        m["constitution_articles"] = None

    rc, out = _run("git ls-files docs skills .claude | wc -l")
    m["tracked_files_docs_skills_claude"] = int(out.strip()) if rc == 0 else None
    return m


LABELS = {
    "pytest_passed": "`python3 -m pytest scripts/ -q`",
    "spec_check_findings": "`python3 scripts/spec_check.py` の検出件数",
    "allowlist_entries": "許可リストの有効エントリ数",
    "allowlist_forward_refs": "うち前方参照（作ったら消す）",
    "commands": "`.claude/commands/**/*.md`",
    "hooks": "`.claude/hooks/*.py`",
    "issues_max": "課題の最大 ID（C-NN）",
    "constitution_articles": "`docs/constitution.md` の条数",
    "tracked_files_docs_skills_claude": "`git ls-files docs skills .claude`",
}


def main():
    ap = argparse.ArgumentParser(description="成果物に書く数値を実行して生成する")
    ap.add_argument("--project-dir", default=".")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--markdown", action="store_true")
    a = ap.parse_args()
    m = collect(os.path.abspath(a.project_dir))

    if a.json:
        print(json.dumps(m, ensure_ascii=False, indent=2))
    elif a.markdown:
        print("| 指標 | 実測値 |")
        print("|------|--------|")
        for k, label in LABELS.items():
            if m.get(k) is not None:
                print(f"| {label} | **{m[k]}** |")
        if m.get("permissions"):
            p = m["permissions"]
            print(f"| `permissions` | allow **{p['allow']}** / deny **{p['deny']}** / ask **{p['ask']}** |")
    else:
        print("=== 実測値 ===\n")
        for k, v in m.items():
            print(f"  {k}: {v}")
        print("\n**成果物に書く数値は本スクリプトの出力を引くこと。** 手で書かない。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
