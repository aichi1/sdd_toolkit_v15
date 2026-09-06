#!/usr/bin/env python3
"""
check_constitution.py: docs/constitution.md の強制点のうち、機械検査できるものを実行する。

背景（R-12 / Phase 06）:
  Iteration 1 の実測で `docs/constitution.md` は validation レポートで 24 回引かれた一方、
  `docs/constraints.md`（D-01〜D-06 の運用プロトコル）は **0 回**だった。
  運用ルールが Validator の判定対象になっていない。オーナー決定（2026-09-04）により
  **機械検査できるものだけを憲法へ格上げ**し、本スクリプトがそれを検査する。

設計方針（C-42 の教訓）:
  機械チェックを置くだけでは足りない。**判定できない入力を黙って通さない**こと。
  検査できなかった項目は `skip` として明示的に報告し、`pass` と区別する。

使い方:
  python3 scripts/check_constitution.py --phase 6
  python3 scripts/check_constitution.py --phase 6 --article 3
  python3 scripts/check_constitution.py --phase 6 --json

exit code:
  0 = 違反なし   1 = 違反あり   2 = 実行エラー（引数不正など）
"""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# `.claude/` 配下のうち、変更したら次フェーズで D-01 が必要になるもの。
#
# **`.claude/` 全体を対象にする。** 当初は settings.json / hooks / agents / skills / rules の
# 5 つだけを列挙しており、**`.claude/commands/` が漏れていた**。
# Phase 07 が `/clarify` `/spec-check` をコマンドとして新設したとき、
# 第10条の機械強制が空振りする一因になった（Validator が検出）。
# 第10条の条文は「`.claude/` 配下」と書いており、括弧内の列挙は例示にすぎない。
SELF_MODIFY_PREFIXES = (".claude/",)

# 第10条（D-01）が適用され始めるフェーズ。
# オーナー決定（2026-09-04）: 過去フェーズの検証証跡は書き換えないため、
# `.metadata.json` の `session` を実セッション ID に標準化するのは Phase 06 以降。
#
# **判定対象は「前フェーズの自己変更」である**。したがって条文の「遡及適用しない」を満たすには、
# **前フェーズも Phase 06 以降**でなければならない（実質 Phase 07 が最初の判定対象）。
# 当初の実装は現フェーズだけを見ており、第10条が存在しなかった Phase 05 の振る舞いを裁いていた。
# Validator が Phase 06 の検証でこれを検出し、オーナー決定（2026-09-04、選択肢 (b)）により修正した。
ARTICLE_10_FROM_PHASE = 6

# 第3条 D-02 の判定を構造化フィールド（`skills_executed_this_phase`）へ移行するフェーズ。
# オーナー決定（2026-09-06、Phase 12、C-52 / R-32、改正履歴(3)）:
#   従来の実装は `execution_note` 等の散文を部分文字列一致（`f"/{n}" in note`）で読んでおり、
#   ファイル名が `/{skill}` に前方一致するだけで「実行した」と誤検出した
#   （例: `docs/convergence.md` への言及が `converge` に前方一致）。
#   新しい判定は `.metadata.json` の配列フィールド `skills_executed_this_phase` と
#   `modified_skill_names()` の積集合のみを見る。**散文は一切読まない**。
# 第10条 (ARTICLE_10_FROM_PHASE) と同じ理由で、過去フェーズの証跡は遡及修正しないため
# **Phase 12 以降にのみ適用**する。Phase 12 未満は skip。
D02_STRUCTURED_FROM_PHASE = 12


def _run(cmd, cwd=None):
    """コマンドを実行し (exit_code, stdout) を返す。"""
    p = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def phase_is_committed(root, phase):
    """そのフェーズの成果物が既にコミットされているか。

    第2条 改正(6)（C-43）: patch.diff が保証するのは**フェーズ完了時点（コミット前）**の
    可逆性である。コミット後は後続コミットが同じ箇所を書き換えうるため
    `git apply --reverse --check` が失敗しうる。これは違反ではない。
    """
    rc, out = _run(f"git log --oneline -1 -- outputs/phase-{int(phase):02d}/", cwd=root)
    return rc == 0 and bool(out.strip())


def _result(article, check, status, message):
    return {"article": article, "check": check, "status": status, "message": message}


def _load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _phase_dir(root, phase):
    return Path(root) / "outputs" / f"phase-{int(phase):02d}"


def _prev_phase_dir(root, phase):
    return Path(root) / "outputs" / f"phase-{int(phase) - 1:02d}"


def has_self_modification(metadata):
    """`.claude/` 配下を変更したか。**新規作成も自己変更である**。

    当初は `in_place_changes` だけを見ていた。しかし `.claude/commands/` や
    `.claude/skills/` へのファイル**追加**は `new_files` に記録されるため、
    Phase 07（コマンド 2 つを新設）が「自己変更なし」と判定されていた。
    Validator が Phase 07 の再検証で検出（第10条の機械強制が空振りしていた）。
    """
    if not metadata:
        return False
    for key in ("in_place_changes", "new_files"):
        for f in metadata.get(key, []) or []:
            if any(p in str(f) for p in SELF_MODIFY_PREFIXES):
                return True
    return False


def modified_skill_names(metadata):
    """そのフェーズが変更した `.claude/skills/<name>/` の name 一覧。

    `in_place_changes` と `new_files` の**両方**を見る。
    当初は `in_place_changes` だけを見ていたため、**そのフェーズで新規作成した
    スキルを同じフェーズで実行しても第3条 / D-02 の検査を素通りした**（Phase 07 の Critical #29）。
    `has_self_modification()` が同じ理由で修正された（#4）のに、
    こちらは直っていなかった —— **兄弟関数は一緒に直す。**
    """
    names = set()
    for key in ("in_place_changes", "new_files"):
        for f in (metadata or {}).get(key, []) or []:
            s = str(f)
            if ".claude/skills/" in s:
                rest = s.split(".claude/skills/", 1)[1]
                if "/" in rest:
                    names.add(rest.split("/", 1)[0])
    return names



def phase_scripts(metadata):
    """そのフェーズが新規作成または変更した `scripts/*.py` の一覧。

    第3条 改正(2)（オーナー決定 2026-09-05）。スクリプトは D-02 の禁止対象に
    しない代わりに、**作った本人以外が実行した証跡**を要求する。
    """
    out = set()
    for key in ("in_place_changes", "new_files"):
        for f in (metadata or {}).get(key, []) or []:
            s = str(f)
            if s.startswith("scripts/") and s.endswith(".py"):
                out.add(s)
    return out
_APPROVED = re.compile(r"承認済み|追認済み|決定済み")


def unapproved_amendments(root):
    """`docs/constitution.md` の「改正履歴の追認状況」表のうち、承認欄が未確定の行。

    改正は「条文を触る前にオーナーへ提起 → 承認 → 実施」が原則だが、
    Phase 01・02・07 で**四度**この順序を破り、毎回 Validator が事後に検出した。
    四度目のオーナー決定（2026-09-05）により、**表の状態そのものを強制点にした**。

    戻り値は未承認行の「改正」列のリスト。
    """
    src = Path(root) / "docs" / "constitution.md"
    if not src.is_file():
        return None
    text = src.read_text(encoding="utf-8", errors="replace")
    sec = re.split(r"^##[ \t]*改正履歴の追認状況", text, maxsplit=1, flags=re.MULTILINE)
    if len(sec) < 2:
        return None
    body = re.split(r"^#{1,2}[ \t]", sec[1], maxsplit=1, flags=re.MULTILINE)[0]
    bad = []
    for ln in body.split("\n"):
        if not ln.lstrip().startswith("|"):
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if len(cells) < 4 or cells[0].startswith("---") or cells[0] == "改正":
            continue
        if not _APPROVED.search(cells[3]):
            bad.append(cells[0])
    return bad
# ---------------------------------------------------------------- 第2条
def check_article_2(root, phase):
    out = []
    pd = _phase_dir(root, phase)
    patch = pd / "patch.diff"
    if not patch.is_file():
        out.append(_result(2, "patch_exists", "fail", f"{patch} が存在しない"))
        return out
    if patch.stat().st_size == 0:
        out.append(_result(2, "patch_not_empty", "fail", "patch.diff が空"))
        return out
    out.append(_result(2, "patch_exists", "pass", f"patch.diff {patch.stat().st_size} bytes"))

    rc, _ = _run(f"git apply --reverse --check {patch}", cwd=root)
    if rc == 0:
        out.append(_result(2, "reverse_applicable", "pass",
                           "git apply --reverse --check → exit=0"))
    elif phase_is_committed(root, phase):
        # 第2条 改正(6)（C-43）: コミット後は保証の対象外。違反ではない
        out.append(_result(2, "reverse_applicable", "skip",
                           f"git apply --reverse --check → exit={rc}。"
                           "本フェーズはコミット済みのため第2条の保証対象外"
                           "（改正(6) / C-43。ロールバックは git revert）"))
    else:
        out.append(_result(2, "reverse_applicable", "fail",
                           f"git apply --reverse --check → exit={rc}。"
                           "**未コミットのフェーズでは exit 0 でなければならない**"))

    # 改正(5)（C-41）: 他フェーズ成果物への変更が patch.diff から漏れていないか
    rc, sout = _run("git diff --stat HEAD -- 'outputs/phase-*'", cwd=root)
    leaked = [ln for ln in sout.splitlines() if "|" in ln]
    if leaked:
        listed = (pd / "change-report.md")
        text = listed.read_text(encoding="utf-8") if listed.is_file() else ""
        missing = [ln.split("|")[0].strip() for ln in leaked
                   if ln.split("|")[0].strip() not in text]
        out.append(_result(2, "other_phase_outputs_listed",
                           "pass" if not missing else "fail",
                           f"patch.diff の対象外となる他フェーズ成果物 {len(leaked)} 件"
                           + ("（すべて change-report.md に列挙済み）" if not missing
                              else f"。**未列挙: {missing}**")))
    else:
        out.append(_result(2, "other_phase_outputs_listed", "pass",
                           "他フェーズ成果物への変更なし"))
    return out


# ---------------------------------------------------------------- 第3条
def check_article_3(root, phase):
    """D-02（変更中のスキルを同じフェーズで実行しない）と D-04（safe-mode 起動可能性）。"""
    out = []
    pd = _phase_dir(root, phase)
    md = _load_json(pd / ".metadata.json")

    # --- D-02（改正(3) / C-52 / R-32: 構造化フィールド `skills_executed_this_phase` で判定）---
    # **`execution_note` / `builder_notes` / `deviations` は一切読まない。**
    # 部分文字列一致（`f"/{n}" in note`）は「ファイル名が `/{skill}` に前方一致するが
    # 実行していない」ケース（例: `docs/convergence.md` が `converge` に前方一致）を誤検出した。
    if md is None:
        out.append(_result(3, "modified_skill_not_executed", "skip",
                           ".metadata.json が読めないため判定不能"))
    elif int(phase) < D02_STRUCTURED_FROM_PHASE:
        # 過去フェーズの証跡は遡及修正しない（第10条 ARTICLE_10_FROM_PHASE と同じ設計）。
        # 旧形式（`skills_executed_this_phase` フィールド無し）は判定対象外。
        out.append(_result(3, "modified_skill_not_executed", "skip",
                           f"Phase {int(phase)} は D-02 構造化フィールドの適用開始"
                           f"（Phase {D02_STRUCTURED_FROM_PHASE}）より前のため判定対象外"
                           "（旧形式。オーナー決定 2026-09-06、過去の証跡は遡及修正しない）"))
    else:
        modified = modified_skill_names(md)
        if not modified:
            out.append(_result(3, "modified_skill_not_executed", "pass",
                               "本フェーズは .claude/skills/ を変更していない"))
        elif "skills_executed_this_phase" not in md:
            # フィールドを省けば検査を回避できる、という新しい穴を開けない（C-42 と同じ設計）。
            out.append(_result(3, "modified_skill_not_executed", "fail",
                               f"変更した skill: {sorted(modified)}。"
                               "**`.metadata.json` に必須フィールド `skills_executed_this_phase` が無い**"
                               f"（Phase {D02_STRUCTURED_FROM_PHASE} 以降は必須。フィールドを省いた場合は fail とする）"))
        else:
            declared = set(str(x) for x in (md.get("skills_executed_this_phase") or []))
            executed = sorted(modified & declared)
            out.append(_result(3, "modified_skill_not_executed",
                               "pass" if not executed else "fail",
                               f"変更した skill: {sorted(modified)} / "
                               f"skills_executed_this_phase: {sorted(declared)}"
                               + ("。同フェーズで実行した記録なし" if not executed
                                  else f"。**同フェーズで実行した記録あり: {executed}**")))

    # --- D-02 の補完: そのフェーズが作った/変えた scripts/*.py の外部再実行（第3条 改正(2)）---
    scripts_changed = phase_scripts(md) if md else set()
    if not scripts_changed:
        out.append(_result(3, "phase_scripts_rerun_by_validator", "pass",
                           "本フェーズは scripts/*.py を変更していない"))
    else:
        report = pd / ".validation" / "report.md"
        if not report.is_file():
            out.append(_result(3, "phase_scripts_rerun_by_validator", "fail",
                               f".validation/report.md が無いため外部再実行を確認できない"
                               f"（対象 {len(scripts_changed)} 件）"))
        else:
            txt = report.read_text(encoding="utf-8", errors="replace")
            sec = re.split(r"^#{1,3}[ \t]*(?:\d+[.)]?[ \t]*)*Executed Verification",
                           txt, maxsplit=1, flags=re.MULTILINE)
            body = sec[1] if len(sec) > 1 else ""
            # **セクションの終端で切る**（Critical #40）。切らないと、Suggestions や
            # 全体評価など**後続の節に書かれたコマンド**まで「再実行した」と数えてしまう。
            body = re.split(r"^#{1,3}[ \t]", body, maxsplit=1, flags=re.MULTILINE)[0]
            # **表の行だけを見る**（Critical #40）。Executed Verification の証跡は表であり、
            # 散文は証跡ではない。「`python3 scripts/spec_check.py` は実行していない」と
            # 本文に書いてあっても数えない。
            rows = [ln for ln in body.split("\n") if ln.lstrip().startswith("|")]
            # さらに、バッククォートで囲まれ**引数を伴う**コマンドの形のものだけを採る
            # （裸の `pytest` は「`pytest` は回していない」で pass するため。Critical #36）
            cmds = [c for c in re.findall(r"`([^`\n]+)`", "\n".join(rows))
                    if re.match(r"^\s*(?:!\s*)?(?:[A-Z_]+=\S+\s+)*"
                                r"(?:env|python3?|pytest|git|bash|sh|\./\S+)\s+\S", c)]
            joined = "\n".join(cmds)
            has_pytest = any("pytest" in c for c in cmds)

            def _rerun(rel):
                # テストモジュールは名指しではなく pytest の一括実行で走る
                if Path(rel).name.startswith("test_") and has_pytest:
                    return True
                return rel in joined or Path(rel).name in joined

            missing = sorted(x for x in scripts_changed if not _rerun(x))
            out.append(_result(3, "phase_scripts_rerun_by_validator",
                               "pass" if not missing else "fail",
                               f"変更した scripts/*.py {len(scripts_changed)} 件すべてが "
                               f"Validator の Executed Verification に現れる" if not missing
                               else f"**Validator が再実行していない: {missing}**"))

    # --- 改正手続きの完了: 追認状況表に未承認の行が無いこと（オーナー決定 2026-09-05）---
    bad = unapproved_amendments(root)
    if bad is None:
        out.append(_result(3, "amendments_all_approved", "skip",
                           "docs/constitution.md の「改正履歴の追認状況」表が見つからない"))
    else:
        out.append(_result(3, "amendments_all_approved", "pass" if not bad else "fail",
                           f"改正 {0 if not bad else len(bad)} 件が未承認"
                           if bad else "改正履歴の追認状況にすべて承認の記録がある"))
        if bad:
            out[-1]["detail"] = bad

    # --- D-04: settings.json が valid JSON ---
    sj = Path(root) / ".claude" / "settings.json"
    ok = _load_json(sj) is not None
    out.append(_result(3, "settings_json_valid", "pass" if ok else "fail",
                       f"{sj} が valid JSON" if ok else f"{sj} がパースできない"))

    # --- D-04: 全 hook が不正入力で exit 0（safe-mode 起動可能性の実質的担保）---
    hooks = sorted((Path(root) / ".claude" / "hooks").glob("*.py"))
    if not hooks:
        out.append(_result(3, "hooks_never_crash", "skip", "hook が見つからない"))
    else:
        bad = []
        for h in hooks:
            rc, _ = _run(f"echo 'not-a-json' | python3 {h}", cwd=root)
            if rc != 0:
                bad.append(f"{h.name}(exit={rc})")
        out.append(_result(3, "hooks_never_crash", "pass" if not bad else "fail",
                           f"{len(hooks)} hook すべて不正入力で exit 0" if not bad
                           else f"**exit≠0 の hook: {bad}**"))
    return out


# ---------------------------------------------------------------- 第4条
def check_article_4(root, phase):
    out = []
    rc, sout = _run("git diff --stat HEAD -- eval/scenarios/ eval/rubric.json", cwd=root)
    changed = [ln for ln in sout.splitlines() if "|" in ln]
    out.append(_result(4, "scenarios_and_rubric_unchanged",
                       "pass" if not changed else "fail",
                       "eval/scenarios/ と eval/rubric.json は不変" if not changed
                       else f"**変更あり: {changed}**"))
    rc, sout = _run("git diff --numstat eval/summary.csv", cwd=root)
    if sout.strip():
        add, dele = sout.split()[0], sout.split()[1]
        out.append(_result(4, "summary_csv_append_only",
                           "pass" if dele == "0" else "fail",
                           f"eval/summary.csv: +{add} -{dele}"
                           + ("（追記のみ）" if dele == "0" else "。**既存行が変更されている**")))
    else:
        out.append(_result(4, "summary_csv_append_only", "pass", "eval/summary.csv に変更なし"))
    return out


# ---------------------------------------------------------------- 第10条（D-01）
def check_article_10(root, phase):
    """自己変更は次のセッションで確かめる。"""
    out = []
    # 判定材料は「前フェーズの自己変更」なので、**前フェーズ**が適用開始以降である必要がある。
    # そうでないと第10条が存在しなかった時点の振る舞いを裁くことになり、
    # 条文の「遡及適用しない」に反する（オーナー決定 2026-09-04、選択肢 (b)）
    if int(phase) - 1 < ARTICLE_10_FROM_PHASE:
        out.append(_result(10, "new_session_after_self_modify", "skip",
                           f"前フェーズ（Phase {int(phase) - 1}）が第10条の適用開始"
                           f"（Phase {ARTICLE_10_FROM_PHASE}）より前のため判定対象外。"
                           "条文の「遡及適用しない」に従う（オーナー決定 2026-09-04）"))
        return out

    prev_md = _load_json(_prev_phase_dir(root, phase) / ".metadata.json")
    if prev_md is None:
        out.append(_result(10, "new_session_after_self_modify", "skip",
                           "前フェーズの .metadata.json がないため判定不能"))
        return out
    if not has_self_modification(prev_md):
        out.append(_result(10, "new_session_after_self_modify", "pass",
                           "前フェーズは .claude/ 配下を変更していない"))
        return out

    md = _load_json(_phase_dir(root, phase) / ".metadata.json")
    if md is None:
        out.append(_result(10, "new_session_after_self_modify", "fail",
                           "本フェーズの .metadata.json が読めない"))
        return out

    cur, prev = str(md.get("session", "")), str(prev_md.get("session", ""))
    same = cur and cur == prev
    out.append(_result(10, "new_session_after_self_modify",
                       "fail" if same else ("pass" if cur else "fail"),
                       f"前フェーズ session={prev[:24]} / 本フェーズ session={cur[:24]}"
                       + ("。**同一セッション**" if same
                          else ("" if cur else "。**session が空**"))))

    # D-01 の動作確認の証跡が verification.log にあるか
    vlog = _phase_dir(root, phase) / "verification.log"
    if not vlog.is_file():
        out.append(_result(10, "self_modify_verified", "fail", "verification.log がない"))
    else:
        t = vlog.read_text(encoding="utf-8", errors="replace")
        has_hooks = t.count(".claude/hooks/") >= 2
        out.append(_result(10, "self_modify_verified",
                           "pass" if has_hooks else "fail",
                           "verification.log に hook の動作確認がある" if has_hooks
                           else "**verification.log に hook の動作確認がない**"))
    return out


# ---------------------------------------------------------------- 第11条（D-05）
def check_article_11(root, phase):
    """引き継ぎは機械が読める形で残す。

    `.phase-context.json` は**フェーズ完了ごとに上書きされる単一ファイル**である。
    当初はフェーズを見ずに中身を数えていたため、**前フェーズの残骸で pass** していた
    （Phase 07 の検証で Phase 06 の記録を数えていた。Validator が検出）。
    `last_phase` が検査対象フェーズと一致することを先に確かめる。
    """
    out = []
    ctx = _load_json(Path(root) / "outputs" / ".phase-context.json")
    if ctx is None:
        out.append(_result(11, "phase_context_keys", "fail",
                           "outputs/.phase-context.json が読めない"))
        return out

    recorded = ctx.get("last_phase")
    if str(recorded) != str(int(phase)):
        out.append(_result(11, "phase_context_is_current", "fail",
                           f"outputs/.phase-context.json の last_phase が {recorded} で、"
                           f"検査対象の Phase {int(phase)} と一致しない。"
                           "**前フェーズの記録を数えて pass してはいけない**"))
        return out
    out.append(_result(11, "phase_context_is_current", "pass",
                       f"last_phase = {recorded}（検査対象と一致）"))

    missing = [k for k in ("self_modified_files", "stale_procedures") if k not in ctx]
    out.append(_result(11, "phase_context_keys", "pass" if not missing else "fail",
                       "self_modified_files と stale_procedures が存在する" if not missing
                       else f"**欠落しているキー: {missing}**"))
    if missing:
        return out

    md = _load_json(_phase_dir(root, phase) / ".metadata.json")
    if has_self_modification(md):
        n = len(ctx.get("self_modified_files") or [])
        out.append(_result(11, "self_modified_files_recorded", "pass" if n else "fail",
                           f"自己変更ありのフェーズで self_modified_files が {n} 件"
                           + ("" if n else "。**空であってはならない**")))
    else:
        out.append(_result(11, "self_modified_files_recorded", "pass",
                           "本フェーズは自己変更なし（空でも可）"))
    return out


CHECKS = {2: check_article_2, 3: check_article_3, 4: check_article_4,
          10: check_article_10, 11: check_article_11}


def run_checks(root, phase, articles=None):
    results = []
    for num in sorted(CHECKS):
        if articles and num not in articles:
            continue
        try:
            results.extend(CHECKS[num](root, phase))
        except Exception as e:                       # noqa: BLE001
            # C-42 の教訓: 判定できなかったことを黙って通さない
            results.append(_result(num, "check_error", "fail",
                                   f"検査中に例外: {type(e).__name__}: {e}"))
    return results


def main():
    ap = argparse.ArgumentParser(description="constitution の強制点を機械検査する")
    ap.add_argument("--phase", required=True, help="フェーズ番号")
    ap.add_argument("--article", type=int, action="append",
                    help="検査する条番号（複数可）。省略時はすべて")
    ap.add_argument("--project-dir", default=".", help="プロジェクトルート")
    ap.add_argument("--json", action="store_true", help="JSON で出力")
    args = ap.parse_args()

    root = os.path.abspath(args.project_dir)
    results = run_checks(root, args.phase, set(args.article) if args.article else None)

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print(f"=== Constitution Check: Phase {args.phase} ===\n")
        mark = {"pass": "✓", "fail": "✗", "skip": "-"}
        for r in results:
            print(f"  {mark.get(r['status'], '?')} [第{r['article']}条 {r['check']}] {r['message']}")
        n = {s: sum(1 for r in results if r["status"] == s) for s in ("pass", "fail", "skip")}
        print(f"\nResult: {n['pass']} pass, {n['fail']} fail, {n['skip']} skip")
        print("Status: " + ("VIOLATION" if n["fail"] else "OK"))

    return 1 if any(r["status"] == "fail" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
