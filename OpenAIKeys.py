import os
import time
import asyncio
from openai import AsyncOpenAI


class OpenAIKeyManager:
    def __init__(self, keys: list[str], cooldown_seconds: int = 15, idle_rotate_minutes: int = 5):
        if not keys:
            raise RuntimeError("No OpenAI API keys were provided.")

        # Active keys pool
        self.keys = {k: 0 for k in keys}  # key -> cooldown_until
        self.current_key = keys[0]
        self.cooldown_seconds = cooldown_seconds

        # Tracking stats
        self.stats = {
            k: {"uses": 0, "failures": 0, "cooldowns": 0, "last_used": 0, "health": 100}
            for k in keys
        }

        # Idle tracking
        self.last_activity = time.time()
        self.idle_rotate_minutes = max(5, idle_rotate_minutes)
        self._idle_task = None

        # Background rescan control
        self._all_keys = keys
        self._next_index = len(keys)

        # Optional event hooks
        self.on_all_keys_exhausted = None
        self.on_key_recovered = None

    # ---------------- Idle rotation ---------------- #

    def start_idle_rotator(self):
        """Start the idle rotation loop once an event loop is running."""
        if self._idle_task is None or self._idle_task.done():
            loop = asyncio.get_event_loop()
            self._idle_task = loop.create_task(self._idle_rotator())
            print("[OpenAI] 🔄 Idle rotator started.")

    async def _idle_rotator(self):
        """Background task that rotates keys when idle for too long."""
        while True:
            try:
                await asyncio.sleep(self.idle_rotate_minutes * 60)
                now = time.time()
                if now - self.last_activity >= self.idle_rotate_minutes * 60:
                    print("[OpenAI] 🔄 Idle detected, rotating key...")
                    await self.rotate()
            except Exception as e:
                print(f"[OpenAI] ⚠️ Idle rotator error: {e}")

    def record_activity(self):
        self.last_activity = time.time()

    # ---------------- Key handling ---------------- #

    def get_client(self) -> AsyncOpenAI:
        """Return an AsyncOpenAI client for the current key, enforcing cooldowns and scheduled breaks."""
        now = time.time()
        local_hour = time.localtime(now).tm_hour

        # Scheduled break (11PM → 6AM)
        if local_hour >= 23 or local_hour < 6:
            raise RuntimeError("[OpenAI] ⏸ Scheduled break time (11PM–6AM).")

        if now < self.keys[self.current_key]:
            raise RuntimeError(f"[OpenAI] Key {self.current_key[:8]} cooling down.")

        self.record_activity()
        return AsyncOpenAI(api_key=self.current_key)

    async def rotate(self):
        """Pick the least recently used available key (LRU)."""
        now = time.time()
        available = [(k, until) for k, until in self.keys.items() if now >= until]

        if not available:
            # all cooling down
            soonest_key, soonest_time = min(self.keys.items(), key=lambda kv: kv[1])
            wait_time = max(0, soonest_time - now)
            print(f"[OpenAI] ⏳ All keys cooling. Waiting {wait_time:.1f}s...")
            await asyncio.sleep(wait_time)
            return await self.rotate()

        # Sort by last used time
        available.sort(key=lambda kv: self.stats[kv[0]]["last_used"])
        best_key = available[0][0]

        self.current_key = best_key
        self.stats[best_key]["last_used"] = now
        self.stats[best_key]["uses"] += 1
        print(f"[OpenAI] 🔄 Rotated to least-used key {best_key[:8]}...")

    def mark_cooldown(self, key):
        """Put a key on cooldown."""
        self.keys[key] = time.time() + self.cooldown_seconds
        self.stats[key]["cooldowns"] += 1
        print(f"[OpenAI] ⏳ Cooldown {self.cooldown_seconds}s for {key[:8]}...")

    # ---------------- Reporting ---------------- #

    def current_key_index(self) -> int:
        """Return 1-based index of the current key."""
        keys = list(self.keys.keys())
        return keys.index(self.current_key) + 1

    def status(self):
        """Print status of all keys with cooldowns and usage stats."""
        now = time.time()
        for i, (k, until) in enumerate(self.keys.items(), start=1):
            cooldown_left = max(0, until - now)
            marker = "<-- current" if k == self.current_key else ""
            print(
                f"{i}. {k[:8]}... cooldown {cooldown_left:.1f}s, "
                f"uses={self.stats[k]['uses']}, cooldowns={self.stats[k]['cooldowns']} {marker}"
            )

    def available_keys(self):
        """Return keys that are not cooling down."""
        now = time.time()
        return [k for k, until in self.keys.items() if now >= until]

    def remaining_cooldowns(self):
        """Return cooldown times for keys."""
        now = time.time()
        return {k: max(0, until - now) for k, until in self.keys.items()}

    def stats_summary(self):
        """Return summary of all key usage stats."""
        return {
            k: {
                "uses": self.stats[k]["uses"],
                "failures": self.stats[k]["failures"],
                "cooldowns": self.stats[k]["cooldowns"],
                "last_used": self.stats[k]["last_used"],
                "health": self.stats[k]["health"],
            }
            for k in self.keys
        }


# ---------------- Safe call helper ---------------- #

async def openai_safe_call(manager: OpenAIKeyManager, fn, retries=20, global_cooldown=60):
    last_exc = None
    delay = 2  # backoff start

    for attempt in range(retries):
        try:
            client = manager.get_client()
            return await fn(client)

        except Exception as e:
            last_exc = e
            err = str(e).lower()

            if "scheduled break" in err:
                now = time.localtime()
                seconds_since_midnight = now.tm_hour * 3600 + now.tm_min * 60 + now.tm_sec
                if now.tm_hour >= 23:
                    wait_time = (24 * 3600 - seconds_since_midnight) + (6 * 3600)
                else:
                    wait_time = (6 * 3600) - seconds_since_midnight
                print(f"[OpenAI] 😴 Scheduled break. Waiting {wait_time/3600:.1f} hours...")
                await asyncio.sleep(wait_time)
                continue

            if "429" in err or "rate limit" in err:
                manager.mark_cooldown(manager.current_key)
                await manager.rotate()
                if not manager.available_keys():
                    print(f"[OpenAI] ❌ All keys exhausted. Pausing {global_cooldown}s...")
                    await asyncio.sleep(global_cooldown)
                else:
                    print(f"[OpenAI] ⚠️ Rate limit hit. Backoff {delay}s (attempt {attempt+1}/{retries})...")
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, 60)
                continue

            if "401" in err or "invalid api key" in err or "400" in err:
                manager.mark_cooldown(manager.current_key)
                await manager.rotate()
                if not manager.available_keys():
                    raise RuntimeError("[OpenAI] 🚨 No valid keys available.")
                continue

            if "billing_not_active" in err:
                print(f"[OpenAI] 🚫 Key {manager.current_key[:8]} billing inactive. Dropping...")
                manager.keys.pop(manager.current_key, None)
                if not manager.keys:
                    raise RuntimeError("[OpenAI] 🚨 No active-billing keys left.")
                await manager.rotate()
                continue

            break

    raise last_exc


# ---------------- Key scanning ---------------- #

async def scan_all_keys(batch_size: int = 5, preload: int = 5) -> list[str]:
    """Scan env keys and return a preload pool of valid keys."""
    print("[OpenAI] 🔄 Scanning all keys...")
    all_keys = [os.getenv(f"OPENAI_KEY_{i}") for i in range(1, 211)]
    all_keys = [k for k in all_keys if k]

    valid_keys = []

    for i in range(0, len(all_keys), batch_size):
        batch = all_keys[i:i + batch_size]

        async def test_key(key):
            try:
                client = AsyncOpenAI(api_key=key)
                await client.models.list()
                print(f"[OpenAI] ✅ Key {key[:8]} works")
                valid_keys.append(key)
            except Exception as e:
                print(f"[OpenAI] ❌ Key {key[:8]} invalid ({e})")

        await asyncio.gather(*(test_key(k) for k in batch))

        if len(valid_keys) >= preload:
            break

    if not valid_keys:
        raise RuntimeError("[OpenAI] 🚨 No valid keys found.")
    print(f"[OpenAI] ✅ Using {len(valid_keys)} preload keys (from {len(all_keys)} total).")
    return valid_keys


# ---------------- Manager Init ---------------- #

key_manager = None

async def init_key_manager():
    global key_manager
    preload_keys = await scan_all_keys(batch_size=5, preload=5)
    key_manager = OpenAIKeyManager(preload_keys, cooldown_seconds=15, idle_rotate_minutes=5)
    key_manager._all_keys = preload_keys
    key_manager._next_index = len(preload_keys)
    print(f"[OpenAI] ✅ KeyManager initialized with {len(preload_keys)} keys.")
    return key_manager


async def periodic_rescan(interval_hours=6):
    """Rescan all keys periodically and merge into pool."""
    global key_manager
    while True:
        await asyncio.sleep(interval_hours * 3600)
        print("[OpenAI] 🔄 Background rescan starting...")
        new_keys = await scan_all_keys(batch_size=5, preload=999)
        for key in new_keys:
            if key not in key_manager.keys:
                key_manager.keys[key] = 0
                key_manager.stats[key] = {"uses": 0, "failures": 0,
                                          "cooldowns": 0, "last_used": 0, "health": 100}
        key_manager._all_keys = list(set(key_manager._all_keys) | set(new_keys))
        print(f"[OpenAI] ✅ Rescan complete. Total keys now: {len(key_manager._all_keys)}")
