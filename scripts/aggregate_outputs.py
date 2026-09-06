#!/usr/bin/env python3
"""
aggregate_outputs.py: `outputs/phase-NN/` の成果物を `outputs/final/` に集約する（C-45 / R-33）。

背景（C-45。Phase 05 の `/finalize` 実行時に発見）:
  `.claude/skills/finalize/SKILL.md` の従来の集約規則は「フェーズ番号の昇順で処理し、
  同名ファイルは後のフェーズが上書きする（後勝ち方式）」だった。本プロジェクトのように
  **全フェーズが同名の証跡**（`change-report.md` / `patch.diff` / `verification.log`）を持つ
  ドッグフーディング型プロジェクトでは、後勝ち方式は旧フェーズの証跡を**黙って失う**
  （実測: 66 種のファイル名のうち 3 種が全 5 フェーズで衝突し、Phase 01-04 分が失われた）。

集約規約（オーナー決定 2026-09-06、Phase 12）:
  **後勝ちを廃止し、衝突するファイルは `phase-NN-<元のファイル名>` に改名して両方残す。**
  衝突しないファイルは元の相対パスのまま置く。

C-45 のもう一方の実測症状（修正サイクル 1 巡目。Validator Critical #4）:
  `docs/requirements.md` C-45 は Phase 05 の実測として 2 症状を挙げていた。上記の
  `phase-NN-` 改名は症状 (1)（同名ファイルの後勝ち消失）のみを解消し、症状 (2)
  （`outputs/phase-02/git-zone-backup/` 配下 52 件——C-23 の退避証跡——が
  プレフィックスなしのまま最終成果物に混入する）が再現していた。
  **オーナー決定（2026-09-06）**: 除外パターンの設定可能化（選択肢 (b)）は採らず、
  `git-zone-backup` を除外ディレクトリに追加して解消する（本フェーズは既に
  +54 テストを追加しており、これ以上攻撃面を広げない）。

Usage:
  python3 scripts/aggregate_outputs.py --project-dir . [--dry-run] [--json]
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

EXCLUDE_FILENAMES = {".metadata.json", ".phase-context.json"}
EXCLUDE_DIR_NAMES = {".validation", "__pycache__", "git-zone-backup"}


def _is_phase_dir(path: Path) -> bool:
    """`outputs/phase-NN` の形をしたディレクトリか（`outputs/final` 等は対象外）。"""
    if not path.is_dir() or not path.name.startswith("phase-"):
        return False
    suffix = path.name[len("phase-"):]
    return suffix.isdigit()


def _phase_number(path: Path) -> int:
    return int(path.name[len("phase-"):])


def _iter_phase_files(outputs_dir: Path):
    """フェーズディレクトリをフェーズ番号昇順で走査し、集約対象ファイルを列挙する。

    戻り値: [(phase_num, phase_dir, rel_path, abs_path), ...]（フェーズ番号昇順）
    """
    result = []
    phase_dirs = sorted((p for p in outputs_dir.glob("phase-*") if _is_phase_dir(p)),
                        key=_phase_number)
    for phase_dir in phase_dirs:
        phase_num = _phase_number(phase_dir)
        for src in sorted(phase_dir.rglob("*")):
            if src.is_dir():
                continue
            if src.name in EXCLUDE_FILENAMES:
                continue
            if any(p.name in EXCLUDE_DIR_NAMES for p in src.parents):
                continue
            if src.name == "README.md":
                continue
            if src.suffix == ".pyc":
                continue
            rel = src.relative_to(phase_dir)
            result.append((phase_num, phase_dir, rel, src))
    return result


def find_conflicts(outputs_dir: Path) -> dict:
    """相対パスが同じファイルを複数フェーズに持つものを返す。

    戻り値: {"相対パス": [衝突したフェーズ番号のリスト（出現順）]}（衝突が無いものは含まない）
    """
    by_rel: dict[str, list[int]] = {}
    for phase_num, _, rel, _ in _iter_phase_files(outputs_dir):
        by_rel.setdefault(str(rel), []).append(phase_num)
    return {rel: phases for rel, phases in by_rel.items() if len(phases) > 1}


def aggregate_outputs(project_dir, dry_run: bool = False) -> dict:
    """`outputs/phase-NN/` を `outputs/final/` に集約する（C-45 / R-33）。

    衝突するファイルは `phase-NN-<元のファイル名>` に改名して両方残す。
    衝突しないファイルは元の相対パスのまま置く。`dry_run=True` の場合はファイルを書かない。

    Returns:
        {"copied": [...], "renamed": [[rel, phase_num, new_rel], ...], "conflicts": {...}}
    """
    project_dir = Path(project_dir)
    outputs_dir = project_dir / "outputs"
    final_dir = outputs_dir / "final"
    if not dry_run:
        final_dir.mkdir(parents=True, exist_ok=True)

    files = _iter_phase_files(outputs_dir)
    conflicts = find_conflicts(outputs_dir)

    copied, renamed = [], []
    for phase_num, _phase_dir, rel, src in files:
        rel_str = str(rel)
        if rel_str in conflicts:
            new_name = f"phase-{phase_num:02d}-{rel.name}"
            dest_rel = (rel.parent / new_name) if str(rel.parent) != "." else Path(new_name)
            renamed.append([rel_str, phase_num, str(dest_rel)])
        else:
            dest_rel = rel
            copied.append(rel_str)

        if not dry_run:
            dest = final_dir / dest_rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)

    return {"copied": copied, "renamed": renamed, "conflicts": conflicts}


def main():
    ap = argparse.ArgumentParser(
        description="outputs/phase-NN/ の成果物を outputs/final/ に集約する（C-45/R-33）")
    ap.add_argument("--project-dir", default=".", help="プロジェクトルート")
    ap.add_argument("--dry-run", action="store_true", help="コピーせず集計だけ表示する")
    ap.add_argument("--json", action="store_true", help="JSON で出力")
    args = ap.parse_args()

    result = aggregate_outputs(args.project_dir, dry_run=args.dry_run)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"copied (no conflict): {len(result['copied'])}")
        print(f"renamed (phase-NN- 接頭辞で両方保持): {len(result['renamed'])}")
        print(f"conflicting relative paths: {len(result['conflicts'])}")
        for rel, phases in sorted(result["conflicts"].items()):
            print(f"  - {rel}: phases {phases}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
