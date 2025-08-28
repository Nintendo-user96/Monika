import time
import asyncio
import os
from openai import AsyncOpenAI

class OpenAIKeyManager:
    def __init__(self, keys: list[str], cooldown_seconds: int = 15, wrap: bool = False):
        if not keys:
            raise RuntimeError("No OpenAI API keys were provided.")
        self.keys = {k: 0 for k in keys}
        self.current_key = keys[0]
        self.cooldown_seconds = cooldown_seconds
        self.wrap = wrap

    async def validate_keys(self):
        """Test each key once, keep only valid ones."""
        print("[OpenAI] 🔄 Loading...")

        valid = {}
        for k in list(self.keys.keys()):
            try:
                client = AsyncOpenAI(api_key=k)
                await client.models.list()
                valid[k] = 0
            except Exception:
                pass  # silently ignore invalid keys

        self.keys = valid
        if not self.keys:
            raise RuntimeError("No valid OpenAI keys available.")
        self.current_key = next(iter(self.keys))

        print(f"[OpenAI] ✅ {len(self.keys)} keys are good and ready.")

    def get_client(self) -> AsyncOpenAI:
        now = time.time()
        if now < self.keys[self.current_key]:
            raise RuntimeError(f"[OpenAI] Key {self.current_key[:8]} cooling down.")
        return AsyncOpenAI(api_key=self.current_key)

    async def rotate(self):
        keys = list(self.keys.keys())

        if self.current_key not in self.keys:
            self.current_key = keys[0]

        start_idx = keys.index(self.current_key) + 1
        for i in range(start_idx, len(keys)):  # only forward, no wrap
            k = keys[i]
            if time.time() >= self.keys[k]:  # not cooling
                self.current_key = k
                print(f"[OpenAI] 🔄 Rotated to key {k[:8]}...")
                return

        # If nothing available, wait until the soonest cooldown ends
        soonest_key, soonest_time = min(self.keys.items(), key=lambda kv: kv[1])
        wait_time = max(0, soonest_time - time.time())
        print(f"[OpenAI] ⏳ Waiting {wait_time:.1f}s for next key...")
        await asyncio.sleep(wait_time)
        self.current_key = soonest_key

    def mark_cooldown(self, key):
        self.keys[key] = time.time() + self.cooldown_seconds
        print(f"[OpenAI] ⏳ Cooldown {self.cooldown_seconds}s for {key[:8]}...")

    def current_key_index(self) -> int:
        """Return the index (1-based) of the current key."""
        keys = list(self.keys.keys())
        return keys.index(self.current_key) + 1

    def status(self):
        """Print status of all keys with cooldown times."""
        now = time.time()
        for i, (k, until) in enumerate(self.keys.items(), start=1):
            cooldown_left = max(0, until - now)
            marker = "<-- current" if k == self.current_key else ""
            print(f"{i}. {k[:8]}... cooldown {cooldown_left:.1f}s {marker}")

async def safe_call(manager: OpenAIKeyManager, fn, retries=10):
    last_exc = None
    delay = 2  # initial backoff in seconds
    for attempt in range(retries):
        try:
            client = manager.get_client()
            return await fn(client)
        except Exception as e:
            last_exc = e
            err = str(e).lower()
            if "429" in err or "rate limit" in err:
                manager.mark_cooldown(manager.current_key)
                await manager.rotate()
                print(f"[OpenAI] ⚠️ Rate limit hit. Backing off for {delay}s (attempt {attempt+1}/{retries})...")
                await asyncio.sleep(delay)
                delay = min(delay * 2, 60)  # exponential backoff capped at 60s
                continue
            if "401" in err or "invalid api key" in err or "400" in err:
                print(f"[OpenAI] Fatal error on key {manager.current_key[:8]}: {e}")
                raise e
            break
    raise last_exc

# Load keys from environment
OPENAI_KEYS = [os.getenv(f"OPENAI_KEY_{i}") for i in range(1, 121) if os.getenv(f"OPENAI_KEY_{i}")]

# Shared manager instance (importable everywhere)
key_manager = OpenAIKeyManager(OPENAI_KEYS, cooldown_seconds=15, wrap=False)
