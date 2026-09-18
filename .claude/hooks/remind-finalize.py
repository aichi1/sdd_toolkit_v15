#!/usr/bin/env python3
"""
Stop hook:
- outputs/ に成果物があるのに /finalize が未実行の場合、または outputs/phase-NN/ に
  .validation/ が無いフェーズがある場合、次ターンで Claude に継続を促す（R-09 / C-08）。
- ツールキット開発プロジェクトが Claude Code 2.1.260 で調べたスキーマ（同プロジェクトの調査記録。
  本リポジトリには無い）に従い、`decision: "block"` ではなく `hookSpecificOutput.permissionDecision` を使う。
- **無限ループ防止**（K-06）: 当時の調査では Claude Code 側に安全網が無かったため、`session_id` をキーにした
  ファイルベースのカウンタで継続指示（permissionDecision: "deny"）の発火回数を上限 2 回に制限する。
  上限到達後は permissionDecision を返さず、リマインド表示のみに戻る。
- **例外時は常に exit 0**（R-10）。カウンタ自体が壊れても exit 0 とし、読めない場合は
  「上限到達」として安全側に倒す（継続指示を出さない）。

v15.1:
- **`stop_hook_active` が真なら継続指示を出さない**（停止を許可する）。Claude Code 2.1.276 は
  「Stop hook は stop_hook_active が真の間は成功を返すこと」と案内し、連続して止めると強制終了する。
  v15.0 はこのフィールドを読まず、カウンタが書けない環境（`.claude/hooks/` が書込み不可など）では
  毎回継続指示を返し続けた。
- **カウンタを書けなかったら上限到達とみなす**（読めない場合と同じ安全側）。
- プロジェクトルートは `CLAUDE_PROJECT_DIR`（無ければ stdin の `cwd`）。サブディレクトリへ `cd`
  した後でもリマインドが黙って無効にならないように。
- `systemMessage` をトップレベルにも置く（`hookSpecificOutput` の中の `systemMessage` は認識されない）。
- 継続指示の出力形式（`hookSpecificOutput.permissionDecision`）は、公式の Stop フックのスキーマで
  確認できていない（未検証）。v15.1 では形式を変えず、上の停止保証だけを足した。
"""
import json
import os
import sys

IGNORE_FILES = {".DS_Store", "Thumbs.db"}
MAX_FIRE_COUNT = 2  # 継続指示（permissionDecision: deny）を返せる回数の上限（暫定値）


def _state_path(cwd: str, session_id: str) -> str:
    state_dir = os.path.join(cwd, ".claude", "hooks", ".state")
    safe_id = "".join(c for c in session_id if c.isalnum() or c in ("-", "_")) or "unknown"
    return os.path.join(state_dir, "stop-count-{}.json".format(safe_id))


def _read_fire_count(path: str) -> int:
    """カウンタを読む。壊れていれば MAX_FIRE_COUNT を返し『上限到達』側に倒す（安全側）。"""
    try:
        if not os.path.isfile(path):
            return 0
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        count = data.get("count", 0)
        if not isinstance(count, int) or count < 0:
            return MAX_FIRE_COUNT
        return count
    except Exception:
        return MAX_FIRE_COUNT


def _write_fire_count(path: str, count: int) -> bool:
    """カウンタを書く。書けなければ False（呼び出し側は上限到達として扱う。v15.1）。"""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"count": count}, f)
        return True
    except Exception:
        return False  # R-10: カウンタが書けなくてもターンは止めない


def _collect_reasons(cwd: str):
    """継続を促す理由のリストを返す（空なら継続不要 = 停止を許可）。"""
    reasons = []
    outputs_dir = os.path.join(cwd, "outputs")
    if not os.path.isdir(outputs_dir):
        return reasons

    deliverables_readme = os.path.join(outputs_dir, "README-deliverables.md")
    finalized = os.path.isfile(deliverables_readme)

    output_files = []
    phase_dirs_missing_validation = []
    for root_dir, _dirs, files in os.walk(outputs_dir):
        if os.path.basename(root_dir).startswith("phase-"):
            metadata_path = os.path.join(root_dir, ".metadata.json")
            validation_dir = os.path.join(root_dir, ".validation")
            if os.path.isfile(metadata_path) and not os.path.isdir(validation_dir):
                phase_dirs_missing_validation.append(os.path.basename(root_dir))
        for f in files:
            if f in IGNORE_FILES:
                continue
            full = os.path.join(root_dir, f)
            if os.path.abspath(full) == os.path.abspath(deliverables_readme):
                continue
            output_files.append(full)

    if phase_dirs_missing_validation:
        reasons.append(
            "Validator 未実行のフェーズがあります: {}".format(
                ", ".join(sorted(phase_dirs_missing_validation))
            )
        )

    if not finalized and len(output_files) > 0:
        reasons.append(
            "outputs/ に {} 件の成果物がありますが /finalize が未実行です。".format(
                len(output_files)
            )
        )

    return reasons


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)  # R-10: 壊れた入力でもターンを止めない

    try:
        if not isinstance(data, dict):
            sys.exit(0)
        cwd = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
        session_id = data.get("session_id", "")

        reasons = _collect_reasons(cwd)
        if not reasons:
            # 継続する理由がない: permissionDecision を返さず停止を許可する
            sys.exit(0)

        reason_text = " / ".join(reasons)

        if data.get("stop_hook_active") is True:
            # 既にこのフックの継続指示で動いている（v15.1）: 停止を許可し、リマインド表示のみ
            json.dump({"systemMessage": "SDD リマインド: " + reason_text}, sys.stdout,
                      ensure_ascii=False)
            sys.exit(0)

        if not session_id:
            # session_id が無い場合は回数管理を諦め、リマインド表示のみに戻す（フォールバック）
            json.dump({"systemMessage": "SDD リマインド: " + reason_text}, sys.stdout,
                      ensure_ascii=False)
            sys.exit(0)

        state_path = _state_path(cwd, session_id)
        fire_count = _read_fire_count(state_path)

        if fire_count >= MAX_FIRE_COUNT or not _write_fire_count(state_path, fire_count + 1):
            # 上限到達（K-06）、またはカウンタを書けない（v15.1: 回数を数えられないので上限扱い）:
            # permissionDecision を返さずリマインド表示のみ
            json.dump(
                {
                    "systemMessage": (
                        "SDD リマインド（継続指示の発火上限 {} 回に到達したため停止を許可します）: {}"
                    ).format(MAX_FIRE_COUNT, reason_text)
                },
                sys.stdout,
                ensure_ascii=False,
            )
            sys.exit(0)

        result = {
            "systemMessage": "SDD: " + reason_text,
            "hookSpecificOutput": {
                "hookEventName": "Stop",
                "permissionDecision": "deny",
                "permissionDecisionReason": "SDD: 未完了の作業があります（" + reason_text + "）",
                "additionalContext": (
                    "次のいずれかを行ってから再度終了してください: "
                    "(1) Validator 未実行のフェーズがあれば /run-phase でそのフェーズを検証する。"
                    "(2) 成果物が揃っていれば /finalize でパッケージングと教訓の蓄積を行う。 "
                    "詳細: " + reason_text
                ),
                "systemMessage": "SDD: " + reason_text,
            }
        }
        json.dump(result, sys.stdout)
        sys.exit(0)
    except Exception:
        sys.exit(0)  # R-10


if __name__ == "__main__":
    main()
