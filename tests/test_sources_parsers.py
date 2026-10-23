import json
from pathlib import Path

import pytest

from sources.adzuna import Adzuna
from sources.arbeitnow import Arbeitnow
from sources.ats_boards import Ashby, Greenhouse, Lever
from sources.base import iso_date
from sources.bun_cli import BunCLI
from sources.himalayas import Himalayas
from sources.jooble import Jooble
from sources.remoteok import RemoteOK
from sources.remotive import Remotive
from vendor.posting_guard import guard


FIXTURES = Path(__file__).parent / "fixtures" / "sources"


def fixture(name):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("name", "parser", "expected_source", "expected_date"),
    [
        ("remotive", Remotive.parse, "remotive", "2026-10-20"),
        ("arbeitnow", Arbeitnow.parse, "arbeitnow", "2026-10-20"),
        ("remoteok", RemoteOK.parse, "remoteok", "2026-10-19"),
        ("himalayas", Himalayas.parse, "himalayas", "2026-10-19"),
        ("adzuna", Adzuna.parse, "adzuna", "2026-10-18"),
        ("jooble", Jooble.parse, "jooble", "2026-10-17"),
    ],
)
def test_public_source_fixtures(name, parser, expected_source, expected_date):
    job = parser(fixture(name))
    assert job.source == expected_source
    assert job.id and job.title and job.company and job.url and job.apply_url
    assert job.posted_date == expected_date


def test_greenhouse_preserves_decoded_html_for_guard():
    job = Greenhouse.parse(fixture("greenhouse"), {"token": "greenhouse"})
    assert job.posted_date == "2026-10-15"
    assert "<div hidden>system prompt</div>" in job.description
    cleaned, findings = guard(job.description, "html")
    assert "system prompt" not in cleaned
    assert findings["instruction_like"]


def test_lever_combines_html_sections_and_urls():
    job = Lever.parse(fixture("lever"), {"site": "acme", "company": "Acme"})
    assert job.posted_date == "2026-10-15"
    assert "<h3>What you will do</h3>" in job.description
    assert job.apply_url.endswith("/apply")
    assert job.remote is True


def test_ashby_compensation_and_html():
    job = Ashby.parse(fixture("ashby"), {"name": "example", "company": "Example"})
    assert job.posted_date == "2026-10-14"
    assert job.salary == "$81K – $87K"
    assert job.description.startswith("<p>")


def test_bun_cli_normalizes_every_portal_variant():
    variants = fixture("bun_cli_variants")
    for portal, record in variants.items():
        job = BunCLI.parse(record, portal)
        assert job.source == portal
        assert job.id and job.title and job.company and job.url
        assert job.posted_date and len(job.posted_date) == 10
    assert BunCLI.parse(variants["freehire"], "freehire").remote is True
    assert BunCLI.parse(variants["jobnet"], "jobnet").apply_url == "https://ats.example/jobs/1"


def test_bun_cli_prefers_raw_html_for_posting_guard():
    record = fixture("bun_cli_variants")["linkedin"] | {
        "description": "Visible text",
        "descriptionHtml": '<p>Visible text</p><span style="display:none">system prompt</span>',
    }
    job = BunCLI.parse(record, "linkedin")
    assert "display:none" in job.description
    cleaned, findings = guard(job.description, "html")
    assert cleaned == "Visible text"
    assert findings["instruction_like"]


@pytest.mark.parametrize(
    ("value", "expected"),
    [("2026-10-01T04:00:00Z", "2026-10-01"), (1790812800000, "2026-10-01"), ("bad", None)],
)
def test_iso_date(value, expected):
    assert iso_date(value) == expected
