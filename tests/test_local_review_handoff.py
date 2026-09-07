"""Regression tests for deterministic cross-engine review handoffs."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, cast

import pytest


HEAD = "a" * 40
BASE = "b" * 40
OTHER_HEAD = "d" * 40
REPO = "example/repository"


def _row(comment_id: int, body: str, *, login: str = "reviewer") -> dict[str, Any]:
    return {"id": comment_id, "body": body, "user": {"login": login}}


@pytest.fixture(scope="session")
def handoff() -> ModuleType:
    path = (
        Path(__file__).resolve().parent.parent
        / ".codex/skills/critique/scripts/local-review-handoff.py"
    )
    spec = importlib.util.spec_from_file_location("local_review_handoff", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path}")
    module = ModuleType("local_review_handoff")
    sys.modules["local_review_handoff"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def authenticated_actor(handoff: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(handoff, "_current_actor", lambda: "reviewer")


def _body(handoff: ModuleType, from_engine: str, to_engine: str) -> str:
    args = SimpleNamespace(
        base=BASE,
        from_engine=from_engine,
        head=HEAD,
        outcome="clean",
        pr=7,
        repo=REPO,
        round=1,
        to_engine=to_engine,
    )
    content = handoff._handoff_content(args, "")
    digest = handoff._handoff_digest(
        from_engine=from_engine,
        to_engine=to_engine,
        round_number=1,
        base=BASE,
        head=HEAD,
        outcome="clean",
        content=content,
    )
    marker = (
        f"<!-- local-review-handoff:v1 from={from_engine} to={to_engine} "
        f"round=1 base={BASE} head={HEAD} outcome=clean content-sha256={digest} -->"
    )
    return f"{marker}\n{content}"


def _run_body(
    handoff: ModuleType,
    *,
    tier: str = "deep",
    supersedes: int | None = None,
    content: str = "Review explicitly authorized.",
) -> str:
    max_rounds = handoff.TIER_CAPS[tier]
    digest = handoff._run_digest(
        tier=tier,
        max_rounds=max_rounds,
        base=BASE,
        start_head=HEAD,
        supersedes=supersedes,
        content=content,
    )
    marker = (
        f"<!-- local-review-run:v1 id={digest} tier={tier} "
        f"max-rounds={max_rounds} base={BASE} start-head={HEAD} "
        f"supersedes={supersedes if supersedes is not None else 'none'} "
        f"content-sha256={digest} -->"
    )
    return f"{marker}\n{content}"


def test_post_handoff_builds_prompt_and_replays(
    handoff: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    posted: list[dict[str, Any]] = []
    stored: list[dict[str, Any]] = []

    def fake_gh(args: list[str], payload: dict[str, Any] | None = None) -> str:
        if args[:2] == ["pr", "view"]:
            return HEAD + "\n"
        if args[-1] == f"repos/{REPO}/issues/7/comments?per_page=100":
            return json.dumps([stored])
        if args[-1] == f"repos/{REPO}/issues/7/comments":
            assert payload is not None
            posted.append(payload)
            stored.append(_row(77, cast(str, payload["body"])))
            return json.dumps({"id": 77})
        if args[-1] == f"repos/{REPO}/issues/comments/77":
            return json.dumps(stored[0])
        raise AssertionError(args)

    monkeypatch.setattr(handoff, "_run_gh", fake_gh)
    command = [
        "post-handoff",
        "--repo",
        REPO,
        "--pr",
        "7",
        "--head",
        HEAD,
        "--base",
        BASE,
        "--from-engine",
        "codex",
        "--to-engine",
        "claude",
        "--round",
        "2",
        "--outcome",
        "material",
    ]
    assert handoff.main(command) == 0
    assert json.loads(capsys.readouterr().out)["replayed"] is False
    body = cast(str, posted[0]["body"])
    assert "Continue review on PR #7." in body
    assert "Do not invoke the other review" in body
    assert "If they satisfy the repository's convergence" in body
    assert f"base={BASE} head={HEAD}" in body

    assert handoff.main(command) == 0
    assert json.loads(capsys.readouterr().out)["replayed"] is True
    assert len(posted) == 1


def test_authorize_pass_enforces_run_cap_and_duplicate_passes(
    handoff: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rows = [
        _row(20, _run_body(handoff)),
        _row(
            21,
            f"<!-- local-review-pass:v3 engine=codex round=1 base={BASE} "
            f"head={HEAD} result-sha256={'c' * 64} -->\nVerified pass.",
        ),
    ]
    monkeypatch.setattr(handoff, "_issue_comments", lambda repo, pr: rows)
    monkeypatch.setattr(handoff, "_verify_head", lambda repo, pr, head: None)

    assert (
        handoff.main(
            [
                "authorize-pass",
                "--repo",
                REPO,
                "--pr",
                "7",
                "--base",
                BASE,
                "--head",
                HEAD,
                "--engine",
                "claude",
                "--round",
                "1",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["max_rounds"] == 4

    with pytest.raises(handoff.HandoffError, match="already completed"):
        handoff.main(
            [
                "authorize-pass",
                "--repo",
                REPO,
                "--pr",
                "7",
                "--base",
                BASE,
                "--head",
                HEAD,
                "--engine",
                "codex",
                "--round",
                "1",
            ]
        )
    with pytest.raises(handoff.HandoffError, match="exceeds the deep cap"):
        handoff.main(
            [
                "authorize-pass",
                "--repo",
                REPO,
                "--pr",
                "7",
                "--base",
                BASE,
                "--head",
                HEAD,
                "--engine",
                "codex",
                "--round",
                "5",
            ]
        )


def test_restart_requires_terminal_prior_run(
    handoff: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    authorization = tmp_path / "authorization.txt"
    authorization.write_text("Explicit restart authorization.\n", encoding="utf-8")
    rows = [_row(20, _run_body(handoff))]
    monkeypatch.setattr(handoff, "_issue_comments", lambda repo, pr: rows)
    monkeypatch.setattr(handoff, "_verify_head", lambda repo, pr, head: None)

    with pytest.raises(handoff.HandoffError, match="must be ended"):
        handoff.main(
            [
                "start-run",
                "--repo",
                REPO,
                "--pr",
                "7",
                "--base",
                BASE,
                "--head",
                HEAD,
                "--tier",
                "deep",
                "--authorization-file",
                str(authorization),
                "--restart",
            ]
        )


def test_restart_supersedes_an_ended_same_head_run(
    handoff: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    authorization = tmp_path / "authorization.txt"
    authorization.write_text("Explicit restart authorization.\n", encoding="utf-8")
    prior_body = _run_body(handoff)
    prior_id = handoff.RUN_V1_RE.search(prior_body).group("run_id")
    rows = [
        _row(20, prior_body),
        _row(
            21,
            f"<!-- local-review-run-end:v1 id={prior_id} outcome=converged "
            f"head={HEAD} -->",
        ),
    ]
    posted: list[str] = []
    monkeypatch.setattr(handoff, "_issue_comments", lambda repo, pr: rows)
    monkeypatch.setattr(handoff, "_verify_head", lambda repo, pr, head: None)

    def fake_post(repo: str, pr: int, marker: str, body: str) -> tuple[int, bool]:
        posted.append(body)
        return 30, False

    monkeypatch.setattr(handoff, "_post_issue_comment", fake_post)

    assert (
        handoff.main(
            [
                "start-run",
                "--repo",
                REPO,
                "--pr",
                "7",
                "--base",
                BASE,
                "--head",
                HEAD,
                "--tier",
                "deep",
                "--authorization-file",
                str(authorization),
                "--restart",
            ]
        )
        == 0
    )
    assert "supersedes=20" in posted[0]
    assert json.loads(capsys.readouterr().out)["replayed"] is False


def test_identical_concurrent_run_markers_are_canonicalized(
    handoff: ModuleType,
) -> None:
    first = _run_body(handoff)
    second = _run_body(handoff, supersedes=21, content="Restart authorized.")

    records = handoff._run_records([_row(20, first), _row(21, first), _row(30, second)])

    assert [record["comment_id"] for record in records] == [20, 30]
    assert records[1]["supersedes"] == 20


def test_concurrent_run_fork_is_rejected(handoff: ModuleType) -> None:
    rows = [
        _row(20, _run_body(handoff)),
        _row(30, _run_body(handoff, supersedes=20, content="Restart A.")),
        _row(31, _run_body(handoff, supersedes=20, content="Restart B.")),
    ]

    with pytest.raises(handoff.HandoffError, match="incomplete or forked"):
        handoff._run_records(rows)


def test_ended_run_rejects_another_pass(
    handoff: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_body = _run_body(handoff, tier="lean")
    run_id = handoff.RUN_V1_RE.search(run_body).group("run_id")
    rows = [
        _row(20, run_body),
        _row(
            21,
            f"<!-- local-review-run-end:v1 id={run_id} outcome=exhausted "
            f"head={HEAD} -->",
        ),
    ]
    monkeypatch.setattr(handoff, "_issue_comments", lambda repo, pr: rows)
    with pytest.raises(handoff.HandoffError, match="has ended"):
        handoff.main(
            [
                "authorize-pass",
                "--repo",
                REPO,
                "--pr",
                "7",
                "--base",
                BASE,
                "--head",
                HEAD,
                "--engine",
                "codex",
                "--round",
                "1",
            ]
        )


def test_finish_run_replay_reverifies_the_current_head(
    handoff: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run_body = _run_body(handoff)
    run_id = handoff.RUN_V1_RE.search(run_body).group("run_id")
    rows = [
        _row(20, run_body),
        _row(
            21,
            f"<!-- local-review-run-end:v1 id={run_id} outcome=converged "
            f"head={HEAD} -->",
        ),
    ]
    verified: list[str] = []
    monkeypatch.setattr(handoff, "_issue_comments", lambda repo, pr: rows)
    monkeypatch.setattr(
        handoff,
        "_verify_head",
        lambda repo, pr, head: verified.append(head),
    )

    assert (
        handoff.main(
            [
                "finish-run",
                "--repo",
                REPO,
                "--pr",
                "7",
                "--head",
                HEAD,
                "--outcome",
                "converged",
            ]
        )
        == 0
    )
    assert verified == [HEAD]
    assert json.loads(capsys.readouterr().out)["replayed"] is True


def test_resume_preserves_round_budget_and_supports_repeated_recovery(
    handoff: ModuleType, monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_body = _run_body(handoff)
    run_id = handoff.RUN_V1_RE.search(run_body).group("run_id")
    rows = [
        _row(20, run_body),
        _row(21, f"<!-- local-review-pass:v3 engine=claude round=4 base={BASE} head={HEAD} result-sha256={'c' * 64} -->\nVerified pass."),
        _row(22, f"<!-- local-review-run-end:v1 id={run_id} outcome=aborted head={HEAD} -->"),
    ]
    monkeypatch.setattr(handoff, "_issue_comments", lambda repo, pr: rows)
    monkeypatch.setattr(handoff, "_verify_head", lambda repo, pr, head: None)

    def post(repo: str, pr: int, marker: str, body: str) -> tuple[int, bool]:
        for row in rows:
            if row["body"] == body:
                return row["id"], True
        comment_id = max(row["id"] for row in rows) + 1
        rows.append(_row(comment_id, body))
        return comment_id, False

    monkeypatch.setattr(handoff, "_post_issue_comment", post)
    common = ["--repo", REPO, "--pr", "7", "--head", HEAD]
    resume = ["resume-run", *common, "--base", BASE]
    for _ in range(2):
        assert handoff.main(resume) == 0
        count = len(rows)
        assert handoff.main(resume) == 0
        assert len(rows) == count
        # A lost response may have left an identical delivery duplicate. It
        # must not move the canonical recovery boundary or break finalization.
        rows.append(_row(max(row["id"] for row in rows) + 1, rows[-1]["body"]))
        with pytest.raises(handoff.HandoffError, match="exceeds the deep cap"):
            handoff.main(["authorize-pass", *common, "--base", BASE, "--engine", "codex", "--round", "5"])
        with pytest.raises(handoff.HandoffError, match="already completed"):
            handoff.main(["authorize-pass", *common, "--base", BASE, "--engine", "claude", "--round", "4"])
        assert handoff.main(["finish-run", *common, "--outcome", "aborted"]) == 0
        assert handoff._run_end(rows, run_id)["outcome"] == "aborted"
    assert len(handoff._run_records(rows)) == 1


@pytest.mark.parametrize("outcome", ["converged", "exhausted"])
def test_resume_cannot_reopen_a_completed_or_exhausted_run(
    handoff: ModuleType, monkeypatch: pytest.MonkeyPatch, outcome: str,
) -> None:
    body = _run_body(handoff)
    run_id = handoff.RUN_V1_RE.search(body).group("run_id")
    rows = [_row(20, body), _row(21, f"<!-- local-review-run-end:v1 id={run_id} outcome={outcome} head={HEAD} -->")]
    monkeypatch.setattr(handoff, "_issue_comments", lambda repo, pr: rows)
    monkeypatch.setattr(handoff, "_verify_head", lambda repo, pr, head: None)
    with pytest.raises(handoff.HandoffError, match="cannot be resumed"):
        handoff.main(["resume-run", "--repo", REPO, "--pr", "7", "--base", BASE, "--head", HEAD])


def test_resume_rejects_a_fabricated_recovery_parent(handoff: ModuleType) -> None:
    body = _run_body(handoff)
    run_id = handoff.RUN_V1_RE.search(body).group("run_id")
    rows = [_row(20, body), _row(21, f"<!-- local-review-run-resume:v1 id={run_id} after=19 head={HEAD} -->")]
    with pytest.raises(handoff.HandoffError, match="most recent aborted"):
        handoff._run_end(rows, run_id)


@pytest.mark.parametrize("outcome", ["converged", "exhausted"])
def test_run_state_rejects_recovery_after_a_sealed_terminal(handoff: ModuleType, outcome: str) -> None:
    body = _run_body(handoff)
    run_id = handoff.RUN_V1_RE.search(body).group("run_id")
    rows = [
        _row(20, body),
        _row(21, f"<!-- local-review-run-end:v1 id={run_id} outcome={outcome} head={HEAD} -->"),
        _row(22, f"<!-- local-review-run-resume:v1 id={run_id} after=21 head={HEAD} -->"),
    ]
    # A recovery whose parent is a converged or exhausted terminal must not
    # reopen the run, even though the parent id is the latest terminal.
    with pytest.raises(handoff.HandoffError, match="most recent aborted"):
        handoff._run_state(rows, run_id)


@pytest.mark.parametrize("listing", ["visible", "lost", "re-aborted"])
def test_resume_verifies_the_posted_recovery_by_reading_back(
    handoff: ModuleType, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str], listing: str,
) -> None:
    run_body = _run_body(handoff)
    run_id = handoff.RUN_V1_RE.search(run_body).group("run_id")
    rows = [_row(20, run_body), _row(21, f"<!-- local-review-run-end:v1 id={run_id} outcome=aborted head={HEAD} -->")]
    posted: list[dict[str, Any]] = []

    def fake_gh(args: list[str], payload: dict[str, Any] | None = None) -> str:
        if args[:2] == ["pr", "view"]:
            return HEAD + "\n"
        if args[-1] == f"repos/{REPO}/issues/7/comments?per_page=100":
            # A listing that never shows the recovery models a lost write; one
            # that shows a newer aborted terminal models a concurrent finish.
            visible = list(rows) if listing == "lost" else rows + posted
            if posted and listing == "re-aborted":
                visible = visible + [_row(31, f"<!-- local-review-run-end:v1 id={run_id} outcome=aborted head={HEAD} after=30 -->")]
            return json.dumps([visible])
        if args[-1] == f"repos/{REPO}/issues/7/comments":
            assert payload is not None
            posted.append(_row(30, cast(str, payload["body"])))
            return json.dumps({"id": 30})
        if args[-1] == f"repos/{REPO}/issues/comments/30":
            return json.dumps(posted[0])
        raise AssertionError(args)

    monkeypatch.setattr(handoff, "_run_gh", fake_gh)
    command = ["resume-run", "--repo", REPO, "--pr", "7", "--base", BASE, "--head", HEAD]
    if listing == "lost":
        with pytest.raises(handoff.HandoffError, match="idempotency key did not resolve"):
            handoff.main(command)
        return
    if listing == "re-aborted":
        with pytest.raises(handoff.HandoffError, match="did not resume"):
            handoff.main(command)
        return
    assert handoff.main(command) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["comment_id"] == 30
    assert result["replayed"] is False
    assert posted[0]["body"] == f"<!-- local-review-run-resume:v1 id={run_id} after=21 head={HEAD} -->"


def test_matching_body_recovers_identical_deliveries_and_ignores_quotes(handoff: ModuleType) -> None:
    marker = "<!-- local-review-example:v1 -->"
    body = marker + "\nVerified context."
    rows = [_row(3, "Quoted:\n" + body), _row(5, body), _row(4, body)]
    assert handoff._matching_body(rows, marker, body) == 4
    with pytest.raises(handoff.HandoffError, match="conflicting content"):
        handoff._matching_body(rows + [_row(6, marker + "\nChanged.")], marker, body)


@pytest.mark.parametrize("state,action,next_round", [
    ("empty", "start-run", None), ("active", "review", 1), ("quoted", "review", 1),
    ("covered", "covered", 2), ("aborted", "resume-run", 1),
    ("cap", "finish-exhausted", 5), ("marker-only", "review", 1),
    ("empty-content", "review", 1),
])
def test_status_reports_recovery_without_manual_round_arithmetic(
    handoff: ModuleType, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str], state: str, action: str, next_round: int | None,
) -> None:
    body = _run_body(handoff)
    run_id = handoff.RUN_V1_RE.search(body).group("run_id")
    rows = [] if state == "empty" else [_row(20, body)]
    if state in {"covered", "cap", "marker-only", "empty-content"}:
        round_number = 1 if state == "covered" else 4
        reviewed_head = HEAD if state == "covered" else OTHER_HEAD
        content = "" if state == "marker-only" else "\n  " if state == "empty-content" else "\nVerified pass."
        rows.append(_row(21, f"<!-- local-review-pass:v3 engine=codex round={round_number} base={BASE} head={reviewed_head} result-sha256={'c' * 64} -->" + content))
    if state == "aborted":
        rows.append(_row(22, f"<!-- local-review-run-end:v1 id={run_id} outcome=aborted head={HEAD} -->"))
    if state == "quoted":
        rows.append(_row(22, f"Example only:\n<!-- local-review-pass:v3 engine=codex round=4 base={BASE} head={HEAD} result-sha256={'c' * 64} -->"))
    monkeypatch.setattr(handoff, "_issue_comments", lambda repo, pr: rows)
    monkeypatch.setattr(handoff, "_verify_head", lambda repo, pr, head: None)
    assert handoff.main(["status", "--repo", REPO, "--pr", "7", "--head", HEAD, "--engine", "codex"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["next_action"] == action
    assert result.get("next_round") == next_round
    if state in {"quoted", "marker-only", "empty-content"}:
        assert handoff.main(["authorize-pass", "--repo", REPO, "--pr", "7", "--head", HEAD, "--base", BASE, "--engine", "codex", "--round", "1"]) == 0


def _pass_row(comment_id: int, engine: str, round_number: int, *, head: str = HEAD, base: str = BASE) -> dict[str, Any]:
    return _row(comment_id, f"<!-- local-review-pass:v3 engine={engine} round={round_number} base={base} head={head} result-sha256={'c' * 64} -->\nVerified pass.")


def _status(handoff: ModuleType, capsys: pytest.CaptureFixture[str], engine: str = "codex") -> dict[str, Any]:
    assert handoff.main(["status", "--repo", REPO, "--pr", "7", "--head", HEAD, "--engine", engine]) == 0
    return cast(dict[str, Any], json.loads(capsys.readouterr().out))


@pytest.mark.parametrize("engine,next_round", [("codex", 2), ("claude", 3), ("gemini", 2)])
def test_status_next_round_follows_the_run_not_this_engine_alone(
    handoff: ModuleType, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str], engine: str, next_round: int,
) -> None:
    rows = [_row(20, _run_body(handoff)), _pass_row(21, "codex", 1, head=OTHER_HEAD), _pass_row(22, "claude", 2, head=OTHER_HEAD)]
    monkeypatch.setattr(handoff, "_issue_comments", lambda repo, pr: rows)
    monkeypatch.setattr(handoff, "_verify_head", lambda repo, pr, head: None)
    result = _status(handoff, capsys, engine)
    assert result["next_action"] == "review"
    assert result["next_round"] == next_round
    assert handoff.main(["authorize-pass", "--repo", REPO, "--pr", "7", "--head", HEAD, "--base", BASE, "--engine", engine, "--round", str(next_round)]) == 0


def test_status_next_round_is_the_run_highest_when_another_engine_leads(
    handoff: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    rows = [
        _row(20, _run_body(handoff)),
        _pass_row(21, "codex", 1, head=OTHER_HEAD),
        _pass_row(22, "claude", 2, head=OTHER_HEAD),
        _pass_row(23, "claude", 3, head=OTHER_HEAD),
    ]
    monkeypatch.setattr(handoff, "_issue_comments", lambda repo, pr: rows)
    monkeypatch.setattr(handoff, "_verify_head", lambda repo, pr, head: None)
    # Codex owes the run's current round 3, not its own next round 2.
    assert _status(handoff, capsys, "codex")["next_round"] == 3
    with pytest.raises(handoff.HandoffError, match="already completed"):
        handoff.main(["authorize-pass", "--repo", REPO, "--pr", "7", "--head", HEAD, "--base", BASE, "--engine", "claude", "--round", "3"])


def test_pass_records_are_scoped_to_the_current_run(
    handoff: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    prior_body = _run_body(handoff)
    prior_id = handoff.RUN_V1_RE.search(prior_body).group("run_id")
    rows = [
        _row(20, prior_body),
        _pass_row(21, "codex", 1),
        _row(22, f"<!-- local-review-run-end:v1 id={prior_id} outcome=aborted head={HEAD} -->"),
        _row(23, _run_body(handoff, supersedes=20, content="Explicit restart authorization.")),
    ]
    monkeypatch.setattr(handoff, "_issue_comments", lambda repo, pr: rows)
    monkeypatch.setattr(handoff, "_verify_head", lambda repo, pr, head: None)
    result = _status(handoff, capsys)
    assert result["next_action"] == "review"
    assert result["next_round"] == 1
    assert result["passes"] == []
    assert handoff.main(["authorize-pass", "--repo", REPO, "--pr", "7", "--head", HEAD, "--base", BASE, "--engine", "codex", "--round", "1"]) == 0


def test_pass_records_reject_an_attestation_against_another_base(
    handoff: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    rows = [_row(20, _run_body(handoff)), _pass_row(21, "codex", 1, base="e" * 40)]
    monkeypatch.setattr(handoff, "_issue_comments", lambda repo, pr: rows)
    monkeypatch.setattr(handoff, "_verify_head", lambda repo, pr, head: None)
    with pytest.raises(handoff.HandoffError, match="pinned base"):
        _status(handoff, capsys)


@pytest.mark.parametrize("outcome", ["converged", "exhausted"])
def test_status_does_not_report_a_stale_terminal_as_finished(
    handoff: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], outcome: str,
) -> None:
    body = _run_body(handoff)
    run_id = handoff.RUN_V1_RE.search(body).group("run_id")
    end = f"<!-- local-review-run-end:v1 id={run_id} outcome={outcome} head={OTHER_HEAD} -->"
    rows = [_row(20, body), _row(21, end)]
    monkeypatch.setattr(handoff, "_issue_comments", lambda repo, pr: rows)
    monkeypatch.setattr(handoff, "_verify_head", lambda repo, pr, head: None)
    result = _status(handoff, capsys)
    assert result["next_action"] == "start-run"
    assert result["reason"] == "terminal_head_stale"
    rows[1] = _row(21, end.replace(OTHER_HEAD, HEAD))
    result = _status(handoff, capsys)
    assert result["next_action"] == "finished"
    assert result["reason"] is None


@pytest.mark.parametrize("body_suffix,match", [
    (" extra prose", "terminal marker is malformed"),
    ("\n<!-- local-review-run-end:v1 malformed -->", "terminal marker is malformed"),
])
def test_run_state_fails_closed_on_a_malformed_terminal_marker(handoff: ModuleType, body_suffix: str, match: str) -> None:
    body = _run_body(handoff)
    run_id = handoff.RUN_V1_RE.search(body).group("run_id")
    rows = [_row(20, body), _row(21, f"<!-- local-review-run-end:v1 id={run_id} outcome=converged head={HEAD} -->" + body_suffix)]
    with pytest.raises(handoff.HandoffError, match=match):
        handoff._run_state(rows, run_id)


def test_run_state_fails_closed_on_a_malformed_recovery_marker(handoff: ModuleType) -> None:
    body = _run_body(handoff)
    run_id = handoff.RUN_V1_RE.search(body).group("run_id")
    rows = [
        _row(20, body),
        _row(21, f"<!-- local-review-run-end:v1 id={run_id} outcome=aborted head={HEAD} -->"),
        _row(22, f"<!-- local-review-run-resume:v1 id={run_id} after=0 head={HEAD} -->"),
    ]
    with pytest.raises(handoff.HandoffError, match="recovery marker is malformed"):
        handoff._run_state(rows, run_id)


@pytest.mark.parametrize("after", ["", " after=99"])
def test_run_state_requires_the_terminal_to_follow_the_latest_recovery(handoff: ModuleType, after: str) -> None:
    body = _run_body(handoff)
    run_id = handoff.RUN_V1_RE.search(body).group("run_id")
    rows = [
        _row(20, body),
        _row(21, f"<!-- local-review-run-end:v1 id={run_id} outcome=aborted head={HEAD} -->"),
        _row(22, f"<!-- local-review-run-resume:v1 id={run_id} after=21 head={HEAD} -->"),
        _row(23, f"<!-- local-review-run-end:v1 id={run_id} outcome=converged head={HEAD}{after} -->"),
    ]
    with pytest.raises(handoff.HandoffError, match="does not follow its latest recovery"):
        handoff._run_state(rows, run_id)
    rows[3] = _row(23, f"<!-- local-review-run-end:v1 id={run_id} outcome=converged head={HEAD} after=22 -->")
    assert handoff._run_state(rows, run_id) == ({"comment_id": 23, "head": HEAD, "outcome": "converged"}, 22)
    # A byte-identical redelivery of the pre-recovery terminal collapses as a
    # duplicate and does not close the resumed run.
    rows[3] = _row(23, rows[1]["body"])
    assert handoff._run_state(rows, run_id) == (None, 22)


def test_resume_on_an_open_run_reports_only_a_real_recovery(
    handoff: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    body = _run_body(handoff)
    run_id = handoff.RUN_V1_RE.search(body).group("run_id")
    rows = [_row(20, body)]
    monkeypatch.setattr(handoff, "_issue_comments", lambda repo, pr: rows)
    monkeypatch.setattr(handoff, "_verify_head", lambda repo, pr, head: None)
    monkeypatch.setattr(handoff, "_post_issue_comment", lambda *args: pytest.fail("active run must not post"))
    resume = ["resume-run", "--repo", REPO, "--pr", "7", "--base", BASE, "--head", HEAD]
    assert handoff.main(resume) == 0
    assert json.loads(capsys.readouterr().out) == {
        "run_id": run_id, "head": HEAD, "status": "already_active",
        "replayed": False, "verified": True,
    }
    assert len(rows) == 1
    rows.append(_row(21, f"<!-- local-review-run-end:v1 id={run_id} outcome=aborted head={HEAD} -->"))
    rows.append(_row(22, f"<!-- local-review-run-resume:v1 id={run_id} after=21 head={HEAD} -->"))
    assert handoff.main(resume) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["replayed"] is True
    assert result["comment_id"] == 22
    assert result["head"] == HEAD
    # A recovery recorded at another head is not a replay of this request.
    assert handoff.main(["resume-run", "--repo", REPO, "--pr", "7", "--base", BASE, "--head", OTHER_HEAD]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "run_id": run_id, "head": OTHER_HEAD, "status": "already_active",
        "replayed": False, "verified": True,
    }
    assert len(rows) == 3


@pytest.mark.parametrize("suffix", ["", " ", "\n", "\r\n\t ", "\v\f"])
def test_recovery_marker_whitespace_preserves_canonical_ids_and_replay(
    handoff: ModuleType, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str], suffix: str,
) -> None:
    run = _run_body(handoff)
    run_id = handoff.RUN_V1_RE.search(run).group("run_id")
    terminal = f"<!-- local-review-run-end:v1 id={run_id} outcome=aborted head={HEAD} -->"
    recovery = f"<!-- local-review-run-resume:v1 id={run_id} after=21 head={HEAD} -->"
    rows = [_row(20, run), _row(21, terminal + suffix), _row(22, terminal),
            _row(23, recovery + suffix), _row(24, recovery)]
    monkeypatch.setattr(handoff, "_issue_comments", lambda repo, pr: rows)
    monkeypatch.setattr(handoff, "_verify_head", lambda repo, pr, head: None)
    monkeypatch.setattr(handoff, "_post_issue_comment", lambda *args: pytest.fail("replay must not post"))
    assert handoff._run_state(rows, run_id) == (None, 23)
    assert handoff.main(["resume-run", "--repo", REPO, "--pr", "7", "--base", BASE, "--head", HEAD]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["replayed"] is True
    assert result["comment_id"] == 23
    assert result["head"] == HEAD
    rows.append(_row(25, f"<!-- local-review-run-end:v1 id={run_id} outcome=converged head={HEAD} after=23 -->" + suffix))
    assert handoff._run_state(rows, run_id) == ({"comment_id": 25, "head": HEAD, "outcome": "converged"}, 23)


@pytest.mark.parametrize("kind", ["id", "head", "parent", "conflict"])
def test_whitespace_normalization_does_not_accept_invalid_recovery_evidence(handoff: ModuleType, kind: str) -> None:
    body = _run_body(handoff)
    run_id = handoff.RUN_V1_RE.search(body).group("run_id")
    terminal = f"<!-- local-review-run-end:v1 id={run_id} outcome=aborted head={HEAD} -->"
    recovery = f"<!-- local-review-run-resume:v1 id={run_id} after=21 head={HEAD} -->"
    malformed = {
        "id": recovery.replace(run_id, "z" * 64),
        "head": recovery.replace(HEAD, "z" * 40),
        "parent": recovery.replace("after=21", "after=19"),
        "conflict": terminal.replace("aborted", "converged"),
    }[kind]
    rows = [_row(20, body), _row(21, terminal + "\n"), _row(22, malformed + "\r\n ")]
    with pytest.raises(handoff.HandoffError):
        handoff._run_state(rows, run_id)


@pytest.mark.parametrize("prefix", ["> ", " ", "Example:\n", "```\n"])
def test_whitespace_normalization_does_not_admit_quoted_markers(handoff: ModuleType, prefix: str) -> None:
    marker = f"<!-- local-review-run-end:v1 id={'c' * 64} outcome=aborted head={HEAD} -->"
    assert handoff._run_state([_row(21, prefix + marker + "\n")], "c" * 64) == (None, None)


def test_active_resume_preserves_head_and_spent_round_guards(
    handoff: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    rows = [_row(20, _run_body(handoff)), _pass_row(21, "codex", 4)]
    monkeypatch.setattr(handoff, "_issue_comments", lambda repo, pr: rows)
    monkeypatch.setattr(handoff, "_run_gh", lambda args, payload=None: HEAD)
    monkeypatch.setattr(handoff, "_post_issue_comment", lambda *args: pytest.fail("active run must not post"))
    common = ["--repo", REPO, "--pr", "7", "--base", BASE]
    assert handoff.main(["resume-run", *common, "--head", HEAD]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "already_active"
    assert len(rows) == 2
    with pytest.raises(handoff.HandoffError, match="head mismatch"):
        handoff.main(["resume-run", *common, "--head", OTHER_HEAD])
    with pytest.raises(handoff.HandoffError, match="already completed"):
        handoff.main(["authorize-pass", *common, "--head", HEAD, "--engine", "codex", "--round", "4"])
    with pytest.raises(handoff.HandoffError, match="exceeds the deep cap"):
        handoff.main(["authorize-pass", *common, "--head", HEAD, "--engine", "codex", "--round", "5"])


def test_resume_rejects_another_base(
    handoff: ModuleType, monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = _run_body(handoff)
    run_id = handoff.RUN_V1_RE.search(body).group("run_id")
    rows = [_row(20, body), _row(21, f"<!-- local-review-run-end:v1 id={run_id} outcome=aborted head={HEAD} -->")]
    monkeypatch.setattr(handoff, "_issue_comments", lambda repo, pr: rows)
    monkeypatch.setattr(handoff, "_verify_head", lambda repo, pr, head: None)
    with pytest.raises(handoff.HandoffError, match="pinned review base"):
        handoff.main(["resume-run", "--repo", REPO, "--pr", "7", "--base", "e" * 40, "--head", HEAD])


def test_run_state_orders_evidence_by_comment_id(handoff: ModuleType) -> None:
    body = _run_body(handoff)
    run_id = handoff.RUN_V1_RE.search(body).group("run_id")
    rows = [
        _row(23, f"<!-- local-review-run-end:v1 id={run_id} outcome=aborted head={HEAD} after=22 -->"),
        _row(22, f"<!-- local-review-run-resume:v1 id={run_id} after=21 head={HEAD} -->"),
        _row(21, f"<!-- local-review-run-end:v1 id={run_id} outcome=aborted head={HEAD} -->"),
        _row(20, body),
    ]
    assert handoff._run_state(rows, run_id) == ({"comment_id": 23, "head": HEAD, "outcome": "aborted"}, 22)


def test_pass_records_reject_contradictory_evidence_for_one_engine_round(
    handoff: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    rows = [_row(20, _run_body(handoff)), _pass_row(21, "codex", 1, head=OTHER_HEAD), _pass_row(22, "codex", 1, head=OTHER_HEAD)]
    monkeypatch.setattr(handoff, "_issue_comments", lambda repo, pr: rows)
    monkeypatch.setattr(handoff, "_verify_head", lambda repo, pr, head: None)
    # An identical redelivery collapses to one record.
    assert len(_status(handoff, capsys)["passes"]) == 1
    rows.append(_pass_row(23, "codex", 1, head=HEAD))
    with pytest.raises(handoff.HandoffError, match="contradictory attestations"):
        _status(handoff, capsys)
    with pytest.raises(handoff.HandoffError, match="contradictory attestations"):
        handoff.main(["authorize-pass", "--repo", REPO, "--pr", "7", "--head", HEAD, "--base", BASE, "--engine", "claude", "--round", "1"])


@pytest.mark.parametrize("field", ["digest", "before", "fingerprints"])
def test_pass_records_compare_complete_sealed_identity(
    handoff: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], field: str,
) -> None:
    marker = f"<!-- local-review-complete:v3 engine=codex round=1 base={BASE} before={OTHER_HEAD} head={HEAD} classification=material fingerprints=first result-sha256={'c' * 64} -->"
    changed = {
        "digest": marker.replace("c" * 64, "d" * 64),
        "before": marker.replace(f"before={OTHER_HEAD}", f"before={'e' * 40}"),
        "fingerprints": marker.replace("fingerprints=first", "fingerprints=second"),
    }[field]
    rows = [_row(20, _run_body(handoff)), _row(21, marker + "\nOriginal explanation."), _row(22, changed + "\nAnother explanation.")]
    monkeypatch.setattr(handoff, "_issue_comments", lambda repo, pr: rows)
    monkeypatch.setattr(handoff, "_verify_head", lambda repo, pr, head: None)
    with pytest.raises(handoff.HandoffError, match="contradictory attestations"):
        _status(handoff, capsys)
    with pytest.raises(handoff.HandoffError, match="contradictory attestations"):
        handoff.main(["authorize-pass", "--repo", REPO, "--pr", "7", "--head", HEAD, "--base", BASE, "--engine", "claude", "--round", "1"])


def test_pass_records_allow_changed_prose_and_normalized_engine_alias(
    handoff: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    first = _pass_row(21, "gemini", 1)
    second = _row(22, first["body"].replace("engine=gemini", "engine=antigravity").replace("Verified pass.", "Updated explanation."))
    rows = [_row(20, _run_body(handoff)), first, second]
    monkeypatch.setattr(handoff, "_issue_comments", lambda repo, pr: rows)
    monkeypatch.setattr(handoff, "_verify_head", lambda repo, pr, head: None)
    result = _status(handoff, capsys, "gemini")
    assert result["next_action"] == "covered"
    assert len(result["passes"]) == 1
    assert result["passes"][0]["engine"] == "gemini"


@pytest.mark.parametrize("classification", ["minor", "material"])
@pytest.mark.parametrize("round_number", [1, 4])
def test_status_covers_current_head_completions(
    handoff: ModuleType, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str], classification: str, round_number: int,
) -> None:
    rows = [_row(20, _run_body(handoff)), _row(
        21, f"<!-- local-review-complete:v3 engine=codex round={round_number} "
        f"base={BASE} before={OTHER_HEAD} head={HEAD} classification={classification} "
        f"fingerprints=status-fix result-sha256={'c' * 64} -->\nVerified fix and validation.",
    )]
    monkeypatch.setattr(handoff, "_issue_comments", lambda repo, pr: rows)
    monkeypatch.setattr(handoff, "_verify_head", lambda repo, pr, head: None)
    assert handoff.main(["status", "--repo", REPO, "--pr", "7", "--head", HEAD, "--engine", "codex"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["next_action"] == "covered"
    assert result["passes"][0]["classification"] == classification


def test_show_handoff_uses_latest_authenticated_comment(
    handoff: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rows = [
        _row(10, _body(handoff, "claude", "codex")),
        _row(11, _body(handoff, "codex", "claude")),
        _row(12, _body(handoff, "claude", "codex"), login="other"),
    ]

    def fake_gh(args: list[str], payload: dict[str, Any] | None = None) -> str:
        assert payload is None
        if args[:2] == ["pr", "view"]:
            return HEAD + "\n"
        return json.dumps([rows])

    monkeypatch.setattr(handoff, "_run_gh", fake_gh)
    command = ["show-handoff", "--repo", REPO, "--pr", "7", "--engine", "claude"]
    assert handoff.main(command) == 0
    assert json.loads(capsys.readouterr().out)["comment_id"] == 11
    with pytest.raises(handoff.HandoffError, match="targets claude, not codex"):
        handoff.main(["show-handoff", "--repo", REPO, "--pr", "7", "--engine", "codex"])


def test_show_handoff_rejects_stale_head(
    handoff: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = _row(11, _body(handoff, "codex", "claude"))

    def fake_gh(args: list[str], payload: dict[str, Any] | None = None) -> str:
        assert payload is None
        if args[:2] == ["pr", "view"]:
            return OTHER_HEAD + "\n"
        return json.dumps([[row]])

    monkeypatch.setattr(handoff, "_run_gh", fake_gh)
    with pytest.raises(handoff.HandoffError, match="PR head mismatch"):
        handoff.main(
            ["show-handoff", "--repo", REPO, "--pr", "7", "--engine", "claude"]
        )


def test_show_handoff_rejects_tampered_marker_metadata(
    handoff: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    tampered = _body(handoff, "codex", "claude").replace(
        f"head={HEAD}", f"head={OTHER_HEAD}", 1
    )

    def fake_gh(args: list[str], payload: dict[str, Any] | None = None) -> str:
        assert payload is None
        if args[:2] == ["pr", "view"]:
            return OTHER_HEAD + "\n"
        return json.dumps([[_row(11, tampered)]])

    monkeypatch.setattr(handoff, "_run_gh", fake_gh)
    with pytest.raises(handoff.HandoffError, match="content digest is invalid"):
        handoff.main(
            ["show-handoff", "--repo", REPO, "--pr", "7", "--engine", "claude"]
        )


def test_show_handoff_rejects_malformed_newest_marker(
    handoff: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = [
        _row(10, _body(handoff, "claude", "codex")),
        _row(11, "<!-- local-review-handoff:v1 malformed -->\nnewer"),
    ]
    monkeypatch.setattr(handoff, "_issue_comments", lambda repo, pr: rows)
    with pytest.raises(handoff.HandoffError, match="marker is malformed"):
        handoff.main(["show-handoff", "--repo", REPO, "--pr", "7", "--engine", "codex"])


@pytest.mark.parametrize("conflicting", [False, True])
def test_post_handoff_recovers_only_identical_concurrent_duplicates(
    handoff: ModuleType, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str], conflicting: bool,
) -> None:
    stored: list[dict[str, Any]] = []
    comment_lists = 0

    def fake_gh(args: list[str], payload: dict[str, Any] | None = None) -> str:
        nonlocal comment_lists
        if args[:2] == ["pr", "view"]:
            return HEAD + "\n"
        if args[-1] == f"repos/{REPO}/issues/7/comments?per_page=100":
            comment_lists += 1
            if comment_lists == 1:
                return json.dumps([[]])
            # The concurrent poster won the race, so its lower id is canonical.
            duplicate = _row(76, cast(str, stored[0]["body"]) + ("changed" if conflicting else ""))
            return json.dumps([[duplicate, stored[0]]])
        if args[-1] == f"repos/{REPO}/issues/7/comments":
            assert payload is not None
            stored.append(_row(77, cast(str, payload["body"])))
            return json.dumps({"id": 77})
        if args[-1] == f"repos/{REPO}/issues/comments/76":
            return json.dumps(_row(76, cast(str, stored[0]["body"])))
        raise AssertionError(args)

    monkeypatch.setattr(handoff, "_run_gh", fake_gh)
    command = [
                "post-handoff",
                "--repo",
                REPO,
                "--pr",
                "7",
                "--head",
                HEAD,
                "--base",
                BASE,
                "--from-engine",
                "codex",
                "--to-engine",
                "claude",
                "--round",
                "1",
                "--outcome",
                "clean",
            ]
    if conflicting:
        with pytest.raises(handoff.HandoffError, match="conflicting content"):
            handoff.main(command)
    else:
        assert handoff.main(command) == 0
        result = json.loads(capsys.readouterr().out)
        assert result["comment_id"] == 76
        assert result["replayed"] is True


def test_context_rejects_marker_injection(handoff: ModuleType, tmp_path: Path) -> None:
    context = tmp_path / "context.md"
    context.write_text("<!-- local-review-handoff:v1 injected -->", encoding="utf-8")
    with pytest.raises(handoff.HandoffError, match="must not contain"):
        handoff._read_context(str(context))
