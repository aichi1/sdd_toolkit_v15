# Builder / Validator Protocol

## Core Principle: Separation of Concerns
- **Builder** → generates deliverables (never self-validates)
- **Validator** → verifies against requirements (never modifies files)
- Flow: `Builder → artifact → Validator → report → Builder (fix) → Validator → ...`

## Builder Rules
1. **Follow SKILL.md exactly** — no skipped steps, no improvised additions
2. **Don't self-judge quality** — that's Validator's job. Generate and hand off immediately
3. **Ask when unclear** — never guess ambiguous requirements
4. **Minimal fixes only** — when fixing Validator issues, change ONLY the flagged locations
5. **Output**: deliverables in `outputs/phase-{N}/` + `.metadata.json` with session info and deliverables list
6. **Count before you write** — every number in a deliverable or report (test counts, commit counts, line
   counts, grep hits) comes from a command you ran first, with its output pasted into `verification.log`
7. **Re-run the detecting check before reporting a fix** — re-run the exact check that found the issue,
   recount every member of the "must-agree" set it belongs to, and report the commands + exit codes.
   Regressions caused by the previous round's fix are the main driver of extra rounds
   (details: `.claude/agents/builder.md`「修正後の再検査」)

## Validator Rules
1. **Read-only** — never modify deliverables, only write validation reports
2. **Evidence-based** — every issue must cite a specific requirement from docs/ or SKILL.md Quality Criteria
3. **Concrete issues** — each Critical Issue must include: Location, Problem, Required by, Current
   state, Expected, Fix, Priority, and **Gate** (a self-reported attribution: `0` / `1` / `2` /
   `3-only`, matching the Quality Gates in `quality-standards.md`). **Do not guess the Gate from the
   issue's wording** — it is a self-reported field, not something to infer with a heuristic
   (C-50). **An issue attributed solely to Gate 3 (consistency) must never be classified as
   Critical** — file it as a Suggestion instead, since Gate 3 is recommended/exemptable
   (see `quality-standards.md` Gate 3 and Exemptions)
4. **Judge by docs/ and SKILL.md only** — not personal preference or implicit expectations
5. **One report file per round** — write `.validation/report-round{R}.md` and the same content to
   `.validation/report.md` (latest). Never overwrite an earlier round
6. **Form-only findings are Suggestions** — citation position, heading numbers, formatting, terminology,
   leaked internal IDs: treat like Gate 3-only. Exception: a shipped deliverable that states something
   false is a content defect (Gate 1)

## Expert Reviewers (optional, `/run-phase` Step 2.5)
- Generated specialists (`.claude/agents/generated/`) are chosen per phase from `docs/team.md` and the
  phase's **actual** changes (`git status --porcelain --untracked-files=all`; `git diff --name-only`
  misses new untracked files), not by default all of them
- Launch them **in the same round as the Validator, in parallel**; decide the phase verdict only after
  the Validator and every launched expert have returned
- Each expert writes its findings **verbatim** to `.validation/expert-<agent>-round{R}.md` in the
  Critical Issue format (+ severity and reproduction steps). Never compress them into one-line summaries
- The main session reproduces every High before handing it to the Builder

## Validation Verdicts
| Verdict | Condition | Action |
|---------|-----------|--------|
| PASS | All critical requirements met | Proceed to next phase |
| NEEDS_REVISION | 1-5 critical issues, fixable | Builder fixes, then re-validate |
| FAIL | 6+ critical issues or design flaw | Escalate to user |

## Fix Cycle Limits
- Max 2 auto-fix cycles per phase
- Cycle 3 still failing → stop, report to user with root cause analysis:
  - SKILL.md instructions inadequate?
  - docs/ requirements contradictory?
  - Builder/Validator interpretation mismatch?
- **A fix cycle may stop once Gate 0–2 and all machine-checkable requirements are green.**
  Outstanding Gate-3-only findings never block stopping (C-51) — record them as Suggestions.
- **From the 3rd cycle onward, "Accept the current state and proceed" must be offered as an equal
  option every cycle** — not merely a fallback after repeated escalation (C-51). Concretely: if
  `revision_history` has reached 3 or more entries and the phase has not yet reached a final `pass`,
  the last `revision_history` entry must record a non-empty `owner_decision` explaining whether the
  cycle continues or stops and why. Leaving this field out at cycle 3+ is itself a violation
  (machine-checkable — see `scripts/check_fix_cycle.py`, and `docs/io-spec.md` §2.5.2).
- **Every `revision_history` entry records `opened_by`** — why this cycle was opened:
  `validator_critical` / `expert_defect` / `owner_decision` / `main_session`. A cycle opened while the
  Validator reported 0 Critical is legitimate (expert findings, owner decisions); the violation is a
  missing reason, not a mismatch with the Critical count
- **Small fixes may skip a review round** only when the last Validator verdict was PASS (0 Critical) and the
  items being closed are Suggestions, form-only findings, expert Medium/Low, or record corrections — never
  a Validator Critical or an expert High, and never a change to what a listed deliverable claims.
  All machine checks must be re-run green (`/run-phase` Step 3.2)

## Handoff Protocol
- Builder → Validator: `.metadata.json` with deliverables list, docs referenced, builder notes
- Validator → Builder: `.validation/report.md` with issue list and fix instructions
- Builder (fix) → Validator: updated `.metadata.json` with `revision_history` entry (`cycle`, `opened_by`,
  `changes`, `rechecked`)
- Deferred findings (Suggestions, deferred expert findings) → `findings-register.md` with an ID
  (`templates/findings-register.md`); `.phase-context.json` `pending_issues` only references IDs

## Prohibited Patterns
- Validator directly editing files
- Builder self-reviewing before handoff
- Builder fixing beyond flagged scope ("while I'm here..." changes)
- Validator giving vague feedback ("improve this", "not detailed enough")

## Detail Reference
Full protocol with examples, templates, and troubleshooting: `docs/rules-reference/builder-validator-detail.md`
