"""Adzuna multi-country job search API adapter."""
from __future__ import annotations

import os

from .base import Job, iso_date, within_days
from .http import HttpSource, as_dict, as_list


class Adzuna(HttpSource):
    name = "adzuna"
    endpoint = "https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"

    def __init__(
        self,
        *,
        app_id: str = "",
        app_key: str = "",
        countries: list[str] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.app_id = app_id or os.getenv("ADZUNA_APP_ID", "")
        self.app_key = app_key or os.getenv("ADZUNA_APP_KEY", "")
        self.countries = [str(value).lower() for value in (countries or ["gb"]) if str(value).strip()]

    @property
    def configured(self) -> bool:
        return bool(self.app_id and self.app_key)

    @staticmethod
    def parse(item: dict) -> Job:
        company = item.get("company") if isinstance(item.get("company"), dict) else {}
        location = item.get("location") if isinstance(item.get("location"), dict) else {}
        url = str(item.get("redirect_url") or "")
        minimum, maximum = item.get("salary_min"), item.get("salary_max")
        salary = ""
        if minimum is not None or maximum is not None:
            salary = "–".join(str(value) for value in (minimum, maximum) if value is not None)
        return Job(
            id=str(item.get("id") or url), source="adzuna",
            title=str(item.get("title") or ""), company=str(company.get("display_name") or ""),
            location=str(location.get("display_name") or ""), url=url, apply_url=url,
            posted_date=iso_date(item.get("created")),
            description=str(item.get("description") or ""),
            remote=None, salary=salary,
        )

    def search(self, queries: list[str]) -> list[Job]:
        if not self.configured:
            self._error("missing ADZUNA_APP_ID/ADZUNA_APP_KEY; source skipped")
            return []
        jobs: list[Job] = []
        seen: set[str] = set()
        for country in self.countries:
            for query in queries or [""]:
                for location in self.locations or [""]:
                    for page in range(1, self.max_pages + 1):
                        params = {
                            "app_id": self.app_id, "app_key": self.app_key,
                            "what": query, "results_per_page": min(self.limit, 50),
                            "max_days_old": self.max_age_days or 30,
                            "content-type": "application/json",
                        }
                        if location:
                            params["where"] = location
                        try:
                            payload = as_dict(self._json("get", self.endpoint.format(country=country, page=page), params=params))
                        except Exception as exc:
                            self._error(exc)
                            break
                        items = as_list(payload.get("results"))
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


AdzunaSource = Adzuna


if __name__ == "__main__":
    from ._cli import run
    raise SystemExit(run(Adzuna))
