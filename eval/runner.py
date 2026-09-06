#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
eval/runner.py — `/eval` の半自動化（R-19 / R-20）

`eval/scenarios/` の各シナリオを `claude -p` で実行し、採点（Judge）を別セッションに分離する。
軌跡指標（turns / retries / tool_calls）の**定義**は `docs/io-spec.md` §6 を参照すること。
実装はその定義に従うだけで、独自の解釈を追加しない（`skills/phase-11/SKILL.md` Procedure 1）。

## 安全設計（第8条・constitution.md 第4条）

- **デフォルトでは実際に `claude -p` を呼び出さない**（`--live` を付けない限り `source=not_run` を記録するだけ）。
  実 API 呼び出しはコストと時間を伴い、無条件の自動実行はふさわしくない
- `--live` 実行時は、cwd を一時ディレクトリにし `--setting-sources user` を付ける（`docs/io-spec.md` §6.4）。
  これを外すと、本プロジェクト自身の CLAUDE.md / hooks / Auto Memory を読み込み、
  シナリオと無関係な自己言及的な探索が起きることを実測済み（2026-09-06、`session_id: fa5c9763-...`）
- `--bare` は使わない。本環境（OAuth ログイン）では認証が失敗することを実測済み（`session_id: 71292e56-...`）
- Judge は `.claude/agents/eval-judge.md` の本文を `--append-system-prompt` で渡し、
  `--tools Read,Glob,Grep` で技術的に読み取り専用を強制する（Write/Edit/Bash を持たせない）
- 出力は `eval/summary_trajectory.csv` のみ。**`eval/summary.csv` / `eval/rubric.json` / `eval/scenarios/` は
  一切変更しない**（`docs/constitution.md` 第4条。既存 `eval/aggregate.py` の入出力にも触れない）
"""

import argparse
import csv
import json
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVAL_DIR = ROOT / "eval"
SCENARIOS_DIR = EVAL_DIR / "scenarios"
RUBRIC_PATH = EVAL_DIR / "rubric.json"
JUDGE_AGENT_PATH = ROOT / ".claude" / "agents" / "eval-judge.md"
TRAJECTORY_CSV = EVAL_DIR / "summary_trajectory.csv"

TRAJECTORY_HEADER = [
    "date", "iteration_id", "scenario", "turns", "retries", "tool_calls",
    "model", "session_id", "duration_ms", "cost_usd", "source",
]

SCENARIO_NAMES = ["T1_research", "T2_implement", "T3_proposal"]


class RunnerError(Exception):
    """シナリオ/Judge 実行に関する回復不能なエラー（実行不能・応答不正など）。"""


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_scenario_task(scenario: str, scenarios_dir: Path = SCENARIOS_DIR) -> str:
    path = scenarios_dir / scenario / "task.md"
    if not path.exists():
        raise RunnerError(f"scenario task not found: {path}")
    return path.read_text(encoding="utf-8")


def read_agent_body(path: Path = JUDGE_AGENT_PATH) -> str:
    """YAML frontmatter（`---`〜`---`）を除いた本文のみを返す。"""
    if not path.exists():
        raise RunnerError(f"judge agent definition not found: {path}")
    text = path.read_text(encoding="utf-8")
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            return parts[2].strip()
    return text.strip()


def run_claude_p(prompt, cwd, model, extra_args=None, timeout=600):
    """
    `claude -p` をサブプロセスとして実行し、`--output-format stream-json` の NDJSON を全行パースする。

    戻り値: (events: list[dict], final_result: dict|None, exit_code: int, raw_stdout: str)
    `final_result` は最後に現れる `{"type": "result", ...}` 行（turns / retries / cost の一次情報源）。
    """
    cmd = [
        "claude", "-p", prompt,
        "--output-format", "stream-json",
        "--model", model,
        "--setting-sources", "user",
        "--no-session-persistence",
        "--verbose",
    ] + list(extra_args or [])
    try:
        proc = subprocess.run(
            cmd, cwd=str(cwd), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            timeout=timeout, text=True,
        )
        stdout = proc.stdout or ""
        returncode = proc.returncode
    except FileNotFoundError as e:
        raise RunnerError(f"claude コマンドが見つかりません: {e}")
    except subprocess.TimeoutExpired as e:
        stdout = (e.stdout or "") if isinstance(e.stdout, str) else ""
        returncode = -1

    events = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # stream-json 以外の雑音行（進捗表示等）は無視する

    final_result = None
    for ev in reversed(events):
        if isinstance(ev, dict) and ev.get("type") == "result":
            final_result = ev
            break

    return events, final_result, returncode, stdout


def compute_trajectory(events, final_result):
    """
    `docs/io-spec.md` §6 の定義どおりに turns / retries / tool_calls を計算する。
    取得できない場合は `"unknown"`（推測値で埋めない。§6.5）。
    """
    if final_result is None:
        return {
            "turns": "unknown", "retries": "unknown", "tool_calls": "unknown",
            "session_id": "unknown", "duration_ms": "unknown", "cost_usd": "unknown",
        }

    turns = final_result.get("num_turns", "unknown")

    permission_denials = final_result.get("permission_denials", [])
    denial_count = len(permission_denials) if isinstance(permission_denials, list) else "unknown"

    tool_call_count = 0
    tool_error_count = 0
    for ev in events:
        if not isinstance(ev, dict):
            continue
        msg = ev.get("message", {})
        content = msg.get("content", []) if isinstance(msg, dict) else []
        if not isinstance(content, list):
            continue
        if ev.get("type") == "assistant":
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tool_call_count += 1
        elif ev.get("type") == "user":
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result" and block.get("is_error"):
                    tool_error_count += 1

    if isinstance(denial_count, int):
        retries = denial_count + tool_error_count
    else:
        retries = "unknown"

    return {
        "turns": turns,
        "retries": retries,
        "tool_calls": tool_call_count,
        "session_id": final_result.get("session_id", "unknown"),
        "duration_ms": final_result.get("duration_ms", "unknown"),
        "cost_usd": final_result.get("total_cost_usd", "unknown"),
    }


def extract_json_object(text):
    """応答テキストから最初の `{`〜最後の `}` を抜き出して parse する（前後の説明文を許容する）。"""
    if not isinstance(text, str):
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None


def run_scenario_live(scenario, model, timeout, scenarios_dir=SCENARIOS_DIR):
    """
    1 シナリオを隔離した一時ディレクトリで実際に実行する。

    `--permission-mode acceptEdits` を付ける。実測（2026-09-06、`session_id: f005ff98-...`）で、
    このフラグ無しでは Write への許可プロンプトに応答者（host）がおらず、
    `deliverable.md` への保存が拒否されて成果物が 0 件になることを確認した
    （`permission_denials` は空だが `result` が「許可をお願いします」で終わる。
    エージェント自身は完全なレポート本文を生成できていた）。
    **`--dangerously-skip-permissions` / `bypassPermissions` は使わない**——
    影響範囲を「このセッションの Edit/Write プロンプトを自動承認する」だけに絞り、
    かつ対象は隔離した使い捨ての一時ディレクトリのみである（本プロジェクトのリポジトリには一切触れない）。
    """
    task_text = read_scenario_task(scenario, scenarios_dir)
    tmpdir = Path(tempfile.mkdtemp(prefix=f"sdd-eval-{scenario}-"))
    output_path = tmpdir / "deliverable.md"
    prompt = (
        f"{task_text}\n\n---\n"
        "これは非対話の自動実行パイプラインです。質問には応答できません。"
        "対象（技術/製品/手法など）が具体的に指定されていない場合は、"
        "あなた自身が妥当な具体例を1つ選び、その前提を成果物内に明記した上で、"
        "確認を待たずに最後まで作業を完了させてください。\n"
        f"作業ディレクトリは {tmpdir} です。成果物を Markdown 1 ファイルとして "
        f"{output_path} に保存してください。保存が終わったら『完了』とだけ返信してください。"
    )
    events, final_result, exit_code, raw = run_claude_p(
        prompt=prompt, cwd=tmpdir, model=model, timeout=timeout,
        extra_args=["--permission-mode", "acceptEdits"],
    )
    trajectory = compute_trajectory(events, final_result)
    deliverable_text = output_path.read_text(encoding="utf-8") if output_path.exists() else None
    return {
        "scenario": scenario,
        "tmpdir": str(tmpdir),
        "deliverable_path": str(output_path) if output_path.exists() else None,
        "deliverable_text": deliverable_text,
        "exit_code": exit_code,
        "trajectory": trajectory,
        "raw_stdout_tail": raw[-2000:] if raw else "",
    }


def run_judge_live(scenario, deliverable_text, model, timeout,
                    scenarios_dir=SCENARIOS_DIR, rubric_path=RUBRIC_PATH, judge_agent_path=JUDGE_AGENT_PATH):
    """採点を Builder（シナリオ実行）とは別の `claude -p` セッションで行う。読み取り専用。"""
    checklist_path = scenarios_dir / scenario / "checklist.json"
    if not checklist_path.exists():
        raise RunnerError(f"checklist not found: {checklist_path}")
    checklist = load_json(checklist_path)
    rubric = load_json(rubric_path)
    judge_body = read_agent_body(judge_agent_path)

    tmpdir = Path(tempfile.mkdtemp(prefix=f"sdd-eval-judge-{scenario}-"))
    (tmpdir / "deliverable.md").write_text(deliverable_text or "(成果物なし)", encoding="utf-8")
    (tmpdir / "checklist.json").write_text(json.dumps(checklist, ensure_ascii=False, indent=2), encoding="utf-8")
    (tmpdir / "rubric.json").write_text(json.dumps(rubric, ensure_ascii=False, indent=2), encoding="utf-8")

    prompt = (
        "以下を採点してください。\n"
        f"- 成果物: {tmpdir}/deliverable.md\n"
        f"- checklist: {tmpdir}/checklist.json\n"
        f"- rubric: {tmpdir}/rubric.json\n"
        "score.json の JSON のみを最終応答として返してください（説明文を前後に付けない）。"
    )
    extra_args = ["--append-system-prompt", judge_body, "--tools", "Read,Glob,Grep"]
    events, final_result, exit_code, raw = run_claude_p(
        prompt=prompt, cwd=tmpdir, model=model, extra_args=extra_args, timeout=timeout,
    )
    trajectory = compute_trajectory(events, final_result)
    score = extract_json_object(final_result.get("result")) if final_result else None
    return {
        "score": score, "exit_code": exit_code, "trajectory": trajectory,
        "raw_stdout_tail": raw[-2000:] if raw else "",
    }


def append_trajectory_row(row: dict, csv_path: Path = TRAJECTORY_CSV):
    """`eval/summary_trajectory.csv`（別ファイル）に 1 行追記する。`eval/summary.csv` には触れない。"""
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    file_exists = csv_path.exists()
    with csv_path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=TRAJECTORY_HEADER, lineterminator="\n")
        if not file_exists:
            writer.writeheader()
        writer.writerow({k: row.get(k, "") for k in TRAJECTORY_HEADER})


def not_run_row(date, iteration, scenario, model):
    return {
        "date": date, "iteration_id": iteration, "scenario": scenario,
        "turns": "unknown", "retries": "unknown", "tool_calls": "unknown",
        "model": model, "session_id": "unknown", "duration_ms": "unknown",
        "cost_usd": "unknown", "source": "not_run",
    }


def build_arg_parser():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenario", choices=SCENARIO_NAMES, default=None,
                     help="実行するシナリオ名。省略時は3件すべて")
    ap.add_argument("--iteration", default="dryrun", help="summary_trajectory.csv に書く iteration_id")
    ap.add_argument("--model", default="sonnet", help="claude -p に渡すモデル（例: sonnet, haiku）")
    ap.add_argument("--live", action="store_true",
                     help="実際に claude -p を呼び出す（API 呼び出しを伴う）。"
                          "指定しない場合は何も実行せず source=not_run を記録するだけ")
    ap.add_argument("--timeout", type=int, default=600, help="シナリオ実行1回あたりのタイムアウト秒")
    ap.add_argument("--judge-timeout", type=int, default=300, help="Judge 実行1回あたりのタイムアウト秒")
    ap.add_argument("--csv-path", default=None, help="summary_trajectory.csv の出力先（テスト用。既定は eval/summary_trajectory.csv）")
    return ap


def main(argv=None):
    args = build_arg_parser().parse_args(argv)
    csv_path = Path(args.csv_path) if args.csv_path else TRAJECTORY_CSV
    scenarios = [args.scenario] if args.scenario else SCENARIO_NAMES
    date = datetime.now().strftime("%Y-%m-%d")
    exit_code = 0

    for scenario in scenarios:
        if not args.live:
            append_trajectory_row(not_run_row(date, args.iteration, scenario, args.model), csv_path)
            print(f"[not_run] {scenario}: --live を指定していないため実行していません")
            continue

        try:
            run_result = run_scenario_live(scenario, args.model, args.timeout)
        except RunnerError as e:
            print(f"[error] {scenario}: シナリオ実行に失敗しました: {e}", file=sys.stderr)
            exit_code = 1
            continue

        t = run_result["trajectory"]
        row = {
            "date": date, "iteration_id": args.iteration, "scenario": scenario,
            "turns": t["turns"], "retries": t["retries"], "tool_calls": t["tool_calls"],
            "model": args.model, "session_id": t["session_id"], "duration_ms": t["duration_ms"],
            "cost_usd": t["cost_usd"],
            "source": "live" if run_result["exit_code"] == 0 else "error",
        }
        append_trajectory_row(row, csv_path)

        if run_result["exit_code"] != 0 or run_result["deliverable_text"] is None:
            print(f"[error] {scenario}: シナリオ実行が失敗、または成果物が生成されませんでした "
                  f"(exit={run_result['exit_code']})", file=sys.stderr)
            exit_code = 1
            continue

        print(f"[live] {scenario}: turns={t['turns']} retries={t['retries']} tool_calls={t['tool_calls']} "
              f"session={t['session_id']}")

        try:
            judge_result = run_judge_live(scenario, run_result["deliverable_text"], args.model, args.judge_timeout)
        except RunnerError as e:
            print(f"[error] {scenario}: Judge 実行に失敗しました: {e}", file=sys.stderr)
            exit_code = 1
            continue

        if judge_result["score"] is None:
            print(f"[error] {scenario}: Judge の応答が score.json として解釈できません", file=sys.stderr)
            exit_code = 1
            continue

        jt = judge_result["trajectory"]
        print(f"[live] {scenario}: judge session={jt['session_id']} turns={jt['turns']}")
        print(json.dumps(judge_result["score"], ensure_ascii=False, indent=2))

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
