"""1.5–1.7 — the whole backend over HTTP: push in, read out, per tenant.

Uses the real decoder, store (SQLite), services and API; only the engine
lookup is faked. The fixture payloads are the real captured lines.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.domain.models import Tenant
from app.main import create_app
from tests.fakes import PUSH_TOKEN, FakeEngine, make_container

FIXTURES = Path(__file__).parent / "fixtures" / "connector"
PUSH = {"Authorization": f"Bearer {PUSH_TOKEN}", "Content-Type": "application/x-ndjson"}
PASSWORD = "correct horse battery"


@pytest.fixture
def engine() -> FakeEngine:
    return FakeEngine()


@pytest.fixture
def client(tmp_path: Path, engine: FakeEngine) -> Iterator[TestClient]:
    container = make_container(tmp_path, engine)
    with TestClient(create_app(container)) as c:
        c.portal.call(container.auth.add_tenant, Tenant("hq", "HQ", "token-hq"))
        c.portal.call(container.auth.add_tenant, Tenant("branch", "Branch", "token-branch"))
        c.portal.call(container.auth.add_user, "alice", "hq", PASSWORD)
        c.portal.call(container.auth.add_user, "bob", "branch", PASSWORD)
        yield c


def _login(client: TestClient, user: str) -> dict[str, str]:
    r = client.post("/api/auth/login", json={"username": user, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _push(client: TestClient, path: str, fixture: str) -> dict:
    r = client.post(path, content=(FIXTURES / fixture).read_bytes(), headers=PUSH)
    assert r.status_code == 200, r.text
    return r.json()


# -- 1.5 hooks ----------------------------------------------------------------
def test_push_without_token_is_rejected(client: TestClient) -> None:
    r = client.post("/hooks/values", content=b"{}")
    assert r.status_code == 401
    r = client.post("/hooks/values", content=b"{}", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


def test_push_values_reach_latest(client: TestClient) -> None:
    assert _push(client, "/hooks/values", "probes-0001.ndjson") == {"stored": 1}

    latest = client.get("/api/devices/Zabbix server/latest", headers=_login(client, "alice"))

    assert latest.status_code == 200
    assert [(p["metric"], p["value"]) for p in latest.json()] == [("Lab event probe", 0.0)]


def test_problem_then_recovery(client: TestClient) -> None:
    alice = _login(client, "alice")

    assert _push(client, "/hooks/events", "events-0001.ndjson") == {"handled": 1}
    (problem,) = client.get("/api/problems", headers=alice).json()
    assert problem["ref"] == "P20"
    assert problem["severity"] == "warning"
    assert problem["active"] is True

    _push(client, "/hooks/events", "events-0002.ndjson")
    assert client.get("/api/problems", headers=alice).json() == []
    (resolved,) = client.get("/api/problems?active=false", headers=alice).json()
    assert resolved["resolved_at"] is not None


def test_retried_batch_does_not_duplicate(client: TestClient) -> None:
    for _ in range(3):
        _push(client, "/hooks/events", "events-0001.ndjson")
    assert len(client.get("/api/problems", headers=_login(client, "alice")).json()) == 1


def test_bad_lines_do_not_fail_the_batch(client: TestClient) -> None:
    body = b"garbage\n" + (FIXTURES / "probes-0001.ndjson").read_bytes()
    r = client.post("/hooks/values", content=body, headers=PUSH)
    assert r.status_code == 200 and r.json() == {"stored": 1}


# -- 1.6 read API -------------------------------------------------------------
def test_metrics_series_from_store(client: TestClient) -> None:
    for i in range(1, 21):
        _push(client, "/hooks/values", f"values-{i:04d}.ndjson")
    alice = _login(client, "alice")

    r = client.get(
        "/api/devices/Zabbix server/metrics",
        params={"from": "2026-10-07T00:00:00+00:00", "to": "2026-10-09T00:00:00+00:00"},
        headers=alice,
    )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["step"] >= 60
    assert body["series"]  # every metric with a latest value
    assert all(points for points in body["series"].values())


def test_metrics_rejects_naive_and_reversed_times(client: TestClient) -> None:
    alice = _login(client, "alice")
    url = "/api/devices/Zabbix server/metrics"
    assert client.get(url, params={"from": "2026-10-07T00:00:00"}, headers=alice).status_code == 400
    r = client.get(
        url,
        params={"from": "2026-10-09T00:00:00+00:00", "to": "2026-10-08T00:00:00+00:00"},
        headers=alice,
    )
    assert r.status_code == 400


def test_device_list_is_cached(client: TestClient, engine: FakeEngine) -> None:
    alice = _login(client, "alice")
    for _ in range(5):
        assert client.get("/api/devices", headers=alice).status_code == 200
    assert engine.calls == 1


def test_engine_down_is_502_without_naming_it(client: TestClient, engine: FakeEngine) -> None:
    engine.down = True
    r = client.get("/api/devices", headers=_login(client, "alice"))
    assert r.status_code == 502
    assert "zabbix" not in r.text.lower()


# -- 1.7 tenants --------------------------------------------------------------
def test_requests_need_a_session(client: TestClient) -> None:
    for path in ("/api/devices", "/api/problems", "/api/latest", "/api/auth/me"):
        assert client.get(path).status_code == 401, path


def test_wrong_password_and_unknown_user_look_the_same(client: TestClient) -> None:
    a = client.post("/api/auth/login", json={"username": "alice", "password": "nope"})
    b = client.post("/api/auth/login", json={"username": "mallory", "password": "nope"})
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json()


def test_cookie_session_works_for_the_browser(client: TestClient) -> None:
    client.post("/api/auth/login", json={"username": "alice", "password": PASSWORD})
    assert client.get("/api/auth/me").json() == {"tenant_id": "hq", "tenant_name": "HQ"}


def test_tenants_see_only_their_own_devices(client: TestClient) -> None:
    alice, bob = _login(client, "alice"), _login(client, "bob")
    assert [d["ref"] for d in client.get("/api/devices", headers=alice).json()] == [
        "Zabbix server", "core-sw-01",
    ]
    assert [d["ref"] for d in client.get("/api/devices", headers=bob).json()] == ["branch-sw-01"]


def test_tenant_cannot_read_another_tenants_data(client: TestClient) -> None:
    _push(client, "/hooks/values", "probes-0001.ndjson")
    _push(client, "/hooks/events", "events-0001.ndjson")
    bob = _login(client, "bob")

    # Same answer as for a device that does not exist.
    assert client.get("/api/devices/Zabbix server", headers=bob).status_code == 404
    assert client.get("/api/devices/Zabbix server/latest", headers=bob).status_code == 404
    assert client.get("/api/devices/Zabbix server/metrics", headers=bob).status_code == 404
    assert client.get("/api/problems?device=Zabbix server", headers=bob).status_code == 404
    # And the tenant-wide lists simply do not contain it.
    assert client.get("/api/problems", headers=bob).json() == []
    assert client.get("/api/latest", headers=bob).json() == []


def test_tampered_session_is_rejected(client: TestClient) -> None:
    token = _login(client, "alice")["Authorization"].removeprefix("Bearer ")
    payload, signature = token.split(".")
    forged = {"Authorization": f"Bearer {payload}x.{signature}"}
    assert client.get("/api/devices", headers=forged).status_code == 401


# -- 1.9 ----------------------------------------------------------------------
def test_health_and_unknown_api_path(client: TestClient) -> None:
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/api/nope").status_code == 404
