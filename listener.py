"""Telegram command listener for the job-search agent.

Send to the bot (only the configured TELEGRAM_CHAT_ID is obeyed):

    apply  (or /apply, run)   -> start a scan-and-apply run now
    status (or /status)       -> current application report
    pending                   -> applications parked waiting for your input
    manual                    -> document packages waiting for manual submission
    applied <n>               -> mark a listed manual package as submitted
    applied id <stable-id>    -> mark one by its durable database ID
    answer <text or link>     -> provide the missing info for the first
                                 pending application (or: answer 2 <text>
                                 for the second) and complete it

While a run is active (run.lock exists) the listener pauses polling so it
never steals the run's approval buttons or field-question replies.
"""
import os
import subprocess
import sys
import time
from pathlib import Path

import requests

from config import PROJECT_ROOT, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from db import get_conn, get_manual, get_pending, mark_applied, requeue
from matcher import append_learned_answer

PROJECT_DIR = Path(PROJECT_ROOT)
LOGS_DIR = PROJECT_DIR / "logs"

# under pythonw.exe (windowless) there is no stdout — log to a file instead
if sys.stdout is None or sys.stderr is None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    _log = (LOGS_DIR / "listener.log").open(
        "a", buffering=1, encoding="utf-8", errors="replace"
    )
    sys.stdout = sys.stderr = _log
elif sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
LOCK_PATH = PROJECT_DIR / "run.lock"
BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
_manual_snapshot: list[str] = []


def _run_active() -> bool:
    # Match the coordinator's exclusive lock; never steal approval replies from
    # a long-running process based solely on an arbitrary age threshold.
    return LOCK_PATH.exists()


def _reply(text: str):
    try:
        requests.post(f"{BASE}/sendMessage",
                      data={"chat_id": TELEGRAM_CHAT_ID, "text": text[:4096]},
                      timeout=30)
    except Exception as e:
        print(f"reply failed: {type(e).__name__}")


def _start_run():
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    with (LOGS_DIR / "run.log").open("a", encoding="utf-8") as log:
        subprocess.Popen(
            [sys.executable, str(PROJECT_DIR / "main.py")],
            cwd=str(PROJECT_DIR),
            stdout=log,
            stderr=subprocess.STDOUT,
        )


def _status_text() -> str:
    with get_conn() as conn:
        lines = ["Application status:"]
        rows = conn.execute(
            """SELECT status, deadline, title FROM listings
               WHERE status IN ('applied', 'suitable', 'pending', 'ready_manual',
                                'needs_review', 'submitting', 'submission_unknown',
                                'failed', 'skipped')
               ORDER BY CASE status
                        WHEN 'submission_unknown' THEN 0 WHEN 'submitting' THEN 1
                        WHEN 'needs_review' THEN 2 WHEN 'ready_manual' THEN 3
                        WHEN 'pending' THEN 4 WHEN 'suitable' THEN 5
                        WHEN 'applied' THEN 6 ELSE 7 END,
                        (deadline IS NULL OR deadline=''), deadline, title LIMIT 30"""
        ).fetchall()
        marks = {
            "applied": "✅", "suitable": "⏳", "pending": "⏸",
            "ready_manual": "📦", "needs_review": "🔎", "submitting": "🔒",
            "submission_unknown": "❓", "failed": "⚠️", "skipped": "⏭",
        }
        for r in rows:
            mark = marks[r["status"]]
            lines.append(f"{mark} {r['status']} | {r['deadline'] or '?'} | {r['title'][:60]}")
        counts = conn.execute(
            "SELECT status, COUNT(*) n FROM listings GROUP BY status").fetchall()
        if counts:
            lines.append("Totals: " + ", ".join(f"{r['status']}: {r['n']}" for r in counts))
        else:
            lines.append("No jobs recorded yet.")
        return "\n".join(lines)


def _pending_text() -> str:
    items = get_pending()
    if not items:
        return "No pending applications — nothing is waiting for your input."
    lines = ["Pending applications (waiting for you):"]
    for i, it in enumerate(items, 1):
        missing = (it["match_reason"] or "")
        if missing.startswith("pending: "):
            missing = missing[len("pending: "):].split(" || ")[0]
        lines.append(f"{i}. {it['title'][:60]} (deadline {it['deadline'] or '?'})\n   needs: {missing}")
    lines.append("\nProvide the info with: answer <text or link>  (or: answer 2 <text> for item 2)")
    return "\n".join(lines)


def _manual_text() -> str:
    """List manual packages and remember exactly which IDs the numbers mean."""
    items = get_manual()
    _manual_snapshot.clear()
    if not items:
        return "No manual application packages are waiting."

    # Telegram messages are capped at 4096 characters. Ten compact entries leave
    # room for durable IDs and full application links.
    shown = items[:10]
    _manual_snapshot.extend(item["id"] for item in shown)
    lines = ["Manual application packages:"]
    for number, item in enumerate(shown, 1):
        company = (item.get("company") or "Unknown company")[:50]
        title = (item.get("title") or "Untitled role")[:70]
        link = item.get("apply_url") or item.get("url") or "No application link"
        package = item.get("docs_path") or "Package path unavailable"
        lines.extend([
            f"{number}. {company} — {title}",
            f"   Deadline: {item.get('deadline') or '?'}",
            f"   Package: {package}",
            f"   Apply: {link}",
            f"   ID: {item['id']}",
        ])
    if len(items) > len(shown):
        lines.append(
            f"Showing {len(shown)} of {len(items)}. Mark completed items, then send manual again."
        )
    lines.append(
        "After submitting one yourself, send: applied <number>\n"
        "You can also use: applied id <stable-id>"
    )
    return "\n".join(lines)


def _handle_applied(raw: str):
    """Mark only a currently ready_manual item as applied."""
    tokens = raw.split(maxsplit=2)
    if len(tokens) < 2:
        _reply("Usage: applied <number> after 'manual', or applied id <stable-id>")
        return

    selection = tokens[1]
    if selection.casefold() == "id":
        if len(tokens) < 3 or not tokens[2].strip():
            _reply("Usage: applied id <stable-id>")
            return
        listing_id = tokens[2].strip()
    elif selection.isdigit():
        if not _manual_snapshot:
            _reply("Send 'manual' first so the numbered list is fixed for this listener session.")
            return
        number = int(selection)
        if not 1 <= number <= len(_manual_snapshot):
            _reply(f"Pick a number from 1 to {len(_manual_snapshot)} in the last manual list.")
            return
        listing_id = _manual_snapshot[number - 1]
    else:
        # Direct IDs remain convenient for clients that cannot preserve spaces.
        listing_id = raw.split(maxsplit=1)[1].strip()

    current = {item["id"]: item for item in get_manual()}
    item = current.get(listing_id)
    if item is None:
        _reply(
            "That ID is not currently waiting for manual submission. "
            "Send 'manual' to refresh the list; uncertain submissions are never requeued."
        )
        return

    mark_applied(listing_id)
    _reply(f"✅ Marked as applied: {(item.get('company') or '')} — {item['title'][:60]}")


def _handle_answer(raw: str):
    """'answer <text>' or 'answer <n> <text>' — store the missing info for a
    pending application, requeue it, and run to complete the submission."""
    items = get_pending()
    if not items:
        _reply("No pending applications to answer.")
        return
    tokens = raw.split(maxsplit=2)
    if len(tokens) >= 3 and tokens[1].isdigit():
        n, content = int(tokens[1]), tokens[2].strip()
    elif len(tokens) >= 2:
        n, content = 1, raw.split(maxsplit=1)[1].strip()
    else:
        _reply("Usage: answer <text or link>  (or: answer 2 <text> for the second pending item)")
        return
    if not (1 <= n <= len(items)):
        _reply(f"There are {len(items)} pending item(s) — pick a number in that range.")
        return

    item = items[n - 1]
    reason = item["match_reason"] or ""
    label, question = "", ""
    if reason.startswith("pending: "):
        parts = reason[len("pending: "):].split(" || ", 1)
        label = parts[0]
        question = parts[1] if len(parts) > 1 else ""

    append_learned_answer(label or "user-provided info", question, content)
    requeue(item["id"])
    _reply(f"✅ Saved for '{label or item['title'][:40]}'. Completing the application now — "
           f"updates will arrive here.")
    if not _run_active():
        _start_run()
        time.sleep(10)


def _handle_command(raw: str):
    text = raw.casefold()
    if text in ("apply", "/apply", "run", "/run"):
        if _run_active():
            _reply("A run is already in progress — results will arrive here.")
        else:
            _reply(
                "🚀 Run started — searching and preparing the strongest job matches. "
                "Updates will arrive here."
            )
            _start_run()
            time.sleep(10)  # give main.py time to create run.lock
    elif text in ("status", "/status"):
        _reply(_status_text())
    elif text in ("pending", "/pending"):
        _reply(_pending_text())
    elif text in ("manual", "/manual"):
        _reply(_manual_text())
    elif text.startswith(("applied ", "/applied ")) or text in ("applied", "/applied"):
        _handle_applied(raw.lstrip("/"))
    elif text.startswith(("answer ", "/answer ")) or text in ("answer", "/answer"):
        _handle_answer(raw.lstrip("/"))
    elif text.startswith("/"):
        _reply(
            "Commands: apply — run now; status — report; pending — questions; "
            "manual — manual packages; applied <number> — mark submitted; "
            "answer <text> — provide missing info."
        )


def main():
    print("Job listener started.")
    offset = None
    while True:
        if _run_active():
            time.sleep(10)
            continue
        params = {"timeout": 25, "allowed_updates": '["message"]'}
        if offset is not None:
            params["offset"] = offset
        try:
            resp = requests.get(f"{BASE}/getUpdates", params=params, timeout=35)
            updates = resp.json().get("result", [])
        except Exception as e:
            print(f"poll error: {type(e).__name__}")
            time.sleep(15)
            continue

        for update in updates:
            offset = update["update_id"] + 1
            msg = update.get("message") or {}
            if str(msg.get("chat", {}).get("id")) != str(TELEGRAM_CHAT_ID):
                continue
            raw = (msg.get("text") or "").strip()
            _handle_command(raw)


if __name__ == "__main__":
    main()
