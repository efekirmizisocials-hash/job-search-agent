"""Himalayas' public Remote Jobs API adapter."""
from __future__ import annotations

import os

from .base import Job, iso_date, within_days
from .http import HttpSource, as_dict, as_list


class Himalayas(HttpSource):
    name = "himalayas"
    endpoint = "https://himalayas.app/jobs/api/search"

    def __init__(self, *, api_key: str = "", **kwargs) -> None:
        super().__init__(**kwargs)
        self.api_key = api_key or os.getenv("HIMALAYAS_API_KEY", "")

    @staticmethod
    def parse(item: dict) -> Job:
        url = str(item.get("guid") or item.get("applicationLink") or "")
        locations = item.get("locationRestrictions")
        if isinstance(locations, list):
            location = ", ".join(
                str(entry.get("name") or entry.get("alpha2") or "") if isinstance(entry, dict) else str(entry)
                for entry in locations
            ).strip(", ") or "Worldwide"
        else:
            location = "Worldwide"
        minimum, maximum = item.get("minSalary"), item.get("maxSalary")
        salary = ""
        if minimum is not None or maximum is not None:
            values = "–".join(str(value) for value in (minimum, maximum) if value is not None)
            salary = f"{item.get('currency') or ''} {values}/{item.get('salaryPeriod') or 'annual'}".strip()
        return Job(
            id=url, source="himalayas", title=str(item.get("title") or ""),
            company=str(item.get("companyName") or ""), location=location,
            url=url, apply_url=str(item.get("applicationLink") or url),
            posted_date=iso_date(item.get("pubDate")), deadline=iso_date(item.get("expiryDate")),
            description=str(item.get("description") or item.get("excerpt") or ""),
            remote=True, salary=salary,
        )

    def search(self, queries: list[str]) -> list[Job]:
        jobs: list[Job] = []
        seen: set[str] = set()
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        for query in queries or [""]:
            for page in range(1, self.max_pages + 1):
                try:
                    payload = as_dict(self._json("get", self.endpoint, params={"q": query, "sort": "recent", "page": page}, headers=headers))
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


HimalayasSource = Himalayas


if __name__ == "__main__":
    from ._cli import run
    raise SystemExit(run(Himalayas))
