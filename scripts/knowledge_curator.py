#!/usr/bin/env python3
"""knowledge-curator のロジック（テスト用スタンドアロン版）。

レトロスペクティブ JSON を処理し、コンポーネントの改善候補を生成する。

Usage:
    python3 knowledge_curator.py <retrospective.json> [--kb-dir PATH]
"""

import argparse
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from registry_utils import load_json_safe, now_iso


def get_default_kb_dir() -> str:
    return os.path.expanduser("~/.sdd-knowledge")


# C-53 / R-34: 教訓の `applicability` が「制限なし」を意味するとみなす正規化済みの値。
# **完全一致のみ**を「広い」とみなす（`spec_check.py` の許可リストと同じ発想。
# 自然言語の全文一致や部分文字列一致で「広い/狭い」を推測しない）。
_BROAD_APPLICABILITY = {"all projects", "all", "any project", "any", ""}


def is_broad_applicability(lesson) -> bool:
    """レッスンの `applicability` がカテゴリ全体への無差別適用を許すか判定する（C-53）。

    `applicability` が「self-modifying projects」のような**具体的なスコープ**を持つ教訓は、
    タグの重なりが無い限りカテゴリ内の全コンポーネントへ無差別に付与してはならない
    （実測: 教訓 10 件が同一カテゴリの 5 スキル全部に付与され 50 件の候補になった）。
    `applicability` フィールドが無い、または `_BROAD_APPLICABILITY` に完全一致する場合のみ
    「広い」とみなし、従来どおりカテゴリ一致だけで関連コンポーネントとする。
    """
    if not isinstance(lesson, dict):
        return True  # 文字列教訓は絞り込み情報が無いため従来どおり（後方互換）
    value = str(lesson.get("applicability", "")).strip().lower()
    return value in _BROAD_APPLICABILITY


def find_related_components(
    registry: dict, category: str, lesson_keywords: list[str], broad: bool = True
) -> list[dict]:
    """レッスンに関連するコンポーネントをレジストリから検索する。

    `broad=False`（`applicability` が具体的なスコープを持つ教訓）の場合、
    **カテゴリ一致だけでの無差別マッチを行わない**。タグの重なりが
    MIN_TAG_OVERLAP 件以上あるコンポーネントのみを対象にする（C-53 / R-34）。
    """
    related = []
    for comp in registry.get("components", []):
        # カテゴリ一致（`broad` のときだけ無差別マッチを許す。C-53）
        if broad and comp.get("category_origin") == category:
            related.append(comp)
            continue
        # タグマッチ。共通キーワードが MIN_TAG_OVERLAP 件以上のときだけ（C-46）
        comp_tags = set(comp.get("tags", []))
        if len(comp_tags & set(lesson_keywords)) >= MIN_TAG_OVERLAP:
            related.append(comp)
    return related


# --- retrospective JSON の形式差を吸収する（C-46）----------------------------
# `/retrospective` が生成する形式と、2026-02 期の一部のファイルで
# キー名が異なる。取り違えにより **教訓ループが全期間にわたって機能していなかった**。
#   - カテゴリ:   metadata.category（現行） / category（旧）
#   - 教訓の配列: lessons_learned（現行） / lessons（旧）
#   - 教訓の本文: lesson + evidence + applicability（現行） / description + context（旧）


# キーワードから除く一般語。これを入れないとタグマッチが noise で埋まる（C-46）
_STOPWORDS = {
    "that", "this", "with", "from", "have", "been", "will", "when", "then",
    "than", "them", "they", "there", "these", "those", "what", "which", "while",
    "into", "over", "same", "such", "only", "also", "some", "more", "most",
    "each", "both", "were", "does", "done", "make", "made", "used", "using",
    "note", "case", "cases", "type", "types", "file", "files", "line", "lines",
    "projects", "project", "quality", "criteria", "applicability", "evidence",
    "lesson", "lessons", "category", "priority", "process", "tools", "all",
}

# 1 つの教訓に紐づける候補の上限。上限がないと 1 レトロで 1,500 件を超え、
# 「候補」として人がレビューできる量にならない（C-46 の修正時に実測）
MAX_CANDIDATES_PER_LESSON = 5

# タグマッチに必要な最小の共通キーワード数。1 だと一般語 1 つで無関係な
# コンポーネントが引っかかる
MIN_TAG_OVERLAP = 2


def generalizable_tags(keywords: list[str], limit: int = 3) -> list[str]:
    """タグとして提案できるキーワードだけを返す（C-46）。

    `c-26` `r-08` `s-04` `d-01` のようなプロジェクト固有の ID は、
    マッチングには有用だが**他プロジェクトのコンポーネントのタグとしては無意味**なので除く。
    """
    import re
    # 課題 ID は必ずハイフン付き（c-26 / r-08 / s-04）。ハイフンを任意にすると
    # c1234 のような通常の語まで除外してしまう
    return [w for w in keywords if not re.fullmatch(r"[crsdkhm]-\d+", w)][:limit]


def retro_category(retro: dict) -> str:
    """retrospective JSON からカテゴリを取り出す（両形式に対応）。"""
    md = retro.get("metadata")
    if isinstance(md, dict) and md.get("category"):
        return md["category"]
    return retro.get("category", "unknown")


def retro_project_name(retro: dict) -> str:
    """プロジェクト名を取り出す（両形式に対応。C-46）。

    `lesson_source` が全件 `unknown` になっていたのは、トップレベルの `project_name` を
    読んでいたため。現行形式では `metadata.project_name` にある。
    """
    md = retro.get("metadata")
    if isinstance(md, dict) and md.get("project_name"):
        return md["project_name"]
    return retro.get("project_name", "unknown")


def retro_lessons(retro: dict) -> list:
    """教訓の配列を取り出す（両形式に対応）。"""
    for key in ("lessons_learned", "lessons"):
        v = retro.get(key)
        if isinstance(v, list) and v:
            return v
    return []


def lesson_text(lesson) -> str:
    """教訓オブジェクトから本文を組み立てる（両形式に対応）。

    旧実装は `description` と `context` のみを読んでいたため、現行形式では
    **常に空文字列**になり、キーワードマッチが一度も発火しなかった。
    """
    if not isinstance(lesson, dict):
        return str(lesson)
    parts = [lesson.get(k, "") for k in
             ("lesson", "description", "evidence", "context", "applicability")]
    return " ".join(str(p) for p in parts if p)


def extract_lesson_keywords(lesson: dict) -> list[str]:
    """レッスンからキーワードを抽出する。"""
    import re

    text = lesson_text(lesson)   # C-46: 現行形式では description/context が存在しない

    # 英語キーワード（4文字以上）+ 課題 ID（C-42 等）。一般語は除く（C-46）
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9_-]+", text.lower())
    kws = [w for w in words if len(w) > 3 and w not in _STOPWORDS]
    # 重複を除きつつ出現順を保つ
    seen, out = set(), []
    for w in kws:
        if w not in seen:
            seen.add(w); out.append(w)
    return out


def generate_improvement_candidates(
    retro: dict, registry: dict
) -> list[dict]:
    """レトロスペクティブから改善候補を生成する。"""
    candidates = []
    category = retro_category(retro)   # C-46: metadata.category / category の両対応
    lessons = retro_lessons(retro)     # C-46: lessons_learned / lessons の両対応

    for lesson in lessons:
        keywords = extract_lesson_keywords(lesson)
        broad = is_broad_applicability(lesson)   # C-53: applicability による絞り込み
        related = find_related_components(registry, category, keywords, broad=broad)

        # C-46: 旧実装は dict 全体を文字列化して候補に入れていた
        lesson_desc = lesson_text(lesson)
        priority = (
            lesson.get("priority", "medium")
            if isinstance(lesson, dict)
            else "medium"
        )

        for comp in related[:MAX_CANDIDATES_PER_LESSON]:   # C-46: 上限
            candidates.append({
                "timestamp": now_iso(),
                "action": "update_metadata",
                "component_id": comp["id"],
                "component_name": comp.get("name", ""),
                "lesson_source": retro_project_name(retro),   # C-46: metadata.project_name / project_name
                "lesson_description": lesson_desc,
                "suggested_changes": {
                    "add_tags": generalizable_tags(keywords),   # C-46: 固有 ID を除く
                    "update_quality_criteria": lesson_desc
                    if priority == "high"
                    else None,
                    "adjust_effectiveness": -0.05
                    if priority == "high"
                    else 0.0,
                },
                "priority": priority,
            })

    return candidates


# v15.1 / C-57: curator 候補の重複判定キー。curator 候補には `suggested_id` が無いため
# `extract_components.py` と同じキーは使えない。`timestamp` は実行のたびに変わるので含めない。
# `component_name` / `priority` / `suggested_changes` は registry と教訓から導出される従属値
# なので含めない（キーを最小にして、同じ教訓 × 同じコンポーネントを確実に同一視する）。
CURATOR_KEY_FIELDS = ("action", "component_id", "lesson_source", "lesson_description")


def curator_candidate_key(c) -> str | None:
    """curator 候補の重複判定キーを返す（v15.1 / C-57）。

    `CURATOR_KEY_FIELDS` のどれかを欠く行（`extract_components.py` の候補や未知の形式）は
    curator 候補ではないので None を返す。値が list 等でもハッシュできるよう JSON 文字列にする。
    `promote_candidates.py` の圧縮も同じキーで curator 候補を重複排除する（キーを 1 箇所に置く）。
    """
    if not isinstance(c, dict) or any(k not in c for k in CURATOR_KEY_FIELDS):
        return None
    return json.dumps([c[k] for k in CURATOR_KEY_FIELDS], ensure_ascii=False, sort_keys=True)


def load_existing_curator_keys(path: str) -> set:
    """`candidates.jsonl` に既にある curator 候補のキー集合を読み込む（v15.1 / C-57）。

    壊れた行・object でない行・curator 候補でない行は無視する（全体を止めない。R-10 と同じ思想）。
    """
    keys = set()
    if not os.path.exists(path):
        return keys
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            k = curator_candidate_key(d)
            if k is not None:
                keys.add(k)
    return keys


def append_curator_candidates(candidates: list[dict], kb_dir: str) -> int:
    """改善候補のうち新規のものだけを candidates.jsonl に追記する。

    v15.1 / C-57: 以前は無条件に追記しており、同じ retrospective を 2 回処理すると
    同じ候補が 2 行ずつ溜まった（`extract_components.py` の C-54 と同じ欠陥パターンの
    「別ファイルの兄弟関数」）。既存行と同じキー（`curator_candidate_key()`）の候補、
    および同じバッチ内で既に採用したキーの候補はスキップする。新規が 0 件ならファイルを
    開かずに 0 を返す（空ファイルを作らない）。

    Returns:
        実際に追記した件数。
    """
    path = os.path.join(kb_dir, "candidates.jsonl")
    os.makedirs(kb_dir, exist_ok=True)

    seen = load_existing_curator_keys(path)
    new_candidates = []
    for c in candidates:
        k = curator_candidate_key(c)
        if k is not None:
            if k in seen:
                continue
            seen.add(k)   # バッチ内の重複も 1 件にする
        new_candidates.append(c)

    if not new_candidates:
        return 0

    with open(path, "a", encoding="utf-8") as f:
        for c in new_candidates:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    return len(new_candidates)


def update_curator_memory(
    memory_lines: list[str], retro_name: str, candidate_count: int
) -> list[str]:
    """curator の MEMORY.md を更新する（200行制限対策付き）。

    Returns:
        更新後の行リスト。
    """
    MAX_LINES = 180  # 安全マージン付き

    new_entry = (
        f"- [{datetime.now().strftime('%Y-%m-%d')}] "
        f"Processed {retro_name}: {candidate_count} candidates generated"
    )

    # 処理履歴セクションを見つけるか新規追加
    history_idx = -1
    for i, line in enumerate(memory_lines):
        if "## Processing History" in line:
            history_idx = i
            break

    if history_idx < 0:
        memory_lines.append("\n## Processing History")
        memory_lines.append(new_entry)
    else:
        memory_lines.insert(history_idx + 1, new_entry)

    # 履歴エントリ数を制限（200行制限への対策）
    max_history = 20  # 最新20件のみ保持
    trimmed = []
    in_history = False
    history_count = 0

    for line in memory_lines:
        if "## Processing History" in line:
            in_history = True
            trimmed.append(line)
            continue
        if in_history and line.startswith("- ["):
            history_count += 1
            if history_count <= max_history:
                trimmed.append(line)
            continue
        if in_history and not line.startswith("- ["):
            in_history = False
        trimmed.append(line)

    memory_lines = trimmed

    return memory_lines


def main():
    parser = argparse.ArgumentParser(
        description="Process retrospective and generate improvement candidates"
    )
    parser.add_argument("retrospective", help="Path to retrospective JSON file")
    parser.add_argument("--kb-dir", default=get_default_kb_dir())
    args = parser.parse_args()

    # レトロスペクティブを読み込み
    retro = load_json_safe(args.retrospective)
    if retro is None:
        print(f"Error: Cannot read {args.retrospective}", file=sys.stderr)
        sys.exit(1)

    # レジストリを読み込み
    registry_path = os.path.join(args.kb_dir, "registry.json")
    registry = load_json_safe(registry_path)
    if registry is None:
        print(f"Warning: No registry.json at {registry_path}")
        registry = {"components": []}

    # 改善候補を生成
    candidates = generate_improvement_candidates(retro, registry)
    print(f"Generated {len(candidates)} improvement candidates")

    if candidates:
        count = append_curator_candidates(candidates, args.kb_dir)
        print(f"Appended {count} candidates to candidates.jsonl "
              f"({len(candidates) - count} duplicates skipped, C-57)")

        # サマリー表示
        for c in candidates:
            print(f"  - [{c['priority']}] {c['component_id']}: {c['lesson_description'][:60]}")


if __name__ == "__main__":
    main()
