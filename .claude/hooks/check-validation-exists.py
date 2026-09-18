#!/usr/bin/env python3
"""
PostToolUse hook: `.metadata.json` 書込後に同じフェーズディレクトリに `.validation/` が
無ければ警告する（**非ブロック**。Builder が `.metadata.json` を Validator より先に書く
運用を壊さないため）。

SEC-03: ユーザー入力・成果物内容をコマンドに展開しない。ファイルパスの組み立ては
os.path.join を使い、シェルを経由しない。

v15.1: パスの判定をスクリプト側で行い（`outputs/phase-*/.metadata.json` だけが対象）、
絶対パスの `tool_input.file_path` をプロジェクトルート相対に直す。警告は `systemMessage` で返す
（v15.0 の matcher は不正な正規表現でこのフックは起動しておらず、出力キー `message` も
Claude Code が認識しないものだった）。v15.1 でオーナー承認のうえ settings.json の matcher を `Write` に直した
（README §9.1）。
"""
import json
import os
import sys


def _warn(message):
    json.dump({"systemMessage": message}, sys.stdout, ensure_ascii=False)


def project_root(data):
    return os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()


def rel_to_root(file_path, root):
    """プロジェクトルートからの相対パス（`/` 区切り）。ルートの外なら None。"""
    if not isinstance(file_path, str) or not file_path:
        return None
    full = file_path if os.path.isabs(file_path) else os.path.join(root, file_path)
    rel = os.path.relpath(os.path.normpath(full), os.path.normpath(root))
    if rel == ".." or rel.startswith(".." + os.sep):
        return None
    return rel.replace(os.sep, "/")


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)  # R-10: 壊れた入力でもターンを止めない

    try:
        root = project_root(data)
        rel = rel_to_root((data.get("tool_input") or {}).get("file_path", ""), root)
        parts = rel.split("/") if rel else []
        # outputs/phase-NN/.metadata.json だけが対象
        if not (len(parts) == 3 and parts[0] == "outputs" and parts[1].startswith("phase-")
                and parts[2] == ".metadata.json"):
            sys.exit(0)

        phase_dir = os.path.join(root, parts[0], parts[1])
        if not os.path.isdir(os.path.join(phase_dir, ".validation")):
            _warn("SDD警告: {} に .validation/ がありません。Validator 未実行の可能性があります。"
                  .format(parts[1]))
    except Exception:
        pass  # R-10: 例外時もターンを止めない

    sys.exit(0)


if __name__ == "__main__":
    main()
