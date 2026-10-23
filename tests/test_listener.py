from contextlib import contextmanager
import os
from pathlib import Path
import sys
from unittest.mock import Mock

import listener


def _manual_item(listing_id, title="Engineer", status="ready_manual"):
    return {
        "id": listing_id,
        "title": title,
        "company": "Example Co",
        "deadline": "2026-12-01",
        "docs_path": f"/packages/{listing_id}",
        "apply_url": f"https://jobs.example.com/{listing_id}",
        "url": "",
        "status": status,
    }


def test_manual_list_creates_number_snapshot(monkeypatch):
    items = [_manual_item("job-b", "Backend Engineer"), _manual_item("job-a", "Analyst")]
    monkeypatch.setattr(listener, "get_manual", lambda: items)
    listener._manual_snapshot.clear()

    rendered = listener._manual_text()

    assert listener._manual_snapshot == ["job-b", "job-a"]
    assert "1. Example Co — Backend Engineer" in rendered
    assert "Package: /packages/job-b" in rendered
    assert "Apply: https://jobs.example.com/job-b" in rendered
    assert "ID: job-a" in rendered


def test_applied_number_uses_last_snapshot_and_current_manual_state(monkeypatch):
    items = [_manual_item("job-b", "Backend Engineer"), _manual_item("job-a", "Analyst")]
    replies = []
    mark = Mock()
    monkeypatch.setattr(listener, "get_manual", lambda: items)
    monkeypatch.setattr(listener, "mark_applied", mark)
    monkeypatch.setattr(listener, "_reply", replies.append)
    listener._manual_snapshot[:] = ["job-b", "job-a"]

    listener._handle_applied("applied 2")

    mark.assert_called_once_with("job-a")
    # Keep the original mapping stable until the user explicitly refreshes it.
    assert listener._manual_snapshot == ["job-b", "job-a"]
    assert "Marked as applied" in replies[-1]


def test_applied_number_requires_manual_snapshot(monkeypatch):
    replies = []
    mark = Mock()
    monkeypatch.setattr(listener, "get_manual", Mock())
    monkeypatch.setattr(listener, "mark_applied", mark)
    monkeypatch.setattr(listener, "_reply", replies.append)
    listener._manual_snapshot.clear()

    listener._handle_applied("applied 1")

    mark.assert_not_called()
    assert replies == ["Send 'manual' first so the numbered list is fixed for this listener session."]


def test_applied_stable_id_works_after_restart(monkeypatch):
    item = _manual_item("company-role-123", "Platform Engineer")
    replies = []
    mark = Mock()
    monkeypatch.setattr(listener, "get_manual", lambda: [item])
    monkeypatch.setattr(listener, "mark_applied", mark)
    monkeypatch.setattr(listener, "_reply", replies.append)
    listener._manual_snapshot.clear()

    listener._handle_applied("applied id company-role-123")

    mark.assert_called_once_with("company-role-123")
    assert "Platform Engineer" in replies[-1]


def test_applied_never_changes_uncertain_or_nonmanual_item(monkeypatch):
    replies = []
    mark = Mock()
    monkeypatch.setattr(listener, "get_manual", lambda: [_manual_item("ready")])
    monkeypatch.setattr(listener, "mark_applied", mark)
    monkeypatch.setattr(listener, "_reply", replies.append)

    listener._handle_applied("applied id submission-unknown")

    mark.assert_not_called()
    assert "not currently waiting for manual submission" in replies[-1]
    assert "never requeued" in replies[-1]


def test_pending_answer_requeues_only_returned_pending_item(monkeypatch):
    item = {
        "id": "pending-job",
        "title": "Data Engineer",
        "match_reason": "pending: Notice period || When can you start?",
    }
    saved = Mock()
    requeue = Mock()
    replies = []
    monkeypatch.setattr(listener, "get_pending", lambda: [item])
    monkeypatch.setattr(listener, "append_learned_answer", saved)
    monkeypatch.setattr(listener, "requeue", requeue)
    monkeypatch.setattr(listener, "_reply", replies.append)
    monkeypatch.setattr(listener, "_run_active", lambda: True)

    listener._handle_answer("answer 2026-11-15")

    saved.assert_called_once_with("Notice period", "When can you start?", "2026-11-15")
    requeue.assert_called_once_with("pending-job")
    assert "Saved" in replies[-1]


def test_status_includes_manual_review_and_uncertain_states(monkeypatch):
    rows = [
        {"status": "ready_manual", "deadline": None, "title": "Manual Role"},
        {"status": "needs_review", "deadline": "2026-11-02", "title": "Review Role"},
        {"status": "submitting", "deadline": None, "title": "Submitting Role"},
        {
            "status": "submission_unknown",
            "deadline": None,
            "title": "Unknown Outcome Role",
        },
    ]
    counts = [
        {"status": "ready_manual", "n": 1},
        {"status": "submission_unknown", "n": 1},
    ]

    class Result(list):
        def fetchall(self):
            return self

    class Connection:
        def execute(self, query):
            return Result(counts if "COUNT(*)" in query else rows)

    @contextmanager
    def fake_conn():
        yield Connection()

    monkeypatch.setattr(listener, "get_conn", fake_conn)

    rendered = listener._status_text()

    assert "📦 ready_manual" in rendered
    assert "🔎 needs_review" in rendered
    assert "🔒 submitting" in rendered
    assert "❓ submission_unknown" in rendered


def test_start_run_uses_current_interpreter_and_absolute_paths(monkeypatch, tmp_path):
    popen = Mock()
    monkeypatch.setattr(listener, "PROJECT_DIR", tmp_path)
    monkeypatch.setattr(listener, "LOGS_DIR", tmp_path / "logs")
    monkeypatch.setattr(listener.subprocess, "Popen", popen)

    listener._start_run()

    assert (tmp_path / "logs").is_dir()
    args, kwargs = popen.call_args
    assert args[0] == [sys.executable, str(tmp_path / "main.py")]
    assert kwargs["cwd"] == str(tmp_path)
    assert kwargs["stderr"] is listener.subprocess.STDOUT
    assert Path(kwargs["stdout"].name) == tmp_path / "logs" / "run.log"


def test_run_active_uses_absolute_lock_path(monkeypatch, tmp_path):
    lock = tmp_path / "run.lock"
    lock.write_text("123", encoding="utf-8")
    monkeypatch.setattr(listener, "LOCK_PATH", lock)
    monkeypatch.setattr(listener.time, "time", lambda: os.path.getmtime(lock) + 1)

    assert listener._run_active() is True


def test_command_dispatches_manual_without_network(monkeypatch):
    replies = []
    monkeypatch.setattr(listener, "_manual_text", lambda: "manual packages")
    monkeypatch.setattr(listener, "_reply", replies.append)

    listener._handle_command("/manual")

    assert replies == ["manual packages"]
