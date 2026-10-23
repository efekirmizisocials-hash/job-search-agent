"""
Sends a desktop, email, or Telegram notification depending on config. Used
both for "here's what I applied to" summaries and for manual-review alerts.
The interactive approval flow lives in approval.py.
"""
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import requests

from config import (
    NOTIFY_METHOD, NOTIFY_EMAIL, SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD,
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
)


def notify(subject: str, body: str, image_path: str | None = None):
    if NOTIFY_METHOD == "desktop":
        _notify_desktop(subject, body)
    elif NOTIFY_METHOD == "email":
        _notify_email(subject, body, image_path)
    elif NOTIFY_METHOD == "telegram":
        _notify_telegram(subject, body, image_path)
    else:
        print(f"[NOTIFY] {subject}\n{body}")


def _notify_desktop(subject: str, body: str):
    try:
        from plyer import notification
        notification.notify(title=subject, message=body[:250], timeout=15)
    except Exception as e:
        print(f"Desktop notification failed ({e}), falling back to console:")
        print(f"[NOTIFY] {subject}\n{body}")


def _notify_telegram(subject: str, body: str, image_path: str | None = None):
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        print("Telegram not configured, falling back to console:")
        print(f"[NOTIFY] {subject}\n{body}")
        return
    try:
        send_telegram_message(f"*{subject}*\n{body}", image_path=image_path)
    except Exception as e:
        print(f"Telegram notification failed ({e}), falling back to console:")
        print(f"[NOTIFY] {subject}\n{body}")


def send_telegram_message(text: str, image_path: str | None = None,
                          reply_markup: dict | None = None) -> dict:
    """Low-level Bot API call, shared with approval.py. Returns the sent
    message object from Telegram. Field labels/questions are arbitrary text
    that can break Markdown parsing (Telegram answers 400) — on that error
    the message is retried once as plain text."""
    base = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "parse_mode": "Markdown"}
    if reply_markup:
        import json
        payload["reply_markup"] = json.dumps(reply_markup)

    if image_path:
        endpoint = "sendPhoto"
        payload["caption"] = text[:1024]  # Telegram caps photo captions
    else:
        endpoint = "sendMessage"
        payload["text"] = text[:4096]

    for attempt in (1, 2):
        if image_path:
            with open(image_path, "rb") as f:
                resp = requests.post(f"{base}/{endpoint}", data=payload,
                                     files={"photo": f}, timeout=30)
        else:
            resp = requests.post(f"{base}/{endpoint}", data=payload, timeout=30)

        if resp.status_code == 400 and attempt == 1 and "parse_mode" in payload:
            del payload["parse_mode"]  # formatting broke parsing — plain text
            continue
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram API error: {data}")
        return data["result"]


def send_telegram_document(file_path: str, caption: str = "") -> dict | None:
    """Sends a file (e.g. the prepared answers .txt) to the Telegram chat.
    Returns None silently when Telegram isn't configured."""
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        print(f"Telegram not configured; document not sent: {file_path}")
        return None
    base = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
    with open(file_path, "rb") as f:
        resp = requests.post(f"{base}/sendDocument",
                             data={"chat_id": TELEGRAM_CHAT_ID,
                                   "caption": caption[:1024]},
                             files={"document": f}, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram API error: {data}")
    return data["result"]


def _notify_email(subject: str, body: str, image_path: str | None = None):
    if not (SMTP_HOST and SMTP_USER and SMTP_PASSWORD and NOTIFY_EMAIL):
        print("Email not fully configured, falling back to console:")
        print(f"[NOTIFY] {subject}\n{body}")
        return

    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = NOTIFY_EMAIL
    msg.attach(MIMEText(body, "plain"))

    if image_path:
        with open(image_path, "rb") as f:
            from email.mime.image import MIMEImage
            img = MIMEImage(f.read())
            msg.attach(img)

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.send_message(msg)
