"""The source registry must stay checkable, not just prose."""

from __future__ import annotations

import copy
import json

from scripts.corpus.sources import actionable, load, summary, validate


def test_shipped_registry_is_valid():
    registry = load()
    assert validate(registry) == []
    assert registry["budget"]["target_tokens"] == 4_000_000_000


def test_registry_covers_the_target():
    stats = summary(load())
    low, high = stats["usable_tokens_est"]
    assert low > stats["target_tokens"], "sourcing must exceed the 4B target several times over"
    assert low <= high
    assert stats["coverage_x"] >= 2


def test_actionable_is_priority_ordered_and_excludes_blocked():
    rows = actionable(load())
    assert rows, "some sources must be usable without any gate"
    assert all(row["status"] == "available" for row in rows)
    assert [row["priority"] for row in rows] == sorted(row["priority"] for row in rows)


def test_duplicate_ids_are_rejected():
    registry = copy.deepcopy(load())
    registry["sources"].append(copy.deepcopy(registry["sources"][0]))
    problems = validate(registry)
    assert any("duplicate id" in problem for problem in problems)


def test_bad_status_and_kind_are_rejected():
    registry = copy.deepcopy(load())
    registry["sources"][0]["status"] = "maybe"
    registry["sources"][1]["kind"] = "whatever"
    problems = validate(registry)
    assert any("invalid status" in problem for problem in problems)
    assert any("invalid kind" in problem for problem in problems)


def test_missing_field_is_rejected():
    registry = copy.deepcopy(load())
    del registry["sources"][0]["license"]
    assert any("missing field 'license'" in problem for problem in validate(registry))


def test_evaluation_sets_are_never_actionable():
    registry = load()
    evaluation = [s for s in registry["sources"] if s["kind"] == "evaluation"]
    assert evaluation, "the registry should name the eval sets we must not train on"
    assert all(s["status"] == "excluded" for s in evaluation)
    assert all(s["id"] not in {r["id"] for r in actionable(registry)} for s in evaluation)
