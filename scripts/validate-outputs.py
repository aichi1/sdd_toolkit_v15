#!/usr/bin/env python3
"""
validate-outputs.py: Builder 成果物の自動プリチェック

Validator エージェント起動前に実行し、機械的に検証可能な項目を自動チェックする。
手動の Validator レビューの前段として、明らかな欠落を早期検出する。

Usage:
    python3 scripts/validate-outputs.py --phase 1
    python3 scripts/validate-outputs.py --phase 1 --category research_report
    python3 scripts/validate-outputs.py --phase 1 --project-type mkdocs
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_validate_rules(project_dir):
    """validate_rules.yaml を読み込む。存在しない/パースエラー時は None を返す。"""
    rules_path = project_dir / "validate_rules.yaml"
    if not rules_path.is_file():
        # scripts/ 配下も探す（配置場所の柔軟性）
        rules_path = project_dir / "scripts" / "validate_rules.yaml"
    if not rules_path.is_file():
        # config/ 配下も探す
        rules_path = project_dir / "config" / "validate_rules.yaml"
    if not rules_path.is_file():
        return None

    try:
        import yaml
    except ImportError:
        print("WARNING: pyyaml が未インストールのため validate_rules.yaml を読み込めません。"
              " generic カテゴリとして続行します。")
        print("  → pip install pyyaml でインストールしてください。")
        return None

    try:
        with open(rules_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data
    except Exception as e:
        print("WARNING: validate_rules.yaml のパースに失敗しました: {}".format(e))
        print("  → generic カテゴリとして続行します。")
        return None


def get_project_type_rules(rules_data, project_type):
    """指定されたプロジェクトタイプのルールを取得する。"""
    if rules_data is None:
        return {"skip_checks": [], "required_checks": []}

    categories = rules_data.get("categories", {})
    if project_type not in categories:
        return None  # 不明なカテゴリ

    cat_rules = categories[project_type]
    return {
        "skip_checks": cat_rules.get("skip_checks", []),
        "required_checks": cat_rules.get("required_checks", []),
    }


def should_skip_check(check_name, skip_patterns):
    """チェック名がスキップパターンに一致するかを判定する。"""
    import fnmatch
    for pattern in skip_patterns:
        if fnmatch.fnmatch(check_name, pattern):
            return True
        # パターンがチェック名に含まれるかも確認（部分一致）
        if pattern in check_name:
            return True
    return False


def get_valid_phases(metadata):
    """
    metadata.json から有効なフェーズ番号リストを返す。

    - iterations[] がある場合: 全イテレーションのフェーズを統合
    - iterations[] がない場合: 1〜phase_count の連番
    """
    if "iterations" in metadata and metadata["iterations"]:
        valid = []
        for iter_data in metadata["iterations"]:
            valid.extend(iter_data.get("phases", []))
        return sorted(set(valid))

    phase_count = metadata.get("phase_count", 0)
    return list(range(1, phase_count + 1))


def _deliverable_paths(deliverables):
    """`.metadata.json` の deliverables を (パス文字列のリスト, 解釈できない要素のリスト) に分ける。

    v15.1: 要素は文字列（`"report.md"`。planner.md の例）と
    `{"file": "report.md", ...}`（builder.md / builder-validator-detail.md の例）の両形式が
    実在するため、両方を受け付ける。それ以外は黙って捨てず warn として報告する。
    """
    paths, bad = [], []
    for d in deliverables:
        if isinstance(d, str) and d.strip():
            paths.append(d.strip())
        elif isinstance(d, dict) and isinstance(d.get("file"), str) and d["file"].strip():
            paths.append(d["file"].strip())
        else:
            bad.append(d)
    return paths, bad


def check_listed_deliverables(phase_dir, project_root, deliverables):
    """`.metadata.json` の deliverables に列挙された成果物が存在し、空でないか（v15.1）。

    Quality Gate 0（免除不可）:「列挙した成果物が存在し、空でない」。
    旧実装は「隠しファイル以外のファイルが 1 つ以上あるか」しか見ておらず、
    **0 バイトの report.md だけがあり analysis.md が欠落していても PASS / exit 0** だった
    （プリチェック PASS はファストパスで Validator を省略する入口なので、Gate 0 の穴がそのまま素通りする）。

    パスはまず `outputs/phase-NN/` 基準、無ければプロジェクトルート基準で解決する
    （`docs/x.md` のように in-place の成果物を列挙するプロジェクトがあるため）。
    `.validation/` 配下は Validator の検証レポートであり成果物として数えない。
    """
    issues = []
    paths, bad = _deliverable_paths(deliverables)
    if bad:
        issues.append({
            "check": "deliverables_listed_format",
            "status": "warn",
            "message": ("deliverables の要素を解釈できない（文字列か {{\"file\": ...}} のみ対応）: {}"
                        .format(", ".join(repr(b)[:60] for b in bad)))
        })

    validation_dir = (phase_dir / ".validation").resolve()
    problems = []
    for p in paths:
        target = next((c for c in (phase_dir / p, project_root / p) if c.exists()), None)
        if target is None:
            problems.append("{}（存在しない）".format(p))
            continue
        resolved = target.resolve()
        if resolved == validation_dir or validation_dir in resolved.parents:
            problems.append("{}（.validation/ 配下は成果物として数えない）".format(p))
        elif target.is_dir():
            if not any(target.iterdir()):
                problems.append("{}（空のディレクトリ）".format(p))
        elif target.stat().st_size == 0:
            problems.append("{}（0 バイト）".format(p))

    if problems:
        issues.append({
            "check": "deliverables_listed",
            "status": "fail",
            "message": (".metadata.json の deliverables に列挙された成果物が欠落または空: {}"
                        "（Quality Gate 0: 成果物は存在し、空でないこと）".format(", ".join(problems)))
        })
    elif paths:
        issues.append({
            "check": "deliverables_listed",
            "status": "pass",
            "message": "deliverables に列挙された成果物 {} 件がすべて存在し、空でない".format(len(paths))
        })
    return issues


def check_file_existence(outputs_dir, phase):
    """成果物ディレクトリとメタデータの存在チェック"""
    issues = []
    phase_dir = outputs_dir / "phase-{:02d}".format(phase)
    listed = None     # .metadata.json の deliverables（v15.1: 列挙された成果物の実在チェック用）

    if not phase_dir.is_dir():
        issues.append({
            "check": "phase_dir_exists",
            "status": "fail",
            "message": "outputs/phase-{:02d}/ ディレクトリが存在しない".format(phase)
        })
        return issues, phase_dir

    issues.append({
        "check": "phase_dir_exists",
        "status": "pass",
        "message": "outputs/phase-{:02d}/ ディレクトリが存在する".format(phase)
    })

    metadata_path = phase_dir / ".metadata.json"
    if not metadata_path.is_file():
        issues.append({
            "check": "metadata_exists",
            "status": "fail",
            "message": ".metadata.json が存在しない"
        })
    else:
        issues.append({
            "check": "metadata_exists",
            "status": "pass",
            "message": ".metadata.json が存在する"
        })
        try:
            meta = load_json(metadata_path)
            for field in ["phase", "deliverables"]:
                if field not in meta:
                    issues.append({
                        "check": "metadata_field_{}".format(field),
                        "status": "fail",
                        "message": ".metadata.json に必須フィールド '{}' がない".format(field)
                    })
            if isinstance(meta, dict):
                listed = meta.get("deliverables")
        except (json.JSONDecodeError, Exception) as e:
            issues.append({
                "check": "metadata_valid_json",
                "status": "fail",
                "message": ".metadata.json の JSON パースエラー: {}".format(e)
            })

    # 成果物ファイルが1つ以上あるか
    content_files = [f for f in phase_dir.iterdir()
                     if f.is_file() and not f.name.startswith(".")]
    if not content_files:
        issues.append({
            "check": "has_deliverables",
            "status": "fail",
            "message": "成果物ファイルが1つもない（隠しファイル以外）"
        })
    else:
        issues.append({
            "check": "has_deliverables",
            "status": "pass",
            "message": "成果物ファイル {} 件".format(len(content_files))
        })

    # v15.1: deliverables が列挙されていれば、その 1 件ずつの実在と非空を確かめる。
    # 未指定・空リストなら上の「1 件以上あるか」だけ（従来どおり）。
    if isinstance(listed, list) and listed:
        issues.extend(check_listed_deliverables(phase_dir, outputs_dir.parent, listed))
    elif listed and not isinstance(listed, list):
        issues.append({
            "check": "deliverables_listed_format",
            "status": "warn",
            "message": ".metadata.json の deliverables がリストでないため、列挙された成果物の実在を検査できない"
        })

    return issues, phase_dir


def check_skill_quality_criteria(phase_dir, skills_dir, phase):
    """SKILL.md の Quality Criteria を成果物と照合"""
    issues = []
    skill_path = skills_dir / "phase-{:02d}".format(phase) / "SKILL.md"

    if not skill_path.is_file():
        issues.append({
            "check": "skill_md_exists",
            "status": "fail",
            "message": "skills/phase-{:02d}/SKILL.md が存在しない".format(phase)
        })
        return issues

    # v15.1: errors="replace"。Shift_JIS などの非 UTF-8 ファイルで UnicodeDecodeError を出して
    # プリチェック全体が落ちていた（check_change_report_sections は既に replace だった）
    skill_text = skill_path.read_text(encoding="utf-8", errors="replace")

    # Quality Criteria セクションを抽出
    criteria_match = re.search(
        r"## Quality Criteria\s*\n(.*?)(?=\n## |\Z)",
        skill_text, re.DOTALL
    )
    if not criteria_match:
        issues.append({
            "check": "has_quality_criteria",
            "status": "warn",
            "message": "SKILL.md に Quality Criteria セクションがない"
        })
        return issues

    criteria_text = criteria_match.group(1)
    criteria_items = re.findall(r"- \[ \] (.+)", criteria_text)

    if not criteria_items:
        issues.append({
            "check": "has_quality_criteria",
            "status": "warn",
            "message": "Quality Criteria にチェック項目がない"
        })
        return issues

    issues.append({
        "check": "has_quality_criteria",
        "status": "pass",
        "message": "Quality Criteria: {} 項目".format(len(criteria_items))
    })

    # 成果物テキストを結合して簡易チェック（v15.1: 非 UTF-8 でも落ちないよう errors="replace"）
    all_output_text = ""
    for f in phase_dir.iterdir():
        if f.is_file() and f.suffix == ".md" and not f.name.startswith("."):
            all_output_text += f.read_text(encoding="utf-8", errors="replace") + "\n"

    # 必須セクションキーワードの簡易存在チェック
    section_keywords = {
        "TL;DR": ["tl;dr", "tldr", "エグゼクティブサマリー", "executive summary"],
        "比較軸": ["比較軸", "評価軸", "comparison", "criteria"],
        "出典": ["出典", "参考文献", "references", "sources"],
        "不確実性": ["不確実性", "留意点", "limitation", "caveat", "注意事項"],
        "リスク": ["リスク", "risk"],
        "次アクション": ["次アクション", "next action", "ロードマップ", "roadmap"],
        "選択肢": ["選択肢", "案a", "案b", "option", "alternative"],
        "テスト": ["test", "pytest", "unittest"],
    }

    for criterion in criteria_items:
        criterion_lower = criterion.lower()
        found_keyword = False
        for label, keywords in section_keywords.items():
            if any(kw in criterion_lower for kw in keywords):
                if any(kw in all_output_text.lower() for kw in keywords):
                    found_keyword = True
                    break
        # We don't mark fail here since this is a heuristic;
        # just record what we found for the Validator to use

    return issues


# --- Executed Verification 表の解析（C-42）---------------------------------
# exit code 欄の書式: 数字のみ、または数字 + 括弧注記（例: `0（4件とも）` / `1 (意図的)`）
_EXIT_CODE_RE = re.compile(r"^(\d+)\s*(?:[（(]\s*([^）)]*?)\s*[）)])?$")
_INTENTIONAL_RE = re.compile(r"^(意図的|expected|期待値)$")


# `## Executed Verification` の見出しパターン（C-36 / C-47）
#   C-36: 接尾辞を許す（例: 「（実行者: Validator 自身）」）
#   C-47: **接頭辞の番号を許す**（例: 「## 6. Executed Verification」）。
#         Validator が見出しに番号を振るだけで検査対象が見つからなくなり、
#         **19 行の exit code が一度も検査されないまま warn で素通りしていた**。
#         判定は warn（fail ではない）ため PASS もブロックしない。C-42 と同じ型の穴。
_EV_HEADING = r"^#{2,3}[ \t]*(?:\d+[.)]?[ \t]*)*Executed Verification"


# `Overall Status` 行の書式（v15.1）。**閉じた集合**として列挙し、散文から推測しない:
#   **Overall Status**: PASS         既定の書式（validator.md のテンプレート）
#   **Overall Status**: **PASS**     判定語だけ太字
#   **Overall Status: PASS**         太字が全体を囲む
#   **Overall Status**: ✅ PASS      判定語の前に絵文字 1 つ（下の集合のみ）
#   **Overall Status**：PASS         全角コロン
# 判定語も PASS / NEEDS_REVISION / FAIL の 3 つに限る。
# 旧実装は `\*\*Overall Status\*\*` 固定 + 任意の大文字列だったため、上の 2〜4 行目の書式では
# overall="" となり、**exit≠0 の行があるのに「整合している」と判定して PASS を素通りさせていた**。
_STATUS_EMOJI = "\u2705\u274c\u26a0\u2714\u2716\U0001F7E2\U0001F7E1\U0001F534"  # ✅❌⚠✔✖🟢🟡🔴
_OVERALL_STATUS_RE = re.compile(
    r"\*\*Overall Status\**\s*[:：]\s*\**\s*"
    r"(?:[" + _STATUS_EMOJI + r"]\ufe0f?\s*)?\**\s*"
    r"(PASS|NEEDS_REVISION|FAIL)(?![A-Za-z0-9_])")


def _split_markdown_row(line):
    r"""Markdown 表の 1 行をセルに分割する。

    `\|`（エスケープされたパイプ）はセル区切りとして扱わない。

    素朴な `split("|")` はコマンド中のパイプで列をずらし、exit code 欄に
    コマンドの断片を紛れ込ませる（C-42）。その結果 exit code の機械チェックが
    その行を黙って読み飛ばし、**exit≠0 の行を PASS のまま通せてしまった**。
    第1条を自己申告から機械強制に移した C-34 の仕組みそのものの穴だった。
    """
    placeholder = "\x00ESCAPED_PIPE\x00"
    s = line.strip().replace("\\|", placeholder)
    s = s.strip("|")
    return [c.replace(placeholder, "|").strip().strip("`").strip()
            for c in s.split("|")]


def check_executed_verification(phase_dir):
    """`.validation/report.md` の `## Executed Verification` セクションを確認する。

    --require-verification 指定時のみ呼ばれる（デフォルト False で既存挙動は変わらない）。
    docs/constitution.md 第1条 / docs/io-spec.md §2.6（Phase 03 以降必須）に対応。

    2 段階のチェックを行う:
      (1) セクションの存在と表の行数 → 無ければ WARN（既存フェーズの再検証を壊さないため FAIL にしない）
      (2) **exit code 列と Overall Status の整合** → 非 0 の行があるのに PASS なら FAIL
          （M2 / Phase 03。第1条の強制点を Validator の自己申告から機械チェックへ移す）
    """
    report = phase_dir / ".validation" / "report.md"
    if not report.is_file():
        return []          # report 自体が無い場合は既存チェックに委ねる（挙動不変）

    # v15.1: errors="replace"。非 UTF-8 のレポートで UnicodeDecodeError を出して落ちないようにする
    text = report.read_text(encoding="utf-8", errors="replace")
    if not re.search(_EV_HEADING, text, re.MULTILINE):
        return [{"check": "executed_verification", "status": "warn",
                 "message": ".validation/report.md に '## Executed Verification' セクションがない"}]

    # セクション本文だけを取り出す（次の ## まで、または末尾まで）
    # 見出しに接尾辞（例: 「（実行者: Validator 自身）」）が付いても抽出できるようにする（C-36）
    m = re.search(_EV_HEADING + r"[^\n]*\n(.*?)(?=\n#{2,3}[ \t]|\Z)", text,
                  re.DOTALL | re.MULTILINE)
    section = m.group(1) if m else ""
    # 表のデータ行（先頭が "| 数字 |"）のみ。ヘッダ行と区切り行は除外
    row_lines = [ln for ln in section.splitlines()
                 if re.match(r"^\|\s*\d+\s*\|", ln)]

    if not row_lines:
        return [{"check": "executed_verification", "status": "warn",
                 "message": ".validation/report.md の Executed Verification 表に行がない"}]

    issues = [{"check": "executed_verification", "status": "pass",
               "message": "Executed Verification: {} 行検出".format(len(row_lines))}]

    # --- (2) exit code 列と Overall Status の整合（M2）---
    failing = []
    intentional = []
    malformed = []
    for ln in row_lines:
        # C-42: `\|` を区切りとして扱わない。素朴な split("|") は列をずらす
        cells = _split_markdown_row(ln)
        # 期待レイアウト: # | コマンド | exit code | 要約 | ...
        num = cells[0] if cells else "?"
        cmd = cells[1][:60] if len(cells) > 1 else ln.strip()[:60]
        if len(cells) < 3:
            malformed.append((num, cmd, "列が 3 つ未満"))
            continue
        # 太字装飾（**1**）を剥がす
        code = cells[2].replace("*", "").strip()
        if code.upper() == "N/A":
            continue          # 「該当なし」行は判定対象外
        m_code = _EXIT_CODE_RE.match(code)
        if not m_code:
            # exit code 欄を解釈できない。**黙って読み飛ばさない**（C-42）
            malformed.append((num, cmd, code[:40]))
            continue
        value = int(m_code.group(1))
        note = (m_code.group(2) or "").strip()
        if value == 0:
            continue
        # 意図的に非 0 で終了するコマンドの明示マーカー（C-37）。
        # 例: `1 (意図的)` / `1 (expected)`。N/A と同じく「明示されていること」が濫用の歯止め。
        if _INTENTIONAL_RE.match(note):
            intentional.append((num, cmd, code))
        else:
            failing.append((num, cmd, code))

    status_m = _OVERALL_STATUS_RE.search(text)
    overall = status_m.group(1) if status_m else ""

    if failing:
        detail = "; ".join("行{}: `{}` exit={}".format(n, c, e) for n, c, e in failing)
        if overall == "PASS":
            issues.append({
                "check": "executed_verification_exit_code",
                "status": "fail",
                "message": ("Overall Status が PASS だが exit code が 0 でない行が {} 件ある（{}）。"
                            "constitution.md 第1条: exit≠0 のコマンドが1つでもあれば PASS にできない"
                            .format(len(failing), detail))})
        elif not overall:
            # v15.1: 判定語を読めないまま「整合している」とはみなさない（黙って通さない。C-42 と同じ型）
            issues.append({
                "check": "executed_verification_exit_code",
                "status": "fail",
                "message": ("exit code が 0 でない行が {} 件ある（{}）が、Overall Status を読み取れない。"
                            "`**Overall Status**: PASS / NEEDS_REVISION / FAIL` の書式で書くこと。"
                            "判定を読めないまま整合しているとはみなさない（constitution.md 第1条）"
                            .format(len(failing), detail))})
        else:
            issues.append({
                "check": "executed_verification_exit_code",
                "status": "pass",
                "message": ("exit≠0 の行が {} 件あり、Overall Status は {} （PASS ではない）。整合している"
                            .format(len(failing), overall))})
    else:
        issues.append({"check": "executed_verification_exit_code", "status": "pass",
                       "message": "exit code が 0 でない行はない"})

    if malformed:
        detail = "; ".join("行{}: `{}` → exit code 欄が `{}`".format(n, c, e)
                           for n, c, e in malformed)
        issues.append({
            "check": "executed_verification_malformed",
            "status": "fail",
            "message": ("exit code 欄を解釈できない行が {} 件ある（{}）。"
                        "コマンド中のパイプは `\\|` とエスケープし、exit code 欄には"
                        "数字（必要なら `1 (意図的)` のような注記付き）か `N/A` を書くこと。"
                        "constitution.md 第1条: 判定できない行を黙って読み飛ばさない（C-42）"
                        .format(len(malformed), detail))})

    if intentional:
        detail = "; ".join("行{}: `{}` {}".format(n, c, e) for n, c, e in intentional)
        issues.append({
            "check": "executed_verification_intentional",
            "status": "pass",
            "message": ("意図的に非 0 で終了するコマンドが {} 件（判定対象外）: {}"
                        .format(len(intentional), detail))})

    return issues


def check_category_required_sections(phase_dir, category, skip_patterns=None):
    """カテゴリテンプレートの必須セクション存在チェック"""
    issues = []
    if skip_patterns is None:
        skip_patterns = []

    required_sections = {
        "research_report": [
            ("TL;DR", ["tl;dr", "tldr", "エグゼクティブサマリー", "executive summary"]),
            ("比較軸", ["比較軸", "評価軸", "比較の観点"]),
            ("不確実性・留意点", ["不確実性", "留意点", "limitation", "注意事項"]),
            ("出典・参考文献", ["出典", "参考文献", "references", "sources"]),
        ],
        "small_implementation": [
            ("README", []),  # README.md existence check instead
            ("src/", []),    # Directory existence check
            ("tests/", []),  # Directory existence check
        ],
        "internal_proposal": [
            ("目的と成功条件", ["目的", "成功条件", "objective", "success"]),
            ("選択肢比較", ["選択肢", "案a", "案b", "option", "alternative"]),
            ("リスクと対策", ["リスク", "対策", "risk", "mitigation"]),
            ("次アクション", ["次アクション", "next action", "ロードマップ", "roadmap", "担当"]),
        ],
    }

    if category not in required_sections:
        return issues

    # Collect all output text（v15.1: 非 UTF-8 でも落ちないよう errors="replace"）
    all_output_text = ""
    for f in phase_dir.iterdir():
        if f.is_file() and f.suffix == ".md" and not f.name.startswith("."):
            all_output_text += f.read_text(encoding="utf-8", errors="replace") + "\n"
    all_lower = all_output_text.lower()

    for section_name, keywords in required_sections[category]:
        # Check if this section should be skipped by project-type rules
        if should_skip_check(section_name, skip_patterns):
            issues.append({
                "check": "required_section_{}".format(section_name),
                "status": "pass",
                "message": "スキップ: {} (project-type ルールにより除外)".format(section_name)
            })
            continue

        if category == "small_implementation" and not keywords:
            # Special: check directory/file existence
            target = phase_dir / section_name.rstrip("/")
            if section_name == "README":
                target = phase_dir / "README.md"
            exists = target.exists()
            issues.append({
                "check": "required_section_{}".format(section_name),
                "status": "pass" if exists else "fail",
                "message": "{}: {}".format("存在" if exists else "欠落", section_name)
            })
        elif keywords:
            found = any(kw in all_lower for kw in keywords)
            issues.append({
                "check": "required_section_{}".format(section_name),
                "status": "pass" if found else "warn",
                "message": "{}: {} (キーワードベースの簡易チェック)".format(
                    "検出" if found else "未検出", section_name)
            })

    return issues


def _strip_fenced_blocks(text):
    """コードフェンスで囲まれた部分を取り除く。

    **必須要件の充足判定に使う**ため、迷ったら「フェンス内」と見なす側に倒す:
    閉じられていないフェンスがあれば残り全体をフェンス内として落とす。
    その結果 `## 4.` などが見つからなくなり **fail** になる —— 安全側である。

    フェンス種別（``` と ~~~）と長さを見て、**同じ種別・同じ長さ以上**でしか閉じない
    （CommonMark と同じ規則。種別を区別しないと入れ子で誤爆する。Phase 07 の Critical #37）。
    """
    out = []
    fence = None            # (文字, 長さ)
    for line in text.split("\n"):
        st = line.lstrip()
        m = re.match(r"^(`{3,}|~{3,})", st)
        if m:
            ch, n = m.group(1)[0], len(m.group(1))
            if fence is None:
                fence = (ch, n)
                continue
            if ch == fence[0] and n >= fence[1] and not st[n:].strip():
                fence = None
                continue
        if fence is None:
            out.append(line)
    return "\n".join(out)

# docs/io-spec.md §2.3 が定める change-report.md の必須セクション（C-48）
_CHANGE_REPORT_SECTIONS = [
    (1, "変更ファイル一覧"),
    (2, "変更の意図"),
    (3, "影響範囲"),
    (4, "Claude Code バージョン確認結果"),
    (5, "settings.json / hooks の前後差分"),
    (6, "ロールバック手順"),
]


def check_change_report_sections(phase_dir):
    """`change-report.md` が `docs/io-spec.md` §2.3 の必須 6 セクションを持つか（C-48）。

    Phase 05 以降、§4 / §5 の**番号を保ったまま内容を差し替える**運用に無断でドリフトし、
    7 巡の Validator が誰も見ていなかった。成果物の中身は毎回検査されたが、
    **io-spec が定める形式そのもの**と突き合わせる切り口が無かった
    （C-26 / C-42 / C-47 と同型で、**検査する仕組みの側に穴がある**）。

    番号と見出し文言の**両方**を見る。7 節目以降の追加は自由（本プロジェクトは
    修正サイクルの記録を §12 以降に積む）。
    """
    report = phase_dir / "change-report.md"
    if not report.is_file():
        return []          # 存在しない場合は既存の成果物チェックに委ねる（挙動不変）

    # フェンス内に必須見出しを**引用**しただけで pass させない（Critical #35）
    text = _strip_fenced_blocks(report.read_text(encoding="utf-8", errors="replace"))
    missing = []
    for num, title in _CHANGE_REPORT_SECTIONS:
        pat = r"^##[ \t]+{}\.[ \t]*{}".format(num, re.escape(title))
        if not re.search(pat, text, re.MULTILINE):
            missing.append("## {}. {}".format(num, title))

    if missing:
        return [{"check": "change_report_sections", "status": "fail",
                 "message": "change-report.md に docs/io-spec.md §2.3 の必須セクションが無い: "
                            + ", ".join(missing)}]
    return [{"check": "change_report_sections", "status": "pass",
             "message": "change-report.md が docs/io-spec.md §2.3 の必須 6 セクションを満たす"}]

def main():
    ap = argparse.ArgumentParser(description="Builder 成果物の自動プリチェック")
    ap.add_argument("--phase", type=int, required=True, help="対象フェーズ番号")
    ap.add_argument("--category", type=str, default="",
                     help="タスクカテゴリ (research_report, small_implementation, internal_proposal)")
    ap.add_argument("--project-type", type=str, default="",
                     help="プロジェクトタイプ (mkdocs, python, nodejs, generic)")
    ap.add_argument("--project-dir", type=str, default=".", help="プロジェクトルート")
    ap.add_argument("--require-verification", action="store_true",
                     help=".validation/report.md に Executed Verification セクションを要求する")
    args = ap.parse_args()

    project = Path(args.project_dir).resolve()
    outputs_dir = project / "outputs"
    skills_dir = project / "skills"

    # Auto-detect category from metadata.json if not specified
    category = args.category
    if not category:
        meta_path = project / "metadata.json"
        if meta_path.is_file():
            try:
                meta = load_json(meta_path)
                category = meta.get("category", "")
            except Exception:
                pass

    # Load project-type rules
    project_type = args.project_type
    skip_patterns = []
    rules_data = None

    if project_type:
        rules_data = load_validate_rules(project)
        if rules_data is not None:
            type_rules = get_project_type_rules(rules_data, project_type)
            if type_rules is None:
                print("ERROR: 不明なプロジェクトタイプ '{}' が指定されました。".format(project_type))
                if rules_data and "categories" in rules_data:
                    valid_types = list(rules_data["categories"].keys())
                    print("  有効なタイプ: {}".format(", ".join(valid_types)))
                # v15.1: 有効なタイプを並べるだけでは、新しいタイプの足し方が分からなかった
                print("  → 新しいタイプは validate_rules.yaml の `categories:` の下に追加できる"
                      "（書式はファイル冒頭のコメントを参照）")
                sys.exit(1)
            skip_patterns = type_rules["skip_checks"]
            print("[INFO] Project type: {}".format(project_type))
            if skip_patterns:
                print("[INFO] Skipped checks: {}".format(", ".join(skip_patterns)))
        else:
            print("[WARNING] validate_rules.yaml が見つかりません。generic として続行します。")
            project_type = "generic"

    # フェーズ番号の妥当性チェック（イテレーション認識）
    meta_path = project / "metadata.json"
    if meta_path.is_file():
        try:
            project_meta = load_json(meta_path)
            valid_phases = get_valid_phases(project_meta)
            if valid_phases and args.phase not in valid_phases:
                print("Warning: Phase {} は metadata.json の有効フェーズ "
                      "({}) に含まれていません。".format(args.phase, valid_phases))
        except Exception:
            pass  # メタデータ読み取り失敗時はスキップ（後方互換）

    all_issues = []

    # Check 1: File existence
    file_issues, phase_dir = check_file_existence(outputs_dir, args.phase)
    all_issues.extend(file_issues)

    if not phase_dir.is_dir():
        print_report(all_issues, args.phase, category, project_type, skip_patterns)
        sys.exit(1)

    # Check 2: SKILL.md Quality Criteria
    skill_issues = check_skill_quality_criteria(phase_dir, skills_dir, args.phase)
    all_issues.extend(skill_issues)

    # Check 3: Category-specific required sections (with skip patterns applied)
    if category:
        section_issues = check_category_required_sections(
            phase_dir, category, skip_patterns)
        all_issues.extend(section_issues)

    # Check 4: Executed Verification section (--require-verification のみ。デフォルト False で挙動不変)
    if args.require_verification:
        verification_issues = check_executed_verification(phase_dir)
        all_issues.extend(verification_issues)

    # Check 5: change-report.md の必須セクション（C-48。docs/io-spec.md §2.3）
    if not should_skip_check("change_report_sections", skip_patterns):
        all_issues.extend(check_change_report_sections(phase_dir))

    print_report(all_issues, args.phase, category, project_type, skip_patterns)

    # Exit code: 1 if any fail, 0 otherwise
    has_fail = any(i["status"] == "fail" for i in all_issues)
    sys.exit(1 if has_fail else 0)


def print_report(issues, phase, category, project_type="", skip_patterns=None):
    """プリチェック結果を表示"""
    if skip_patterns is None:
        skip_patterns = []

    pass_count = sum(1 for i in issues if i["status"] == "pass")
    warn_count = sum(1 for i in issues if i["status"] == "warn")
    fail_count = sum(1 for i in issues if i["status"] == "fail")

    print("=== Pre-Validation: Phase {} ===".format(phase))
    if category:
        print("Category: {}".format(category))
    if project_type:
        print("Project type: {}".format(project_type))
    if skip_patterns:
        skipped_count = sum(
            1 for i in issues
            if "スキップ" in i.get("message", "") and "project-type" in i.get("message", "")
        )
        if skipped_count:
            print("Skipped checks: {} ({} checks skipped by project-type rules)".format(
                ", ".join(skip_patterns), skipped_count))
    print()

    for issue in issues:
        icon = {"pass": "✓", "warn": "⚠", "fail": "✗"}[issue["status"]]
        print("  {} [{}] {}".format(icon, issue["check"], issue["message"]))

    print()
    print("Result: {} pass, {} warn, {} fail".format(pass_count, warn_count, fail_count))

    if fail_count > 0:
        print("Status: FAIL - Validator 実行前に修正が必要")
    elif warn_count > 0:
        print("Status: WARN - Validator で詳細確認を推奨")
    else:
        print("Status: PASS - Validator 実行可能")


if __name__ == "__main__":
    main()
