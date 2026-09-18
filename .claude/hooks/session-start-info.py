#!/usr/bin/env python3
"""
SessionStart hook: セッション開始時にSDD知識ベースの状態を要約して表示する。
~/.sdd-knowledge/ の内容を確認し、利用可能なスターターや教訓数を報告する。
"""
import json
import sys
import os
import glob

def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)  # R-10: 壊れた入力でもターンを止めない

    knowledge_base = os.path.expanduser("~/.sdd-knowledge")
    
    if not os.path.isdir(knowledge_base):
        sys.exit(0)
    
    # 各ディレクトリのファイル数をカウント
    starters_dir = os.path.join(knowledge_base, "starters")
    retro_dir = os.path.join(knowledge_base, "retrospectives")
    archive_dir = os.path.join(knowledge_base, "docs-archive")
    
    starter_categories = []
    if os.path.isdir(starters_dir):
        starter_categories = [d for d in os.listdir(starters_dir) 
                            if os.path.isdir(os.path.join(starters_dir, d))]
    
    retro_count = 0
    if os.path.isdir(retro_dir):
        retro_count = len([f for f in glob.glob(os.path.join(retro_dir, "*.json"))
                          if os.path.basename(f) != "summary.json"])
    
    archive_count = 0
    if os.path.isdir(archive_dir):
        archive_count = len([d for d in os.listdir(archive_dir)
                           if os.path.isdir(os.path.join(archive_dir, d))])
    
    # 何もなければ無言
    if not starter_categories and retro_count == 0 and archive_count == 0:
        sys.exit(0)
    
    parts = []
    if starter_categories:
        parts.append(f"スターター: {', '.join(starter_categories)}")
    if retro_count > 0:
        parts.append(f"教訓: {retro_count}件")
    if archive_count > 0:
        parts.append(f"アーカイブ: {archive_count}件")
    
    # v15.1: `systemMessage`（利用者に表示される）。v15.0 の `message` は認識されないキーだった
    result = {
        "systemMessage": f"📚 SDD知識ベース: {' | '.join(parts)}"
    }
    json.dump(result, sys.stdout, ensure_ascii=False)
    sys.exit(0)

if __name__ == "__main__":
    main()