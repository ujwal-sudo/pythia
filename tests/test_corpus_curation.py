"""Tests for the storage + corpus curation layer.

Everything runs against a throwaway local store; nothing touches the network.
"""

from __future__ import annotations

import json

import pytest

from scripts.corpus.build import build, select_files
from scripts.corpus.doctor import run as doctor_run
from scripts.corpus.license import Decision, classify
from scripts.corpus.records import inspect_file
from scripts.corpus.schema import normalize_text, normalized_hash, spec_for
from scripts.storage import open_store
from scripts.storage.base import normalize_rel


@pytest.fixture()
def store(tmp_path):
    return open_store("file", str(tmp_path))


def make_peps(n: int = 2) -> list[dict]:
    return [
        {
            "id": f"peps:pep-000{i}",
            "content": f"## Section {i}\n\nSome prose about PEP number {i}.\n",
            "license_spdx": "CC0-1.0",
            "document_url": f"https://peps.python.org/pep-000{i}/",
            "source_revision": "abc123",
        }
        for i in range(n)
    ]


def write_jsonl(store, rel: str, records: list[dict]) -> None:
    lines = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records)
    store.write_text(rel, lines)


# --------------------------------------------------------------- storage


@pytest.mark.parametrize("bad", ["/etc/passwd", "../x", "a/../../b", "a\\b", "a//b", "./x"])
def test_paths_cannot_escape(bad):
    with pytest.raises(ValueError):
        normalize_rel(bad)


def test_store_roundtrip_and_layout(store):
    store.write_text("raw/peps/a.jsonl", '{"a": 1}\n')
    assert store.exists("raw/peps/a.jsonl")
    assert store.read_text("raw/peps/a.jsonl") == '{"a": 1}\n'
    assert [e.rel for e in store.files("raw/peps")] == ["raw/peps/a.jsonl"]
    store.move("raw/peps/a.jsonl", "raw/peps/b.jsonl")
    assert not store.exists("raw/peps/a.jsonl")
    store.delete("raw/peps/b.jsonl")
    assert not store.exists("raw/peps/b.jsonl")


def test_canonical_accessors(store):
    assert store.filtered(1) == "filtered/stage1"
    assert store.raw("peps") == "raw/peps"
    assert store.manifests("corpus-x.json") == "manifests/corpus-x.json"


# ---------------------------------------------------------------- schema


def test_spec_detection_from_path():
    assert spec_for("filtered/stage1/prose_docs_prose-20261022T100121Z-f5fc9a3b_peps.jsonl").name == "peps"
    assert spec_for("filtered/stage2/codesearchnet_full-v3/accepted.jsonl").name == "codesearchnet"
    assert spec_for("filtered/stage3/jupyter_stage3_x.jsonl").name == "jupyter"
    assert spec_for("raw/whatever/thing.jsonl").name == "unknown"


def test_normalize_text_contract():
    raw = "a  \r\n\r\n\r\nb\n\n\nc   \n"
    assert normalize_text(raw) == "a\n\nb\n\nc"
    assert normalize_text("a\n\n\nb") == normalize_text("a\r\n\r\n\r\nb")
    assert normalized_hash("a  \nb") == normalized_hash("a\nb")


# ---------------------------------------------------------------- license


@pytest.mark.parametrize(
    "value,expected",
    [
        ("CC0-1.0", Decision.ALLOW),
        ("Public domain / CC0-1.0", Decision.ALLOW),
        ("MIT", Decision.ALLOW),
        ("BSD-3-Clause", Decision.ALLOW),
        ("CC-BY-4.0", Decision.ALLOW),
        ("CC-BY-NC", Decision.DENY),
        ("CC-BY-NC-SA", Decision.DENY),
        ("UNKNOWN", Decision.HOLD),
        (None, Decision.HOLD),
        ("RESTRICTED_OR_REVIEW", Decision.HOLD),
        ("CLEAR", Decision.HOLD),
        ("Some bespoke license", Decision.HOLD),
    ],
)
def test_license_policy(value, expected):
    assert classify(value).decision is expected


def test_upstream_approval_does_not_override_value():
    verdict = classify("CC-BY-NC", status="APPROVED")
    assert verdict.decision is Decision.DENY
    assert "CC-BY-NC" in verdict.reason


def test_attribution_flagged_for_cc_by():
    assert classify("CC-BY-4.0").attribution_required is True
    assert classify("CC0-1.0").attribution_required is False


# ----------------------------------------------------------------- build


def test_build_dedupes_and_reports_every_drop(store):
    write_jsonl(store, "filtered/stage1/peps_a.jsonl", make_peps(2))
    # One exact duplicate of pep-0000 plus one genuinely new record.
    dupe = make_peps(1)[0]
    new = {"id": "dev:x", "content": "Fresh devguide text.", "license_spdx": "CC0-1.0"}
    write_jsonl(store, "filtered/stage1/devguide_b.jsonl", [dupe, new])
    write_jsonl(
        store,
        "filtered/stage1/atbs_c.jsonl",
        [{"id": "a1", "content": "nc text", "license": "CC-BY-NC"}],
    )
    write_jsonl(store, "filtered/stage1/mystery_d.jsonl", [{"id": "m1", "content": "no license"}])
    write_jsonl(store, "filtered/stage1/jupyter_e.jsonl", [{"record_id": "j1", "license_spdx": "CC0-1.0"}])
    store.write_text("filtered/stage1/broken_f.jsonl", "{not json}\n")

    result = build(store, stages=(1,), write=True, version="corpus-test")
    report = result["report"]
    totals = result["manifest"]["totals"]

    assert totals["kept"] == 3  # 2 peps + 1 new devguide
    assert report["dropped"]["duplicates"] == 1
    assert report["dropped"]["license_deny"] == 1
    assert report["dropped"]["license_hold"] == 1
    assert report["dropped"]["text_missing"] == 1
    assert report["dropped"]["parse_errors"] == 1

    lines = store.read_text(result["output"]).splitlines()
    assert len(lines) == 3
    first = json.loads(lines[0])
    assert set(first) == {"text", "meta"}
    assert first["meta"]["source"] == "peps"
    assert first["meta"]["snapshot_id"] == "corpus-test"
    assert store.exists("manifests/corpus-test.json")
    assert store.exists("reports/curation-corpus-test.json")


def test_build_is_deterministic(store):
    write_jsonl(store, "filtered/stage1/peps_a.jsonl", make_peps(3))
    first = build(store, stages=(1,), write=True, version="v1")
    second = build(store, stages=(1,), write=True, version="v2")
    assert first["manifest"]["totals"]["kept"] == second["manifest"]["totals"]["kept"]

    def payload(result):
        rows = [json.loads(line) for line in store.read_text(result["output"]).splitlines()]
        for row in rows:
            row["meta"].pop("snapshot_id")
        return rows

    assert payload(first) == payload(second)


def test_build_refuses_to_overwrite_snapshot(store):
    write_jsonl(store, "filtered/stage1/peps_a.jsonl", make_peps(1))
    build(store, stages=(1,), write=True, version="fixed")
    with pytest.raises(FileExistsError):
        build(store, stages=(1,), write=True, version="fixed")


def test_select_files_skips_rejected_and_orders_by_stage(store):
    store.write_text("filtered/stage2/codesearchnet_x.jsonl", "")
    store.write_text("filtered/stage1/peps_x.jsonl", "")
    store.write_text("filtered/stage1/peps_rejected.jsonl", "")
    assert select_files(store, stages=(1, 2)) == [
        "filtered/stage1/peps_x.jsonl",
        "filtered/stage2/codesearchnet_x.jsonl",
    ]
    assert "filtered/stage1/peps_rejected.jsonl" in select_files(
        store, stages=(1,), include_rejected=True
    )


# ---------------------------------------------------------------- doctor


def test_doctor_flags_missing_text_and_reruns(store):
    write_jsonl(store, "filtered/stage3/jupyter_a.jsonl", [{"record_id": "j1", "license_spdx": "CC0-1.0"}] * 3)
    write_jsonl(store, "filtered/stage3/jupyter_b.jsonl", [{"record_id": "j1", "license_spdx": "CC0-1.0"}] * 3)
    write_jsonl(store, "filtered/stage1/peps_ok.jsonl", make_peps(2))

    report = doctor_run(store, stages=(1, 3), sample=None, include_raw=False)
    by_rel = {item["rel"]: item for item in report["files"]}

    assert by_rel["filtered/stage3/jupyter_a.jsonl"]["grade"] == "ERROR"
    assert by_rel["filtered/stage1/peps_ok.jsonl"]["grade"] == "OK"
    assert report["duplicate_groups"], "identical reruns must be reported"
    assert "filtered/stage3/jupyter_a.jsonl" in report["errors"]


def test_inspect_file_counts_and_hash(store):
    write_jsonl(store, "filtered/stage1/peps_a.jsonl", make_peps(2))
    stats = inspect_file(store, "filtered/stage1/peps_a.jsonl")
    assert stats.records == 2
    assert stats.text_missing == 0
    assert stats.decisions["ALLOW"] == 2
    assert len(stats.sha256) == 64
    assert stats.hashed_complete is True
