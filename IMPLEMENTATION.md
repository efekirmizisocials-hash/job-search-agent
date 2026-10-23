# Job-search implementation tracker

The coordinator owns integration. Workers share this checkout and own separate files.
No live applications, Telegram messages, or personal-data changes during development.

## Contracts

- `sources.base.Job`: dataclass with id, source, title, company, location, url,
  apply_url, posted_date, deadline, description, remote (bool or None), salary.
  String fields default to empty strings; dates default to None (ISO dates).
- `sources.load_sources(path='search.yaml') -> (list[Source], list[str])`.
  Each source has `name`, `search(queries) -> list[Job]`, and `detail(job) -> Job`.
  Configuration holds queries, locations, max_age_days, per_source_limit,
  max_pages, enabled sources and ATS company-board identifiers. Missing config
  uses safe public-source defaults. Source errors must not prevent other sources.
- `matcher.evaluate_job(job, profile_text) -> dict`: suitable, score, verdict,
  gates, reason, dimensions. Posting guard runs before this function and again
  at its boundary. Four scored dimensions: technical 30%, experience 25%,
  behavioral 15%, career 30%; eligibility/language/location are gates.
- `documents.generate_documents(job, profile_text, job_key) -> DocumentPackage`:
  Path fields `directory`, `cv`, `cover_letter`, `answers`, `posting`.
  Raises on unsafe or unvalidated output; never sends files itself.
- `fill_form(page, profile_text, ask_user=None, documents=None)` preserves the
  existing five-element return tuple. Documents mapping: cv, cover_letter paths.
- Jobs always require explicit Telegram approval, regardless of legacy env
  REQUIRE_APPROVAL. Unknown or blocked ATSs receive a manual package.
- DB keeps legacy listings and adds job metadata. Statuses: suitable, pending,
  ready_manual, needs_review, applied, skipped, failed, submitting,
  submission_unknown, not_suitable. Never retry an uncertain submission.

## Tasks

| Work | Owner | Status |
| --- | --- | --- |
| Startup fixes | Luna | Complete; reviewed |
| Provider SDK/config modernization | Sol provider worker | Complete; reviewed |
| Sources, CLI vendoring, attribution, fixtures | Sol source worker + coordinator | Complete; offline tested |
| PDF documents, templates, validation | Sol document worker + coordinator | Complete; Chromium tested |
| DB migration, guards, matching, ATS routing | Astra coordinator | Complete; tested |
| Form uploads, mandatory approval, orchestration | Astra coordinator | Complete; local forms tested |
| Listener, examples, README | Sol provider worker + coordinator | Complete; reviewed |
| Integration tests and final review | Astra coordinator | Complete offline |

Reference clone remains untouched. Real profile is empty; live validation requires
candidate input. Offline tests use synthetic profiles and local forms.

## Verification completed (2026-10-23)

- 94 tests passed, including all three provider contracts, native-source fixtures,
  portal variants, legacy DB migration, deduplication, ranking, posting guards,
  callback authorization, manual status commands, dry-run isolation, and an
  end-to-end synthetic discovery-to-manual-package run.
- Chromium rendered CVs and letters for three synthetic jobs; pypdf verified
  page limits and extractable email/phone. Rendered CV and letter visually inspected.
- Five browser form tests verified hidden file uploads, unknown required uploads,
  navigation limits, confirmation detection, and exact final-button selection.
- Application imports without provider SDKs/credentials; 37 Python files parsed;
  git diff whitespace check passes.
- Isolated verification environment: `/tmp/salto-job-tests`; browser binaries:
  `/tmp/salto-job-browsers`. Normal installation instructions are in README.md.

Final verification command (requires a browser-capable environment):

```sh
PYTHON_DOTENV_DISABLED=1 RUN_BROWSER_TESTS=1 \
PLAYWRIGHT_BROWSERS_PATH=/tmp/salto-job-browsers \
/tmp/salto-job-tests/bin/python -m pytest -q
```

## Live validation still needed

- Complete the real profile and select sources/company boards in search.yaml.
- Install/configure the chosen provider and Telegram credentials in the runtime
  environment, then run a low-limit dry run. No paid LLM calls were made here.
- Check real provider responses, optional Bun CLIs, and actual employer forms.
  They were tested with fixtures/local pages, not live accounts or submissions.
- Perform a supervised Telegram decline check on an appropriate test application.
  No Telegram messages or employer applications were sent during implementation.
- Keep the reference clone until a separate cleanup decision; it was neither
  deleted nor newly ignored.
