# Quality Standards

## docs/ vs skills/ Relationship
- **docs/** = What (requirements, scope, constraints, audience, format)
- **skills/** = How (procedures, tools, quality criteria, output specs)
- docs/ is authoritative: if docs/ changes, update affected skills/
- skills/ references docs/ (never duplicates content from docs/)
- Consistency check: before run-phase, verify docs/ ↔ skills/ alignment

## Quality Gates (all phases)

### Gate 0: Basic Completeness (mandatory, never exempt)
- All SKILL.md-specified deliverables exist and are non-empty
- `.metadata.json` exists with required fields
- Markdown renders correctly

### Gate 1: docs/ Requirements (mandatory)
- All "must-have" requirements from docs/ are addressed
- Scope boundaries respected (no out-of-scope content)
- Target audience level appropriate (per docs/audience.md)

### Gate 2: SKILL.md Quality Criteria (mandatory)
- Every step in SKILL.md procedure was executed
- All Quality Criteria items checked (Met/Partial/Missing)
- Output matches specified format and structure

### Gate 3: Consistency (recommended)
- No contradictions with previous phase outputs
- Terminology consistent across deliverables
- Claims supported by evidence; tables match narrative
- **An issue whose sole basis is Gate 3 must be filed as a Suggestion, never as a Critical Issue**
  (C-50). Gate 3 is recommended/exemptable (see Exemptions below); classifying a Gate-3-only
  finding as Critical (mandatory) contradicts that exemption. Every Critical Issue must self-report
  which Gate it violates (`Gate: 0 / 1 / 2 / 3-only` — see `builder-validator.md` Validator Rule 3);
  `3-only` cannot appear on a Critical Issue
- **Form-only findings** (citation position, heading numbers, formatting, terminology, leaked internal IDs)
  are handled like Gate 3-only: Suggestions, deferred to `findings-register.md`, no fix cycle.
  **Exception**: if a shipped deliverable states something false, it is a content defect (Gate 1), fix it now

## Phase-Specific Additions
| Phase Type | Additional Checks |
|---|---|
| Research/Analysis | Data sources cited, survey targets fully covered |
| Comparison/Evaluation | Same criteria applied to all subjects, scoring justified, recommendation consistent with scores |
| Report/Document | Follows docs/format.md structure, self-contained (readable without prior phases), minimal typos |

## Exemptions
- Gate 0 + mandatory requirements: **never exempt**
- Other gates: exempt only with explicit user approval → record as `completed_with_issues`
- **Gate 3 is exempt by default** — it does not require a separate user-approval step to defer as a
  Suggestion, because it was never mandatory (C-50). Only Gate 0/1/2 findings require the
  explicit-approval exemption path above
- Time pressure: fix Critical only, defer Suggestions, note in retrospective

## Fix Cycle Stopping Rule (see `builder-validator.md` Fix Cycle Limits)
- A fix cycle may stop once Gate 0–2 and all machine-checkable requirements are green
- Outstanding Gate-3-only findings do not block stopping — record them as Suggestions and proceed
- From the 3rd cycle onward, this state (stop vs. continue) must be recorded explicitly — see
  `builder-validator.md` Fix Cycle Limits for the required `owner_decision` field

## Quality Score
- Phase Quality Score (PQS) = passed gates / total gates × 100
- Project Quality Score = average of all PQS

## Detail Reference
Full gate definitions, scoring templates, and custom gate examples: `docs/rules-reference/quality-gates-detail.md`
