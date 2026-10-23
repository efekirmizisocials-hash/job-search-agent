"""Deterministic posting checks before untrusted source text reaches a model."""
from dataclasses import replace
import re

from sources.base import Job


class UnsafePosting(ValueError):
    def __init__(self, findings: dict):
        self.findings = findings
        super().__init__("Posting contains hidden content or suspicious instructions; manual review required")


def sanitize_text(text: str) -> str:
    from vendor.posting_guard import guard

    mode = "html" if re.search(r"</?[a-zA-Z][^>]*>", text) else "text"
    clean, findings = guard(text, mode)
    if any(findings.get(k) for k in (
        "hidden_blocks", "invisible_flagged", "instruction_like", "homoglyph_runs", "hidden_urls"
    )):
        raise UnsafePosting(findings)
    return clean


def sanitize_job(job: Job) -> Job:
    fields = ("id", "source", "title", "company", "location", "description", "salary", "url", "apply_url")
    return replace(job, **{field: sanitize_text(getattr(job, field) or "") for field in fields})
