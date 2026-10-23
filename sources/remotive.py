"""Remotive's public remote-jobs API adapter."""
from __future__ import annotations

from .base import Job, iso_date, within_days
from .http import HttpSource, as_dict, as_list


class Remotive(HttpSource):
    name = "remotive"
    endpoint = "https://remotive.com/api/remote-jobs"

    @staticmethod
    def parse(item: dict) -> Job:
        url = str(item.get("url") or "")
        return Job(
            id=str(item.get("id") or url), source="remotive",
            title=str(item.get("title") or ""),
            company=str(item.get("company_name") or ""),
            location=str(item.get("candidate_required_location") or "Remote"),
            url=url, apply_url=url,
            posted_date=iso_date(item.get("publication_date")),
            description=str(item.get("description") or ""), remote=True,
            salary=str(item.get("salary") or ""),
        )

    def search(self, queries: list[str]) -> list[Job]:
        jobs: list[Job] = []
        seen: set[str] = set()
        for query in queries or [""]:
            try:
                payload = as_dict(self._json("get", self.endpoint, params={"search": query}))
                for item in as_list(payload.get("jobs")):
                    if not isinstance(item, dict):
                        continue
                    job = self.parse(item)
                    if job.id in seen or not self.accepts(job):
                        continue
                    seen.add(job.id)
                    jobs.append(job)
                    if len(jobs) >= self.limit:
                        return jobs
            except Exception as exc:
                self._error(exc)
        return jobs

    def detail(self, job: Job) -> Job:
        return job


RemotiveSource = Remotive


if __name__ == "__main__":
    from ._cli import run
    raise SystemExit(run(Remotive))
