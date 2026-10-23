"""Arbeitnow's free European job-board API adapter."""
from __future__ import annotations

from .base import Job, iso_date, text_matches, within_days
from .http import HttpSource, as_dict, as_list


class Arbeitnow(HttpSource):
    name = "arbeitnow"
    endpoint = "https://www.arbeitnow.com/api/job-board-api"

    @staticmethod
    def parse(item: dict) -> Job:
        url = str(item.get("url") or "")
        return Job(
            id=str(item.get("slug") or item.get("id") or url), source="arbeitnow",
            title=str(item.get("title") or ""),
            company=str(item.get("company_name") or item.get("company") or ""),
            location=str(item.get("location") or ""), url=url, apply_url=url,
            posted_date=iso_date(item.get("created_at") or item.get("date")),
            description=str(item.get("description") or ""),
            remote=item.get("remote") if isinstance(item.get("remote"), bool) else None,
            salary=str(item.get("salary") or ""),
        )

    def search(self, queries: list[str]) -> list[Job]:
        jobs: list[Job] = []
        seen: set[str] = set()
        url: str | None = self.endpoint
        page = 0
        while url and page < self.max_pages and len(jobs) < self.limit:
            page += 1
            try:
                payload = as_dict(self._json("get", url, params={"page": page} if url == self.endpoint else None))
            except Exception as exc:
                self._error(exc)
                break
            for item in as_list(payload.get("data")):
                if not isinstance(item, dict):
                    continue
                job = self.parse(item)
                if job.id in seen or not self.accepts(job):
                    continue
                if not text_matches(job, queries):
                    continue
                seen.add(job.id)
                jobs.append(job)
                if len(jobs) >= self.limit:
                    break
            links = as_dict(payload.get("links"))
            next_url = links.get("next")
            url = str(next_url) if next_url else None
        return jobs

    def detail(self, job: Job) -> Job:
        return job


ArbeitnowSource = Arbeitnow


if __name__ == "__main__":
    from ._cli import run
    raise SystemExit(run(Arbeitnow))
