"""Remote OK's public JSON feed adapter."""
from __future__ import annotations

from .base import Job, iso_date, text_matches, within_days
from .http import HttpSource, as_list


class RemoteOK(HttpSource):
    name = "remoteok"
    endpoint = "https://remoteok.com/api"

    @staticmethod
    def parse(item: dict) -> Job:
        url = str(item.get("url") or "")
        apply_url = str(item.get("apply_url") or item.get("apply_url_without_tracking") or url)
        return Job(
            id=str(item.get("id") or item.get("slug") or url), source="remoteok",
            title=str(item.get("position") or item.get("title") or ""),
            company=str(item.get("company") or ""),
            location=str(item.get("location") or "Remote"), url=url, apply_url=apply_url,
            posted_date=iso_date(item.get("date") or item.get("epoch")),
            description=str(item.get("description") or ""), remote=True,
            salary=str(item.get("salary") or ""),
        )

    def search(self, queries: list[str]) -> list[Job]:
        try:
            payload = as_list(self._json("get", self.endpoint))
        except Exception as exc:
            self._error(exc)
            return []
        jobs: list[Job] = []
        for item in payload:
            # The first feed record is API metadata, not a posting.
            if not isinstance(item, dict) or not (item.get("position") or item.get("title")):
                continue
            job = self.parse(item)
            if text_matches(job, queries) and self.accepts(job):
                jobs.append(job)
            if len(jobs) >= self.limit:
                break
        return jobs

    def detail(self, job: Job) -> Job:
        return job


RemoteOKSource = RemoteOK


if __name__ == "__main__":
    from ._cli import run
    raise SystemExit(run(RemoteOK))
