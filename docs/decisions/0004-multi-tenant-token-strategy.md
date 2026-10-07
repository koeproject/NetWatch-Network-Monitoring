# 0004 — Multi-tenant token strategy

- Status: **Accepted** (decision carried over from the previous build; see
  CLAUDE.md §8 #4)
- Date: 2026-10-08 (rewritten for the rebuild)
- Affects: `backend/app/zabbix/client.py`, `backend/app/auth/`,
  `provisioning/provision.py`

## Context

One engine instance serves several tenants (e.g. `acme-hq`, `branch-co`).
If every read goes through one admin token, a bug in our own tenant
filtering exposes every tenant's hosts. We want the engine's own host-group
permissions as a second line of defence.

## Decision

Two kinds of API token:

| Token | Owner | Used for |
|---|---|---|
| Admin token (`ENGINE_TOKEN` in `backend/.env`) | provisioning user | configuration, provisioning, connector setup |
| Per-tenant token | one engine user per tenant, in a user group with **read** on that tenant's host groups only | every read made on behalf of a tenant |

- `client.py` takes the token **as a parameter on every call** and never
  reads it from `config.py`. (Already true in the rebuilt `client.py`:
  `call(method, params, token=...)`.)
- `auth/` maps portal user → tenant → tenant token. The token itself never
  reaches the browser.
- Per-tenant tokens live in our store / secret storage, not in git.

## Consequences

- A tenant-filtering bug in our code returns at most that tenant's own data.
- Provisioning a tenant = host group + user group + user + token; done by
  `provisioning/provision.py` (Phase 2).
- More tokens to rotate; rotation is part of the runbook (Phase 4).

## Verification

`provisioning/provision.py` must run this check on **every** run and print
PASS/FAIL per tenant: with each tenant's token, `host.get` returns exactly the
hosts in that tenant's groups and nothing else.

Status in the rebuild: `provision.py` does not exist yet (Phase 2), so this
check has not run against the rebuilt engine. In the previous build it first
passed 2026-09-10 (acme-hq saw exactly its 8 hosts, branch-co exactly its 1).
