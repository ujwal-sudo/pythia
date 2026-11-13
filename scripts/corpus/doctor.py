"""Truthful inventory of the archive.

`project_status.md` described datasets that were not on disk and ran four
near-identical corpora in the same live directory. `doctor` answers, from the
store itself: what exists, how many records actually carry text, what licenses
they carry, and which files are duplicates of each other.

It is read-only.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict

from scripts.corpus.records import FileStats, inspect_file, summarize
from scripts.storage import RootedStore, open_store

EXPECTED = [
    "raw",
    "filtered/stage1",
    "filtered/stage2",
    "filtered/stage3",
    "final",
    "manifests",
    "snapshots",
]

# A file is graded on what it actually contains, not on what its name promises.
TEXT_MISSING_ERROR_RATIO = 0.5
LICENSE_HOLD_WARN_RATIO = 0.05


def _grade(stats: FileStats) -> tuple[str, list[str]]:
    issues: list[str] = []
    if stats.error:
        return "ERROR", [stats.error]
    if stats.records == 0:
        return "ERROR", ["zero records"]
    if stats.text_missing / max(stats.records, 1) >= TEXT_MISSING_ERROR_RATIO:
        issues.append(f"{stats.text_missing}/{stats.records} records have no text")
    if stats.parse_errors:
        issues.append(f"{stats.parse_errors} unparseable lines")
    hold = stats.decisions.get("HOLD", 0) + stats.decisions.get("DENY", 0)
    if hold / max(stats.records, 1) >= LICENSE_HOLD_WARN_RATIO:
        issues.append(f"{hold}/{stats.records} records not license-allowable")
    if stats.intra_file_dupes:
        issues.append(f"{stats.intra_file_dupes} intra-file duplicate texts")

    if any("no text" in issue for issue in issues):
        return "ERROR", issues
    return ("WARN" if issues else "OK"), issues


def _duplicate_groups(stats: list[FileStats]) -> list[dict]:
    """Files with identical record and character counts are near-certain reruns."""
    buckets: dict[tuple[str, int, int], list[str]] = defaultdict(list)
    for item in stats:
        if item.records == 0:
            continue
        buckets[(item.source, item.records, item.chars)].append(item.rel)
    groups = [
        {"source": key[0], "records": key[1], "chars": key[2], "files": rels}
        for key, rels in buckets.items()
        if len(rels) > 1
    ]
    return sorted(groups, key=lambda g: -g["records"])


def run(
    store: RootedStore,
    *,
    stages: tuple[int, ...] = (1, 2, 3),
    sample: int | None = 2000,
    include_raw: bool = True,
    include_rejected: bool = False,
    only: str | None = None,
) -> dict:
    missing = [path for path in EXPECTED if not store.exists(path)]

    targets: list[str] = []
    if include_raw and store.exists("raw"):
        # Only one level down: raw/<source>/*.jsonl. Recursing into raw/ means
        # walking pypi packages and GitHub clones, which is not what this is for.
        for source in store.list("raw"):
            if source.is_dir:
                targets += [
                    e.rel
                    for e in store.files(f"raw/{source.rel.rsplit('/', 1)[-1]}", recursive=False)
                    if e.rel.lower().endswith(".jsonl")
                ]
    for stage in stages:
        prefix = store.filtered(stage)
        if store.exists(prefix):
            targets += [e.rel for e in store.files(prefix, recursive=True) if e.rel.lower().endswith(".jsonl")]
    if only:
        targets = [rel for rel in targets if only.lower() in rel.lower()]
    if not include_rejected:
        # `*_rejected*` files are rejection logs: their records are the ones
        # that were thrown away, so grading them as corpus is a category error.
        targets = [rel for rel in targets if "rejected" not in rel.rsplit("/", 1)[-1].lower()]
    targets = sorted(set(targets))

    stats = [inspect_file(store, rel, sample=sample) for rel in targets]
    graded = [(item, *_grade(item)) for item in stats]

    report = {
        "store": store.describe(),
        "sample_per_file": sample,
        "missing_paths": missing,
        "totals": summarize(stats),
        "files": [
            {**item.to_dict(), "grade": grade, "issues": issues}
            for item, grade, issues in graded
        ],
        "duplicate_groups": _duplicate_groups(stats) if sample is None else [],
        "duplicate_groups_computed": sample is None,
        "errors": [item.rel for item, grade, _ in graded if grade == "ERROR"],
        "warnings": [item.rel for item, grade, _ in graded if grade == "WARN"],
    }
    return report


def render(report: dict) -> str:
    lines: list[str] = []
    lines.append(f"store: {report['store']}")
    if report["missing_paths"]:
        lines.append("missing: " + ", ".join(report["missing_paths"]))
    totals = report["totals"]
    lines.append(
        f"files: {totals['files']}  records: {totals['records']:,}  "
        f"bytes: {totals['bytes']:,}  tokens(est): {totals['tokens_est']:,}"
    )
    lines.append(f"license decisions: {totals['decisions']}")
    lines.append(f"records without text: {totals['text_missing']:,}")
    lines.append("")
    lines.append(f"{'grade':6} {'records':>8} {'no-text':>8} {'hold':>7} {'dup':>6}  file")
    for item in sorted(report["files"], key=lambda i: (i["grade"] != "ERROR", i["rel"])):
        hold = item["decisions"].get("HOLD", 0) + item["decisions"].get("DENY", 0)
        lines.append(
            f"{item['grade']:6} {item['records']:>8,} {item['text_missing']:>8,} "
            f"{hold:>7,} {item['intra_file_dupes']:>6,}  {item['rel']}"
        )
        for issue in item["issues"][:3]:
            lines.append(f"       - {issue}")
    if report["duplicate_groups"]:
        lines.append("")
        lines.append("near-certain reruns (identical record and character counts):")
        for group in report["duplicate_groups"]:
            lines.append(
                f"  {group['records']:,} records, {group['chars']:,} chars: "
                + ", ".join(group["files"])
            )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only inventory of the Pythia archive.")
    parser.add_argument("--store", default=None)
    parser.add_argument("--root", default=None)
    parser.add_argument("--stages", default="1,2,3")
    parser.add_argument("--sample", type=int, default=2000, help="records per file; 0 means all")
    parser.add_argument("--no-raw", action="store_true")
    parser.add_argument("--include-rejected", action="store_true")
    parser.add_argument("--only", default=None)
    parser.add_argument("--json-out", default=None, help="write the full report here")
    args = parser.parse_args(argv)

    stages = tuple(int(part) for part in args.stages.split(",") if part.strip())
    sample = args.sample or None
    store = open_store(args.store, args.root)
    report = run(
        store,
        stages=stages,
        sample=sample,
        include_raw=not args.no_raw,
        include_rejected=args.include_rejected,
        only=args.only,
    )
    print(render(report))
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2)
        print(f"\nwrote {args.json_out}")
    return 0 if not report["errors"] else 1


if __name__ == "__main__":
    sys.exit(main())
