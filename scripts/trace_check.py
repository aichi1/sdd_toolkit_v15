#!/usr/bin/env python3
"""
trace_check.py: 要件 → SKILL → outputs のトレーサビリティを機械的に検査する（R-15）。

背景（`skills/phase-08/SKILL.md`）:
  Iteration 1 では要件 29 件・課題 51 件を人手で追跡しており、
  **未対応要件や孤立タスクの検出は目視に依存**していた。

  対応表を出すだけなら目視と変わらない。**検出が要点**である。

規約は `docs/rules-reference/requirement-id-convention.md`（v15.0 まではツールキット開発
プロジェクトの `docs/requirements.md` §9 にあった。以下の §9.x はその節番号）。
本スクリプトはその規約に従ってのみ ID を抽出する。

  * §5 の表の行だけが R-ID の**定義**（散文の言及は定義ではない）
  * `> 対応要件:` で始まる**1 行だけ**が SKILL の**宣言**（本文の言及は宣言ではない）
  * `requirements_addressed` は JSON の配列（散文を読まない）

  この限定は Phase 07 の Critical #40 と同じ発想である ——
  **証跡は決められた 1 行・決められた表であって、散文ではない。**
  範囲を構造で狭めることで、自然言語の判定を一切しないで済ませている。

  規約のどれにも当てはまらない書き方は `convention_violation` として**報告する**。
  黙って読み飛ばさない（Phase 07 の C-42: 解釈できない行を静かに飛ばして検査が空振りした）。

使い方:
  python3 scripts/trace_check.py                 # 人が読む形式
  python3 scripts/trace_check.py --json          # 機械可読
  python3 scripts/trace_check.py --markdown      # trace-report.md に貼る対応表
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path


class ConventionViolation(ValueError):
    """`docs/requirements.md` §9 の規約に反する書き方。"""


# §5 の表の 1 列目。装飾（** と ~~）は意味を変えない（§9.2）
_ID_CELL = re.compile(r"^(?:~~)?\s*(?:\*\*)?\s*(?:~~)?\s*R-(\d+)\s*(?:~~)?\s*(?:\*\*)?\s*(?:~~)?$")
# SKILL.md の宣言行（§9.4）。**この行だけ**を読む
_DECL_LINE = re.compile(r"^>\s*対応要件\s*[:：]")
_RID_IN_DECL = re.compile(r"R-(\d+)")
_SECTION_5 = "## 5. 機能要件（R-ID）"
# 横断要件を表すトークン（§9.3）
_CROSSCUT = {"全", "各フェーズ"}


def _norm(num: str) -> str:
    """`R-1` と `R-01` を同じ ID にする（§9.2: 2 桁ゼロ埋め）。"""
    return f"R-{int(num):02d}"


def parse_phase_cell(cell: str):
    """§5「実現フェーズ」列を解釈する（§9.3）。

    戻り値は `(フェーズ番号の集合, 横断要件か)`。
    認めるのはフェーズ番号 / カンマ区切り / `全`・`各フェーズ` / 括弧注記つきのみ。
    **それ以外のトークンがあれば ConventionViolation を送出する**（黙って飛ばさない）。
    """
    # 括弧内は注記。**括弧内の数字をフェーズと誤読しない**
    s = re.sub(r"[（(][^）)]*[）)]", "", cell)
    s = s.replace("**", "").replace("~~", "").strip()
    phases, crosscut = set(), False
    for tok in re.split(r"[,、]", s):
        tok = tok.strip()
        if not tok:
            continue
        if tok in _CROSSCUT:
            crosscut = True
        elif re.fullmatch(r"\d{1,2}", tok):
            phases.add(int(tok))
        else:
            raise ConventionViolation(tok)
    return phases, crosscut


def extract_requirements(root: str) -> dict:
    """`docs/requirements.md` §5 の表から R-ID を抽出する。

    **§5 の節に限定する。** §4（C-ID）や §7（S-ID）の表、散文中の言及は読まない。
    """
    src = Path(root) / "docs" / "requirements.md"
    if not src.is_file():
        return {}
    text = src.read_text(encoding="utf-8", errors="replace")
    if _SECTION_5 not in text:
        return {}
    body = text.split(_SECTION_5, 1)[1]
    body = re.split(r"^## ", body, maxsplit=1, flags=re.MULTILINE)[0]

    out = {}
    for i, line in enumerate(body.split("\n"), 1):
        if not line.lstrip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        m = _ID_CELL.match(cells[0]) if cells else None
        if not m:
            continue
        rid = _norm(m.group(1))
        if len(cells) < 4:
            # 「実現フェーズ」列の無い要件行を黙って捨てない（v15.1。以前は `continue` で
            # 読み飛ばし、要件が 1 件減ったまま OK を返していた）
            out[rid] = {"id": rid, "text": cells[1] if len(cells) > 1 else "",
                        "phase_cell": "", "phases": set(), "crosscut": False,
                        "violation": f"列が {len(cells)} 個しかない（実現フェーズは 4 列目）"}
            continue
        entry = {"id": rid, "text": cells[1], "phase_cell": cells[3]}
        try:
            entry["phases"], entry["crosscut"] = parse_phase_cell(cells[3])
            entry["violation"] = None
        except ConventionViolation as e:
            entry["phases"], entry["crosscut"] = set(), False
            entry["violation"] = str(e)
        out[rid] = entry
    return out


def extract_skill_declarations(root: str) -> dict:
    """`skills/phase-NN/SKILL.md` の**宣言行 1 行**から R-ID を抽出する（§9.4）。

    本文中の R-ID は宣言ではない。本フェーズ自身の SKILL.md 本文には
    「R-19〜R-26 が未対応」と書いてあるが、それは負例の説明であって担当宣言ではない。
    """
    out = {}
    base = Path(root) / "skills"
    if not base.is_dir():
        return out
    for sk in sorted(base.glob("phase-*/SKILL.md")):
        phase = sk.parent.name.split("-", 1)[1]
        ids = set()
        for line in sk.read_text(encoding="utf-8", errors="replace").split("\n"):
            if _DECL_LINE.match(line.strip()):
                ids |= {_norm(n) for n in _RID_IN_DECL.findall(line)}
        out[phase] = ids
    return out


def extract_output_claims(root: str) -> dict:
    """`outputs/phase-NN/.metadata.json` の `requirements_addressed`（JSON の配列）。"""
    out = {}
    base = Path(root) / "outputs"
    if not base.is_dir():
        return out
    for md in sorted(base.glob("phase-*/.metadata.json")):
        phase = md.parent.name.split("-", 1)[1]
        try:
            data = json.loads(md.read_text(encoding="utf-8"))
        except Exception:
            out[phase] = set()
            continue
        vals = (data.get("requirements_addressed") or []) if isinstance(data, dict) else []
        ids = set()
        for v in vals if isinstance(vals, list) else []:
            m = re.fullmatch(r"R-(\d+)", str(v).strip())
            if m:
                ids.add(_norm(m.group(1)))
        out[phase] = ids
    return out


def _phase_entries(phases):
    """`metadata.json` の `phases` を (フェーズ番号の文字列, 値) の列にする。

    正の形は `{"1": {"status": ...}}`（辞書。`/init-task` ステップ3.2・`/run-phase` Step 4.1）。
    v15.0 の `/init-task` は `phases` の形を規定しておらず、実プロジェクトで
    `[{"phase": 1, "status": ...}]`（配列）が作られ、本スクリプトが AttributeError で
    落ちた。**既存プロジェクトを壊さないよう配列も読む**。
    """
    if isinstance(phases, dict):
        return list(phases.items())
    if isinstance(phases, list):
        return [(str(v.get("phase")), v) for v in phases if isinstance(v, dict)]
    return []


def completed_phases(root: str) -> set:
    """ルート `metadata.json` が completed 系と記録しているフェーズ番号。"""
    p = Path(root) / "metadata.json"
    if not p.is_file():
        return set()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return set()
    if not isinstance(data, dict):
        return set()
    done = set()
    for k, v in _phase_entries(data.get("phases")):
        if isinstance(v, dict) and str(v.get("status", "")).startswith("completed"):
            try:
                done.add(int(k))
            except ValueError:
                pass
    return done


def build_matrix(root: str) -> list:
    """要件 → SKILL → outputs の対応表。**全要件**を 1 行ずつ含む。"""
    reqs = extract_requirements(root)
    decls = extract_skill_declarations(root)
    claims = extract_output_claims(root)
    rows = []
    for rid in sorted(reqs, key=lambda x: int(x.split("-")[1])):
        e = reqs[rid]
        rows.append({
            "id": rid,
            "text": e["text"],
            "phase_cell": e["phase_cell"],
            "declared_in": sorted(p for p, ids in decls.items() if rid in ids),
            "delivered_in": sorted(p for p, ids in claims.items() if rid in ids),
            "crosscut": e["crosscut"],
            "violation": e["violation"],
        })
    return rows


def check_traceability(root: str) -> list:
    """未対応・孤立・不整合を検出する。

    kind の意味:
      missing_section       requirements.md に §5 の見出しが無く 1 件も読めない（**欠陥**。v15.1）
      convention_violation  §9.3 に反する「実現フェーズ」の書き方（**規約違反。欠陥**）
      overdue               完了済みフェーズが担当のはずなのに宣言が無い（**欠陥**）
      orphan_skill          SKILL が宣言する ID が docs に無い（**欠陥**）
      orphan_output         outputs が申告する ID が docs に無い（**欠陥**）
      phase_mismatch        docs の実現フェーズと宣言フェーズが食い違う（**欠陥**）
      not_delivered         宣言はあるが完了フェーズの outputs に申告が無い（**欠陥**）
      planned               担当する SKILL がまだ無い（**欠陥ではない。予定どおり**）
      assigned              SKILL は宣言済みだがフェーズ未完了（**欠陥ではない。進行中**）
      crosscutting          `全` / `各フェーズ`（**欠陥ではない**）
    """
    root = os.path.abspath(root)
    reqs = extract_requirements(root)
    decls = extract_skill_declarations(root)
    claims = extract_output_claims(root)
    done = completed_phases(root)

    known = set(reqs)
    findings = []

    def add(rid, kind, message, phases=None):
        findings.append({"check": "traceability", "reference": rid, "kind": kind,
                         "message": message, "phases": sorted(phases or [])})

    # `docs/requirements.md` があるのに §5 の見出しが無い → 「要件 0 件・欠陥 0 件・OK」と
    # 黙って通さない（v15.1）。v15.0 の `/init-task` はこの見出しを生成しておらず、
    # 実プロジェクトで `/analyze` が何も検査せずに OK を返していた。
    # ファイル自体が無い（`/init-task` 前のツールキット単体）は従来どおり 0 件で OK。
    req_path = Path(root) / "docs" / "requirements.md"
    if req_path.is_file() and _SECTION_5 not in req_path.read_text(
            encoding="utf-8", errors="replace"):
        add("docs/requirements.md", "missing_section",
            f"`{_SECTION_5}` の見出しが無いため要件を 1 件も読めない。"
            "見出しと表（`| ID | 要件 | 対応課題 | 実現フェーズ | 検証 |`）の規約は "
            "`docs/rules-reference/requirement-id-convention.md`")

    for rid in sorted(known, key=lambda x: int(x.split("-")[1])):
        e = reqs[rid]
        if e["violation"] is not None:
            add(rid, "convention_violation",
                f"「実現フェーズ」列が規約外: `{e['violation']}`"
                f"（`docs/rules-reference/requirement-id-convention.md` §3.1）", e["phases"])
            continue
        if e["crosscut"] and not e["phases"]:
            add(rid, "crosscutting", "横断要件（`全` / `各フェーズ`）。特定フェーズの宣言を要求しない")
            continue

        declared = {p for p, ids in decls.items() if rid in ids}
        delivered = {p for p, ids in claims.items() if rid in ids}
        for ph in sorted(e["phases"]):
            key = f"{ph:02d}"
            if key not in declared:
                if ph in done:
                    add(rid, "overdue",
                        f"Phase {key} は完了しているが `skills/phase-{key}/SKILL.md` の"
                        f"「> 対応要件:」に {rid} が無い", [ph])
                else:
                    add(rid, "planned", f"Phase {key} は未着手。予定どおり未対応", [ph])
            elif ph in done and key not in delivered:
                add(rid, "not_delivered",
                    f"Phase {key} は {rid} を宣言しているが "
                    f"`outputs/phase-{key}/.metadata.json` の `requirements_addressed` に無い", [ph])
            elif ph not in done:
                add(rid, "assigned",
                    f"Phase {key} が宣言済み。フェーズ未完了のため申告はまだ無い", [ph])
        # docs が指定していないフェーズが宣言している
        extra = declared - {f"{p:02d}" for p in e["phases"]}
        if extra and not e["crosscut"]:
            add(rid, "phase_mismatch",
                f"`docs/requirements.md` は Phase {sorted(e['phases'])} と定めるが、"
                f"Phase {sorted(extra)} の SKILL.md が宣言している", e["phases"])

    for ph, ids in sorted(decls.items()):
        for rid in sorted(ids - known):
            add(rid, "orphan_skill",
                f"`skills/phase-{ph}/SKILL.md` が宣言しているが "
                f"`docs/requirements.md` §5 に定義が無い", [int(ph)])
    for ph, ids in sorted(claims.items()):
        for rid in sorted(ids - known):
            add(rid, "orphan_output",
                f"`outputs/phase-{ph}/.metadata.json` が申告しているが "
                f"`docs/requirements.md` §5 に定義が無い", [int(ph)])
    return findings


# 欠陥として扱う分類（exit 1 になる）。planned / crosscutting は**欠陥ではない**
DEFECT_KINDS = {"missing_section", "convention_violation", "overdue", "orphan_skill",
                "orphan_output", "phase_mismatch", "not_delivered"}


def _markdown(rows, findings):
    by_id = {}
    for f in findings:
        by_id.setdefault(f["reference"], []).append(f["kind"])
    out = ["| 要件 | 実現フェーズ（docs） | SKILL の宣言 | outputs の申告 | 状態 |",
           "|------|--------------------|-------------|---------------|------|"]
    for r in rows:
        kinds = sorted(set(by_id.get(r["id"], [])))
        state = "／".join(kinds) if kinds else "対応済み"
        out.append(f"| `{r['id']}` | {r['phase_cell']} | "
                   f"{', '.join(r['declared_in']) or '—'} | "
                   f"{', '.join(r['delivered_in']) or '—'} | {state} |")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="要件のトレーサビリティ検査（R-15）。ファイルは変更しない")
    ap.add_argument("--project-dir", default=".")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--markdown", action="store_true", help="対応表を Markdown で出す")
    args = ap.parse_args()

    root = os.path.abspath(args.project_dir)
    if not os.path.isdir(root):
        # 検査対象が無いのに「欠陥 0 件・OK」を返さない（v15.1）
        print(f"ERROR: --project-dir {root} が存在しない", file=sys.stderr)
        return 2
    rows = build_matrix(root)
    findings = check_traceability(root)
    defects = [f for f in findings if f["kind"] in DEFECT_KINDS]

    if args.json:
        print(json.dumps({"matrix": rows, "findings": findings}, ensure_ascii=False, indent=2))
    elif args.markdown:
        print(_markdown(rows, findings))
    else:
        print("=== Trace Check ===\n")
        print(f"  要件 {len(rows)} 件を検査した\n")
        for kind in ("missing_section", "convention_violation", "overdue", "orphan_skill", "orphan_output",
                     "phase_mismatch", "not_delivered", "planned", "assigned", "crosscutting"):
            hits = [f for f in findings if f["kind"] == kind]
            if not hits:
                continue
            mark = "✗" if kind in DEFECT_KINDS else "・"
            print(f"  [{kind}] {len(hits)} 件")
            for f in hits:
                print(f"    {mark} {f['reference']}: {f['message']}")
            print()
        print(f"Result: 欠陥 {len(defects)} 件 / 未着手（予定どおり）"
              f" {len([f for f in findings if f['kind'] == 'planned'])} 件")
        print("Status: " + ("DEFECT" if defects else "OK"))
    return 1 if defects else 0


if __name__ == "__main__":
    sys.exit(main())
