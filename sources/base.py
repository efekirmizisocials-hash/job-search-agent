"""Provider-independent job records and source contract.

Source adapters deliberately return ordinary :class:`Job` objects.  Network
or optional-runtime failures are recorded on the source's ``errors`` list so a
single unavailable board never stops a multi-source search.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import email.utils
import sys
from typing import Protocol


@dataclass
class Job:
    id: str = ""
    source: str = ""
    title: str = ""
    company: str = ""
    location: str = ""
    url: str = ""
    apply_url: str = ""
    posted_date: str | None = None
    deadline: str | None = None
    description: str = ""
    remote: bool | None = None
    salary: str = ""


class Source(Protocol):
    name: str

    def search(self, queries: list[str]) -> list[Job]: ...

    def detail(self, job: Job) -> Job: ...


class SourceError(RuntimeError):
    """A bounded, user-facing source failure."""


class ErrorReportingSource:
    """Small common base that keeps source failures inspectable."""

    name = "source"

    def __init__(self) -> None:
        self.errors: list[str] = []

    def _error(self, message: object) -> None:
        if len(self.errors) >= 50:
            return
        text = str(message).strip() or "unknown error"
        # Do not let an upstream response dump an unbounded HTML error page.
        text = text.replace("\r", " ").replace("\n", " ")[:500]
        rendered = f"source[{self.name}]: {text}"
        self.errors.append(rendered)
        print(rendered, file=sys.stderr)


def iso_date(value: object) -> str | None:
    """Return a valid ``YYYY-MM-DD`` date from common API date shapes."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        stamp = float(value)
        if stamp > 10_000_000_000:  # JavaScript milliseconds
            stamp /= 1000
        try:
            return datetime.fromtimestamp(stamp, timezone.utc).date().isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.date().isoformat()
    except ValueError:
        pass
    try:
        parsed = email.utils.parsedate_to_datetime(text)
        return parsed.date().isoformat()
    except (TypeError, ValueError, OverflowError):
        return None


def within_days(value: str | None, max_age_days: int | None) -> bool:
    """Whether an ISO date is recent enough; unknown dates stay eligible."""
    if not value or not max_age_days or max_age_days < 1:
        return True
    try:
        age = (datetime.now(timezone.utc).date() - date.fromisoformat(value)).days
    except ValueError:
        return True
    return age <= max_age_days


def text_matches(job: Job, queries: list[str]) -> bool:
    """Case-insensitive local fallback matching for unfiltered feeds."""
    wanted = [query.casefold().strip() for query in queries if query.strip()]
    if not wanted:
        return True
    haystack = " ".join((job.title, job.company, job.location, job.description)).casefold()
    return any(query in haystack for query in wanted)


def location_matches(job: Job, locations: list[str]) -> bool:
    """Search preference only; work authorization remains a separate matching gate."""
    if not locations or not job.location.strip():
        return True
    location = job.location.casefold()
    if job.remote and location in {'worldwide', 'anywhere', 'global'}:
        return True
    return any((wanted.casefold() == 'remote' and job.remote is True)
               or wanted.casefold() in location for wanted in locations)
