# performance.py
import asyncio, functools, tracemalloc, gc, psutil, os, time
from typing import Callable, Coroutine, Optional, Any

# Start memory tracking
tracemalloc.start()

# ✅ Background task runner/decorator
def background_task(
    func: Callable[..., Coroutine[Any, Any, Any]] | Coroutine[Any, Any, Any],
    interval: Optional[int] = None,
    name: Optional[str] = None
) -> Callable[..., asyncio.Task] | asyncio.Task:
    """
    Run a coroutine in the background with error safety.

    - As a decorator:
        @background_task
        async def my_task(): ...
        my_task()  # runs in background

    - With a coroutine instance:
        background_task(my_coro())

    - With interval (repeats every X seconds):
        background_task(my_coro, interval=60)
    """

    async def loop(coro_func: Callable[..., Coroutine], *args, **kwargs):
        while True:
            try:
                await coro_func(*args, **kwargs)
            except Exception as e:
                print(f"[BackgroundTask Error] {coro_func.__name__}: {e}")
            if interval is None:
                break
            await asyncio.sleep(interval)

    def safe_create(coro: Coroutine, task_name: str = None) -> asyncio.Task:
        task = asyncio.create_task(coro, name=task_name)
        def _done_callback(t: asyncio.Task):
            try:
                exc = t.exception()
                if exc:
                    print(f"[BackgroundTask Error] {task_name or t.get_name()}: {exc}")
            except asyncio.CancelledError:
                print(f"[BackgroundTask Cancelled] {task_name or t.get_name()}")
        task.add_done_callback(_done_callback)
        return task

    # Case 1: Used as decorator
    if asyncio.iscoroutinefunction(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return safe_create(loop(func, *args, **kwargs), name or func.__name__)
        return wrapper

    # Case 2: Coroutine instance
    elif asyncio.iscoroutine(func):
        return safe_create(func, name or getattr(func, "__name__", "anon_task"))

    else:
        raise TypeError("background_task expects a coroutine function or coroutine instance.")

# ✅ Async cache (TTL-based)
def cache_result(ttl: int = 300):
    """Cache results of a coroutine for `ttl` seconds."""
    def decorator(func: Callable[..., Coroutine[Any, Any, Any]]):
        cache = {}
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            key = (args, frozenset(kwargs.items()))
            now = time.time()
            if key in cache:
                result, timestamp = cache[key]
                if now - timestamp < ttl:
                    return result
            result = await func(*args, **kwargs)
            cache[key] = (result, now)
            return result
        return wrapper
    return decorator

# ✅ Memory usage
def get_memory_usage():
    process = psutil.Process(os.getpid())
    mem_info = process.memory_info()
    current = mem_info.rss / 1024 / 1024  # MB
    peak = tracemalloc.get_traced_memory()[1] / 1024 / 1024
    return round(current, 2), round(peak, 2)

# ✅ Cleanup (sync)
@background_task
async def cleanup_memory():
    """Force cleanup of garbage and tracemalloc traces."""
    gc.collect()
    tracemalloc.clear_traces()
    print("[Perf] Manual memory cleanup triggered.")

# ✅ Async cleanup if you want to `await` it
async def async_cleanup_memory():
    """Awaitable version of cleanup."""
    try:
        gc.collect()
        tracemalloc.clear_traces()
        print("[Perf] Async memory cleanup triggered.")
    except Exception as e:
        print(f"[Perf Error] async_cleanup_memory: {e}")

# ✅ Event loop lag monitor
@background_task
async def monitor_event_loop(interval: int = 60, lag_threshold: float = 0.25):
    """
    Monitor the event loop for lag.
    - interval: how often to check (seconds)
    - lag_threshold: max tolerated sleep drift in seconds
    """
    while True:
        try:
            start = time.time()
            await asyncio.sleep(1)
            delay = time.time() - start - 1
            if delay > lag_threshold:
                print(f"[Perf Warning] Event loop lag detected: {delay:.3f}s")
        except Exception as e:
            print(f"[Monitor Error] {e}")

        await asyncio.sleep(interval)
