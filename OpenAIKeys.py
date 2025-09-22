import os
import time
import asyncio
from openai import AsyncOpenAI


class OpenAIKeyManager:
    def __init__(self, keys: list[str], cooldown_seconds: int = 15, idle_rotate_minutes: int = 5):
        if not keys:
            raise RuntimeError("No OpenAI API keys were provided.")

        # Active key pool
        self.keys = {k: 0 for k in keys}  # key -> cooldown_until timestamp
        self.current_key = keys[0]
        self.cooldown_seconds = cooldown_seconds

        # Stats per key
        self.stats = {
            k: {"uses": 0, "failures": 0, "cooldowns": 0,
                "last_used": 0, "health": 100}
            for k in keys
        }

        # Idle handling
        self.last_activity = time.time()
        self.idle_rotate_minutes = max(5, idle_rotate_minutes)
        self._idle_task = None

        # Backup storage
        self._all_keys = keys.copy()
        self._next_index = len(keys)

        # Hooks
        self.on_all_keys_exhausted = None
        self.on_key_recovered = None

    # ---------------- Idle rotation ---------------- #

    def start_idle_rotator(self):
        """Start background task to rotate keys if idle too long."""
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

    # ---------------- Key handling ---------------- #

    def get_client(self) -> AsyncOpenAI:
        """Return a client for current key, enforcing cooldowns and break time."""
        now = time.time()
        local_hour = time.localtime(now).tm_hour

        # Scheduled break (11PM–6AM)
        if local_hour >= 23 or local_hour < 6:
            raise RuntimeError("[OpenAI] ⏸ Scheduled break time (11PM–6AM).")

        if now < self.keys[self.current_key]:
            raise RuntimeError(f"[OpenAI] Key {self.current_key[:8]} cooling down.")

        self.record_activity()
        return AsyncOpenAI(api_key=self.current_key)

    async def rotate(self):
        """Pick least-recently-used key with no cooldown."""
        now = time.time()
        available = [(k, until) for k, until in self.keys.items() if now >= until]

        if not available:
            soonest_key, soonest_time = min(self.keys.items(), key=lambda kv: kv[1])
            wait_time = max(0, soonest_time - now)
            print(f"[OpenAI] ⏳ All keys cooling. Waiting {wait_time:.1f}s...")
            await asyncio.sleep(wait_time)
            return await self.rotate()

        # Prefer least recently used
        available.sort(key=lambda kv: self.stats[kv[0]]["last_used"])
        best_key = available[0][0]

        self.current_key = best_key
        self.stats[best_key]["last_used"] = now
        self.stats[best_key]["uses"] += 1
        print(f"[OpenAI] 🔄 Rotated to {best_key[:8]}...")

    def mark_success(self, key: str = None):
        """Mark a key as having a successful call."""
        key = key or self.current_key
        if key in self.stats:
            self.stats[key]["uses"] += 1
            self.stats[key]["health"] = min(100, self.stats[key]["health"] + 1)

    def mark_failure(self, key: str = None):
        """Mark a key as having a failed call."""
        key = key or self.current_key
        if key in self.stats:
            self.stats[key]["failures"] += 1
            self.stats[key]["health"] = max(0, self.stats[key]["health"] - 5)

    def mark_cooldown(self, key: str = None):
        """Put a key on cooldown."""
        key = key or self.current_key
        self.keys[key] = time.time() + self.cooldown_seconds
        self.stats[key]["cooldowns"] += 1
        print(f"[OpenAI] ⏳ Cooldown {self.cooldown_seconds}s for {key[:8]}...")

    def drop_key(self, key: str, reason: str):
        """Remove a key from rotation permanently."""
        if key in self.keys:
            self.keys.pop(key, None)
        if key in self.stats:
            self.stats.pop(key, None)
        print(f"[OpenAI] 🗑️ Dropped key {key[:8]} ({reason})")

        if not self.keys and self.on_all_keys_exhausted:
            asyncio.create_task(self.on_all_keys_exhausted())

    # ---------------- Reporting ---------------- #

    def current_key_index(self) -> int:
        keys = list(self.keys.keys())
        return keys.index(self.current_key) + 1

    def status(self):
        now = time.time()
        for i, (k, until) in enumerate(self.keys.items(), start=1):
            cooldown_left = max(0, until - now)
            marker = "<-- current" if k == self.current_key else ""
            print(
                f"{i}. {k[:8]}... cooldown {cooldown_left:.1f}s, "
                f"uses={self.stats[k]['uses']}, failures={self.stats[k]['failures']}, "
                f"cooldowns={self.stats[k]['cooldowns']}, health={self.stats[k]['health']} {marker}"
            )

    def get_status_report(self) -> str:
        """Return a text summary (for Discord commands)."""
        now = time.time()
        lines = []
        for i, (k, until) in enumerate(self.keys.items(), start=1):
            cooldown_left = max(0, until - now)
            marker = "⬅️ current" if k == self.current_key else ""
            lines.append(
                f"{i}. {k[:8]}... ⏳{cooldown_left:.1f}s | "
                f"uses={self.stats[k]['uses']} | fails={self.stats[k]['failures']} | "
                f"cd={self.stats[k]['cooldowns']} | health={self.stats[k]['health']} {marker}"
            )
        return "\n".join(lines)

    def available_keys(self):
        now = time.time()
        return [k for k, until in self.keys.items() if now >= until]

    # ---------------- Stats ---------------- #

    def remaining_cooldowns(self):
        now = time.time()
        return {k: max(0, until - now) for k, until in self.keys.items()}

    def stats_summary(self):
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


# ---------------- Safe call wrapper ---------------- #

async def openai_safe_call(manager: OpenAIKeyManager, fn, retries=20, global_cooldown=60):
    last_exc = None
    delay = 2

    for attempt in range(retries):
        try:
            client = manager.get_client()
            result = await fn(client)
            manager.mark_success(manager.current_key)  # ✅ record success
            return result
        except Exception as e:
            last_exc = e
            err = str(e).lower()
            manager.mark_failure(manager.current_key)

            # Scheduled break
            if "scheduled break" in err:
                now = time.localtime()
                seconds = now.tm_hour * 3600 + now.tm_min * 60 + now.tm_sec
                if now.tm_hour >= 23:
                    wait_time = (24 * 3600 - seconds) + (6 * 3600)
                else:
                    wait_time = (6 * 3600) - seconds
                print(f"[OpenAI] 😴 Scheduled break. Waiting {wait_time/3600:.1f}h...")
                await asyncio.sleep(wait_time)
                continue

            # Quota exceeded
            if "insufficient_quota" in err:
                print(f"[OpenAI] 🚫 No quota for {manager.current_key[:8]} — dropping.")
                manager.drop_key(manager.current_key, "insufficient_quota")
                if not manager.keys:
                    raise RuntimeError("[OpenAI] 🚨 All keys out of quota.")
                await manager.rotate()
                continue

            # Rate limited
            if "429" in err or "rate limit" in err:
                manager.mark_cooldown(manager.current_key)
                await manager.rotate()
                if not manager.available_keys():
                    print(f"[OpenAI] ❌ All keys rate-limited. Pausing {global_cooldown}s...")
                    await asyncio.sleep(global_cooldown)
                else:
                    print(f"[OpenAI] ⚠️ Rate limit. Backoff {delay}s (attempt {attempt+1}/{retries})...")
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, 60)
                continue

            # Invalid keys
            if "401" in err or "invalid api key" in err or "400" in err:
                manager.drop_key(manager.current_key, "invalid key")
                if not manager.keys:
                    raise RuntimeError("[OpenAI] 🚨 No valid keys available.")
                await manager.rotate()
                continue

            # Billing inactive
            if "billing_not_active" in err:
                manager.drop_key(manager.current_key, "billing inactive")
                if not manager.keys:
                    raise RuntimeError("[OpenAI] 🚨 No billing-active keys left.")
                await manager.rotate()
                continue

            break

    raise last_exc

# ---------------- Key scanning ---------------- #

async def scan_all_keys(batch_size: int = 5, preload: int = 5) -> list[str]:
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


# ---------------- Manager init & rescan ---------------- #

key_manager = None

async def init_key_manager():
    global key_manager
    preload_keys = await scan_all_keys(batch_size=5, preload=5)
    key_manager = OpenAIKeyManager(preload_keys, cooldown_seconds=15, idle_rotate_minutes=5)
    key_manager._all_keys = preload_keys.copy()
    key_manager._next_index = len(preload_keys)
    print(f"[OpenAI] ✅ KeyManager initialized with {len(preload_keys)} keys.")
    return key_manager


async def periodic_rescan(interval_hours=6):
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
