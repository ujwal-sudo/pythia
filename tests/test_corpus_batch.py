"""Tests for immutable batches and cross-batch deduplication."""

from __future__ import annotations

import json

import pytest

from scripts.corpus.batch import adopt, clean, load_registry, next_batch_id, verify
from scripts.corpus.schema import normalize_text, normalized_hash
from scripts.storage import open_store


@pytest.fixture()
def store(tmp_path):
    return open_store("file", str(tmp_path))


def seed_corpus(store, texts: list[str], snapshot: str = "corpus-x") -> str:
    """Write a fake built corpus plus its manifest, as build would."""
    lines = []
    for i, text in enumerate(texts):
        lines.append(
            json.dumps(
                {
                    "text": text,
                    "meta": {
                        "record_id": f"peps:{i}",
                        "source": "peps",
                        "license_spdx": "CC0-1.0",
                        "license_decision": "ALLOW",
                        "normalized_sha256": normalized_hash(text),
                        "snapshot_id": snapshot,
                    },
                }
            )
        )
    store.write_text(f"final/{snapshot}.jsonl", "\n".join(lines) + "\n")
    store.write_text(
        f"manifests/{snapshot}.json",
        json.dumps({"snapshot_id": snapshot, "output": f"final/{snapshot}.jsonl", "sources": []}),
    )
    return snapshot


def test_adopt_creates_immutable_batch(store):
    seed_corpus(store, ["def a():\n    return 1", "def b():\n    return 2", "def c():\n    return 3"])
    entry = adopt(store, "corpus-x", shard_bytes=100)

    assert entry["id"] == "batch-001"
    assert entry["records"] == 3
    assert len(entry["shards"]) >= 2, "small shard limit must rotate"
    assert sum(s["records"] for s in entry["shards"]) == 3

    registry = load_registry(store)
    assert [b["id"] for b in registry["batches"]] == ["batch-001"]
    assert registry["totals"]["records"] == 3

    hashes = store.read_text(entry["hashes"]["rel"]).splitlines()
    assert len(hashes) == 3
    assert store.exists("batches/batch-001/stats.json")


def test_adopt_refuses_a_second_time(store):
    seed_corpus(store, ["x = 1"])
    adopt(store, "corpus-x")
    with pytest.raises(FileExistsError):
        adopt(store, "corpus-x")


def test_clean_dedupes_against_earlier_batches(store):
    text = "def shared():\n    return 42"
    seed_corpus(store, [text])
    adopt(store, "corpus-x")

    new_text = "def brand_new():\n    return 7"
    store.write_text(
        "filtered/stage1/peps_new.jsonl",
        "\n".join(
            json.dumps({"id": f"p{i}", "content": t, "license_spdx": "CC0-1.0"})
            for i, t in enumerate([text, new_text])
        )
        + "\n",
    )

    entry = clean(store, files=["filtered/stage1/peps_new.jsonl"])
    assert entry["id"] == "batch-002"
    assert entry["records"] == 1
    assert entry["dropped"]["duplicates"] == 1
    assert entry["dedup_seeded_from_prior_batches"] == 1

    registry = load_registry(store)
    assert [b["id"] for b in registry["batches"]] == ["batch-001", "batch-002"]
    assert registry["totals"]["records"] == 2


def test_clean_applies_license_policy(store):
    store.write_text(
        "filtered/stage1/peps_lic.jsonl",
        json.dumps({"id": "a", "content": "nc text", "license": "CC-BY-NC"}) + "\n",
    )
    entry = clean(store, files=["filtered/stage1/peps_lic.jsonl"])
    assert entry["records"] == 0
    assert entry["dropped"]["license_deny"] == 1


def test_verify_detects_tampering(store):
    seed_corpus(store, ["a = 1", "b = 2"])
    adopt(store, "corpus-x")
    assert verify(store, "batch-001")["ok"]

    shard = load_registry(store)["batches"][0]["shards"][0]
    store.write_text(shard["rel"], "tampered\n")
    result = verify(store, "batch-001")
    assert not result["ok"]
    assert any("sha256" in problem or "size" in problem for problem in result["problems"])


def test_next_batch_id_skips_used(store):
    assert next_batch_id({"batches": []}) == "batch-001"
    assert next_batch_id({"batches": [{"id": "batch-001"}, {"id": "batch-002"}]}) == "batch-003"


def test_normalisation_is_what_dedup_sees(store):
    # Same code, different trailing whitespace: one record, not two.
    seed_corpus(store, ["def f():  \n    pass   "])
    adopt(store, "corpus-x")
    store.write_text(
        "filtered/stage1/peps_dup.jsonl",
        json.dumps({"id": "z", "content": "def f():\n    pass", "license_spdx": "CC0-1.0"}) + "\n",
    )
    entry = clean(store, files=["filtered/stage1/peps_dup.jsonl"])
    assert entry["records"] == 0
    assert entry["dropped"]["duplicates"] == 1
    assert normalize_text("def f():  \n    pass   ") == "def f():\n    pass"
