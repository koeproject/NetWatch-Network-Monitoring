"""Export engine templates and our hosts to YAML, so changes show up in git diff.

    nw provisioning.export                                 # ours + inventory hosts
    nw provisioning.export --upstream "Cisco IOS by SNMP"  # as shipped -> templates/upstream/

templates/upstream/ is READ ONLY after the first export: never edit, only re-export.
"""

from __future__ import annotations

import argparse
import asyncio
import re
from pathlib import Path

from app.config import get_settings
from app.zabbix.client import ZabbixClient
from provisioning.catalog import TEMPLATE_PREFIX, load_inventory

ROOT = Path(__file__).resolve().parent.parent
OURS = ROOT / "templates" / "netwatch"
UPSTREAM = ROOT / "templates" / "upstream"


def _filename(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") + ".yaml"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    old = path.read_text(encoding="utf-8") if path.exists() else None
    if old == text:
        print(f"unchanged {path.relative_to(ROOT)}")
        return
    path.write_text(text, encoding="utf-8", newline="\n")
    print(f"{'updated' if old is not None else 'created'} {path.relative_to(ROOT)}")


async def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m provisioning.export")
    parser.add_argument("--upstream", metavar="TEMPLATE_NAME")
    args = parser.parse_args()

    settings = get_settings()
    admin = settings.engine_token
    if not admin:
        raise SystemExit("pass the admin token: -e ENGINE_TOKEN=...")

    async with ZabbixClient(settings.engine_url) as client:
        async def export(kind: str, ids: list[str]) -> str:
            return await client.call(
                "configuration.export", {"options": {kind: ids}, "format": "yaml"}, token=admin
            )

        if args.upstream:
            found = await client.call(
                "template.get",
                {"output": ["templateid", "host"], "filter": {"host": [args.upstream]}},
                token=admin,
            )
            if not found:
                raise SystemExit(f"template {args.upstream!r} not found")
            _write(UPSTREAM / _filename(args.upstream), await export("templates", [found[0]["templateid"]]))
            return

        templates = await client.call(
            "template.get",
            {"output": ["templateid", "host"], "search": {"host": TEMPLATE_PREFIX}, "startSearch": True},
            token=admin,
        )
        for t in templates:
            _write(OURS / "templates" / _filename(t["host"]), await export("templates", [t["templateid"]]))

        names = [d.technical_name for d in load_inventory()]
        if not names:
            # An empty filter is no filter: host.get would return every host.
            return
        hosts = await client.call(
            "host.get", {"output": ["hostid", "host"], "filter": {"host": names}}, token=admin
        )
        for h in hosts:
            _write(OURS / "hosts" / _filename(h["host"]), await export("hosts", [h["hostid"]]))


if __name__ == "__main__":
    asyncio.run(main())