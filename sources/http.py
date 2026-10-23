"""Bounded HTTP helpers shared by native source adapters."""
from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

import requests

from .base import ErrorReportingSource, SourceError, location_matches, within_days


DEFAULT_TIMEOUT = 20.0
USER_AGENT = "salto-job-search/1.0 (+personal job search)"


class HttpSource(ErrorReportingSource):
    def __init__(
        self,
        *,
        limit: int = 25,
        max_pages: int = 2,
        max_age_days: int | None = 30,
        locations: list[str] | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        session: Any | None = None,
    ) -> None:
        super().__init__()
        self.limit = max(1, min(int(limit), 250))
        self.max_pages = max(1, min(int(max_pages), 20))
        self.max_age_days = max_age_days
        self.locations = [str(item) for item in (locations or []) if str(item).strip()]
        self.timeout = min(max(float(timeout), 1.0), 60.0)
        self.session = session or requests.Session()

    def accepts(self, job):
        return bool(job.id and job.title.strip() and job.url.startswith(('https://', 'http://'))
                    and location_matches(job, self.locations)
                    and within_days(job.posted_date, self.max_age_days))

    def _json(self, method: str, url: str, **kwargs: Any) -> Any:
        headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
        headers.update(kwargs.pop("headers", {}) or {})
        try:
            response = self.session.request(
                method,
                url,
                headers=headers,
                timeout=self.timeout,
                **kwargs,
            )
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            # Some providers put credentials in the URL path or query.  Never
            # copy the request URL or exception text into logs.
            status = getattr(getattr(exc, "response", None), "status_code", None)
            reason = f"HTTP {status}" if status is not None else type(exc).__name__
            host = urlsplit(url).netloc or "remote API"
            raise SourceError(f"{method.upper()} {host}: {reason}") from exc


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
