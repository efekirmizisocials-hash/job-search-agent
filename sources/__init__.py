"""Pluggable job-source registry and YAML configuration loader."""
from __future__ import annotations

import os
from pathlib import Path
import sys
from typing import Any

from .adzuna import Adzuna
from .arbeitnow import Arbeitnow
from .ats_boards import ATS_SOURCES, Ashby, Greenhouse, Lever
from .base import Job, Source
from .bun_cli import BunCLI, PORTAL_FLAGS
from .himalayas import Himalayas
from .jooble import Jooble
from .remoteok import RemoteOK
from .remotive import Remotive
from .salto import Salto


PUBLIC_SOURCES = {
    "remotive": Remotive,
    "arbeitnow": Arbeitnow,
    "remoteok": RemoteOK,
    "himalayas": Himalayas,
    "adzuna": Adzuna,
    "jooble": Jooble,
    "salto": Salto,
}
SAFE_DEFAULTS = ["remotive", "arbeitnow", "remoteok", "himalayas"]
DEFAULT_QUERIES = ["software engineer"]


def _warn(message: object) -> None:
    text = str(message).replace("\r", " ").replace("\n", " ")[:500]
    print(f"sources: {text}", file=sys.stderr)


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        import yaml
    except ImportError:
        _warn(f"cannot read {path}: PyYAML is not installed; using safe defaults")
        return {}
    try:
        parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        _warn(f"cannot read {path}: {exc}; using safe defaults")
        return {}
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        _warn(f"{path} must contain a mapping; using safe defaults")
        return {}
    return parsed


def _strings(value: Any, default: list[str] | None = None) -> list[str]:
    if isinstance(value, str):
        values = value.split(",")
    elif isinstance(value, list):
        values = value
    else:
        return list(default or [])
    return [str(item).strip() for item in values if str(item).strip()]


def _positive(value: Any, default: int, maximum: int) -> int:
    try:
        return max(1, min(int(value), maximum))
    except (TypeError, ValueError):
        return default


def load_sources(path: str | os.PathLike[str] = "search.yaml") -> tuple[list[Source], list[str]]:
    """Load configured sources without allowing one bad adapter to abort all.

    Missing configuration enables only keyless public APIs.  Sources requiring
    a key or Bun are skipped at load time with a clear stderr message.
    """
    config = _load_yaml(Path(path))
    queries = _strings(config.get("queries"), DEFAULT_QUERIES)
    env_queries = os.getenv("JOB_QUERIES")
    if env_queries:
        queries = _strings(env_queries, queries)
    queries = queries[:50]
    locations = _strings(config.get("locations"))[:25]
    limit = _positive(config.get("per_source_limit"), 25, 250)
    max_pages = _positive(config.get("max_pages"), 2, 20)
    max_age_days = _positive(config.get("max_age_days"), 30, 3650)
    raw_source_settings = config.get("sources")
    # ``main --sources`` writes a temporary config with ``sources: [names]``.
    # The normal user config uses ``sources: {name: options}`` and
    # ``enabled_sources: [names]``; support both shapes without ambiguity.
    override_names = raw_source_settings if isinstance(raw_source_settings, list) else None
    enabled = _strings(override_names if override_names is not None else config.get("enabled_sources"), SAFE_DEFAULTS)
    if os.getenv("JOB_SOURCES"):
        enabled = _strings(os.getenv("JOB_SOURCES"), enabled)
    enabled = enabled[:50]
    settings = raw_source_settings if isinstance(raw_source_settings, dict) else {}
    ats = config.get("ats") if isinstance(config.get("ats"), dict) else {}
    common = {
        "locations": locations, "limit": limit,
        "max_pages": max_pages, "max_age_days": max_age_days,
    }
    loaded: list[Source] = []
    for raw_name in enabled:
        name = raw_name.casefold().replace("-search", "")
        options = settings.get(name) if isinstance(settings.get(name), dict) else {}
        merged = {**common, **options}
        try:
            if name in PORTAL_FLAGS:
                source = BunCLI(name, **merged)
                if not source.available:
                    _warn(f"{name} skipped: Bun or vendored CLI missing")
                    continue
                loaded.append(source)
            elif name in ATS_SOURCES:
                board_options = dict(options)
                boards = board_options.pop("boards", ats.get(name, []))
                if not boards:
                    _warn(f"{name} skipped: no company boards configured")
                    continue
                loaded.append(ATS_SOURCES[name](boards=boards, **{**common, **board_options}))
            elif name == "adzuna":
                source = Adzuna(**merged)
                if not source.configured:
                    _warn("adzuna skipped: set ADZUNA_APP_ID and ADZUNA_APP_KEY")
                    continue
                loaded.append(source)
            elif name == "jooble":
                source = Jooble(**merged)
                if not source.configured:
                    _warn("jooble skipped: set JOOBLE_API_KEY")
                    continue
                loaded.append(source)
            elif name in PUBLIC_SOURCES:
                loaded.append(PUBLIC_SOURCES[name](**merged))
            else:
                _warn(f"unknown source {raw_name!r}; skipped")
        except Exception as exc:
            _warn(f"{raw_name} skipped: {exc}")
    return loaded, queries


__all__ = [
    "Job", "Source", "load_sources", "Remotive", "Arbeitnow", "RemoteOK",
    "Himalayas", "Adzuna", "Jooble", "Greenhouse", "Lever", "Ashby",
    "BunCLI", "Salto",
]
