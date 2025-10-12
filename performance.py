# performance.py
import asyncio, functools, tracemalloc, gc, psutil, os, time, base64, hashlib, json
from collections import OrderedDict
from typing import Callable, Coroutine, Any, Optional

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
def _to_primitive(obj):
    """Convert object to JSON-serializable primitives for stable key generation."""
    # Primitives
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj

    # Bytes -> base64 string
    if isinstance(obj, (bytes, bytearray)):
        return {"__bytes__": base64.b64encode(bytes(obj)).decode()}

    # Iterable containers
    if isinstance(obj, (list, tuple, set)):
        return [_to_primitive(x) for x in obj]

    if isinstance(obj, dict):
        return {str(k): _to_primitive(v) for k, v in sorted(obj.items(), key=lambda kv: str(kv[0]))}

    # Try common serializable helpers
    try:
        if hasattr(obj, "to_dict") and callable(obj.to_dict):
            return _to_primitive(obj.to_dict())
    except Exception:
        pass

    try:
        if hasattr(obj, "dict") and callable(obj.dict):
            return _to_primitive(obj.dict())
    except Exception:
        pass

    # If object has an 'id' attribute (like many SDK objects), use class:name:id
    try:
        if hasattr(obj, "id"):
            return {"__obj__": f"{obj.__class__.__name__}:{str(getattr(obj, 'id'))}"}
    except Exception:
        pass

    # Last resort: repr string (safe fallback)
    return {"__repr__": repr(obj)}


def _make_cache_key(args, kwargs) -> str:
    """Make a deterministic string key for (args, kwargs)."""
    payload = {
        "args": _to_primitive(args),
        "kwargs": _to_primitive(kwargs)
    }
    # stable JSON string
    s = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def cache_result(ttl: int = 300, max_size: Optional[int] = None):
    """
    Cache results of a coroutine for `ttl` seconds.
    Optional max_size enforces LRU eviction when cache grows bigger than max_size.
    Usage: @cache_result(ttl=60, max_size=200)
    """
    def decorator(func: Callable[..., Coroutine[Any, Any, Any]]):
        cache = OrderedDict()  # key -> (result, timestamp)

        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            key = _make_cache_key(args, kwargs)
            now = time.time()

            # hit & fresh
            if key in cache:
                result, ts = cache[key]
                if now - ts < ttl:
                    # move to end for LRU behavior
                    try:
                        cache.move_to_end(key)
                    except Exception:
                        pass
                    return result
                else:
                    # expired
                    try:
                        del cache[key]
                    except Exception:
                        pass

            # call and store
            result = await func(*args, **kwargs)
            cache[key] = (result, now)

            # enforce size limit
            if max_size is not None:
                while len(cache) > max_size:
                    cache.popitem(last=False)  # pop oldest

            return result

        # expose internals for debugging if needed
        wrapper._cache = cache
        wrapper._cache_ttl = ttl
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
