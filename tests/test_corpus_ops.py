"""Tests for publishing and quarantining data (no network)."""

from __future__ import annotations

import json

import pytest

from scripts.corpus.canonical import STAGE1_CANONICAL
from scripts.corpus.quarantine import apply_plan, build_plan
from scripts.corpus.sync import apply, plan
from scripts.storage import open_store

PEPS = STAGE1_CANONICAL[0].filename
DEV = STAGE1_CANONICAL[1].filename


def make_repo(tmp_path):
    repo = tmp_path / "repo"
    stage1 = repo / "data" / "filtered" / "stage1"
    stage1.mkdir(parents=True)
    (stage1 / PEPS).write_text('{"content": "canonical"}\n', encoding="utf-8")
    (stage1 / "prose_docs_prose-20261022T095336Z-f5fc9a3b_peps.jsonl").write_text(
        '{"content": "old run"}\n', encoding="utf-8"
    )
    (stage1 / "atbs_filtered_v3.jsonl").write_text('{"content": "nc"}\n', encoding="utf-8")
    stray = repo / "scripts" / "data" / "raw" / "github" / "owner__repo"
    stray.mkdir(parents=True)
    (stray / "file.py").write_text("print(1)\n", encoding="utf-8")
    return repo


def test_sync_uploads_missing_then_reports_present(tmp_path):
    repo = make_repo(tmp_path)
    local = open_store("file", str(repo / "data"))
    remote = open_store("file", str(tmp_path / "archive"))

    first = plan(local, remote)
    peps_row = next(row for row in first if row["rel"].endswith(PEPS))
    assert peps_row["action"] == "upload"
    # Files that are not in the frozen list are not uploaded.
    assert len(first) == len(STAGE1_CANONICAL)

    result = apply(local, remote)
    assert result["uploaded"] == 1
    assert remote.stat(f"filtered/stage1/{PEPS}").size == peps_row["local_size"]
    wrote = [e.rel for e in remote.files("manifests")]
    assert wrote and wrote[0].startswith("manifests/stage1_sync_")

    second = plan(local, remote)
    assert next(row for row in second if row["rel"].endswith(PEPS))["action"] == "present"


def test_quarantine_moves_without_deleting(tmp_path):
    repo = make_repo(tmp_path)
    result = build_plan(repo)

    categories = {move["category"] for move in result["moves"]}
    assert categories == {"superseded", "license-excluded", "stray-github-clones"}
    assert result["keep_count"] == 1

    manifest = apply_plan(repo, result)
    assert len(manifest["moved"]) == 3

    stage1 = repo / "data" / "filtered" / "stage1"
    assert (stage1 / PEPS).exists()
    assert not (stage1 / "atbs_filtered_v3.jsonl").exists()
    assert (repo / "data" / "archive" / "stage1-superseded" / "prose_docs_prose-20261022T095336Z-f5fc9a3b_peps.jsonl").exists()
    assert (repo / "data" / "archive" / "stray-github-clones" / "raw" / "github" / "owner__repo" / "file.py").exists()
    assert not (repo / "scripts" / "data").exists()

    saved = json.loads((repo / "data" / "archive" / "ARCHIVE_MANIFEST.json").read_text())
    assert saved["kept_in_stage1"] == [str(stage1 / PEPS)]
    assert saved["moved"][0]["sha256"] is not None


def test_quarantine_refuses_to_touch_outside_repo(tmp_path):
    repo = make_repo(tmp_path)
    outside = tmp_path / "outside.jsonl"
    outside.write_text("x", encoding="utf-8")
    result = build_plan(repo)
    result["moves"].append({"category": "evil", "src": str(outside), "dst": str(tmp_path / "x"), "bytes": 1})
    with pytest.raises(RuntimeError):
        apply_plan(repo, result)
    assert outside.exists()
