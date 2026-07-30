# mojo-h11

`mojo-h11` is a Mojo-accelerated receive path for
[h11](https://github.com/python-hyper/h11), the sans-I/O HTTP/1.1 state
machine. Its `mojo_h11` Python API mirrors h11 0.16: existing code can change
the import and keep the same event classes, sentinels, method signatures, wire
output, and exception behavior.

```python
import mojo_h11 as h11

connection = h11.Connection(h11.SERVER)
connection.receive_data(
    b"GET /health HTTP/1.1\r\nHost: example.com\r\n\r\n"
)

request = connection.next_event()
end = connection.next_event()
assert request.method == b"GET"
assert request.target == b"/health"
assert isinstance(end, h11.EndOfMessage)

wire = connection.send(h11.Response(status_code=204, headers=[]))
wire += connection.send(h11.EndOfMessage())
print(wire)
```

## Coverage

`mojo_h11` re-exports h11 0.16's complete public API. Its only replacement
class is `Connection`, which subclasses h11's implementation and changes its
private receive buffer. The test suite proves the exported names and
signatures match and exercises:

- `Connection.receive_data`, `next_event`, `send`,
  `send_with_data_passthrough`, `send_failed`, `start_next_cycle`, state
  properties, `trailing_data`, and 100-continue state
- request and response parsing, fixed-length and chunked bodies, trailers,
  informational responses, and sending events
- keep-alive cycles, HTTP/1.0 close framing, CONNECT request parsing, Upgrade
  pausing and trailing data, EOF, fragmentation, incomplete-event limits, and
  local and remote protocol errors
- every public event type, role/state sentinel, `NEED_DATA`, and `PAUSED`

The native portion deliberately covers byte delimiter scanning: finding CRLF
chunk lines and the end of a request, response, or trailer header block. Those
are linear byte loops and a sensible fit for Mojo. The transition tables,
event validation, header normalization, and wire writers remain h11's mature
Python implementation. `h11>=0.16` is therefore a runtime dependency, not
only a test oracle. This is an accelerator and compatibility layer, not a
vendored fork or a claim that every line of h11 benefits from native code.

Networking, HTTP/2, TLS, URL routing, cookie parsing, decompression, and
application semantics are outside h11's scope and are likewise not provided
here.

## Install

The repository pins its own Mojo nightly:

```bash
pixi install
pixi run build
pixi run test
```

Run the usage example from the checkout after building. `PYTHONPATH=python` is
set by Pixi, and the shared library is written to
`dist/libmojo-h11.so`. Set `MOJO_H11_LIB` to use a library at another path.

## Performance

Measured with `pixi run bench` on a dual-socket Intel Xeon E5-2697 v4 system
(72 logical CPUs), Linux 6.8.0-136-generic, x86-64, glibc 2.39. Each value is
the best of three runs and reports time per complete operation. The same h11
0.16 event types and state transition implementation are used on both sides.

| case | mojo-h11 | h11 0.16 | relative |
| --- | ---: | ---: | ---: |
| parse minimal request | 33.44 us/op | 38.56 us/op | 1.15x faster |
| parse request with 100 headers | 291.64 us/op | 276.59 us/op | 1.05x slower |
| parse 12 KiB fragmented header | 176.23 us/op | 174.94 us/op | 1.01x slower |
| parse 256 KiB chunked response | 459.13 us/op | 531.71 us/op | 1.16x faster |
| scan and split 62 KiB header block | 135.64 us/op | 160.47 us/op | 1.18x faster |

Mojo wins three of the five cases in this run, by up to 1.18x. It is 1.05x
and 1.01x slower in the other two cases. The benchmark intentionally includes
those losses. Run `pixi run bench` to reproduce the table under the
machine-wide benchmark lock.

There is no parallel or GPU path. These delimiter scanners do roughly one byte
load and one or two comparisons per input byte, far below the arithmetic
intensity needed to repay thread-launch or host/device-transfer overhead.

## How it works

`Connection` subclasses h11's public connection and replaces only its private
receive buffer. The replacement has the same extraction contract and keeps
the same incremental search offsets, so fragmented input is scanned once
instead of repeatedly from the beginning.

Python owns one contiguous `bytearray`. Header-block scans under 1 KiB use
CPython's in-process byte search to avoid fixed FFI overhead. Larger
header-block scans pass a zero-copy writable buffer address to Mojo, which
checks a full byte SIMD vector per iteration and finishes with a scalar tail.
CRLF line scans also use Mojo. A live ctypes buffer export pins the allocation
for each native call, including while ctypes releases the GIL. The single Mojo
compilation unit reconstructs the address as
`UnsafePointer[UInt8, AnyOrigin[mut=True]]` and returns an index. Mojo never
allocates, retains, or frees the buffer. When extraction consumes the complete
buffer, Python transfers the existing `bytearray` instead of slicing and
copying it.

The ABI functions use `@export("name")` and `abi("C")`; the build script emits
one shared library:

```text
Python Connection
      |
      +-- h11 transition tables, events, validation, writers
      |
      +-- mojo_h11.ReceiveBuffer
              |
              +-- ctypes: address + length + search offset
                      |
                      +-- Mojo CRLF/header-boundary scan
```

## Development

```bash
pixi run build
pixi run test
pixi run bench
```

The test suite checks behavior against the installed h11 0.16 package,
including every fragmentation boundary for representative requests and
byte-at-a-time chunked input with trailers. Benchmark output is printed as a
Markdown table for direct comparison.

## License

MIT
