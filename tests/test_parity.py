from __future__ import annotations

import inspect
import ctypes

import h11
import pytest

import mojo_h11
from mojo_h11._receivebuffer import ReceiveBuffer as MojoReceiveBuffer
from mojo_h11 import _lib
from mojo_h11._lib import find_crlf, find_headers_end
from h11._receivebuffer import ReceiveBuffer as PythonReceiveBuffer


def drain(module, role, wire, cuts=()):
    connection = module.Connection(role)
    events = []
    offset = 0
    for end in (*cuts, len(wire)):
        connection.receive_data(wire[offset:end])
        offset = end
        while True:
            event = connection.next_event()
            if event is module.NEED_DATA or event is module.PAUSED:
                break
            events.append(event)
    return events, connection


def event_view(event):
    fields = {}
    for name in ("method", "target", "status_code", "reason", "http_version"):
        if hasattr(event, name):
            fields[name] = getattr(event, name)
    if hasattr(event, "headers"):
        fields["headers"] = list(event.headers)
    if hasattr(event, "data"):
        fields["data"] = bytes(event.data)
        fields["chunk_start"] = event.chunk_start
        fields["chunk_end"] = event.chunk_end
    return type(event), fields


def assert_event_parity(ours, theirs):
    assert [event_view(x) for x in ours] == [event_view(x) for x in theirs]


def test_public_surface_and_signature():
    assert set(mojo_h11.__all__) == set(h11.__all__)
    assert inspect.signature(mojo_h11.Connection) == inspect.signature(h11.Connection)
    for name in h11.__all__:
        if name != "Connection":
            assert getattr(mojo_h11, name) is getattr(h11, name)


@pytest.mark.parametrize(
    "wire",
    [
        b"GET / HTTP/1.1\r\nHost: example.com\r\n\r\n",
        b"POST /submit?q=1 HTTP/1.1\nHost: example.com\nContent-Length: 0\n\n",
        b"OPTIONS * HTTP/1.0\r\nUser-Agent: parity\r\n\r\n",
        b"CONNECT example.com:443 HTTP/1.1\r\nHost: example.com\r\n\r\n",
    ],
)
def test_request_parity_at_every_fragment_boundary(wire):
    for cut in range(1, len(wire)):
        ours, ours_conn = drain(mojo_h11, mojo_h11.SERVER, wire, (cut,))
        theirs, their_conn = drain(h11, h11.SERVER, wire, (cut,))
        assert_event_parity(ours, theirs)
        assert ours_conn.states == their_conn.states
        assert ours_conn.their_http_version == their_conn.their_http_version


def test_one_byte_fragmentation_request():
    wire = (
        b"POST /upload HTTP/1.1\r\n"
        b"Host: example.com\r\n"
        b"Content-Length: 5\r\n"
        b"X-Test: a\r\n\r\nhello"
    )
    cuts = tuple(range(1, len(wire)))
    ours, ours_conn = drain(mojo_h11, mojo_h11.SERVER, wire, cuts)
    theirs, their_conn = drain(h11, h11.SERVER, wire, cuts)
    assert_event_parity(ours, theirs)
    assert ours_conn.states == their_conn.states


@pytest.mark.parametrize(
    "wire",
    [
        b"HTTP/1.1 204 No Content\r\nDate: now\r\n\r\n",
        b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\nhello",
        b"HTTP/1.0 200 Old\r\nConnection: close\r\n\r\nbody",
        b"HTTP/1.1 201 Created\r\nContent-Length: 0\r\n\r\n",
    ],
)
def test_response_parity(wire):
    cuts = (1, len(wire) // 2, max(2, len(wire) - 1))
    cuts = tuple(sorted(set(x for x in cuts if x < len(wire))))
    ours, ours_conn = drain(mojo_h11, mojo_h11.CLIENT, wire, cuts)
    theirs, their_conn = drain(h11, h11.CLIENT, wire, cuts)
    assert_event_parity(ours, theirs)
    assert ours_conn.states == their_conn.states


def test_chunked_body_and_trailers_byte_by_byte():
    wire = (
        b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n"
        b"4;ignored=yes\r\nWiki\r\n5\r\npedia\r\n0\r\nX-Checksum: ok\r\n\r\n"
    )
    cuts = tuple(range(1, len(wire)))
    ours, ours_conn = drain(mojo_h11, mojo_h11.CLIENT, wire, cuts)
    theirs, their_conn = drain(h11, h11.CLIENT, wire, cuts)
    assert_event_parity(ours, theirs)
    assert ours_conn.states == their_conn.states


@pytest.mark.parametrize(
    "wire",
    [
        b" GET / HTTP/1.1\r\nHost: x\r\n\r\n",
        b"GET / HTTP/1.1\r\n\r\n",
        b"GET / HTTP/1.1\r\nBad Header: x\r\n\r\n",
        b"GET / HTTP/1.1\r\nHost: x\r\nContent-Length: 1, 2\r\n\r\n",
        b"GET / HTTP/1.1\r\nHost: x\r\nTransfer-Encoding: gzip\r\n\r\n",
        b"GET / HTTP/1.1\r\nHost: x\r\nX: value\x00\r\n\r\n",
    ],
)
def test_invalid_request_error_parity(wire):
    errors = []
    states = []
    for module in (mojo_h11, h11):
        connection = module.Connection(module.SERVER)
        connection.receive_data(wire)
        with pytest.raises(module.RemoteProtocolError) as caught:
            connection.next_event()
        errors.append((str(caught.value), caught.value.error_status_hint))
        states.append(connection.their_state)
    assert errors[0] == errors[1]
    assert states == [mojo_h11.ERROR, h11.ERROR]


@pytest.mark.parametrize(
    "event",
    [
        h11.Request(method="GET", target="/", headers=[("Host", "example.com")]),
        h11.Response(status_code=200, reason="OK", headers=[("Content-Length", "3")]),
        h11.InformationalResponse(status_code=103, headers=[("Link", "</x>")]),
        h11.Data(data=b"abc"),
        h11.EndOfMessage(),
        h11.ConnectionClosed(),
    ],
)
def test_event_types_are_exact(event):
    public_type = getattr(mojo_h11, type(event).__name__)
    assert public_type is type(event)


def test_send_fixed_length_conversation_parity():
    request = h11.Request(
        method="POST",
        target="/items",
        headers=[("Host", "example.com"), ("Content-Length", "5")],
    )
    events = [request, h11.Data(data=b"hello"), h11.EndOfMessage()]
    outputs = []
    states = []
    for module in (mojo_h11, h11):
        connection = module.Connection(module.CLIENT)
        outputs.append([connection.send(event) for event in events])
        states.append(connection.states)
    assert outputs[0] == outputs[1]
    assert states[0] == states[1]


def test_send_with_data_passthrough_and_send_failed():
    for module in (mojo_h11, h11):
        connection = module.Connection(module.CLIENT)
        request = module.Request(
            method="POST",
            target="/",
            headers=[("Host", "example.com"), ("Content-Length", "3")],
        )
        assert connection.send_with_data_passthrough(request) == [
            b"POST / HTTP/1.1\r\n",
            b"Host: example.com\r\n",
            b"Content-Length: 3\r\n",
            b"\r\n",
        ]
        payload = bytearray(b"abc")
        parts = connection.send_with_data_passthrough(module.Data(data=payload))
        assert parts == [payload]
        assert parts[0] is payload
        connection.send_failed()
        assert connection.our_state is module.ERROR


def test_server_chunked_send_parity():
    request_wire = b"GET /stream HTTP/1.1\r\nHost: example.com\r\n\r\n"
    response = h11.Response(status_code=200, headers=[("Server", "parity")])
    outputs = []
    for module in (mojo_h11, h11):
        connection = module.Connection(module.SERVER)
        connection.receive_data(request_wire)
        assert isinstance(connection.next_event(), h11.Request)
        assert isinstance(connection.next_event(), h11.EndOfMessage)
        outputs.append(
            [
                connection.send(response),
                connection.send(h11.Data(data=b"abc")),
                connection.send(h11.EndOfMessage(headers=[("X-End", "yes")])),
            ]
        )
    assert outputs[0] == outputs[1]
    assert b"Transfer-Encoding: chunked" in outputs[0][0]
    assert outputs[0][1] == b"3\r\nabc\r\n"


def test_keep_alive_two_cycles_parity():
    outputs = []
    states = []
    for module in (mojo_h11, h11):
        connection = module.Connection(module.SERVER)
        sent = []
        for target in (b"/one", b"/two"):
            connection.receive_data(
                b"GET " + target + b" HTTP/1.1\r\nHost: example.com\r\n\r\n"
            )
            assert isinstance(connection.next_event(), h11.Request)
            assert isinstance(connection.next_event(), h11.EndOfMessage)
            sent.append(
                connection.send(
                    h11.Response(status_code=204, headers=[("X-Cycle", target)])
                )
            )
            sent.append(connection.send(h11.EndOfMessage()))
            connection.start_next_cycle()
        outputs.append(sent)
        states.append(connection.states)
    assert outputs[0] == outputs[1]
    assert states[0] == states[1]


def test_upgrade_pause_and_trailing_data_parity():
    wire = (
        b"GET /chat HTTP/1.1\r\nHost: example.com\r\n"
        b"Connection: Upgrade\r\nUpgrade: websocket\r\n\r\nraw-protocol"
    )
    results = []
    for module in (mojo_h11, h11):
        connection = module.Connection(module.SERVER)
        connection.receive_data(wire)
        events = [connection.next_event(), connection.next_event(), connection.next_event()]
        results.append(
            ([event_view(x) if not isinstance(x, type) else x for x in events],
             connection.trailing_data, connection.states)
        )
    assert results[0] == results[1]
    assert results[0][1][0] == b"raw-protocol"


def test_state_properties_and_100_continue_parity():
    wire = (
        b"POST /upload HTTP/1.1\r\nHost: example.com\r\n"
        b"Content-Length: 1\r\nExpect: 100-continue\r\n\r\n"
    )
    results = []
    for module in (mojo_h11, h11):
        connection = module.Connection(module.SERVER)
        connection.receive_data(wire)
        connection.next_event()
        results.append(
            (
                connection.our_state,
                connection.their_state,
                connection.states,
                connection.they_are_waiting_for_100_continue,
                connection.trailing_data,
            )
        )
    assert results[0] == results[1]
    assert results[0][3] is True


def test_incomplete_event_limit_and_local_error_parity():
    remote_errors = []
    local_errors = []
    for module in (mojo_h11, h11):
        connection = module.Connection(module.SERVER, max_incomplete_event_size=16)
        connection.receive_data(b"GET / HTTP/1.1\r\nHost: this-is-incomplete")
        with pytest.raises(module.RemoteProtocolError) as caught:
            connection.next_event()
        remote_errors.append((str(caught.value), caught.value.error_status_hint))

        connection = module.Connection(module.CLIENT)
        with pytest.raises(module.LocalProtocolError) as caught:
            connection.send(module.Data(data=b"not valid yet"))
        local_errors.append(str(caught.value))
    assert remote_errors[0] == remote_errors[1]
    assert local_errors[0] == local_errors[1]


def test_receive_eof_parity():
    for wire in (
        b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n",
        b"HTTP/1.0 200 OK\r\n\r\nsome body",
    ):
        results = []
        for module in (mojo_h11, h11):
            connection = module.Connection(module.CLIENT)
            connection.receive_data(wire)
            connection.receive_data(b"")
            events = []
            for _ in range(5):
                event = connection.next_event()
                events.append(event_view(event))
                if isinstance(event, h11.ConnectionClosed):
                    break
            results.append(events)
        assert results[0] == results[1]


@pytest.mark.parametrize(
    "payload",
    [
        b"\r\n",
        b"\n",
        b"a\r\n\r\n",
        b"a\nb\n\nrest",
        b"a\r\nb: c\r\n\r\nrest",
        b"a\nb: c\n\nrest",
    ],
)
def test_receive_buffer_line_parity(payload):
    outputs = []
    for cls in (MojoReceiveBuffer, PythonReceiveBuffer):
        buffer = cls()
        buffer += payload
        lines = buffer.maybe_extract_lines()
        outputs.append((lines, bytes(buffer)))
    assert outputs[0] == outputs[1]


def test_receive_buffer_incremental_scan_parity():
    ours = MojoReceiveBuffer()
    theirs = PythonReceiveBuffer()
    payload = b"1a;foo=bar\r\nremaining"
    for byte in payload:
        ours += bytes([byte])
        theirs += bytes([byte])
        left = ours.maybe_extract_next_line()
        right = theirs.maybe_extract_next_line()
        assert left == right
        assert bytes(ours) == bytes(theirs)


def test_simd_header_scan_tail_positions():
    for pad in range(80):
        data = bytearray(b"X: " + b"a" * pad + b"\r\n\r\nbody")
        assert find_headers_end(data) == pad + 7


def test_native_scanner_boundaries_and_buffer_lifetime():
    assert find_crlf(bytearray(b"x\r\n")) == 1
    assert find_crlf(bytearray(b"x\r\n"), 10**6) == -1
    assert find_headers_end(bytearray(b"\r\n")) == 2
    assert _lib._FIND_CRLF(0, 2, 0) == -1
    assert _lib._FIND_HEADERS_END(0, 1, 0) == -1

    data = bytearray(b"x\r\n")
    callback_type = ctypes.CFUNCTYPE(
        ctypes.c_int64, ctypes.c_int64, ctypes.c_int64, ctypes.c_int64
    )

    @callback_type
    def try_resize(_address, _length, _start):
        with pytest.raises(BufferError):
            data.extend(b"x")
        return 1

    assert _lib._call_scanner(try_resize, data, 0) == 1


def test_native_scanner_rejects_invalid_result():
    callback_type = ctypes.CFUNCTYPE(
        ctypes.c_int64, ctypes.c_int64, ctypes.c_int64, ctypes.c_int64
    )

    @callback_type
    def invalid_result(_address, length, _start):
        return length + 1

    with pytest.raises(RuntimeError, match="invalid index"):
        _lib._call_scanner(invalid_result, bytearray(b"x"), 0)


@pytest.mark.parametrize("size", [1023, 1024])
def test_header_scan_size_threshold_parity(size):
    payload = b"X: " + b"a" * (size - 7) + b"\r\n\r\n"
    outputs = []
    for cls in (MojoReceiveBuffer, PythonReceiveBuffer):
        buffer = cls()
        buffer += payload
        outputs.append((buffer.maybe_extract_lines(), bytes(buffer)))
    assert outputs[0] == outputs[1]
