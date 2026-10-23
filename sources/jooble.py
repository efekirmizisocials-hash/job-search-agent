"""Jooble REST API adapter."""
from __future__ import annotations

import os

from .base import Job, iso_date, within_days
from .http import HttpSource, as_dict, as_list


class Jooble(HttpSource):
    name = "jooble"

    def __init__(self, *, api_key: str = "", domain: str = "jooble.org", **kwargs) -> None:
        super().__init__(**kwargs)
        self.api_key = api_key or os.getenv("JOOBLE_API_KEY", "")
        self.domain = domain.strip().removeprefix("https://").removeprefix("http://").rstrip("/") or "jooble.org"

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    @staticmethod
    def parse(item: dict) -> Job:
        url = str(item.get("link") or "")
        location = str(item.get("location") or "")
        return Job(
            id=str(item.get("id") or url), source="jooble",
            title=str(item.get("title") or ""), company=str(item.get("company") or ""),
            location=location, url=url, apply_url=url,
            posted_date=iso_date(item.get("updated")),
            description=str(item.get("snippet") or item.get("description") or ""),
            remote=True if "remote" in location.casefold() else None,
            salary=str(item.get("salary") or ""),
        )

    def search(self, queries: list[str]) -> list[Job]:
        if not self.configured:
            self._error("missing JOOBLE_API_KEY; source skipped")
            return []
        jobs: list[Job] = []
        seen: set[str] = set()
        locations = self.locations or [""]
        endpoint = f"https://{self.domain}/api/{self.api_key}"
        for query in queries or [""]:
            for location in locations:
                for page in range(1, self.max_pages + 1):
                    body = {"keywords": query, "location": location, "page": page, "ResultOnPage": min(self.limit, 50)}
                    try:
                        payload = as_dict(self._json("post", endpoint, json=body))
                    except Exception as exc:
                        self._error(exc)
                        break
                    items = as_list(payload.get("jobs"))
                    if not items:
                        break
                    for item in items:
                        if not isinstance(item, dict):
                            continue
                        job = self.parse(item)
                        if job.id in seen or not self.accepts(job):
                            continue
                        seen.add(job.id)
                        jobs.append(job)
                        if len(jobs) >= self.limit:
                            return jobs
        return jobs

    def detail(self, job: Job) -> Job:
        return job


JoobleSource = Jooble


if __name__ == "__main__":
    from ._cli import run
    raise SystemExit(run(Jooble))
