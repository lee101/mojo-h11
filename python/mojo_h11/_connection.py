from typing import Type

from h11._connection import Connection as _Connection
from h11._util import Sentinel

from ._receivebuffer import ReceiveBuffer


class Connection(_Connection):
    def __init__(
        self,
        our_role: Type[Sentinel],
        max_incomplete_event_size: int = 16 * 1024,
    ) -> None:
        super().__init__(our_role, max_incomplete_event_size)
        self._receive_buffer = ReceiveBuffer()
