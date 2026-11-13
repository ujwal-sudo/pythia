"""Move redundant local data out of the live tree.

`filtered/stage1` accumulated four superseded prose runs, two license-gated
revisions, and two non-commercial textbooks that the license policy denies.
Separately, 914 MB of GitHub clones were written to `scripts/data/raw/` by a
path bug and referenced by nothing.

Nothing here deletes. Everything moves under `data/archive/<date>/` and is
recorded in a manifest, so "where did that file go" has an answer.

    python -m scripts.corpus.quarantine --plan
    python -m scripts.corpus.quarantine --apply
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import sys
from pathlib import Path

from scripts.corpus.canonical import STAGE1_CANONICAL, STAGE1_EXCLUDED
from scripts.corpus.sync import sha256_file

# The rejection log belongs to the canonical run even though it is not corpus.
CANONICAL_COMPANIONS = {
    "prose_docs_prose-license-gated-v2_peps_rejected.jsonl",
    "prose_docs_prose-license-gated-v2_cpython_devguide_rejected.jsonl",
}

STAGE1_KEEP = {entry.filename for entry in STAGE1_CANONICAL} | CANONICAL_COMPANIONS
STAGE1_EXCLUDE = {entry.filename: entry.reason for entry in STAGE1_EXCLUDED}


def classify(stage1: Path) -> tuple[list[Path], list[Path], list[Path]]:
    """Return (keep, superseded, license_excluded) for the live stage1 dir."""
    keep: list[Path] = []
    superseded: list[Path] = []
    excluded: list[Path] = []
    for path in sorted(stage1.glob("*.jsonl")):
        if path.name in STAGE1_KEEP:
            keep.append(path)
        elif path.name in STAGE1_EXCLUDE:
            excluded.append(path)
        else:
            superseded.append(path)
    return keep, superseded, excluded


def build_plan(repo: Path) -> dict:
    stage1 = repo / "data" / "filtered" / "stage1"
    keep, superseded, excluded = classify(stage1)
    stray = repo / "scripts" / "data"

    moves: list[dict] = []
    for category, paths, bucket in (
        ("superseded", superseded, "stage1-superseded"),
        ("license-excluded", excluded, "stage1-license-excluded"),
    ):
        for path in paths:
            moves.append(
                {
                    "category": category,
                    "src": str(path),
                    "dst": str(repo / "data" / "archive" / bucket / path.name),
                    "bytes": path.stat().st_size,
                }
            )

    if stray.is_dir():
        repos = sorted(p.name for p in (stray / "raw" / "github").glob("*") if p.is_dir())
        moves.append(
            {
                "category": "stray-github-clones",
                "src": str(stray),
                "dst": str(repo / "data" / "archive" / "stray-github-clones"),
                "bytes": sum(f.stat().st_size for f in stray.rglob("*") if f.is_file()),
                "repos": repos,
            }
        )

    return {
        "keep": [str(p) for p in keep],
        "moves": moves,
        "keep_count": len(keep),
        "move_count": len(moves),
        "bytes_moved": sum(m["bytes"] for m in moves),
    }


def apply_plan(repo: Path, plan: dict) -> dict:
    archive_root = repo / "data" / "archive"
    moved: list[dict] = []
    for move in plan["moves"]:
        src = Path(move["src"]).resolve()
        dst = Path(move["dst"]).resolve()
        # Refuse to touch anything outside this repository.
        if repo.resolve() not in src.parents or repo.resolve() not in dst.parents:
            raise RuntimeError(f"refusing to move outside the repo: {src} -> {dst}")
        if not src.exists():
            continue
        if dst.exists():
            raise FileExistsError(f"destination already exists: {dst}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        moved.append({**move, "sha256": None})
        if move["category"] in ("superseded", "license-excluded"):
            moved[-1]["sha256"] = sha256_file(dst)[0]

    manifest = {
        "archived_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "kept_in_stage1": plan["keep"],
        "moved": moved,
        "bytes_moved": sum(m["bytes"] for m in moved),
        "recover": "move files back from data/archive/ to their original path",
    }
    archive_root.mkdir(parents=True, exist_ok=True)
    manifest_path = archive_root / "ARCHIVE_MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Quarantine redundant local data (move, never delete).")
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve()
    plan = build_plan(repo)
    if not args.apply:
        print(json.dumps(plan, indent=2))
        return 0
    manifest = apply_plan(repo, plan)
    print(json.dumps({"moved": len(manifest["moved"]), "bytes": manifest["bytes_moved"]}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
