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

import discord
from discord import File, app_commands
from discord.ext import commands
from discord.permissions import Permissions

# Local modules
import error_detector
import keepalive
from OpenAIKeys import (
    OpenAIKeyManager,
    openai_safe_call,
    init_key_manager,
    periodic_rescan,
    key_manager,
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

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("Monika")
logger.info("Just Monika!")

async def call_openai_with_retries(user, relationship, personality, conversation):
    """Try models in priority order using safe_call.
       If one key/model fails, ignore and move on to the next.
       Returns a valid response or None if all fail.
    """
    model_priority = ["gpt-5-mini", "gpt-5", "gpt-5-nano", "gpt-3.5-turbo"]

    for model in model_priority:

        async def call_fn(client):
            if not isinstance(conversation, list):
                raise ValueError("Conversation must be a list of messages.")

            # Build system prompt
            system_prompt = await generate_monika_system_prompt(
                guild=user.guild if hasattr(user, "guild") else None,
                user=user,
                relationship_type=relationship,
                selected_modes=personality,
            )

            full_conversation = [{"role": "system", "content": system_prompt}] + conversation

            # Call API
            return await client.chat.completions.create(
                model=model,
                messages=full_conversation
            )

        try:
            response = await openai_safe_call(key_manager, call_fn)

            if response is None:
                print(f"[OpenAI] ❌ {model} failed (ignored). Trying next model...")
                continue

            # Check response validity
            if (response and response.choices and
                response.choices[0].message and
                response.choices[0].message.content.strip()):
                print(f"[OpenAI] ✅ {model} → Success")
                key_manager.mark_success()  # improve key health
                return response
            else:
                print(f"[OpenAI] ⚠️ {model} returned empty/invalid response. Trying next...")
                key_manager.mark_cooldown()
                continue

        except Exception as e:
            print(f"[OpenAI] ⚠️ {model} error ignored: {e}")
            key_manager.mark_cooldown()
            continue

    # If all models failed
    print("[OpenAI] ❌ All models failed, returning None.")
    return None
# ==============================
# Discord Setup
# ==============================
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="/", intents=intents)

# ==============================
# Environment Variables
# ==============================
TOKEN = os.getenv("DISCORD_TOKEN")
IMAGE_CHAN_URL = int(os.getenv("IMAGE_CHAN_URL", 0))
MEMORY_CHAN_ID = int(os.getenv("MEMORY_CHANNEL_ID", 0))
REPORT_CHANNEL_ID = int(os.getenv("REPORT_CHANNEL_ID", 0))
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

FRIENDS = [SAYORI, NATSUKI, YURI, MC]

ALLOWED_GUILD_IDS = [DOKIGUY_GUILD_ID, ALIRI_GUILD_ID, ZERO_GUILD_ID, MAS_GUILD_ID, MY_GUILD_ID]

MON_CHANNEL_NAMES = [
    "monika", "monika-ai", "ddlc-monika", "ddlc-monika-ai", "club-room", "doki-chat", "ddlc-chat", "monika-bot", "chat-monika", "monika-chat", "monika-but-deranged", "just-monika", "club-room-meeting", "literature-club", "literature-club-room", "monika-ddlc"
]

OFF_LIMITS_CHANNELS = [
    "get-roles", "rules", "announcements", "osu", "food", "pets", "teasers", "owo", "tubberbox"
]

NO_CHAT_CHANNELS = [
    cid for cid in [MEMORY_CHAN_ID, IMAGE_CHAN_URL, REPORT_CHANNEL_ID, DM_LOGS_CHAN, SERVER_TRACKER_CHAN, USER_TRACKER_CHAN, AVATAR_URL_CHAN]
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
    now = datetime.datetime.utcnow()
    hour = now.hour
    today = now.date()
    weekday = now.weekday()  # Monday=0, Sunday=6

    # Weekend override
    if weekday in (5, 6):
        random.seed(str(now.date()))
        return random.choice(["casual 1", "casual 2", "casual 3"])

    # Morning/School
    if 6 <= hour < 15:
        return "school uniform"

    # Evening casual
    if 15 <= hour < 20:
        random.seed(str(today))
        return random.choice(["casual 1", "casual 2", "casual 3"])

    # Night
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
    Build Monika's system prompt with personality, relationship, pronouns, memory & language.
    """
    base_description = get_base_prompt(is_friend_context)

    # Personality
    traits = selected_modes or ["Default"]
    personality_desc = f"Active personality traits: {', '.join(traits)}."

    # Relationship
    relationship_desc = "She acts casually with no special attachment."
    try:
        if relationship_type and relationship_type in monika_traits.relationship_modes:
            relationship_desc = monika_traits.relationship_modes[relationship_type]
    except Exception:
        pass
    dynamic_relationship = f"Her relationship with the user is **{relationship_type or 'Stranger'}**: {relationship_desc}"

    # Pronouns
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

    # Memory awareness
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

    # Language awareness
    language_desc = await monika_languages_system_prompt(user=user, message=message)

    return "\n\n".join(filter(None, [
        base_description,
        personality_desc,
        dynamic_relationship,
        pronoun_desc,
        memory_desc,
        language_desc
    ]))

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

@bot.event
async def on_connect():
    await bot.change_presence(status=discord.Status.online, activity=discord.Game("Rebooting..."))
    await on_ready()

@bot.event
async def on_ready():
    global idlechat_task, is_waking_up, key_manager

    is_waking_up = True

    print("---------------------------------------------------")
    key_manager = await init_key_manager()

    # Attach Monika’s hooks
    key_manager.on_all_keys_exhausted = lambda: on_sleeping("All OpenAI keys exhausted")
    key_manager.on_key_recovered = lambda key: on_wake_up(f"Key {key[:8]} recovered")
    print("---------------------------------------------------")
    print(f"just {bot.user.name}")
    print("---------------------------------------------------")
    update_heartbeat()  # refresh on connect
    await error_detector.send_scan_results(bot)

    app_info = await bot.application_info()
    bot_owner = app_info.owner  # the bot’s registered owner (you)

    for guild in bot.guilds:
        monika_member = guild.get_member(bot.user.id)

        # 🔹 Detect "Creator of Monika" role (if it exists)
        creator_role_name = f"Creator of {bot.user.name}"
        creator_role = discord.utils.get(guild.roles, name=creator_role_name)
        if creator_role:
            owner_member = guild.get_member(bot_owner.id or OWNER_ID)
            if owner_member and creator_role in owner_member.roles:
                print(f"[Startup] {owner_member.display_name} is the Creator of {bot.user.name} in {guild.name}")
            else:
                print(f"[Startup] Creator role exists in {guild.name} but the owner does not have it.")
        else:
            print(f"[Startup] No '{creator_role_name}' role found in {guild.name}")

        # 🔹 Restore saved Personality Role (only detect, don’t create new)
        saved_personality = server_tracker.get_personality(guild.id)
        if saved_personality:
            role = discord.utils.get(guild.roles, name=f"Personality - {saved_personality}")
            if role and monika_member and role not in monika_member.roles:
                try:
                    await monika_member.add_roles(role)
                except discord.Forbidden:
                    print(f"[Startup Error] Missing permission to add {role.name} in {guild.name}")

        # 🔹 Restore Relationship Role (only detect, don’t create new)
        saved_relationship = server_tracker.get_relationship_type(guild.id)
        saved_relationship_user = server_tracker.get_relationship_with(guild.id)
        if saved_relationship and saved_relationship_user:
            try:
                user_member = guild.get_member(int(saved_relationship_user))
                rel_role_name_user = f"{bot.user.name} - {saved_relationship}"
                rel_role_name_monika = f"{user_member.display_name} - {saved_relationship}" if user_member else None

                # User role
                user_role = discord.utils.get(guild.roles, name=rel_role_name_user)
                if user_member and user_role and user_role not in user_member.roles:
                    await user_member.add_roles(user_role)

                # Bot role
                if rel_role_name_monika:
                    bot_role = discord.utils.get(guild.roles, name=rel_role_name_monika)
                    if monika_member and bot_role and bot_role not in monika_member.roles:
                        await monika_member.add_roles(bot_role)
            except Exception as e:
                print(f"[Startup Role Restore Error] {e}")

        # 🔹 Track users + detect relationships
        for member in guild.members:
            if member.bot:
                continue

            user_tracker.track_user(member.id, member.display_name, member.bot)

            rel_roles = [r for r in member.roles if r.name.startswith(f"{bot.user.name} - ")]
            if rel_roles:
                for rel_role in rel_roles:
                    relationship_type = rel_role.name.replace(f"{bot.user.name} - ", "").strip()
                    user_tracker.set_relationship(member.id, relationship_type)
                    print(f"[Startup] {member.display_name} is marked as '{relationship_type}' with Monika.")
            else:
                user_tracker.set_relationship(member.id, None)

    try:
        await bot.tree.sync()
        logger.info("✅ Slash commands synced.")

        await on_startup()
        logger.info("✅ Memory restored.")

        logger.info(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")
        logger.info(f"✅ Connected to {len(bot.guilds)} guilds, {len(bot.users)} users.")

        # Background tasks
        errors = await asyncio.to_thread(error_detector.scan_code)
        channel = bot.get_channel(error_detector.SETTINGS_CHAN)
        if channel:
            if errors:
                msg = "\n".join(errors)
                if len(msg) > 1900:
                    msg = msg[:1900] + "\n... (truncated)"
                await channel.send(f"🚨 Startup scan found issues:\n```{msg}```")
            else:
                await channel.send("✅ Startup scan: No issues found.")

        # Background periodic scan
        bot.loop.create_task(periodic_scan(bot, interval=45))
        asyncio.create_task(periodic_rescan())
        monitor_event_loop()
        asyncio.create_task(async_cleanup_memory())

    except Exception as e:
        logger.exception(f"[on_ready] Failed: {e}")

    key_manager.start_idle_rotator()

    if idle_chat_enabled or idlechat_loop() or monika_idle_conversation_task():
        return []
    
    await vote_tracker.load(bot, SETTINGS_CHAN)

    is_waking_up = False
    print("[Bot] Wake-up mode finished. Back to normal idlechat.")

async def periodic_scan(bot, interval: int = 300):  # every 5 min
    last_errors = None
    while True:
        try:
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

            if errors != last_errors:  # only report new results
                channel = bot.get_channel(error_detector.SETTINGS_CHAN)
                if channel:
                    if errors:
                        msg = "\n".join(errors)
                        if len(msg) > 1900:
                            msg = msg[:1900] + "\n... (truncated)"
                        await channel.send(f"🚨 Updated scan report:\n```{msg}```")
                    else:
                        await channel.send("✅ Code scan: No issues found.")
                last_errors = errors
        except Exception as e:
            print(f"[SCAN] Error during subprocess scan: {e}")

        await asyncio.sleep(interval)

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

@bot.event
async def on_error(event, *args, **kwargs):
    err_text = f"[EVENT ERROR] {event}: {traceback.format_exc()}"
    status_info["last_error"] = err_text
    status_info["error_count"] += 1
    await error_detector.report_error(bot, error_detector.SETTINGS_CHAN, err_text, "Error")
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

                        if len(buffer) >= batch_size:
                            await channel.send("\n".join(buffer))
                            buffer.clear()
                            await asyncio.sleep(0.5)

        if buffer:
            await channel.send("\n".join(buffer))

    except Exception as e:
        logger.exception(f"[Memory] Failed to save memory: {e}")

async def get_monika_context(channel: discord.abc.Messageable, limit: int = 20) -> list[dict]:
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

                async for msg in channel.history(limit=200, oldest_first=True):
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
    bot_name = bot.user.name
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
    valid_relationships = list(monika_traits.relationships)
    if new_relationship not in valid_relationships:
        print(f"[AutoRel] Invalid relationship: {new_relationship}. Resetting to Stranger.")
        new_relationship = "Stranger"

    # 7️⃣ Create or assign role
    role_name = f"{bot_name} - {new_relationship}"
    role = discord.utils.get(guild.roles, name=role_name)
    if not role:
        role = await guild.create_role(name=role_name, color=discord.Color.teal())
        print(f"[AutoRel] Created new role: {role_name}")

    if role not in user_member.roles:
        await user_member.add_roles(role, reason=f"Auto relationship: {new_relationship}")
        print(f"[AutoRel] {user_member.display_name} → {role_name}")

    # 8️⃣ Save tracker
    await user_tracker.save(bot, channel_id=USER_TRACKER_CHAN)

@bot.event
async def setup_hook():
    bot.loop.create_task(heartbeat_task())  # start heartbeat
    bot.loop.create_task(periodic_cleanup())
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
async def on_guild_leave(guild):

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
    await on_shutdown()

@bot.event
async def on_shutdown():
    print("[Shutdown] Saving memory to channel...")
    asyncio.create_task(save_memory_to_channel())
    await server_tracker.save(bot, channel_id=SERVER_TRACKER_CHAN)
    await vote_tracker.save(bot, SETTINGS_CHAN)

@bot.event
async def on_sleeping(reason: str = "Taking a nap..."):
    """Triggered when the bot goes into sleep mode (no replies until wake)."""
    global idle_chat_enabled, idlechat_paused

    status_info.update({
        "is_sleeping": True,
        "last_sleep": datetime.datetime.utcnow(),
        "sleep_reason": reason
    })
    bot.is_sleeping = True
    idle_chat_enabled = False
    idlechat_paused = True

    print(f"[Sleep] 😴 Entering sleep mode. Reason: {reason}")

    statuses = [
        ("I'm going to take a nap...", 5),
        ("💤 ZZZ... zzz... zzzz...", 7),
        ("Dreaming about you...", 10),
        ("Dreaming about you...(secretly editing my coding)", 3)
    ]
    for text, delay in statuses:
        await bot.change_presence(status=discord.Status.idle,
                                  activity=discord.Game(text))
        await asyncio.sleep(delay)

    # Announce in first available channel
    channel = next((c for c in bot.get_all_channels()
                   if isinstance(c, discord.TextChannel)
                   and c.permissions_for(c.guild.me).send_messages), None)

    if channel:
        await channel.send(f"😴 The bot is now sleeping. Reason: **{reason}**")

last_wakeup_date = None  

async def on_wake_up(reason: str = "I'm back online!"):
    global is_waking_up, last_wakeup_date, idle_chat_enabled

    status_info.update({
        "is_sleeping": False,
        "last_wake": datetime.datetime.utcnow(),
        "wake_reason": reason
    })
    bot.is_sleeping = False

    print(f"[Wake] 🌅 Waking up. Reason: {reason}")
    is_waking_up = True

    today = datetime.date.today()

    # Prevent multiple wakeups per day
    if last_wakeup_date == today:
        print("[Wakeup] Already sent a wakeup message today, skipping...")
        return
    last_wakeup_date = today

    print(f"[Wakeup] 🌅 Monika is waking up: {reason}")

    # Presence cycle
    statuses = [
        ("Waking up...", 3),
        ("Stretching...", 3),
        ("Getting dressed...", 3),
        ("Ready to chat! 💚", 0),
        ("Ready to chat!! 💚", 2),
        ("Ready to chat!!! 💚", 2)
    ]
    for text, delay in statuses:
        await bot.change_presence(status=discord.Status.online, activity=discord.Game(text))
        if delay > 0:
            await asyncio.sleep(delay)

    # 🌅 Wake-up messages (pick one per day)
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

    # ✅ Send only one random message per guild
    for guild in bot.guilds:
        wakeup_line = random.choice(wakeup_lines)

        target_channel = None

        # First try: look for a preferred channel
        for channel in guild.text_channels:
            if not channel.permissions_for(guild.me).send_messages:
                continue
            if channel.name in OFF_LIMITS_CHANNELS:
                continue
            if channel.name in MON_CHANNEL_NAMES:
                target_channel = channel
                break

        # Fallback: pick the first available channel if no preferred one found
        if not target_channel:
            for channel in guild.text_channels:
                if not channel.permissions_for(guild.me).send_messages:
                    continue
                if channel.name in OFF_LIMITS_CHANNELS:
                    continue
                target_channel = channel
                break

        # Send to chosen channel
        if target_channel:
            try:
                await target_channel.send(wakeup_line)
                print(f"[Wakeup] Sent wakeup message to #{target_channel.name} in {guild.name}")
            except Exception as e:
                print(f"[Wakeup Error] Could not send to #{target_channel.name} in {guild.name}: {e}")

    await asyncio.sleep(3)
    await bot.change_presence(activity=None)

    # ✅ Resume idle chat afterwards
    await asyncio.sleep(3)
    idle_chat_enabled = True
    return []

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

# active_votes = {}

@bot.event
async def on_message(message: discord.Message):
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

    # Ignore "!" commands outside report/settings channels
    if message.content.startswith("!") and message.channel.id not in (REPORT_CHANNEL_ID, SETTINGS_CHAN):
        return

    # ==============================
    # 2. Report channel handling (staff reply to reports)
    # ==============================
    if message.channel.id == REPORT_CHANNEL_ID:
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
    if message.channel.id == SETTINGS_CHAN and not message.author.bot:
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

        return  # stop further handling in settings channel

    #     elif content.startswith("!create vote"):
    #         if message.author.id != OWNER_ID:
    #             await message.channel.send("❌ Only the owner can create votes.")
    #             return

    #         parts = [opt.strip() for opt in message.content[len("!create vote"):].split("|") if opt.strip()]
    #         if not parts or len(parts) > 5:
    #             await message.channel.send("❌ Provide between 1 and 5 options separated by `|`.")
    #             return

    #         # ✅ reset global vote
    #         active_votes["active"] = {"options": parts, "votes": {}, "menu_id": None}

    #         embed = discord.Embed(title="🗳️ New Global Vote Started!", color=discord.Color.green())
    #         for i, option in enumerate(parts, 1):
    #             embed.add_field(name=f"Option {i}", value=option, inline=False)

    #         menu_message = await message.channel.send(embed=embed)
    #         active_votes["active"]["menu_id"] = menu_message.id
    #         return

    # # --- Voting System ---
    # if content.startswith("!vote menu"):
    #     vote = active_votes.get("active")
    #     if not vote:
    #         await message.channel.send("❌ No active vote right now.")
    #         return

    #     # Count votes
    #     counts = {i: 0 for i in range(1, len(vote["options"]) + 1)}
    #     for choice in vote["votes"].values():
    #         counts[choice] += 1

    #     # Build embed
    #     embed = discord.Embed(title="🗳️ Current Global Voting Menu", color=discord.Color.blue())
    #     for i, option in enumerate(vote["options"], 1):
    #         embed.add_field(
    #             name=f"Option {i}",
    #             value=f"{option}\n**Votes:** {counts[i]}",
    #             inline=False
    #         )

    #     await message.channel.send(embed=embed)
    #     return
    
    # if content.startswith("!vote "):
    #     vote = active_votes.get("active")
    #     if not vote:
    #         await message.channel.send("❌ No active vote right now.")
    #         return

    #     arg = message.content.split(" ", 1)[1].strip()
    #     if arg == "cancel":
    #         if message.author.id in vote["votes"]:
    #             del vote["votes"][message.author.id]
    #             await message.channel.send(f"✅ {message.author.display_name}, your vote has been cancelled.")
    #         else:
    #             await message.channel.send("❌ You don’t have an active vote.")
    #         return

    #     try:
    #         choice = int(arg)
    #     except ValueError:
    #         await message.channel.send("❌ Please enter a number (1–5) or `cancel`.")
    #         return

    #     if choice < 1 or choice > len(vote["options"]):
    #         await message.channel.send("❌ Invalid option number.")
    #         return

    #     vote["votes"][message.author.id] = choice
    #     await message.channel.send(f"✅ {message.author.display_name}, you voted for **{vote['options'][choice-1]}**")
    #     return

    # if content.startswith("!vote results") and message.author.id == OWNER_ID:
    #     vote = active_votes.get("active")
    #     if not vote:
    #         await message.channel.send("❌ No active vote right now.")
    #         return

    #     counts = {i: 0 for i in range(1, len(vote["options"]) + 1)}
    #     for choice in vote["votes"].values():
    #         counts[choice] += 1

    #     embed = discord.Embed(title="📊 Final Vote Results", color=discord.Color.purple())
    #     for i, option in enumerate(vote["options"], 1):
    #         embed.add_field(name=f"Option {i}", value=f"{option} → {counts[i]} votes", inline=False)

    #     await message.channel.send(embed=embed)

    #     # 🔹 Reset after showing results
    #     active_votes.clear()
    #     await message.channel.send("✅ Voting has ended. Start a new one with `!create vote`.")
    #     return

    # 4. Guild usage tracking
    guild_name = str(message.guild.name) if message.guild else "dm"
    guild_id = str(message.guild.id) if message.guild else "dm"
    user_id = str(message.author.id)
    username = message.author.display_name
    channel_id = str(message.channel.id)
    channel_name = message.channel.name if message.guild else "dm"
    channel_usage.setdefault(guild_id, {})
    channel_usage[guild_id][channel_id] = channel_usage[guild_id].get(channel_id, 0) + 1

    # 6. Mentions
    if server_tracker.get_toggle(guild_id, "mention_only_mode"):
        if bot.user not in message.mentions and not isinstance(message.channel, discord.DMChannel):
            return  # Ignore messages without @Monika

    # ✅ Idle/chat toggle
    if not server_tracker.get_toggle(guild_id, "idlechat"):
        return
    
    avatar_url = str(message.author.display_avatar.url) if message.author.display_avatar else None
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
    """Return a stable CDN link for sprite; upload once if not cached."""
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
    import aiohttp
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
    relationship = "Stranger"
    personality = ["Default"]
    guild = None

    # If the user shares a server with Monika, inherit personality/relationship from first one
    if bot.guilds:
        for g in bot.guilds:
            member = g.get_member(user.id)
            if member:
                guild = g
                relationship = getattr(monika_traits, "get_relationship", lambda _: "Stranger")(user_id)
                personality = server_personality_modes.get(str(g.id), ["Default"])
                break

    # --- Build system prompt ---
    system_prompt = await generate_monika_system_prompt(
        guild=guild,
        user=user,
        relationship_type=relationship,
        selected_modes=personality
    )

    # --- Conversation context ---
    context_entries = await get_monika_context(message.channel, limit=20)
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
        response = await call_openai_with_retries(user, relationship, personality, conversation)
        if response and response.choices and response.choices[0].message:
            content = response.choices[0].message.content.strip()
            if content:
                monika_DMS = clean_monika_reply(content, bot_name, user.display_name)
                emotion = await classify_cached(monika_DMS)
                sprite_link = await get_sprite_link_cached(emotion, get_time_based_outfit())
    except Exception as e:
        print(f"[DM OpenAI Error] {e}")

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

    # --- Logging ---
    if DM_LOGS_CHAN:
        forward_channel = bot.get_channel(DM_LOGS_CHAN)
        if forward_channel:
            translated_msg = translate_to_english(message.content)

            if message.content.startswith("<@1375562131784732812>"):
                return ["Monika"]

            await forward_channel.send(
                f"**From {user} in DM:**\n"
                f"Original: {message.content}\n"
                f"English: {translated_msg}\n"
                f"**Reply ({bot_name}):** {monika_DMS}"
            )
            
async def handle_guild_message(message: discord.Message, avatar_url: str):
    """Handle messages inside guilds with personality/relationship context."""
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
    context_entries = await get_monika_context(message.channel, limit=20)
    conversation = [{"role": "system", "content": system_prompt}]
    for entry in context_entries:
        role = "assistant" if entry["author"] == "Monika" else "user"
        conversation.append({"role": role, "content": entry["content"]})
    conversation.append({"role": "user", "content": message.content})

    # --- Defaults ---
    monika_reply = random.choice(error_messages)
    emotion = "error"
    sprite_link = await error_emotion()

    # --- OpenAI ---
    try:
        response = await call_openai_with_retries(
            user=message.author,
            relationship=relationship_type,
            personality=personality,
            conversation=conversation
        )
        if response and response.choices and response.choices[0].message:
            content = response.choices[0].message.content.strip()
            if content:
                monika_reply = content
                emotion = await classify_cached(monika_reply)
                sprite_link = await get_sprite_link_cached(emotion, get_time_based_outfit())
    except Exception as e:
        print(f"[Guild OpenAI Error] {e}")

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

    # --- Memory logging ---
    if MEMORY_CHAN_ID:
        dest_channel = bot.get_channel(MEMORY_CHAN_ID)

        if message.content.startswith("<@1375562131784732812>"):
            return ["Monika"]

        if dest_channel:
            try:
                timestamp = datetime.datetime.utcnow().isoformat()
                if user_id and username:
                    header = f"📩 `[{timestamp}]` | `User: {username} ({user_id})` | "
                elif user.bot or is_friend:
                    header = f"📩 `[{timestamp}]` | `Bot: {user.bot}`| `emotion: {emotion}` | "
                body = f"`Server: {guild_name} ({guild_id})` | `Channel: {channel_name} ({channel_id})`"
                quote = ""
                if message.reference and message.reference.resolved:
                    ref = message.reference.resolved
                    if isinstance(ref, discord.Message):
                        ref_author = ref.author.display_name
                        ref_content = ref.content or "*[No text]*"
                        quote = f"> 🗨️ __Reply to {ref_author}__: {ref_content}\n\n"
                if message.attachments:
                    for attachment in message.attachments:
                        await dest_channel.send(attachment.url)
                translated_msg = translate_to_english(message.content)
                full_content = (
                    f"{header}{body}:\n"
                    f"{quote}> Original: `{message.content}`\n"
                    f"> English: `{translated_msg}`"
                )
                await dest_channel.send(full_content)

            except Exception as e:
                print(f"[Forwarding Error] {e}")

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
    from Idle_Presence import monika_idle_presences
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
        gid = str(interaction.guild.id)
        current_state = server_tracker.get_toggle(gid, "idlechat_enabled") or False
        new_state = not current_state
        server_tracker.set_toggle(gid, "idlechat_enabled", new_state)

        button.label = f"💬 Idlechat ({'ON' if new_state else 'OFF'})"
        await server_tracker.save(interaction.client, SERVER_TRACKER_CHAN)
        await interaction.response.edit_message(view=self)

    # ⏱ Idlechat Timer
    @discord.ui.button(label="⏱ Idlechat Timer", style=discord.ButtonStyle.primary)
    async def idlechat_timer(self, interaction: discord.Interaction, button: discord.ui.Button):
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
        gid = str(interaction.guild.id)
        server_tracker.guilds[gid]["memory"] = {}  # clear memory dict
        await server_tracker.save(interaction.client, SERVER_TRACKER_CHAN)
        await interaction.response.send_message("🧹 All memory has been reset!", ephemeral=True)

    # 🎭 Reset Personality
    @discord.ui.button(label="🎭 Reset Personality", style=discord.ButtonStyle.danger)
    async def reset_personality(self, interaction: discord.Interaction, button: discord.ui.Button):
        gid = str(interaction.guild.id)
        server_tracker.guilds[gid]["personality_roles"] = []
        await server_tracker.save(interaction.client, SERVER_TRACKER_CHAN)
        await interaction.response.send_message("🎭 Personality reset complete.", ephemeral=True)

    # 💞 Reset Relationship
    @discord.ui.button(label="💞 Reset Relationship", style=discord.ButtonStyle.danger)
    async def reset_relationship(self, interaction: discord.Interaction, button: discord.ui.Button):
        gid = str(interaction.guild.id)
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
    description="Toggle whether if I would be idle/chatty mode for this server."
)
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(state="Set to true (on) or false (off)")
async def idlechat(interaction: discord.Interaction, state: bool):
    guild_id = str(interaction.guild.id)
    user = interaction.user.display_name
    print(f"Administrator: {user} used `/idlechat`: set {state}")

    server_tracker.set_toggle(guild_id, "idlechat", state)
    await server_tracker.save(bot, channel_id=SERVER_TRACKER_CHAN)

    state_text = "On ✅" if state else "Off ❌"
    await interaction.response.send_message(
        f"✅ Idle chat mode set to **{state_text}** for this server.",
        ephemeral=True
    )

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
    #                              ↓
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
    # vote_commands = ["!vote 1-5", "!vote menu", "!vote cancel"]

    admin_cmds = []
    user_cmds = []
    # vote_cmds = vote_commands

    # if "!vote 1-5" in vote_cmds:
    #     description = "select between 1-5"

    # if "!vote menu" in vote_cmds:
    #     description = "shows the voting menu(administrators only)"

    # if "!vote cancel" in vote_cmds:
    #     description = "cancel the your current vote"

    for command in bot.tree.get_commands():
        # Skip hidden commands
        if command.name in hidden_cmds:
            continue

        # Check if the command has permission checks (like admin)
        if any("has_permissions" in str(check) for check in getattr(command, "checks", [])):
            admin_cmds.append(f"`* /{command.name} *` – {command.description or 'No description'}")
        elif not any("has_permissions" in str(check) for check in getattr(command, "checks", [])):
            user_cmds.append(f"`* /{command.name} *` – {command.description or 'No description'}")
        # else:
        #     vote_cmds.append(f"`* {vote_commands} *` – {description or 'Help when vote for the new feature'}")

    embed = discord.Embed(
        title="✒️ Need a little help?",
        description="Hi there! Here’s what you can ask me to do. Don’t be shy, okay?\n",
        color=discord.Color.green()
    )

    if admin_cmds:
        embed.add_field(name="🔧 Admin Commands", value="\n".join(admin_cmds), inline=False)
    if user_cmds:
        embed.add_field(name="💬 User Commands", value="\n".join(user_cmds), inline=False)
    # if vote_cmds:
    #     embed.add_field(name="💬 Vote Commands", value="\n".join(vote_cmds), inline=False)

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
            if role.name.startswith("Monika -") or role.name.startswith(f"{interaction.user.display_name} -"):
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
                if role_name.startswith("Monika -"):
                    await interaction.user.add_roles(role, reason="Restored user relationship role")
                elif role_name.startswith(interaction.user.display_name):
                    monika_member = interaction.guild.get_member(bot.user.id)
                    if monika_member:
                        await monika_member.add_roles(role, reason="Restored bot relationship role")

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
    if today.month == 9 and today.day == 21:
        await interaction.response.send_message(
            "❌ You can’t change my outfit today… it’s a special day.",
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
    options = ["default", "poll", "custom"]
    return [
        app_commands.Choice(name=opt, value=opt)
        for opt in options if current.lower() in opt.lower()
    ]

async def custom_reactions_autocomplete(interaction: discord.Interaction, current: str):
    choices = []

    # Unicode emoji suggestions
    unicode_emojis = ["✅", "❌", "👍", "👎", "🤔", "🎉", "🔥", "💚"]
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
    reaction_set: str = "default",   # default, poll, or custom
    custom_reactions: str = None     # comma-separated emojis
):
    await interaction.response.defer(ephemeral=True)

    global is_broadcasting
    user = interaction.user

    if user.id != OWNER_ID:
        await interaction.response.send_message("❌ You can't use this command.", ephemeral=True)
        return

    if is_broadcasting:
        await interaction.response.send_message("❌ A broadcast is already in progress.", ephemeral=True)
        return

    wait_minutes = 3
    update_interval = 30
    is_broadcasting = True
    await bot.change_presence(activity=discord.Game("📣 Announcement in progress..."))

    try:
        # --- Reaction sets ---
        available_sets = {
            "default": ["✅", "❌"],
            "poll": ["👍", "👎", "🤔"]
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
        embed.set_footer(
            text="Pick your reaction to vote. Use /report for bugs, errors, or feedback. "
                 "Please wait until I finish sharing this announcement."
        )

        success_count, failure_count, skip_count = 0, 0, 0
        sent_messages = []
        announcement_id = f"{title}:{message}"

        # --- Step 1: Find servers to announce ---
        servers_to_announce = []
        for guild in bot.guilds:
            gid = str(guild.id)
            server_tracker.ensure_guild(gid)

            # Skip if already broadcasted within 24h
            last_time = server_tracker.guilds[gid].get("last_broadcast_time")
            if last_time:
                last_dt = datetime.datetime.fromisoformat(last_time)
                if (datetime.datetime.now(datetime.timezone.utc) - last_dt).total_seconds() < 86400:
                    print(f"[Broadcast] ⏭ Skipping {guild.name}, announced in last 24h")
                    skip_count += 1
                    continue

            # Skip if announcement already logged
            if announcement_id in server_tracker.guilds[gid].get("announcements", []):
                print(f"[Broadcast] ⏭ Skipping {guild.name}, already logged")
                skip_count += 1
                continue

            # Find usable channel
            channel = None
            for c in guild.text_channels:
                if c.permissions_for(guild.me).send_messages:
                    if c.name not in OFF_LIMITS_CHANNELS:
                        channel = c
                        break

            if not channel:
                print(f"[Broadcast] ❌ No available channel in {guild.name} ({guild.id})")
                failure_count += 1
                continue

            servers_to_announce.append((guild, gid, channel))

        if not servers_to_announce:
            await interaction.followup.send(
                f"⚠️ No servers need this announcement.\n"
                f"⏭ Skipped **{skip_count}** servers (already had it).\n"
                f"❌ Failed in **{failure_count}** servers.",
                ephemeral=True
            )
            return

        # --- Step 2: Send warning messages ---
        confirmed_servers = []
        for guild, gid, channel in servers_to_announce:
            try:
                await channel.send("⚠️ **Attention everyone!** An announcement will begin shortly. Please stand by...")
                confirmed_servers.append((guild, gid, channel))
            except Exception as e:
                print(f"[Broadcast Warning Error] in {guild.name}: {e}")
                failure_count += 1

        await asyncio.sleep(10)

        # --- Step 3: Send the actual announcement ---
        for guild, gid, channel in confirmed_servers:
            try:
                msg = await channel.send(embed=embed)
                for r in reactions:
                    try:
                        await safe_add_reaction(msg, r)
                    except Exception as e:
                        print(f"[Broadcast Reaction Error] {e}")

                progress = await channel.send("⏳ Collecting reactions...")
                sent_messages.append((msg, progress))

                # Log announcement only after success
                server_tracker.guilds[gid].setdefault("announcements", [])
                server_tracker.guilds[gid]["announcements"].append(announcement_id)
                server_tracker.guilds[gid]["last_broadcast_time"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
                await server_tracker.save(bot, channel_id=SERVER_TRACKER_CHAN)

                print(f"[Broadcast] ✅ Sent to {guild.name} in #{channel.name}")
                success_count += 1
                await asyncio.sleep(0.2)
            except Exception as e:
                print(f"[Broadcast Error] in {guild.name}: {e}")
                failure_count += 1

        # --- Step 4: Collect votes ---
        await asyncio.sleep(60)
        elapsed = 0
        while elapsed < wait_minutes * 60:
            for orig, progress in sent_messages:
                try:
                    refreshed = await orig.channel.fetch_message(orig.id)
                    counts = {}
                    for reaction in refreshed.reactions:
                        emoji = str(reaction.emoji)
                        users = [u async for u in reaction.users() if u.id != bot.user.id]
                        counts[emoji] = len(users)
                    result_line = " | ".join([f"{emoji} {count}" for emoji, count in counts.items()])
                    await progress.edit(content=f"{result_line} (updating...)")
                except discord.errors.NotFound:
                    print("[Broadcast Update Error] Progress message deleted, skipping.")
                except Exception as e:
                    print(f"[Broadcast Update Error] {e}")

            await asyncio.sleep(update_interval)
            elapsed += update_interval

        # --- Step 5: Final pass ---
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
                await progress.edit(content=f"{result_line} (final)")

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
                print("[Broadcast Fetch Error] Original or progress message deleted.")
            except Exception as e:
                print(f"[Broadcast Fetch Error] {e}")

        # --- Step 6: Build summary ---
        if reaction_set == "default":
            summary_lines = [f"✅ Likes: **{like_total}**", f"❌ Dislikes: **{dislike_total}**"]
        elif reaction_set == "poll":
            summary_lines = [
                f"👍 Likes: **{like_total}**",
                f"👎 Dislikes: **{dislike_total}**",
                f"🤔 Maybe: **{maybe_total}**"
            ]
        else:
            summary_lines = [f"{emoji}: **{total}**" for emoji, total in custom_totals.items()]

        # --- Step 7: Final owner summary ---
        await interaction.followup.send(
            f"✅ Broadcast finished.\n"
            f"Sent successfully to **{success_count}** servers.\n"
            f"⚠️ Failed in **{failure_count}** servers.\n"
            f"⏭ Skipped **{skip_count}** servers (already had this announcement).\n\n"
            + "\n".join(summary_lines),
            ephemeral=True
        )

    finally:
        # Always reset state even on crash
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
    keepalive.keep_alive()  # start keepalive Flask
    while True:
        try:
            asyncio.run(main())  # run bot forever
        except BaseException:
            print("⚠️ Fatal asyncio error, restarting in 10s")
            traceback.print_exc()
            time.sleep(10)
