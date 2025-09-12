# performance.py
import asyncio, functools, tracemalloc, gc, psutil, os, time
from typing import Callable, Coroutine

# Start memory tracking
tracemalloc.start()

# ✅ Background task wrapper
def background_task(func: Callable[..., Coroutine]) -> Callable[..., Coroutine]:
    """Run a coroutine in the background, suppressing errors."""
    async def wrapper(*args, **kwargs):
        try:
            await func(*args, **kwargs)
        except Exception as e:
            print(f"[BackgroundTask Error] {e}")
    return wrapper

# ✅ Async cache (TTL-based)
def cache_result(ttl: int = 300):
    """Cache results of a coroutine for `ttl` seconds."""
    def decorator(func: Callable):
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

# ✅ Cleanup
def cleanup_memory():
    gc.collect()
    tracemalloc.clear_traces()
    print("[Perf] Manual memory cleanup triggered.")

# ✅ Event loop lag monitor
async def monitor_event_loop(threshold: float = 0.25):
    """Warn if the event loop lags more than threshold seconds."""
    while True:
        start = time.time()
        await asyncio.sleep(1)
        delay = time.time() - start - 1
        if delay > threshold:
            print(f"[Perf Warning] Event loop lag detected: {delay:.3f}s")