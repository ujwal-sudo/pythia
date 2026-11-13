"""One-shot corpus build over everything in the archive.

Kept for rebuilding from raw sources. Incremental work should use
`scripts.corpus.batch`, which produces immutable batches; this command still
writes a single monolithic corpus.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import tempfile
import uuid
from pathlib import Path

from scripts.corpus.license import DEFAULT_POLICY, Policy
from scripts.corpus.pipeline import CurationRun, DedupIndex
from scripts.corpus.schema import spec_for
from scripts.storage import RootedStore, open_store

STAGE_ORDER = {1: 0, 2: 1, 3: 2}
SOURCE_PRIORITY = {
    "peps": 0,
    "devguide": 1,
    "python_docs": 2,
    "scientific_docs": 3,
    "thinkpython": 4,
    "atbs": 5,
    "jupyter": 6,
    "pypi": 7,
    "stackoverflow": 8,
    "codesearchnet": 9,
    "the_stack": 10,
    "unknown": 99,
}


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def select_files(
    store: RootedStore,
    *,
    stages: tuple[int, ...] = (1, 2, 3),
    only: str | None = None,
    include_rejected: bool = False,
) -> list[str]:
    """List candidate JSONL files, ordered by curriculum stage then source."""
    selected: list[str] = []
    for stage in stages:
        prefix = store.filtered(stage)
        if not store.exists(prefix):
            continue
        for entry in store.files(prefix, recursive=True):
            rel = entry.rel
            name = rel.rsplit("/", 1)[-1].lower()
            if not name.endswith(".jsonl"):
                continue
            if ".part-" in name:
                continue
            if not include_rejected and "rejected" in name:
                continue
            if only and only.lower() not in rel.lower():
                continue
            selected.append(rel)

    def sort_key(rel: str) -> tuple:
        spec = spec_for(rel)
        return (STAGE_ORDER.get(spec.stage, 9), SOURCE_PRIORITY.get(spec.name, 99), rel)

    return sorted(selected, key=sort_key)


def build(
    store: RootedStore,
    *,
    stages: tuple[int, ...] = (1, 2, 3),
    only: str | None = None,
    include_rejected: bool = False,
    write: bool = False,
    version: str | None = None,
    policy: Policy = DEFAULT_POLICY,
    sample: int | None = None,
    limit: int | None = None,
) -> dict:
    files = select_files(store, stages=stages, only=only, include_rejected=include_rejected)
    snapshot_id = version or (
        "corpus-"
        + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + uuid.uuid4().hex[:6]
    )
    manifest_rel = store.manifests(f"{snapshot_id}.json")
    if write and store.exists(manifest_rel):
        raise FileExistsError(f"snapshot already exists: {manifest_rel}")

    output_rel = store.final(f"{snapshot_id}.jsonl")
    with tempfile.TemporaryDirectory(prefix="pythia-build-") as tmp:
        with DedupIndex(Path(tmp) / "dedup.sqlite") as index:
            run = CurationRun(
                store=store,
                files=files,
                index=index,
                snapshot_id=snapshot_id,
                policy=policy,
                sample=sample,
                limit=limit,
            )
            if write:
                store.write(output_rel, run.lines())
            else:
                for _ in run.lines():
                    pass
            totals = run.finalise_totals()

    manifest = {
        "snapshot_id": snapshot_id,
        "created_at": utc_now(),
        "store": store.describe(),
        "generator": "scripts.corpus.build",
        "policy": policy.describe(),
        "sample": sample,
        "limit": limit,
        "sources": run.source_rows(),
        "totals": totals,
        "licenses": dict(run.licenses.most_common()),
        "output": output_rel if write else None,
    }
    report = {
        "snapshot_id": snapshot_id,
        "generated_at": utc_now(),
        "kept": totals["kept"],
        "dropped": {
            "duplicates": totals.get("duplicates", 0),
            "cross_source_duplicates": run.cross_source,
            "license_hold": totals.get("license_hold", 0),
            "license_deny": totals.get("license_deny", 0),
            "text_missing": totals.get("text_missing", 0),
            "parse_errors": totals.get("parse_errors", 0),
        },
        "hold_reasons": dict(run.holders.most_common(20)),
        "duplicate_examples": run.dupe_examples,
        "per_file": run.source_rows(),
    }

    if write:
        store.write_text(manifest_rel, json.dumps(manifest, indent=2) + "\n")
        store.write_text(
            store.reports(f"curation-{snapshot_id}.json"), json.dumps(report, indent=2) + "\n"
        )
    return {"manifest": manifest, "report": report, "manifest_rel": manifest_rel, "output": output_rel}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the corpus in one streaming pass.")
    parser.add_argument("--store", default=None, help="rclone (default) or file")
    parser.add_argument("--root", default=None, help="store root, e.g. pythia:Pythia")
    parser.add_argument("--stages", default="1,2,3", help="comma separated stage numbers")
    parser.add_argument("--only", default=None, help="substring filter on file paths")
    parser.add_argument("--include-rejected", action="store_true")
    parser.add_argument("--write", action="store_true", help="materialise corpus and manifest")
    parser.add_argument("--version", default=None, help="explicit snapshot id")
    parser.add_argument("--sample", type=int, default=None, help="records per file")
    parser.add_argument("--limit", type=int, default=None, help="stop after N kept records")
    args = parser.parse_args(argv)

    stages = tuple(int(part) for part in args.stages.split(",") if part.strip())
    store = open_store(args.store, args.root)
    result = build(
        store,
        stages=stages,
        only=args.only,
        include_rejected=args.include_rejected,
        write=args.write,
        version=args.version,
        sample=args.sample,
        limit=args.limit,
    )
    manifest = result["manifest"]
    print(json.dumps({"snapshot_id": manifest["snapshot_id"], **manifest["totals"]}, indent=2))
    if args.write:
        print(f"manifest: {result['manifest_rel']}")
        print(f"corpus:   {result['output']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
