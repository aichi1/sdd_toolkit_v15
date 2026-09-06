#!/usr/bin/env python3
"""
PostToolUse hook: `.metadata.json` 書込後に同じフェーズディレクトリに `.validation/` が
無ければ警告する（**非ブロック**。Builder が `.metadata.json` を Validator より先に書く
運用を壊さないため）。

SEC-03: ユーザー入力・成果物内容をコマンドに展開しない。ファイルパスの組み立ては
os.path.join を使い、シェルを経由しない。
"""
import json
import os
import sys


def _warn(message):
    json.dump({"message": message}, sys.stdout)


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)  # R-10: 壊れた入力でもターンを止めない

    try:
        file_path = data.get("tool_input", {}).get("file_path", "")
        if not isinstance(file_path, str) or not file_path.endswith(".metadata.json"):
            sys.exit(0)

        cwd = data.get("cwd", os.getcwd())
        phase_dir = os.path.dirname(os.path.join(cwd, file_path))

        if not os.path.isdir(os.path.join(phase_dir, ".validation")):
            _warn(
                "SDD警告: {} に .validation/ がありません。Validator 未実行の可能性があります。".format(
                    os.path.basename(phase_dir)
                )
            )
    except Exception:
        pass  # R-10: 例外時もターンを止めない

    sys.exit(0)


if __name__ == "__main__":
    main()
