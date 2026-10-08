"""PushDecoderPort: raw Connector batch -> domain objects.

Schema (connector_schema) validates the lines; mapper translates them. This
class only glues the two, so api/hooks.py never sees an engine field.
"""

from __future__ import annotations

from app.domain.models import MetricPoint, Problem, ProblemResolution
from app.zabbix import mapper
from app.zabbix.connector_schema import ProblemLine, parse_events, parse_values


class ConnectorDecoder:
    def decode_values(self, body: bytes) -> list[MetricPoint]:
        points = (mapper.metric_from_value(line) for line in parse_values(body))
        return [p for p in points if p is not None]

    def decode_events(self, body: bytes) -> list[Problem | ProblemResolution]:
        return [
            mapper.problem_from_event(line)
            if isinstance(line, ProblemLine)
            else mapper.resolution_from_event(line)
            for line in parse_events(body)
        ]
