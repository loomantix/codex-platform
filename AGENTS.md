# codex-platform — Agent Guide

## OpenAI documentation (Codex and Agy)

When a task needs facts about OpenAI products or APIs, including Codex
configuration, use current official OpenAI documentation. This applies to
both Codex and Agy (Antigravity/Gemini).

- If `openai-docs` is available in the current client, use it and follow its
  source routing. Do not assume another client's skills or global config apply.
- Otherwise, use the OpenAI documentation MCP tools when available: search for
  the topic, then fetch the relevant page. If unavailable or unhelpful, search
  and open official pages on `developers.openai.com`, `platform.openai.com`,
  or `learn.chatgpt.com`.
- Cite supporting pages; state uncertainty when the sources do not establish
  the answer. Preserve explicitly requested model targets and existing
  provider choices unless the task authorizes a change.
- Keep documentation queries generic; never send secrets, personal data, or
  private repository content to documentation tools or web search.

Upstream source of truth for Loomantix Codex skills, reusable agent workflows, and repo-sync automation. Apache 2.0 + DCO.

## Repository Policy

This repo is public-facing. Keep all issues, PRs, comments, and docs suitable for public readers:

- Do not reference private consumer repositories by name.
- Do not document private fleet topology, internal escalation paths, or deployment-specific secret names.
- Keep compliance rationale generic; do not describe private audit findings or control mappings.
- Put consumer-specific details in the consumer repo, not here.

## Working Rules

- At the start of work in this repo, verify local skill bootstrap with `./scripts/install-skills.sh --dry-run`. If it reports missing skills, run `./scripts/install-skills.sh` before relying on commands such as `deepcritique`, `reviewit`, or `agent-loop`.
- If a documented skill command is not found, rerun the bootstrap check. Use `./scripts/install-skills.sh --force` only to repair stale or conflicting local entries after confirming replacement is intended.
- Preserve the agent-agnostic sync engine unless a Codex feature genuinely requires a schema change.
- Do not do implementation work directly on `main`; create a topic branch and PR back to `main`.
- Put Codex-discoverable workflows under `.codex/skills/<name>/SKILL.md`.
- Keep large or optional role prompts under `.codex/references/` and have skills load them only when needed.
- Consumer-editable files should use `create_if_missing: true` in `scripts/sync-targets.yml`.
- Files listed in `scripts/sync-targets.yml` are upstream-owned; consumer edits will be overwritten unless the target is skipped.

## Review Workflow

See [`.codex/REVIEW_WORKFLOW.md`](.codex/REVIEW_WORKFLOW.md) for the selectable
local-convergence and hosted-fallback review paths.

## Cross-References

- [README.md](README.md) — install and consumer wiring.
- [docs/sync.md](docs/sync.md) — sync contract and tag gating.
- [scripts/sync-targets.yml](scripts/sync-targets.yml) — canonical sync surface.
- [CONTRIBUTING.md](CONTRIBUTING.md) — contribution workflow.
