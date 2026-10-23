"""
Human-approval channel. Telegram is the primary path because it works
headless under cron / Task Scheduler; the console prompt is only a fallback
for supervised manual runs. Fails safe: no answer within the timeout means
"do not submit".
"""
import sys
import time
import uuid

import requests

from config import (
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, APPROVAL_TIMEOUT_MINUTES,
    FIELD_QUESTION_TIMEOUT_MINUTES, DEFER_ANSWER,
)
from notifier import send_telegram_message


def ask_user_field(listing_title: str, field_label: str, question: str) -> str | None:
    """A form asked something profile.md can't answer: relay the question to
    the user on Telegram and wait for a text reply. Returns the reply text,
    None for 'skip' (leave the field empty and continue), or DEFER_ANSWER
    for 'later' / timeout (park the application on the pending list)."""
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        print(f"Field question (no Telegram configured, leaving empty): {field_label}")
        return None

    sent = send_telegram_message(
        f"❓ *The application form asks something not in your profile*\n"
        f"Listing: {listing_title}\n"
        f"Field: *{field_label}*\n\n{question}\n\n"
        f"_Reply with the answer to fill in, 'skip' to leave it empty, or "
        f"'later' to park this application on the pending list (happens "
        f"automatically after {FIELD_QUESTION_TIMEOUT_MINUTES} min). Resume "
        f"any time by messaging: answer <your text or link>_"
    )
    sent_id = sent.get("message_id", 0)

    base = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
    deadline = time.time() + FIELD_QUESTION_TIMEOUT_MINUTES * 60
    offset = None
    while time.time() < deadline:
        params = {"timeout": 30, "allowed_updates": '["message"]'}
        if offset is not None:
            params["offset"] = offset
        try:
            resp = requests.get(f"{base}/getUpdates", params=params, timeout=40)
            updates = resp.json().get("result", [])
        except Exception as e:
            print(f"Telegram poll error ({type(e).__name__}), retrying...")
            time.sleep(5)
            continue

        for update in updates:
            offset = update["update_id"] + 1
            msg = update.get("message")
            if not msg or str(msg.get("chat", {}).get("id")) != str(TELEGRAM_CHAT_ID):
                continue
            if msg.get("message_id", 0) <= sent_id:
                continue  # a reply from before the question was sent
            text = (msg.get("text") or "").strip()
            if not text:
                continue
            if text.lower() == "skip":
                send_telegram_message(f"Left *{field_label}* empty.")
                return None
            if text.lower() in ("later", "pending"):
                send_telegram_message(
                    f"⏸ Parked. This application waits on the pending list — "
                    f"when ready, message: answer <your text or link>")
                return DEFER_ANSWER
            send_telegram_message(f"Got it — filling *{field_label}* and saving the answer for future forms.")
            return text

    send_telegram_message(
        f"⏰ No answer for *{field_label}* — the application moved to the "
        f"pending list. When ready, message: answer <your text or link> "
        f"(send 'pending' to see what's waiting).")
    return DEFER_ANSWER


def request_approval(title: str, listing_url: str, screenshot_path: str, *, require_telegram: bool = False) -> bool:
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        return _telegram_approval(title, listing_url, screenshot_path)
    if not require_telegram and sys.stdin.isatty():
        return _console_approval(title, screenshot_path)
    print(f"No approval channel available for '{title}' (no Telegram config, "
          "no console). Declining — configure TELEGRAM_BOT_TOKEN/CHAT_ID for "
          "scheduled runs.")
    return False


def _console_approval(title: str, screenshot_path: str) -> bool:
    print(f"\nApproval needed for: {title}")
    print(f"Screenshot saved at: {screenshot_path}")
    answer = input("Submit this application? [y/N]: ").strip().lower()
    return answer == "y"


def _telegram_approval(title: str, listing_url: str, screenshot_path: str) -> bool:
    """Sends the filled-form screenshot with Submit/Skip buttons and polls
    getUpdates for the button press until APPROVAL_TIMEOUT_MINUTES."""
    token = uuid.uuid4().hex[:12]  # ties the button press to this request
    keyboard = {"inline_keyboard": [[
        {"text": "✅ Submit", "callback_data": f"approve:{token}"},
        {"text": "❌ Skip", "callback_data": f"decline:{token}"},
    ]]}
    sent = send_telegram_message(
        f"*Approve application?*\n{title}\n{listing_url}\n"
        f"_(no answer within {APPROVAL_TIMEOUT_MINUTES} min = skip)_",
        image_path=screenshot_path,
        reply_markup=keyboard,
    )

    base = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
    deadline = time.time() + APPROVAL_TIMEOUT_MINUTES * 60
    offset = None
    while time.time() < deadline:
        params = {"timeout": 30, "allowed_updates": '["callback_query"]'}
        if offset is not None:
            params["offset"] = offset
        try:
            resp = requests.get(f"{base}/getUpdates", params=params, timeout=40)
            updates = resp.json().get("result", [])
        except Exception as e:
            print(f"Telegram poll error ({type(e).__name__}), retrying...")
            time.sleep(5)
            continue

        for update in updates:
            offset = update["update_id"] + 1
            cb = update.get("callback_query")
            if not cb or cb.get("data") not in (f"approve:{token}", f"decline:{token}"):
                continue
            message = cb.get("message") or {}
            if (str(message.get("chat", {}).get("id")) != str(TELEGRAM_CHAT_ID)
                    or message.get("message_id") != sent.get("message_id")):
                continue
            approved = cb["data"].startswith("approve:")
            # acknowledge the button press so Telegram stops the spinner
            requests.post(f"{base}/answerCallbackQuery",
                          data={"callback_query_id": cb["id"],
                                "text": "Submitting..." if approved else "Skipped."},
                          timeout=10)
            return approved

    send_telegram_message(f"⏰ Approval timed out for *{title}* — skipped (not submitted).")
    return False
