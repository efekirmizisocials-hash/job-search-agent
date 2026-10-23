"""Generic adapter for the vendored Bun portal CLIs.

The CLIs share a JSON contract but intentionally use portal-appropriate flag
names.  This adapter contains that small flag matrix and normalizes both the
common search result shape and each detail variant into :class:`Job`.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any

from .base import ErrorReportingSource, Job, iso_date, within_days, location_matches


PORTAL_FLAGS = {
    "linkedin": {"query": "--query", "location": "--location", "page": "--page"},
    "freehire": {"query": "--query", "location": "--city", "page": "--page"},
    "jobnet": {"query": "--search-string", "page": "--page"},
    "jobindex": {"query": "--query", "page": "--page"},
    "jobbank": {"query": "--key"},
    "jobdanmark": {"query": "--text", "page": "--page"},
}
VENDOR_ROOT = Path(__file__).resolve().parent.parent / "vendor" / "portal_clis"


class BunCLI(ErrorReportingSource):
    def __init__(
        self,
        portal: str,
        *,
        locations: list[str] | None = None,
        limit: int = 25,
        max_pages: int = 2,
        max_age_days: int | None = 30,
        timeout: float = 45.0,
        extra_args: list[str] | None = None,
        cli_root: Path | None = None,
    ) -> None:
        super().__init__()
        if portal not in PORTAL_FLAGS:
            raise ValueError(f"unsupported Bun portal: {portal}")
        self.portal = portal
        self.name = portal
        self.locations = [str(item) for item in (locations or []) if str(item).strip()]
        self.limit = max(1, min(int(limit), 250))
        self.max_pages = max(1, min(int(max_pages), 20))
        self.max_age_days = max_age_days
        self.timeout = min(max(float(timeout), 1.0), 120.0)
        self.extra_args = [str(item) for item in (extra_args or [])]
        self.cli_root = cli_root or VENDOR_ROOT / portal
        self._detailed_ids: set[str] = set()

    @property
    def available(self) -> bool:
        return shutil.which("bun") is not None and (self.cli_root / "src" / "cli.ts").is_file()

    def _run(self, args: list[str]) -> Any:
        if not self.available:
            raise RuntimeError("Bun or vendored CLI missing; source skipped")
        command = ["bun", "run", "src/cli.ts", *args, "--format", "json"]
        env = os.environ.copy()
        env.setdefault("NO_COLOR", "1")
        try:
            completed = subprocess.run(
                command, cwd=self.cli_root, env=env, text=True,
                capture_output=True, timeout=self.timeout, check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError(f"CLI failed: {exc}") from exc
        if completed.returncode:
            error = completed.stderr.strip() or completed.stdout.strip() or f"exit {completed.returncode}"
            raise RuntimeError(error[:500])
        try:
            return json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"CLI returned invalid JSON: {exc}") from exc

    def _search_args(self, query: str, location: str, page: int) -> list[str]:
        flags = PORTAL_FLAGS[self.portal]
        args = ["search"]
        if query:
            args.extend([flags["query"], query])
        if flags.get("location") and location:
            args.extend([flags["location"], location])
        if flags.get("page"):
            args.extend([flags["page"], str(page)])
        args.extend(["--limit", str(self.limit)])
        if self.portal == "freehire":
            args.extend(["--description-format", "html"])
        args.extend(self.extra_args)
        return args

    @staticmethod
    def parse(item: dict[str, Any], portal: str) -> Job:
        company_value = item.get("company") or item.get("companyName") or item.get("hiringOrgName")
        if isinstance(company_value, dict):
            company = str(company_value.get("name") or "")
        else:
            company = str(company_value or "")
        location_value = item.get("location")
        if isinstance(location_value, dict):
            location = ", ".join(
                str(location_value.get(key) or "")
                for key in ("city", "addressLocality", "addressRegion", "country", "addressCountry")
                if location_value.get(key)
            )
        else:
            location = str(location_value or item.get("postalDistrictName") or item.get("municipality") or "")
        hiring = item.get("hiringOrganization")
        if isinstance(hiring, dict) and not company:
            company = str(hiring.get("name") or "")
        job_location = item.get("jobLocation")
        if isinstance(job_location, dict) and not location:
            location = ", ".join(
                str(job_location.get(key))
                for key in ("addressLocality", "addressRegion", "addressCountry")
                if job_location.get(key)
            )
        url = str(item.get("url") or item.get("jobUrl") or "")
        apply_url = str(item.get("applyUrl") or item.get("apply_url") or item.get("jobAdUrl") or url)
        identifier = str(item.get("id") or item.get("slug") or item.get("jobAdId") or url)
        mode = str(item.get("work_mode") or item.get("workplaceType") or "").casefold()
        remote = True if mode == "remote" or "remote" in location.casefold() else (False if mode in {"onsite", "on-site"} else None)
        return Job(
            id=identifier, source=portal, title=str(item.get("title") or item.get("text") or ""),
            company=company, location=location, url=url, apply_url=apply_url,
            posted_date=iso_date(item.get("date") or item.get("posted") or item.get("datePosted") or item.get("publicationDate")),
            deadline=iso_date(item.get("deadline") or item.get("validThrough") or item.get("applicationDeadline") or item.get("deadlineDate")),
            description=str(item.get("descriptionHtml") or item.get("description") or item.get("body") or ""),
            remote=remote, salary=str(item.get("salary") or ""),
        )

    def search(self, queries: list[str]) -> list[Job]:
        if not self.available:
            self._error("Bun or vendored CLI missing; source skipped")
            return []
        jobs: list[Job] = []
        seen: set[str] = set()
        locations = self.locations or (["Remote"] if self.portal == "linkedin" else [""])
        stop = False
        for query in queries or [""]:
            for location in locations:
                for page in range(1, self.max_pages + 1):
                    try:
                        payload = self._run(self._search_args(query, location, page))
                    except Exception as exc:
                        self._error(exc)
                        break
                    items = payload.get("results", []) if isinstance(payload, dict) else payload
                    if not isinstance(items, list) or not items:
                        break
                    for raw in items:
                        if not isinstance(raw, dict):
                            continue
                        job = self.parse(raw, self.portal)
                        if not job.id or job.id in seen or not within_days(job.posted_date, self.max_age_days):
                            continue
                        # Freehire's agent search endpoint uniquely returns a
                        # full description (requested as HTML). Other portals
                        # need detail even when an RSS summary happens to sit
                        # in their search-result ``description`` field.
                        if self.portal != "freehire" or not job.description:
                            job = self.detail(job)
                        if not job.title.strip() or not job.url or not location_matches(job, self.locations):
                            continue
                        seen.add(job.id)
                        jobs.append(job)
                        if len(jobs) >= self.limit:
                            stop = True
                            break
                    if stop or "page" not in PORTAL_FLAGS[self.portal]:
                        break
                if stop:
                    break
            if stop:
                break
        return jobs

    def detail(self, job: Job) -> Job:
        if not job.id:
            return job
        if job.id in self._detailed_ids:
            return job
        if self.portal == "freehire" and job.description:
            self._detailed_ids.add(job.id)
            return job
        try:
            payload = self._run(["detail", job.id])
        except Exception as exc:
            self._error(exc)
            return job
        if not isinstance(payload, dict):
            return job
        detailed = self.parse(payload, self.portal)
        # Detail pages occasionally omit card-only data; retain useful fields.
        for field in ("title", "company", "location", "url", "apply_url", "posted_date", "deadline", "description", "salary"):
            if not getattr(detailed, field):
                setattr(detailed, field, getattr(job, field))
        if detailed.remote is None:
            detailed.remote = job.remote
        detailed.id = job.id
        self._detailed_ids.add(job.id)
        return detailed


BunCLISource = BunCLI


if __name__ == "__main__":
    import argparse
    from dataclasses import asdict

    parser = argparse.ArgumentParser()
    parser.add_argument("portal", choices=sorted(PORTAL_FLAGS))
    parser.add_argument("query", nargs="?", default="python developer")
    parser.add_argument("--location", action="append", default=[])
    parser.add_argument("--limit", type=int, default=3)
    args = parser.parse_args()
    source = BunCLI(args.portal, locations=args.location, limit=args.limit)
    print(json.dumps([asdict(job) for job in source.search([args.query])], ensure_ascii=False, indent=2))
