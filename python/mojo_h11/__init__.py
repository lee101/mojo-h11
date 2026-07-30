from __future__ import annotations

from h11 import (
    CLIENT,
    CLOSED,
    DONE,
    ERROR,
    IDLE,
    MIGHT_SWITCH_PROTOCOL,
    MUST_CLOSE,
    NEED_DATA,
    PAUSED,
    SEND_BODY,
    SEND_RESPONSE,
    SERVER,
    SWITCHED_PROTOCOL,
    ConnectionClosed,
    Data,
    EndOfMessage,
    Event,
    InformationalResponse,
    LocalProtocolError,
    ProtocolError,
    RemoteProtocolError,
    Request,
    Response,
)
from h11._version import __version__

from ._connection import Connection

PRODUCT_ID = "mojo-h11/" + __version__

__all__ = (
    "Connection",
    "NEED_DATA",
    "PAUSED",
    "ConnectionClosed",
    "Data",
    "EndOfMessage",
    "Event",
    "InformationalResponse",
    "Request",
    "Response",
    "CLIENT",
    "CLOSED",
    "DONE",
    "ERROR",
    "IDLE",
    "MUST_CLOSE",
    "SEND_BODY",
    "SEND_RESPONSE",
    "SERVER",
    "SWITCHED_PROTOCOL",
    "ProtocolError",
    "LocalProtocolError",
    "RemoteProtocolError",
)
