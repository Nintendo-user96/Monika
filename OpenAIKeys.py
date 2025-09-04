import os, time, asyncio
from openai import AsyncOpenAI

class OpenAIKeyManager:
    def __init__(self, keys: list[str], cooldown_seconds: int = 15, wrap: bool = False, idle_rotate_minutes: int = 5):
        if not keys:
            raise RuntimeError("No OpenAI API keys were provided.")
        self.keys = {k: 0 for k in keys}  # key -> cooldown_until
        self.current_key = keys[0]
        self.cooldown_seconds = cooldown_seconds
        self.wrap = wrap
        self.used_keys = set()
        self.stats = {k: {"uses": 0, "cooldowns": 0, "last_used": 0} for k in keys}
        self.last_activity = time.time()
        self.idle_rotate_minutes = max(5, idle_rotate_minutes)
        self._idle_task = None

    # ⬇️ NEW
    def refill_key(self, bad_key: str):
        """Replace a failed key with the next available from ALL_KEYS."""
        if not hasattr(self, "_all_keys"):
            return

        if self._next_index >= len(self._all_keys):
            print("[OpenAI] 🚨 No more spare keys available to refill.")
            return

        new_key = self._all_keys[self._next_index]
        self._next_index += 1

        if bad_key in self.keys:
            del self.keys[bad_key]
            del self.stats[bad_key]

        self.keys[new_key] = 0
        self.stats[new_key] = {"uses": 0, "cooldowns": 0, "last_used": 0}

        if self.current_key == bad_key:
            self.current_key = new_key

        print(f"[OpenAI] 🔄 Replaced bad key {bad_key[:8]}... with new key {new_key[:8]}...")

    def start_idle_rotator(self):
        if self._idle_task is None or self._idle_task.done():
            loop = asyncio.get_event_loop()
            self._idle_task = loop.create_task(self._idle_rotator())
            print("[OpenAI] 🔄 Idle rotator started.")

    async def _idle_rotator(self):
        while True:
            try:
                await asyncio.sleep(self.idle_rotate_minutes * 60)
                now = time.time()
                if now - self.last_activity >= self.idle_rotate_minutes * 60:
                    print("[OpenAI] 🔄 Idle detected, rotating key...")
                    await self.rotate(force=True)
            except Exception as e:
                print(f"[OpenAI] ⚠️ Idle rotator error: {e}")

    def record_activity(self):
        self.last_activity = time.time()

    async def validate_keys(self, batch_size: int = 5):
        """Test keys in batches and refill if bad keys are found."""
        print("[OpenAI] 🔄 Validating keys...")

        keys = list(self.keys.keys())
        valid = {}

        for i in range(0, len(keys), batch_size):
            batch = keys[i:i + batch_size]

            async def test_key(key):
                try:
                    client = AsyncOpenAI(api_key=key)
                    await client.models.list()
                    valid[key] = 0
                    print(f"[OpenAI] ✅ Valid key {key[:8]}...")
                except Exception as e:
                    print(f"[OpenAI] ❌ Invalid key {key[:8]}... {e}")
                    self.refill_key(key)   # ⬅️ Refill immediately

            await asyncio.gather(*(test_key(k) for k in batch))

        self.keys = valid
        if not self.keys:
            raise RuntimeError("No valid OpenAI keys available.")
        self.current_key = next(iter(self.keys))
        print(f"[OpenAI] ✅ {len(self.keys)} keys are good and ready.")

    def get_client(self) -> AsyncOpenAI:
        now = time.time()
        local_hour = time.localtime(now).tm_hour

        if local_hour >= 23 or local_hour < 4:
            raise RuntimeError("[OpenAI] ⏸ Scheduled break time (11PM–4AM).")

        if now < self.keys[self.current_key]:
            raise RuntimeError(f"[OpenAI] Key {self.current_key[:8]} cooling down.")

        self.record_activity()
        self.stats[self.current_key]["uses"] += 1
        self.stats[self.current_key]["last_used"] = now
        return AsyncOpenAI(api_key=self.current_key)

    async def rotate(self, force: bool = False):
        now = time.time()
        available = [(k, until) for k, until in self.keys.items() if now >= until]

        if not available:
            soonest_key, soonest_time = min(self.keys.items(), key=lambda kv: kv[1])
            wait_time = max(0, soonest_time - now)
            print(f"[OpenAI] ⏳ All keys cooling. Waiting {wait_time:.1f}s...")
            await asyncio.sleep(wait_time)
            return await self.rotate(force=force)

        unused = [k for k, _ in available if k not in self.used_keys]
        if unused:
            candidate = min(unused, key=lambda k: self.stats[k]["last_used"])
        else:
            self.used_keys.clear()
            candidate = min((k for k, _ in available), key=lambda k: self.stats[k]["last_used"])

        self.current_key = candidate
        self.used_keys.add(candidate)
        self.stats[candidate]["last_used"] = now
        print(f"[OpenAI] 🔄 Rotated to key {candidate[:8]}...")

    def mark_cooldown(self, key=None):
        key = key or self.current_key
        self.keys[key] = time.time() + self.cooldown_seconds
        self.stats[key]["cooldowns"] += 1
        print(f"[OpenAI] ⏳ Cooldown {self.cooldown_seconds}s for {key[:8]}...")

    def status(self):
        now = time.time()
        for i, (k, until) in enumerate(self.keys.items(), start=1):
            cooldown_left = max(0, until - now)
            marker = "<-- current" if k == self.current_key else ""
            print(f"{i}. {k[:8]}... cooldown {cooldown_left:.1f}s, "
                  f"uses={self.stats[k]['uses']}, cooldowns={self.stats[k]['cooldowns']} {marker}")

async def safe_call(manager: OpenAIKeyManager, fn, retries=20, global_cooldown=60):
    last_exc = None
    delay = 2
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
                    wait_time = (24 * 3600 - seconds_since_midnight) + (4 * 3600)
                else:
                    wait_time = (4 * 3600) - seconds_since_midnight
                print(f"[OpenAI] 😴 Scheduled break. Waiting {wait_time/3600:.1f} hours...")
                await asyncio.sleep(wait_time)
                continue

            if "429" in err or "rate limit" in err:
                manager.mark_cooldown()
                await manager.rotate()
                if not manager.keys:
                    print(f"[OpenAI] ❌ All keys exhausted (rate-limited). Pausing {global_cooldown}s...")
                    await asyncio.sleep(global_cooldown)
                else:
                    print(f"[OpenAI] ⚠️ Rate limit hit. Backing off {delay}s (attempt {attempt+1}/{retries})...")
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, 60)
                continue

            if "401" in err or "invalid api key" in err or "400" in err:
                bad_key = manager.current_key
                manager.mark_cooldown(bad_key)
                manager.refill_key(bad_key)   # ⬅️ Auto refill
                await manager.rotate()
                if not manager.keys:
                    raise RuntimeError("[OpenAI] 🚨 No valid keys available. Please update your keys.")
                continue

            break
    raise last_exc

# Load keys from environment (preloaded)
ALL_KEYS = [
    os.getenv(f"OPENAI_KEY_{i}")
    for i in range(1, 211)
    if os.getenv(f"OPENAI_KEY_{i}")
]
if not ALL_KEYS:
    raise RuntimeError("No OpenAI API keys were provided in environment variables.")

print("[DEBUG] Total keys available:", len(ALL_KEYS))

# Start with first 5 keys only
INITIAL_KEYS = ALL_KEYS[:5]

key_manager = OpenAIKeyManager(INITIAL_KEYS, cooldown_seconds=15, wrap=False, idle_rotate_minutes=5)
key_manager._all_keys = ALL_KEYS
key_manager._next_index = 5        # track where to pull the next key
