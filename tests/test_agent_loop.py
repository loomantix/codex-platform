"""Fail-before-claim coverage for agent-loop consumer configuration."""
from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
AGENT_LOOP = REPO_ROOT / ".codex/skills/agent-loop/scripts/agent-loop.sh"


def _consumer(tmp_path: Path, config_text: str) -> tuple[Path, Path]:
    repo = tmp_path / "consumer"
    script = repo / ".codex/skills/agent-loop/scripts/agent-loop.sh"
    ready = repo / ".codex/skills/issues/scripts/ready.py"
    config = repo / ".codex/skills/agent-loop/agent-loop.config"
    script.parent.mkdir(parents=True)
    ready.parent.mkdir(parents=True)
    shutil.copy2(AGENT_LOOP, script)
    ready.write_text("#!/bin/sh\nprintf '[]\\n'\n", encoding="utf-8")
    ready.chmod(0o755)
    (repo / "agent-loop-instructions.md").write_text("# Instructions\n", encoding="utf-8")
    config.write_text(config_text, encoding="utf-8")
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh_log = tmp_path / "gh.log"
    gh = bin_dir / "gh"
    gh.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' \"$*\" >> \"$GH_LOG\"\n"
        "if [ \"$1 $2\" = \"repo view\" ]; then printf 'example/consumer\\n'; fi\n",
        encoding="utf-8",
    )
    gh.chmod(0o755)
    # `codex` is a paid CLI absent from CI runners; these tests exit at config /
    # base-branch validation, long before `codex exec`, so a harmless stub keeps
    # the dependency preflight (gh jq xxd python3 codex) from short-circuiting
    # with "required command not found: codex" before the code under test runs.
    codex = bin_dir / "codex"
    codex.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    codex.chmod(0o755)
    return repo, gh_log


def _run(repo: Path, gh_log: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PATH"] = f"{gh_log.parent / 'bin'}:{env['PATH']}"
    env["GH_LOG"] = str(gh_log)
    env.pop("AGENT_LOOP_BASE_BRANCH", None)
    return subprocess.run(
        [str(repo / ".codex/skills/agent-loop/scripts/agent-loop.sh"), "1"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )


@pytest.mark.parametrize(
    "config_text",
    [
        "base_branch staging\n",
        "base_branch =\n",
        "base_branch = staging\nbase_branch = main\n",
        "base_branch = release candidate\n",
        "base_branch = HEAD\n",
    ],
)
def test_invalid_base_config_exits_before_queue_claim_or_worktree(
    tmp_path: Path, config_text: str
) -> None:
    repo, gh_log = _consumer(tmp_path, config_text)
    result = _run(repo, gh_log)
    assert result.returncode != 0
    assert "base_branch" in result.stdout or "base branch" in result.stdout
    assert not gh_log.exists() or "issue edit" not in gh_log.read_text(encoding="utf-8")
    match = re.search(r"^   Worktree: (.+)$", result.stdout, re.MULTILINE)
    if match:
        assert not Path(match.group(1)).exists()


def test_agent_loop_script_remains_executable() -> None:
    assert stat.S_IMODE(AGENT_LOOP.stat().st_mode) == 0o755


def test_missing_remote_base_exits_before_claim_or_worktree(tmp_path: Path) -> None:
    repo, gh_log = _consumer(tmp_path, "base_branch = integration\n")
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "add", "."], check=True, capture_output=True
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-m",
            "test fixture",
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "remote", "add", "origin", str(remote)],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "push", "origin", "main"],
        check=True,
        capture_output=True,
    )

    result = _run(repo, gh_log)
    assert result.returncode != 0
    assert "configured base branch does not exist" in result.stdout
    assert "issue edit" not in gh_log.read_text(encoding="utf-8")
    match = re.search(r"^   Worktree: (.+)$", result.stdout, re.MULTILINE)
    assert match is not None
    assert not Path(match.group(1)).exists()
