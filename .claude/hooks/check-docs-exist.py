#!/usr/bin/env python3
"""
PreToolUse hook: outputs/ にファイルを書き込む前に docs/ の存在と最低限の仕様ファイルを確認する。

- docs/ が存在しない → 警告（ブロックはしない）
- docs/_manifest.json がある → required_files を検証し、不足があれば警告
- manifest がない → docs/ に Markdown が1つでもあればOK（空なら警告）

v15.1:
- **パスの判定をスクリプト側で行う**。settings.json の matcher はツール名（`Write|Edit`）だけを見る。
  v15.0 の matcher `Write(outputs/**)|Edit(outputs/**)` は正規表現として不正で、Claude Code は
  このフックを一度も起動していなかった（v15.1 でオーナー承認のうえ matcher を直した。README §9.1）。
- `tool_input.file_path` は絶対パスで渡るため、プロジェクトルート（`CLAUDE_PROJECT_DIR`、
  無ければ stdin の `cwd`）からの相対パスに直してから `outputs/` 配下かを判定する
  （v15.0 は `startswith("outputs/")` だけを見ており、絶対パスでは常に素通りだった）。
- 警告は `systemMessage`（利用者に表示される）で返す。v15.0 の `{"message": ...}` は
  Claude Code が認識しないキーで、表示されていなかった。
"""
import glob
import json
import os
import sys

MANIFEST = "_manifest.json"


def _warn(message: str):
    json.dump({"systemMessage": message}, sys.stdout, ensure_ascii=False)


def project_root(data: dict) -> str:
    return os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()


def rel_to_root(file_path: str, root: str):
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
    if not isinstance(data, dict):
        sys.exit(0)

    try:
        root = project_root(data)
        tool_input = data.get("tool_input") or {}
        rel = rel_to_root(tool_input.get("file_path", ""), root)

        # outputs/ 配下に書き込む操作だけ対象にする（Write / Edit 共通）
        if rel is None or not rel.startswith("outputs/"):
            sys.exit(0)

        docs_dir = os.path.join(root, "docs")
        manifest_path = os.path.join(docs_dir, MANIFEST)

        if not os.path.isdir(docs_dir):
            _warn("⚠️ SDD警告: docs/ ディレクトリが存在しません。仕様なしで成果物を生成しています。"
                  "先に /init-task で仕様を定義することを推奨します。")
            sys.exit(0)

        # manifest がある場合は required_files を検証
        if os.path.isfile(manifest_path):
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
                required = manifest.get("required_files", []) or []
                missing = [p for p in required if not os.path.isfile(os.path.join(docs_dir, p))]
                if missing:
                    _warn("⚠️ SDD警告: docs/ に不足ファイルがあります（" + ", ".join(missing)
                          + "）。/init-task の仕様ファイル作成が未完了か、削除された可能性があります。")
            except Exception:
                _warn("⚠️ SDD警告: docs/_manifest.json の読み取りに失敗しました。仕様ファイルの整合性を確認してください。")
            sys.exit(0)

        # manifest がない場合は、docs/ に Markdown が1つでもあればOK（空なら警告）
        if not glob.glob(os.path.join(docs_dir, "*.md")):
            _warn("⚠️ SDD警告: docs/ は存在しますが仕様ファイル（*.md）が見つかりません。"
                  "先に /init-task で仕様を定義することを推奨します。")
    except Exception:
        pass  # R-10: 例外時もターンを止めない
    sys.exit(0)


if __name__ == "__main__":
    main()
