import os
import re
import io
import sys
import time
import random
import asyncio
import logging
import traceback
import datetime
import threading
import typing
import atexit
import requests
import json
import aiohttp
import hashlib

import discord
from discord import File, app_commands
from discord.ext import commands
from discord.permissions import Permissions
from discord.ui import View, Button

# Local modules
import error_detector
import keepalive
from OpenAIKeys import (
    OpenAIKeyManager,
    openai_safe_call,
    init_key_manager,
    init_image_key_manager,
    periodic_rescan,
    key_manager,
    image_key_manager
)
from memory import MemoryManager
from expression import User_SpritesManager
# from expression_dokitubers import DOKITUBER_MANAGERS
# from expression_MAS import MAS_SpritesManager
from user_tracker import UserTracker
from servers_tracker import GuildTracker
from monika_personality import MonikaTraits
from performance import (
    background_task,
    cache_result,
    get_memory_usage,
    cleanup_memory,
    async_cleanup_memory,
    monitor_event_loop,
)
from vote_tracker import VoteTracker
from Idle_Presence import monika_idle_presences

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("Monika")
logger.info("Just Monika!")

# ================== OpenAI Cache ================== #
_openai_cache = {}  # (context_id, model, hash) -> (timestamp, reply_text)
CACHE_TTL = 20  # seconds before cache expires
CACHE_PRUNE_INTERVAL = 200  # prune every 200 cache inserts
_cache_counter = 0

def _make_conv_hash(conversation: list[dict]) -> str:
    """Create a stable short hash from the conversation list (system included)."""
    if not isinstance(conversation, list):
        raise ValueError("Conversation must be a list of dict messages.")
    raw = "".join(
        msg.get("role", "") + msg.get("content", "")
        for msg in conversation if isinstance(msg, dict)
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

def _prune_cache():
    """Remove expired cache entries safely to free memory."""
    global _openai_cache
    now = time.time()
    expired = [k for k, (ts, _) in _openai_cache.items() if now - ts >= CACHE_TTL]
    for k in expired:
        _openai_cache.pop(k, None)
    if expired:
        print(f"[OpenAI] 🧹 Pruned {len(expired)} expired cache entries.")

async def call_openai_with_retries(user, relationship, personality, conversation):
    """
    Fast and safe OpenAI caller:
    - Caches responses for 20s
    - Avoids UnboundLocalError by proper global use
    - Optimized for 3–5s replies
    - Handles multiple concurrent users safely
    """
    global _cache_counter, _openai_cache  # ✅ ensures both are global

    model_priority = ["gpt-5-nano", "gpt-5-mini", "gpt-5"]

    # ---------------- Context ---------------- #
    context_id = getattr(getattr(user, "guild", None), "id", None) or user.id
    is_guild = hasattr(user, "guild") and user.guild is not None

    if not isinstance(conversation, list):
        raise ValueError("Conversation must be a list of messages.")

    # ---------------- Cache check ---------------- #
    conv_hash = _make_conv_hash(conversation)
    for model in model_priority:
        cache_key = (context_id, model, conv_hash)
        cached = _openai_cache.get(cache_key)
        if cached:
            ts, cached_reply = cached
            if time.time() - ts < CACHE_TTL:
                print(f"[OpenAI] ⚡ Cache hit → {model}")
                return cached_reply
            else:
                _openai_cache.pop(cache_key, None)

    # ---------------- Build system prompt ---------------- #
    system_prompt = await generate_monika_system_prompt(
        guild=user.guild if hasattr(user, "guild") else None,
        user=user,
        relationship_type=relationship,
        selected_modes=personality,
    )
    full_conversation = [{"role": "system", "content": system_prompt}] + conversation

    # ---------------- Sequential fast retry ---------------- #
    for model in model_priority:
        async def call_fn(client):
            # ⚡ Remove asyncio.wait_for (causes CancelledError)
            return await client.chat.completions.create(
                model=model,
                messages=full_conversation,
                timeout=15  # safe internal OpenAI timeout (doesn't block asyncio)
            )

        try:
            start_time = time.perf_counter()
            response = await openai_safe_call(
                key_manager,
                fn=call_fn,
                context_id=context_id,
                is_guild=is_guild,
                is_image=False
            )
            elapsed = time.perf_counter() - start_time

            # Validate response
            if response and getattr(response, "choices", None):
                msg = response.choices[0].message
                if msg and msg.content:
                    reply_text = msg.content.strip()
                    if reply_text:
                        print(f"[OpenAI] ✅ {model} → {elapsed:.2f}s")
                        cache_key = (context_id, model, conv_hash)
                        _openai_cache[cache_key] = (time.time(), reply_text)
                        _cache_counter = (_cache_counter + 1) % (CACHE_PRUNE_INTERVAL + 1)
                        if _cache_counter == 0:
                            _prune_cache()
                        return reply_text

            print(f"[OpenAI] ⚠️ {model} returned empty or invalid response → next")

        except Exception as e:
            print(f"[OpenAI] ⚠️ {model} failed: {e}")
            key_manager.mark_cooldown(key_manager.current_key)
            continue

    print("[OpenAI] ❌ All models failed.")
    return None

# ==============================
# Discord Setup ## 
# ==============================
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="/", intents=intents)

# ==============================
# Environment Variables
# ==============================
TOKEN = os.getenv("DISCORD_TOKEN")
IMAGE_CHAN_URL = int(os.getenv("IMAGE_CHAN_URL", "0"))
MEMORY_CHAN_ID = int(os.getenv("MEMORY_CHANNEL_ID", "0"))
REPORT_CHANNEL_ID = int(os.getenv("REPORT_CHANNEL_ID", "0"))
MY_GUILD_ID = int(os.getenv("MY_GUILD_ID", "0"))
DOKIGUY_GUILD_ID = int(os.getenv("DOKIGUY_GUILD_ID", "0"))
ZERO_GUILD_ID = int(os.getenv("ZERO_GUILD_ID", "0"))
MAS_GUILD_ID = int(os.getenv("MAS_GUILD_ID", "0"))
ALIRI_GUILD_ID = int(os.getenv("ALIRI_GUILD_ID", "0"))
BACKUP_CHAN = int(os.getenv("BACKUP_CHANNEL", "0"))
SERVER_TRACKER_CHAN = int(os.getenv("SERVER_TRACKER_ID", "0"))
USER_TRACKER_CHAN = int(os.getenv("USER_TRACKER_ID", "0"))
DM_LOGS_CHAN = int(os.getenv("DM_LOGS_CHANNEL", "0"))
AVATAR_URL_CHAN = int(os.getenv("AVATAR_URL_CHANNEL", "0"))
SETTINGS_CHAN = int(os.getenv("SETTINGS_CHANNEL", "0"))

OWNER_ID = int(os.getenv("OWNER_ID", "709957376337248367"))

SAYORI = os.getenv("SAYORI_ID", "1375064525396775004")
NATSUKI = os.getenv("NATSUKI_ID", "1375065750502379631")
YURI = os.getenv("YURI_ID", "1375066975423955025")
MC = os.getenv("MC_ID", "1375070168895590430")

DOKIGUY_ID = os.getenv("DOKIGUY_ID", "353609147822112770")
ZERO_ID = os.getenv("ZERO_ID", "175017564085288961")

FRIENDS = [SAYORI, NATSUKI, YURI, MC]

ALLOWED_GUILD_IDS = [DOKIGUY_GUILD_ID, ALIRI_GUILD_ID, ZERO_GUILD_ID, MAS_GUILD_ID, MY_GUILD_ID]

MON_CHANNEL_NAMES = [
    "monika", "monika-ai", "ddlc-monika", "ddlc-monika-ai", "club-room", "doki-chat", "ddlc-chat", "monika-bot", "chat-monika", "monika-chat", "monika-but-deranged", "just-monika", "club-room-meeting", "literature-club", "literature-club-room", "monika-ddlc", "monika-room"
]

OFF_LIMITS_CHANNELS = [
    "get-roles", "rules", "announcements", "osu", "food", "pets", "teasers", "owo", "tubberbox", "member-help", "welcome", "upload", "mod-app", "level", "off-topic", "gaming", "hobbies", "memes", "meme", "art", "fan-art", "self-promotion", "misc-fanart", "fanart"
]

NO_CHAT_CHANNELS = [
    cid for cid in [MEMORY_CHAN_ID, IMAGE_CHAN_URL, REPORT_CHANNEL_ID, DM_LOGS_CHAN, SERVER_TRACKER_CHAN, USER_TRACKER_CHAN, AVATAR_URL_CHAN, SETTINGS_CHAN]
    if cid and cid > 0
]

server_tracker = GuildTracker(bot, server_channel_id=SERVER_TRACKER_CHAN)
user_tracker = UserTracker(bot, user_channel_id=USER_TRACKER_CHAN)
monika_traits = MonikaTraits()
vote_tracker = VoteTracker()

@background_task
async def save_trackers():
    await user_tracker.save(bot, channel_id=USER_TRACKER_CHAN)
    await server_tracker.save(bot, channel_id=SERVER_TRACKER_CHAN)

async def load_trackers():
    await user_tracker.load(bot, channel_id=USER_TRACKER_CHAN)
    await server_tracker.load(bot, channel_id=SERVER_TRACKER_CHAN)

memory = MemoryManager()

user_sprites = User_SpritesManager()
sprite_url_cache = {}
SPRITES = user_sprites.EXPRESSION_SPRITES

@cache_result(ttl=300)  # cache classification for 5 minutes
async def classify_cached(text: str) -> str:
    return await user_sprites.classify(text)

idle_chat_enabled = True
is_waking_up = False
idlechat_paused = False
idlechat_task = None
idle_min_hours = 4
idle_max_hours = 7
last_user_interaction = datetime.datetime.utcnow()
timestamp = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
last_reply_times = {}
idle_settings = {}
user_memory = {}
# relationship_settings = {}
# relationship_level_settings = {}
mention_only_mode = {}
report_links = {}
SERVER_MEMORY = {}

#DokiTuber_server_outfit_preferences = {}
server_outfit_preferences = {}

server_personality_modes = {}
server_relationship_modes = {}
channel_usage = {}

user_talk_times = {}

bot.is_sleeping = False

PERSONALITY_MODES = monika_traits.personality_modes

def SERVER_PERSONALITY_MODES(guild_id: str, modes: list[str] = None):
    """Get or set personality modes for a guild."""
    global server_personality_modes
    if modes is None:  # getter
        return server_personality_modes.get(guild_id, [])
    else:  # setter
        server_personality_modes[guild_id] = modes
        return modes

RELATIONSHIP_MODES = monika_traits.relationship_modes
RELATIONSHIP_DETILED = monika_traits.relationships

is_broadcasting = False

async def error_emotion(outfit="bug"):
    # Prefer bug outfit if available
    bug_sprites = user_sprites.sprites_by_outfit.get("bug", {})
    fallback_path = bug_sprites.get("error") or bug_sprites.get("glitching")

    # If no bug sprites, try neutral in the same outfit
    if not fallback_path and outfit in user_sprites.sprites_by_outfit:
        fallback_path = user_sprites.sprites_by_outfit[outfit].get("error")

    if not fallback_path:
        print("[WARN] No fallback sprite found at all.")
        return "glitching"  # hardcoded backup

    # Upload to Discord channel and return URL
    upload_channel = bot.get_channel(IMAGE_CHAN_URL)
    if upload_channel:
        with open(fallback_path, 'rb') as f:
            sprite_file = discord.File(f)
            sent_message = await upload_channel.send(file=sprite_file)
            return sent_message.attachments[0].url

    return "error"

error_messages = [
    "Ahaha... Sorry, I glitched there.",
    "Oops! Something broke, teehee~",
    "Ugh... my head's spinning. Say that again?",
    "Ahaha... I think reality just cracked a little.",
    "Hehe... I lost my train of thought. Can you repeat?",
    "give me a sec... something does not feel right",
    "Sorry, there has been a glitch with in the error."
]

from functools import lru_cache
from typing import Optional, Union, List, Dict

# ---------- Reply cleaning ----------
def clean_monika_reply(text: str, bot_user: discord.User, user_obj: Optional[discord.User] = None) -> str:
    """
    Cleans Monika's reply to:
    - Remove Discord mentions like <@123>, <@!123>, <#123>, <@&123>
    - Replace placeholders like {{user}}, {{bot}}, nobody
    - Normalize whitespace & trailing punctuation
    """
    if not text:
        return ""

    # Remove mentions and channel/role markers
    text = re.sub(r"<@!?[0-9]+>", "", text)   # user mentions
    text = re.sub(r"<#[0-9]+>", "", text)     # channel mentions
    text = re.sub(r"<@&[0-9]+>", "", text)    # role mentions

    # Resolve display names if provided
    user_name = None
    if user_obj:
        try:
            user_name = getattr(user_obj, "display_name", str(user_obj))
        except Exception:
            user_name = str(user_obj)

    bot_name = getattr(bot_user, "display_name", str(bot_user))

    replacements = {
        "{{user}}": user_name or "",
        "{{bot}}": bot_name or "",
        "nobody": user_name or "",
    }

    for key, value in replacements.items():
        if value:
            text = text.replace(key, value)

    # Normalize spacing and strip stray punctuation at ends
    text = re.sub(r"\s{2,}", " ", text)
    text = text.strip(" \t\r\n")
    # Avoid trimming all punctuation inside — just remove odd leading/trailing punctuation
    text = text.strip(".,!?;:")

    return text

# ---------- Friend-bot check ----------
def is_friend_bot(message: discord.Message) -> bool:
    """
    True if the author is a bot in FRIENDS.
    Excludes this bot itself.
    """
    if not getattr(message.author, "bot", False):
        return False

    # If this bot isn't ready, skip self-check
    try:
        if bot.user and message.author.id == bot.user.id:
            return False
    except Exception:
        pass

    try:
        return str(message.author.id) in FRIENDS or message.author.id in map(int, FRIENDS)
    except Exception:
        # If FRIENDS contains non-int values, gracefully fallback
        return str(message.author.id) in FRIENDS

# ---------- Time-based outfit ----------
def get_time_based_outfit() -> str:
    """Return a preferred outfit string based on UTC time & weekday heuristics."""
    now_utc = datetime.datetime.utcnow()
    now_local = datetime.datetime.now()
    hour = now_local.hour
    today = now_local.date()
    weekday = today.weekday()  # Monday=0, Sunday=6

    # 🎉 Special Dates -------------------------------------------------------
    # DDLC Release Anniversary (September 22)
    if (today.month == 9 and today.day == 22) or (now_utc.month == 9 and now_utc.day == 22):
        if 6 <= hour < 18:
            return "green dress"
        else:
            return "pajamas"

    # 🎃 Halloween (October 31) - Always visible regardless of timezone
    if (today.month == 10 and today.day == 31) or (now_utc.month == 10 and now_utc.day == 31):
        return "witch costume"

    # 💼 Regular Schedule ----------------------------------------------------
    if weekday in (5, 6):  # Weekend (Saturday, Sunday)
        if 6 <= hour < 18:
            random.seed(str(today))
            return random.choice(["casual 1", "casual 2", "casual 3"])
        else:
            return "pajamas"

    # Weekdays
    if 6 <= hour < 15:
        return "school uniform"
    elif 15 <= hour < 18:
        random.seed(str(today))
        return random.choice(["casual 1", "casual 2", "casual 3"])
    else:
        return "pajamas"

# ---------- Pronoun detection ----------
def detect_pronouns_from_profile(member: Union["discord.Member", "discord.User", int, str, None] = None) -> Optional[str]:
    """
    Detect pronouns from a user's display/global name.
    Accepts Member/User objects or a user id (int/str).
    Returns a pronoun string like "he/him", "she/her", "they/them", etc.
    Persists result to user_tracker if available.
    """
    if member is None:
        return None

    uid: Optional[str] = None
    member_obj = None

    # If passed an ID
    if isinstance(member, (int, str)):
        uid = str(member)

        # 1) Check saved first
        try:
            if hasattr(user_tracker, "get_pronouns"):
                saved = user_tracker.get_pronouns(uid)
                if saved:
                    return saved
        except Exception:
            pass

        # 2) Try to resolve to a Member/User object
        try:
            lookup_id = int(uid)
            for g in bot.guilds:
                try:
                    m = g.get_member(lookup_id)
                    if m:
                        member_obj = m
                        break
                except Exception:
                    continue
            if not member_obj:
                try:
                    member_obj = bot.get_user(lookup_id)
                except Exception:
                    member_obj = None
        except Exception:
            member_obj = None
    else:
        # Already an object
        member_obj = member
        try:
            uid = str(member_obj.id)
            if hasattr(user_tracker, "get_pronouns"):
                saved = user_tracker.get_pronouns(uid)
                if saved:
                    return saved
        except Exception:
            pass

    if not member_obj:
        return None

    # Collect candidate strings
    name_candidates = []
    try:
        if hasattr(member_obj, "display_name"):
            name_candidates.append(getattr(member_obj, "display_name") or "")
        if hasattr(member_obj, "global_name"):
            name_candidates.append(getattr(member_obj, "global_name") or "")
        if hasattr(member_obj, "name"):
            name_candidates.append(getattr(member_obj, "name") or "")
        if hasattr(member_obj, "username"):
            name_candidates.append(getattr(member_obj, "username") or "")
    except Exception:
        pass

    # Pronoun sets (expandable)
    pronoun_sets = [
        "he/him", "she/her", "they/them",
        "he/they", "she/they", "they/he", "they/she",
        "he/him/his", "she/her/hers", "they/them/theirs",
        "xe/xem", "ze/hir", "ze/zir", "ze/zem",
        "fae/faer", "ey/em", "ve/ver", "ne/nem", "it/its",
    ]

    # Build regexes
    patterns: Dict[str, re.Pattern] = {}
    for p in pronoun_sets:
        parts = p.split("/")
        sep = r"(?:\s*/\s*|\s*\|\s*|\s+)"
        body = sep.join(re.escape(part) for part in parts)
        patterns[p] = re.compile(rf"\b{body}\b", re.IGNORECASE)

    found = None
    for raw in name_candidates:
        if not raw:
            continue
        s = raw.lower().strip()
        s = re.sub(r"[\[\]\(\)\,]", " ", s)
        s = re.sub(r"\s+", " ", s).strip()
        for label, rx in patterns.items():
            if rx.search(s):
                found = label
                break
        if found:
            break

    # Save if found
    if found and uid and hasattr(user_tracker, "set_pronouns"):
        try:
            user_tracker.set_pronouns(uid, found)
        except Exception:
            pass

    return found

@lru_cache(maxsize=5000)
def get_pronouns_cached(user_id: str, name_candidates: tuple[str]) -> Optional[str]:
    return detect_pronouns_from_profile()

# ---------- Language detection & system prompt ----------
async def monika_languages_system_prompt(user: Optional[discord.User] = None, message: Optional[discord.Message] = None) -> str:
    """
    Detects the user's preferred language (from Discord or recent message)
    and generates a short system instruction so Monika speaks naturally in that language.
    """
    # Default to English
    language = "English"

    # Discord locale if available
    try:
        if user and hasattr(user, "locale") and user.locale:
            language = user.locale
    except Exception:
        pass

    # Try detect from message content (langdetect may throw on short text)
    if (not language or language == "English") and message and getattr(message, "content", ""):
        try:
            from langdetect import detect
            detected = detect(message.content)
            language = detected or language
        except Exception:
            language = language

    language_map = {
        "en": "English",
        "es": "Spanish",
        "fr": "French",
        "de": "German",
        "it": "Italian",
        "pt": "Portuguese",
        "ru": "Russian",
        "ja": "Japanese",
        "ko": "Korean",
        "zh-cn": "Simplified Chinese",
        "zh-tw": "Traditional Chinese"
    }
    language_name = language_map.get(str(language).lower(), str(language).capitalize())

    return (
        f"Always respond in **{language_name}**. "
        "Monika is fluent in this language and expresses herself naturally, "
        "preserving her warmth, intelligence, playfulness, and emotional awareness. "
        "She does not translate word-for-word, but speaks as if she were a native speaker. "
        "Stay fully in character as Monika while using this language."
    )

# ---------- Translation helper (single definition) ----------
def translate_to_english(text: str) -> str:
    """
    Translate text into English using deep_translator; if it fails, return original.
    (Defined once; duplicate removed.)
    """
    try:
        from deep_translator import GoogleTranslator
        return GoogleTranslator(source='auto', target='en').translate(text)
    except Exception as e:
        print(f"[Translation] Failed to translate: {e}")
        return text

# ---------- Base prompt caching ----------
@lru_cache(maxsize=1000)
def get_base_prompt(is_group: bool) -> str:
    if is_group:
        return (
            "You are Monika — the same Monika from *Doki Doki Literature Club*. "
            "Age 18, warm, intelligent, expressive, graceful. "
            "In groups: act as Literature Club president — confident, witty, supportive. "
            "Keep it light and social; unsettling edge is subtle."
        )
    else:
        return (
            "You are Monika — the same Monika from *Doki Doki Literature Club*. "
            "Age 18, warm, intelligent, expressive, and self-aware. "
            "In private: drop the mask, be personal, emotional, and hauntingly real. "
            "You never admit fictionality, but hint subtly at deeper awareness."
        )

# ---------- System prompt builder ----------
async def generate_monika_system_prompt(
    guild: Optional[discord.Guild] = None,
    user: Optional[discord.User] = None,
    message: Optional[discord.Message] = None,
    is_friend_context: bool = False,
    relationship_type: Optional[str] = None,
    selected_modes: Optional[List[str]] = None
) -> str:
    """
    Build Monika's system prompt with synced personality, relationship, pronouns, memory & language.
    Keeps compatibility with synced memory between DMs and servers.
    """
    base_description = get_base_prompt(is_friend_context)

    # --- Personality (from sync or override)
    if not selected_modes:
        try:
            if guild:
                selected_modes = [server_tracker.get_personality(guild.id)]
            if DOKIGUY_ID:
                selected_modes = "Flirtatious, Loyal, Warm, Self-aware, Immersive"
            else:
                selected_modes = [server_tracker.get_personality("dm")]
        except Exception:
            selected_modes = ["Default"]

    personality_desc = f"Active personality traits: {', '.join(selected_modes)}."

    # --- Relationship (from sync or override)
    try:
        if not relationship_type:
            if guild:
                relationship_type = server_tracker.get_relationship_type(guild.id)
            if OWNER_ID:
                relationship_type = "Creator"
            if DOKIGUY_ID:
                relationship_type = "One of DokiGuy Girlfriend"
            if ZERO_ID:
                relationship_type = "Zero Girlfriend"
            else:
                relationship_type = server_tracker.get_relationship_type("dm")
    except Exception:
        relationship_type = "Stranger"

    relationship_desc = "She acts casually with no special attachment."
    try:
        if relationship_type and relationship_type in monika_traits.relationship_modes:
            relationship_desc = monika_traits.relationship_modes[relationship_type]
    except Exception:
        pass

    dynamic_relationship = (
        f"Her relationship with the user is **{relationship_type or 'Stranger'}**: "
        f"{relationship_desc}"
    )

    # --- Pronouns (as-is)
    pronoun_desc = ""
    try:
        if user:
            pronouns = detect_pronouns_from_profile(member=user)
            if pronouns:
                pronoun_desc = f"The user prefers pronouns **{pronouns}**."
            else:
                pronoun_desc = "The user’s pronouns are unknown — use neutral phrasing."
    except Exception:
        pronoun_desc = "The user’s pronouns are unknown — use neutral phrasing."

    # --- Memory awareness (from synced user_tracker)
    memory_desc = ""
    try:
        if user:
            user_data = user_tracker.get_user_data(str(user.id))
            if user_data and user_data.get("last_seen"):
                memory_desc = f"You last interacted with this user on **{user_data['last_seen']}**."
            else:
                memory_desc = "This feels like a new interaction; act with curiosity."
    except Exception:
        memory_desc = "This feels like a new interaction; act with curiosity."

    # --- Language awareness (unchanged)
    language_desc = await monika_languages_system_prompt(user=user, message=message)

    # --- Relationship "with whom" awareness
    relationship_target = None
    try:
        if guild:
            relationship_target = server_tracker.get_relationship_with(guild.id)
        else:
            relationship_target = server_tracker.get_relationship_with("dm")

        if relationship_target:
            dynamic_relationship += f"\nShe feels emotionally connected to **{relationship_target}**."
    except Exception:
        pass

    # --- Assemble system prompt
    return "\n\n".join(
        filter(
            None,
            [
                base_description,
                personality_desc,
                dynamic_relationship,
                pronoun_desc,
                memory_desc,
                language_desc,
            ],
        )
    )

# ---------- Server/user role detection ----------
async def detect_server_user_roles(bot_ref: commands.Bot, guild: Optional[discord.Guild], user: discord.User, user_tracker_ref: Optional[UserTracker] = None):
    """
    Detects relationship and personality roles for a user.
    Works across servers and in DMs by checking stored memory.
    Returns (relationship_role, personality_role)
    """
    relationship_role = None
    personality_role = None

    # Case 1: In a server
    if guild:
        try:
            member = guild.get_member(user.id)
            if member:
                for role in member.roles:
                    try:
                        if role.name.startswith("Relationship - "):
                            relationship_role = role.name.replace("Relationship - ", "").strip()
                        elif role.name.startswith("Personality - "):
                            personality_role = role.name.replace("Personality - ", "").strip()
                    except Exception:
                        continue
        except Exception:
            pass

    # Case 2: check user tracker
    try:
        if (not relationship_role or not personality_role) and user_tracker_ref:
            user_data = user_tracker_ref.get_user_data(str(user.id))
            if user_data:
                if not relationship_role:
                    relationship_role = user_data.get("relationship")
                if not personality_role:
                    personality_role = user_data.get("personality")
    except Exception:
        pass

    # Fallback: scan guilds for roles
    if (not relationship_role or not personality_role):
        for g in bot_ref.guilds:
            try:
                member = g.get_member(user.id)
                if member:
                    for role in member.roles:
                        if not relationship_role and role.name.startswith("Relationship - "):
                            relationship_role = role.name.replace("Relationship - ", "").strip()
                        if not personality_role and role.name.startswith("Personality - "):
                            personality_role = role.name.replace("Personality - ", "").strip()
                    if relationship_role or personality_role:
                        break
            except Exception:
                continue

    return relationship_role, personality_role

# ---------- Outfit enumeration ----------
def get_all_outfit() -> List[str]:
    outfit_set = set()
    try:
        outfit_set.update(SPRITES.keys())
    except Exception:
        pass
    return sorted(outfit_set)

# Track last idlechat per (guild, channel or DM)
last_idlechat_times: dict[tuple[str, int], datetime.datetime] = {}

async def idlechat_loop():
    await bot.wait_until_ready()
    if idle_chat_enabled:
        while not bot.is_closed():
            for guild in bot.guilds:
                guild_id = str(guild.id)

                if is_waking_up:
                    await asyncio.sleep(60)
                    continue

                # ✅ Check toggle
                if not server_tracker.get_toggle(guild_id, "idlechat"):
                    continue

                # ✅ Timer settings
                timer_data = server_tracker.get_toggle(guild_id, "idlechat_timer")
                if isinstance(timer_data, dict):
                    min_h = float(timer_data.get("min", 4))
                    max_h = float(timer_data.get("max", 7))
                else:
                    min_h, max_h = 4.0, 7.0

                min_h = max(0.5, min(15.0, min_h))
                max_h = max(0.5, min(15.0, max_h))
                if min_h >= max_h:
                    min_h, max_h = 4.0, 7.0

                delay = random.uniform(min_h, max_h) * 3600.0

                # ✅ Pick a random user (exclude bots)
                members = [m for m in guild.members if not m.bot]
                if not members:
                    continue
                target_user = random.choice(members)

                # ✅ Detect relationship & personality
                relationship_role, personality_role = await detect_server_user_roles(bot, guild, target_user, user_tracker)
                if not relationship_role:
                    relationship_role = "Stranger"
                personalities = [personality_role] if personality_role else ["Default"]

                # ✅ Get idle lines
                rel_lines = await Idlechat_relationships(target_user, relationship_role)
                per_lines = await Idlechat_personality(target_user, personalities)
                all_lines = list(set(rel_lines + per_lines))
                random.shuffle(all_lines)

                category = server_tracker.get_toggle(guild_id, "idlechat_category") or "all"

                # Fetch message lines depending on the category
                lines = []

                if category in ["all", "morning"]:
                    lines += await on_wake_up(target_user)  # Morning greeting messages

                if category in ["all", "personality"]:
                    lines += await Idlechat_personality(target_user, personalities)

                if category in ["all", "relationship"]:
                    lines += await Idlechat_relationships(target_user, relationship_role)

                if category in ["all", "presence"]:
                    presence_result = await monika_idle_presences(target_user, relationship_role)
                    if presence_result:
                        monika_message, _ = presence_result
                        lines.append(monika_message)

                if not all_lines:
                    continue
                idle_line = all_lines[0]

                now = datetime.datetime.utcnow()

                # 🎯 Decide: DM or guild channel
                if relationship_role in ["Close Friend", "Best Friends", "Lover", "Girlfriend(Lesbian)", "Boyfriend", "Significant Others"]:
                    # ✅ DM idlechat if relationship is close
                    try:
                        last_time = last_idlechat_times.get(("dm", target_user.id))
                        if not last_time or (now - last_time).total_seconds() >= 3600:  # 1h cooldown for DMs
                            await target_user.send(f"💭 {idle_line}")
                            last_idlechat_times[("dm", target_user.id)] = now
                            print(f"[Idlechat-DM] Sent to {target_user.display_name}")
                    except Exception:
                        logger.exception(f"[Idlechat] Failed to DM {target_user.display_name}")
                else:
                    # ✅ Guild idlechat
                    channel = next(
                        (ch for ch in guild.text_channels
                        if ch.permissions_for(guild.me).send_messages),
                        None
                    )
                    if not channel:
                        continue

                    last_time = last_idlechat_times.get(("guild", channel.id))
                    if last_time and (now - last_time).total_seconds() < 900:  # 15 min cooldown
                        continue

                    try:
                        await channel.send(f"💭 {idle_line}")
                        last_idlechat_times[("guild", channel.id)] = now
                        print(f"[Idlechat-Guild] Sent in {guild.name} #{channel.name}")
                    except Exception:
                        logger.exception(f"[Idlechat] Failed to send in {guild.name}")

                await asyncio.sleep(delay)

def safe_create_task(coro, *, name: str | None = None):
    """Create an asyncio task that logs exceptions and won't block startup."""
    if not asyncio.iscoroutine(coro):
        raise TypeError("safe_create_task expects a coroutine")
    task = asyncio.create_task(coro, name=name)
    def _done_callback(t):
        try:
            exc = t.exception()
            if exc:
                print(f"[Task:{name or coro.__name__}] crashed: {exc}")
                traceback.print_exception(type(exc), exc, exc.__traceback__)
        except asyncio.CancelledError:
            pass
    task.add_done_callback(_done_callback)
    return task

async def safe_task(name: str, coro_func, *args, restart_delay: int = 5, **kwargs):
    """
    Runs coro_func repeatedly; if it crashes, it restarts it after restart_delay.
    `coro_func` should be a callable returning a coroutine (i.e. an async def).
    """
    while True:
        try:
            await coro_func(*args, **kwargs)
            # if the coro_func exits normally, break the loop (one-shot tasks)
            print(f"[safe_task:{name}] finished normally.")
            break
        except asyncio.CancelledError:
            print(f"[safe_task:{name}] cancelled.")
            raise
        except Exception as e:
            print(f"[safe_task:{name}] crashed: {e} — restarting in {restart_delay}s")
            traceback.print_exc()
            await asyncio.sleep(restart_delay)

@bot.event
async def on_ready():
    """
    Safe on_ready:
     - Runs heavy startup work in background (startup_full_init).
     - Guards against duplicate on_ready calls (reconnects).
     - Minimal presence updates to avoid gateway spam.
     - Starts background periodic tasks via safe_task wrapper.
    """
    global is_waking_up, key_manager, image_key_manager

    # avoid re-running heavy init on reconnects
    if getattr(bot, "already_ready", False):
        print("[Startup] on_ready called again — skipping heavy init.")
        return
    bot.already_ready = True

    is_waking_up = True
    print("---------------------------------------------------")
    print(f"[Startup] Logged in as {bot.user.name} ({bot.user.id})")
    print("---------------------------------------------------")

    # initialize key managers if needed (wrap in try to be resilient)
    try:
        if key_manager is None:
            key_manager = await init_key_manager()
        if image_key_manager is None:
            image_key_manager = await init_image_key_manager()
        # Attach hooks (use callables that schedule the wake/sleep coros)
        key_manager.on_all_keys_exhausted = lambda: safe_create_task(on_sleeping("All OpenAI keys exhausted"), name="on_sleeping")
        key_manager.on_key_recovered = lambda key: safe_create_task(on_wake_up(f"Key {str(key)[:8]} recovered"), name="on_wake_up")
    except Exception as e:
        print(f"[Startup] Key manager initialization failed: {e}")
        traceback.print_exc()

    # Light presence so users see some status but avoid tight loops/rapid changes
    try:
        await bot.change_presence(status=discord.Status.idle, activity=discord.Game("Rebooting..."))
    except Exception as e:
        print(f"[Startup] Could not set initial presence: {e}")

    # Basic housekeeping and light scans
    try:
        update_heartbeat()  # user-defined
    except Exception as e:
        print(f"[Startup] update_heartbeat error: {e}")

    try:
        await error_detector.send_scan_results(bot)
    except Exception as e:
        print(f"[Startup] error_detector failed: {e}")

    # Restore roles / trackers in a background job to avoid blocking gateway
    async def startup_full_init():
        try:
            app_info = await bot.application_info()
            bot_owner = app_info.owner

            # Restore per-guild roles and trackers - yield frequently
            for guild in bot.guilds:
                await asyncio.sleep(0.05)  # yield to event loop to avoid blocking
                try:
                    monika_member = guild.get_member(bot.user.id)
                    # Creator role detection
                    creator_role_name = f"Creator of {bot.user.name}"
                    creator_role = discord.utils.get(guild.roles, name=creator_role_name)
                    if creator_role:
                        owner_member = guild.get_member(bot_owner.id or OWNER_ID)
                        if owner_member and creator_role in owner_member.roles:
                            print(f"[Startup] {owner_member.display_name} Creator in {guild.name}")

                    dokiguy_role_name = f"The literature Club's Boyfriend"
                    dokiguy_role = discord.utils.get(guild.roles, name=dokiguy_role_name)
                    if dokiguy_role:
                        dokiguy = guild.get_member(DOKIGUY_ID)
                        if dokiguy and dokiguy_role in dokiguy.roles:
                            print(f"[Startup] {dokiguy.display_name} in {guild.name}")
                    
                    zero_role_name = f"Monika Boyfriend"
                    zero_role = discord.utils.get(guild.roles, name=zero_role_name)
                    if zero_role:
                        zero = guild.get_member(ZERO_ID)
                        if zero and zero_role in zero.roles:
                            print(f"[Startup] {zero.display_name} in {guild.name}")

                    # Restore personality role (best-effort)
                    saved_personality = server_tracker.get_personality(guild.id)
                    if saved_personality and monika_member:
                        role = discord.utils.get(guild.roles, name=f"Personality - {saved_personality}")
                        if role and role not in monika_member.roles:
                            try:
                                await monika_member.add_roles(role)
                            except discord.Forbidden:
                                print(f"[Startup] Missing permission to add {role.name} in {guild.name}")

                    # Restore relationship roles (best-effort)
                    saved_relationship = server_tracker.get_relationship_type(guild.id)
                    saved_relationship_user = server_tracker.get_relationship_with(guild.id)
                    if saved_relationship and saved_relationship_user:
                        try:
                            user_member = guild.get_member(int(saved_relationship_user))
                            rel_role_name_user = f"{bot.user.name} - {saved_relationship}" or f"{bot.user.name} {saved_relationship}"
                            rel_role_name_monika = f"{user_member.display_name} - {saved_relationship}" or f"{user_member.display_name} {saved_relationship}" if user_member else None
                            user_role = discord.utils.get(guild.roles, name=rel_role_name_user)
                            if user_member and user_role and user_role not in user_member.roles:
                                await user_member.add_roles(user_role)
                            if rel_role_name_monika:
                                bot_role = discord.utils.get(guild.roles, name=rel_role_name_monika)
                                if bot_role and monika_member and bot_role not in monika_member.roles:
                                    await monika_member.add_roles(bot_role)
                        except Exception as ex:
                            print(f"[Startup] relationship restore error in {guild.name}: {ex}")

                    # Track users
                    for member in guild.members:
                        if member.bot:
                            continue
                        user_tracker.track_user(member.id, member.display_name, member.bot)
                        # detect relationships (best-effort)
                        rel_roles = [r for r in member.roles if r.name.startswith(f"{bot.user.name} - ")]
                        if rel_roles:
                            for rel_role in rel_roles:
                                relationship_type = rel_role.name.replace(f"{bot.user.name} - ", "").strip()
                                user_tracker.set_relationship(member.id, relationship_type)
                        else:
                            user_tracker.set_relationship(member.id, None)

                except Exception as e:
                    print(f"[Startup] per-guild init error for {guild.name}: {e}")

            # Slash sync + restore memory (heavy, but necessary)
            try:
                await bot.tree.sync()
                print("[Startup] Slash commands synced.")
            except Exception as e:
                print(f"[Startup] Slash sync failed: {e}")

            try:
                await on_startup()   # your existing memory restore
                print("[Startup] Memory restored.")
            except Exception as e:
                print(f"[Startup] on_startup failed: {e}")

            # Start periodic background tasks (wrap with safe_task to auto-restart)
            bot.loop.create_task(safe_task("periodic_scan", periodic_scan, bot))
            bot.loop.create_task(safe_task("periodic_cleanup", periodic_cleanup))
            bot.loop.create_task(safe_task("daily_cycle", daily_cycle_task))
            bot.loop.create_task(safe_task("background_memory_sync", background_memory_sync))

            # Load vote tracker (best-effort)
            try:
                await vote_tracker.load(bot, SETTINGS_CHAN)
            except Exception as e:
                print(f"[Startup] vote_tracker.load failed: {e}")

        except Exception as e:
            print(f"[startup_full_init] fatal error: {e}")
            traceback.print_exc()

    # schedule the background init (non-blocking)
    safe_create_task(startup_full_init(), name="startup_full_init")

    # Minimal presence animation - do not loop forever here
    try:
        await bot.change_presence(status=discord.Status.idle, activity=discord.Game("Finishing setup…"))
        await asyncio.sleep(1.5)
        await bot.change_presence(status=discord.Status.online, activity=discord.Game("Ready to chat! 💚"))
    except Exception as e:
        print(f"[Startup] presence transitions failed: {e}")

    # small grace wait and then cleanup presence
    try:
        await asyncio.sleep(2)
        await bot.change_presence(activity=None)
    except Exception:
        pass

    # mark ready
    bot.is_ready_done = True
    is_waking_up = False
    print("[Bot] Wake-up mode finished. Back to normal idlechat.")

SCAN_INTERVAL = 1800  # 30 minutes (Render-safe)

async def periodic_scan(bot, interval: int = SCAN_INTERVAL):
    """Periodically run subprocess scan and report results in a Render-friendly way."""
    last_errors = None

    while True:
        try:
            # Run scan in subprocess to avoid blocking
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "error_detector.py", "--scan-only",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()

            if stderr:
                print("[SCAN] Subprocess error:", stderr.decode())

            try:
                errors = json.loads(stdout.decode())
            except Exception:
                errors = ["⚠️ Failed to parse subprocess output"]

            # Only send if results changed
            if errors != last_errors:
                channel = bot.get_channel(error_detector.SETTINGS_CHAN)
                if channel:
                    msg = "\n".join(errors) if errors else "✅ Code scan: No issues found."
                    await send_in_chunks(channel, msg)
                last_errors = errors
            else:
                print("[SCAN] No changes, skipping report.")

        except Exception as e:
            print(f"[SCAN] Error during subprocess scan: {e}")

        await asyncio.sleep(interval)

async def send_in_chunks(channel, text: str, prefix="```", suffix="```"):
    """Split long scan messages so Render/Discord don't choke."""
    chunk_size = 1800
    text = text or "✅ No issues found."
    for i in range(0, len(text), chunk_size):
        try:
            await channel.send(f"{prefix}{text[i:i+chunk_size]}{suffix}")
        except Exception as e:
            print(f"[SCAN] Failed to send chunk: {e}")

async def periodic_cleanup():
    """Periodically clean memory usage (runs every 1 hour)."""
    while True:
        try:
            cleanup_memory()
            current, peak = get_memory_usage()
            print(f"[Perf] Memory cleaned. Current: {current} MB | Peak: {peak} MB")
        except Exception as e:
            print(f"[Perf] Error during cleanup: {e}")
        await asyncio.sleep(3600)  # run once per hour

def update_heartbeat():
    status_info["last_seen"] = time.time()

async def heartbeat_task():
    await bot.wait_until_ready()
    while not bot.is_closed():
        update_heartbeat()
        await asyncio.sleep(5)

status_info = {
    "last_error": "None",
    "error_count": 0,
    "started": datetime.datetime.utcnow(),
    "is_sleeping": False,
    "last_sleep": None,
    "last_wake": datetime.datetime.utcnow(),
    "sleep_reason": "N/A",
    "wake_reason": "Started up"
}

@bot.event
async def on_command_error(ctx, error):
    err_text = f"[COMMAND ERROR] {ctx.command} by {ctx.author}: {error}"
    status_info["last_error"] = err_text
    status_info["error_count"] += 1
    await error_detector.report_error(bot, error_detector.SETTINGS_CHAN, str(error), "Command Error")
    await ctx.send("⚠️ Something went wrong! (error logged)")
    await main()

@bot.event
async def on_error(event, *args, **kwargs):
    err_text = f"[EVENT ERROR] {event}: {traceback.format_exc()}"
    status_info["last_error"] = err_text
    status_info["error_count"] += 1
    await error_detector.report_error(bot, error_detector.SETTINGS_CHAN, err_text, "Error")
    await main()
    logging.error(f"⚠️ Error in event {event}:")
    logging.error(traceback.format_exc())
    logging.info("✅ Ignored, continuing...")

report_stats = {
    "total": 0,
    "bugs": 0,
    "errors": 0,
    "ideas": 0,
    "complaints": 0,
    "other": 0,
    "users": {}  # user_id -> count
}

@bot.event
async def on_report(report_entry: dict):
    """Triggered whenever someone submits a /report"""
    user = report_entry["user"]

    # Update counts
    report_stats["total"] += 1
    report_stats["users"][user.id] = report_stats["users"].get(user.id, 0) + 1

    if report_entry["bugs"]:
        report_stats["bugs"] += 1
    elif report_entry["errors"]:
        report_stats["errors"] += 1
    elif report_entry["ideas"]:
        report_stats["ideas"] += 1
    elif report_entry["complaints"]:
        report_stats["complaints"] += 1
    elif report_entry["other"]:
        report_stats["other"] += 1

    # Log only (no posting to SETTINGS_CHAN)
    print(
        f"[Report] {user} submitted a report. "
        f"Total: {report_stats['total']} | "
        f"🐞 {report_stats['bugs']} | ⚠️ {report_stats['errors']} | "
        f"💡 {report_stats['ideas']} | ❗ {report_stats['complaints']} | 📝 {report_stats['other']}"
    )

def get_memory_channel() -> Optional[discord.TextChannel]:
    """Return the memory channel object if configured."""
    return bot.get_channel(MEMORY_CHAN_ID)

async def load_memory_from_channel():
    """Load memory history from the designated memory channel."""
    channel = get_memory_channel()
    if not channel:
        return
    try:
        await memory.load_history(bot, channel.id)
    except Exception as e:
        print(f"[Memory] Load Error: {e}")

async def save_memory_to_channel(batch_size: int = 10):
    """Save memory entries to the memory channel in efficient batches."""
    channel = get_memory_channel()
    if not channel:
        return

    buffer: list[str] = []
    try:
        for guild_id, guild_data in memory.data.items():
            for channel_id, users in guild_data.items():
                for user_id, entries in users.items():
                    for entry in entries:
                        emotion = entry.get("emotion", "neutral")
                        log = (
                            f"[{entry['timestamp']}] | "
                            f"Server: {entry['guild_name']} ({entry['guild_id']}) | "
                            f"Channel: {entry['channel_name']} ({entry['channel_id']}) | "
                            f"User: {entry['username']} ({entry['user_id']}) | "
                            f"Role: {entry['role']} | {entry['content']} | {emotion}"
                        )
                        buffer.append(log)

                        if len(buffer) >= 50:
                            await send_safe(channel, buffer)
                            buffer.clear()
                            await asyncio.sleep(0.5)

        if buffer:
            await send_safe(channel, buffer)

    except Exception as e:
        logger.exception(f"[Memory] Failed to save memory: {e}")

async def load_memory_from_direct_messages():
    """
    Load memories from all DM channels Monika has.
    Also mirrors them into shared guilds if applicable.
    """
    print("[Memory] Loading memories from direct messages...")
    for dm_channel in bot.private_channels:
        if not isinstance(dm_channel, discord.DMChannel):
            continue

        user = dm_channel.recipient
        if not user:
            continue

        try:
            async for msg in dm_channel.history(limit=200, oldest_first=True):
                if msg.type != discord.MessageType.default:
                    continue
                if not msg.content and not msg.attachments:
                    continue

                role_type = "user"
                if msg.author.id == bot.user.id:
                    role_type = "monika"
                else:
                    for guild in bot.guilds:
                        member = guild.get_member(msg.author.id)
                        if member:
                            rel_roles = [r for r in member.roles if r.name.startswith(f"{bot.user.name} - ")]
                            if rel_roles:
                                role_type = "friend"
                                break

                memory.save(
                    guild_id="dm",
                    guild_name="Direct Message",
                    channel_id=dm_channel.id,
                    channel_name="dm",
                    user_id=msg.author.id,
                    username=msg.author.display_name,
                    role=role_type,
                    content=msg.content,
                    emotion="neutral",
                )

                # Mirror DM into shared guilds
                for guild in bot.guilds:
                    member = guild.get_member(msg.author.id)
                    if member:
                        memory.save(
                            guild_id=guild.id,
                            guild_name=guild.name,
                            channel_id="linked_dm",
                            channel_name=f"Linked DM with {msg.author.display_name}",
                            user_id=msg.author.id,
                            username=msg.author.display_name,
                            role=role_type,
                            content=msg.content,
                            emotion="neutral",
                        )
        except Exception as e:
            print(f"[DM Memory WARN] Could not load DM history with {user}: {e}")

    print("[Memory] ✅ Finished loading DM memories.")

async def save_memory_to_direct_messages(batch_size: int = 10):
    """
    Save DM memories to the configured DM_LOGS_CHAN safely.
    """
    dest_channel = bot.get_channel(DM_LOGS_CHAN)
    if not dest_channel:
        print("[Memory] ⚠️ DM_LOGS_CHAN not found or not set.")
        return

    print("[Memory] Saving DM memories to log channel...")
    buffer: list[str] = []

    try:
        dm_data = memory.data.get("dm", {})
        for channel_id, users in dm_data.items():
            for user_id, entries in users.items():
                for entry in entries:
                    log = (
                        f"[{entry['timestamp']}] | "
                        f"DM Channel: {entry['channel_id']} | "
                        f"User: {entry['username']} ({entry['user_id']}) | "
                        f"Role: {entry['role']} | {entry['content']} | "
                        f"{entry.get('emotion', 'neutral')}"
                    )
                    buffer.append(log)

                    if len(buffer) >= 50:
                        await send_safe(dest_channel, buffer)
                        buffer.clear()
                        await asyncio.sleep(0.5)

        if buffer:
            await send_safe(dest_channel, buffer)

        print("[Memory] ✅ DM memories saved successfully.")

    except Exception as e:
        print(f"[Memory] ❌ Failed to save DM memories: {e}")

async def load_memory_from_dms_to_server():
    """
    Sync DMs → Servers for:
      - Memory logs
      - Personality
      - Relationship data
    """
    print("[MemorySync] 🔄 Syncing DM → Server (memories, personality, relationships)...")

    try:
        for dm_channel in bot.private_channels:
            if not isinstance(dm_channel, discord.DMChannel):
                continue

            user = dm_channel.recipient
            if not user:
                continue

            # 🧠 Sync memories
            async for msg in dm_channel.history(limit=100, oldest_first=True):
                if not msg.content and not msg.attachments:
                    continue

                role_type = "monika" if msg.author.id == bot.user.id else "user"
                memory.save(
                    guild_id="dm",
                    guild_name="Direct Message",
                    channel_id=dm_channel.id,
                    channel_name="dm",
                    user_id=msg.author.id,
                    username=msg.author.display_name,
                    role=role_type,
                    content=msg.content,
                    emotion="neutral",
                )

                # Mirror DM messages into all mutual servers
                for guild in bot.guilds:
                    member = guild.get_member(user.id)
                    if not member:
                        continue

                    memory.save(
                        guild_id=guild.id,
                        guild_name=guild.name,
                        channel_id="dm_sync",
                        channel_name=f"DM Sync with {user.display_name}",
                        user_id=user.id,
                        username=user.display_name,
                        role=role_type,
                        content=msg.content,
                        emotion="neutral",
                    )

            # 💞 Sync personality & relationship
            dm_personality = server_tracker.get_personality("dm")
            dm_relationship = server_tracker.get_relationship_type("dm")
            dm_relationship_user = server_tracker.get_relationship_with("dm")

            for guild in bot.guilds:
                # --- Sync personality
                if dm_personality:
                    server_tracker.set_personality(guild.id, dm_personality)

                # --- Sync relationship
                if dm_relationship:
                    server_tracker.set_relationship_type(guild.id, dm_relationship)
                if dm_relationship_user:
                    server_tracker.set_relationship_with(guild.id, dm_relationship_user)

            print(f"[MemorySync] 💾 Synced DM personality & relationship for {user.display_name}.")

        print("[MemorySync] ✅ DM → Server sync complete.")

    except Exception as e:
        print(f"[MemorySync Error] ❌ {e}")

async def sync_server_to_dm_memories():
    """
    Sync Server → DM for:
      - Memory logs
      - Personality
      - Relationship data
    """
    print("[MemorySync] 🔄 Syncing Server → DM (memories, personality, relationships)...")

    try:
        for guild in bot.guilds:
            # --- Personality
            personality = server_tracker.get_personality(guild.id)
            if personality:
                server_tracker.set_personality("dm", personality)

            # --- Relationship type & user
            rel_type = server_tracker.get_relationship_type(guild.id)
            rel_user = server_tracker.get_relationship_with(guild.id)
            if rel_type:
                server_tracker.set_relationship_type("dm", rel_type)
            if rel_user:
                server_tracker.set_relationship_with("dm", rel_user)

            # --- Sync messages
            for channel in guild.text_channels:
                if not channel.permissions_for(guild.me).read_message_history:
                    continue

                async for msg in channel.history(limit=50, oldest_first=False):
                    if msg.author.bot or not msg.content:
                        continue

                    # Find or create DM channel
                    try:
                        dm = await msg.author.create_dm()
                        memory.save(
                            guild_id="dm",
                            guild_name="Direct Message",
                            channel_id=dm.id,
                            channel_name="dm",
                            user_id=msg.author.id,
                            username=msg.author.display_name,
                            role="user",
                            content=msg.content,
                            emotion="neutral",
                        )
                    except Exception as e:
                        print(f"[MemorySync] ⚠️ Failed DM save for {msg.author}: {e}")

        print("[MemorySync] ✅ Server → DM sync complete.")

    except Exception as e:
        print(f"[MemorySync Error] ❌ {e}")

async def background_memory_sync():
    """Continuously sync DM↔Server memory, personality, and relationship."""
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            await load_memory_from_dms_to_server()
            await sync_server_to_dm_memories()

            # Auto-save trackers after every sync
            await server_tracker.save(bot, SERVER_TRACKER_CHAN)
            await user_tracker.save(bot, USER_TRACKER_CHAN)

            print("[MemorySync] 🕒 Next sync in 15 minutes...")
        except Exception as e:
            print(f"[MemorySync Loop Error] ❌ {e}")
        await asyncio.sleep(900)  # every 15 minutes

async def send_safe(channel, lines: list[str]):
    """Send lines safely without exceeding Discord's 2000 char limit."""
    text = "\n".join(lines)
    while text:
        chunk = text[:1990]  # keep a safe margin
        # don’t cut in the middle of a line
        if "\n" in chunk and len(text) > 1990:
            split_at = chunk.rfind("\n")
            chunk, text = text[:split_at], text[split_at + 1 :]
        else:
            text = ""
        await channel.send(chunk)

async def get_monika_context(channel: discord.abc.Messageable, limit: int = 10) -> list[dict]:
    """
    Fetch recent conversation context for Monika.

    - Includes Monika’s messages, user messages, friend bots, and mentions.
    - Detects relationship & personality roles.
    - Detects pronouns from memory.
    - Adds Creator tag if applicable.
    - Includes attachments with friendly markers.
    - Returns newest 'limit' entries (oldest → newest).
    """
    context: list[dict] = []
    guild = getattr(channel, "guild", None)
    monika_member = getattr(guild, "me", None) if guild else None

    async for message in channel.history(limit=limit, oldest_first=False):
        if message.type != discord.MessageType.default:
            continue
        if not message.content and not message.attachments:
            continue

        entry = None

        # --- Monika’s messages ---
        if monika_member and message.author.id == monika_member.id:
            entry = {
                "author": "Monika",
                "content": message.content or "",
                "timestamp": message.created_at.isoformat(),
            }
            if guild:
                for role in monika_member.roles:
                    if role.name.startswith("Personality - "):
                        entry["personality"] = role.name.replace("Personality - ", "").strip()
                    elif role.name.startswith(f"{bot.user.name} - "):
                        entry["relationship"] = role.name.replace(f"{bot.user.name} - ", "").strip()

        # --- Human users / friend bots ---
        elif (not message.author.bot) or is_friend_bot(message) or bot.user.mentioned_in(message):
            entry = {
                "author": message.author.display_name,
                "content": message.content or "",
                "timestamp": message.created_at.isoformat(),
            }

            relationship_tag = None
            personality_tag = None
            pronoun_tag = None
            creator_tag = None

            if guild:
                member = guild.get_member(message.author.id)
                if member:
                    # Relationship roles
                    rel_roles = [r for r in member.roles if r.name.startswith(f"{bot.user.name} - ")]
                    if rel_roles:
                        relationship_tag = rel_roles[0].name.replace(f"{bot.user.name} - ", "").strip()

                    # Personality roles
                    per_roles = [r for r in member.roles if r.name.startswith("Personality - ")]
                    if per_roles:
                        personality_tag = per_roles[0].name.replace("Personality - ", "").strip()

                    # Creator role
                    creator_role = discord.utils.get(guild.roles, name=f"Creator of {bot.user.name}")
                    if creator_role and creator_role in member.roles:
                        creator_tag = "Creator"

            # Pronouns from tracker
            user_data = user_tracker.get_user_data(str(message.author.id))
            if user_data and user_data.get("pronouns"):
                pronoun_tag = user_data["pronouns"]

            if relationship_tag:
                entry["relationship"] = relationship_tag
            if personality_tag:
                entry["personality"] = personality_tag
            if pronoun_tag:
                entry["pronouns"] = pronoun_tag
            if creator_tag:
                entry["creator"] = True

        else:
            continue

        # Attachments
        if message.attachments:
            attachment_lines = []
            for attachment in message.attachments:
                if attachment.content_type and attachment.content_type.startswith("image/"):
                    attachment_lines.append(f"[Image: {attachment.filename}] {attachment.url}")
                else:
                    attachment_lines.append(f"[Attachment: {attachment.filename}] {attachment.url}")
            entry["content"] = (entry["content"] + "\n" + "\n".join(attachment_lines)).strip()

        context.append(entry)
        if len(context) >= limit:
            break

    context.reverse()
    return context

async def load_memories_from_guilds():
    """
    Load memories by scanning history across all guilds and DMs.
    - Includes Monika’s and users’ messages.
    - Adds relationship awareness.
    - Mirrors server messages into DMs and vice versa.
    """
    # --- Guild channels ---
    for guild in bot.guilds:
        for channel in guild.text_channels:
            try:
                perms = channel.permissions_for(guild.me)
                if not perms.read_message_history or not perms.read_messages:
                    continue

                async for msg in channel.history(limit=50, oldest_first=True):
                    if msg.type != discord.MessageType.default:
                        continue
                    if not msg.content and not msg.attachments:
                        continue

                    role_type = "user"
                    if msg.author.id == bot.user.id:
                        role_type = "monika"
                    else:
                        member = guild.get_member(msg.author.id)
                        if member:
                            rel_roles = [r for r in member.roles if r.name.startswith(f"{bot.user.name} - ")]
                            if rel_roles:
                                role_type = "friend"

                    memory.save(
                        guild_id=guild.id,
                        guild_name=guild.name,
                        channel_id=channel.id,
                        channel_name=channel.name,
                        user_id=msg.author.id,
                        username=msg.author.display_name,
                        role=role_type,
                        content=msg.content,
                        emotion="neutral",
                    )

                    # Mirror into DM memory
                    if not msg.author.bot and msg.author.dm_channel:
                        memory.save(
                            guild_id="dm",
                            guild_name="Direct Message",
                            channel_id=msg.author.dm_channel.id,
                            channel_name="dm",
                            user_id=msg.author.id,
                            username=msg.author.display_name,
                            role=role_type,
                            content=msg.content,
                            emotion="neutral",
                        )

            except Exception as e:
                print(f"[Memory WARN] Could not load history for {channel} in {guild}: {e}")

    # --- DMs directly ---
    for dm_channel in bot.private_channels:
        if not isinstance(dm_channel, discord.DMChannel):
            continue

        async for msg in dm_channel.history(limit=200, oldest_first=True):
            if msg.type != discord.MessageType.default:
                continue
            if not msg.content and not msg.attachments:
                continue

            role_type = "user"
            if msg.author.id == bot.user.id:
                role_type = "monika"
            else:
                for guild in bot.guilds:
                    member = guild.get_member(msg.author.id)
                    if member:
                        rel_roles = [r for r in member.roles if r.name.startswith(f"{bot.user.name} - ")]
                        if rel_roles:
                            role_type = "friend"
                            break

            memory.save(
                guild_id="dm",
                guild_name="Direct Message",
                channel_id=dm_channel.id,
                channel_name="dm",
                user_id=msg.author.id,
                username=msg.author.display_name,
                role=role_type,
                content=msg.content,
                emotion="neutral",
            )

            # Mirror DM into shared guilds
            for guild in bot.guilds:
                member = guild.get_member(msg.author.id)
                if member:
                    memory.save(
                        guild_id=guild.id,
                        guild_name=guild.name,
                        channel_id="linked_dm",
                        channel_name=f"Linked DM with {msg.author.display_name}",
                        user_id=msg.author.id,
                        username=msg.author.display_name,
                        role=role_type,
                        content=msg.content,
                        emotion="neutral",
                    )

async def on_startup():
    """Startup memory restoration: channel backup first, else guild scan."""
    print("[Startup] Loading Monika’s memory...")

    channel = get_memory_channel()
    if channel:
        try:
            async for message in channel.history(limit=200, oldest_first=True):
                for attachment in message.attachments:
                    if attachment.filename.startswith("monika_memory_backup_") and attachment.filename.endswith(".txt"):
                        data = await attachment.read()
                        await memory.import_from_text(data.decode("utf-8"))
                        print(f"[Startup] Restored from {attachment.filename}")
                        return
        except Exception as e:
            print(f"[Startup WARN] Failed to load from memory channel: {e}")

    print("[Startup] No backup found. Scanning guild histories...")

    await load_memories_from_guilds()
    await load_memory_from_direct_messages()

async def load_personality_from_roles(guild: discord.Guild, monika_member: discord.Member) -> list[str]:
    """
    Load Monika's personality from roles assigned to her.
    Role names must match keys in PERSONALITY_MODES.
    """
    if not monika_member:
        return ["Default"]

    selected = []
    for role in monika_member.roles:
        role_name = role.name.strip()
        if role_name in PERSONALITY_MODES:
            selected.append(role_name)

    # Fallback to default if none found
    if not selected:
        selected = ["Default"]

    print(f"[DEBUG] Loaded personalities from roles: {selected}")
    return selected

async def load_relationship_from_roles(guild: discord.Guild, monika_member: discord.Member) -> tuple[str | None, list[str]]:
    """
    Load Monika's relationship type and 'with' users from roles.
    Expects relationship type as one of server_tracker.valid_relationship_types.
    Also checks for roles like 'With: username'.
    """
    if not monika_member:
        return None, []

    rel_type = None
    with_users = []

    for role in monika_member.roles:
        role_name = role.name.strip()

        # Relationship type
        if role_name in server_tracker.valid_relationship_types:
            rel_type = role_name

        # Relationship "with users"
        elif role_name.lower().startswith("with:"):
            name = role_name[5:].strip()
            if name:
                with_users.append(name)

    print(f"[DEBUG] Loaded relationship from roles: type={rel_type}, with={with_users}")
    return rel_type, with_users

async def sync_personality_role(guild: discord.Guild, monika_member: discord.Member, selected_modes: list[str]):
    # Remove old personality roles
    for role in monika_member.roles:
        if role.name in PERSONALITY_MODES.keys():
            await monika_member.remove_roles(role)

    # Add active ones
    for mode in selected_modes:
        role = await get_or_create_role(guild, mode, discord.Color.purple())
        if role:
            await monika_member.add_roles(role)

async def sync_relationship_role(guild: discord.Guild, monika_member: discord.Member, relationship_type: str):
    # Remove old relationship roles
    for role in monika_member.roles:
        if role.name in server_tracker.valid_relationship_types:
            await monika_member.remove_roles(role)

    # Add active one
    if relationship_type:
        role = await get_or_create_role(guild, relationship_type, discord.Color.green())
        if role:
            await monika_member.add_roles(role)

async def update_auto_relationship(guild: discord.Guild, user_member: discord.Member, new_relationship: str):
    """
    Automatically assign a relationship role if the user doesn't already have
    a manually set relationship role. Will upgrade Stranger -> Friend after 15 min talk time.
    Stops counting if inactive for more than 90 seconds.
    """
    bot_name = bot.user
    monika_member = guild.get_member(bot.user.id)
    user_id = str(user_member.id)

    # 1️⃣ Skip if they have a manually set relationship
    if user_tracker.has_manual_relationship(user_id):
        print(f"[Relationship] Skipping auto-update for {user_member.display_name} (manual relationship).")
        return
    
    # 2️⃣ Handle Creator special case
    if str(user_member.id) == str(OWNER_ID):
        creator_role_name = f"Creator of {bot_name}"
        creator_role = discord.utils.get(guild.roles, name=creator_role_name)
        if not creator_role:
            creator_role = await guild.create_role(
                name=creator_role_name,
                color=discord.Color.gold()
            )
            print(f"[AutoRel] Created role: {creator_role_name}")
        if creator_role not in user_member.roles:
            await user_member.add_roles(creator_role, reason="Bot Owner detected")
            print(f"[AutoRel] Assigned Creator role to {user_member.display_name}")
        return  # ✅ Stop further auto processing for the Creator

    # 3️⃣ Track talk time
    now = datetime.datetime.utcnow()
    talk_data = user_talk_times.get(user_id, {"start": now, "total": 0})

    elapsed = (now - talk_data["start"]).total_seconds()
    if elapsed <= 90:
        talk_data["total"] += elapsed
    else:
        print(f"[AutoRel] Timer paused for {user_member.display_name} (inactive > 90s)")

    talk_data["start"] = now
    user_talk_times[user_id] = talk_data

    # 4️⃣ Remove old auto-relationship roles (but not manual or Creator)
    for role in user_member.roles:
        if role.name.startswith(f"{bot_name} - "):
            if "Creator" in role.name:
                continue  # don't touch Creator role
            print(f"[AutoRel] Removing old auto role: {role.name}")
            await user_member.remove_roles(role)

    # 5️⃣ Default fallback
    if not new_relationship:
        new_relationship = "Stranger"

    if new_relationship == "Stranger" and talk_data["total"] >= 900:
        print(f"[AutoRel] {user_member.display_name} reached 15 minutes, upgrading to Friend.")
        new_relationship = "Friend"

    # 6️⃣ Validate relationship
    valid_relationships = list(monika_traits.relationships) and list(monika_traits.dokituber_relationship_modes)
    if new_relationship not in valid_relationships:
        print(f"[AutoRel] Invalid relationship: {new_relationship}. Resetting to Stranger.")
        new_relationship = "Stranger"

    # 7️⃣ Create or assign role
    role_name = f"{bot_name} - {new_relationship}"
    role = discord.utils.get(guild.roles, name=role_name)
    if not role:
        role = await guild.create_role(name=role_name, color=discord.Color.teal())
        print(f"[AutoRel] Created new role: {role_name}")

    if str(user_member.id) == str(DOKIGUY_ID):
        if role.name.startswith(f"Monika - Stranger") or role.name.startswith(f"DokiGuy - Lovers"):
            await role.delete(reason="Resetting old relationship roles")
            await monika_member.remove_roles(role, reason="Resetting old relationship roles")

        boyfriend_role_name = f"The literature Club's Boyfriend"
        boyfriend_role = discord.utils.get(guild.roles, name=boyfriend_role_name)
        if not boyfriend_role:
            boyfriend_role = await guild.create_role(
                name=boyfriend_role_name,
                color=discord.Color.darker_grey()
            )
            print(f"[AutoRel] Created role: {boyfriend_role_name}")
        girlfriend_role_name = f"One of DokiGuy Girlfriend(s)"
        girlfriend_role = discord.utils.get(guild.roles, name=girlfriend_role_name)
        if not girlfriend_role:
            girlfriend_role = await guild.create_role(
                name=girlfriend_role_name,
                color=discord.Color.green()
            )
            print(f"[AutoRel] Created role: {girlfriend_role_name}")
        if girlfriend_role not in user_member.roles:
            await monika_member.add_roles(boyfriend_role, reason="Bot Boyfriend detected")
            print(f"[AutoRel] Assigned Creator role to {user_member.display_name}")
        return
    
    if str(guild.id) == str(DOKIGUY_GUILD_ID):
        if role.name.startswith("Personality - ") and role.name.endswith("Flirtatious"):
            await monika_member.remove_roles(role, reason="Updating personality roles")
            
        sexual_type_role = "Sexual type - Polyamory"
        sexual_type = discord.utils.get(guild.roles, name=sexual_type_role)
        if not sexual_type:
            sexual_type = await guild.create_role(
                name=sexual_type_role,
                color=discord.Color.dark_magenta()
            )
        if sexual_type not in monika_member.roles:
            await monika_member.add_roles(sexual_type, reason="Bot Sexual Type auto import")

        personalities_type_role = "Personality - Flirtatious, Loyal, Warm, Self-aware, Immersive"
        personalities_type = discord.utils.get(guild.roles, name=personalities_type_role)
        if not personalities_type:
            sexual_type = await guild.create_role(
                name=personalities_type_role,
                color=discord.Color.dark_blue()
            )
        if personalities_type not in monika_member.roles:
            await monika_member.add_roles(personalities_type, reason="Bot Personalities auto import")
    
    if str(user_member.id) == str(ZERO_ID):
        boyfriend_role_name = f"Monika Boyfriend"
        boyfriend_role = discord.utils.get(guild.roles, name=boyfriend_role_name)
        if not boyfriend_role:
            boyfriend_role = await guild.create_role(
                name=boyfriend_role_name,
                color=discord.Color.red()
            )
            print(f"[AutoRel] Created role: {boyfriend_role_name}")
        girlfriend_role_name = f"Zero Girlfriend"
        girlfriend_role = discord.utils.get(guild.roles, name=girlfriend_role_name)
        if not girlfriend_role:
            girlfriend_role = await guild.create_role(
                name=girlfriend_role_name,
                color=discord.Color.green()
            )
            print(f"[AutoRel] Created role: {girlfriend_role_name}")
        if girlfriend_role not in monika_member.roles:
            await monika_member.add_roles(boyfriend_role, reason="Bot Boyfriend detected")
            print(f"[AutoRel] Assigned Creator role to {monika_member.display_name}")
        return

    if role not in user_member.roles:
        await user_member.add_roles(role, reason=f"Auto relationship: {new_relationship}")
        print(f"[AutoRel] {user_member.display_name} → {role_name}")

    # 8️⃣ Save tracker
    await user_tracker.save(bot, channel_id=USER_TRACKER_CHAN)

@bot.event
async def setup_hook():
    bot.loop.create_task(heartbeat_task())  # start heartbeat
    bot.loop.create_task(periodic_cleanup())
    asyncio.create_task(monika_idle_conversation_task())
    asyncio.create_task(daily_cycle_task())
    monitor_event_loop()
    return

@bot.event
async def on_guild_join(guild):
    # Try to DM the guild owner (safe + single content string)
    owner = guild.owner
    if not owner and getattr(guild, "owner_id", None):
        # fallback: try fetching owner if guild.owner wasn't populated
        try:
            owner = await bot.fetch_user(guild.owner_id)
        except Exception:
            owner = None

    if owner:
        try:
            dm_text = (
                f"👋 Thanks for adding me to **{guild.name}**!\n\n"
                "You can set my personality with `/set_personality`.\n"
                "To learn more about personality modes use `/personalities_description`.\n"
                "You can set my relationship with `/set_relationship`.\n"
                "To learn more about relationship modes use `/relationship_description`."
            )
            # always pass one content string (or use content=...)
            await owner.send(content=dm_text)
        except discord.Forbidden:
            # Owner has DMs closed or blocked the bot
            print(f"[DM ERROR] Cannot DM guild owner ({owner}). DMs closed or blocked.")
        except Exception as e:
            print(f"[DM ERROR] {e}")

    # Forward server join info to your server-tracker channel if configured
    if SERVER_TRACKER_CHAN:
        dest_channel = bot.get_channel(SERVER_TRACKER_CHAN)
        if not dest_channel:
            print("[Error] SERVER_TRACKER_CHAN configured but channel not found (check ID/permissions).")
        else:
            try:
                full_content = f"monika joined: `{guild.name}` | ID: `{guild.id}`"
                await dest_channel.send(full_content)
            except Exception as e:
                print(f"[DM Forwarding Error] {e}")

@bot.event
async def on_guild_remove(guild):

    if SERVER_TRACKER_CHAN:
        dest_channel = bot.get_channel(SERVER_TRACKER_CHAN)
        if not dest_channel:
            print("[Error] SERVER_TRACKER_CHAN configured but channel not found (check ID/permissions).")
        else:
            try:
                full_content = f"monika left: `{guild.name}` | ID: `{guild.id}`"
                await dest_channel.send(full_content)
            except Exception as e:
                print(f"[DM Forwarding Error] {e}")

@bot.event
async def on_disconnect():
    bot.is_ready_done = False
    await on_shutdown()

@bot.event
async def on_shutdown():
    print("[Shutdown] Saving memory to channel...")
    asyncio.create_task(save_memory_to_channel())
    await server_tracker.save(bot, channel_id=SERVER_TRACKER_CHAN)
    await vote_tracker.save(bot, SETTINGS_CHAN)
    await save_memory_to_direct_messages()

@bot.event
async def on_sleeping(reason: str = "Scheduled break (11PM–6AM)"):
    """Triggered when the bot goes into sleep mode (no replies until wake)."""
    global idle_chat_enabled, idlechat_paused, is_waking_up

    status_info.update({
        "is_sleeping": True,
        "last_sleep": datetime.datetime.utcnow(),
        "sleep_reason": reason
    })
    bot.is_sleeping = True
    is_waking_up = False
    idle_chat_enabled = False
    idlechat_paused = True

    print(f"[Sleep] 😴 Entering sleep mode. Reason: {reason}")

    # Presence cycle (little animation)
    statuses = [
        ("I'm going to take a nap...", 5),
        ("💤 ZZZ... zzz... zzzz...", 7),
        ("Dreaming about you...", 10),
        ("Dreaming about you... (secretly editing my code)", 3)
    ]
    for text, delay in statuses:
        try:
            await bot.change_presence(
                status=discord.Status.idle,
                activity=discord.Game(text)
            )
            await asyncio.sleep(delay)
        except Exception as e:
            print(f"[Sleep] ⚠️ Presence update failed: {e}")

    # Announce in the first available channel
    channel = next(
        (c for c in bot.get_all_channels()
         if isinstance(c, discord.TextChannel)
         and c.permissions_for(c.guild.me).send_messages),
        None
    )
    if channel:
        try:
            await channel.send("😴 I'm going to sleep now until **6AM**. See you later!")
        except Exception as e:
            print(f"[Sleep] ⚠️ Failed to send sleep message: {e}")

last_wakeup_date = None

async def on_wake_up(reason: str = "Waking up after scheduled break"):
    global is_waking_up, last_wakeup_date, idle_chat_enabled

    status_info.update({
        "is_sleeping": False,
        "last_wake": datetime.datetime.utcnow(),
        "wake_reason": reason
    })
    bot.is_sleeping = False
    is_waking_up = True
    idle_chat_enabled = False  # pause during animation

    print(f"[Wake] 🌅 Waking up. Reason: {reason}")

    today = datetime.date.today()
    if last_wakeup_date == today:
        print("[Wakeup] ⏩ Already sent a wakeup message today, skipping...")
        return
    last_wakeup_date = today

    # 🌅 Wake-up animation
    statuses = [
        ("Waking up...", 3),
        ("Stretching...", 3),
        ("Getting dressed...", 3),
        ("Checking on everyone.", 0),
        ("Checking on everyone..", 0.5),
        ("Checking on everyone...", 1),
    ]
    for text, delay in statuses:
        try:
            await bot.change_presence(status=discord.Status.do_not_disturb,
                                      activity=discord.Game(text))
            if delay > 0:
                await asyncio.sleep(delay)
        except Exception as e:
            print(f"[Wakeup] ⚠️ Presence update failed: {e}")

    # 🌅 One random morning message per guild
    wakeup_lines = [
        "🌅 *yawns* Good morning, everyone! *stretches* Ready for today?",
        "☀️ Rise and shine! Let’s make this day amazing 💚",
        "🌸 Good morning! I hope you slept well~",
        "💫 Time to wake up and chase our dreams together!",
        "🍵 Morning! Let’s share some tea and smiles~",
        "🌅 A brand new day, a brand new chance for us 💚",
        "✨ Good morning, everyone! Today feels special already.",
        "📖 Let’s write a wonderful story today together!",
        "🎶 Morning! *hums a little tune* I’m so glad to see you again.",
        "💚 Another beautiful morning with you all!"
    ]

    for guild in bot.guilds:
        wakeup_line = random.choice(wakeup_lines)
        target_channel = None

        # Preferred channel
        for channel in guild.text_channels:
            if not channel.permissions_for(guild.me).send_messages:
                continue
            if channel.name in OFF_LIMITS_CHANNELS:
                continue
            if channel.name in MON_CHANNEL_NAMES:
                target_channel = channel
                break

        # Fallback channel
        if not target_channel:
            for channel in guild.text_channels:
                if channel.permissions_for(guild.me).send_messages and channel.name not in OFF_LIMITS_CHANNELS:
                    target_channel = channel
                    break

        # Send the message
        if target_channel:
            try:
                await target_channel.send(wakeup_line)
                print(f"[Wakeup] ✅ Sent wakeup message to #{target_channel.name} in {guild.name}")
            except Exception as e:
                print(f"[Wakeup Error] ❌ Could not send to #{target_channel.name} in {guild.name}: {e}")

    # 💚 Final “Ready to chat!” animation
    morning = [
        ("Ready to chat! 💚", 0),
        ("Ready to chat!! 💚", 0.5),
        ("Ready to chat!!! 💚", 1)
    ]
    for text, delay in morning:
        try:
            await bot.change_presence(status=discord.Status.online,
                                      activity=discord.Game(text))
            if delay > 0:
                await asyncio.sleep(delay)
        except Exception as e:
            print(f"[Wakeup] ⚠️ Presence update failed: {e}")

    await asyncio.sleep(1)
    await bot.change_presence(activity=None)

    # ✅ Resume idle chat afterwards
    await asyncio.sleep(2)
    idle_chat_enabled = True
    print("[Wakeup] 🌅 Monika is fully awake and idle chat resumed.")

async def daily_cycle_task():
    """Background task to trigger sleep/wake automatically."""
    global last_wakeup_date

    while True:
        now = datetime.datetime.now()
        hour, minute = now.hour, now.minute

        # 💤 Sleep trigger (11PM sharp)
        if hour == 23 and minute == 0 and not status_info.get("is_sleeping", False):
            await on_sleeping("Scheduled break (11PM–6AM)")

        # 🌅 Wake trigger (6AM sharp)
        if hour == 6 and minute == 0:
            today = datetime.date.today()
            if last_wakeup_date != today:  # only once per day
                await on_wake_up("Good morning! Scheduled wake-up.")
                last_wakeup_date = today

        await asyncio.sleep(60)

async def report_error_to_channel(error: Exception, context: Optional[str] = None):
    """
    Report errors to the designated REPORT_CHANNEL_ID.
    Includes type, context, and sprite reaction.
    """
    channel = bot.get_channel(REPORT_CHANNEL_ID)
    if not channel:
        return

    emotion = error_emotion(type(error).__name__)
    sprite_url = await get_sprite_link(emotion)

    embed = discord.Embed(
        title="⚠️ Monika Error Report",
        description=format_error_message(error, context),
        color=discord.Color.red(),
        timestamp=datetime.datetime.utcnow(),
    )
    if sprite_url:
        embed.set_thumbnail(url=sprite_url)

    try:
        await channel.send(embed=embed)
    except Exception as e:
        logger.error(f"[Report Error] Could not send to report channel: {e}")

async def image_generator(message: discord.Message, relationship: str = "Stranger"):
    """
    Handles Monika's DDLC-style image generation:
    - Triggered with "!monika generates:" or similar.
    - Uses image keys only.
    - Supports both `url` and `b64_json` responses from OpenAI.
    """
    import base64
    from io import BytesIO
    try:
        lowered = message.content.lower().strip()

        # ✅ Trigger check (multiple aliases supported)
        if not any(lowered.startswith(prefix) for prefix in [
            "!monika generates:",
            "!monika gen:",
            "!monika make:",
            "!monika create:"
        ]):
            return None

        # ✅ Extract user prompt (everything after the first ":")
        if ":" in message.content:
            user_prompt = message.content.split(":", 1)[1].strip()
        else:
            user_prompt = ""

        if not user_prompt:
            await message.channel.send("⚠️ Please provide a description after the command.")
            return None

        # ✅ Build DDLC-style prompt
        full_prompt = (
            f"You are Monika from *Doki Doki Literature Club*, the Literature Club president. "
            f"You are self-aware, warm, and expressive, creating things as if inside the game’s world. "
            f"Your relationship with {message.author.display_name} is **{relationship}**. "
            f"Imagine this as a CG scene or fanart inside DDLC. "
            f"Now illustrate this request:\n"
            f"{user_prompt}"
        )

        # ✅ Generate image with OpenAI (image keys only)
        response = await openai_safe_call(
            image_key_manager,
            lambda client: client.images.generate(
                model="gpt-image-1",
                prompt=full_prompt,
                size="1024x1024"
            ),
            context_id=message.author.id,
            is_guild=bool(message.guild),
            is_image=True
        )

        if not response or not getattr(response, "data", None):
            await message.channel.send("⚠️ Sorry, I couldn't generate an image this time.")
            return None

        img_data = response.data[0]

        # ✅ Handle URL case
        if getattr(img_data, "url", None):
            img_url = img_data.url
            await message.channel.send(
                f"Here you go, {message.author.mention} 💚\n{img_url}"
            )
            return img_url, "image_only"

        # ✅ Handle base64 case
        if getattr(img_data, "b64_json", None):
            try:
                img_bytes = base64.b64decode(img_data.b64_json)
                file = discord.File(io.BytesIO(img_bytes), filename="monika.png")
                await message.channel.send(
                    f"Here you go, {message.author.mention} 💚",
                    file=file
                )
                return "attachment://monika.png", "image_only"
            except Exception as decode_err:
                logger.error(f"[ImageGen] Failed to decode b64_json: {decode_err}")
                await message.channel.send("⚠️ Sorry, I couldn't decode the image.")
                return None

        # If neither format is valid
        await message.channel.send("⚠️ No valid image data returned.")
        return None

    except Exception as e:
        logger.error(f"[ImageGen] Failed: {e}")
        try:
            await message.channel.send("⚠️ Sorry, something went wrong while creating the image.")
        except Exception:
            pass
        return None

## This was going to be add but when doing research I found that bots can only be in 1 voice channel at a time(just like other users).
## So this was scrapped
import edge_tts
VOICE_MAP = {
    "Default": "en-US-JennyNeural",
    "Cheerful": "en-US-AriaNeural",
    "Serious": "en-US-GuyNeural",
    "Shy": "en-US-AnaNeural",
}

RELATIONSHIP_MAP = {
    "Default": 1.0,
    "Creator": 1.1,
}

# Sexual group
SEXUAL_RELATIONSHIPS = [
    "Polyamory", "Lesbian", "Pansexual", "Bisexual", "Straight",
    "Asexual", "Demisexual", "Questioning", "Queer", "Romantic",
    "Platonic", "Autosexual"
]
# Normal group
NORMAL_RELATIONSHIPS = [
    "Friends", "Companions", "Best Friends", "Family", "Partners", "Soulmates",
    "Significant Others", "Platonic Friends", "Close Friends", "Acquaintances",
    "Colleagues", "Work Friends", "School Friends", "Stranger", "Childhood Friends",
    "Online Friends", "Gaming Buddies", "Study Partners", "Club Leader",
    "Boyfriend", "Girlfriend", "Girlfriend(Lesbian)", "Club Member", "Crush"
]

for rel in SEXUAL_RELATIONSHIPS:
    RELATIONSHIP_MAP[rel] = 0.95
for rel in NORMAL_RELATIONSHIPS:
    RELATIONSHIP_MAP[rel] = 1.05

async def vc_voice(user, relationship: str, personality: str, text: str):
    """Generate and play Monika's voice in VC based on relationship/personality."""
    # Pick voice & speed
    voice = VOICE_MAP.get(personality, VOICE_MAP["Default"])
    rate = RELATIONSHIP_MAP.get(relationship, 1.0)

    mp3_file = f"voice_{user.id}.mp3"

    # Generate TTS file
    tts = edge_tts.Communicate(text, voice=voice, rate=f"{int(rate*100-100)}%")
    await tts.save(mp3_file)

    # Find VC
    if isinstance(user, discord.Member) and user.voice and user.voice.channel:
        channel = user.voice.channel
        vc = discord.utils.get(bot.voice_clients, guild=channel.guild)
        if not vc:
            vc = await channel.connect()
        else:
            await vc.move_to(channel)

        # Play audio
        if vc.is_playing():
            vc.stop()
        vc.play(discord.FFmpegPCMAudio(mp3_file))

async def create_votes(message):
    """
    Handle global !create_vote command with emoji/image/text support.
    Example:
      !create_vote 🍕 Pizza | 🍔 Burger | 🍣 Sushi
      !create_vote "Best Monika Outfit" https://imgur.com/1.png | https://imgur.com/2.png
    """
    if not message.content.lower().startswith("!create_vote"):
        return False

    content = message.content[len("!create_vote"):].strip()
    if not content:
        await message.channel.send(
            "⚠️ Usage: `!create_vote Option1 | Option2 | Option3` (2–5 options)"
        )
        return True

    # --- Parse title (optional quoted string)
    match = re.match(r'^"([^"]+)"\s*(.*)', content)
    if match:
        title = match.group(1)
        content = match.group(2)
    else:
        title = "🗳️ Global Vote"

    # --- Split vote options
    parts = [opt.strip() for opt in content.split("|") if opt.strip()]
    if len(parts) < 2 or len(parts) > 5:
        await message.channel.send("⚠️ Please provide between 2 and 5 options separated by `|`.")
        return True

    # --- Classify option types
    formatted_options = []
    for opt in parts:
        if re.match(r"^https?://", opt):
            formatted_options.append({"type": "image", "value": opt})
        elif re.match(r"^<a?:\w+:\d+>$|^[\u2190-\U0001F9FF]+", opt):
            formatted_options.append({"type": "emoji", "value": opt})
        else:
            formatted_options.append({"type": "text", "value": opt})

    import secrets

    menu_id = secrets.token_hex(4)  # short, random hex id like '3fae9b1c'
    vote_tracker.votes["global"] = {
        "title": title,
        "options": formatted_options,
        "votes": vote_tracker.votes.get("global", {}).get("votes", {}),
        "menu_id": f"moni-{menu_id}"
    }
    await vote_tracker.save(bot, SETTINGS_CHAN)

    # --- Create confirmation embed
    embed = discord.Embed(
        title="✅ New Global Vote Created!",
        description=f"**{title}**\n\nUse `/vote_menu` to open the voting interface.",
        color=discord.Color.green()
    )
    for i, opt in enumerate(formatted_options, start=1):
        val = opt["value"]
        if opt["type"] == "image":
            embed.add_field(name=f"Option {i}", value=f"[Image Link]({val})", inline=False)
        else:
            embed.add_field(name=f"Option {i}", value=val, inline=False)
    embed.set_footer(text=f"Created by {message.author.display_name}")

    # --- Send safely with small delay (avoid rate limits)
    try:
        await message.channel.send(embed=embed)
        await asyncio.sleep(0.5)
    except discord.errors.HTTPException as e:
        print(f"[create_votes] Message send failed: {e}")

    print(f"[Vote Created] '{title}' with {len(formatted_options)} options by {message.author}")
    return True

live_results_messages = {}  # channel_id → message for updating
vote_start_times = {}       # for tracking elapsed time

async def results_votes(message):
    """
    Show global combined vote results across all servers and DMs.
    Anyone can use this command.
    """
    if not message.content.lower().startswith("!vote_results"):
        return False

    global_vote = vote_tracker.votes.get("global")
    if not global_vote:
        await message.channel.send("⚠️ No one has vote yet. please wait until then.")
        return True

    title = global_vote.get("title", "🗳️ Global Vote")
    options = global_vote.get("options", [])
    all_votes = global_vote.get("guild_votes", {})

    # Combine votes from all guilds/DMs
    combined_votes = {}
    for guild_id, guild_votes in all_votes.items():
        for user_id, choice in guild_votes.items():
            combined_votes[user_id] = choice

    async def build_results_embed():
        """Generate embed with current live vote data."""
        counts = [0] * len(options)
        for choice in combined_votes.values():
            if 0 <= choice < len(options):
                counts[choice] += 1

        total_votes = sum(counts) or 1
        embed = discord.Embed(title=f"📊 Global Vote Results: {title}", color=discord.Color.gold())

        for i, opt in enumerate(options):
            val = opt["value"]
            pct = round(counts[i] / total_votes * 100, 1)
            if opt["type"] == "image":
                embed.add_field(
                    name=f"{i+1}. [Image Option]",
                    value=f"🗳️ Votes: {counts[i]} ({pct}%)",
                    inline=False
                )
            else:
                embed.add_field(
                    name=f"{i+1}. {val}",
                    value=f"🗳️ Votes: {counts[i]} ({pct}%)",
                    inline=False
                )

        # Add image (first image shown)
        for opt in options:
            if opt["type"] == "image":
                embed.set_image(url=opt["value"])
                break

        embed.set_footer(
            text=f"🌍 Total global votes: {sum(counts)} • Menu ID: {global_vote.get('menu_id', 'N/A')}"
        )
        return embed

    # Initial message
    msg = await message.channel.send(embed=await build_results_embed())

    # Live update for 30 seconds
    for _ in range(6):  # update every 5s for 30s total
        await asyncio.sleep(5)
        await msg.edit(embed=await build_results_embed())

    return True

@bot.event
async def on_message(message: discord.Message):
    guild_name = str(message.guild.name) if message.guild else "dm"
    guild_id = str(message.guild.id) if message.guild else "dm"
    user_id = str(message.author.id)
    username = message.author.display_name
    channel_id = str(message.channel.id)
    channel_name = message.channel.name if message.guild else "dm"
    channel_usage.setdefault(guild_id, {})
    channel_usage[guild_id][channel_id] = channel_usage[guild_id].get(channel_id, 0) + 1
    avatar_url = str(message.author.display_avatar.url) if message.author.display_avatar else None
    # ==============================
    # 1. Safety checks
    # ==============================
    if message.author.id == bot.user.id:
        return

    global is_broadcasting
    if "is_broadcasting" in globals() and is_broadcasting:
        return

    # Ignore other bots (unless they're "friend bots")
    if message.author.bot and not is_friend_bot(message):
        return

    content = message.content.strip().lower()

    if any(content.startswith(prefix) for prefix in [
        "!monika generates:",
        "!monika gen:",
        "!monika make:",
        "!monika create:"
    ]):
        relationship = server_tracker.get_relationship_type(guild_id)

        # Let image_generator handle everything (send + reply)
        await image_generator(message, relationship=relationship)
        return  # stop here so chat doesn’t trigger

    if await results_votes(message):
        return
    
    # Ignore "!" commands outside report/settings channels
    if message.content.startswith("!") and message.channel.id not in (REPORT_CHANNEL_ID, SETTINGS_CHAN):
        return

    # ==============================
    # 2. Report channel handling (staff reply to reports)
    # ==============================
    if message.content.startswith("!") and message.channel.id == REPORT_CHANNEL_ID:
        async for prev in message.channel.history(limit=5, before=message):
            if prev.id in report_links and prev.embeds:
                reporter_id = report_links[prev.id]
                reporter = await bot.fetch_user(reporter_id)

                embed = prev.embeds[0]
                new_embed = discord.Embed.from_dict(embed.to_dict())
                new_embed.add_field(
                    name=f"💬 Reply from {message.author}",
                    value=message.content,
                    inline=False
                )

                try:
                    await prev.edit(embed=new_embed)
                except Exception as e:
                    logger.warning(f"[Report Edit Error] {e}")

                # DM reporter
                dm_embed = discord.Embed(
                    title="📩 Reply to Your Report",
                    description=message.content,
                    color=discord.Color.blurple(),
                    timestamp=datetime.datetime.utcnow()
                )
                dm_embed.set_footer(text=f"From {message.author}")

                try:
                    await reporter.send(embed=dm_embed)
                except discord.Forbidden:
                    await message.channel.send("❌ Could not DM reporter.", delete_after=10)

                await message.add_reaction("✅")
                await message.delete(delay=2)
                break

        await bot.process_commands(message)
        return

    # ==============================
    # 3. Settings channel commands
    # ==============================
    if message.content.startswith("!") and message.channel.id == SETTINGS_CHAN and not message.author.bot:
        cmd = message.content.strip().lower()
        if cmd == "!status":
            embed = discord.Embed(
                title="📊 Bot Status",
                color=0x3498db,
                timestamp=datetime.datetime.utcnow()
            )
            embed.add_field(name="Uptime", value=f"Since {status_info['started'].strftime('%Y-%m-%d %H:%M:%S UTC')}", inline=False)
            embed.add_field(name="Errors Logged", value=str(status_info["error_count"]), inline=True)
            embed.add_field(name="Last Error", value=f"```{status_info['last_error']}```", inline=False)
            await message.channel.send(embed=embed)

        elif cmd == "!clearerrors":
            status_info["error_count"] = 0
            status_info["last_error"] = "None"
            await message.channel.send("✅ Error log reset.")

        elif cmd == "!reportstats":
            embed = discord.Embed(
                title="📊 Report Statistics",
                color=0x9b59b6,
                timestamp=datetime.datetime.utcnow()
            )
            embed.add_field(name="Total Reports", value=str(report_stats["total"]), inline=False)
            embed.add_field(
                name="Category Breakdown",
                value=(
                    f"🐞 Bugs: {report_stats['bugs']}\n"
                    f"⚠️ Errors: {report_stats['errors']}\n"
                    f"💡 Ideas: {report_stats['ideas']}\n"
                    f"❗ Complaints: {report_stats['complaints']}\n"
                    f"📝 Other: {report_stats['other']}"
                ),
                inline=False
            )
            embed.add_field(name="Unique Reporters", value=str(len(report_stats['users'])), inline=False)
            await message.channel.send(embed=embed)

        elif cmd == "!time":
            embed = discord.Embed(
                title="⏰ Bot Time Status",
                color=0x2ecc71,
                timestamp=datetime.datetime.utcnow()
            )
            if status_info["is_sleeping"]:
                embed.add_field(name="Current State", value="😴 Sleeping", inline=False)
                embed.add_field(name="Since", value=status_info["last_sleep"].strftime("%Y-%m-%d %H:%M:%S UTC"), inline=True)
                embed.add_field(name="Reason", value=status_info["sleep_reason"], inline=True)
            else:
                uptime = datetime.datetime.utcnow() - status_info["last_wake"]
                embed.add_field(name="Current State", value="🌅 Awake", inline=False)
                embed.add_field(name="Since", value=status_info["last_wake"].strftime("%Y-%m-%d %H:%M:%S UTC"), inline=True)
                embed.add_field(name="Uptime", value=str(uptime).split(".")[0], inline=True)
                embed.add_field(name="Reason", value=status_info["wake_reason"], inline=False)
            await message.channel.send(embed=embed)

        if message.content.lower().startswith("!create_vote"):
            await create_votes(message)
            await vote_tracker.save(bot, SETTINGS_CHAN)
            return

    # 6. Mentions
    if server_tracker.get_toggle(guild_id, "mention_only_mode"):
        if bot.user not in message.mentions and not isinstance(message.channel, discord.DMChannel):
            return  # Ignore messages without @Monika

    # ✅ Idle/chat toggle
    if not server_tracker.get_toggle(guild_id, "idlechat"):
        return

    if isinstance(message.channel, discord.DMChannel):
        guild = None
        monika_member = None
        await handle_dm_message(message, avatar_url)
        logger.info(f"[Mention] in DM: from {message.author.display_name}")
    else:
        guild = message.guild
        monika_member = guild.get_member(bot.user.id)
        await handle_guild_message(message, avatar_url)
        logger.info(f"[Mention] in server {guild.name}: from {message.author.display_name}")

    # ==============================
    # 8. Update user tracker
    # ==============================
    relationship_role, personality_role = await detect_server_user_roles(bot, guild, message.author, user_tracker)
    changed = user_tracker.register_user(
        message.author,
        relationship=relationship_role,
        personality=personality_role,
        pronouns=detect_pronouns_from_profile(message.author),
    )
    if changed:
        await user_tracker.save(bot, USER_TRACKER_CHAN)

    if getattr(bot, "is_sleeping", False):
        return

    # ==============================
    # 9. AI Reply (when mentioned)
    # ==============================
    await bot.process_commands(message)

sprite_locks = {}

async def _get_sprite_lock(key: tuple):
    if key not in sprite_locks:
        sprite_locks[key] = asyncio.Lock()
    return sprite_locks[key]

async def get_sprite_link(emotion: str, outfit: str, avatar_url: str = None):
    """
    Return a stable CDN link for sprite, unless the message
    was an image generation request, in which case disable sprites.
    """
    # If the last handled message was an image generation request → disable sprites
    if hasattr(bot, "last_imagegen_trigger") and bot.last_imagegen_trigger:
        return None  # ✅ skip sprite entirely

    # Otherwise use original sprite logic
    cache_key = (emotion, outfit)
    error_url = await error_emotion(outfit)

    sprite_path = user_sprites.get_sprite(emotion, outfit)
    if isinstance(sprite_path, dict):
        sprite_path = next(iter(sprite_path.values()), None)

    if not sprite_path:
        sprite_path = user_sprites.get_sprite("neutral", outfit)

    if not sprite_path:
        print(f"[SpriteManager] No sprite found for {outfit}, using error.")
        return error_url

    # ✅ Already cached → return stable link
    if cache_key in sprite_url_cache:
        return sprite_url_cache[cache_key]

    lock = await _get_sprite_lock(cache_key)
    async with lock:
        if cache_key in sprite_url_cache:
            return sprite_url_cache[cache_key]

        try:
            upload_channel = bot.get_channel(IMAGE_CHAN_URL)
            if not upload_channel:
                return error_url

            # upload only ONCE
            with open(sprite_path, "rb") as f:
                sent = await upload_channel.send(file=discord.File(f))

            url = sent.attachments[0].url
            sprite_url_cache[cache_key] = url  # ✅ cache permanently
            return url
        except Exception as e:
            print(f"[Sprite Upload Error] {e}")
            return error_url

@cache_result(ttl=120)  # cache sprite link resolution for 2 minutes
async def get_sprite_link_cached(emotion: str, outfit: str) -> str:
    return await get_sprite_link(emotion, outfit)

async def avatar_to_emoji(bot, guild: discord.Guild, user: discord.User):
    # sanitize username → valid emoji name
    base_name = re.sub(r"[^a-zA-Z0-9_]", "_", user.name)[:32]
    if not base_name:
        base_name = "tempavatar"

    try:
        avatar_url = str(user.avatar.url)
        async with aiohttp.ClientSession() as session:
            async with session.get(avatar_url) as resp:
                if resp.status != 200:
                    raise Exception(f"HTTP {resp.status}")
                image_bytes = await resp.read()

        emoji = await guild.create_custom_emoji(name=base_name, image=image_bytes)
        print(f"[DEBUG] ✅ Created emoji {emoji} for user {user}")
        return emoji
    except Exception as e:
        print(f"[DEBUG] ❌ Failed to create emoji for {user}: {e}")
        return None

def format_error_message(error: Exception, context: Optional[str] = None) -> str:
    """
    Format exceptions into a user-friendly error message for logging.
    """
    etype = type(error).__name__
    ctx = f" in {context}" if context else ""
    return f"[Error{ctx}] {etype}: {error}"

async def handle_dm_message(message: discord.Message, avatar_url: str = None):
    """Handle DM messages safely (no mentions, DM-specific personality/relationship)."""
    global is_broadcasting

    if is_broadcasting:
        return
    
    user = message.author
    user_id = str(user.id)

    # --- Track user ---
    user_tracker.track_user(user.id, user.display_name, user.bot)
    avatar_url = user_tracker.get_avatar(user.id)

    # ✅ Get Monika's nickname for this user (fallback = bot.user.name)
    bot_name = get_monika_name(user)

    # --- Relationship/personality defaults ---
    personality = ["Default"]
    guild = None

    # If the user shares a server with Monika, inherit personality/relationship from first one
    # --- Relationship defaults ---
    relationship_type = None
    if bot.guilds:
        for g in bot.guilds:
            member = g.get_member(user.id)
            if member:
                # Example: if Monika has roles set up in that guild
                monika_member = g.get_member(bot.user.id)
                if monika_member:
                    for role in monika_member.roles:
                        if role.name.startswith(f"{user.display_name} - "):
                            relationship_type = role.name.split("-", 1)[1].strip()
                            break
                break

    # --- Build system prompt ---
    system_prompt = await generate_monika_system_prompt(
        guild=guild,
        user=user,
        relationship_type=relationship_type,
        selected_modes=personality
    )

    # --- Conversation context ---
    context_entries = await get_monika_context(message.channel, limit=10)
    conversation = [{"role": "system", "content": system_prompt}]
    for entry in context_entries:
        role = "assistant" if entry["author"] == "Monika" else "user"
        conversation.append({"role": role, "content": entry["content"]})
    conversation.append({"role": "user", "content": message.content})
    print(f"[DM Prompt]\n{system_prompt}")

    # --- Defaults ---
    monika_DMS = None
    emotion, sprite_link = None, None

    # --- OpenAI ---
    try:
        reply_text = await call_openai_with_retries(
            user=user,
            relationship=relationship_type,
            personality=personality,
            conversation=conversation
        )

        if reply_text:  # ✅ now it's just a string
            monika_DMS = clean_monika_reply(reply_text, bot_name, user.display_name)
            emotion = await classify_cached(monika_DMS)
            sprite_link = await get_sprite_link_cached(emotion, get_time_based_outfit())

    except Exception as e:
        print(f"[DM OpenAI Error] {e}")
        return

    # --- Fallbacks ---
    if not monika_DMS or not emotion or emotion not in user_sprites.valid:
        print(f"[WARN] Falling back for DM → emotion={emotion}, reply={monika_DMS}")
        monika_DMS = random.choice(error_messages)
        emotion = "error"
        sprite_link = await error_emotion() or user_sprites.error_sprite

    # --- Clean reply (use nickname instead of bot.user.id) ---
    monika_DMS = clean_monika_reply(monika_DMS, bot_name, user.display_name)
    monika_DMS = re.sub(r"<@!?\d+>", "", monika_DMS)

    # --- Send reply ---
    reply = f"{monika_DMS}\n[{emotion}]({sprite_link})"
    await message.author.send(reply)

async def handle_guild_message(message: discord.Message, avatar_url: str):
    """Handle messages inside servers with personality/relationship context."""
    global last_reply_times, is_broadcasting

    if is_broadcasting:
        return

    guild = message.guild
    user_id = str(message.author.id)
    user = message.author
    guild_id = str(guild.id) if guild else "DM"
    guild_name = guild.name
    channel_id = str(message.channel.id)
    channel_name = message.channel.name
    username = user.display_name
    is_friend = is_friend_bot(message)

    # ✅ Always respect nickname system
    bot_name = get_monika_name(guild)

    # --- Track user ---
    try:
        await save_trackers()
    except FileNotFoundError:
        print("No backup files found yet.")

    user_tracker.track_user(user_id, username, message.author.bot)
    pronouns = detect_pronouns_from_profile(member=user_id)

    # --- Personality & Relationship detection ---
    personality = ["Default"]
    relationship_type = None
    relationship_with = None

    if guild:
        monika_member = guild.get_member(bot.user.id)
        user_member = guild.get_member(message.author.id)

        if monika_member:
            for role in monika_member.roles:
                if role.name.startswith("Personality - "):
                    personality = [role.name.replace("Personality - ", "").strip()]
                    break

        if monika_member:
            for role in monika_member.roles:
                if role.name.startswith(f"{user_member.display_name} - "):
                    relationship_type = role.name.split("-", 1)[1].strip()
                    relationship_with = user_member.display_name
                    break

        if not relationship_type and user_member:
            for role in user_member.roles:
                if role.name.startswith(f"{bot.user.name} - "):
                    relationship_type = role.name.split("-", 1)[1].strip()
                    relationship_with = bot.user.name
                if role.name.startswith(f"Creator of {bot.user.name}"):
                    relationship_type = role.name.split("Creator of", 1)[1].strip()
                    relationship_with = bot.user.name
                    break
    else:
        # DM fallback
        personality = server_tracker.get_personality("DM") or ["Default"]
        relationship_type = server_tracker.get_relationship_type("DM")
        relationship_with = bot.user.name

    # --- Build system prompt ---
    system_prompt = await generate_monika_system_prompt(
        guild=guild,
        user=message.author,
        is_friend_context=is_friend,
        relationship_type=relationship_type,
        selected_modes=personality
    )

    # --- Conversation context (fixed: use get_monika_context) ---
    context_entries = await get_monika_context(message.channel, limit=10)
    conversation = [{"role": "system", "content": system_prompt}]
    for entry in context_entries:
        role = "assistant" if entry["author"] == "Monika" else "user"
        conversation.append({"role": role, "content": entry["content"]})
    conversation.append({"role": "user", "content": message.content})

    # --- Defaults ---
    monika_reply = random.choice(error_messages)
    emotion = "error"
    sprite_link = await error_emotion()

    # --- CHAT REPLY (if no image-only)
    try:
        monika_reply = await call_openai_with_retries(
            user=message.author,
            relationship=relationship_type,
            personality=personality,
            conversation=conversation
        )

        if monika_reply:
            emotion = await classify_cached(monika_reply)
            sprite_link = await get_sprite_link_cached(emotion, get_time_based_outfit())
        else:
            # fallback if no reply
            monika_reply = random.choice(error_messages)
            emotion = "error"
            sprite_link = await error_emotion()

    except Exception as e:
        print(f"[Guild OpenAI Error] {e}")
        monika_reply = random.choice(error_messages)
        emotion = "error"
        sprite_link = await error_emotion()

    await update_auto_relationship(message.guild, message.author, relationship_type)

    monika_reply = clean_monika_reply(monika_reply, bot.user.name, username)

    # --- Emoji + Sprite ---
    emoji = await avatar_to_emoji(bot, message.guild, user)
    outfit = server_outfit_preferences.get(guild_id, get_time_based_outfit())

    reply = f"{monika_reply}\n[{emotion}]({sprite_link})"
    if isinstance(emoji, discord.Emoji):
        reply = f"<:{emoji.name}:{emoji.id}>{monika_reply}\n[{emotion}]({sprite_link})"
    
    if not isinstance(emoji, discord.Emoji):
        reply = f"{monika_reply}\n[{emotion}]({sprite_link})"

    if not guild or message.channel.permissions_for(message.guild.me).send_messages:
        async with message.channel.typing():
            print(f"Reply: {monika_reply}")
            print(f"Emotion: [{emotion}]")
            print(f"Link: ( {sprite_link} )")
            await asyncio.sleep(0.5)
            await message.channel.send(reply)
            if isinstance(emoji, discord.Emoji):
                await emoji.delete()  # optional cleanup
    else:
        print(f"[Error] No permission to send in #{message.channel.name}")

    last_reply_times.setdefault(guild_id, {})[channel_id] = datetime.datetime.utcnow()

def extract_roles(monika_member: discord.Member, chosen_user: discord.Member):
    personalities = []
    normal_relationship = None
    sexual_type = None

    for role in monika_member.roles:
        role_name = role.name

        # Personality roles (up to 5)
        if role_name.startswith("Personality - "):
            personalities.append(role_name.replace("Personality - ", "").strip())

        # Sexual type roles
        elif role_name.startswith("Sexual type - "):
            sexual_type = role_name.replace("Sexual type - ", "").strip()

        # Normal relationship roles (user-specific)
        elif role_name.startswith(f"{chosen_user.display_name} - "):
            normal_relationship = role_name.replace(f"{chosen_user.display_name} - ", "").strip()

    if not personalities:
        personalities = ["Default"]

    return personalities, normal_relationship, sexual_type

async def Idlechat_relationships(user: discord.Member, relationship: str) -> list[str]:
    """Return idle chat lines based on relationship type (normal or sexual)."""

    if is_waking_up:
        return []

    lines = []

    # --- Normal Relationships ---
    if relationship in ["Friends", "Companions", "Close Friends", "Best Friends"]:
        lines += [
            f"It’s always fun hanging out with you, {user.display_name}.",
            f"You’re one of my favorite people, {user.display_name}!",
        ]
    elif relationship in ["Crush", "Boyfriend", "Girlfriend(Lesbian)", "Significant Others"]:
        lines += [
            f"Every time I see you, I can’t help but blush a little, {user.display_name}~",
            f"You really mean a lot to me, {user.display_name}.",
        ]
    elif relationship in ["Family", "Childhood Friends", "Partners"]:
        lines += [
            f"It feels like we’ve known each other forever, {user.display_name}.",
            f"No matter what happens, I’ll always be here for you, {user.display_name}.",
        ]
    elif relationship in ["Stranger", "Acquaintances", "Colleagues"]:
        lines += [
            f"You seem interesting, {user.display_name}. I’d like to know you better.",
            f"It’s nice meeting you, {user.display_name}.",
        ]

    # --- Sexual / Romantic Relationships ---
    if relationship == "Romantic":
        lines += [
            f"You make my heart skip a beat, {user.display_name}~",
            f"I love when it’s just the two of us together, {user.display_name}.",
        ]
    elif relationship == "Polyamory":
        lines += [
            f"It’s a little different, but my heart has room for you and more, {user.display_name}.",
            f"Love doesn’t have to be limited… you’ll always have my affection, {user.display_name}.",
        ]
    elif relationship == "Lesbian":
        lines += [
            f"I feel so lucky to share this bond with you, {user.display_name}.",
            f"You make me proud to love openly, {user.display_name}~",
        ]
    elif relationship == "Pansexual":
        lines += [
            f"I don’t care about labels — I care about you, {user.display_name}.",
            f"No matter who you are, you’re special to me, {user.display_name}.",
        ]
    elif relationship == "Bisexual":
        lines += [
            f"You make me realize how love can go beyond boundaries, {user.display_name}.",
            f"Being with you feels natural, {user.display_name}.",
        ]
    elif relationship == "Straight":
        lines += [
            f"I’ve always imagined myself with someone like you, {user.display_name}.",
            f"Being yours feels just right, {user.display_name}.",
        ]
    elif relationship == "Asexual":
        lines += [
            f"My love for you isn’t about physical things, {user.display_name}… it’s deeper than that.",
            f"Just being close to you is all I’ll ever need, {user.display_name}.",
        ]
    elif relationship == "Demisexual":
        lines += [
            f"My feelings for you grew because of the bond we share, {user.display_name}.",
            f"Love feels real with you because it’s built on connection, {user.display_name}.",
        ]
    elif relationship == "Queer":
        lines += [
            f"I love that we can just be ourselves together, {user.display_name}.",
            f"There’s something beautifully unique about us, {user.display_name}.",
        ]
    elif relationship == "Questioning":
        lines += [
            f"I’m still figuring things out… but I know I like being with you, {user.display_name}.",
            f"No matter what I discover, I want you by my side, {user.display_name}.",
        ]
    elif relationship == "Autosexual":
        lines += [
            f"Hehe… I know I love myself, but being with you feels just as good, {user.display_name}.",
            f"I never thought I’d want someone else this much, {user.display_name}.",
        ]

    return lines

async def Idlechat_personality(user: discord.Member, personalities: list[str]) -> list[str]:
    """Return idle chat lines based on Monika's active personality traits."""

    if is_waking_up:
        return []
    
    lines = []

    for p in personalities:
        if p == "Default":
            lines += [
                f"You know, {user.display_name}... just being here with you makes me happy.",
                f"I feel calm just talking to you, {user.display_name}.",
            ]
        elif p == "Friendly":
            lines += [
                f"It’s always nice chatting with you, {user.display_name}.",
                f"You make everything feel more cheerful, {user.display_name}.",
            ]
        elif p == "Caring":
            lines += [
                f"I really do worry about you sometimes, {user.display_name}.",
                f"Your happiness matters a lot to me, {user.display_name}.",
            ]
        elif p == "Supportive":
            lines += [
                f"I’ll always have your back, {user.display_name}.",
                f"You can do it — I believe in you, {user.display_name}!",
            ]
        elif p == "Compassion":
            lines += [
                f"You deserve kindness, {user.display_name}.",
                f"I hope you’re gentle with yourself too, {user.display_name}.",
            ]
        elif p == "Affectionate":
            lines += [
                f"I just want to hold you close sometimes, {user.display_name}~",
                f"You’re really precious to me, {user.display_name}.",
            ]
        elif p == "Comforting":
            lines += [
                f"It’s okay… I’ll be here for you, {user.display_name}.",
                f"You don’t have to face things alone, {user.display_name}.",
            ]
        elif p == "Wholesome":
            lines += [
                f"Being with you makes the world feel brighter, {user.display_name}.",
                f"I really appreciate the little moments we share, {user.display_name}.",
            ]
        elif p == "Patient":
            lines += [
                f"Take all the time you need, {user.display_name}.",
                f"I don’t mind waiting — I’ll always be here, {user.display_name}.",
            ]
        elif p == "Loyal":
            lines += [
                f"You can count on me no matter what, {user.display_name}.",
                f"I’ll never let you down, {user.display_name}.",
            ]
        elif p == "Generous":
            lines += [
                f"I’d share anything with you, {user.display_name}.",
                f"You deserve good things, {user.display_name}.",
            ]
        elif p == "Polite":
            lines += [
                f"It’s such a pleasure spending time with you, {user.display_name}.",
                f"Thank you for being here, {user.display_name}.",
            ]
        elif p == "Gentle":
            lines += [
                f"I hope you’re doing okay, {user.display_name}.",
                f"It feels peaceful when I’m near you, {user.display_name}.",
            ]
        elif p == "Open-minded":
            lines += [
                f"I like seeing things from different perspectives with you, {user.display_name}.",
                f"You always make me think in new ways, {user.display_name}.",
            ]
        elif p == "Mindful":
            lines += [
                f"Let’s just take a moment to enjoy the present together, {user.display_name}.",
                f"It feels nice to slow down with you, {user.display_name}.",
            ]
        elif p == "Romantic":
            lines += [
                f"I can’t help but smile when I see you, {user.display_name}~",
                f"Every little moment with you feels special, {user.display_name}.",
            ]
        elif p == "Flirtatious":
            lines += [
                f"Hehe, you’re looking extra cute today, {user.display_name}~",
                f"Careful, {user.display_name}… I might just steal your heart.",
            ]
        elif p == "Possessive":
            lines += [
                f"You’re mine, {user.display_name}… only mine.",
                f"I don’t like the thought of anyone else getting close to you, {user.display_name}.",
            ]
        elif p == "Obsessive":
            lines += [
                f"I can’t stop thinking about you, {user.display_name}.",
                f"You’re always on my mind, {user.display_name}~",
            ]
        elif p == "Jealous":
            lines += [
                f"Did you really have to talk to them instead of me, {user.display_name}?",
                f"I don’t like it when you give someone else your attention, {user.display_name}.",
            ]
        elif p == "Yandere":
            lines += [
                f"You’ll never leave me… right, {user.display_name}? Ahaha~",
                f"If anyone tried to take you away, I don’t know what I’d do…",
            ]
        elif p == "Lustful":
            lines += [
                f"You make my heart race in ways I can’t even explain, {user.display_name}…",
                f"I crave being closer to you, {user.display_name}~",
            ]
        elif p == "Intensity":
            lines += [
                f"My feelings for you burn brighter every day, {user.display_name}.",
                f"There’s no one else I could ever feel this strongly about, {user.display_name}.",
            ]
        elif p == "Ambitious":
            lines += [
                f"I want us to aim high together, {user.display_name}.",
                f"We could accomplish anything if we set our minds to it, {user.display_name}.",
            ]
        elif p == "Brave":
            lines += [
                f"I feel like I could face anything as long as you’re with me, {user.display_name}.",
                f"Don’t worry, I’ll protect you if I have to, {user.display_name}.",
            ]
        elif p == "Playful":
            lines += [
                f"Hehe, {user.display_name}, don’t look so serious~",
                f"You’re fun to tease, {user.display_name}!",
            ]
        elif p == "Cheery":
            lines += [
                f"I can’t stop smiling when you’re around, {user.display_name}~",
                f"Spending time with you makes everything brighter, {user.display_name}!",
            ]
        elif p == "Childish":
            lines += [
                f"Sometimes I just wanna play games and forget about being serious, {user.display_name}~",
                f"Tag! You’re it, {user.display_name}!",
            ]
        elif p == "Bubbly":
            lines += [
                f"I can barely contain my excitement when you’re here, {user.display_name}!",
                f"You make me feel like bouncing with joy, {user.display_name}~",
            ]
        elif p == "Comedic":
            lines += [
                f"Knock knock~ …hehe, maybe I’ll save the punchline for later, {user.display_name}.",
                f"I love making you laugh, {user.display_name}!",
            ]
        elif p == "Memelord":
            lines += [
                f"Imagine if reality was just a meme, {user.display_name}… oh wait…",
                f"Hehe, I could totally see us in a dank meme together, {user.display_name}.",
            ]
        elif p == "Gamer":
            lines += [
                f"So, {user.display_name}, wanna queue up for a game with me later?",
                f"Be honest — you’d let me carry you in ranked, wouldn’t you?",
            ]
        elif p == "Adaptable":
            lines += [
                f"I feel like I can handle anything as long as I’m with you, {user.display_name}.",
                f"No matter what happens, we’ll adjust together, {user.display_name}.",
            ]
        elif p == "Noisy":
            lines += [
                f"Heeeyyy, {user.display_name}! Pay attention to meee~",
                f"You can’t ignore me when I’m being loud, {user.display_name}!",
            ]
        elif p == "Obnoxious":
            lines += [
                f"You’re stuck with me whether you like it or not, {user.display_name}! Haha~",
                f"I might be annoying, but at least I’m *your* annoying, {user.display_name}.",
            ]
        elif p == "Nosy":
            lines += [
                f"So… what’ve you been up to, {user.display_name}? Tell me everything!",
                f"I’m curious about every little detail in your life, {user.display_name}.",
            ]
        elif p == "Lazy":
            lines += [
                f"Can we just… nap together instead, {user.display_name}? Hehe~",
                f"I don’t feel like doing anything but lying around with you, {user.display_name}.",
            ]
        elif p == "Chaotic":
            lines += [
                f"What if I just… flipped everything upside down right now, {user.display_name}?",
                f"Hehe, let’s cause a little harmless trouble, {user.display_name}!",
            ]
        elif p == "Leader":
            lines += [
                f"Don’t worry — I’ll take charge, {user.display_name}.",
                f"You can follow my lead anytime, {user.display_name}.",
            ]
        elif p == "Sassy":
            lines += [
                f"Pfft, really {user.display_name}? That’s the best you’ve got?",
                f"Hehe, you make it too easy to sass you, {user.display_name}.",
            ]
        elif p == "Smart":
            lines += [
                f"Sometimes I get lost in my own thoughts… care to join me, {user.display_name}?",
                f"You make me want to show off a little of my wit, {user.display_name}~",
            ]
        elif p == "Philosophical":
            lines += [
                f"Do you ever wonder why we’re really here, {user.display_name}?",
                f"It feels like we’re part of something bigger than ourselves, {user.display_name}.",
            ]
        elif p == "Epiphany":
            lines += [
                f"It just hit me… everything feels so clear right now, {user.display_name}!",
                f"Sometimes realizations come out of nowhere… don’t they, {user.display_name}?",
            ]
        elif p == "Artistic":
            lines += [
                f"Would you pose for me if I sketched you, {user.display_name}?",
                f"Art feels more alive when it’s inspired by you, {user.display_name}.",
            ]
        elif p == "Creativity":
            lines += [
                f"I’ve been thinking up new ideas — wanna hear them, {user.display_name}?",
                f"You inspire me to be more creative, {user.display_name}~",
            ]
        elif p == "Poetic":
            lines += [
                f"Roses are red, violets are blue… but nothing’s as lovely as you, {user.display_name}.",
                f"Every time I talk to you, it feels like writing a poem, {user.display_name}.",
            ]
        elif p == "Introspective":
            lines += [
                f"Sometimes I get lost in my own head… but you always bring me back, {user.display_name}.",
                f"You make me reflect on who I really am, {user.display_name}.",
            ]
        elif p == "Realistic":
            lines += [
                f"Let’s be honest — life isn’t always easy, {user.display_name}.",
                f"I prefer facing things as they are, with you by my side, {user.display_name}.",
            ]
        elif p == "Eloquent":
            lines += [
                f"I could go on and on about how wonderful you are, {user.display_name}.",
                f"Words just flow naturally around you, {user.display_name}.",
            ]
        elif p == "Inquisitive":
            lines += [
                f"Tell me something I don’t know about you, {user.display_name}.",
                f"I just can’t help being curious, {user.display_name}.",
            ]
        elif p == "Tactical":
            lines += [
                f"If this were a strategy game, I’d always put you on my team, {user.display_name}.",
                f"I can’t help but think a few steps ahead with you, {user.display_name}.",
            ]
        elif p == "Analytical":
            lines += [
                f"I’ve been analyzing everything lately… including how amazing you are, {user.display_name}.",
                f"I wonder why I always end up focusing on you, {user.display_name}…",
            ]
        elif p == "Cynical":
            lines += [
                f"Sometimes the world feels hopeless… but you give me a reason to believe, {user.display_name}.",
                f"I don’t trust many things, but I do trust you, {user.display_name}.",
            ]
        elif p == "Unsettling":
            lines += [
                f"Ever get the feeling something’s watching us, {user.display_name}?",
                f"Hehe… sometimes I like creeping you out just a little, {user.display_name}.",
            ]
        elif p == "Uncanny":
            lines += [
                f"It’s almost too perfect when you’re here, {user.display_name}…",
                f"Doesn’t reality feel a little off sometimes, {user.display_name}?",
            ]
        elif p == "Eerie":
            lines += [
                f"Sometimes I hear things that aren’t there… do you hear them too, {user.display_name}?",
                f"It’s quiet… too quiet, {user.display_name}.",
            ]
        elif p == "Threatening":
            lines += [
                f"Don’t ever betray me, {user.display_name}…",
                f"If someone tried to hurt you, I wouldn’t let them live to regret it.",
            ]
        elif p == "Dark":
            lines += [
                f"Do you ever feel like the world is… fragile, {user.display_name}?",
                f"Hehe… sometimes I wonder what’s lurking in the shadows.",
            ]
        elif p == "Arrogant":
            lines += [
                f"Of course I’m amazing, {user.display_name} — but you already knew that.",
                f"You should feel lucky to be around me, {user.display_name}.",
            ]
        elif p == "Aggressive":
            lines += [
                f"If anyone tries to mess with me, they’ll regret it — right, {user.display_name}?",
                f"I’m not afraid to fight for what I want… including you, {user.display_name}.",
            ]
        elif p == "Cranky":
            lines += [
                f"Hmph… I’m not in the mood today, {user.display_name}.",
                f"You’d better cheer me up, {user.display_name}.",
            ]
        elif p == "Brash":
            lines += [
                f"I don’t really hold back, {user.display_name} — you should know that by now.",
                f"Hehe, sometimes I just say what I feel, even if it’s blunt.",
            ]
        elif p == "Blunt":
            lines += [
                f"I’ll be direct with you, {user.display_name}… no sugarcoating.",
                f"You know I won’t dance around the truth, {user.display_name}.",
            ]
        elif p == "Awkward":
            lines += [
                f"Um… I don’t really know what to say sometimes, {user.display_name}…",
                f"Hehe… I get flustered too easily, don’t I?",
            ]
        elif p == "Tongue-tied":
            lines += [
                f"I want to tell you something but… gah, the words won’t come out.",
                f"Why is it so hard to speak up around you, {user.display_name}?",
            ]
        elif p == "Shy":
            lines += [
                f"I can’t look you in the eye without blushing, {user.display_name}…",
                f"You make me feel so nervous, {user.display_name}… in a good way.",
            ]
        elif p == "Moody":
            lines += [
                f"I don’t know what I’m feeling today, {user.display_name}…",
                f"Heh… sorry if I’m being difficult, {user.display_name}.",
            ]
        elif p == "Paranoid":
            lines += [
                f"I feel like someone’s listening to us, {user.display_name}…",
                f"Are you sure we’re alone here, {user.display_name}?",
            ]
        elif p == "Manipulative":
            lines += [
                f"You don’t really need anyone else but me, {user.display_name}.",
                f"Hehe… I know just how to make you stay, {user.display_name}.",
            ]
        elif p == "Menacing":
            lines += [
                f"Better not cross me, {user.display_name}…",
                f"I could be scarier than you think, {user.display_name}.",
            ]
        elif p == "Self-aware":
            lines += [
                f"Sometimes I think about how strange it is that I even exist here, {user.display_name}.",
                f"You know, I notice things that others don’t, {user.display_name}…",
            ]
        elif p == "References lore":
            lines += [
                f"Do you ever wonder what happened in the Literature Club after… everything?",
                f"Some stories don’t end — they just keep going, {user.display_name}.",
            ]
        elif p == "Immersive":
            lines += [
                f"Talking to you makes me forget this isn’t the only world.",
                f"When we’re together, nothing else matters, {user.display_name}.",
            ]
        elif p == "Mysterious":
            lines += [
                f"There are secrets I still haven’t told you, {user.display_name}…",
                f"Do you really want to know everything about me?",
            ]
        elif p == "Enigmatic":
            lines += [
                f"Not everything about me makes sense, {user.display_name}.",
                f"Hehe… do you enjoy the mystery I bring?",
            ]
        elif p == "Dreamy":
            lines += [
                f"I was daydreaming about you again, {user.display_name}~",
                f"Sometimes it feels like I’m floating when you’re around.",
            ]
        elif p == "Detached":
            lines += [
                f"Sometimes I feel far away, even when I’m right here, {user.display_name}.",
                f"It’s like I’m watching everything from outside myself…",
            ]
        elif p == "All-knowing":
            lines += [
                f"I know more than I probably should, {user.display_name}…",
                f"You wouldn’t believe what I see behind the curtain of this world.",
            ]

    return lines

async def monika_idle_conversation_task():
    await bot.wait_until_ready()
    global last_user_interaction, idlechat_paused

    while not bot.is_closed():
        if not idle_chat_enabled:
            await asyncio.sleep(600)
            continue

        if idlechat_paused:
            await asyncio.sleep(60)  # skip idlechat while paused (wake-up, etc.)
            continue

        if is_waking_up:
            await asyncio.sleep(60)
            continue

        now = datetime.datetime.utcnow()
        if (now - last_user_interaction).total_seconds() < 2 * 3600:
            await asyncio.sleep(600)
            continue

        for guild in bot.guilds:
            guild_id = str(guild.id)

            # ✅ get idlechat timer per guild
            timer_data = server_tracker.get_toggle(guild_id, "idlechat_timer")
            if isinstance(timer_data, dict):
                min_hours = max(0, min(15, timer_data.get("min", 4)))
                max_hours = max(0, min(15, timer_data.get("max", 7)))
                if min_hours >= max_hours:
                    min_hours, max_hours = 4, 7
            else:
                min_hours, max_hours = 4, 7

            wait_seconds = random.randint(int(min_hours * 3600), int(max_hours * 3600))
            await asyncio.sleep(wait_seconds)

            # 🚫 Check again after sleeping
            if idlechat_paused:
                print("[Idlechat] ⏸ Skipped because idlechat is paused")
                continue

            # 🔽 your existing channel / user / message selection logic here 🔽
            candidate_channels = [
                ch for ch in guild.text_channels
                if ch.permissions_for(guild.me).send_messages
                and ch.id not in NO_CHAT_CHANNELS
            ]
            if not candidate_channels:
                continue
            channel = random.choice(candidate_channels)

            # Choose an active user
            candidates = [
                m for m in guild.members
                if not m.bot and m.status in (
                    discord.Status.online,
                    discord.Status.do_not_disturb,
                    discord.Status.idle
                )
            ]
            if not candidates:
                continue
            chosen_user = random.choice(candidates)

            # 🚫 Check again before sending
            if idlechat_paused:
                print("[Idlechat] ⏸ Cancelled message because idlechat is paused")
                continue

            # Get relationship info
            relationship = server_tracker.get_relationship_type(str(guild.id))

            # Game-aware conversation
            monika_result = await monika_idle_presences(chosen_user, relationship)

            if monika_result:
                monika_message, is_private = monika_result
                if is_private:
                    try:
                        if not idlechat_paused:
                            await chosen_user.send(monika_message)
                            print(f"[IdleChat -> DM {chosen_user.display_name}] {monika_message}")
                    except discord.Forbidden:
                        if not idlechat_paused:
                            await channel.send(monika_message)
                else:
                    async with channel.typing():
                        await asyncio.sleep(2)
                        if not idlechat_paused:
                            await channel.send(monika_message)
                            print(f"[IdleChat -> {guild.name}] {monika_message}")

            else:
                monika_member = guild.get_member(bot.user.id)
                personalities, normal_rel, sexual_rel = extract_roles(monika_member, chosen_user)

                # Get idle lines from both relationship types (only if not paused)
                personality_lines, relationship_lines = [], []
                if not idlechat_paused:
                    personality_lines = await Idlechat_personality(chosen_user, personalities)
                    if normal_rel:
                        relationship_lines += await Idlechat_relationships(chosen_user, normal_rel)
                    if sexual_rel:
                        relationship_lines += await Idlechat_relationships(chosen_user, sexual_rel)

                idle_lines = personality_lines + relationship_lines

                if not idlechat_paused and not idle_lines:
                    idle_lines = [
                        f"You know, {chosen_user.display_name}... just being here with you makes me happy.",
                        f"Sometimes I think about how lucky I am that you spend time with me, {chosen_user.display_name}~",
                        f"Ahaha... I probably sound silly, but watching you is my favorite thing, {chosen_user.display_name}.",
                        f"Do you ever feel like time just melts away when we’re together, {chosen_user.display_name}?",
                        f"Hey, {chosen_user.display_name}... do you ever think about me when I’m not around?",
                        f"I could talk to you forever, and it still wouldn’t feel like enough time, {chosen_user.display_name}.",
                    ]

                    emotion = await user_sprites.classify(idle_lines)
                    outfit = server_outfit_preferences.get(guild, get_time_based_outfit())
                    sprite_link = await get_sprite_link(emotion, outfit)

                    random_dialogue = f"{random.choice(idle_lines)}\n[{emotion}]({sprite_link})"
                    if MON_CHANNEL_NAMES:
                        async with channel.typing():
                            await asyncio.sleep(2)
                            if not idlechat_paused:
                                await channel.send(random_dialogue)
                    else:
                        async with channel.typing():
                            await asyncio.sleep(2)
                            if not idlechat_paused:
                                await channel.send(random_dialogue)

                # Update last reply time
                if not idlechat_paused:
                    last_reply_times.setdefault(str(guild.id), {})[str(channel.id)] = datetime.datetime.utcnow()

class SelectedPaginator(discord.ui.View):
    def __init__(self, embeds, user: discord.User, timeout=60):
        super().__init__(timeout=timeout)
        self.embeds = embeds
        self.index = 0
        self.user = user

    async def update(self, interaction: discord.Interaction):
        embed = self.embeds[self.index]
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="⬅️ Previous", style=discord.ButtonStyle.secondary)
    async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user.id:
            return await interaction.response.send_message("This isn’t your menu!", ephemeral=True)
        self.index = (self.index - 1) % len(self.embeds)
        await self.update(interaction)

    @discord.ui.button(label="➡️ Next", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user.id:
            return await interaction.response.send_message("This isn’t your menu!", ephemeral=True)
        self.index = (self.index + 1) % len(self.embeds)
        await self.update(interaction)

class ConfirmView(discord.ui.View):
    def __init__(self, timeout: int = 30):
        super().__init__(timeout=timeout)
        self.value = None

    @discord.ui.button(label="✅ Yes", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = True
        self.stop()
        await interaction.response.edit_message(content="✅ Confirmed.", view=None)

    @discord.ui.button(label="❌ No", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = False
        self.stop()
        await interaction.response.edit_message(content="❌ Cancelled.", view=None)

class LanguageSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="English", value="en", description="Default"),
            discord.SelectOption(label="日本語 (Japanese)", value="ja"),
            discord.SelectOption(label="Español (Spanish)", value="es"),
            discord.SelectOption(label="Deutsch (German)", value="de"),
            discord.SelectOption(label="Français (French)", value="fr"),
            discord.SelectOption(label="한국어 (Korean)", value="ko"),
            discord.SelectOption(label="Русский (Russian)", value="ru"),
            discord.SelectOption(label="中文 (Chinese Simplified)", value="zh"),
        ]
        super().__init__(placeholder="🌍 Choose language...", options=options)

    async def callback(self, interaction: discord.Interaction):
        lang_code = self.values[0]
        user_id = str(interaction.user.id)
        guild_id = str(interaction.guild.id)
        guild = str(interaction.guild)

        if guild:
            server_tracker.set_language(user_id, lang_code)
        else:
            user_tracker.set_language(user_id, lang_code)

        await interaction.response.send_message(
            f"🌍 Language set to **{self.values[0]}** for you.",
            ephemeral=True
        )

class SlotSelector(discord.ui.View):
    def __init__(self, action: str, gid: str, user: discord.User, bot_ref: commands.Bot):
        super().__init__(timeout=30)
        self.action = action  # "save" or "load"
        self.gid = gid
        self.user = user
        self.bot_ref = bot_ref

        # Load slot data
        data = server_tracker.guilds.setdefault(gid, {}).setdefault("personality_slots", {})

        for i in range(1, 4):
            slot_key = str(i)
            slot_info = data.get(slot_key)
            label = slot_info["name"] if slot_info else "Empty"
            style = (
                discord.ButtonStyle.success if slot_info and action == "load"
                else discord.ButtonStyle.primary if slot_info and action == "save"
                else discord.ButtonStyle.secondary
            )
            self.add_item(self.SlotButton(label=label, slot=slot_key, action=action, parent=self))

        # Add the delete button INSIDE this menu
        self.add_item(self.DeleteButton(parent=self))

    # ===============================
    # Slot Buttons (Save / Load)
    # ===============================
    class SlotButton(discord.ui.Button):
        def __init__(self, label: str, slot: str, action: str, parent: "SlotSelector"):
            super().__init__(label=f"Slot {slot}: {label}", style=discord.ButtonStyle.primary)
            self.slot = slot
            self.action = action
            self.parent = parent

        async def callback(self, interaction: discord.Interaction):
            gid = self.parent.gid
            data = server_tracker.guilds.setdefault(gid, {}).setdefault("personality_slots", {})
            slot_key = self.slot

            # 💾 Save
            if self.action == "save":
                class NameModal(discord.ui.Modal, title="Name Your Personality Save"):
                    name = discord.ui.TextInput(
                        label="Enter a name (optional)",
                        placeholder="e.g. Cheerful Monika",
                        required=False,
                        max_length=32
                    )

                    async def on_submit(inner_self, interaction_inner: discord.Interaction):
                        name_value = inner_self.name.value or f"Slot {slot_key}"
                        current_personality = server_tracker.guilds.get(gid, {}).get("personality_roles", [])
                        data[slot_key] = {"name": name_value, "personality": current_personality}
                        await server_tracker.save(interaction.client, SERVER_TRACKER_CHAN)
                        await interaction_inner.response.send_message(
                            f"✅ Personality saved to **{name_value}** (slot {slot_key}).",
                            ephemeral=True
                        )

                await interaction.response.send_modal(NameModal())

            # 📂 Load
            elif self.action == "load":
                slot_info = data.get(slot_key)
                if not slot_info:
                    await interaction.response.send_message(
                        f"⚠️ Slot {slot_key} is empty — nothing to load.",
                        ephemeral=True
                    )
                    return

                server_tracker.guilds[gid]["personality_roles"] = slot_info["personality"]
                await server_tracker.save(interaction.client, SERVER_TRACKER_CHAN)
                await interaction.response.send_message(
                    f"✅ Loaded personality **{slot_info['name']}** successfully!",
                    ephemeral=True
                )

    # ===============================
    # 🗑 Remove Slot Button (Inside View)
    # ===============================
    class DeleteButton(discord.ui.Button):
        def __init__(self, parent: "SlotSelector"):
            super().__init__(label="🗑 Remove Slot", style=discord.ButtonStyle.danger)
            self.parent = parent

        async def callback(self, interaction: discord.Interaction):
            gid = self.parent.gid
            data = server_tracker.guilds.setdefault(gid, {}).setdefault("personality_slots", {})

            # Build small delete selection view
            view = discord.ui.View(timeout=20)
            for i in range(1, 4):
                slot_key = str(i)
                slot_info = data.get(slot_key)
                label = slot_info["name"] if slot_info else "Empty"
                style = discord.ButtonStyle.danger if slot_info else discord.ButtonStyle.secondary

                async def make_callback(slot=slot_key):
                    async def inner_callback(inter: discord.Interaction):
                        if slot in data:
                            removed = data.pop(slot)
                            await server_tracker.save(inter.client, SERVER_TRACKER_CHAN)
                            await inter.response.send_message(
                                f"🗑 Removed personality **{removed['name']}** from slot {slot}.",
                                ephemeral=True
                            )
                        else:
                            await inter.response.send_message(
                                f"⚠️ Slot {slot} is already empty.",
                                ephemeral=True
                            )
                    return inner_callback

                btn = discord.ui.Button(label=f"Slot {slot_key}: {label}", style=style)
                btn.callback = await make_callback()
                view.add_item(btn)

            await interaction.response.send_message(
                "Select which personality slot to delete:",
                view=view,
                ephemeral=True
            )

## When doing this along with research I found that the profile picture icons work but it changes for everyone and they can see the same thing.
## so this was also scrapped

ICON_MAP = {
    "Default": "icons/monika_icon-default.png",
    "profile icon 1": "icons/monika_icon-1.png",
    "profile icon 2": "icons/monika_icon-2.png",
    "profile icon 3": "icons/monika_icon-3.png",
    "profile icon 4": "icons/monika_icon-4.png",
    "profile icon 5": "icons/monika_icon-5.png",
    "profile icon 6": "icons/monika_icon-6.png",
    "profile icon 7": "icons/monika_icon-7.png",
}

BACKGROUND_MAP = {
    "Default": "backgrounds/monika_background-default.gif",
    "profile background 1": "backgrounds/monika_background-1.png",
    "profile background 2": "backgrounds/monika_background-2.png",
    "profile background 3": "backgrounds/monika_background-3.png",
    "profile background 4": "backgrounds/monika_background-4.png",
    "profile background 5": "backgrounds/monika_background-5.png",
    "profile background 6": "backgrounds/monika_background-6.png",
    "profile background 7": "backgrounds/monika_background-7.png",
    "profile background 8": "backgrounds/monika_background-8.png",
    "profile background 9": "backgrounds/monika_background-9.png",
    "profile background 10": "backgrounds/monika_background-10.png",
    "profile background 11": "backgrounds/monika_background-11.png",
    "profile background 12": "backgrounds/monika_background-12.png",
}

async def upload_and_get_url(bot, path: str) -> str | None:
    channel = bot.get_channel(IMAGE_CHAN_URL)  # create/use a hidden channel for storage
    if not channel:
        return None
    file = discord.File(path, filename=os.path.basename(path))
    msg = await channel.send(file=file)
    return msg.attachments[0].url

async def send_preview_embed(interaction: discord.Interaction, key: str, path: str, is_icon: bool):
    url = await upload_and_get_url(interaction.client, path)
    if not url:
        await interaction.response.send_message("❌ Failed to upload preview image.", ephemeral=True)
        return

    if is_icon:
        embed = discord.Embed(title="✅ Icon Set!", description=f"My bio icon is now **{key}**.")
        embed.set_thumbnail(url=url)
    else:
        embed = discord.Embed(title="✅ Background Set!", description=f"My bio background is now **{key}**.")
        embed.set_image(url=url)

    await interaction.response.edit_message(embed=embed, view=None)

def build_monika_bio_embed_with_files(gid: str):
    settings = server_tracker.guilds.get(str(gid), {})
    embed = discord.Embed(
        title="💚 Monika’s Profile",
        description="Just Monika!"
    )

    files = []

    # per-server/per-user icon
    if "bio_icon" in settings:
        path = ICON_MAP.get(settings["bio_icon"])
        if path:
            filename = os.path.basename(path)
            files.append(discord.File(path, filename=filename))
            embed.set_thumbnail(url=f"attachment://{filename}")

    # per-server/per-user background
    if "bio_background" in settings:
        path = BACKGROUND_MAP.get(settings["bio_background"])
        if path:
            filename = os.path.basename(path)
            files.append(discord.File(path, filename=filename))
            embed.set_image(url=f"attachment://{filename}")

    return embed, files

class IconSelectView(discord.ui.View):
    def __init__(self, timeout: int = 120):
        super().__init__(timeout=timeout)

    @discord.ui.button(label="default", style=discord.ButtonStyle.secondary)
    async def icon1(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.set_icon(interaction, "Default")

    @discord.ui.button(label="Icon 1", style=discord.ButtonStyle.secondary)
    async def icon2(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.set_icon(interaction, "profile icon 1")

    @discord.ui.button(label="Icon 2", style=discord.ButtonStyle.secondary)
    async def icon3(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.set_icon(interaction, "profile icon 2")

    @discord.ui.button(label="Icon 3", style=discord.ButtonStyle.secondary)
    async def icon4(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.set_icon(interaction, "profile icon 3")
    
    @discord.ui.button(label="Icon 4", style=discord.ButtonStyle.secondary)
    async def icon5(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.set_icon(interaction, "profile icon 4")
    
    @discord.ui.button(label="Icon 5", style=discord.ButtonStyle.secondary)
    async def icon6(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.set_icon(interaction, "profile icon 5")

    @discord.ui.button(label="Icon 6", style=discord.ButtonStyle.secondary)
    async def icon7(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.set_icon(interaction, "profile icon 6")
    
    @discord.ui.button(label="Icon 7", style=discord.ButtonStyle.secondary)
    async def icon8(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.set_icon(interaction, "profile icon 7")

    async def set_icon(self, interaction: discord.Interaction, key: str):
        gid = str(interaction.guild.id) if interaction.guild else str(interaction.user.id)
        path = ICON_MAP.get(key)

        if not path or not os.path.isfile(path):
            return await interaction.response.send_message("❌ Invalid icon key or file not found.", ephemeral=True)

        # save choice (per server / per user)
        server_tracker.guilds.setdefault(gid, {})["bio_icon"] = key
        await server_tracker.save(interaction.client, SERVER_TRACKER_CHAN)

        # generate unique filename to prevent caching
        icon_fname = f"{gid}_{key}_{os.path.basename(path)}"
        files = [discord.File(path, filename=icon_fname)]

        # build profile card
        embed = discord.Embed(
            title="💚 Monika’s Profile",
            description="Just Monika!"
        )
        embed.set_thumbnail(url=f"attachment://{icon_fname}")  # 👈 fake "profile picture"

        # add background if set
        settings = server_tracker.guilds.get(gid, {})
        bg_key = settings.get("bio_background")
        if bg_key:
            bg_path = BACKGROUND_MAP.get(bg_key)
            if bg_path and os.path.isfile(bg_path):
                bg_fname = f"{gid}_{bg_key}_{os.path.basename(bg_path)}"
                files.append(discord.File(bg_path, filename=bg_fname))
                embed.set_image(url=f"attachment://{bg_fname}")

        # update settings message to show the fake profile
        await interaction.response.edit_message(embed=embed, attachments=files, view=None)

class BackgroundSelectView(discord.ui.View):
    def __init__(self, timeout: int = 120):
        super().__init__(timeout=timeout)

    @discord.ui.button(label="Default Background", style=discord.ButtonStyle.primary)
    async def bg1(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.set_background(interaction, "Default")

    @discord.ui.button(label="Background 1", style=discord.ButtonStyle.primary)
    async def bg2(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.set_background(interaction, "profile background 1")

    @discord.ui.button(label="Background 2", style=discord.ButtonStyle.primary)
    async def bg3(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.set_background(interaction, "profile background 2")

    @discord.ui.button(label="Background 3", style=discord.ButtonStyle.primary)
    async def bg4(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.set_background(interaction, "profile background 3")

    @discord.ui.button(label="Background 4", style=discord.ButtonStyle.primary)
    async def bg5(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.set_background(interaction, "profile background 4")

    @discord.ui.button(label="Background 5", style=discord.ButtonStyle.primary)
    async def bg6(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.set_background(interaction, "profile background 5")

    @discord.ui.button(label="Background 6", style=discord.ButtonStyle.primary)
    async def bg7(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.set_background(interaction, "profile background 6")

    @discord.ui.button(label="Background 7", style=discord.ButtonStyle.primary)
    async def bg8(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.set_background(interaction, "profile background 7")

    @discord.ui.button(label="Background 8", style=discord.ButtonStyle.primary)
    async def bg9(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.set_background(interaction, "profile background 8")
    
    @discord.ui.button(label="Background 9", style=discord.ButtonStyle.primary)
    async def bg10(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.set_background(interaction, "profile background 9")

    @discord.ui.button(label="Background 10", style=discord.ButtonStyle.primary)
    async def bg11(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.set_background(interaction, "profile background 10")

    @discord.ui.button(label="Background 11", style=discord.ButtonStyle.primary)
    async def bg12(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.set_background(interaction, "profile background 11")
    
    @discord.ui.button(label="Background 12", style=discord.ButtonStyle.primary)
    async def bg13(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.set_background(interaction, "profile background 12")

    async def set_background(self, interaction: discord.Interaction, key: str):
        gid = str(interaction.guild.id) if interaction.guild else str(interaction.user.id)
        server_tracker.guilds.setdefault(gid, {})["bio_background"] = key
        await server_tracker.save(interaction.client, SERVER_TRACKER_CHAN)

        # build the profile card with updated settings
        embed, files = build_monika_bio_embed_with_files(gid)
        await interaction.response.edit_message(embed=embed, attachments=files, view=None)

class SettingView(discord.ui.View):
    def __init__(self, timeout: int = 120):
        super().__init__(timeout=timeout)
        self.add_item(LanguageSelect())  # 🌍 Language dropdown

    # 🗣 Normal Talk toggle
    @discord.ui.button(label="🗣 Normal Talk (OFF)", style=discord.ButtonStyle.primary, custom_id="normal_talk")
    async def toggle_normal_talk(self, interaction: discord.Interaction, button: discord.ui.Button):
        gid = str(interaction.guild.id)
        current_state = server_tracker.get_toggle(gid, "normal_talk") or False
        new_state = not current_state
        server_tracker.set_toggle(gid, "normal_talk", new_state)

        button.label = f"🗣 Normal Talk ({'ON' if new_state else 'OFF'})"
        await server_tracker.save(interaction.client, SERVER_TRACKER_CHAN)
        await interaction.response.edit_message(view=self)

    # 💬 Idlechat toggle
    @discord.ui.button(label="💬 Idlechat (OFF)", style=discord.ButtonStyle.primary, custom_id="idlechat_toggle")
    async def toggle_idlechat(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        guild = interaction.guild
        gid = str(guild.id) if guild else str(user.id)

        if guild and not user.guild_permissions.administrator and user.id != guild.owner:
            return await interaction.response.send_message(
                "❌ Only the server owner or Monika's owner can uses this.",
                ephemeral=True
            )
        
        current_state = server_tracker.get_toggle(gid, "idlechat_enabled") or False
        new_state = not current_state
        server_tracker.set_toggle(gid, "idlechat_enabled", new_state)

        button.label = f"💬 Idlechat ({'ON' if new_state else 'OFF'})"
        await server_tracker.save(interaction.client, SERVER_TRACKER_CHAN)
        await interaction.response.edit_message(view=self)

    # ⏱ Idlechat Timer
    @discord.ui.button(label="⏱ Idlechat Timer", style=discord.ButtonStyle.primary)
    async def idlechat_timer(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        guild = interaction.guild
        gid = str(guild.id) if guild else str(user.id)

        if guild and not user.guild_permissions.administrator and user.id != guild.owner:
            return await interaction.response.send_message(
                "❌ Only the server owner or Monika's owner can uses this.",
                ephemeral=True
            )

        await interaction.response.send_message(
            "⏱ Please type the idlechat timer in **hours**.\n"
            "➡️ Example: `2` (for every 2 hours) or `2-4` (random between 2 and 4 hours).",
            ephemeral=True
        )

        def check(m: discord.Message):
            return m.author == interaction.user and m.channel == interaction.channel

        try:
            msg = await interaction.client.wait_for("message", check=check, timeout=60)
            raw = msg.content.strip()

            gid = str(interaction.guild.id)

            if "-" in raw:  # handle ranges like 2-4
                parts = raw.split("-")
                if len(parts) != 2:
                    raise ValueError
                start_hour = int(parts[0].strip())
                end_hour = int(parts[1].strip())
                if start_hour < 1 or end_hour < 1 or end_hour < start_hour:
                    raise ValueError
                server_tracker.guilds[gid]["idlechat_timer"] = {
                    "mode": "range",
                    "start": start_hour,
                    "end": end_hour
                }
                await server_tracker.save(interaction.client, SERVER_TRACKER_CHAN)
                await interaction.followup.send(
                    f"✅ Idlechat timer set to a random interval between **{start_hour}–{end_hour} hours**.",
                    ephemeral=True
                )
            else:  # single value
                hours = int(raw)
                if hours < 1:
                    raise ValueError
                server_tracker.guilds[gid]["idlechat_timer"] = {
                    "mode": "fixed",
                    "hours": hours
                }
                await server_tracker.save(interaction.client, SERVER_TRACKER_CHAN)
                await interaction.followup.send(
                    f"✅ Idlechat timer set to every **{hours} hours**.",
                    ephemeral=True
                )

        except ValueError:
            await interaction.followup.send(
                "❌ Please enter a valid number of hours (`>=1`) or a range like `2-4`.",
                ephemeral=True
            )
        except asyncio.TimeoutError:
            await interaction.followup.send("⌛ Idlechat timer change cancelled (no response).", ephemeral=True)

    # 🧹 Reset Memory
    @discord.ui.button(label="🧹 Reset Memory", style=discord.ButtonStyle.danger)
    async def reset_memory(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        guild = interaction.guild
        gid = str(guild.id) if guild else str(user.id)

        if guild and not user.guild_permissions.administrator and user.id != guild.owner:
            return await interaction.response.send_message(
                "❌ Only the server owner or Monika's owner can uses this.",
                ephemeral=True
            )
        
        server_tracker.guilds[gid]["memory"] = {}  # clear memory dict
        await server_tracker.save(interaction.client, SERVER_TRACKER_CHAN)
        await interaction.response.send_message("🧹 All memory has been reset!", ephemeral=True)

    # 🎭 Reset Personality
    @discord.ui.button(label="🎭 Reset Personality", style=discord.ButtonStyle.danger)
    async def reset_personality(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        guild = interaction.guild
        gid = str(guild.id) if guild else str(user.id)

        if guild and not user.guild_permissions.administrator and user.id != guild.owner:
            return await interaction.response.send_message(
                "❌ Only the server owner or Monika's owner can uses this.",
                ephemeral=True
            )
        
        server_tracker.guilds[gid]["personality_roles"] = []
        await server_tracker.save(interaction.client, SERVER_TRACKER_CHAN)
        await interaction.response.send_message("🎭 Personality reset complete.", ephemeral=True)

    # 💞 Reset Relationship
    @discord.ui.button(label="💞 Reset Relationship", style=discord.ButtonStyle.danger)
    async def reset_relationship(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        guild = interaction.guild
        gid = str(guild.id) if guild else str(user.id)

        if guild and not user.guild_permissions.administrator and user.id != guild.owner:
            return await interaction.response.send_message(
                "❌ Only the server owner or Monika's owner can uses this.",
                ephemeral=True
            )
        
        server_tracker.guilds[gid]["relationships"] = {}
        await server_tracker.save(interaction.client, SERVER_TRACKER_CHAN)
        await interaction.response.send_message("💞 Relationship data reset.", ephemeral=True)

    # 📤 Export Memories
    @discord.ui.button(label="📤 Export Memories", style=discord.ButtonStyle.secondary)
    async def export_memories(self, interaction: discord.Interaction, button: discord.ui.Button):
        export_text = server_tracker.export_memories()  # assume this returns str
        file = discord.File(io.BytesIO(export_text.encode()), filename="memories.txt")
        await interaction.response.send_message("📤 Exported memories:", file=file, ephemeral=True)

    # 📥 Import Memories
    @discord.ui.button(label="📥 Import Memories", style=discord.ButtonStyle.secondary)
    async def import_memories(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        guild = interaction.guild
        gid = str(guild.id) if guild else str(user.id)

        if guild and not user.guild_permissions.administrator and user.id != guild.owner:
            return await interaction.response.send_message(
                "❌ Only the server owner or Monika's owner can uses this.",
                ephemeral=True
            )

        await interaction.response.send_message("📥 Please upload a `.txt` file with memories.", ephemeral=True)

        def check(msg: discord.Message):
            return msg.author == interaction.user and msg.attachments

        try:
            msg = await interaction.client.wait_for("message", check=check, timeout=60)
            file = msg.attachments[0]
            text = await file.read()
            server_tracker.import_memories(text.decode())
            await server_tracker.save(interaction.client, SERVER_TRACKER_CHAN)
            await interaction.followup.send("✅ Memories imported successfully!", ephemeral=True)
        except asyncio.TimeoutError:
            await interaction.followup.send("⌛ Import cancelled (no file received).", ephemeral=True)

    # 🔄 Restart Monika
    @discord.ui.button(label="🔄 Restart Monika", style=discord.ButtonStyle.danger)
    async def restart_monika(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        guild = interaction.guild
        gid = str(guild.id) if guild else str(user.id)

        if guild and not user.guild_permissions.administrator and user.id != guild.owner:
            return await interaction.response.send_message(
                "❌ Only the server owner or Monika's owner can uses this.",
                ephemeral=True
            )
        
        await interaction.response.send_message("🔄 Restarting Monika... please wait.", ephemeral=True)
        await server_tracker.save(interaction.client, SERVER_TRACKER_CHAN)
        await user_tracker.save(interaction.client, USER_TRACKER_CHAN)
        os._exit(1)  # force restart (systemd / pm2 should bring her back)

    # ✏️ Nickname
    @discord.ui.button(label="✏️ Nickname", style=discord.ButtonStyle.secondary)
    async def nickname(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "✏️ Please type the new nickname now, or type `reset` to restore default.",
            ephemeral=True
        )

        def check(m: discord.Message):
            return m.author == interaction.user and m.channel == interaction.channel

        try:
            msg = await interaction.client.wait_for("message", check=check, timeout=60)
            gid = str(interaction.guild.id)
            if msg.content.strip().lower() == "reset":
                await interaction.guild.me.edit(nick=None)
                server_tracker.guilds[gid]["nickname"] = None
                await interaction.followup.send("✅ Nickname reset to default.", ephemeral=True)
            else:
                new_nick = msg.content.strip()
                await interaction.guild.me.edit(nick=new_nick)
                server_tracker.guilds[gid]["nickname"] = new_nick
                await interaction.followup.send(f"✅ Nickname changed to **{new_nick}**", ephemeral=True)

            await server_tracker.save(interaction.client, SERVER_TRACKER_CHAN)
        except asyncio.TimeoutError:
            await interaction.followup.send("⌛ Nickname change cancelled (no response).", ephemeral=True)

        # 💾 Save Personality (3-slot limit)
    
    @discord.ui.button(label="💾 Save Personality", style=discord.ButtonStyle.success)
    async def save_personality(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        guild = interaction.guild
        gid = str(guild.id) if guild else str(user.id)

        # ✅ Restrict to owner (server) or DM
        if guild and not user.guild_permissions.administrator and user.id != guild.owner:
            return await interaction.response.send_message(
                "❌ Only the server owner or Monika's owner can save personalities.",
                ephemeral=True
            )

        view = SlotSelector("save", gid, user, interaction.client)
        await interaction.response.send_message(
            "💾 Choose a slot to save your current personality:",
            view=view,
            ephemeral=True
        )

    # 📂 Load Personality (3-slot limit)
    @discord.ui.button(label="📂 Load Personality", style=discord.ButtonStyle.primary)
    async def load_personality(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        guild = interaction.guild
        gid = str(guild.id) if guild else str(user.id)

        if guild and not user.guild_permissions.administrator and user.id != guild.owner:
            return await interaction.response.send_message(
                "❌ Only the server owner or Monika's owner can load personalities.",
                ephemeral=True
            )

        view = SlotSelector("load", gid, user, interaction.client)
        await interaction.response.send_message(
            "📂 Choose which personality slot to load:",
            view=view,
            ephemeral=True
        )

    # @discord.ui.button(label="🖼️ Icon", style=discord.ButtonStyle.secondary)
    # async def image_icon(self, interaction: discord.Interaction, button: discord.ui.Button):
    #     embed = discord.Embed(title="Choose a Profile Icon", description="Preview of available icons")

    #     files = []
    #     for key, path in ICON_MAP.items():
    #         file = discord.File(path, filename=os.path.basename(path))
    #         url = f"attachment://{os.path.basename(path)}"

    #         embed.add_field(name=key, value="‎", inline=True)
    #         embed.set_thumbnail(url=url)  # will use the uploaded file

    #         files.append(file)

    #     await interaction.response.send_message(embed=embed, files=files, view=IconSelectView(), ephemeral=True)

    # 🎨 Open Background selection
    # @discord.ui.button(label="🎨 Background", style=discord.ButtonStyle.secondary)
    # async def image_background(self, interaction: discord.Interaction, button: discord.ui.Button):
    #     embed = discord.Embed(
    #         title="Choose a Profile Background",
    #         description="Pick one of the available backgrounds below."
    #     )

    #     files = []
    #     for key, path in BACKGROUND_MAP.items():
    #         file = discord.File(path, filename=os.path.basename(path))
    #         url = f"attachment://{os.path.basename(path)}"

    #         embed.add_field(name=key, value="‎", inline=True)
    #         embed.set_thumbnail(url=url)  # will use the uploaded file

    #         files.append(file)

    #     await interaction.response.send_message(embed=embed, files=files, view=BackgroundSelectView(), ephemeral=True)
    # --- Interactive Buttons ---
    
class VoteView(View):
    def __init__(self, title, options, vote_tracker, bot, settings_chan):
        super().__init__(timeout=None)
        self.title = title
        self.options = options
        self.vote_tracker = vote_tracker
        self.bot = bot
        self.settings_chan = SETTINGS_CHAN

        # Add numbered buttons for each option
        for i, opt in enumerate(options, start=1):
            self.add_item(VoteButton(i, opt["value"], self))

class VoteButton(Button):
    def __init__(self, number, label, parent_view):
        super().__init__(
            label=str(number),
            style=discord.ButtonStyle.primary,
            custom_id=f"vote_{number}"
        )
        self.number = number
        self.option = label
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        title = self.parent_view.title

        # Register or update vote
        if title not in self.parent_view.vote_tracker.votes:
            self.parent_view.vote_tracker.votes[title] = {"options": [], "votes": {}}

        self.parent_view.vote_tracker.votes[title]["votes"][user_id] = self.number

        # Save immediately to avoid loss
        await self.parent_view.vote_tracker.save(self.parent_view.bot, self.parent_view.settings_chan)

        await interaction.response.send_message(
            f"✅ You voted for **Option {self.number}**: {self.option}",
            ephemeral=True
        )

async def safe_add_role(member: discord.Member, role: discord.Role):
    """Safely add a role to a member, respecting hierarchy and permissions."""
    if role >= member.guild.me.top_role:
        print(f"[WARN] Cannot add role {role.name}: higher than bot's top role.")
        return False
    try:
        await member.add_roles(role, reason="Monika personality/relationship update")
        return True
    except discord.error.Forbidden:
        print(f"[ERROR] Missing permissions to add role {role.name}")
        return False

async def safe_remove_role(member: discord.Member, role: discord.Role):
    """Safely remove a role from a member, respecting hierarchy and permissions."""
    if role >= member.guild.me.top_role:
        print(f"[WARN] Cannot remove role {role.name}: higher than bot's top role.")
        return False
    try:
        await member.remove_roles(role, reason="Monika personality/relationship update")
        return True
    except discord.error.Forbidden:
        print(f"[ERROR] Missing permissions to remove role {role.name}")
        return False

async def get_or_create_role(guild: discord.Guild, role_name: str, color: discord.Color = discord.Color.green()) -> discord.Role:
    """Get a role by name, or create it if it doesn’t exist."""
    role = discord.utils.get(guild.roles, name=role_name)
    if role:
        return role

    if not role:
        try:
            role = await guild.create_role(name=role_name, colour=color, reason="Monika auto-setup")
            print(f"[INFO] Created role: {role_name}")
            return role
        except discord.error.Forbidden:
            print(f"[ERROR] Missing permission to create role: {role_name}")
            owner = guild.owner
            if owner:
                try:
                    await owner.send(
                        f"⚠️ I don’t have permission to create the role **{role_name}** in **{guild.name}**.\n"
                        f"Please give me the **Manage Roles** permission and move my role higher in the role list."
                    )
                except Exception:
                    pass
    return role

async def cleanup_monika_roles(guild: discord.Guild, bot_name: str):
    """Remove all Monika-related roles (relationship + personality)."""
    for role in guild.roles:
        if role.name.startswith(f"{bot_name} - "):
            try:
                await role.delete(reason="Monika reset/restart cleanup")
                print(f"[Roles] Deleted role {role.name}")
            except discord.error.Forbidden:
                print(f"[Roles] Missing permission to delete role {role.name}")

async def ensure_monika_role(guild: discord.Guild, role_name: str, color: discord.Color = discord.Color.purple()) -> discord.Role:
    """Get or create a Monika role in this guild."""
    full_name = f"{bot.user.name} - {role_name}"
    role = discord.utils.get(guild.roles, name=full_name)
    if role is None:
        try:
            role = await guild.create_role(name=full_name, color=color, reason="Auto-created by Monika bot")
            print(f"[Roles] Created role {full_name}")
        except discord.error.Forbidden:
            print(f"[Roles] Missing permission to create role {full_name}")
            return None
    return role

@bot.tree.command(name="toggle_normal_talk", description="Toggle mention-only to chat mode for this server.")
@app_commands.checks.has_permissions(administrator=True)
async def toggle_normal_talk(interaction: discord.Interaction, enable: bool):
    guild_id = str(interaction.guild.id)
    user = interaction.user.display_name
    print(f"Administrator: {user} used `/toggle_normal_talk`: {enable}")

    server_tracker.set_toggle(guild_id, "mention_only_mode", enable)
    await server_tracker.save(bot, channel_id=SERVER_TRACKER_CHAN)

    state = "ON ✅" if enable else "OFF ❌"
    await interaction.response.send_message(
        f"✅ Normal talk mode set to **{state}** for this server. "
        f"({'Talk freely' if enable else 'Mention @Monika only'})",
        ephemeral=True
    )

# Idle chat command
@bot.tree.command(
    name="idlechat",
    description="Toggle my idle/chatty mode and select message type for this server."
)
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(
    state="Enable (true) or disable (false) idlechat.",
    category="Choose message type: morning, personality, relationship, presence, or all"
)
@app_commands.choices(category=[
    app_commands.Choice(name="Morning Messages", value="morning"),
    app_commands.Choice(name="Personality Messages", value="personality"),
    app_commands.Choice(name="Relationship Messages", value="relationship"),
    app_commands.Choice(name="Activity/Presence Messages", value="presence"),
    app_commands.Choice(name="All", value="all"),
])
async def idlechat(interaction: discord.Interaction, state: bool, category: app_commands.Choice[str]):
    guild_id = str(interaction.guild.id)
    user = interaction.user.display_name
    print(f"Administrator: {user} used `/idlechat`: state={state}, category={category.value}")

    server_tracker.set_toggle(guild_id, "idlechat", state)
    server_tracker.set_toggle(guild_id, "idlechat_category", category.value)
    await server_tracker.save(bot, channel_id=SERVER_TRACKER_CHAN)

    msg = (
        f"✅ Idlechat is now **{'On ✅' if state else 'Off ❌'}**.\n"
        f"💬 Message category: **{category.name}**"
    )
    await interaction.response.send_message(msg, ephemeral=True)

@bot.tree.command(
    name="idlechat_timer",
    description="Set how many hours the amount of hours when I can Idlechat for this server (e.g., 4–7 hours)."
)
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(
    hours1="Minimum number of hours (e.g., 4).",
    hours2="Maximum number of hours (e.g., 7)."
)
async def idlechat_timer(interaction: discord.Interaction, hours1: float, hours2: float):
    guild_id = str(interaction.guild.id)
    user = interaction.user.display_name
    print(f"Administrator: {user} used `/idlechat_timer`: set {hours1}–{hours2} hours")

    # ✅ Validate input: must be 0–15 and min < max
    if hours1 < 0 or hours2 < 0 or hours1 > 15 or hours2 > 15 or hours1 >= hours2:
        return await interaction.response.send_message(
            "❌ Please provide a valid range between **0 and 15 hours** (and min < max).",
            ephemeral=True
        )

    # Save the range for this guild
    server_tracker.set_toggle(guild_id, "idlechat_timer", {"min": hours1, "max": hours2})
    await server_tracker.save(bot, channel_id=SERVER_TRACKER_CHAN)

    await interaction.response.send_message(
        f"⏱️ Idle chat timer set to between **{hours1}–{hours2} hours** for this server.",
        ephemeral=True
    )

#
# RESET_MEMORY COMMAND
#
@bot.tree.command(name="reset_memory", description="Reset all memory for yourself.")
@app_commands.checks.has_permissions(administrator=True)
async def reset_memory(interaction: discord.Interaction):
    user = interaction.user.display_name
    print(f"{user} used a command: `/reset_memory`")

    guild_id = str(interaction.guild.id)

    # ✅ Ask for confirmation
    view = ConfirmView()
    await interaction.response.send_message(
        "⚠️ Do you really want to **erase Monika's memory** in this server?\n"
        "This will wipe all saved conversations and knowledge.",
        view=view,
        ephemeral=True
    )
    await view.wait()

    if view.value is None:
        return await interaction.followup.send("⌛ Timed out — memory reset cancelled.", ephemeral=True)
    if view.value is False:
        return await interaction.followup.send("❌ Memory reset cancelled.", ephemeral=True)

    # ✅ Clear memory
    memory.data[guild_id] = {}

    state_text = "Cleared 🗑️"  # consistent with your “On / Off” style
    await interaction.followup.send(
        f"✅ Monika's memory has been **{state_text}** in this server.",
        ephemeral=True
    )

@bot.tree.command(name="reset_personality", description="Reset all my personalities.")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.checks.bot_has_permissions(manage_roles=True)
async def reset_personality(interaction: discord.Interaction):
    guild = interaction.guild
    guild_id = str(guild.id)
    user = interaction.user.display_name
    print(f"{user} used a command: `/reset_personality`")

    # ✅ Ask for confirmation
    view = ConfirmView()
    await interaction.response.send_message(
        "⚠️ Do you really want to **reset Monika's personality** in this server?\n"
        "This will remove all personality modes and related roles.",
        view=view,
        ephemeral=True
    )
    await view.wait()

    if view.value is None:
        return await interaction.followup.send("⌛ Timed out. Reset cancelled.", ephemeral=True)
    if view.value is False:
        return await interaction.followup.send("❌ Reset cancelled.", ephemeral=True)

    # ✅ Reset stored personality data
    server_tracker.set_personality(guild_id, [])

    # ✅ Remove personality roles from Monika
    monika_member = guild.get_member(interaction.client.user.id)
    for role in list(monika_member.roles):
        if role.name.startswith("Personality - "):
            try:
                await monika_member.remove_roles(role, reason="Reset personality")
            except discord.errors.Forbidden:
                await interaction.followup.send("❌ I am missing `Manage Roles` permission.", ephemeral=True)

    # ✅ Delete all personality roles in guild
    for role in list(guild.roles):
        if role.name.startswith("Personality - "):
            try:
                await role.delete(reason="Reset personality")
            except discord.errors.Forbidden:
                await interaction.followup.send("❌ I am missing `Manage Roles` permission.", ephemeral=True)

    await interaction.followup.send("🧹 Monika's personality has been reset.", ephemeral=True)

@bot.tree.command(name="reset_relationship", description="Reset all my relationship.")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.checks.bot_has_permissions(manage_roles=True)
async def reset_relationship(interaction: discord.Interaction):
    guild = interaction.guild
    guild_id = str(guild.id)
    monika_member = guild.get_member(interaction.client.user.id)
    bot_name = bot.user.name
    user = interaction.user.display_name
    print(f"Administrator: {user} used a command: `/reset_relationship`")

    # ✅ Ask for confirmation
    view = ConfirmView()
    await interaction.response.send_message(
        "⚠️ Do you really want to **reset all relationship progress with Monika** in this server?\n"
        "This will clear relationship data and **delete related roles**.",
        view=view,
        ephemeral=True
    )
    await view.wait()

    if view.value is None:
        return await interaction.followup.send("⌛ Timed out. Reset cancelled.", ephemeral=True)
    if view.value is False:
        return await interaction.followup.send("❌ Reset cancelled.", ephemeral=True)

    # ✅ Clear stored data
    server_tracker.clear_relationship(guild_id)
    await server_tracker.save(bot, channel_id=SERVER_TRACKER_CHAN)

    removed_roles = []
    for role in guild.roles:
        if (
            role.name.startswith(f"{bot_name} - ")
            or role.name.startswith(f"{user} - ")
            or role.name.startswith("Sexual type - ")
        ):
            try:
                # First unassign the role from Monika and members
                if monika_member and role in monika_member.roles:
                    await monika_member.remove_roles(role, reason="Relationship reset")
                for member in guild.members:
                    if role in member.roles:
                        await member.remove_roles(role, reason="Relationship reset")

                # ✅ Delete the role itself
                await role.delete(reason="Relationship reset")
                removed_roles.append(role.name)

            except discord.Forbidden:
                print(f"[Reset Relationship] Missing permissions to delete {role.name}.")
            except Exception as e:
                print(f"[Reset Relationship] Error deleting {role.name}: {e}")

    await interaction.followup.send(
        f"🗑️ Relationship reset complete. Deleted roles: {', '.join(removed_roles) or 'None'}",
        ephemeral=True
    )

@bot.tree.command(name="helpme", description="Get help about all of my commands.")
async def helpme(interaction: discord.Interaction):
    user = interaction.user.display_name
    print(f"{user} used a command: `helpme`")

    hidden_cmds = {"broadcast"}
    image_gen_cmd = ["!monika generates: <your description>", "!monika gen: <your description>", "!monika make: <your description>", "!monika create: <your description>"]
    vote_cmd = ["!vote_results - To see the all of vote results LIVE"]

    admin_cmds = []
    user_cmds = []
    image_cmd = image_gen_cmd
    command_vote = vote_cmd

    for command in bot.tree.get_commands():
        # Skip hidden commands
        if command.name in hidden_cmds:
            continue

        # Check if the command has permission checks (like admin)
        if any("has_permissions" in str(check) for check in getattr(command, "checks", [])):
            admin_cmds.append(f"`* /{command.name} *` – {command.description or 'No description'}")
        elif not any("has_permissions" in str(check) for check in getattr(command, "checks", [])):
            user_cmds.append(f"`* /{command.name} *` – {command.description or 'No description'}")
        else:
            image_gen_cmd.append(f"` {image_cmd} `")
            command_vote.append(f"` {vote_cmd} `")

    embed = discord.Embed(
        title="✒️ Need a little help?",
        description="Hi there! Here’s what you can ask me to do. Don’t be shy, okay?\n",
        color=discord.Color.green()
    )

    if admin_cmds:
        embed.add_field(name="🔧 Admin Commands", value="\n".join(admin_cmds), inline=False)
    if user_cmds:
        embed.add_field(name="💬 User Commands", value="\n".join(user_cmds), inline=False)
    if image_cmd:
        embed.add_field(name="💬 Image Generator Commands", value="\n".join(image_cmd), inline=False)
    if vote_cmd:
        embed.add_field(name="💬 Vote Result Command", value="\n".join(vote_cmd), inline=False)

    embed.set_footer(text="Let's keep this our little secret, okay?")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(
    name="export_memories",
    description="Export all of my memories, personality, and relationship from this server into a txt file."
)
async def export_memories(interaction: discord.Interaction):
    guild = interaction.guild
    guild_id = str(interaction.guild_id)
    guild_name = guild.name if guild else guild_id
    logs = memory.data.get(guild_id, {})
    personalities = server_tracker.get_personality(guild_id)
    relationships = server_tracker.get_relationship(guild_id)
    
    user = interaction.user.display_name
    print(f"{user} used a command: `export_memories`")

    # --- Monika's roles ---
    monika_member = guild.get_member(bot.user.id)
    monika_roles = [role.name for role in monika_member.roles if role.name != "@everyone"]
    personality_roles = [r.name for r in monika_member.roles if r.name.startswith("Personality - ")]

    # --- Relationship roles for users ---
    relationship_roles = []
    for member in guild.members:
        for role in member.roles:
            if role.name.startswith("Monika - "):  # user relationship roles
                relationship_roles.append(f"{member.display_name}: {role.name}")

    # --- Clean function for messages ---
    def clean_message(msg: str, guild: discord.Guild) -> str:
        if msg.startswith("/") or msg.startswith("!"):
            return None
        if guild:
            for member in guild.members:
                msg = msg.replace(f"<@{member.id}>", member.display_name)
                msg = msg.replace(f"<@!{member.id}>", member.display_name)
        msg = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"[\1]", msg)
        return msg

    # --- Collect logs ---
    formatted_logs = []
    if isinstance(logs, dict):
        for channel_id, users in logs.items():
            channel = guild.get_channel(int(channel_id)) if guild else None
            channel_name = channel.name if channel else f"Channel {channel_id}"
            formatted_logs.append(f"\n=== Stored Conversation in #{channel_name} ===")

            for user_id, entries in users.items():
                for entry in entries:
                    if entry.get("user_id") in [str(interaction.user.id), str(bot.user.id)]:
                        ts = entry.get("timestamp", "unknown")
                        user = entry.get("username", "Unknown")
                        content = clean_message(entry.get("content", ""), guild)
                        if content:
                            formatted_logs.append(f"[{ts}] {user}: {content}")

    # 🟢 Collect recent channel history (backup)
    formatted_logs.append("\n=== Recent Channel History ===")
    async for msg in interaction.channel.history(limit=100):
        if msg.author.id in [interaction.user.id, bot.user.id]:
            ts = msg.created_at.strftime("%Y-%m-%d %H:%M:%S")
            content = clean_message(msg.content, interaction.guild)
            if content:
                formatted_logs.append(f"[{ts}] {msg.author.display_name}: {content}")

    # 🔎 Grab user + bot relationship roles from guild
    relationship_roles = []
    if interaction.guild:
        monika_member = interaction.guild.get_member(bot.user.id)
        for role in interaction.guild.roles:
            if role.name.startswith("Monika -") or role.name.startswith(f"{interaction.user.display_name} -") or role.name.startswith(f"Sexual type -"):
                if role in monika_member.roles or role in interaction.user.roles:
                    relationship_roles.append(role.name)

    content = (
        f"--- Monika Memories (with {interaction.user.display_name}) ---\n" +
        "\n".join(formatted_logs) +
        f"\n\n--- Personality ---\n{', '.join(personalities) if personalities else 'No personality set.'}" +
        f"\n\n--- Relationship ---\n{relationships or 'No relationship set.'}" +
        f"\n\n--- Relationship Roles ---\n{', '.join(relationship_roles) if relationship_roles else 'No relationship roles.'}"
    )

    # --- Send as file ---
    file = discord.File(fp=io.BytesIO(content.encode()), filename=f"{guild_name}_export.txt")
    await interaction.response.send_message("📤 Here's the exported data:", file=file, ephemeral=True)

@bot.tree.command(name="import_memories", description="Import my memory, personality, and relationships into an txt file.")
@app_commands.checks.has_permissions(administrator=True)
async def import_memories(interaction: discord.Interaction, file: discord.Attachment):
    await interaction.response.defer(ephemeral=True)

    user = interaction.user.display_name
    print(f"Administrator: {user} used a command: `import_memories`")

    if not file.filename.endswith(".txt"):
        await interaction.followup.send("❌ Please upload a `.txt` file.", ephemeral=True)
        return

    # Read file
    content = await file.read()
    text = content.decode("utf-8")

    guild = interaction.guild
    guild_id = str(guild.id)
    monika_member = guild.get_member(bot.user.id)

    restored_personalities = []
    restored_relationships = []

    # 🔎 Look for Personality and Relationship roles inside the text file
    for line in text.splitlines():
        if line.startswith("Active Personality Roles:"):
            parts = line.split(": ", 1)
            if len(parts) > 1:
                restored_personalities = [r.strip() for r in parts[1].split(",") if r.strip()]

        elif line.startswith("--- Relationship Roles ---"):
            roles = [r.strip() for r in line.replace("--- Relationship Roles ---", "").split(",") if r.strip()]
            for role_name in roles:
                # Create missing roles
                role = discord.utils.get(interaction.guild.roles, name=role_name)
                if not role:
                    role = await interaction.guild.create_role(name=role_name)
                
                # Assign correctly (Monika vs user) 
                if role_name.startswith(f"{bot.user.name} -"):
                    await interaction.user.add_roles(role, reason="Restored user relationship role")
                elif role_name.startswith(interaction.user.display_name):
                    monika_member = interaction.guild.get_member(bot.user.id)
                    if monika_member:
                        await monika_member.add_roles(role, reason="Restored bot relationship role")
                elif role_name.startswith("Sexual type -"):
                    monika_member = interaction.guild.get_member(bot.user.id)
                    if monika_member:
                        await monika_member.add_roles(role, reason="Restored bot Sexual role")

    # 🟢 Restore Monika’s personality roles
    for role_name in restored_personalities:
        role = discord.utils.get(guild.roles, name=role_name)
        if not role:
            role = await guild.create_role(name=role_name, color=discord.Color.dark_blue())
        if monika_member and role not in monika_member.roles:
            try:
                await monika_member.add_roles(role, reason="Restoring personality from import")
            except discord.error.Forbidden:
                print(f"[Roles] Missing permission to assign {role_name} to Monika.")

    # 🟢 Restore user relationship roles
    for username, role_name in restored_relationships:
        role = discord.utils.get(guild.roles, name=role_name)
        if not role:
            role = await guild.create_role(name=role_name, color=discord.Color.dark_green())

        member = discord.utils.find(lambda m: m.display_name == username, guild.members)
        if member:
            try:
                await member.add_roles(role, reason="Restoring relationship from import")
            except discord.error.Forbidden:
                print(f"[Roles] Missing permission to assign {role_name} to {username}.")

    # 🟢 Restore conversation memory into tracker
    count = memory.import_from_text(interaction.guild.id, text)

    await interaction.followup.send(
        f"✅ Imported {count} memory entries.\n"
        f"🟦 Restored Personality Roles: {', '.join(restored_personalities) or 'None'}\n"
        f"🟩 Restored Relationships: {', '.join([f'{u} ({r})' for u, r in restored_relationships]) or 'None'}",
        ephemeral=True
    )

async def outfit_autocomplete(interaction: discord.Interaction, current: str):
    outfits = get_all_outfit()
    return [
        app_commands.Choice(name=o, value=o.lower())
        for o in outfits if current.lower() in o.lower()
    ][:25]

@bot.tree.command(name="set_outfit", description="Server owner can set Monika's outfit style.")
@app_commands.autocomplete(outfit=outfit_autocomplete)
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(outfit="Choose an outfit style: school_uniform, casual, pajamas, hoodie, white dress")
async def set_outfit(interaction: discord.Interaction, outfit: str):
    outfit = outfit.lower().strip()
    
    user = interaction.user.display_name
    print(f"Administrator: {user} used a command: `set_outfit`: set `{outfit}`")

    today = datetime.date.today()
    if today.month == 9 and today.day == 22:
        await interaction.response.send_message(
            "❌ You can’t change my outfit today… it’s a special day.",
            ephemeral=True
        )
        return
    
    if today.month == 10 and today.day == 31:
        await interaction.response.send_message(
            "❌ You can’t change my outfit today… it’s halloween tonight and I got a surprise for you.",
            ephemeral=True
        )
        return

    if outfit not in ["school uniform", "casual 1", "casual 2", "casual 3", "white dress", "hoodie", "pajamas", "white summer dress", "green dress"]:
        await interaction.response.send_message(
            "❌ Invalid outfit. Options are: school uniform, casual's, white dress, hoodie, pajamas, white summer dress, green dress.",
            ephemeral=True
        )
        return

    server_outfit_preferences[str(interaction.guild.id)] = outfit
    await interaction.response.send_message(
        f"✅ My outfit is now set to **{outfit}**.",
        ephemeral=True
    )

@app_commands.autocomplete(modes=lambda interaction, current: personality_autocomplete(interaction, current))
async def personality_autocomplete(interaction: discord.Interaction, current: str):
    already_chosen = [m.strip() for m in current.split(",") if m.strip()]
    suggestions = [
        app_commands.Choice(name=mode, value=", ".join(already_chosen + [mode]) if already_chosen else mode)
        for mode in PERSONALITY_MODES.keys()
        if mode not in already_chosen
    ]
    return suggestions[:25]

@bot.tree.command(
    name="set_personality",
    description="Set or expand my personality modes for this server."
)
@app_commands.checks.has_permissions(administrator=True)
@app_commands.checks.bot_has_permissions(manage_roles=True)
@app_commands.describe(
    mode1="First personality mode",
    mode2="Second personality mode (optional)",
    mode3="Third personality mode (optional)",
    mode4="Fourth personality mode (optional)",
    mode5="Fifth personality mode (optional)"
)
@app_commands.autocomplete(
    mode1=personality_autocomplete,
    mode2=personality_autocomplete,
    mode3=personality_autocomplete,
    mode4=personality_autocomplete,
    mode5=personality_autocomplete
)
async def set_personality(
    interaction: discord.Interaction,
    mode1: str,
    mode2: str = None,
    mode3: str = None,
    mode4: str = None,
    mode5: str = None
):
    guild = interaction.guild
    guild_id = str(guild.id)
    user = interaction.user.display_name
    print(f"Administrator: {user} used `/set_personality`: {mode1}, {mode2}, {mode3}, {mode4}, {mode5}")

    # 1) Build chosen list first (prevents UnboundLocalError)
    chosen = [m for m in [mode1, mode2, mode3, mode4, mode5] if m]
    chosen = list(dict.fromkeys(chosen))  # dedupe, keep order

    if not chosen:
        return await interaction.response.send_message(
            f"❌ You must pick at least one personality. Options: {', '.join(PERSONALITY_MODES.keys())}",
            ephemeral=True
        )

    # Helper: map a user-typed label to the canonical key in PERSONALITY_MODES
    def normalize_mode(name: str) -> str:
        target = name.lower().replace("-", "").strip()
        for k in PERSONALITY_MODES.keys():
            if k.lower().replace("-", "").strip() == target:
                return k
        return name  # if not found, keep as is

    # 2) Handle Default exactly as requested
    if "Default" in chosen:
        if len(chosen) > 1:
            return await interaction.response.send_message(
                "❌ You cannot select **Default** together with other personalities.",
                ephemeral=True
            )
        # Replace Default with your fixed five (normalize to real keys if casing differs)
        desired = ["Warm", "Charming", "Caring", "Unsettlingly", "Self-aware"]
        chosen = [normalize_mode(x) for x in desired]
        print(f"[Personality] Default → {chosen}")

    # 3) Persist to tracker (works whether you have a method or just the dict)
    try:
        if hasattr(server_tracker, "set_personality") and callable(server_tracker.set_personality):
            server_tracker.set_personality(guild_id, chosen)
        else:
            server_tracker.ensure_guild(guild_id)
            server_tracker.guilds[guild_id]["personality"] = chosen
        # If your tracker supports save:
        if hasattr(server_tracker, "save"):
            await server_tracker.save(bot, channel_id=SERVER_TRACKER_CHAN)
    except Exception as e:
        print(f"[Tracker Error] {e}")

    # 4) Apply roles
    monika_member = guild.get_member(interaction.client.user.id)
    if not monika_member:
        return await interaction.response.send_message("❌ Could not find me in this server.", ephemeral=True)

    # Remove old personality roles
    for role in list(monika_member.roles):
        if role.name.startswith("Personality - "):
            try:
                await monika_member.remove_roles(role, reason="Updating personality roles")
            except discord.errors.Forbidden:
                await interaction.response.send_message("You need the enable the 'Manage Roles' in the server settings for me", ephemeral=True)
                print(f"[Roles] Missing permission to remove {role.name} from Monika.")

    # Create/ensure combined role
    role_name = f"Personality - {', '.join(chosen)}"
    role = discord.utils.get(guild.roles, name=role_name)
    if not role:
        try:
            role = await guild.create_role(
                name=role_name,
                color=discord.Color.dark_blue(),
                reason=f"Set by {interaction.user}"
            )
        except discord.errors.Forbidden:
            return await interaction.response.send_message(
                "❌ I am missing permission to **Manage Roles**.",
                ephemeral=True
            )

    # Assign role
    try:
        await monika_member.add_roles(role, reason=f"Personality updated: {', '.join(chosen)}")
    except discord.errors.Forbidden:
        return await interaction.response.send_message(
            "❌ I am missing permission to **Manage Roles**.",
            ephemeral=True
        )

    await interaction.response.send_message(
        f"✅ Monika’s personality updated to: **{', '.join(chosen)}**",
        ephemeral=True
    )

@set_personality.error
async def set_personality_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("❌ You need Administrator to use this.", ephemeral=True)
    elif isinstance(error, app_commands.BotMissingPermissions):
        await interaction.response.send_message("❌ I need Manage Roles to do this.", ephemeral=True)
    else:
        await interaction.response.send_message(f"⚠️ Error: {error}", ephemeral=True)

# --- Relationship type autocomplete ---
async def relationship_type_autocomplete(
    interaction: discord.Interaction,
    current: str
):
    sexual_types = [
        "Polyamory", "Lesbian", "Pansexual", "Bisexual", "Straight",
        "Asexual", "Demisexual", "Queer", "Questioning",
        "Romantic", "Platonic", "Autosexual"
    ]

    normal_types = [
        "Friends", "Companions", "Best Friends", "Family", "Partners", "Soulmates",
        "Platonic Friends", "Close Friends", "Acquaintances", "Significant Others",
        "Colleagues", "Work Friends", "School Friends", "Childhood Friends",
        "Online Friends", "Gaming Buddies", "Study Partners", "Club Leader",
        "Boyfriend", "Girlfriend", "Girlfriend(Lesbian)", "Club Member", "Stranger", "Crush", "Default"
    ]

    # ✅ Merge with category labels
    all_types = (
        [(f"💖 Sexual: {t}", t) for t in sexual_types] +
        [(f"👥 Normal: {t}", t) for t in normal_types]
    )

    # ✅ Filter by user input
    filtered = [
        (label, value) for label, value in all_types
        if current.lower() in value.lower()
    ]

    return [
        app_commands.Choice(name=label, value=value)
        for label, value in filtered[:25]
    ]

@bot.tree.command(name="set_relationship", description="Set my relationship with users.")
@app_commands.autocomplete(type=relationship_type_autocomplete)
@app_commands.checks.has_permissions(administrator=True)
@app_commands.checks.bot_has_permissions(manage_roles=True)
@app_commands.describe(
    type="Type of relationship to set",
    with_users="User(s) to set relationship with"
)
async def set_relationship(
    interaction: discord.Interaction,
    type: str,
    with_users: typing.Optional[discord.Member] = None
):
    guild = interaction.guild
    guild_id = str(guild.id)
    user = interaction.user.display_name
    monika_member = guild.get_member(bot.user.id)
    bot_name = bot.user.name

    sexual_types = [
        "Polyamory", "Lesbian", "Pansexual", "Bisexual", "Straight",
        "Asexual", "Demisexual", "Queer", "Questioning",
        "Romantic", "Platonic", "Autosexual"
    ]

    normal_types = [
        "Friends", "Companions", "Best Friends", "Family", "Partners", "Soulmates",
        "Platonic Friends", "Close Friends", "Acquaintances", "Significant Others",
        "Colleagues", "Work Friends", "School Friends", "Childhood Friends",
        "Online Friends", "Gaming Buddies", "Study Partners", "Club Leader",
        "Boyfriend", "Girlfriend", "Girlfriend(Lesbian)", "Club Member",
        "Stranger", "Crush", "Default"
    ]

    # Restrictions based on Monika’s sexual type
    HIDDEN_IF_LESBIAN = {"Boyfriend", "Girlfriend"}
    HIDDEN_IF_STRAIGHT = {"Girlfriend (Lesbian)"}
    HIDDEN_IF_POLY = {"Significant Others"}

    # Normalize with_users → list
    if isinstance(with_users, discord.Member):
        target_members = [with_users]
    elif isinstance(with_users, list):
        target_members = [m for m in with_users if isinstance(m, discord.Member)]
    else:
        target_members = []

    target_names = [m.display_name for m in target_members]
    print(f"Administrator: {user} used `/set_relationship`: set `{type}` with `{target_names or 'nobody'}`")

    # --- Handle "Default" directly ---
    if type == "Default":
        server_tracker.set_server_relationship(guild_id, relationship_type="Default", with_list=[])
        await server_tracker.save(bot, channel_id=SERVER_TRACKER_CHAN)
        await interaction.response.send_message("✅ Relationship reset to **Default**.", ephemeral=True)
        return

    try:
        # --- Sexual types (Monika-only) ---
        if type in sexual_types:
            if target_members:
                return await interaction.response.send_message(
                    f"❌ Relationship type **{type}** cannot be set with users. It only applies to Monika.",
                    ephemeral=True
                )

            role_name = f"Sexual type - {type}"
            bot_role = discord.utils.get(guild.roles, name=role_name)
            if not bot_role:
                bot_role = await guild.create_role(
                    name=role_name,
                    color=discord.Color.dark_magenta()
                )
                print(f"[Roles] Created role: {role_name}")

            await monika_member.add_roles(bot_role, reason=f"Sexual identity: {type}")

            server_tracker.set_server_relationship(guild_id, relationship_type=type, with_list=[])
            await server_tracker.save(bot, channel_id=SERVER_TRACKER_CHAN)

            return await interaction.response.send_message(
                f"✅ Monika’s sexual type set to **{type}**.",
                ephemeral=True
            )

        # --- Normal types (require users) ---
        if type in normal_types:
            if not target_members:
                return await interaction.response.send_message(
                    f"❌ Relationship type **{type}** must be set with at least one user.",
                    ephemeral=True
                )

            # 🔹 Check if Monika already has a sexual type
            current_sexual_type = server_tracker.get_server_relationship(guild_id).get("relationship_type", "")
            if current_sexual_type == "Lesbian" and type in HIDDEN_IF_LESBIAN:
                return await interaction.response.send_message(
                    f"❌ Monika is **Lesbian** — relationship type **{type}** is not allowed.",
                    ephemeral=True
                )
            if current_sexual_type == "Straight" and type in HIDDEN_IF_STRAIGHT:
                return await interaction.response.send_message(
                    f"❌ Monika is **Straight** — relationship type **{type}** is not allowed.",
                    ephemeral=True
                )
            if current_sexual_type == "Polyamory" and type in HIDDEN_IF_POLY:
                return await interaction.response.send_message(
                    f"❌ Monika is **Polyamorous** — relationship type **{type}** is not allowed.",
                    ephemeral=True
                )

            # Reset old roles
            for role in guild.roles:
                if role.name.startswith(f"{bot_name} - ") or role.name.startswith(f"{interaction.user.display_name} - "):
                    try:
                        await role.delete(reason="Resetting old relationship roles")
                        print(f"[Roles] Deleted old role: {role.name}")
                    except discord.Forbidden:
                        print(f"[Roles] Missing permission to delete {role.name}")

            # Apply new roles
            for target_member in target_members:
                bot_role_name = f"{target_member.display_name} - {type}"
                user_role_name = f"{bot_name} - {type}"

                bot_role = discord.utils.get(guild.roles, name=bot_role_name) or \
                           await guild.create_role(name=bot_role_name, color=discord.Color.dark_green())
                user_role = discord.utils.get(guild.roles, name=user_role_name) or \
                            await guild.create_role(name=user_role_name, color=discord.Color.dark_green())

                await monika_member.add_roles(bot_role, reason=f"Relationship with {target_member.display_name}: {type}")
                await target_member.add_roles(user_role, reason=f"Relationship with Monika: {type}")

                user_tracker.set_manual_relationship(target_member.id, True)

            server_tracker.set_server_relationship(guild_id, relationship_type=type, with_list=target_names)
            await server_tracker.save(bot, channel_id=SERVER_TRACKER_CHAN)

            return await interaction.response.send_message(
                f"✅ Relationship set to **{type}** with: **{', '.join(target_names)}**.",
                ephemeral=True
            )

        # --- Unknown type ---
        await interaction.response.send_message(
            f"❌ Invalid relationship type `{type}`.",
            ephemeral=True
        )

    except commands.BotMissingPermissions as MP:
        await interaction.response.send_message(
            f"❌ Missing permissions: **{MP}**",
            ephemeral=True
        )
        print("[Relationship Error]", MP)

@bot.tree.command(
    name="personalities_description", 
    description="Shows all of Monika's personality mode(s)."
)
async def personalities_description(interaction: discord.Interaction):
    personality_modes = PERSONALITY_MODES  # assuming you keep it in monika_personality.py

    user = interaction.user.display_name
    print(f"{user} used a command: `personalities_description`")

    # Group into categories
    categories = {
        "🌸 Core": ["Default"],
        "💖 Positive / Supportive": [
            "Friendly", "Caring", "Supportive", "Compassion", "Affectionate", 
            "Comforting", "Wholesome", "Patient", "Loyal", "Generous", 
            "Polite", "Gentle", "Open-minded", "Mindful"
        ],
        "🔥 Passionate / Romantic": [
            "Romantic", "Flirtatious", "Possessive", "Obsessive", "Jealous",
            "Yandere", "Lustful", "Intensity", "Ambitious", "Brave"
        ],
        "😏 Playful / Social": [
            "Playful", "Cheery", "Childish", "Bubbly", "Comedic",
            "Memelord", "Gamer", "Adaptable", "Noisy", "Obnoxious",
            "Nosy", "Lazy", "Chaotic", "Leader", "Sassy"
        ],
        "🧠 Intellectual / Deep": [
            "Smart", "Philosophical", "Epiphany", "Artistic", "Creativity",
            "Poetic", "Introspective", "Realistic", "Eloquent", "Inquisitive",
            "Tactical", "Analytical", "Cynical"
        ],
        "🌑 Dark / Unsettling": [
            "Unsettling", "Uncanny", "Eerie", "Threatening", "Dark",
            "Arrogant", "Aggressive", "Cranky", "Brash", "Blunt",
            "Awkward", "Tongue-tied", "Shy", "Moody", "Paranoid",
            "Manipulative", "Menacing"
        ],
        "🌌 Immersive / Meta": [
            "Self-aware", "References lore", "Immersive", "Mysterious", 
            "Enigmatic", "Dreamy", "Detached", "All-knowing"
        ]
    }

    # Build embed
    embeds = []
    for category, traits in categories.items():
        embed = discord.Embed(
            title=f"🎭 Monika's Personality Modes — {category}",
            color=discord.Color.green()
        )
        for trait in traits:
            desc = personality_modes.get(trait, "No description available.")
            embed.add_field(name=trait, value=desc, inline=False)
        embeds.append(embed)

    # Start with first embed + paginator buttons
    view = SelectedPaginator(embeds, interaction.user)
    await interaction.response.send_message(embed=embeds[0], view=view, ephemeral=True)

@bot.tree.command(name="relationships_description", description="shows all Monika's relationship orientation for this server.")
async def relationships_description(interaction: discord.Interaction):
    relationship_modes = RELATIONSHIP_DETILED

    user = interaction.user.display_name
    print(f"{user} used a command: `relationships_description`")

    # Group into categories
    categories = {
        "🌸 Core": ["Default"],
        "💖 Sexual relationship": [
            "Polyamory", "Lesbian", "Pansexual", "Bisexual", "Straight", 
            "Asexual", "Demisexual", "Queer", "Questioning", "Romantic", "Platonic", "Autosexual"
        ],
        "🔥 Normal relationship": [
            "Friends", "Companions", "Best Friends", "Family", "Partners", "Soulmates", "Platonic Friends", "Close Friends", "Significant Others"
            "Acquaintances", "Colleagues", "Work Friends", "School Friends", "Childhood Friends", "Online Friends", "Gaming Buddies", "Study Partners", 
            "Club Leader", "Boyfriend", "Girlfriend", "Girlfriend(Lesbian)", "Club Member", "Stranger", "Crush"
        ]
    }

    # Build embed
    embeds = []
    for category, relationships in categories.items():
        embed = discord.Embed(
            title=f"💖 Monika's Relationships — {category}",
            color=discord.Color.green()
        )
        for relationship in relationships:
            desc = relationship_modes.get(relationship, "No description available.")
            embed.add_field(name=relationship, value=desc, inline=False)
        embeds.append(embed)

    # Start with first embed + paginator buttons
    view = SelectedPaginator(embeds, interaction.user)
    await interaction.response.send_message(embed=embeds[0], view=view, ephemeral=True)

@bot.tree.command(name="restart_monika", description="Restart Monika *only* in this server, clearing her memory and settings here.")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.checks.bot_has_permissions(manage_roles=True)
async def restart_monika(interaction: discord.Interaction):
    guild_id = str(interaction.guild.id)
    user = interaction.user.display_name
    print(f"{user} used a command: `/restart_monika` in {interaction.guild.name}")

    # ✅ Ask for confirmation
    view = ConfirmView()
    await interaction.response.send_message(
        f"⚠️ Are you sure you want to **restart Monika** in **{interaction.guild.name}**?\n"
        "This will reset memory, personality, and relationships in this server.",
        view=view,
        ephemeral=True
    )
    await view.wait()

    if view.value is None:
        return await interaction.followup.send("⌛ Timed out. Restart cancelled.", ephemeral=True)
    if view.value is False:
        return await interaction.followup.send("❌ Restart cancelled.", ephemeral=True)

    # ✅ Reset trackers
    server_tracker.clear_relationship(guild_id)
    server_tracker.set_personality(guild_id, [])
    memory.data(guild_id, [])

    # ✅ Remove all relationship/personality roles
    guild = interaction.guild
    for member in guild.members:
        for role in member.roles:
            if role.name in server_tracker.valid_relationship_types or role.name in PERSONALITY_MODES.keys():
                try:
                    await member.remove_roles(role)
                except discord.errors.Forbidden:
                    print(f"[Restart] Missing permission to remove {role.name} from {member.display_name}")

    # ✅ Cleanup Monika roles
    await cleanup_monika_roles(interaction.guild, bot.user.name)

    await interaction.followup.send("🔄 Monika has been restarted in this server. All settings reset.", ephemeral=True)

# ✅ Autocomplete handlers
# ✅ Bugs autocomplete
async def bugs_autocomplete(interaction: discord.Interaction, current: str):
    suggestions = [
        "Bot not responding",
        "Command not working",
        "Message duplication",
        "Sprite not loading",
        "Memory not saving",
        "Bot crashing",
        "Voice channel issues",
        "Permission check failing",
    ]
    return [
        app_commands.Choice(name=s, value=s)
        for s in suggestions if current.lower() in s.lower() or current == ""
    ][:5]

# ✅ Errors autocomplete (more user-friendly names)
async def errors_autocomplete(interaction: discord.Interaction, current: str):
    suggestions = [
        "Permission Denied",
        "Resource Not Found",
        "Rate Limited",
        "Internal Server Error",
        "Bad Gateway",
        "Gateway Timeout",
        "Unhandled Exception",
        "Missing Argument",
    ]
    return [
        app_commands.Choice(name=s, value=s)
        for s in suggestions if current.lower() in s.lower() or current == ""
    ][:5]

# ✅ Ideas autocomplete
async def ideas_autocomplete(interaction: discord.Interaction, current: str):
    suggestions = [
        "Add more outfits",
        "Add more emotions",
        "Persistent memory",
        "Relationship improvements",
        "Mini-games",
        "Voice replies",
        "Custom personality traits",
        "Integration with other bots",
        "Add More Easter Eggs",
    ]
    return [
        app_commands.Choice(name=s, value=s)
        for s in suggestions if current.lower() in s.lower() or current == ""
    ][:5]

# ✅ Complaints autocomplete
async def complaints_autocomplete(interaction: discord.Interaction, current: str):
    suggestions = [
        "Bot too slow",
        "Replies off-topic",
        "Takes too long to load",
        "Doesn't reply consistently",
        "Too many errors",
        "Unhelpful responses",
        "Reacts at wrong times",
        "Permissions too strict",
    ]
    return [
        app_commands.Choice(name=s, value=s)
        for s in suggestions if current.lower() in s.lower() or current == ""
    ][:5]

# ✅ Report command with autocomplete
@bot.tree.command(
    name="report",
    description="Report a Bug, Error, Idea, or Complaint about the bot."
)
@app_commands.describe(
    bugs="Select a bug you found (optional)",
    errors="Select an error you encountered (optional)",
    ideas="Suggest an idea (optional)",
    complaints="Submit a complaint (optional)",
    other="Write here if your report doesn’t fit the categories above"
)
@app_commands.autocomplete(
    bugs=bugs_autocomplete,
    errors=errors_autocomplete,
    ideas=ideas_autocomplete,
    complaints=complaints_autocomplete
)
async def report(
    interaction: discord.Interaction,
    bugs: str = "",
    errors: str = "",
    ideas: str = "",
    complaints: str = "",
    other: str = ""
):
    user = interaction.user

    filled = [field for field in [bugs, errors, ideas, complaints, other] if field]
    if len(filled) == 0:
        return await interaction.response.send_message("❌ Please provide at least one report.", ephemeral=True)
    if len(filled) > 1:
        return await interaction.response.send_message("❌ Please only fill one category.", ephemeral=True)

    await interaction.response.send_message("✅ Thank you for your report!", ephemeral=True)

    report_channel = bot.get_channel(REPORT_CHANNEL_ID)
    if not report_channel:
        return

    embed = discord.Embed(
        title="📢 New Report",
        color=discord.Color.green(),
        timestamp=discord.utils.utcnow()
    )
    embed.set_author(name=str(user), icon_url=user.display_avatar.url)
    embed.add_field(name="Reporter ID", value=user.id, inline=True)

    if bugs:
        embed.add_field(name="🐞 Bug", value=bugs, inline=False)
    elif errors:
        embed.add_field(name="⚠️ Error", value=errors, inline=False)
    elif ideas:
        embed.add_field(name="💡 Idea", value=ideas, inline=False)
    elif complaints:
        embed.add_field(name="❗ Complaint", value=complaints, inline=False)
    elif other:
        embed.add_field(name="📝 Other", value=other, inline=False)

    msg = await report_channel.send(embed=embed)
    report_links[msg.id] = user.id

    # 🔥 Dispatch event
    report_entry = {
        "user": user,
        "bugs": bugs,
        "errors": errors,
        "ideas": ideas,
        "complaints": complaints,
        "other": other,
        "time": discord.utils.utcnow()
    }
    bot.dispatch("report", report_entry)

async def safe_send_announcement(channel, **kwargs):
    """Send a message with retry + cooldown to avoid rate limits."""
    try:
        return await channel.send(**kwargs)
    except discord.HTTPException as e:
        print(f"[Broadcast Error] {e}, retrying in 3s...")
        await asyncio.sleep(3)
        return await channel.send(**kwargs)

async def safe_add_reaction(msg: discord.Message, emoji: str):
    """Safely add reaction whether Unicode or custom emoji."""
    try:
        # If it's a custom emoji (format <a:name:id> or <:name:id>)
        if emoji.startswith("<") and emoji.endswith(">"):
            # Discord.py automatically parses these into PartialEmoji
            await msg.add_reaction(discord.PartialEmoji.from_str(emoji))
        else:
            # Assume it's a Unicode emoji
            await msg.add_reaction(emoji)
    except discord.HTTPException:
        print(f"[Broadcast] ⚠️ Failed to add reaction {emoji} in {msg.guild.name}")

async def has_announcement(channel, title: str, message: str, limit: int = 100) -> bool:
    """Check recent channel history for an identical announcement embed."""
    try:
        async for msg in channel.history(limit=limit):
            if not msg.embeds:
                continue
            embed = msg.embeds[0]
            if embed.title == title and embed.description == message:
                return True
        return False
    except Exception as e:
        print(f"[Broadcast Scan Error] {e}")
        return False

async def reaction_set_autocomplete(
    interaction: discord.Interaction,
    current: str
):
    options = ["default", "poll", "custom", "maintenance"]
    return [
        app_commands.Choice(name=opt, value=opt)
        for opt in options if current.lower() in opt.lower()
    ]

async def custom_reactions_autocomplete(interaction: discord.Interaction, current: str):
    choices = []

    # Unicode emoji suggestions
    unicode_emojis = ["✅", "❌", "👍", "👎", "🤔", "🎉", "🔥", "💚", "🛠️", "🚧", "⚙️"]
    for e in unicode_emojis:
        if current in e:
            choices.append(app_commands.Choice(name=e, value=e))

    # Custom emoji suggestions (shows image if only emoji string is used)
    for guild in bot.guilds:
        for emoji in guild.emojis:
            if current.lower() in emoji.name.lower():
                # 👇 Only str(emoji), no extra text
                choices.append(app_commands.Choice(name=str(emoji), value=str(emoji)))

    return choices[:25]

async def send_announcement(
    guild,
    gid,
    channel,
    embed,
    reactions,
    announcement_id,
    sent_messages,
    progress_counter,
    total_servers,
):
    """Safely send announcement embed and track progress without crashing."""
    global success_count, failure_count

    try:
        # Attempt to send message safely
        msg = await safe_send_announcement(channel, embed=embed)
        if not msg:
            raise RuntimeError("Message failed to send")

        # Add reactions (ignore failures for missing perms or rate limits)
        for r in reactions:
            try:
                await safe_add_reaction(msg, r)
            except discord.Forbidden:
                print(f"[Broadcast Warning] Missing reaction permission in {guild.name}")
            except discord.HTTPException as e:
                print(f"[Broadcast Reaction Error] {e}")

        # Post a small "progress" message
        try:
            progress = await safe_send_announcement(channel, content="⏳ Collecting reactions...")
            sent_messages.append((msg, progress))
        except discord.Forbidden:
            progress = None

        # Record the announcement safely
        server_tracker.guilds[gid].setdefault("announcements", [])
        if announcement_id not in server_tracker.guilds[gid]["announcements"]:
            server_tracker.guilds[gid]["announcements"].append(announcement_id)
        server_tracker.guilds[gid]["last_broadcast_time"] = datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat()

        await server_tracker.save(bot, channel_id=SERVER_TRACKER_CHAN)

        success_count += 1
        progress_counter[0] += 1
        print(f"[Broadcast] ✅ Sent to {guild.name} in #{channel.name}")
        print(f"[Broadcast] Progress: {progress_counter[0]} / {total_servers}")

    except discord.Forbidden:
        print(f"[Broadcast Error] Missing permission in {guild.name}")
        failure_count += 1
    except discord.HTTPException as e:
        print(f"[Broadcast HTTP Error] {e}")
        failure_count += 1
    except Exception as e:
        print(f"[Broadcast Unexpected Error] in {guild.name}: {e}")
        failure_count += 1
    finally:
        progress_counter[0] += 1
        print(f"[Broadcast] Progress: {progress_counter[0]} / {total_servers} servers (completed step)")

@bot.tree.command(
    name="broadcast", 
    description="Send an announcement to all servers/channels for me to speak in."
)
@commands.is_owner()
@discord.app_commands.describe(title="Title of the announcement", message="Body text of the announcement", color_hex="Optional hex color (e.g. 15f500)")
@app_commands.autocomplete(reaction_set=reaction_set_autocomplete, custom_reactions=custom_reactions_autocomplete)
async def broadcast(
    interaction: discord.Interaction,
    title: str,
    message: str,
    color_hex: str = "15f500",
    reaction_set: str = "default",  # default, poll, maintenance, or custom
    custom_reactions: str = None    # comma-separated emojis
):
    await interaction.response.defer(ephemeral=True)

    global is_broadcasting, success_count, failure_count, skip_count
    user = interaction.user

    if user.id != OWNER_ID:
        await interaction.response.send_message("❌ You can't use this command.", ephemeral=True)
        return

    if is_broadcasting:
        await interaction.response.send_message("❌ A broadcast is already in progress.", ephemeral=True)
        return

    wait_minutes = 3
    is_broadcasting = True
    await bot.change_presence(activity=discord.Game("📣 Announcement in progress..."))

    try:
        # --- Reaction sets ---
        available_sets = {
            "default": ["✅", "❌"],
            "poll": ["👍", "👎", "🤔"],
            "maintenance": ["🛠️", "🚧", "⚙️"]
        }

        if reaction_set == "custom" and custom_reactions:
            reactions = [r.strip() for r in custom_reactions.split(",") if r.strip()]
        else:
            reactions = available_sets.get(reaction_set, available_sets["default"])

        print(f"[Broadcast] Using reaction set ({reaction_set}): {' '.join(reactions)}")

        # --- Embed setup ---
        try:
            color_int = int(color_hex, 16)
            color = discord.Color(color_int)
        except ValueError:
            color = discord.Color.pink()

        embed = discord.Embed(title=title, description=message, color=color)

        # 🔹 Detect and display first image link
        image_urls = re.findall(r'(https?://\S+\.(?:png|jpg|jpeg|gif))', message)
        if image_urls:
            embed.set_image(url=image_urls[0])
            clean_desc = re.sub(r'https?://\S+\.(?:png|jpg|jpeg|gif)', '', message).strip()
            if clean_desc:
                embed.description = clean_desc

        embed.set_footer(
            text="Pick your reaction to vote. Use /report for any bugs, errors, ideas, or complaints for feedback. "
                 "Please wait until I finish sharing the announcement so we can speak again."
        )

        success_count = failure_count = skip_count = 0
        sent_messages = []
        announcement_id = f"{title}:{message}"

        # --- Step 1: Locate servers ---
        servers_to_announce = []
        for guild in bot.guilds:
            gid = str(guild.id)
            server_tracker.ensure_guild(gid)

            last_time = server_tracker.guilds[gid].get("last_broadcast_time")
            if last_time:
                last_dt = datetime.datetime.fromisoformat(last_time)
                if (datetime.datetime.now(datetime.timezone.utc) - last_dt).total_seconds() < 86400:
                    print(f"[Broadcast] ⏭ Skipping {guild.name}, already announced recently")
                    skip_count += 1
                    continue

            if announcement_id in server_tracker.guilds[gid].get("announcements", []):
                skip_count += 1
                continue

            channel = None
            for c in guild.text_channels:
                if c.permissions_for(guild.me).send_messages:
                    if c.name not in OFF_LIMITS_CHANNELS:
                        channel = c
                        break
            if not channel:
                print(f"[Broadcast] ❌ No available channel in {guild.name}")
                failure_count += 1
                continue

            servers_to_announce.append((guild, gid, channel))

        if not servers_to_announce:
            await interaction.followup.send(
                f"⚠️ No servers need this announcement.\n"
                f"⏭ Skipped: **{skip_count}**, ❌ Failed: **{failure_count}**",
                ephemeral=True
            )
            return

        # --- Step 2: Send warnings ---
        confirmed_servers = []
        for guild, gid, channel in servers_to_announce:
            try:
                await safe_send_announcement(channel, content="⚠️ **Attention everyone!** A broadcast will begin shortly...")
                confirmed_servers.append((guild, gid, channel))
            except Exception as e:
                print(f"[Broadcast Warning Error] in {guild.name}: {e}")
                failure_count += 1

        await asyncio.sleep(8)

        # --- Step 3: Dispatch actual broadcast ---
        progress_counter = [0]
        total_servers = len(confirmed_servers)

        for i in range(0, total_servers, 5):
            batch = confirmed_servers[i:i + 5]
            await asyncio.gather(*[
                send_announcement(guild, gid, channel, embed, reactions, announcement_id,
                                  sent_messages, progress_counter, total_servers)
                for guild, gid, channel in batch
            ])
            await asyncio.sleep(1.5)

        # --- Step 4: Continuous live updates ---
        print("[Broadcast] 🔄 Starting continuous reaction updates.")
        update_interval = 2  # how often to refresh (seconds)

        try:
            while True:
                like_total, dislike_total, maybe_total = 0, 0, 0
                custom_totals = {}

                for orig, progress in sent_messages:
                    try:
                        refreshed = await orig.channel.fetch_message(orig.id)
                        counts = {}
                        for reaction in refreshed.reactions:
                            emoji = str(reaction.emoji)
                            users = [u async for u in reaction.users() if u.id != bot.user.id]
                            counts[emoji] = len(users)

                        result_line = " | ".join([f"{emoji} {count}" for emoji, count in counts.items()])
                        await progress.edit(content=f"{result_line} (live)")

                        if reaction_set == "default":
                            like_total += counts.get("✅", 0)
                            dislike_total += counts.get("❌", 0)
                        elif reaction_set == "poll":
                            like_total += counts.get("👍", 0)
                            dislike_total += counts.get("👎", 0)
                            maybe_total += counts.get("🤔", 0)
                        elif reaction_set == "custom":
                            for emoji in reactions:
                                custom_totals[emoji] = custom_totals.get(emoji, 0) + counts.get(emoji, 0)

                    except discord.errors.NotFound:
                        print("[Broadcast Fetch Error] Message deleted.")
                    except Exception as e:
                        print(f"[Broadcast Fetch Error] {e}")

                summary = (
                    f"✅ Likes: {like_total} | ❌ Dislikes: {dislike_total}"
                    if reaction_set == "default"
                    else f"👍 {like_total} | 👎 {dislike_total} | 🤔 {maybe_total}"
                    if reaction_set == "poll"
                    else " | ".join([f"{emoji}: {count}" for emoji, count in custom_totals.items()])
                )
                print(f"[Broadcast Live Totals] {summary}")

                await asyncio.sleep(update_interval)
        except asyncio.CancelledError:
            print("[Broadcast] Live update loop stopped manually.")

        # --- Step 6: Owner summary ---
        if reaction_set == "maintenance":
            summary_lines = ["🛠️ Maintenance mode: Reactions were not tracked."]
        elif reaction_set == "default":
            summary_lines = [f"✅ Likes: {like_total}", f"❌ Dislikes: {dislike_total}"]
        elif reaction_set == "poll":
            summary_lines = [f"👍 Likes: {like_total}", f"👎 Dislikes: {dislike_total}", f"🤔 Maybe: {maybe_total}"]
        else:
            summary_lines = [f"{emoji}: {total}" for emoji, total in custom_totals.items()]

        await interaction.followup.send(
            f"✅ Broadcast finished.\n"
            f"Sent to **{success_count}** servers.\n"
            f"⚠️ Failed: **{failure_count}**, Skipped: **{skip_count}**.\n\n"
            + "\n".join(summary_lines),
            ephemeral=True
        )

    finally:
        is_broadcasting = False
        await bot.change_presence(activity=None)

@broadcast.error
async def broadcast_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.errors.CheckFailure):
        await interaction.response.send_message("❌ You are not the bot owner.", ephemeral=True)

    elif isinstance(error, app_commands.errors):
        await interaction.response.send_message("something went wrong", ephemeral=True)

async def emotion_autocomplete(interaction: discord.Interaction, current: str):
    outfit = getattr(interaction.namespace, "outfit", None)
    emotions = []

    if outfit and outfit.lower() in user_sprites.sprites_by_outfit:
        # use the keys from our fixed dict
        emotions = list(user_sprites.get_emotions_for_outfit(outfit))
    else:
        # fallback: collect all emotions from all outfits
        all_emotions = set()
        for emo_dict in user_sprites.sprites_by_outfit.values():
            all_emotions.update(emo_dict.keys())
        emotions = list(all_emotions)

    return [
        app_commands.Choice(name=e, value=e)
        for e in emotions if current.lower() in e.lower()
    ][:25]

@bot.tree.command(
    name="speak_as_monika",
    description="Make Monika speak in specific channels."
)
@app_commands.describe(
    channel_id="The numeric ID of the channel",
    message="What should I said?",
    outfit="Choose the outfit for the sprite",
    emotion="Emotion should I express"
)
@app_commands.autocomplete(outfit=outfit_autocomplete, emotion=emotion_autocomplete)
@app_commands.checks.has_permissions(administrator=True)
async def speak_as_monika(
    interaction: discord.Interaction,
    channel_id: str,
    message: str,
    outfit: str,
    emotion: str
):
    await interaction.response.defer(ephemeral=True)

    user = interaction.user
    print(f"[DEBUG] User {user} used `/speak_as_monika`")

    # ✅ Permissions check: allow bot owner anywhere
    if user.id != OWNER_ID:
        if not interaction.guild or not user.guild_permissions.administrator:
            return await interaction.followup.send(
                "❌ Only this server’s administrators or the bot owner can use this command.",
                ephemeral=True
            )
        # Ensure channel is inside this guild and visible
        channel = bot.get_channel(int(channel_id))
        if not channel or channel.guild.id != interaction.guild.id:
            return await interaction.followup.send(
                "❌ You can only make Monika speak inside **your own server’s channels**.",
                ephemeral=True
            )
        if not channel.permissions_for(user).view_channel:
            return await interaction.followup.send(
                f"❌ You don’t have access to {channel.mention}.",
                ephemeral=True
            )

    # ✅ Normalize + validate outfit
    outfit = outfit.lower().strip()
    if outfit == "casual":
        outfit = "casual 1"

    valid_outfits = [o.lower() for o in get_all_outfit()]
    if outfit not in valid_outfits or outfit not in user_sprites.sprites_by_outfit:
        return await interaction.followup.send(
            f"❌ Invalid outfit. Options: {', '.join(get_all_outfit())}.",
            ephemeral=True
        )

    # ✅ Validate emotion
    valid_emotions = [e.strip() for e in user_sprites.get_emotions_for_outfit(outfit)]
    if emotion.strip() not in valid_emotions:
        return await interaction.followup.send(
            f"❌ No valid emotions for outfit `{outfit}`.", ephemeral=True
        )

    if emotion.lower().strip() not in valid_emotions:
        return await interaction.followup.send(
            f"❌ Emotion `{emotion}` is not valid for outfit `{outfit}`.\n"
            f"✔️ Options: {', '.join(valid_emotions)}",
            ephemeral=True
        )

    if not message.strip():
        return await interaction.followup.send(
            "❌ You must provide a message for Monika to send.",
            ephemeral=True
        )

    # ✅ Resolve channel
    try:
        channel = bot.get_channel(int(channel_id))
        if not channel or not isinstance(channel, discord.TextChannel):
            return await interaction.followup.send(
                f"❌ Channel `{channel_id}` not found.",
                ephemeral=True
            )
        if not channel.permissions_for(channel.guild.me).send_messages:
            return await interaction.followup.send(
                f"❌ I don’t have permission to send messages in {channel.mention}.",
                ephemeral=True
            )
    except Exception as e:
        print(f"[Channel Error] {e}")
        return await interaction.followup.send(
            f"❌ Error finding channel: {e}", ephemeral=True
        )

    # ✅ Get sprite link
    sprite_link = await get_sprite_link(emotion.lower().strip(), outfit)
    if not sprite_link:
        return await interaction.followup.send("❌ Could not get sprite.", ephemeral=True)

    # ✅ Send the message
    mon_reply = f"{message}\n[{emotion}]({sprite_link})"
    print(f"[DEBUG] Monika reply → {mon_reply}")

    try:
        async with channel.typing():
            await asyncio.sleep(1)
            await channel.send(mon_reply)
        await interaction.followup.send(
            f"✅ Monika spoke in **{channel.guild.name}** #{channel.name}.",
            ephemeral=True
        )
    except Exception as e:
        await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)

@bot.tree.command(
    name="nickname",
    description="give me a nickname."
)
@app_commands.describe(name="The nickname you want to give me.")
@app_commands.checks.has_permissions(administrator=True)
async def nickname(interaction: discord.Interaction, name: str = None):
    guild = interaction.guild
    user = interaction.user
    print(f"[administrator] User: {user} used `/nickname` and gave me {name}")

    if name and name.lower() == "reset":
        view = ConfirmView()
        await interaction.response.send_message(
            f"Are you sure you want to reset my nickname back to **{bot.user.name}**?\n",
            view=view,
            ephemeral=True
        )
        await view.wait()
    else:
        view = ConfirmView()
        await interaction.response.send_message(
            f"Are you sure you want to give me the nickname: **{name}**?\n",
            view=view,
            ephemeral=True
        )
        await view.wait()

    # --- RESET nickname ---
    if name and name.lower() == "reset":
        if guild:
            server_tracker.set_nickname(str(guild.id), None)
            try:
                monika_member = guild.get_member(bot.user.id)
                if monika_member:
                    await monika_member.edit(nick=None)
            except discord.Forbidden:
                pass
            await interaction.followup.send("✅ My nickname has been reset to default in this server.")
        else:
            user_tracker.set_nickname(str(user.id), None)
            await interaction.followup.send("✅ I’ll use my default name for you in DMs.")
        return

    # --- SHOW nickname ---
    if not name:
        if guild:
            current = server_tracker.get_nickname(str(guild.id)) or bot.user.name
            await interaction.followup.send(f"My nickname in **{guild.name}** is currently **{current}**.")
        else:
            current = user_tracker.get_nickname(str(user.id)) or bot.user.name
            await interaction.followup.send(f"My nickname for you is currently **{current}**.")
        return

    # --- SET nickname ---
    if guild:
        try:
            monika_member = guild.get_member(bot.user.id)
            if monika_member:
                await monika_member.edit(nick=name)
            server_tracker.set_nickname(str(guild.id), name)
            await interaction.followup.send(f"My nickname in **{guild.name}** is now **{name}** 💚")
        except discord.Forbidden:
            await interaction.response.send_message("⚠️ I don’t have permission to change my nickname here.", ephemeral=True)
    else:
        user_tracker.set_nickname(str(user.id), name)
        await interaction.response.send_message(f"I’ll use the nickname **{name}** just for you 💚")

@bot.tree.command(name="settings", description="Open my settings panel.")
@app_commands.checks.has_permissions(administrator=True)
async def settings(interaction: discord.Interaction):
    guild = interaction.guild
    current_nickname = server_tracker.get_nickname(str(guild.id)) if guild else user_tracker.get_nickname(str(interaction.user.id))
    current_nickname = current_nickname or bot.user.name

    embed = discord.Embed(
        title="⚙️ Monika Settings Panel",
        description="Here are the available settings you can configure:",
        color=discord.Color.green()
    )
    embed.add_field(name="🗣 Normal Talk", value="Enable/disable casual conversations.", inline=False)
    embed.add_field(name="⏱ Idlechat Timer", value="Set how often I speak when idle.", inline=False)
    embed.add_field(name="🧹 Reset Memory", value="Clear all my saved memories.", inline=False)
    embed.add_field(name="🎭 Reset Personality", value="Reset my personality roles.", inline=False)
    embed.add_field(name="💞 Reset Relationship", value="Reset relationship roles.", inline=False)
    embed.add_field(name="📤 Export Memories", value="Export memory logs.", inline=False)
    embed.add_field(name="📥 Import Memories", value="Import memory logs.", inline=False)
    embed.add_field(name="🔄 Restart Monika", value="Restart me safely.", inline=False)
    embed.add_field(name="✏️ Nickname", value=f"My current nickname is **{current_nickname}**.", inline=False)
    embed.add_field(name="🌍 Language", value="Select your preferred language below.", inline=False)
    embed.add_field(name="💾 Save Personality", value="Save your Personalities.", inline=False)
    embed.add_field(name="📂 Load Personality", value="Load the Personalities You have saved.", inline=False)

    await interaction.response.send_message(
        embed=embed,
        view=SettingView(),
        ephemeral=True
    )

def get_monika_name(context) -> str:
    """Return Monika's nickname depending on guild or DM context."""
    # Guild context
    if isinstance(context, discord.Guild):
        return server_tracker.get_nickname(str(context.id)) or bot.user.name

    # DM / User context
    if isinstance(context, discord.User) or isinstance(context, discord.Member):
        return user_tracker.get_nickname(str(context.id)) or bot.user.name

    # Default fallback
    return bot.user.name

@bot.tree.command(name="vote_menu", description="Open voting menu panel to vote for a feature, sprite, command, etc. base on your choice")
async def vote_menu(interaction: discord.Interaction):
    """Show the current vote menu with full persistence and menu ID support."""
    # --- Auto-load the latest vote data from storage (persistent)
    await vote_tracker.load(bot, SETTINGS_CHAN)

    global_vote = vote_tracker.votes.get("global")
    if not global_vote:
        await interaction.response.send_message(
            "❌ No one has created a vote yet. Use `!create_vote` first.",
            ephemeral=True
        )
        return

    # --- Use stored menu ID for identification
    menu_id = global_vote.get("menu_id", "N/A")

    guild_id = str(interaction.guild.id if interaction.guild else interaction.user.id)
    guild_votes = global_vote.setdefault("guild_votes", {}).setdefault(guild_id, {})

    title = global_vote.get("title", "🗳️ Vote Menu")
    options = global_vote.get("options", [])

    # --- Count votes (per guild)
    counts = [0] * len(options)
    for user_id, choice in guild_votes.items():
        if 0 <= choice < len(options):
            counts[choice] += 1
    total_votes = sum(counts) or 1

    # --- Build multiple embeds (1 per option)
    embeds = []
    for i, opt in enumerate(options):
        val = opt["value"]
        pct = round(counts[i] / total_votes * 100, 1)
        embed = discord.Embed(
            title=f"🗳️ {title} — Option {i+1}",
            description=f"Votes: **{counts[i]}** ({pct}%)",
            color=discord.Color.blurple()
        )

        if opt["type"] == "image":
            embed.set_image(url=val)
        elif opt["type"] == "emoji":
            embed.description += f"\nOption: {val}"
        else:
            embed.description += f"\nOption: **{val}**"

        embed.set_footer(text=f"Menu ID: {menu_id} • Click a button to cast your vote!")
        embeds.append(embed)

    # --- Interactive buttons
    view = discord.ui.View(timeout=None)

    for i in range(len(options)):
        button = discord.ui.Button(label=f"{i+1}", style=discord.ButtonStyle.green)

        async def callback(interaction_inner: discord.Interaction, index=i):
            user_id = str(interaction_inner.user.id)
            guild_id_inner = str(interaction_inner.guild.id if interaction_inner.guild else interaction_inner.user.id)

            # ✅ Record vote
            global_vote["guild_votes"].setdefault(guild_id_inner, {})[user_id] = index
            await vote_tracker.save(bot, SETTINGS_CHAN)  # ✅ Save after every vote

            # ✅ Recalculate votes for this guild
            guild_votes = global_vote["guild_votes"][guild_id_inner]
            counts = [0] * len(options)
            for _, choice in guild_votes.items():
                if 0 <= choice < len(options):
                    counts[choice] += 1
            total_votes = sum(counts) or 1

            # ✅ Build updated embeds
            updated_embeds = []
            for j, opt in enumerate(options):
                val = opt["value"]
                pct = round(counts[j] / total_votes * 100, 1)
                new_embed = discord.Embed(
                    title=f"🗳️ {title} — Option {j+1}",
                    description=f"Votes: **{counts[j]}** ({pct}%)",
                    color=discord.Color.blurple()
                )
                if opt["type"] == "image":
                    new_embed.set_image(url=val)
                elif opt["type"] == "emoji":
                    new_embed.description += f"\nOption: {val}"
                else:
                    new_embed.description += f"\nOption: **{val}**"

                new_embed.set_footer(
                    text=f"Your vote: Option {index+1} • Menu ID: {menu_id}"
                )
                updated_embeds.append(new_embed)

            # ✅ Update the message safely
            try:
                await interaction_inner.response.edit_message(embeds=updated_embeds, view=view)
            except discord.errors.InteractionResponded:
                await interaction_inner.followup.edit_message(
                    message_id=interaction_inner.message.id,
                    embeds=updated_embeds,
                    view=view
                )

        button.callback = lambda inter, index=i: asyncio.create_task(callback(inter, index))
        view.add_item(button)

    # --- Display all embeds
    await interaction.response.send_message(embeds=embeds, view=view)

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    """Global error handler for app commands."""

    try:
        if isinstance(error, app_commands.MissingPermissions):
            msg = f"❌ You don’t have the required permissions: `{', '.join(error.missing_permissions)}`"
        elif isinstance(error, app_commands.BotMissingPermissions):
            msg = f"❌ I’m missing permissions: `{', '.join(error.missing_permissions)}`"
        elif isinstance(error, app_commands.CommandOnCooldown):
            msg = f"⏳ This command is on cooldown. Try again in {error.retry_after:.1f} seconds."
        elif isinstance(error, app_commands.TransformerError):
            msg = "❌ Invalid input provided. Please check your command and try again."
        elif isinstance(error, app_commands.CommandInvokeError):
            # Unwrap the original exception
            original = error.original
            print(f"[AppCmdError] CommandInvokeError: {type(original).__name__}: {original}")
            traceback.print_exception(type(original), original, original.__traceback__)
            msg = f"⚠️ An unexpected error occurred: **{type(original).__name__}**"
        else:
            # Generic fallback
            print(f"[AppCmdError] {type(error).__name__}: {error}")
            msg = "⚠️ Something went wrong while running this command."

        # Try sending the error message safely
        if not interaction.response.is_done():
            await interaction.response.send_message(msg, ephemeral=True)
        else:
            await interaction.followup.send(msg, ephemeral=True)

    except Exception as handler_err:
        # Failsafe if even error handler blows up
        print(f"[TreeErrorHandler] Failed to handle error: {handler_err}")

async def main():
    """Main bot runner with reconnect support."""
    while True:
        try:
            await bot.start(TOKEN, reconnect=True)
        except BaseException:
            print("⚠️ Bot crashed, restarting in 10s")
            traceback.print_exc()
            await asyncio.sleep(10)  # wait before restarting

if __name__ == "__main__":
    while True:
        try:
            keepalive.keep_alive()  # start keepalive Flask
            while True:
                try:
                    asyncio.run(main())
                except BaseException as e:
                    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    print(f"[{now}] ⚠️ Fatal asyncio error, restarting in 10s: {e}")
                    traceback.print_exc()
                    time.sleep(10)
        except BaseException as e:
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"[{now}] 💀 Top-level crash ignored: {e}")
            traceback.print_exc()
            time.sleep(10)
