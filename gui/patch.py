from aiopubsub.loop import Loop
import asyncio
import contextlib
from typing import (
    Any,
    Awaitable,
    Callable,
    DefaultDict,
    Dict,
    Iterable,
    List,
    NamedTuple,
    Optional,
    Set,
    Tuple,
    Union,
)


async def _run(self) -> None:
    while self._is_running.is_set():
        self.task = asyncio.ensure_future(self.coro())
        try:
            await self.task
        except asyncio.CancelledError:
            # if self._is_running.is_set():
            #     self._logger.exception("Unhandled CancelledError in = %s", self.name)
            #     raise
            self._logger.debug("Stopping task = %s", self.name)
            break
        except Exception:  # pylint: disable=broad-except
            self._logger.exception(
                "Uncaught exception in _run in coroutine = %s", self.name
            )
            self._is_running.clear()
            raise
        if self.delay is not None:
            await asyncio.sleep(self.delay)


Loop._run = _run
