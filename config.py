import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent


def _project_path(env_name: str, default: str) -> str:
    """Return an absolute path, resolving relative settings from the repo root."""
    path = Path(os.getenv(env_name, default)).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return str(path)

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic").lower()
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

NOTIFY_METHOD = os.getenv("NOTIFY_METHOD", "desktop")  # "desktop" | "email" | "telegram"
NOTIFY_EMAIL = os.getenv("NOTIFY_EMAIL", "")

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")

# Telegram — used for notifications (NOTIFY_METHOD=telegram) and for the
# approval flow, which works headless under cron / Task Scheduler.
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

REQUIRE_APPROVAL = os.getenv("REQUIRE_APPROVAL", "true").lower() == "true"
APPROVAL_TIMEOUT_MINUTES = int(os.getenv("APPROVAL_TIMEOUT_MINUTES", "60"))

# When a form asks something profile.md can't answer, the agent asks the
# user on Telegram and waits this long for a reply. Answers are saved to
# LEARNED_ANSWERS_PATH and reused forever after.
FIELD_QUESTION_TIMEOUT_MINUTES = int(os.getenv("FIELD_QUESTION_TIMEOUT_MINUTES", "30"))
LEARNED_ANSWERS_PATH = _project_path("LEARNED_ANSWERS_PATH", "learned_answers.md")

# Sentinel returned by the Telegram Q&A when the user answers "later" (or
# doesn't answer): the application moves to the pending list instead of
# being submitted incomplete. Resumed via the listener's "answer" command.
DEFER_ANSWER = "__defer__"

# SALTO account — needed for login-gated listings and native SALTO
# application forms. The Playwright session is persisted to
# STORAGE_STATE_PATH so login happens rarely, not every run.
SALTO_EMAIL = os.getenv("SALTO_EMAIL", "")
SALTO_PASSWORD = os.getenv("SALTO_PASSWORD", "")
SALTO_LOGIN_URL = "https://www.salto-youth.net/mysalto/login/"
STORAGE_STATE_PATH = "salto_session.json"

# European Training Calendar — the listing surface individuals apply to
# (training courses, seminars, youth exchanges). Verified live 2026-07-11.
SALTO_LISTINGS_URL = "https://www.salto-youth.net/tools/european-training-calendar/browse/"
DB_PATH = _project_path("DB_PATH", "state.db")
PROFILE_PATH = _project_path("PROFILE_PATH", "profile.md")
SEARCH_CONFIG_PATH = _project_path("SEARCH_CONFIG_PATH", "search.yaml")
APPLICATIONS_DIR = _project_path("APPLICATIONS_DIR", "applications")

# Cap on "Next"-style pagination inside a single application form
# (Typeform / multi-page Google Forms).
MAX_FORM_PAGES = 10

# The browse listing shows 10 results per page, sorted by application
# deadline. 12 pages covers the whole calendar; already-seen listings are
# skipped via the database, so full scans stay cheap after the first run.
MAX_LISTING_PAGES = int(os.getenv("MAX_LISTING_PAGES", "12"))

# At most this many application attempts per run; unprocessed matches stay
# unrecorded and are picked up on the next scheduled run.
MAX_APPLICATIONS_PER_RUN = int(os.getenv("MAX_APPLICATIONS_PER_RUN", "3"))

# Model split: cheap/fast model for the frequent suitability check,
# stronger vision model for the rarer, higher-stakes form-filling step.
if LLM_PROVIDER == "anthropic":
    _match, _vision = "claude-haiku-5-5", "claude-sonnet-5-5"
elif LLM_PROVIDER == "openai":
    _match, _vision = "gpt-6-luna", "gpt-6.1-sol"
else:  # gemini
    _match, _vision = "gemini-3.5-flash-lite", "gemini-3.8-flash"
MATCH_MODEL = os.getenv("MATCH_MODEL") or _match
VISION_MODEL = os.getenv("VISION_MODEL") or _vision
