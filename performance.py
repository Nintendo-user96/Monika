# performance.py
import asyncio, functools, tracemalloc, gc, psutil, os, time
from typing import Callable, Coroutine, Optional, Any

# Start memory tracking
tracemalloc.start()

# ✅ Background task runner/decorator
def background_task(func: Callable[..., Coroutine[Any, Any, Any]] | Coroutine, interval: Optional[int] = None):
    """
    Run a coroutine in the background.
    - If used as a decorator: @background_task
    - If passed a coroutine: background_task(my_coro())
    - If interval is set: repeats every X seconds
    """

    async def loop(coro_func: Callable[..., Coroutine], *args, **kwargs):
        while True:
            try:
                await coro_func(*args, **kwargs)
            except Exception as e:
                print(f"[BackgroundTask Error] {coro_func.__name__}: {e}")
            if interval is None:
                break  # run once
            await asyncio.sleep(interval)

    # Case 1: Used as a decorator on an async function
    if asyncio.iscoroutinefunction(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return asyncio.create_task(loop(func, *args, **kwargs))
        return wrapper

    # Case 2: Passed a coroutine instance directly
    elif asyncio.iscoroutine(func):
        async def run_once():
            try:
                await func
            except Exception as e:
                print(f"[BackgroundTask Error] Direct coroutine: {e}")
        return asyncio.create_task(run_once())

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
def cleanup_memory():
    """Force cleanup of garbage and tracemalloc traces."""
    gc.collect()
    tracemalloc.clear_traces()
    print("[Perf] Manual memory cleanup triggered.")

# ✅ Async cleanup if you want to `await` it
async def async_cleanup_memory():
    cleanup_memory()

# ✅ Event loop lag monitor
@background_task
async def monitor_event_loop(threshold: float = 0.25):
    """Warn if the event loop lags more than threshold seconds."""
    while True:
        start = time.time()
        await asyncio.sleep(1)
        delay = time.time() - start - 1
        if delay > threshold:
            print(f"[Perf Warning] Event loop lag detected: {delay:.3f}s")
