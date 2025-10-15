import os
import time
import random
import asyncio
from openai import AsyncOpenAI

class OpenAIKeyManager:
    def __init__(self, keys: list[str], cooldown_seconds: int = 3, is_image: bool = False):
        if not keys:
            raise RuntimeError("No OpenAI API keys were provided.")

        self.keys = {k: 0 for k in keys}  # key -> cooldown_until timestamp
        self.stats = {
            k: {"uses": 0, "failures": 0, "cooldowns": 0,
                "last_used": 0, "health": 100}
            for k in keys
        }
        self.cooldown_seconds = cooldown_seconds
        self.current_key = keys[0]
        self.is_image = is_image
        self.failed_keys = set()
        self.client_cache = {}

        # Context mappings: each guild/user → locked key
        self.guild_key_map = {}
        self.user_key_map = {}

    # ---------------- Context assignment ---------------- #

    def assign_key_for_guild(self, guild_id: int | None):
        """Lock a single key to a guild."""
        if guild_id is None:
            return None  # ✅ Prevents "Guild None"
        available = self.available_keys()
        if not available:
            return None
        chosen = random.choice(available)
        self.guild_key_map[guild_id] = chosen
        print(f"[OpenAI] 🏰 Guild {guild_id} → key {chosen[:16]}...")
        return chosen

    def assign_key_for_user(self, user_id: int):
        """Lock a single key to a DM user."""
        available = self.available_keys()
        if not available:
            return None
        chosen = random.choice(available)
        self.user_key_map[user_id] = chosen
        print(f"[OpenAI] 👤 User {user_id} → key {chosen[:16]}...")
        return chosen

    def reassign_key(self, context_id: int, is_guild: bool = True):
        """Reassign a new key after failure or cooldown."""
        if context_id is None:
            return None
        available = self.available_keys()
        if not available:
            return None
        chosen = random.choice(available)
        if is_guild:
            self.guild_key_map[context_id] = chosen
            print(f"[OpenAI] 🔄 Guild {context_id} switched → {chosen[:16]}...")
        else:
            self.user_key_map[context_id] = chosen
            print(f"[OpenAI] 🔄 User {context_id} switched → {chosen[:16]}...")
        return chosen

    # ---------------- Context-based client ---------------- #

    def get_client_for_context(self, context_id: int | None, is_guild: bool = True) -> AsyncOpenAI | None:
        """Return an AsyncOpenAI client for a given guild or user."""
        available = self.available_keys()
        if not available:
            return None

        if context_id is None:
            # DM fallback: just pick any available key
            key = random.choice(available)
            self.current_key = key
            return AsyncOpenAI(api_key=key)

        if is_guild:
            if context_id not in self.guild_key_map:
                self.assign_key_for_guild(context_id)
            key = self.guild_key_map.get(context_id)
        else:
            if context_id not in self.user_key_map:
                self.assign_key_for_user(context_id)
            key = self.user_key_map.get(context_id)

        if not key:
            return None

        now = time.time()
        cooldown_until = self.keys.get(key, 0)
        if now < cooldown_until:
            # Instead of blocking, rotate key immediately
            return AsyncOpenAI(api_key=random.choice(available))

        self.current_key = key
        self.stats[key]["last_used"] = now

        if key not in self.client_cache:
            self.client_cache[key] = AsyncOpenAI(api_key=key)
        return self.client_cache[key]

    # ---------------- Key marking ---------------- #

    def mark_success(self, key=None):
        key = key or self.current_key
        if key in self.stats:
            self.stats[key]["uses"] += 1
            self.stats[key]["health"] = min(100, self.stats[key]["health"] + 1)

    def mark_failure(self, key=None):
        key = key or self.current_key
        if key in self.stats:
            self.stats[key]["failures"] += 1
            self.stats[key]["health"] = max(0, self.stats[key]["health"] - 5)

    def mark_cooldown(self, key=None):
        key = key or self.current_key
        self.keys[key] = time.time() + self.cooldown_seconds
        self.stats[key]["cooldowns"] += 1
        print(f"[OpenAI] ⏳ Cooldown {self.cooldown_seconds}s for {key[:8]}...")

    def drop_key(self, key, reason: str):
        self.keys.pop(key, None)
        self.stats.pop(key, None)
        print(f"[OpenAI] 🗑️ Dropped key {key[:8]} ({reason})")
        if not self.keys and self.on_all_keys_exhausted:
            asyncio.create_task(self.on_all_keys_exhausted())

    # ---------------- Helpers ---------------- #

    def available_keys(self):
        now = time.time()
        return [k for k, until in self.keys.items() if now >= until]

# ---------------- Safe call wrapper ---------------- #

async def openai_safe_call(
    manager: OpenAIKeyManager,
    fn,
    context_id=None,
    is_guild=True,
    is_image=False,
    retries=10
):
    """
    Ultra-fast + safe wrapper for OpenAI calls:
    - Context-locked key (guilds/users)
    - Auto key rotation & cooldown
    - Small retry delay for speed
    - Handles quota, rate limits, invalid keys, etc.
    """
    if manager is None:
        raise RuntimeError("[OpenAI] 🚨 Key manager not initialized!")

    last_exc = None
    key_type = "IMAGE" if is_image else "CHAT"

    # small fixed delay for quick retries
    delay = 0.4  

    for attempt in range(retries):
        try:
            # 🔹 Try to get a client for this context
            client = manager.get_client_for_context(context_id, is_guild)
            if client is None:
                print(f"[OpenAI] ⏳ No available {key_type} key for {context_id}, retrying...")
                manager.reassign_key(context_id, is_guild)
                await asyncio.sleep(0.2)
                continue

            # 🔹 Run the API call
            result = await fn(client)
            manager.mark_success(manager.current_key)
            return result

        except Exception as e:
            last_exc = e
            err = str(e).lower()
            manager.mark_failure(manager.current_key)

            # --- Fast categorized failover --- #
            if "quota" in err or "billing" in err:
                print(f"[OpenAI] 🚫 Quota/billing issue for {manager.current_key[:8]}")
                manager.drop_key(manager.current_key, "quota/billing")
                manager.reassign_key(context_id, is_guild)
                continue

            if "401" in err or "invalid api key" in err:
                print(f"[OpenAI] ❌ Invalid key {manager.current_key[:8]}")
                manager.drop_key(manager.current_key, "invalid key")
                manager.reassign_key(context_id, is_guild)
                continue

            if "429" in err or "rate limit" in err:
                print(f"[OpenAI] ⚠️ Rate limit hit → cooldown {delay}s (try {attempt+1}/{retries})")
                manager.mark_cooldown(manager.current_key)
                manager.reassign_key(context_id, is_guild)
                await asyncio.sleep(delay)
                delay = min(delay + 0.3, 3.0)
                continue

            # --- Unknown / transient error --- #
            print(f"[OpenAI] ⚠️ Unexpected error on key {manager.current_key[:8]}: {e}")
            manager.mark_cooldown(manager.current_key)
            await asyncio.sleep(0.5)
            continue

    print(f"[OpenAI] ❌ All {retries} retries failed. Last error: {last_exc}")
    if isinstance(last_exc, BaseException):
        raise last_exc
    else:
        raise RuntimeError(f"OpenAI safe call failed after {retries} retries: {last_exc}")

# ---------------- Key scanning ---------------- #

async def scan_all_keys(batch_size: int = 10) -> list[str]:
    """Scan all OPENAI_KEY_* env vars and return only valid keys, parallelized."""
    print("[OpenAI] 🔄 Scanning all text keys...")
    all_keys = [k for k in (os.getenv(f"OPENAI_KEY_{i}") for i in range(1, 500)) if k]
    if not all_keys:
        raise RuntimeError("[OpenAI] 🚨 No OPENAI_KEY_* found in environment.")

    valid_keys = []

    async def test_key(key):
        try:
            client = AsyncOpenAI(api_key=key)
            await client.models.list()
            print(f"[OpenAI] ✅ Key {key[:8]} works")
            return key
        except Exception as e:
            print(f"[OpenAI] ❌ Key {key[:8]} invalid ({e})")
            return None

    # Run in batches
    for i in range(0, len(all_keys), batch_size):
        batch = all_keys[i:i + batch_size]
        tasks = [asyncio.create_task(test_key(k)) for k in batch]

        for coro in asyncio.as_completed(tasks):
            result = await coro
            if result:
                valid_keys.append(result)

    if not valid_keys:
        raise print("[OpenAI] 🚨 No valid text keys found.")
    print(f"[OpenAI] ✅ Found {len(valid_keys)} valid text keys.")
    return valid_keys

async def scan_all_image_keys(batch_size: int = 10) -> list[str]:
    """Scan all IMAGE_KEY_* env vars and return only valid keys, parallelized."""
    print("[OpenAI] 🔄 Scanning all image keys...")
    all_keys = [k for k in (os.getenv(f"IMAGE_KEY_{i}") for i in range(1, 500)) if k]
    if not all_keys:
        raise RuntimeError("[OpenAI] 🚨 No IMAGE_KEY_* found in environment.")

    valid_keys = []

    async def test_key(key):
        try:
            client = AsyncOpenAI(api_key=key)
            await client.models.list()
            print(f"[OpenAI] ✅ Image key {key[:8]} works")
            return key
        except Exception as e:
            print(f"[OpenAI] ❌ Image key {key[:8]} invalid ({e})")
            return None

    # Run in batches
    for i in range(0, len(all_keys), batch_size):
        batch = all_keys[i:i + batch_size]
        tasks = [asyncio.create_task(test_key(k)) for k in batch]

        for coro in asyncio.as_completed(tasks):
            result = await coro
            if result:
                valid_keys.append(result)

    if not valid_keys:
        raise print("[OpenAI] 🚨 No valid image keys found.")
    print(f"[OpenAI] ✅ Found {len(valid_keys)} valid image keys.")
    return valid_keys

# ---------------- Lazy-loaded managers ---------------- #

key_manager = None
image_key_manager = None

async def init_key_manager():
    global key_manager
    if key_manager is None:
        keys = [k for k in (os.getenv(f"OPENAI_KEY_{i}") for i in range(1, 500)) if k]
        if not keys:
            raise RuntimeError("No text keys found.")
        key_manager = OpenAIKeyManager(keys)
    return key_manager

async def init_image_key_manager():
    global image_key_manager
    if image_key_manager is None:
        keys = [k for k in (os.getenv(f"IMAGE_KEY_{i}") for i in range(1, 500)) if k]
        if not keys:
            raise RuntimeError("No image keys found.")
        image_key_manager = OpenAIKeyManager(keys, is_image=True)
    return image_key_manager

# ---------------- Periodic rescans ---------------- #

async def periodic_rescan(interval_hours: int = 6):
    """Periodically rescan OPENAI_KEY_* and add new ones if found."""
    global key_manager
    while True:
        await asyncio.sleep(interval_hours * 3600)
        if not key_manager:
            continue
        print("[OpenAI] 🔄 Background rescan (text keys)...")
        new_keys = await scan_all_keys(batch_size=5)
        for key in new_keys:
            if key not in key_manager.keys:
                key_manager.keys[key] = 0
                key_manager.stats[key] = {"uses": 0, "failures": 0,
                                          "cooldowns": 0, "last_used": 0, "health": 100}
        print(f"[OpenAI] ✅ Rescan done. Total text keys: {len(key_manager.keys)}")

async def image_periodic_rescan(interval_hours: int = 6):
    """Periodically rescan IMAGE_KEY_* and add new ones if found."""
    global image_key_manager
    while True:
        await asyncio.sleep(interval_hours * 3600)
        if not image_key_manager:
            continue
        print("[OpenAI] 🔄 Background rescan (image keys)...")
        new_keys = await scan_all_image_keys(batch_size=5)
        for key in new_keys:
            if key not in image_key_manager.keys:
                image_key_manager.keys[key] = 0
                image_key_manager.stats[key] = {"uses": 0, "failures": 0,
                                                "cooldowns": 0, "last_used": 0, "health": 100}
        print(f"[OpenAI] ✅ Rescan done. Total image keys: {len(image_key_manager.keys)}")
