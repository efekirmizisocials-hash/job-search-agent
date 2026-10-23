"""Compatibility adapter for the legacy SALTO Youth Playwright scraper."""
from __future__ import annotations

import re

from .base import ErrorReportingSource, Job, iso_date, text_matches


class Salto(ErrorReportingSource):
    name = "salto"

    def __init__(self, *, limit: int = 25, max_pages: int = 2, **_: object) -> None:
        super().__init__()
        self.limit = max(1, min(int(limit), 250))
        self.max_pages = max(1, min(int(max_pages), 20))

    @staticmethod
    def _deadline(text: str) -> str | None:
        match = re.search(r"(?:application\s+)?deadline\s*:?\s*(\d{4}-\d{2}-\d{2})", text, re.I)
        if match:
            return iso_date(match.group(1))
        match = re.search(r"(?:application\s+)?deadline(?:\s*\([^)]*\))?\s*:?\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", text, re.I)
        if match:
            from datetime import date
            months = 'january february march april may june july august september october november december'.split()
            try:
                day, month, year = match.groups()
                return date(int(year), months.index(month.lower())+1, int(day)).isoformat()
            except ValueError:
                return None
        return None

    def search(self, queries: list[str]) -> list[Job]:
        try:
            # Import lazily: public API sources do not require Playwright or
            # legacy SALTO configuration at import time.
            import scraper
            previous = scraper.MAX_LISTING_PAGES
            try:
                scraper.MAX_LISTING_PAGES = self.max_pages
                listings = scraper.fetch_open_listings(headless=True)
            finally:
                scraper.MAX_LISTING_PAGES = previous
        except Exception as exc:
            self._error(exc)
            return []
        jobs: list[Job] = []
        for listing in listings:
            job = Job(
                id=str(listing.id), source="salto", title=str(listing.title),
                company="SALTO Youth", url=str(listing.url), apply_url=str(listing.url),
                deadline=self._deadline(str(listing.summary)),
                description=str(listing.summary), remote=None,
            )
            # Preserve the original flow: profile eligibility screens training
            # opportunities; employment search keywords should not hide them.
            jobs.append(job)
            if len(jobs) >= self.limit:
                break
        return jobs

    def detail(self, job: Job) -> Job:
        handles = None
        try:
            import scraper
            handles = scraper.open_listing(job.url, headless=True)
            _, _, page = handles
            container = page.locator(".tool-item-detail-wrapper")
            if container.count() == 0:
                container = page.locator("body")
            # Keep markup intact so posting_guard can inspect hidden content.
            job.description = container.first.inner_html()[:100_000]
            job.deadline = job.deadline or self._deadline(container.first.inner_text())
        except Exception as exc:
            self._error(exc)
        finally:
            if handles is not None:
                playwright, browser, _ = handles
                try:
                    browser.close()
                finally:
                    playwright.stop()
        return job


SaltoSource = Salto


if __name__ == '__main__':
    from ._cli import run
    raise SystemExit(run(Salto))
