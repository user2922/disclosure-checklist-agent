"""Audit log guarantees. Every test writes to tmp_path; nothing touches the real log."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.audit import append, append_rule_evaluations, read_entries, result_exists
from app.engine import compose_buckets
from tests.test_rules import load_fixture


@pytest.fixture
def log(tmp_path: Path) -> Path:
    return tmp_path / "audit.jsonl"


def test_two_appends_leave_two_lines_and_never_rewrite_the_first(log: Path) -> None:
    """Append-only, asserted at the byte level rather than assumed."""
    append("result", "r1", {"n": 1}, path=log)
    first_after_one_write = log.read_text(encoding="utf-8").splitlines()[0]

    append("result", "r2", {"n": 2}, path=log)
    lines = log.read_text(encoding="utf-8").splitlines()

    assert len(lines) == 2
    assert lines[0] == first_after_one_write


def test_invalid_kind_raises_before_writing_anything(log: Path) -> None:
    with pytest.raises(ValidationError):
        append("fabricated", "r1", {}, path=log)  # type: ignore[arg-type]
    assert not log.exists(), "a rejected entry must leave no trace"


def test_corrupt_line_is_skipped_and_counted(log: Path) -> None:
    append("result", "r1", {"n": 1}, path=log)
    with open(log, "a", encoding="utf-8") as handle:
        handle.write("{ this is not json\n")
    append("result", "r3", {"n": 3}, path=log)

    read = read_entries(path=log)
    assert read.skipped == 1
    assert [e.payload["n"] for e in read.entries] == [3, 1], "newest first"


def test_missing_file_reads_as_empty_not_an_error(tmp_path: Path) -> None:
    read = read_entries(path=tmp_path / "does-not-exist.jsonl")
    assert read.entries == []
    assert read.skipped == 0


def test_parent_directory_is_created_on_first_write(tmp_path: Path) -> None:
    nested = tmp_path / "a" / "b" / "audit.jsonl"
    append("result", "r1", {}, path=nested)
    assert nested.exists()


def test_result_exists_ignores_rule_evaluations(log: Path) -> None:
    """A result that never completed cannot be confirmed."""
    facts = load_fixture("dc_condo_tenant")
    append_rule_evaluations("r1", facts, compose_buckets(facts).evaluations, path=log)

    assert result_exists("r1", path=log) is False
    append("result", "r1", {"ok": True}, path=log)
    assert result_exists("r1", path=log) is True
    assert result_exists("never-seen", path=log) is False


def test_dc_fixture_writes_nine_rule_evaluation_lines(log: Path) -> None:
    """Every rule in scope, applied or not — 9 for DC."""
    facts = load_fixture("dc_condo_tenant")
    buckets = compose_buckets(facts)
    written = append_rule_evaluations("r1", facts, buckets.evaluations, path=log)

    assert written == 9
    assert len(log.read_text(encoding="utf-8").splitlines()) == 9

    applied = [
        json.loads(line)["payload"]
        for line in log.read_text(encoding="utf-8").splitlines()
        if json.loads(line)["payload"]["applies"]
    ]
    assert len(applied) == 4, "4 of 9 DC rules apply to this fixture"


def test_every_timestamp_is_utc_iso8601_with_z(log: Path) -> None:
    append("result", "r1", {}, path=log)
    append("confirmation", "r1", {"by": "A Broker"}, path=log)

    for line in log.read_text(encoding="utf-8").splitlines():
        stamp = json.loads(line)["timestamp"]
        assert stamp.endswith("Z"), stamp
        assert "+00:00" not in stamp


def test_entry_has_exactly_four_keys(log: Path) -> None:
    append("error", "r1", {"detail": "x"}, path=log)
    record = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
    assert set(record) == {"timestamp", "kind", "result_id", "payload"}


def test_filter_by_result_id(log: Path) -> None:
    append("result", "r1", {}, path=log)
    append("result", "r2", {}, path=log)
    assert len(read_entries(result_id="r1", path=log).entries) == 1
    assert len(read_entries(path=log).entries) == 2
