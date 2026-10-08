"""Product-owned enumerations.

Engine values are translated into these in the engine package's mapper only;
nothing outside it may know the engine's numbering.
"""

from __future__ import annotations

from enum import IntEnum, StrEnum


class Severity(IntEnum):
    """Ordered, so filters can say ``severity >= Severity.MAJOR``."""

    INFO = 0
    WARNING = 1
    MINOR = 2
    MAJOR = 3
    CRITICAL = 4


class DeviceStatus(StrEnum):
    UP = "up"
    DOWN = "down"
    UNKNOWN = "unknown"
    MAINTENANCE = "maintenance"
    DISABLED = "disabled"


class DeviceKind(StrEnum):
    CORE_SWITCH = "core_switch"
    ACCESS_SWITCH = "access_switch"
    ACCESS_POINT = "access_point"
    SERVER = "server"
    OTHER = "other"
