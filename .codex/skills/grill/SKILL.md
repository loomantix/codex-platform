---
name: grill
description: Pre-push adversarial code review for Codex. Use after implementation or refactorpass and before pushing a PR, especially when the user asks to grill, review hard, find bugs, or run the platform pre-push review chain. Supports lean and deep modes.
---

# Grill

Review the local diff adversarially before push. The goal is to catch bugs, missing tests, security issues, and convention violations while fixes are still local.

## Mode

- **Lean**: default. Review correctness, tests, conventions, and likely silent failures.
- **Deep**: if the user passes `deep` or the change is high-risk. Add security, type/API design, comments/docs accuracy, and CI/test adequacy.

## Process

1. Verify there is a local diff or unpushed commits to review.
2. Skip docs/config-only changes unless the user explicitly wants review.
3. Read `AGENTS.md`, relevant path-specific instructions, and changed files.
4. For complex reviews, load role references as needed:
   - `.codex/references/roles/code-reviewer.md`
   - `.codex/references/roles/code-explorer.md`
   - `.codex/references/roles/code-architect.md`
5. Report only findings that are specific, actionable, and supported by file/line evidence.
6. For each finding, either fix it, defer it with rationale, or dismiss it with evidence.
7. Critical correctness/security findings must not be silently ignored.
8. Run targeted validation for any fixes.

## Output

End with:

- findings fixed
- findings deferred or dismissed
- validation run
- whether the change should use `reviewit <pr>` or `reviewit <pr> deep` after PR creation
