"""Tiny smoke-test entry point shared by source modules."""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from typing import Any


def run(source_type: Any) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("query", nargs="?", default="python developer")
    parser.add_argument("--limit", type=int, default=3)
    args = parser.parse_args()
    source = source_type(limit=args.limit)
    jobs = source.search([args.query])
    print(json.dumps([asdict(job) for job in jobs], ensure_ascii=False, indent=2))
    return 0 if jobs or not source.errors else 1
