#!/usr/bin/env python3
"""
check_fix_cycle.py: 修正サイクルの打ち切り規則（R-30 / C-51）と
Critical Issue の Gate 帰属（R-31 / C-50）を機械検査する。

背景（Phase 07 クロージング時の診断、`CLAUDE.md` 参照）:
  Phase 07 は 11 巡した。原因は成果物の質ではなく「回し方」だった:
    (1) run-phase Step 3.1 の選択肢 4「Accept」を Builder が一度も対等に提示しなかった
    (2) `.claude/rules/quality-standards.md`（Gate 3 = recommended・免除可）と
        `.claude/agents/validator.md`（矛盾は無条件 Critical）が矛盾しており、
        免除可能な Gate を根拠に免除不可の Critical を 6 巡出し続けた（C-50）

設計方針（`docs/io-spec.md` §2.5.2 / §2.6 に規約を先に書いてから実装。C-42 の教訓を踏襲）:
  - 打ち切り規則（R-30）: `revision_history` が 3 巡以上かつ `validation_status` が
    文字列 `"pass"` と完全一致しなければ、最後の要素に非空の `owner_decision` を要求する
  - Gate 帰属（R-31）: Critical Issue は `Gate: 0/1/2/3-only` の**自己申告フィールド**を
    必須とし、`3-only` は Critical に分類できない（Suggestions に置く）。
    **正規表現で内容から Gate を推測しない**——自己申告のマーカーだけを読む

使い方:
  python3 scripts/check_fix_cycle.py --phase 12
  python3 scripts/check_fix_cycle.py --phase 12 --json

exit code:
  0 = 違反なし   1 = 違反あり   2 = 実行エラー
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

_GATE_RE = re.compile(r"\*\*Gate\*\*:\s*(0|1|2|3-only)")
_CRITICAL_HEADING_RE = re.compile(r"critical issues", re.IGNORECASE)
_SECTION_RE = re.compile(r"^##[ \t]+.*$", re.MULTILINE)
_ISSUE_SPLIT_RE = re.compile(r"^###[ \t]+", re.MULTILINE)
_FENCE_LINE_RE = re.compile(r"^(`{3,}|~{3,})")
_INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
# Critical Issue らしき記述（`### ` 見出しが無くても検出する）。
# `Gate` 自体は含めない —— Gate 欄の有無を判定する対象と、Issue の存在を判定する
# マーカーを兼ねると、Gate 欄しか書いていない壊れた入力を誤って「Issue あり」と扱いかねない。
_ISSUE_MARKER_RE = re.compile(r"\*\*(Location|Problem)\*\*", re.IGNORECASE)

# Gate 自己申告が複数出現し一意に定まらない場合の内部マーカー（missing とは区別する）。
_AMBIGUOUS_GATE = "__ambiguous__"

# owner_decision を要求し始める巡数。3 巡目（Fix Cycle Limits の上限）で
# エスケレーションする、という既存の `.claude/rules/builder-validator.md` 運用に合わせる。
CUTOFF_CYCLE_COUNT = 3

# 「打ち切り済み」とみなす validation_status の唯一の値。表記揺れ（"PASS" 等）は
# 「未 pass」として扱う（`docs/io-spec.md` §2.5.2）。
PASS_VALUE = "pass"


def _result(check, status, message, detail=None):
    r = {"check": check, "status": status, "message": message}
    if detail is not None:
        r["detail"] = detail
    return r


def _load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _phase_dir(root, phase):
    return Path(root) / "outputs" / f"phase-{int(phase):02d}"


# ---------------------------------------------------------------- R-30
def check_cutoff_rule(metadata):
    """打ち切り規則（C-51 / R-30）: `revision_history` が 3 巡以上かつ未 pass のとき
    `owner_decision` が無ければ fail する。

    `docs/io-spec.md` §2.5.2 が定義の唯一の正。
    """
    if metadata is None:
        return [_result("fix_cycle_cutoff", "skip", ".metadata.json が読めないため判定不能")]

    revision_history = metadata.get("revision_history") or []
    if not isinstance(revision_history, list) or len(revision_history) < CUTOFF_CYCLE_COUNT:
        return [_result("fix_cycle_cutoff", "pass",
                        f"revision_history {len(revision_history) if isinstance(revision_history, list) else 0} 件"
                        f"（{CUTOFF_CYCLE_COUNT} 巡未満のため打ち切り規則の対象外）")]

    validation_status = metadata.get("validation_status")
    if validation_status == PASS_VALUE:
        return [_result("fix_cycle_cutoff", "pass",
                        f"revision_history {len(revision_history)} 件だが "
                        f"validation_status が \"{PASS_VALUE}\"（解決済み）")]

    last = revision_history[-1]
    if not isinstance(last, dict):
        return [_result("fix_cycle_cutoff", "fail",
                        "revision_history の最後の要素がオブジェクトでない。"
                        "owner_decision の有無を判定できない")]

    decision = str(last.get("owner_decision", "")).strip()
    if decision:
        return [_result("fix_cycle_cutoff", "pass",
                        f"revision_history {len(revision_history)} 件・"
                        f"validation_status=\"{validation_status}\" だが、"
                        f"最後の要素（cycle={last.get('cycle', '?')}）に owner_decision がある")]

    return [_result("fix_cycle_cutoff", "fail",
                    f"**revision_history が {len(revision_history)} 件（{CUTOFF_CYCLE_COUNT} 巡以上）で、"
                    f"validation_status=\"{validation_status}\"（未 pass）なのに、"
                    f"最後の要素（cycle={last.get('cycle', '?')}）に owner_decision が無い**")]


# ---------------------------------------------------------------- R-31
def _sections(text):
    """`## ` 見出しごとに (heading, body) のリストへ分割する。"""
    marks = [(m.start(), m.group().strip()) for m in _SECTION_RE.finditer(text)]
    if not marks:
        return []
    marks.append((len(text), ""))
    out = []
    for i in range(len(marks) - 1):
        start, heading = marks[i]
        end = marks[i + 1][0]
        out.append((heading, text[start:end]))
    return out


def _issue_blocks(section_body):
    """`### ` 見出し単位のブロックに分割する（無ければ空リスト）。"""
    parts = _ISSUE_SPLIT_RE.split(section_body)
    return parts[1:]  # parts[0] は `## ` 見出し行そのもの


def critical_issue_blocks(report_text):
    """`## ... Critical Issues ...` セクション配下の `### ` ブロック一覧を返す。"""
    blocks = []
    for heading, body in _sections(report_text):
        if _CRITICAL_HEADING_RE.search(heading):
            blocks.extend(_issue_blocks(body))
    return blocks


def malformed_critical_sections(report_text):
    """`### ` 見出しが無いのに Issue らしき記述がある `Critical Issues` セクションの
    見出し一覧を返す（Critical #3 の再現手順。`docs/io-spec.md` §2.6 の区切り書式規約）。

    番号付きリスト等、規約外の書式で書かれた Critical Issue は `### ` で分割できず、
    `critical_issue_blocks()` からは「0 件（Critical Issue なし）」に見える。
    それを黙って pass にせず、**区切り書式違反として明示的に fail** できるよう
    見出しを返す。
    """
    offenders = []
    for heading, body in _sections(report_text):
        if not _CRITICAL_HEADING_RE.search(heading):
            continue
        if _ISSUE_SPLIT_RE.search(body):
            continue  # 通常どおり `### ` 見出しで区切られている
        if _ISSUE_MARKER_RE.search(body):
            offenders.append(heading)
    return offenders


def _strip_fenced_and_inline_code(text):
    """コードフェンス（```/~~~、行単位）とインラインコード（`...`）を除去する。

    Critical #2 の再現手順（書式例としてコードフェンスやバッククォートで引用された
    `**Gate**: 0` が、本物の自己申告 `**Gate**: 3-only` より前に出現し、`.search()` の
    「最初の一致」採用ロジックで本物を隠す）を塞ぐ。行単位でフェンスを追跡する方式は
    `scripts/validate-outputs.py::_strip_fenced_blocks` と同じ考え方（閉じていない
    フェンスは残り全体をフェンス内とみなし、安全側に倒す）。
    """
    out_lines = []
    fence = None  # (文字, 長さ)
    for line in text.split("\n"):
        st = line.lstrip()
        m = _FENCE_LINE_RE.match(st)
        if m:
            ch, n = m.group(1)[0], len(m.group(1))
            if fence is None:
                fence = (ch, n)
                continue
            if ch == fence[0] and n >= fence[1] and not st[n:].strip():
                fence = None
                continue
        if fence is None:
            out_lines.append(line)
    without_fences = "\n".join(out_lines)
    return _INLINE_CODE_RE.sub("", without_fences)


def extract_gate(block):
    """自己申告 `**Gate**:` を抽出する。

    コードフェンス・インラインコードを除去してから検索し、デコイの引用例を無視する。
    除去後になお **複数の一致** が残る場合は、どちらが本物の自己申告か機械的に
    決められないため `_AMBIGUOUS_GATE` を返す（`docs/io-spec.md` §2.6。Critical #2）。
    """
    stripped = _strip_fenced_and_inline_code(block)
    matches = _GATE_RE.findall(stripped)
    if not matches:
        return None
    if len(matches) > 1:
        return _AMBIGUOUS_GATE
    return matches[0]


def _block_title(block):
    lines = block.strip().splitlines()
    return lines[0].strip() if lines else "(タイトル不明)"


def check_gate_attribution(report_text):
    """Gate 帰属（C-50 / R-31）: Critical Issue の Gate 自己申告を検査する。

    (1) Gate 欄の無い Critical Issue がないこと（複数出現で一意に定まらない場合も含む）
    (2) Gate 3-only の Critical Issue がないこと（3-only は Suggestions に置く）
    (0) 上記いずれの判定にも先立ち、`### ` 以外の書式で書かれた Critical Issue を
        「0 件（検査対象なし）」と誤読しないこと（Critical #3）
    """
    out = []
    malformed = malformed_critical_sections(report_text)
    if malformed:
        message = ("**区切り書式が規約に反するため判定不能**（`### ` 見出しが無いのに "
                   f"Issue らしき記述がある見出し: {malformed}）。"
                   "`docs/io-spec.md` §2.6 は Critical Issue を `### ` 見出しで区切ることを"
                   "規約化している")
        out.append(_result("gate_field_present", "fail", message))
        out.append(_result("gate_3only_not_critical", "fail",
                           "区切り書式が規約に反するため 3-only 判定も不能（上記と同一原因）"))
        return out

    blocks = critical_issue_blocks(report_text)
    if not blocks:
        out.append(_result("gate_field_present", "pass",
                           "Critical Issue が無い（Gate 欄の検査対象なし）"))
        out.append(_result("gate_3only_not_critical", "pass",
                           "Critical Issue が無い（3-only 誤分類の検査対象なし）"))
        return out

    missing, ambiguous, gate3only = [], [], []
    for block in blocks:
        gate = extract_gate(block)
        title = _block_title(block)
        if gate is None:
            missing.append(title)
        elif gate == _AMBIGUOUS_GATE:
            ambiguous.append(title)
        elif gate == "3-only":
            gate3only.append(title)

    problems = []
    if missing:
        problems.append(f"Gate 欄の無い Critical Issue: {missing}")
    if ambiguous:
        problems.append(f"Gate 欄が複数出現し一意に定まらない Critical Issue: {ambiguous}")

    out.append(_result("gate_field_present",
                       "pass" if not problems else "fail",
                       f"Critical Issue {len(blocks)} 件すべてに Gate 欄が一意にある" if not problems
                       else "**" + "; ".join(problems) + "**"))
    out.append(_result("gate_3only_not_critical",
                       "pass" if not gate3only else "fail",
                       "Gate 3-only な Critical Issue はない" if not gate3only
                       else f"**Gate 3-only なのに Critical に分類されている: {gate3only}**"))
    return out


def run_checks(root, phase):
    results = []
    pd = _phase_dir(root, phase)
    md = _load_json(pd / ".metadata.json")
    try:
        results.extend(check_cutoff_rule(md))
    except Exception as e:                                   # noqa: BLE001
        results.append(_result("fix_cycle_cutoff", "fail",
                               f"検査中に例外: {type(e).__name__}: {e}"))

    report_path = pd / ".validation" / "report.md"
    if not report_path.is_file():
        results.append(_result("gate_field_present", "skip",
                               ".validation/report.md が無いため Gate 帰属を判定不能"))
        results.append(_result("gate_3only_not_critical", "skip",
                               ".validation/report.md が無いため Gate 帰属を判定不能"))
    else:
        text = report_path.read_text(encoding="utf-8", errors="replace")
        try:
            results.extend(check_gate_attribution(text))
        except Exception as e:                                # noqa: BLE001
            results.append(_result("gate_field_present", "fail",
                                   f"検査中に例外: {type(e).__name__}: {e}"))
    return results


def main():
    ap = argparse.ArgumentParser(description="修正サイクルの打ち切り規則と Gate 帰属を機械検査する")
    ap.add_argument("--phase", required=True, help="フェーズ番号")
    ap.add_argument("--project-dir", default=".", help="プロジェクトルート")
    ap.add_argument("--json", action="store_true", help="JSON で出力")
    args = ap.parse_args()

    root = os.path.abspath(args.project_dir)
    results = run_checks(root, args.phase)

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print(f"=== Fix Cycle Check: Phase {args.phase} ===\n")
        mark = {"pass": "✓", "fail": "✗", "skip": "-"}
        for r in results:
            print(f"  {mark.get(r['status'], '?')} [{r['check']}] {r['message']}")
        n = {s: sum(1 for r in results if r["status"] == s) for s in ("pass", "fail", "skip")}
        print(f"\nResult: {n['pass']} pass, {n['fail']} fail, {n['skip']} skip")
        print("Status: " + ("VIOLATION" if n["fail"] else "OK"))

    return 1 if any(r["status"] == "fail" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
