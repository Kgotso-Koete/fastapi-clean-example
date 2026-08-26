import asyncio
import threading
from collections.abc import Iterator

import pytest

from app.main.worker import loop_runtime


@pytest.fixture(autouse=True)
def _reset_loop_runtime() -> Iterator[None]:
    """
    loop_runtime keeps its state (the running loop/thread) in module-level
    globals, since there's meant to be exactly one persistent loop per
    worker *process*. That global state would otherwise leak between
    tests, so every test starts and ends with the loop stopped.
    """
    loop_runtime.stop_loop()
    yield
    loop_runtime.stop_loop()


class TestRunCoroutineBeforeLoopIsStarted:
    def test_raises_runtime_error(self) -> None:
        async def _noop() -> None:
            return None

        # Build the coroutine but don't await it -- run_coroutine() should
        # reject it before ever scheduling it on a loop.
        coro = _noop()
        try:
            with pytest.raises(RuntimeError, match="not running"):
                loop_runtime.run_coroutine(coro)
        finally:
            # Close the never-awaited coroutine so Python doesn't print a
            # "coroutine was never awaited" warning for it.
            coro.close()


class TestStartLoop:
    def test_run_coroutine_executes_on_the_started_loop_and_returns_its_result(self) -> None:
        loop_runtime.start_loop()

        async def _add(a: int, b: int) -> int:
            return a + b

        result = loop_runtime.run_coroutine(_add(2, 3))

        assert result == 5

    def test_coroutine_runs_on_a_different_thread_than_the_caller(self) -> None:
        # The whole point of loop_runtime is running task coroutines on a
        # dedicated background thread, not the Celery worker's own thread --
        # this proves that's actually happening.
        loop_runtime.start_loop()
        caller_thread = threading.current_thread()

        async def _current_thread() -> threading.Thread:
            return threading.current_thread()

        worker_thread = loop_runtime.run_coroutine(_current_thread())

        assert worker_thread is not caller_thread

    def test_calling_start_loop_twice_returns_the_same_loop(self) -> None:
        # start_loop() must be idempotent: Celery's worker_process_init
        # signal could in principle fire more than once, and we only ever
        # want one persistent loop per process.
        loop1 = loop_runtime.start_loop()
        loop2 = loop_runtime.start_loop()

        assert loop1 is loop2


class TestSpawn:
    def test_raises_runtime_error_before_loop_is_started(self) -> None:
        async def _noop() -> None:
            return None

        coro = _noop()
        try:
            with pytest.raises(RuntimeError, match="not running"):
                loop_runtime.spawn(coro)
        finally:
            coro.close()

    def test_does_not_block_the_calling_thread(self) -> None:
        # spawn()'s whole point is starting a coroutine that keeps running
        # (e.g. a forever loop) without the caller waiting on it -- unlike
        # run_coroutine(), calling it must return immediately even though
        # the coroutine it schedules never finishes on its own.
        loop_runtime.start_loop()
        started = threading.Event()

        async def _run_until_cancelled() -> None:
            started.set()
            await asyncio.Event().wait()

        loop_runtime.spawn(_run_until_cancelled())

        assert started.wait(timeout=1)

    def test_cancel_stops_the_coroutine_mid_run(self) -> None:
        loop_runtime.start_loop()
        started = threading.Event()
        cancelled = threading.Event()

        async def _run_until_cancelled() -> None:
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        future = loop_runtime.spawn(_run_until_cancelled())
        assert started.wait(timeout=1)

        future.cancel()

        assert cancelled.wait(timeout=1)


class TestStopLoop:
    def test_run_coroutine_raises_again_after_stop(self) -> None:
        loop_runtime.start_loop()
        loop_runtime.stop_loop()

        async def _noop() -> None:
            return None

        coro = _noop()
        try:
            with pytest.raises(RuntimeError, match="not running"):
                loop_runtime.run_coroutine(coro)
        finally:
            coro.close()

    def test_stop_loop_before_any_start_does_not_raise(self) -> None:
        # Safe to call even if nothing was ever started (e.g. a worker
        # process shutting down before worker_process_init ever ran).
        loop_runtime.stop_loop()
