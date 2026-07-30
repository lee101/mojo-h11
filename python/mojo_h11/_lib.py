from __future__ import annotations

import ctypes
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LIB_PATH = os.environ.get("MOJO_H11_LIB", os.path.join(ROOT, "dist", "libmojo-h11.so"))
I = ctypes.c_int64


def _load() -> ctypes.CDLL:
    try:
        library = ctypes.CDLL(LIB_PATH)
    except OSError as exc:
        raise RuntimeError(
            f"cannot load {LIB_PATH}; run `pixi run build` first"
        ) from exc
    for name in ("mh11_find_crlf", "mh11_find_headers_end"):
        fn = getattr(library, name)
        fn.argtypes = [I, I, I]
        fn.restype = I
    return library


LIB = _load()
_FIND_CRLF = LIB.mh11_find_crlf
_FIND_HEADERS_END = LIB.mh11_find_headers_end


def _call_scanner(
    scanner: ctypes._CFuncPtr, data: bytearray, start: int
) -> int:
    # Keep the exported buffer alive for the whole native call. ctypes.CDLL
    # releases the GIL while calling Mojo; the live export prevents another
    # thread from resizing the bytearray and invalidating its address.
    view = (ctypes.c_ubyte * len(data)).from_buffer(data)
    result = int(scanner(ctypes.addressof(view), len(data), start))
    if result < -1 or result > len(data):
        raise RuntimeError(f"native scanner returned invalid index {result}")
    return result


def find_crlf(data: bytearray, start: int = 0) -> int:
    if len(data) < 2:
        return -1
    return _call_scanner(_FIND_CRLF, data, start)


def find_headers_end(data: bytearray, start: int = 0) -> int:
    if not data:
        return -1
    return _call_scanner(_FIND_HEADERS_END, data, start)
