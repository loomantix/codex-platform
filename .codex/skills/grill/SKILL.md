---
name: grill
description: Pre-push adversarial code review for Codex. Use after implementation or refactorpass and before pushing a PR, especially when the user asks to grill, review hard, find bugs, or run the platform pre-push review chain. Supports lean and deep modes.
---

# Grill

Review the local diff adversarially before push. The goal is to catch bugs, missing tests, security issues, and convention violations while fixes are still local.

## Adversarial Stance

Assume there are problems to find. Treat the diff as guilty until each risk is
disproved by code, tests, or documented constraints. Actively look for the
highest-impact failure modes first: data loss, security exposure, silent
failure, broken public contracts, rollout breakage, and missing validation.
Do not soften the search into a general quality pass.

Still keep the reporting bar high: only report specific, actionable findings
with file/line evidence. If a suspected issue cannot be supported, dismiss it
privately or list it as dismissed with the evidence that disproved it.

## Fix Bias

Fix every valid finding in the current PR, including small nits and cleanup
items. Do not defer valid findings just because they are inconvenient or
"out of scope." Only dismiss invalid findings, false positives, or suggestions
that would make the code worse. Defer only when the finding is a valid but
extremely large follow-up refactor, roughly 300+ lines or a cross-cutting
rewrite; create or link a GitHub issue for every deferral.

## Mode

- **Lean**: default. Run the lean two-lane review: code reviewer plus silent failure hunter. This is still an adversarial pre-push review, not a casual skim.
- **Deep**: if the user passes `deep` or the change is high-risk. Run the full independent review matrix below. Deep mode is intentionally much heavier than lean mode; do not collapse it into one general review pass.

## Lean Review Matrix

Lean mode must cover two independent lanes:

1. **Code reviewer** — correctness bugs, regressions, edge cases, broken contracts, project conventions, and meaningful test gaps.
2. **Silent failure hunter** — swallowed errors, partial failures, async races, retries, timeouts, idempotency, and missing observability for critical paths.

Run these lanes as independently as the active runtime permits:

- If subagents/delegation are available and permitted by the active Codex instructions, spawn independent reviewers for both lanes. Tell each reviewer to inspect the diff independently, return only actionable findings with file/line evidence, and avoid relying on conclusions from the other lane.
- If subagents are unavailable or not permitted, perform two separate local passes using the lane prompts above. Do not present that as equivalent to independent subagents.
- If lean mode was requested but independent subagents could not be used, explicitly say so in the output under `review depth`.

## Deep Review Matrix

Deep mode must cover six independent lanes:

1. **Code reviewer** — correctness bugs, regressions, edge cases, and broken contracts.
2. **Silent failure hunter** — swallowed errors, partial failures, async races, retries, timeouts, idempotency, and observability gaps.
3. **Type/API design analyzer** — public API shape, type soundness, compatibility, dependency boundaries, and versioning drift.
4. **Comment/docs analyzer** — misleading comments, stale docs, migration instructions, public/private information leaks, and docs that overpromise behavior.
5. **PR test analyzer** — missing tests, weak assertions, CI gaps, fixture realism, and whether validation actually exercises the risk.
6. **Security reviewer** — auth, secrets, injection, supply-chain, workflow permissions, sensitive-data exposure, and fail-closed behavior.

Run these lanes as independently as the active runtime permits:

- If subagents/delegation are available and permitted by the active Codex instructions, spawn independent reviewers with disjoint lane prompts. Tell each reviewer to inspect the diff independently, return only actionable findings with file/line evidence, and avoid relying on conclusions from other lanes.
- If subagents are unavailable or not permitted, perform six separate local passes using the lane prompts above. Do not present that as equivalent to independent subagents.
- If deep mode was requested but independent subagents could not be used, explicitly say so in the output under `review depth`.

## Process

1. Verify there is a local diff or unpushed commits to review.
2. Skip docs/config-only changes unless the user explicitly wants review.
3. Read `AGENTS.md`, relevant path-specific instructions, and changed files.
4. In lean mode, execute every lane in the Lean Review Matrix. Load these role references for lane prompts:
   - `.codex/references/roles/code-reviewer.md`
   - `.codex/references/roles/silent-failure-hunter.md`
     Keep lane findings separated until both lanes complete, then deduplicate by root cause.
5. In deep mode, execute every lane in the Deep Review Matrix. Load these role references for lane prompts:
   - `.codex/references/roles/code-reviewer.md`
   - `.codex/references/roles/silent-failure-hunter.md`
   - `.codex/references/roles/type-design-analyzer.md`
   - `.codex/references/roles/comment-analyzer.md`
   - `.codex/references/roles/pr-test-analyzer.md`
   - `.codex/references/roles/security-reviewer.md`
     Keep lane findings separated until all lanes complete, then deduplicate by root cause.
6. Report only findings that are specific, actionable, and supported by file/line evidence.
7. For each finding, fix it unless it is invalid or a valid extremely large follow-up refactor. Dismiss invalid findings with evidence. Defer only 300+ line or cross-cutting refactors, and track each deferral in a GitHub issue.
8. Critical correctness/security findings must not be silently ignored.
9. Run targeted validation for any fixes.

## Output

End with:

- review depth: lean with independent subagents, lean local two-pass fallback, deep with independent subagents, or deep local six-pass fallback
- findings fixed
- findings deferred or dismissed
- validation run
- whether the change should use `reviewit <pr>` or `reviewit <pr> deep` after PR creation
