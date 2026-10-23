# Job Search Agent

This project finds jobs from several public sources, evaluates them against a
candidate profile, creates tailored application documents, and helps complete
applications. It can fill supported public ATS forms, but every automated
submission waits for explicit approval in Telegram. Jobs on unsupported or
blocked systems receive a manual application package.

The repository contains an example profile only. It does not include a usable
live candidate profile, so complete `profile.md` before running discovery or
document generation.

## How it works

1. Load search terms, locations, limits, sources, and company boards from
   `search.yaml`.
2. Collect and normalize postings, then deduplicate them across sources.
3. Reject suspicious posting content before sending it to an LLM.
4. Apply work-authorization, language, and location gates, then score technical
   fit, relevant experience, behavioral evidence, and career alignment.
5. Build an ATS-readable CV, cover letter, answers file, and saved posting from
   facts in `profile.md`. Evidence quotes, dates, numbers, and contact details
   are checked; review rewritten claims for accuracy before approving.
6. Route supported public ATS forms through supervised filling. All other jobs
   are stored as `ready_manual` with their documents and application link.
7. Record durable states in SQLite before and after submission. An uncertain
   submission is never retried automatically.

Supported public sources include Remotive, Arbeitnow, RemoteOK, and Himalayas.
Adzuna and Jooble need API keys. Greenhouse, Lever, and Ashby company boards
need identifiers in `search.yaml`. Optional vendored Bun adapters cover
LinkedIn public listings, FreeHire, Jobnet, Jobindex, Jobbank, and JobDanmark.
The legacy SALTO training source remains available as an explicit source.

Public forms on Greenhouse, Lever, Ashby, Teamtailor, Recruitee, and
SmartRecruiters may be filled automatically. Workday, LinkedIn, Taleo,
SuccessFactors, unknown systems, account walls, and CAPTCHAs are manual routes.

## Requirements

- Python 3.10 or newer
- Chromium installed through Playwright
- One supported LLM API key: Anthropic, OpenAI, or Google Gemini
- A Telegram bot and chat ID for approvals and questions
- Bun only if you enable one of the vendored portal CLI sources
- SALTO credentials only if you explicitly enable the `salto` source

Install the Python environment:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

On Windows, activate with `.venv\Scripts\activate`.

## Configure the agent

Copy the examples:

```bash
cp .env.example .env
cp profile.md.example profile.md
cp search.yaml.example search.yaml
```

Choose one provider and add only its key to `.env`:

```dotenv
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=your-key

NOTIFY_METHOD=telegram
TELEGRAM_BOT_TOKEN=your-bot-token
TELEGRAM_CHAT_ID=your-chat-id
```

Provider SDKs are imported only when selected. The defaults use active stable
text-and-vision models, and `MATCH_MODEL` or `VISION_MODEL` can override them.
Never commit `.env`, `profile.md`, `learned_answers.md`, the SQLite database,
application packages, or browser session files.

Fill every relevant section of `profile.md`, especially name, email, phone,
work authorization, visa needs, languages, dated experience, education,
target roles and locations, salary constraints, and deal-breakers. Generated
documents use this file as evidence. Citation checks cannot prove that every
paraphrase is faithful, so review the documents before approving. See
`APPLICATION_RULES.md.example` for the fixed safety and submission policy.

Edit `search.yaml` to set queries and enable sources. A missing file falls back
to the four keyless public sources with a conservative default query. Keep API
keys in `.env`, not YAML.

For a Greenhouse board, for example:

```yaml
queries: [backend engineer, platform engineer]
locations: [Remote, Istanbul]
enabled_sources: [remotive, arbeitnow, greenhouse]
ats:
  greenhouse:
    - token: example-company
      company: Example Company
```

## Telegram setup

1. Message `@BotFather`, run `/newbot`, and save the bot token.
2. Send one message to the new bot.
3. Open `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy the chat ID.
4. Put both values in `.env` and set `NOTIFY_METHOD=telegram`.

Only the configured chat ID is accepted. Every supported ATS submission sends
the job, screenshot, and documents for approval. A timeout, rejection, or
missing Telegram configuration cannot approve a job.

## Run

Start with a dry run using an explicit search configuration:

```bash
python main.py --dry-run --config search.yaml
```

Run the configured workflow:

```bash
python main.py --config search.yaml
```

Override configured sources for one run, including the legacy SALTO source:

```bash
python main.py --dry-run --config search.yaml --sources salto
```

Use low limits and inspect the dry-run output before the first supervised run.
Do not use a real candidate profile or employer form in automated tests.

## Telegram commands

Run `python listener.py` as a long-lived process if you want phone control.
It starts runs with the same Python interpreter and writes logs under `logs/`.

- `apply` or `run`: start a job-search run.
- `status`: show queued and completed states, including review or uncertain submissions.
- `pending`: list jobs waiting for a missing answer.
- `answer <text>` or `answer 2 <text>`: save an answer and resume that pending job.
- `manual`: list manual application packages and assign session-stable numbers.
- `applied <number>`: mark an item from the latest `manual` list as submitted.
- `applied id <stable-id>`: mark a manual item by durable ID after a listener restart.

Numbered manual selections are valid only after `manual` in the current listener
session. Before changing an uncertain submission, verify it directly with the
employer; `submitting` and `submission_unknown` jobs are deliberately excluded
from manual completion and requeue commands.

## Application states

| State | Meaning |
| --- | --- |
| `suitable` | Matched and waiting for preparation or supervised application |
| `pending` | A required candidate answer is missing |
| `ready_manual` | Documents and link are ready for the applicant |
| `needs_review` | Posting, model output, or package needs human inspection |
| `submitting` | Submission intent was recorded before the final click |
| `submission_unknown` | The click outcome is uncertain; never auto-retry |
| `applied` | Submission was confirmed or the user confirmed manual completion |
| `skipped` | The user declined the application |
| `failed` | Preparation or filling failed without an uncertain submission |
| `not_suitable` | The job failed a gate or minimum score |

The SQLite file is configurable with `DB_PATH`; generated packages go under
`APPLICATIONS_DIR`. Relative paths in `.env` resolve from the repository root,
so scheduled runs behave consistently regardless of their working directory.

## Tests

Install development dependencies and run the offline suite:

```bash
pip install -r requirements-dev.txt
pytest -q
```

Tests use mocked provider SDKs, saved source fixtures, synthetic profiles, and
local forms. They do not call LLM APIs, message Telegram, or submit applications.

To include local browser form tests, after installing Chromium:

```bash
RUN_BROWSER_TESTS=1 python -m pytest tests -q
```

Dry runs still query enabled public sources and the selected LLM, so they can
incur provider usage. They use a temporary database snapshot and do not change
your real queue, generate documents, fill forms, or send Telegram messages.

The process holds `run.lock` while running. After a crash, verify that the old
process has stopped before removing that file. `submitting` and
`submission_unknown` rows stay excluded from automatic retries.

Source fixtures and browser tests cover offline behavior; individual hosted
boards may change or block access. Unsupported custom ATS domains and forms
whose navigation needs blocked pre-approval requests fall back to manual
packages. Indeed, Kariyer.net, and login-only Workday discovery are future
adapters. Bun sources are optional and require `bun` on PATH.

## Attribution

Source adapters and safety utilities derived from `ai-job-search` are included
under its MIT license. See `THIRD_PARTY.md` for the pinned revision and notices.
