"""1.2 — the schema must parse every captured line, and survive bad ones."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.zabbix.connector_schema import (
    ProblemLine,
    RecoveryLine,
    parse_events,
    parse_values,
)

FIXTURES = Path(__file__).parent / "fixtures" / "connector"


def _lines(pattern: str) -> list[tuple[Path, bytes]]:
    files = sorted(FIXTURES.glob(pattern))
    assert files, f"no fixtures match {pattern}"
    return [(f, f.read_bytes()) for f in files]


@pytest.mark.parametrize("pattern", ["values-*.ndjson", "probes-*.ndjson"])
def test_every_captured_value_line_parses(pattern: str) -> None:
    for path, body in _lines(pattern):
        expected = len([ln for ln in body.splitlines() if ln.strip()])
        assert len(parse_values(body)) == expected, path.name


def test_value_types_seen_in_the_lab() -> None:
    body = (FIXTURES / "probes-0001.ndjson").read_bytes()
    by_type = {v.type: v for v in parse_values(body)}
    assert by_type[1].value == "probe-char"
    assert by_type[2].value == "probe log line"
    assert by_type[3].value == 0 and isinstance(by_type[3].value, int)
    assert by_type[4].value == "probe text\nsecond line"


def test_float_item_accepts_json_integer() -> None:
    line = (
        b'{"host":{"host":"h","name":"h"},"itemid":1,"name":"n",'
        b'"clock":1,"ns":0,"value":0,"type":0}'
    )
    (parsed,) = parse_values(line)
    assert parsed.value == 0


def test_problem_and_recovery_lines() -> None:
    (problem,) = parse_events((FIXTURES / "events-0001.ndjson").read_bytes())
    (recovery,) = parse_events((FIXTURES / "events-0002.ndjson").read_bytes())

    assert isinstance(problem, ProblemLine)
    assert problem.eventid == 20
    assert problem.severity == 2
    assert problem.hosts[0].host == "Zabbix server"

    assert isinstance(recovery, RecoveryLine)
    assert recovery.p_eventid == problem.eventid


def test_bad_lines_are_skipped_not_fatal(caplog: pytest.LogCaptureFixture) -> None:
    good = (FIXTURES / "values-0006.ndjson").read_bytes().splitlines()[0]
    body = b"\n".join([b"not json", good, b'{"itemid":"missing fields"}', b"", good])

    parsed = parse_values(body)

    assert len(parsed) == 2
    assert caplog.text.count("skipped") == 2


def test_unknown_members_are_ignored() -> None:
    line = (
        b'{"clock":1,"ns":0,"value":0,"eventid":2,"p_eventid":1,'
        b'"added_in_a_patch_release":true}'
    )
    (parsed,) = parse_events(line)
    assert isinstance(parsed, RecoveryLine)


def test_unknown_event_value_is_skipped() -> None:
    assert parse_events(b'{"clock":1,"ns":0,"value":7,"eventid":2}') == []
