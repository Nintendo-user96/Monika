import time
import asyncio
import os
from openai import AsyncOpenAI

class OpenAIKeyManager:
    def __init__(self, keys: list[str], cooldown_seconds: int = 15, wrap: bool = False, idle_rotate_minutes: int = 5):
        if not keys:
            raise RuntimeError("No OpenAI API keys were provided.")
        self.keys = {k: 0 for k in keys}  # key -> cooldown_until timestamp
        self.current_key = keys[0]
        self.cooldown_seconds = cooldown_seconds
        self.wrap = wrap
        self.used_keys = set()  # Track used keys for fair round-robin
        self.stats = {k: {"uses": 0, "cooldowns": 0, "last_used": 0} for k in keys}
        self.last_activity = time.time()
        self.idle_rotate_minutes = max(5, idle_rotate_minutes)  # minimum 5 minutes
        self._idle_task = None

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
        """Update last activity timestamp."""
        self.last_activity = time.time()

    async def validate_keys(self, batch_size: int = 5):
        """Test keys in batches, keep only valid ones."""
        print("[OpenAI] 🔄 Loading...")

        keys = list(self.keys.keys())
        valid = {}

        for i in range(0, len(keys), batch_size):
            batch = keys[i:i + batch_size]

            async def test_key(key):
                try:
                    client = AsyncOpenAI(api_key=key)
                    await client.models.list()
                    valid[key] = 0
                except Exception:
                    pass

            await asyncio.gather(*(test_key(k) for k in batch))

        self.keys = valid
        if not self.keys:
            raise RuntimeError("No valid OpenAI keys available.")
        self.current_key = next(iter(self.keys))
        print(f"[OpenAI] ✅ {len(self.keys)} keys are good and ready.")

    def get_client(self) -> AsyncOpenAI:
        now = time.time()
        local_hour = time.localtime(now).tm_hour

        # Detect scheduled break (11PM–4AM)
        if local_hour >= 23 or local_hour < 4:
            raise RuntimeError("[OpenAI] ⏸ Scheduled break time (11PM–4AM).")

        if now < self.keys[self.current_key]:
            raise RuntimeError(f"[OpenAI] Key {self.current_key[:8]} cooling down.")

        self.record_activity()
        return AsyncOpenAI(api_key=self.current_key)

    async def rotate(self):
        """Pick the least recently used available key (LRU strategy)."""
        now = time.time()
        available = [(k, until) for k, until in self.keys.items() if now >= until]

        if not available:
            # wait for soonest cooldown
            soonest_key, soonest_time = min(self.keys.items(), key=lambda kv: kv[1])
            wait_time = max(0, soonest_time - now)
            print(f"[OpenAI] ⏳ All keys cooling. Waiting {wait_time:.1f}s...")
            await asyncio.sleep(wait_time)
            return await self.rotate()

        # Sort by last used timestamp
        available.sort(key=lambda kv: self.stats[kv[0]]["last_used"])
        best_key = available[0][0]

        self.current_key = best_key
        self.stats[best_key]["last_used"] = now
        self.stats[best_key]["uses"] += 1
        print(f"[OpenAI] 🔄 Rotated to least-used key {best_key[:8]}...")

    def mark_cooldown(self, key):
        self.keys[key] = time.time() + self.cooldown_seconds
        self.stats[key]["cooldowns"] += 1
        print(f"[OpenAI] ⏳ Cooldown {self.cooldown_seconds}s for {key[:8]}...")

    def current_key_index(self) -> int:
        """Return the index (1-based) of the current key."""
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
        """Return list of keys that are not cooling down."""
        now = time.time()
        return [k for k, until in self.keys.items() if now >= until]

    def remaining_cooldowns(self):
        """Return dict of keys with their remaining cooldown times."""
        now = time.time()
        return {k: max(0, until - now) for k, until in self.keys.items()}

    def stats_summary(self):
        """Return summary stats for all keys."""
        return {
            k: {
                "uses": self.stats[k]["uses"],
                "cooldowns": self.stats[k]["cooldowns"],
                "last_used": self.stats[k]["last_used"]
            }
            for k in self.keys
        }

async def safe_call(manager: OpenAIKeyManager, fn, retries=20, global_cooldown=60):
    last_exc = None
    delay = 2  # initial backoff in seconds
    for attempt in range(retries):
        try:
            client = manager.get_client()
            return await fn(client)

        except Exception as e:
            last_exc = e
            err = str(e).lower()

            # Handle scheduled break
            if "scheduled break" in err:
                now = time.localtime()
                seconds_since_midnight = now.tm_hour * 3600 + now.tm_min * 60 + now.tm_sec
                if now.tm_hour >= 23:
                    wait_time = (24 * 3600 - seconds_since_midnight) + (4 * 3600)
                else:
                    wait_time = (4 * 3600) - seconds_since_midnight
                print(f"[OpenAI] 😴 Scheduled break. Waiting {wait_time/3600:.1f} hours...")
                await asyncio.sleep(wait_time)
                continue

            # Handle rate limits (429)
            if "429" in err or "rate limit" in err:
                manager.mark_cooldown(manager.current_key)
                await manager.rotate()
                if not manager.available_keys():
                    print(f"[OpenAI] ❌ All keys exhausted (rate-limited). Pausing {global_cooldown}s...")
                    await asyncio.sleep(global_cooldown)
                else:
                    print(f"[OpenAI] ⚠️ Rate limit hit. Backing off for {delay}s (attempt {attempt+1}/{retries})...")
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, 60)
                continue

            # Handle invalid keys
            if "401" in err or "invalid api key" in err or "400" in err:
                manager.mark_cooldown(manager.current_key)
                await manager.rotate()
                if not manager.available_keys():
                    raise RuntimeError("[OpenAI] 🚨 No valid keys available. Please update your keys.")
                continue

            break

    raise last_exc

# Load keys from environment
OPENAI_KEYS = [os.getenv(f"OPENAI_KEY_{i}") for i in range(1, 211) if os.getenv(f"OPENAI_KEY_{i}")]

# Shared manager instance (importable everywhere)
key_manager = OpenAIKeyManager(OPENAI_KEYS, cooldown_seconds=15, wrap=False, idle_rotate_minutes=5)
