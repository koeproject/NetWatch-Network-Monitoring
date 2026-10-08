"""Schemas for the Connector's NDJSON push (Zabbix 7.0.29).

Written from the real payloads in lab/ndjson-sink/captured/ — see
docs/connector-payload.md for every field and where it was observed. Do not
add a field here that has not been seen in a captured line.

- ``extra="ignore"``: a patch release may add members; that must not break
  ingest.
- Parsing is per line. A bad line is logged and skipped; it never drops the
  rest of the batch.
"""

from __future__ import annotations

import json
import logging
from typing import Annotated, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

log = logging.getLogger(__name__)


class _Line(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


class HostRef(_Line):
    host: str  # technical name, unique in the engine
    name: str  # visible name


class Tag(_Line):
    tag: str
    value: str = ""


class ValueLine(_Line):
    """One item value (connector data_type 0)."""

    host: HostRef
    groups: list[str] = []
    item_tags: list[Tag] = []
    itemid: int
    name: str
    clock: int
    ns: int = 0
    # int before float: keeps unsigned counters exact (a float JSON value such
    # as 0 may still arrive as a JSON integer — both are accepted).
    value: int | float | str
    # The item's value_type: 0 float, 1 character, 2 log, 3 unsigned, 4 text.
    type: int


class ProblemLine(_Line):
    """A problem started (event ``value`` 1)."""

    value: Literal[1]
    eventid: int
    clock: int
    ns: int = 0
    name: str
    severity: int
    hosts: list[HostRef]
    groups: list[str] = []
    tags: list[Tag] = []


class RecoveryLine(_Line):
    """A problem ended (event ``value`` 0). Carries no name, host or severity:
    ``p_eventid`` points back at the problem's ``eventid``."""

    value: Literal[0]
    eventid: int
    p_eventid: int
    clock: int
    ns: int = 0


EventLine = Annotated[ProblemLine | RecoveryLine, Field(discriminator="value")]

VALUE_LINE = TypeAdapter(ValueLine)
EVENT_LINE: TypeAdapter[ProblemLine | RecoveryLine] = TypeAdapter(EventLine)

# value_type numbers that hold a number (float, unsigned).
NUMERIC_VALUE_TYPES = frozenset({0, 3})

T = TypeVar("T")


def parse_ndjson(body: bytes, adapter: TypeAdapter[T], *, kind: str) -> list[T]:
    """Parse every non-empty line; log and skip the ones that do not validate."""
    parsed: list[T] = []
    for number, raw in enumerate(body.splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            parsed.append(adapter.validate_python(json.loads(raw)))
        except (ValueError, ValidationError) as exc:
            # json.JSONDecodeError is a ValueError.
            log.warning(
                "connector %s line %d skipped: %s | %.200r",
                kind,
                number,
                str(exc).splitlines()[0],
                raw,
            )
    return parsed


def parse_values(body: bytes) -> list[ValueLine]:
    return parse_ndjson(body, VALUE_LINE, kind="value")


def parse_events(body: bytes) -> list[ProblemLine | RecoveryLine]:
    return parse_ndjson(body, EVENT_LINE, kind="event")
