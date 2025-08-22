import time
import asyncio
import os
from openai import AsyncOpenAI

class OpenAIKeyManager:
    def __init__(self, keys: list[str], cooldown_seconds: int = 15, wrap: bool = False):
        self.keys = {k: 0 for k in keys}
        self.current_key = keys[0] if keys else None
        self.cooldown_seconds = cooldown_seconds
        self.wrap = wrap

    async def validate_keys(self):
        """Test each key once, keep only valid ones."""
        valid = {}
        for k in list(self.keys.keys()):
            try:
                client = AsyncOpenAI(api_key=k)
                await client.models.list()
                valid[k] = 0
                print(f"[OpenAI] ✅ Valid key: {k[:8]}...")
            except Exception as e:
                print(f"[OpenAI] ❌ Dropping key {k[:8]}... {e}")

        self.keys = valid
        if not self.keys:
            raise RuntimeError("No valid OpenAI keys available.")
        self.current_key = next(iter(self.keys))

    def get_client(self) -> AsyncOpenAI:
        now = time.time()
        if now < self.keys[self.current_key]:
            raise RuntimeError(f"[OpenAI] Key {self.current_key[:8]} cooling down.")
        return AsyncOpenAI(api_key=self.current_key)

    async def rotate(self):
        # Keep the original insertion order of keys
        keys = list(self.keys.keys())

        # If current_key somehow disappeared (e.g., after validation), pick the first available one
        if self.current_key not in self.keys:
            for k in keys:
                if time.time() >= self.keys[k]:
                    self.current_key = k
                    print(f"[OpenAI] 🔄 Rotated to key {k[:8]}...")
                    return
            raise RuntimeError("No keys available (all cooling).")

        # Move forward from the *next* key only; do not wrap.
        start_idx = keys.index(self.current_key) + 1
        for i in range(start_idx, len(keys)):  # only forward, no modulo
            k = keys[i]
            if time.time() >= self.keys[k]:  # not cooling
                self.current_key = k
                print(f"[OpenAI] 🔄 Rotated to key {k[:8]}...")
                return

        # If we got here, we reached the end with no available key.
        raise RuntimeError("No more keys available ahead (end reached, no wrap).")

    def mark_cooldown(self, key):
        self.keys[key] = time.time() + self.cooldown_seconds
        print(f"[OpenAI] ⏳ Cooldown {self.cooldown_seconds}s for {key[:8]}...")

async def safe_call(manager: OpenAIKeyManager, fn, retries=3):
    last_exc = None
    for _ in range(retries):
        try:
            client = manager.get_client()
            return await fn(client)
        except Exception as e:
            last_exc = e
            err = str(e).lower()
            if "429" in err or "rate limit" in err:
                manager.mark_cooldown(manager.current_key)
                await manager.rotate()
                await asyncio.sleep(2)
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
