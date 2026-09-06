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
  (machine-checkable — see `scripts/check_fix_cycle.py` in the SDD Toolkit self-improvement project,
  and `docs/io-spec.md` §2.5.2 in projects that adopt this schema).

## Handoff Protocol
- Builder → Validator: `.metadata.json` with deliverables list, docs referenced, builder notes
- Validator → Builder: `.validation/report.md` with issue list and fix instructions
- Builder (fix) → Validator: updated `.metadata.json` with `revision_history` entry

## Prohibited Patterns
- Validator directly editing files
- Builder self-reviewing before handoff
- Builder fixing beyond flagged scope ("while I'm here..." changes)
- Validator giving vague feedback ("improve this", "not detailed enough")

## Detail Reference
Full protocol with examples, templates, and troubleshooting: `docs/rules-reference/builder-validator-detail.md`
