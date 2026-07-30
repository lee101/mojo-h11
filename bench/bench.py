from __future__ import annotations

import math
import os
import platform
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "python"))

import h11  # noqa: E402
import mojo_h11  # noqa: E402
from h11._receivebuffer import ReceiveBuffer as H11Buffer  # noqa: E402
from mojo_h11._receivebuffer import ReceiveBuffer as MojoBuffer  # noqa: E402


def best_time(function, repeat=5):
    best = math.inf
    for _ in range(repeat):
        start = time.perf_counter()
        function()
        best = min(best, time.perf_counter() - start)
    return best


def parse_requests(module, wire, iterations):
    for _ in range(iterations):
        connection = module.Connection(module.SERVER)
        connection.receive_data(wire)
        connection.next_event()
        connection.next_event()


def parse_fragmented(module, wire, iterations):
    cut = len(wire) - 4
    for _ in range(iterations):
        connection = module.Connection(module.SERVER)
        connection.receive_data(wire[:cut])
        connection.next_event()
        connection.receive_data(wire[cut:])
        connection.next_event()
        connection.next_event()


def parse_chunked(module, wire, iterations):
    request = h11.Request(method="GET", target="/", headers=[("Host", "x")])
    for _ in range(iterations):
        connection = module.Connection(module.CLIENT)
        connection.send(request)
        connection.send(h11.EndOfMessage())
        connection.receive_data(wire)
        while True:
            event = connection.next_event()
            if event is module.NEED_DATA or event is module.PAUSED:
                break


def scan_blocks(buffer_type, wire, iterations):
    for _ in range(iterations):
        buffer = buffer_type()
        buffer += wire
        buffer.maybe_extract_lines()


def main():
    small = b"GET / HTTP/1.1\r\nHost: example.com\r\nUser-Agent: bench\r\n\r\n"
    many = (
        b"GET /headers HTTP/1.1\r\nHost: example.com\r\n"
        + b"".join(b"X-Field-%03d: abcdefghijklmnopqrstuvwxyz\r\n" % i for i in range(100))
        + b"\r\n"
    )
    large_line = (
        b"GET /large HTTP/1.1\r\nHost: example.com\r\nX-Pad: "
        + b"a" * 12_000
        + b"\r\n\r\n"
    )
    body = b"x" * (256 * 1024)
    chunked = (
        b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n"
        + b"%x\r\n" % len(body)
        + body
        + b"\r\n0\r\n\r\n"
    )
    scan_wire = b"start\r\n" + (b"X: " + b"a" * 120 + b"\r\n") * 500 + b"\r\n"

    cases = [
        (
            "parse minimal request",
            lambda: parse_requests(mojo_h11, small, 20_000),
            lambda: parse_requests(h11, small, 20_000),
            20_000,
        ),
        (
            "parse request with 100 headers",
            lambda: parse_requests(mojo_h11, many, 2_000),
            lambda: parse_requests(h11, many, 2_000),
            2_000,
        ),
        (
            "parse 12 KiB fragmented header",
            lambda: parse_fragmented(mojo_h11, large_line, 2_000),
            lambda: parse_fragmented(h11, large_line, 2_000),
            2_000,
        ),
        (
            "parse 256 KiB chunked response",
            lambda: parse_chunked(mojo_h11, chunked, 500),
            lambda: parse_chunked(h11, chunked, 500),
            500,
        ),
        (
            "scan and split 62 KiB header block",
            lambda: scan_blocks(MojoBuffer, scan_wire, 5_000),
            lambda: scan_blocks(H11Buffer, scan_wire, 5_000),
            5_000,
        ),
    ]

    mojo_h11.Connection(mojo_h11.SERVER)
    print(f"Machine: {platform.processor() or platform.machine()} ({platform.platform()})")
    print()
    print("| case | mojo-h11 | h11 0.16 | relative |")
    print("| --- | ---: | ---: | ---: |")
    for name, ours, upstream, operations in cases:
        ours_s = best_time(ours, repeat=3)
        upstream_s = best_time(upstream, repeat=3)
        ours_us = ours_s * 1e6 / operations
        upstream_us = upstream_s * 1e6 / operations
        ratio = upstream_s / ours_s
        label = f"{ratio:.2f}x faster" if ratio >= 1 else f"{1 / ratio:.2f}x slower"
        print(
            f"| {name} | {ours_us:.2f} us/op | {upstream_us:.2f} us/op | {label} |"
        )


if __name__ == "__main__":
    main()
