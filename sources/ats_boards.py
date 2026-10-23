"""Public company-board adapters for Greenhouse, Lever, and Ashby."""
from __future__ import annotations

import html
from typing import Any
from urllib.parse import quote

from .base import Job, iso_date, text_matches, within_days
from .http import HttpSource, as_dict, as_list


def _board_entries(values: list[Any] | None, key: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for value in values or []:
        if isinstance(value, str) and value.strip():
            entries.append({key: value.strip()})
        elif isinstance(value, dict) and str(value.get(key) or value.get("id") or "").strip():
            entries.append({**value, key: str(value.get(key) or value.get("id")).strip()})
    return entries


class Greenhouse(HttpSource):
    name = "greenhouse"

    def __init__(self, *, boards: list[Any] | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.boards = _board_entries(boards, "token")
        self._job_boards: dict[str, str] = {}

    @staticmethod
    def parse(item: dict, board: dict) -> Job:
        url = str(item.get("absolute_url") or "")
        location = as_dict(item.get("location"))
        # Greenhouse entity-encodes editor HTML in its API response.
        description = html.unescape(str(item.get("content") or ""))
        job_id = str(item.get("id") or url)
        return Job(
            id=job_id, source="greenhouse", title=str(item.get("title") or ""),
            company=str(item.get("company_name") or board.get("company") or board.get("token") or ""),
            location=str(location.get("name") or ""), url=url, apply_url=url,
            posted_date=iso_date(item.get("first_published") or item.get("updated_at")),
            deadline=iso_date(item.get("application_deadline")), description=description,
            remote=True if "remote" in str(location.get("name") or "").casefold() else None,
        )

    def search(self, queries: list[str]) -> list[Job]:
        jobs: list[Job] = []
        for board in self.boards:
            token = quote(str(board["token"]), safe="")
            url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
            try:
                payload = as_dict(self._json("get", url, params={"content": "true"}))
            except Exception as exc:
                self._error(exc)
                continue
            for item in as_list(payload.get("jobs")):
                if not isinstance(item, dict):
                    continue
                job = self.parse(item, board)
                if text_matches(job, queries) and self.accepts(job):
                    jobs.append(job)
                    self._job_boards[job.id] = str(board["token"])
                if len(jobs) >= self.limit:
                    return jobs
        return jobs

    def detail(self, job: Job) -> Job:
        if job.description:
            return job
        board = self._job_boards.get(job.id)
        if not board:
            return job
        url = f"https://boards-api.greenhouse.io/v1/boards/{quote(board, safe='')}/jobs/{quote(job.id, safe='')}"
        try:
            return self.parse(as_dict(self._json("get", url)), {"token": board, "company": job.company})
        except Exception as exc:
            self._error(exc)
            return job


class Lever(HttpSource):
    name = "lever"

    def __init__(self, *, boards: list[Any] | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.boards = _board_entries(boards, "site")
        self._job_boards: dict[str, dict] = {}

    @staticmethod
    def _base(board: dict) -> str:
        host = "api.eu.lever.co" if str(board.get("region") or "").casefold() == "eu" else "api.lever.co"
        return f"https://{host}/v0/postings/{quote(str(board['site']), safe='')}"

    @staticmethod
    def parse(item: dict, board: dict) -> Job:
        categories = as_dict(item.get("categories"))
        url = str(item.get("hostedUrl") or item.get("applyUrl") or "")
        pieces = [str(item.get("description") or item.get("descriptionPlain") or "")]
        for section in as_list(item.get("lists")):
            if isinstance(section, dict):
                pieces.append(f"<h3>{section.get('text') or ''}</h3>{section.get('content') or ''}")
        description = "\n".join(part for part in pieces if part)
        workplace = str(item.get("workplaceType") or "").casefold()
        return Job(
            id=str(item.get("id") or url), source="lever", title=str(item.get("text") or ""),
            company=str(board.get("company") or board.get("site") or ""),
            location=str(categories.get("location") or ""), url=url,
            apply_url=str(item.get("applyUrl") or url),
            posted_date=iso_date(item.get("createdAt")), description=description,
            remote=True if workplace == "remote" else (False if workplace in {"onsite", "on-site"} else None),
        )

    def search(self, queries: list[str]) -> list[Job]:
        jobs: list[Job] = []
        seen: set[str] = set()
        for board in self.boards:
            page_size = 100
            for page in range(self.max_pages):
                try:
                    payload = as_list(self._json("get", self._base(board), params={
                        "mode": "json", "limit": page_size, "skip": page * page_size}))
                except Exception as exc:
                    self._error(exc)
                    break
                for item in payload:
                    if not isinstance(item, dict):
                        continue
                    job = self.parse(item, board)
                    if job.id not in seen and text_matches(job, queries) and self.accepts(job):
                        jobs.append(job)
                        seen.add(job.id)
                        self._job_boards[job.id] = board
                    if len(jobs) >= self.limit:
                        return jobs
                if len(payload) < page_size:
                    break
        return jobs

    def detail(self, job: Job) -> Job:
        if job.description:
            return job
        board = self._job_boards.get(job.id)
        if not board:
            return job
        try:
            payload = as_dict(self._json("get", f"{self._base(board)}/{quote(job.id, safe='')}"))
            return self.parse(payload, board)
        except Exception as exc:
            self._error(exc)
            return job


class Ashby(HttpSource):
    name = "ashby"

    def __init__(self, *, boards: list[Any] | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.boards = _board_entries(boards, "name")

    @staticmethod
    def parse(item: dict, board: dict) -> Job:
        url = str(item.get("jobUrl") or "")
        compensation = as_dict(item.get("compensation"))
        return Job(
            id=url or str(item.get("id") or ""), source="ashby",
            title=str(item.get("title") or ""),
            company=str(board.get("company") or board.get("name") or ""),
            location=str(item.get("location") or ""), url=url,
            apply_url=str(item.get("applyUrl") or url),
            posted_date=iso_date(item.get("publishedAt")),
            description=str(item.get("descriptionHtml") or item.get("descriptionPlain") or ""),
            remote=item.get("isRemote") if isinstance(item.get("isRemote"), bool) else None,
            salary=str(compensation.get("compensationTierSummary") or compensation.get("scrapeableCompensationSalarySummary") or ""),
        )

    def search(self, queries: list[str]) -> list[Job]:
        jobs: list[Job] = []
        for board in self.boards:
            name = quote(str(board["name"]), safe="")
            url = f"https://api.ashbyhq.com/posting-api/job-board/{name}"
            try:
                payload = as_dict(self._json("get", url, params={"includeCompensation": "true"}))
            except Exception as exc:
                self._error(exc)
                continue
            for item in as_list(payload.get("jobs")):
                if not isinstance(item, dict) or item.get("isListed") is False:
                    continue
                job = self.parse(item, board)
                if text_matches(job, queries) and self.accepts(job):
                    jobs.append(job)
                if len(jobs) >= self.limit:
                    return jobs
        return jobs

    def detail(self, job: Job) -> Job:
        return job


ATS_SOURCES = {"greenhouse": Greenhouse, "lever": Lever, "ashby": Ashby}
GreenhouseSource = Greenhouse
LeverSource = Lever
AshbySource = Ashby


if __name__ == '__main__':
    import argparse
    from dataclasses import asdict
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('provider', choices=sorted(ATS_SOURCES))
    parser.add_argument('query', nargs='?', default='python developer')
    parser.add_argument('--board', action='append', required=True)
    parser.add_argument('--limit', type=int, default=3)
    args = parser.parse_args()
    source = ATS_SOURCES[args.provider](boards=args.board, limit=args.limit)
    jobs = source.search([args.query])
    print(json.dumps([asdict(job) for job in jobs], ensure_ascii=False, indent=2))
    raise SystemExit(0 if jobs or not source.errors else 1)
