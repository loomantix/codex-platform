---
name: deepgrill
description: High-fidelity pre-push Codex review chain. Use for complex or high-risk changes such as auth, crypto, secrets, data migrations, GitHub Actions, sync tooling, .codex/skills, large refactors, or when the user asks for a deep review.
---

# Deep Grill

Run the full pre-push chain:

1. Execute the `refactorpass` workflow.
2. Execute the `grill` workflow in deep mode.
3. Stop before pushing unless the user explicitly asked you to push.

## Deep Triggers

Use this path when the change touches:

- `.codex/skills/**`, `scripts/sync*`, or `.github/workflows/**`
- authentication, authorization, crypto, secret handling, or sensitive data
- database schema, data shape, migrations, or serialization contracts
- more than roughly 20 files or 500 net lines
- an area with recurring incidents

## Handoff

When complete, tell the user:

```text
Deep pre-push review complete.
Next:
  git push
  gh pr create --title "..." --body "..."
  reviewit <pr-number> deep
```
