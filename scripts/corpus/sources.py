"""The source registry: what we plan to ingest, and why.

`DATASET_SOURCES.md` is the narrative; this module makes the same list
checkable. Ingest code reads it instead of hard-coding dataset ids, so adding a
source is a data change, not a code change.

    python -m scripts.corpus.sources list
    python -m scripts.corpus.sources check
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REGISTRY_PATH = Path(__file__).with_name("sources.json")

REQUIRED_FIELDS = ("id", "title", "kind", "priority", "status", "access", "license", "size", "why")
VALID_STATUS = {"available", "needs_terms", "deferred", "hold", "excluded"}
VALID_KINDS = {"code_corpus", "docs", "instruction", "tests", "pypi", "educational", "evaluation"}


def load(path: str | Path | None = None) -> dict:
    with Path(path or REGISTRY_PATH).open(encoding="utf-8") as handle:
        return json.load(handle)


def validate(registry: dict) -> list[str]:
    """Return human-readable problems; empty list means the registry is sound."""
    problems: list[str] = []
    sources = registry.get("sources")
    if not isinstance(sources, list) or not sources:
        return ["registry has no sources"]

    seen: set[str] = set()
    for index, source in enumerate(sources):
        label = source.get("id", f"#{index}")
        for field in REQUIRED_FIELDS:
            if field not in source:
                problems.append(f"{label}: missing field {field!r}")
        if source.get("id") in seen:
            problems.append(f"{label}: duplicate id")
        seen.add(source.get("id"))
        if source.get("status") not in VALID_STATUS:
            problems.append(f"{label}: invalid status {source.get('status')!r}")
        if source.get("kind") not in VALID_KINDS:
            problems.append(f"{label}: invalid kind {source.get('kind')!r}")
        if not isinstance(source.get("priority"), int):
            problems.append(f"{label}: priority must be an int")
        size = source.get("size") or {}
        low, high = size.get("tokens_est_low", 0), size.get("tokens_est_high", 0)
        if not isinstance(low, int) or not isinstance(high, int) or low > high:
            problems.append(f"{label}: bad token estimate range")
        access = source.get("access") or {}
        if not access.get("type"):
            problems.append(f"{label}: access.type missing")
    return problems


def summary(registry: dict) -> dict:
    by_status: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    tokens_low = tokens_high = 0
    for source in registry["sources"]:
        by_status[source["status"]] = by_status.get(source["status"], 0) + 1
        by_kind[source["kind"]] = by_kind.get(source["kind"], 0) + 1
        if source["status"] in ("available", "needs_terms"):
            tokens_low += source["size"]["tokens_est_low"]
            tokens_high += source["size"]["tokens_est_high"]
    budget = registry.get("budget", {})
    target = budget.get("target_tokens", 0)
    return {
        "sources": len(registry["sources"]),
        "by_status": by_status,
        "by_kind": by_kind,
        "usable_tokens_est": [tokens_low, tokens_high],
        "target_tokens": target,
        "coverage_x": round(tokens_low / target, 1) if target else None,
    }


def actionable(registry: dict) -> list[dict]:
    """Sources we can start on right now, highest priority first."""
    rows = [s for s in registry["sources"] if s["status"] == "available"]
    return sorted(rows, key=lambda s: (s["priority"], s["id"]))


def _fmt_tokens(value: int) -> str:
    if value >= 1_000_000_000:
        return f"{value / 1e9:.1f}B"
    if value >= 1_000_000:
        return f"{value / 1e6:.0f}M"
    return str(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Source registry for the Pythia corpus.")
    parser.add_argument("--registry", default=None)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="list sources by priority")
    sub.add_parser("check", help="validate the registry")
    sub.add_parser("summary", help="totals by status and kind")
    args = parser.parse_args(argv)

    registry = load(args.registry)
    if args.command == "check":
        problems = validate(registry)
        for problem in problems:
            print("PROBLEM:", problem)
        print("ok" if not problems else f"{len(problems)} problem(s)")
        return 0 if not problems else 1

    if args.command == "summary":
        print(json.dumps(summary(registry), indent=2))
        return 0

    for source in sorted(registry["sources"], key=lambda s: (s["priority"], s["id"])):
        size = source["size"]
        estimate = (
            f"{_fmt_tokens(size['tokens_est_low'])}-{_fmt_tokens(size['tokens_est_high'])}"
            if size["tokens_est_high"]
            else "metadata"
        )
        print(
            f"P{source['priority']:<2} {source['status']:12} {estimate:>10}  "
            f"{source['kind']:12} {source['id']:24} {source['title']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
