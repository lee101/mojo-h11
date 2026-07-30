from __future__ import annotations

from typing import List, Optional, Union

from ._lib import find_crlf, find_headers_end


_SMALL_SCAN_LIMIT = 1024


class ReceiveBuffer:
    def __init__(self) -> None:
        self._data = bytearray()
        self._next_line_search = 0
        self._multiple_lines_search = 0

    def __iadd__(self, byteslike: Union[bytes, bytearray]) -> "ReceiveBuffer":
        self._data += byteslike
        return self

    def __bool__(self) -> bool:
        return bool(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __bytes__(self) -> bytes:
        return bytes(self._data)

    def _extract(self, count: int) -> bytearray:
        if count >= len(self._data):
            result = self._data
            self._data = bytearray()
        else:
            result = self._data[:count]
            del self._data[:count]
        self._next_line_search = 0
        self._multiple_lines_search = 0
        return result

    def maybe_extract_at_most(self, count: int) -> Optional[bytearray]:
        if not self._data or count <= 0:
            return None
        return self._extract(min(count, len(self._data)))

    def maybe_extract_next_line(self) -> Optional[bytearray]:
        index = find_crlf(self._data, self._next_line_search)
        if index < 0:
            self._next_line_search = len(self._data)
            return None
        return self._extract(index + 2)

    def maybe_extract_lines(self) -> Optional[List[bytearray]]:
        if self._data and self._data[0] == 10:
            self._extract(1)
            return []
        if len(self._data) >= 2 and self._data[0] == 13 and self._data[1] == 10:
            self._extract(2)
            return []
        if len(self._data) < _SMALL_SCAN_LIMIT:
            search_start = max(0, self._multiple_lines_search - 2)
            lf_end = self._data.find(b"\n\n", search_start)
            crlf_end = self._data.find(b"\n\r\n", search_start)
            if lf_end < 0:
                end = crlf_end + 3 if crlf_end >= 0 else -1
            elif crlf_end < 0:
                end = lf_end + 2
            else:
                end = min(lf_end + 2, crlf_end + 3)
        else:
            end = find_headers_end(self._data, self._multiple_lines_search)
        if end < 0:
            self._multiple_lines_search = max(0, len(self._data) - 2)
            return None
        if end <= 2:
            self._extract(end)
            return []
        block = self._extract(end)
        lines = block.split(b"\n")
        for line in lines:
            if line and line[-1] == 13:
                del line[-1]
        del lines[-2:]
        return lines

    def is_next_line_obviously_invalid_request_line(self) -> bool:
        return bool(self._data and self._data[0] < 0x21)
