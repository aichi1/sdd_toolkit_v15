#!/usr/bin/env python3
"""
spec_check.py: 仕様（docs/ と skills/）の機械検査可能な部分を検査する。

R-14 / Phase 07。**ファイルを一切変更しない。**

背景:
  Iteration 1 では **C-19**（存在しない `/recap` を検証手段に指定）と
  **C-38**（削除済みの `/agents` を D-01 の手順に指定）が計画時に混入し、
  実行して初めて判明した。本スクリプトはこの型 ——
  **存在しないものを参照している仕様** —— を実装前に検出する。

判定方式（オーナー決定 2026-09-05）:
  **許可リスト方式。ヒューリスティックは使わない。**

    resolved   `.claude/commands/` または `.claude/skills/<name>/SKILL.md` に実在する / ファイルが存在する
    builtin    Claude Code の組み込みコマンド（固定リスト）
    allowed    `docs/spec-check-allowlist.json` に明示されている
               （略記も前方参照もここに書く。**推測で解決しない**）
    unresolved 上のいずれでもない → **報告する**

  当初は「同じ行の否定語」「公式ドメインの URL」「文書レベルの宣言」「リスト構造」などで
  誤検出を抑えようとしたが、**3 巡の修正で Critical 10 件**が出た。
  自然言語の「指示か記録か」を正規表現で判定しようとしたことが原因である。
  パッチを足すたびに新しい回避経路が生まれた。

  許可リスト方式では**抑制がすべて 1 ファイルに現れる**。
  「冒頭に一言書けば通る」「URL を置けば通る」といった回避経路の概念そのものが消える。

使い方:
  python3 scripts/spec_check.py
  python3 scripts/spec_check.py --json
  python3 scripts/spec_check.py --check command_reference

exit code:
  0 = 欠陥なし   1 = 欠陥あり   2 = 実行エラー
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

# Claude Code の組み込みスラッシュコマンド（2.1.260 時点）。
# 出典: outputs/phase-01/claude-code-capabilities.md
BUILTIN_COMMANDS = {
    "clear", "help", "config", "doctor", "compact", "cost", "context", "memory",
    "rewind", "summarize", "goal", "artifacts", "tasks", "workflows", "loop",
    "fast", "resume", "review", "pr-comments", "vim", "terminal-setup",
    "add-dir", "bug", "exit", "quit", "login", "logout", "status", "model",
    "permissions", "hooks", "mcp", "ide", "install-github-app", "migrate-installer",
    "release-notes", "upgrade", "privacy-settings", "export", "todos", "output-style",
}

ALLOWLIST_PATH = "docs/spec-check-allowlist.json"
# 人間向けの説明。**パーサは読まない**（Markdown は説明用の表と本物の許可を区別できない）
ALLOWLIST_DOC = "docs/spec-check-allowlist.md"

# 参照の抽出。`/name` の直前が行頭・空白・開き括弧・バッククォート・全角の箇条書き記号のとき。
# URL の途中（`.com/docs`）やファイルパス（`.claude/commands/x.md`）を拾わないため。
#
# 直後の否定先読み（v15.1）: 名前の直後が `/`・ASCII 英数字・`_:-`、または `.` + ASCII 英数字なら
# コマンドではない。v15.0 は `/home/user/x.sh` を `/home`、`/usr/bin/git` を `/usr`、
# `/notes.md` を `/notes` としてコマンド扱いしていた（拡張子で除外するはずの `_looks_like_path()`
# は、名前の文字クラスに `.` が無いため一度も真にならないデッドコードだった）。
# ASCII に限るのは、日本語が直後に続く `/clarifyを` を従来どおりコマンドとして拾うため
# （`\w` は日本語にも一致する）。文末の `/cmd.` は `.` の後が英数字でないので拾う。
_REF = re.compile(r"(?:^|(?<=[\s`（(\[「『|・※●◆▪－★→]))/([a-z][a-z0-9:_-]*)"
                  r"(?![A-Za-z0-9_/:-]|\.[A-Za-z0-9])")


def load_allowlist(root: str) -> list:
    """`docs/spec-check-allowlist.json` から許可エントリを読む。

    **JSON を使う。** 当初は Markdown の表を読んでいたが、
    「ファイル内の 3 列の表」を許可とみなすため、**説明用の表・例示・却下した候補と
    本物の許可を区別できなかった**（Phase 07 の Critical #13 / #16 / #17）。
    実際、許可リスト文書内の「方式転換の経緯」を説明する表 4 行が
    許可エントリとして読み込まれていた（#19）。

    フェンスの種類（``` / ~~~）や入れ子を追う必要もなくなる。
    人間向けの説明は `docs/spec-check-allowlist.md` に残す。

    **理由（reason）が空のエントリは無効**とする（黙って通すための追加を防ぐ）。
    """
    p = Path(root) / ALLOWLIST_PATH
    if not p.is_file():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []
    out = []
    for e in data.get("entries", []) if isinstance(data, dict) else []:
        if not isinstance(e, dict):
            continue
        ref, scope, reason = e.get("ref"), e.get("scope"), e.get("reason")
        if not ref or not scope or not reason:
            continue
        out.append({"ref": str(ref).lstrip("/"), "scope": str(scope), "reason": str(reason)})
    return out


def _load_allowlist_section(root: str, key: str, field: str) -> list:
    """許可リスト JSON の `excludes` / `resolve_roots` を読む（v15.1）。

    `entries` と同じく**理由（reason）が空の要素は無効**。`"*"` は無効（検査全体を
    黙って止める経路になるため）。値は宣言の順に返す。
    """
    p = Path(root) / ALLOWLIST_PATH
    if not p.is_file():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []
    out = []
    for e in data.get(key, []) if isinstance(data, dict) else []:
        if not isinstance(e, dict):
            continue
        value, reason = e.get(field), e.get("reason")
        if not value or not reason or str(value).strip() in ("*", ".", "/"):
            continue
        out.append(str(value).strip().rstrip("/"))
    return out


def load_excludes(root: str) -> list:
    """走査しないファイル・ディレクトリ（`excludes[].scope`）。

    **履歴の記録**（`docs/CHANGELOG.md` など、過去に存在したファイルへの言及が正しい文書）を
    1 件ずつ許可するのではなく、ファイル単位で対象外にする。対象外にしたファイル数は
    毎回出力に表示する（抑制が見えなくならないように）。
    """
    return _load_allowlist_section(root, "excludes", "scope")


def load_resolve_roots(root: str) -> list:
    """ファイル参照の追加の解決先（`resolve_roots[].path`。プロジェクトルートからの相対）。

    製品を別リポジトリ（例: `product/app/`）に置き、仕様がその中のパスを製品ルート相対で
    書くプロジェクトのため。プロジェクトルートで見つからない参照を、宣言した順に各ルートで探す。
    """
    return _load_allowlist_section(root, "resolve_roots", "path")


def is_excluded(rel_path: str, excludes: list) -> bool:
    return any(_scope_matches(rel_path, s) for s in excludes)


def _scanned_files(root: str, scan_dirs: list, excluded_out=None):
    """走査対象の Markdown を (Path, 相対パス) で返す。許可リスト自体と `excludes` は除く。"""
    excludes = load_excludes(root)
    for d in scan_dirs:
        base = Path(root) / d
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*.md")):
            rel = p.relative_to(root).as_posix()
            if rel in (ALLOWLIST_PATH, ALLOWLIST_DOC):   # 許可リストとその説明は対象外
                continue
            if is_excluded(rel, excludes):
                if excluded_out is not None:
                    excluded_out.add(rel)
                continue
            yield p, rel


def _scope_matches(rel_path: str, scope: str) -> bool:
    """scope が rel_path に一致するか。**パスの境界で照合する。**

    当初は `rel_path.startswith(scope)` としていたため、
    `docs/tech` が `docs/tech2/b.md` まで許可していた（Validator が実測で指摘）。
    """
    if scope == "*":
        return True
    scope = scope.rstrip("/")
    return rel_path == scope or rel_path.startswith(scope + "/")


def is_allowed(name: str, rel_path: str, allowlist: list) -> bool:
    """その参照がそのファイルで許可されているか。"""
    return any(e["ref"] == name and _scope_matches(rel_path, e["scope"])
               for e in allowlist)


def real_commands(root: str) -> set:
    """`.claude/commands/**/*.md` と `.claude/skills/*/SKILL.md` から実在コマンド名を集める。

    サブディレクトリは名前空間（`extras/create-deck` → `extras:create-deck`）。

    **Phase 13 / C-28 / R-21**: 公式ドキュメント（`docs/requirements.md` C-28 が引用）に
    「Custom commands have been merged into skills. A file at `.claude/commands/deploy.md`
    and a skill at `.claude/skills/deploy/SKILL.md` both create `/deploy` and work the same
    way」とあるとおり、`.claude/commands/` と `.claude/skills/<name>/SKILL.md` は**どちらか
    一方が存在すれば解決済み**とみなす。一本化（コマンド実体を削除しスキルのみ残す）が
    このスクリプトの誤検出を引き起こさないようにするための変更（`docs/tech-stack.md` §7）。
    """
    out = set()
    cmd_base = Path(root) / ".claude" / "commands"
    if cmd_base.is_dir():
        for p in cmd_base.rglob("*.md"):
            rel = p.relative_to(cmd_base).with_suffix("").as_posix()
            out.add(rel.replace("/", ":"))
            out.add(rel.split("/")[-1])      # 名前空間なしでも解決できるように
    skills_base = Path(root) / ".claude" / "skills"
    if skills_base.is_dir():
        for p in skills_base.glob("*/SKILL.md"):
            out.add(p.parent.name)
    return out


# パスのプレースホルダ。`outputs/phase-NN/` `skills/phase-{N}/` のような雛形
_PATH_PLACEHOLDER = re.compile(r"(?:^|/)(?:phase-NN|phase-\{N\}|\{[^/}]+\}|<[^/>]+>|\*)")


def classify(name: str, rel_path: str, real: set, allowlist: list) -> str:
    """参照を 4 分類する。**ヒューリスティックは使わない。**"""
    if name in real:
        return "resolved"
    if name in BUILTIN_COMMANDS:
        return "builtin"
    if is_allowed(name, rel_path, allowlist):
        return "allowed"
    return "unresolved"


# 欠陥として報告する分類
DEFECT_KINDS = {"unresolved", "duplicate_id", "missing_id"}


def check_command_references(root: str, scan_dirs=None, excluded_out=None) -> list:
    """仕様が参照するコマンドのうち、実在せず許可もされていないものを検出する。"""
    root = os.path.abspath(root)
    scan_dirs = scan_dirs or ["docs", "skills", ".claude/rules"]
    real = real_commands(root)
    allowlist = load_allowlist(root)
    findings = []
    for p, rel in _scanned_files(root, scan_dirs, excluded_out):
        for i, line in enumerate(
                p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            for m in _REF.finditer(line):
                name = m.group(1)
                kind = classify(name, rel, real, allowlist)
                if kind not in DEFECT_KINDS:
                    continue
                findings.append({
                    "check": "command_reference", "file": rel, "line": i,
                    "reference": name, "kind": kind,
                    "message": f"`/{name}` は `.claude/commands/` にも "
                               f"`.claude/skills/{name}/SKILL.md` にも存在せず、"
                               f"`{ALLOWLIST_PATH}` にも記載がない",
                    "context": line.strip()[:120],
                })
    return findings


def check_file_references(root: str, scan_dirs=None, excluded_out=None) -> list:
    """仕様が参照するファイルパスのうち、実在せず許可もされていないものを検出する。

    プロジェクトルートで見つからなければ `resolve_roots` の各ルートでも探す（v15.1）。
    """
    root = os.path.abspath(root)
    scan_dirs = scan_dirs or ["docs", "skills"]
    pat = re.compile(r"`([a-zA-Z_][\w./-]*\.(?:md|py|json|yaml|yml|csv|sh))`")
    allowlist = load_allowlist(root)
    bases = [Path(root)] + [Path(root) / r for r in load_resolve_roots(root)]
    findings = []
    for p, rel in _scanned_files(root, scan_dirs, excluded_out):
        for i, line in enumerate(
                p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            for m in pat.finditer(line):
                tgt = m.group(1)
                # 裸のファイル名（`change-report.md`）は通称であってパスではない
                if "/" not in tgt:
                    continue
                if _PATH_PLACEHOLDER.search(tgt) or tgt.startswith("http"):
                    continue
                if any((b / tgt).exists() for b in bases):
                    continue
                if is_allowed(tgt, rel, allowlist):
                    continue
                findings.append({
                    "check": "file_reference", "file": rel, "line": i,
                    "reference": tgt, "kind": "unresolved",
                    "message": f"`{tgt}` が存在せず、`{ALLOWLIST_PATH}` にも記載がない",
                    "context": line.strip()[:120],
                })
    return findings


# 要件 ID の定義行。`| C-19 |` `| **C-38** |` `| ~~C-19~~ |` `| ~~**C-21**~~ |` を拾う
_ID_ROW = re.compile(r"^\|\s*(?:~~)?\s*(?:\*\*)?\s*([RCS])-(\d+)\s*(?:\*\*)?\s*(?:~~)?\s*\|")


def check_requirement_ids(root: str, scan_dirs=None) -> list:
    """要件 ID の**重複と欠番**を検出する（`skills/phase-07/SKILL.md` Procedure Step 4）。

    **欠番は Phase 08 で規約が決まってから実装した。**
    `docs/requirements.md` §9.2 が「**取り下げた ID は削除せず `~~C-19~~` と
    打ち消し線で残す。番号を再利用しない**」と定めたため、
    **欠番は原則として存在しない**ことが規約上の帰結になり、判定できるようになった。
    規約が無い時点で実装していれば、打ち消し線の 4 件（C-19/20/21/25）を誤検出していた。

    抑制経路は兄弟の 2 検査と**同じ 1 つだけ**である ——
    `docs/spec-check-allowlist.json` に `ref`（`C-01` など）と `scope`（`docs/requirements.md`）を書く。
    これ以外の抑制手段は無い。

    **コードフェンスの特別扱いはしない**（Phase 07 の Critical #37）。
    #33 の修正で「フェンス内は読まない」を入れたが、そのフェンス判定自体が
    (1) 種別（``` と ~~~）を区別せず入れ子で誤爆し、
    (2) 未閉鎖のフェンスがあると残り全行を**黙って**スキャン対象外にして exit=0 を返した。
    しかも兄弟 2 検査にはフェンス処理が無く、**新たな非対称**を作っていた。
    構造で抑制しようとするたびに穴が開く —— これは本フェーズが 3 巡かけて学んだことである。
    フェンス内の例示が重複 ID を含むなら、**許可リストに書く**（抑制はすべて 1 ファイルに現れる）。
    """
    root = os.path.abspath(root)
    rel_path = "docs/requirements.md"
    src = Path(root) / rel_path
    if not src.is_file():
        return []
    allowlist = load_allowlist(root)
    seen = {}
    findings = []
    for i, line in enumerate(src.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        m = _ID_ROW.match(line)
        if not m:
            continue
        ident = f"{m.group(1)}-{int(m.group(2)):02d}"
        if ident not in seen:
            seen[ident] = i
            continue
        if is_allowed(ident, rel_path, allowlist):
            continue
        findings.append({
            "check": "requirement_id", "file": rel_path, "line": i,
            "reference": ident, "kind": "duplicate_id",
            "message": f"要件 ID `{ident}` が重複している（初出 {seen[ident]} 行目）。"
                       f"意図的なら `{ALLOWLIST_PATH}` に記載する",
            "context": line.strip()[:120],
        })

    # 欠番（`docs/requirements.md` §9.2: 取り下げた ID も打ち消し線で残すため欠番は無い）
    by_prefix = {}
    for ident, ln in seen.items():
        by_prefix.setdefault(ident.split("-")[0], set()).add(int(ident.split("-")[1]))
    for prefix, nums in sorted(by_prefix.items()):
        for missing in sorted(set(range(1, max(nums) + 1)) - nums):
            findings.append({
                "check": "requirement_id", "file": rel_path, "line": 0,
                "reference": f"{prefix}-{missing:02d}", "kind": "missing_id",
                "message": f"要件 ID `{prefix}-{missing:02d}` が欠番（最大は "
                           f"`{prefix}-{max(nums):02d}`）。要件 ID 規約（docs/rules-reference/requirement-id-convention.md §2）は取り下げた ID も "
                           f"`~~{prefix}-{missing:02d}~~` と残すと定める",
                "context": "",
            })
    return findings


CHECKS = {"command_reference": check_command_references,
          "file_reference": check_file_references,
          "requirement_id": check_requirement_ids}


def main():
    ap = argparse.ArgumentParser(description="仕様の機械検査（R-14）。ファイルは変更しない")
    ap.add_argument("--project-dir", default=".")
    ap.add_argument("--scan-dir", action="append", dest="scan_dirs")
    ap.add_argument("--check", action="append",
                    help=f"実行する検査（{', '.join(CHECKS)}）。省略時はすべて")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    root = os.path.abspath(args.project_dir)
    if not os.path.isdir(root):
        # 検査対象が無いのに「欠陥 0 件・OK」を返さない（v15.1）
        print(f"ERROR: --project-dir {root} が存在しない", file=sys.stderr)
        return 2
    names = args.check or list(CHECKS)
    findings = []
    excluded = set()
    for n in names:
        if n not in CHECKS:
            print(f"unknown check: {n}", file=sys.stderr)
            return 2
        if n in ("command_reference", "file_reference"):
            findings.extend(CHECKS[n](root, args.scan_dirs, excluded))
        else:
            findings.extend(CHECKS[n](root, args.scan_dirs))

    if args.json:
        print(json.dumps(findings, ensure_ascii=False, indent=2))
    else:
        print("=== Spec Check ===\n")
        if not findings:
            print("  欠陥は見つかりませんでした。")
        for f in findings:
            print(f"  ✗ [{f['kind']}] {f['file']}:{f['line']}  {f['message']}")
            print(f"      {f['context']}")
        roots = load_resolve_roots(root)
        if excluded or roots:
            # 抑制を見えるようにする（許可リストの excludes / resolve_roots。v15.1）
            print(f"\n  {ALLOWLIST_PATH} により: 走査対象外 {len(excluded)} ファイル"
                  f"（{', '.join(sorted(excluded)) or '—'}） / 追加の解決先 {len(roots)} 件"
                  f"（{', '.join(roots) or '—'}）")
        print(f"\nResult: {len(findings)} 件の欠陥")
        print("Status: " + ("DEFECT" if findings else "OK"))
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
