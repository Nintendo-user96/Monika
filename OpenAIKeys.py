import os
import time
import asyncio
from openai import AsyncOpenAI

# ---------------- Event placeholders (set externally by monika_bot) ---------------- #
async def on_sleeping(reason: str = "Taking a nap..."):
    print(f"[Sleep] 😴 (placeholder) {reason}")

async def on_wake_up(reason: str = "I'm back online!"):
    print(f"[Wake] 🌅 (placeholder) {reason}")


class OpenAIKeyManager:
    def __init__(self, keys: list[str], cooldown_seconds: int = 15,
                 idle_rotate_minutes: int = 5, wrap: bool = False):
        if not keys:
            raise RuntimeError("No OpenAI API keys were provided.")

        # working key pool
        self.keys = {k: 0 for k in keys}  # key → cooldown_until
        self.current_key = keys[0]

        self.cooldown_seconds = cooldown_seconds
        self.idle_rotate_minutes = max(5, idle_rotate_minutes)
        self.wrap = wrap

        # stats + health
        self.stats = {
            k: {"uses": 0, "failures": 0, "cooldowns": 0,
                "last_used": 0, "health": 100, "last_success": 0}
            for k in keys
        }

        self.last_activity = time.time()
        self._idle_task = None
        self._refill_lock = asyncio.Lock()

        # full pool for refills
        self._all_keys = list(keys)
        self._next_index = len(keys)

        # event hooks
        self.on_all_keys_exhausted = self._default_all_keys_exhausted
        self.on_key_recovered = self._default_key_recovered
        self.on_key_exhausted = self._default_key_exhausted

    # ---------------- Lifecycle ---------------- #

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
                    await self.rotate()
            except Exception as e:
                print(f"[OpenAI] ⚠️ Idle rotator error: {e}")

    def record_activity(self):
        self.last_activity = time.time()

    # ---------------- Core ---------------- #

    def _update_health(self, key, success: bool):
        if success:
            self.stats[key]["health"] = min(100, self.stats[key]["health"] + 5)
            self.stats[key]["last_success"] = time.time()
        else:
            self.stats[key]["health"] = max(0, self.stats[key]["health"] - 10)
            self.stats[key]["failures"] += 1

    def get_client(self) -> AsyncOpenAI:
        now = time.time()

        # configurable break window
        break_start = int(os.getenv("BREAK_START", 23))  # default 23h
        break_end = int(os.getenv("BREAK_END", 4))       # default 4h
        local_hour = time.localtime(now).tm_hour
        if (break_start <= local_hour or local_hour < break_end):
            raise RuntimeError("[OpenAI] ⏸ Scheduled break time (11PM–4AM).")

        if now < self.keys[self.current_key]:
            raise RuntimeError(f"[OpenAI] Key {self.current_key[:8]} cooling down.")

        self.stats[self.current_key]["uses"] += 1
        self.stats[self.current_key]["last_used"] = now
        self.record_activity()

        return AsyncOpenAI(api_key=self.current_key)

    async def rotate(self):
        now = time.time()
        available = [(k, until) for k, until in self.keys.items() if now >= until]

        if not available:
            soonest_key, soonest_time = min(self.keys.items(), key=lambda kv: kv[1])
            wait_time = max(0, soonest_time - now)
            print(f"[OpenAI] ⏳ All keys cooling. Waiting {wait_time:.1f}s...")
            await asyncio.sleep(wait_time)

            if self.on_all_keys_exhausted:
                await self.on_all_keys_exhausted()
            return await self.rotate()

        # healthiest + least recently successful
        available.sort(key=lambda kv: (
            -self.stats[kv[0]]["health"],
            self.stats[kv[0]]["last_success"],
            self.stats[kv[0]]["last_used"],
        ))
        best_key = available[0][0]
        self.current_key = best_key
        print(f"[OpenAI] 🔄 Rotated to {best_key[:8]}...")

    def mark_cooldown(self, key=None):
        if not key:
            key = self.current_key
        self.keys[key] = time.time() + self.cooldown_seconds
        self.stats[key]["cooldowns"] += 1
        self._update_health(key, success=False)
        print(f"[OpenAI] ⏳ Cooldown {self.cooldown_seconds}s for {key[:8]}...")

        if self.on_key_exhausted:
            asyncio.create_task(self.on_key_exhausted(key))

    def mark_success(self, key=None):
        if not key:
            key = self.current_key
        self._update_health(key, success=True)

        if self.on_key_recovered:
            asyncio.create_task(self.on_key_recovered(key))

    async def refill_key(self, bad_key: str) -> bool:
        async with self._refill_lock:
            if self._all_keys:
                while self._next_index < len(self._all_keys):
                    candidate = self._all_keys[self._next_index]
                    self._next_index += 1
                    if candidate and candidate not in self.keys:
                        if bad_key in self.keys:
                            del self.keys[bad_key]
                            self.stats.pop(bad_key, None)
                        self.keys[candidate] = 0
                        self.stats[candidate] = {"uses": 0, "failures": 0,
                                                 "cooldowns": 0, "last_used": 0,
                                                 "health": 100, "last_success": 0}
                        if self.current_key == bad_key:
                            self.current_key = candidate
                        print(f"[OpenAI] 🔄 Refilled: replaced {bad_key[:8]}... with {candidate[:8]}...")
                        return True
                print("[OpenAI] 🚨 No spare keys left.")
                return False
            return False

    # ---------------- Validation ---------------- #

    async def validate_keys(self, batch_size: int = 5):
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
                    print(f"[OpenAI] ❌ Invalid key {key[:8]} ({e})")
                    await self.refill_key(key)

            await asyncio.gather(*(test_key(k) for k in batch))

        if valid:
            self.keys = valid
            self.current_key = next(iter(self.keys))
            print(f"[OpenAI] ✅ {len(self.keys)} keys ready.")
        else:
            print("[OpenAI] ❌ No valid keys found — keeping existing set.")

    # ---------------- Introspection ---------------- #

    def status(self):
        now = time.time()
        for i, (k, until) in enumerate(self.keys.items(), start=1):
            cd_left = max(0, until - now)
            marker = "<-- current" if k == self.current_key else ""
            print(f"{i}. {k[:8]}... cd={cd_left:.1f}s "
                  f"health={self.stats[k]['health']} "
                  f"uses={self.stats[k]['uses']} "
                  f"fails={self.stats[k]['failures']} {marker}")

    # ---------------- Default Event Handlers ---------------- #

    async def _default_all_keys_exhausted(self):
        await on_sleeping("All OpenAI keys exhausted")

    async def _default_key_recovered(self, key: str):
        await on_wake_up(f"Key {key[:8]} recovered")

    async def _default_key_exhausted(self, key: str):
        print(f"[OpenAI] ❌ Key {key[:8]} exhausted.")


# ---------------- Safe API Wrapper ---------------- #

async def openai_safe_call(manager: OpenAIKeyManager, fn, retries=20, global_cooldown=60):
    last_exc = None
    delay = 2
    model_priority = ["gpt-5-mini", "gpt-5", "gpt-4o", "gpt-3.5-turbo"]

    for model in model_priority:
        for attempt in range(retries):
            try:
                client = manager.get_client()
                response = await fn(client)
                manager.mark_success()
                return response

            except Exception as e:
                last_exc = e
                err = str(e).lower()
                print(f"[OpenAI] ⚠️ Ignored error: {e}")

                if "scheduled break" in err:
                    now = time.localtime()
                    seconds = now.tm_hour * 3600 + now.tm_min * 60 + now.tm_sec
                    wait_time = (4 * 3600) - seconds if now.tm_hour < 4 else (24*3600 - seconds) + 4*3600
                    print(f"[OpenAI] 😴 Break for {wait_time/3600:.1f}h...")
                    await asyncio.sleep(wait_time)
                    continue

                if "billing_not_active" in err or "your account is not active" in err:
                    print("[OpenAI] 🚨 Billing not active — pausing requests.")
                    if manager.on_all_keys_exhausted:
                        await manager.on_all_keys_exhausted()
                    await asyncio.sleep(global_cooldown)
                    continue

                if "429" in err or "rate limit" in err:
                    manager.mark_cooldown()
                    await manager.rotate()
                    if not manager.available_keys():
                        print(f"[OpenAI] ❌ All keys rate-limited. Cooldown {global_cooldown}s...")
                        await asyncio.sleep(global_cooldown)
                    else:
                        print(f"[OpenAI] ⚠️ Rate limit. Retry in {delay}s...")
                        await asyncio.sleep(delay)
                        delay = min(delay * 2, 60)
                    continue

                if "401" in err or "invalid api key" in err or "400" in err:
                    bad_key = manager.current_key
                    manager.mark_cooldown(bad_key)
                    await manager.refill_key(bad_key)
                    await manager.rotate()
                    continue
                
                if "404" in err or "model_not_found" in err or "organization must be verified" in err:
                    print(f"[OpenAI] 🚫 {model} not available (org not verified). Skipping...")
                    continue

                print(f"[OpenAI] ⚠️ Retrying in {delay}s...")
                await asyncio.sleep(delay)
                delay = min(delay * 2, 60)
                continue

    print("[OpenAI] ❌ All retries failed. Returning None.")
    return None


# ---------------- Key Scanning ---------------- #

async def scan_all_keys(batch_size: int = 5, preload: int = 5) -> list[str]:
    """Scan all env keys and return a preload pool of valid keys (e.g., 5)."""
    print("[OpenAI] 🔄 Scanning all keys...")
    all_keys = [os.getenv(f"OPENAI_KEY_{i}") for i in range(1, 211)]
    all_keys = [k for k in all_keys if k]  # drop None

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

        # Stop early once we have enough preload keys
        if len(valid_keys) >= preload:
            break

    if not valid_keys:
        raise RuntimeError("[OpenAI] 🚨 No valid keys found.")
    print(f"[OpenAI] ✅ Using {len(valid_keys)} preload keys (from {len(all_keys)} total).")
    return valid_keys

# ---------------- Init + Background Rescan ---------------- #

key_manager = None  # will be initialized later

async def init_key_manager():
    """Initialize the key manager by scanning all keys once."""
    global key_manager
    preload_keys = await scan_all_keys(batch_size=5, preload=5)
    initial_keys = preload_keys[:5]

    key_manager = OpenAIKeyManager(preload_keys, cooldown_seconds=15, idle_rotate_minutes=5)
    key_manager._all_keys = preload_keys  # start with known good ones
    key_manager._next_index = len(preload_keys)

    print(f"[OpenAI] ✅ KeyManager initialized with {len(preload_keys)} keys.")
    return key_manager

async def periodic_rescan(interval_hours=6):
    """Periodically rescan all keys and merge new ones into the pool."""
    global key_manager
    while True:
        await asyncio.sleep(interval_hours * 3600)
        print("[OpenAI] 🔄 Background rescan starting...")
        try:
            new_keys = await scan_all_keys(batch_size=5)
            for key in new_keys:
                if key not in key_manager.keys:
                    key_manager.keys[key] = 0
                    key_manager.stats[key] = {"uses": 0, "failures": 0, "cooldowns": 0,
                                              "last_used": 0, "health": 100, "last_success": 0}
            key_manager._all_keys = list(set(key_manager._all_keys) | set(new_keys))
            print(f"[OpenAI] ✅ Rescan complete. Total keys now: {len(key_manager._all_keys)}")
        except Exception as e:
            print(f"[OpenAI] ⚠️ Rescan failed: {e}")
