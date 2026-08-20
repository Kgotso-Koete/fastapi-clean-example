import asyncio
import threading
from collections.abc import Coroutine
from typing import Any, TypeVar

T = TypeVar("T")

# Module-level state: exactly one persistent event loop (and the thread
# running it) for the entire life of this worker *process*. Not per task --
# see run_coroutine()'s docstring for why that distinction matters.
_loop: asyncio.AbstractEventLoop | None = None
_thread: threading.Thread | None = None


def start_loop() -> asyncio.AbstractEventLoop:
    """
    Starts one persistent event loop for the life of this worker process,
    running in a dedicated background thread. Idempotent: calling it again
    while already running just returns the existing loop.

    Every task's coroutine runs on THIS loop (see run_coroutine), rather
    than each task calling asyncio.run() on a fresh loop of its own. That
    matters the moment a background handler touches an async resource that
    is cached for the whole process -- e.g. the SQLAlchemy AsyncEngine,
    which is built once at Scope.APP and bound to whichever event loop
    existed when it was first used. A fresh asyncio.run() per task would
    eventually raise "Future attached to a different loop" the first time
    two different tasks' fresh loops both touched that same cached engine.
    Building one loop per process avoids this by construction.
    """
    global _loop, _thread
    if _loop is not None:
        return _loop
    loop = asyncio.new_event_loop()
    # run_forever() blocks, so it needs its own thread -- otherwise nothing
    # else in this process could ever run once the loop starts.
    thread = threading.Thread(target=loop.run_forever, name="worker-event-loop", daemon=True)
    thread.start()
    _loop, _thread = loop, thread
    return loop


def stop_loop() -> None:
    """Stops the persistent loop and its thread, if one is running. Safe to call even if nothing was ever started."""
    global _loop, _thread
    if _loop is None:
        return
    # call_soon_threadsafe is required here (rather than loop.stop()
    # directly) because this function runs on the CALLING thread, not the
    # loop's own thread -- loop.stop() must be scheduled to run on the loop
    # itself.
    _loop.call_soon_threadsafe(_loop.stop)
    if _thread is not None:
        _thread.join(timeout=5)
    _loop, _thread = None, None


def run_coroutine[T](coro: Coroutine[Any, Any, T]) -> T:
    """
    Runs `coro` on the persistent worker loop (started by start_loop()),
    blocking the calling thread until it completes, and returns its result.
    This is how a synchronous Celery task body gets to run async code: the
    Celery task calls this instead of `await`ing directly (Celery's default
    worker pool has no async support of its own).
    """
    loop = _loop
    if loop is None:
        raise RuntimeError("Worker event loop is not running. Call start_loop() first.")
    # run_coroutine_threadsafe schedules the coroutine on `loop` (which is
    # running on a different thread) and gives back a concurrent.futures
    # Future; .result() blocks this (calling) thread until it's done.
    return asyncio.run_coroutine_threadsafe(coro, loop).result()
