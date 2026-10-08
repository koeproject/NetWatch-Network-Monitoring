"""1.3 — mapper round-trips, adapter over a mocked transport, decoder."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from app.domain.enums import DeviceKind, DeviceStatus, Severity
from app.domain.models import Problem, ProblemResolution
from app.domain.ports import DeviceNotFound, MonitoringEnginePort, PushDecoderPort
from app.zabbix import mapper
from app.zabbix.adapter import ZabbixAdapter
from app.zabbix.client import ZabbixClient
from app.zabbix.connector_ingest import ConnectorDecoder

FIXTURES = Path(__file__).parent / "fixtures" / "connector"

HOST = {
    "hostid": "10084",
    "host": "core-sw-01",
    "name": "Core switch 01",
    "status": "0",
    "maintenance_status": "0",
    "interfaces": [{"available": "1"}],
    "tags": [{"tag": "role", "value": "core"}, {"tag": "site", "value": "HQ"}],
    "lastvalue": "must be ignored",
}


# -- refs ---------------------------------------------------------------------
def test_device_ref_round_trip() -> None:
    assert mapper.host_from_device_ref(mapper.device_ref("core-sw-01")) == "core-sw-01"


def test_problem_ref_round_trip() -> None:
    ref = mapper.problem_ref(20)
    assert ref == "P20"
    assert mapper.eventid_from_problem_ref(ref) == 20


@pytest.mark.parametrize("bad", ["20", "P", "Pabc", "X20"])
def test_problem_ref_rejects_garbage(bad: str) -> None:
    with pytest.raises(ValueError):
        mapper.eventid_from_problem_ref(bad)


# -- scalars ------------------------------------------------------------------
def test_time_is_aware_utc_with_microseconds() -> None:
    ts = mapper.to_datetime(1791395301, 288186659)
    assert ts.tzinfo is UTC
    assert ts == datetime(2026, 10, 7, 17, 48, 21, 288186, tzinfo=UTC)


@pytest.mark.parametrize(
    ("priority", "expected"),
    [(0, Severity.INFO), (2, Severity.WARNING), (3, Severity.MINOR),
     (4, Severity.MAJOR), (5, Severity.CRITICAL), (99, Severity.WARNING)],
)
def test_severity(priority: int, expected: Severity) -> None:
    assert mapper.severity(priority) is expected


# -- devices ------------------------------------------------------------------
def test_device_from_api() -> None:
    d = mapper.device_from_api(HOST)
    assert (d.ref, d.name, d.kind, d.site, d.status) == (
        "core-sw-01", "Core switch 01", DeviceKind.CORE_SWITCH, "HQ", DeviceStatus.UP,
    )


@pytest.mark.parametrize(
    ("patch", "expected"),
    [
        ({"status": "1"}, DeviceStatus.DISABLED),
        ({"maintenance_status": "1"}, DeviceStatus.MAINTENANCE),
        ({"interfaces": [{"available": "2"}]}, DeviceStatus.DOWN),
        ({"interfaces": [{"available": "2"}, {"available": "1"}]}, DeviceStatus.UP),
        ({"interfaces": [{"available": "0"}]}, DeviceStatus.UNKNOWN),
        ({"interfaces": []}, DeviceStatus.UNKNOWN),
    ],
)
def test_device_status(patch: dict, expected: DeviceStatus) -> None:
    assert mapper.device_from_api({**HOST, **patch}).status is expected


# -- adapter ------------------------------------------------------------------
def _engine(hosts: list[dict], seen: list[dict]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append({"body": body, "auth": request.headers.get("Authorization")})
        wanted = body["params"].get("filter", {}).get("host")
        result = [h for h in hosts if wanted is None or h["host"] in wanted]
        return httpx.Response(200, json={"jsonrpc": "2.0", "result": result, "id": body["id"]})

    return httpx.MockTransport(handler)


@pytest.mark.anyio
async def test_adapter_lists_devices_with_callers_token() -> None:
    seen: list[dict] = []
    async with ZabbixClient("http://engine", transport=_engine([HOST], seen)) as client:
        adapter = ZabbixAdapter(client)
        assert isinstance(adapter, MonitoringEnginePort)
        devices = await adapter.list_devices("tenant-token")

    assert [d.ref for d in devices] == ["core-sw-01"]
    assert seen[0]["auth"] == "Bearer tenant-token"
    assert seen[0]["body"]["method"] == "host.get"
    assert "lastvalue" not in json.dumps(seen[0]["body"]["params"])


@pytest.mark.anyio
async def test_adapter_get_device_and_not_found() -> None:
    seen: list[dict] = []
    async with ZabbixClient("http://engine", transport=_engine([HOST], seen)) as client:
        adapter = ZabbixAdapter(client)
        assert (await adapter.get_device("core-sw-01", "t")).name == "Core switch 01"
        with pytest.raises(DeviceNotFound):
            await adapter.get_device("nope", "t")

    assert seen[0]["body"]["params"]["filter"] == {"host": ["core-sw-01"]}


# -- decoder ------------------------------------------------------------------
def test_decoder_keeps_numeric_values_only() -> None:
    decoder = ConnectorDecoder()
    assert isinstance(decoder, PushDecoderPort)

    points = decoder.decode_values((FIXTURES / "probes-0001.ndjson").read_bytes())

    # probes-0001 holds one line of each value_type 1, 2, 3, 4: only 3 is numeric.
    assert [(p.device_ref, p.metric, p.value) for p in points] == [
        ("Zabbix server", "Lab event probe", 0.0)
    ]


def test_decoder_events() -> None:
    decoder = ConnectorDecoder()
    body = (FIXTURES / "events-0001.ndjson").read_bytes() + b"\n" + (
        FIXTURES / "events-0002.ndjson"
    ).read_bytes()

    problem, resolution = decoder.decode_events(body)

    assert isinstance(problem, Problem)
    assert (problem.ref, problem.device_ref, problem.severity, problem.title) == (
        "P20", "Zabbix server", Severity.WARNING, "Lab: event probe is 1",
    )
    assert isinstance(resolution, ProblemResolution)
    assert resolution.problem_ref == problem.ref
    assert resolution.resolved_at > problem.started_at
