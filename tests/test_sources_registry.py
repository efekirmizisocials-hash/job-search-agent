from pathlib import Path

from sources import load_sources
from sources.ats_boards import Greenhouse
from sources.bun_cli import BunCLI
from sources.http import HttpSource


def test_missing_config_uses_safe_keyless_defaults(tmp_path):
    sources, queries = load_sources(tmp_path / "missing.yaml")
    assert [source.name for source in sources] == ["remotive", "arbeitnow", "remoteok", "himalayas"]
    assert queries == ["software engineer"]


def test_registry_skips_missing_keys_and_unknown_source(tmp_path, capsys):
    config = tmp_path / "search.yaml"
    config.write_text(
        "enabled_sources: [adzuna, jooble, imaginary]\nqueries: [python]\n",
        encoding="utf-8",
    )
    sources, queries = load_sources(config)
    assert sources == []
    assert queries == ["python"]
    errors = capsys.readouterr().err
    assert "adzuna skipped" in errors
    assert "jooble skipped" in errors
    assert "unknown source" in errors


def test_registry_builds_ats_board_source(tmp_path):
    config = tmp_path / "search.yaml"
    config.write_text(
        "enabled_sources: [greenhouse]\n"
        "ats:\n  greenhouse:\n    - token: example\n      company: Example Inc\n",
        encoding="utf-8",
    )
    sources, _ = load_sources(config)
    assert len(sources) == 1
    assert isinstance(sources[0], Greenhouse)
    assert sources[0].boards[0]["token"] == "example"


def test_main_sources_override_shape_is_supported(tmp_path):
    config = tmp_path / "search.yaml"
    config.write_text("sources: [remoteok, remotive]\nqueries: [python]\n", encoding="utf-8")
    sources, queries = load_sources(config)
    assert [source.name for source in sources] == ["remoteok", "remotive"]
    assert queries == ["python"]


def test_registry_skips_bun_source_when_runtime_missing(tmp_path, monkeypatch, capsys):
    config = tmp_path / "search.yaml"
    config.write_text("enabled_sources: [linkedin]\n", encoding="utf-8")
    monkeypatch.setattr("sources.bun_cli.shutil.which", lambda _: None)
    sources, _ = load_sources(config)
    assert sources == []
    assert "Bun or vendored CLI missing" in capsys.readouterr().err


def test_bun_search_preserves_html_and_details_missing_descriptions(tmp_path, monkeypatch):
    cli = tmp_path / "src" / "cli.ts"
    cli.parent.mkdir(parents=True)
    cli.write_text("", encoding="utf-8")
    source = BunCLI("freehire", cli_root=tmp_path, limit=2)
    monkeypatch.setattr("sources.bun_cli.shutil.which", lambda _: "/usr/bin/bun")

    def fake_run(args):
        if args[0] == "search":
            assert args[-2:] != ["--format", "json"]  # _run appends format itself
            return {"results": [
                {"id": "one", "title": "One", "company": "Acme", "url": "https://example/1", "date": "2026-10-20", "description": "<p>HTML</p>"},
                {"id": "two", "title": "Two", "company": "Acme", "url": "https://example/2", "date": "2026-10-20"},
            ]}
        return {"id": "two", "title": "Two", "company": "Acme", "url": "https://example/2", "description": "Full detail"}

    monkeypatch.setattr(source, "_run", fake_run)
    jobs = source.search(["engineer"])
    assert [job.description for job in jobs] == ["<p>HTML</p>", "Full detail"]
    assert source.detail(jobs[1]) is jobs[1]


def test_non_freehire_cli_hydrates_rss_summary(tmp_path, monkeypatch):
    cli = tmp_path / "src" / "cli.ts"
    cli.parent.mkdir(parents=True)
    cli.write_text("", encoding="utf-8")
    source = BunCLI("jobbank", cli_root=tmp_path, limit=1)
    monkeypatch.setattr("sources.bun_cli.shutil.which", lambda _: "/usr/bin/bun")

    def fake_run(args):
        if args[0] == "search":
            return {"results": [{"id": "42", "title": "Engineer", "company": "Acme", "url": "https://jobbank.dk/job/42/", "description": "RSS summary"}]}
        return {"id": "42", "title": "Engineer", "company": {"name": "Acme"}, "url": "https://jobbank.dk/job/42/", "description": "<p>Full role</p>"}

    monkeypatch.setattr(source, "_run", fake_run)
    assert source.search(["engineer"])[0].description == "<p>Full role</p>"


def test_http_errors_never_expose_url_credentials():
    class Session:
        def request(self, *args, **kwargs):
            raise RuntimeError("failed https://jooble.org/api/super-secret-key")

    source = HttpSource(session=Session())
    try:
        source._json("post", "https://jooble.org/api/super-secret-key")
    except Exception as exc:
        rendered = str(exc)
    assert "super-secret-key" not in rendered
    assert "jooble.org" in rendered
