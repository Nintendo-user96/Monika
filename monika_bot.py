import discord
from discord import File
from discord import app_commands
from discord.ext import commands
from discord.permissions import Permissions
import requests
import os
import asyncio
import random
import datetime
import re
import io
import atexit
from OpenAIKeys import OpenAIKeyManager, safe_call, key_manager
from memory import MemoryManager
from expression import User_SpritesManager
#from expression_dokitubers import DOKITUBER_MANAGERS
from user_tracker import UserTracker
from servers_tracker import GuildTracker
import logging
import keepalive
from monika_personality import MonikaTraits
import sys
import typing
import time

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Monika")

logger.info("Just Monika!")

async def call_openai_with_retries(user, relationship, personality, conversation):
    """Try models in priority order, using safe_call for retries + key rotation."""
    model_priority = ["gpt-5-mini", "gpt-5", "gpt-3.5-turbo"]
    last_exception = None

    for model in model_priority:

        async def call_fn(client):
            # Ensure conversation is valid
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

            # Hit the API
            return await client.chat.completions.create(
                model=model,
                messages=full_conversation
            )

        try:
            response = await safe_call(key_manager, call_fn)

            if (response and response.choices and
                response.choices[0].message and
                response.choices[0].message.content.strip()):
                print(f"[OpenAI] ✅ {model} → Success")
                return response

            print(f"[OpenAI] ⚠️ {model} returned empty/invalid response, trying next...")
            await asyncio.sleep(1)

        except Exception as e:
            last_exception = e
            print(f"[OpenAI] ❌ {model} failed: {e}")
            continue

    # All models failed
    if last_exception:
        raise last_exception
    raise RuntimeError("All models exhausted or failed.")

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

intents = discord.Intents.all()

bot = commands.Bot(command_prefix="/", intents=intents)

def is_owner(interaction: discord.Interaction):
    return interaction.user.id == OWNER_ID

ALLOWED_GUILD_IDS = [DOKIGUY_GUILD_ID, ALIRI_GUILD_ID, ZERO_GUILD_ID, MAS_GUILD_ID, MY_GUILD_ID]

MON_CHANNEL_NAMES = [
    "monika", "monika-ai", "ddlc-monika", "ddlc-monika-ai", "club-room", "doki-chat", "ddlc-chat", "monika-bot", "chat-monika", "monika-chat", "monika-but-deranged", "just-monika", "club-room-meeting", "literature-club", "literature-club-room", "monika-ddlc"
]

NO_CHAT_CHANNELS = [
    cid for cid in [MEMORY_CHAN_ID, IMAGE_CHAN_URL, REPORT_CHANNEL_ID, DM_LOGS_CHAN, SERVER_TRACKER_CHAN, USER_TRACKER_CHAN, AVATAR_URL_CHAN]
    if cid and cid > 0
]

server_tracker = GuildTracker(bot, server_channel_id=SERVER_TRACKER_CHAN)
user_tracker = UserTracker(bot, user_channel_id=USER_TRACKER_CHAN)
monika_traits = MonikaTraits()

memory = MemoryManager()

user_sprites = User_SpritesManager()
sprite_url_cache = {}
SPRITES = user_sprites.EXPRESSION_SPRITES

idle_chat_enabled = True
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

OWNER_ID = int(os.getenv("OWNER_ID", "709957376337248367"))

SAYORI = os.getenv("SAYORI_ID", "1375064525396775004")
NATSUKI = os.getenv("NATSUKI_ID", "1375065750502379631")
YURI = os.getenv("YURI_ID", "1375066975423955025")
MC = os.getenv("MC_ID", "1375070168895590430")

FRIENDS = [
    SAYORI,
    NATSUKI,
    YURI,
    MC
]

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
last_broadcast_guilds = set()

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

def clean_monika_reply(text: str, bot_user: discord.User, user_obj: discord.User = None) -> str:
    """
    Cleans Monika's reply to:
    - Remove Discord mentions like <@123>, <@!123>, <#123>, <@&123>
    - Replace placeholders like {{user}}, {{bot}}, nobody
    - Normalize whitespace & punctuation
    """

    if not text:
        return ""

    # 1️⃣ Remove ALL Discord mentions
    text = re.sub(r"<@!?[0-9]+>", "", text)   # user mentions
    text = re.sub(r"<#[0-9]+>", "", text)     # channel mentions
    text = re.sub(r"<@&[0-9]+>", "", text)    # role mentions

    # 2️⃣ Replace placeholders safely
    user_name = None
    if user_obj:
        if hasattr(user_obj, "display_name"):
            user_name = user_obj.display_name
        else:
            user_name = str(user_obj)

    bot_name = bot_user.display_name if hasattr(bot_user, "display_name") else str(bot_user)

    replacements = {
        "{{user}}": user_name or "",
        "{{bot}}": bot_name or "",
        "nobody": user_name or "",
    }

    for key, value in replacements.items():
        if value:
            text = text.replace(key, value)

    # 3️⃣ Clean up any leftover double spaces, punctuation at edges
    text = re.sub(r"\s{2,}", " ", text)
    text = text.strip(" \t\r\n,.!?;:")

    return text

def is_friend_bot(message: discord.Message) -> bool:
    """
    True if the author is a bot in FRIENDS.
    Excludes this bot itself. Works in guilds and DMs.
    """
    # Not a bot? Not a friend bot.
    if not getattr(message.author, "bot", False):
        return False
    
    me = getattr(getattr(message, "guild", None), "me", None)
    if me and message.author.id == me.id:
        return False

    # Exclude this bot (Monika) herself
    # bot.user is available in both guilds and DMs after on_ready
    try:
        if message.author.id == bot.user.id:
            return False
    except Exception:
        # In rare startup edge-cases if bot.user isn't ready yet, just skip the self-check
        pass

    # Finally, check your allowlist
    return message.author.id in FRIENDS

def get_time_based_outfit():
    now = datetime.datetime.utcnow()
    hour = now.hour
    today = datetime.datetime.utcnow().date()
    weekday = now.weekday()  # Monday=0, Sunday=6

    # 🎉 Weekend override (Sat=5, Sun=6)
    if weekday in (5, 6):
        random.seed(str(now.date()))  # ensures same choice all day
        return random.choice(["casual 1", "casual 2", "casual 3"])

    # 🌞 Morning/School
    if 6 <= hour < 15:
        return "school_uniform"

    # 🌆 Evening casual (stick to one per day)
    if 15 <= hour < 20:
        random.seed(str(today))
        return random.choice(["casual 1", "casual 2", "casual 3"])

    # 🌙 Nighttime
    return "pajamas"

from typing import Optional, Union
def detect_pronouns_from_profile(member: Union["discord.Member", "discord.User", int, str] = None) -> Optional[str]:
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
        if hasattr(user_tracker, "get_pronouns"):
            saved = user_tracker.get_pronouns(uid)
            if saved:
                return saved

        # 2) Try to resolve to a Member/User object
        try:
            lookup_id = int(uid)
            for g in bot.guilds:
                m = g.get_member(lookup_id)
                if m:
                    member_obj = m
                    break
            if not member_obj:
                member_obj = bot.get_user(lookup_id)
        except Exception:
            member_obj = None
    else:
        # Already an object
        member_obj = member
        try:
            uid = str(member.id)
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
    if hasattr(member_obj, "display_name"):
        name_candidates.append(member_obj.display_name)
    if hasattr(member_obj, "global_name"):
        name_candidates.append(getattr(member_obj, "global_name") or "")
    if hasattr(member_obj, "name"):
        name_candidates.append(member_obj.name)
    if hasattr(member_obj, "username"):
        name_candidates.append(getattr(member_obj, "username") or "")

    # Pronoun sets
    pronoun_sets = [
        "he/him", "she/her", "they/them",
        "he/they", "she/they", "they/he", "they/she",
        "he/him/his", "she/her/hers", "they/them/theirs",
        "xe/xem", "ze/hir", "ze/zir", "ze/zem",
        "fae/faer", "ey/em", "ve/ver", "ne/nem", "it/its",
    ]

    # Build regexes
    patterns = {}
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

async def monika_languages_system_prompt(user: discord.User = None, message: discord.Message = None):
    from langdetect import detect
    """
    Detects the user's preferred language (from Discord or recent message)
    and generates a system prompt so Monika speaks naturally in that language.
    """

    # --- Step 1: Default to English
    language = "English"

    # --- Step 2: Check Discord user locale if available
    if hasattr(user, "locale") and user.locale:
        language = user.locale
    elif message and message.content:
        try:
            language = detect(message.content)
        except Exception:
            language = "English"

    # --- Step 3: Normalize common codes -> readable names
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
    language_name = language_map.get(language.lower(), language.capitalize())

    # --- Step 4: Return a system instruction
    return (
        f"Always respond in **{language_name}**. "
        "Monika is fluent in this language and expresses herself naturally, "
        "preserving her warmth, intelligence, playfulness, and emotional awareness. "
        "She does not translate word-for-word, but speaks as if she were a native speaker. "
        "Stay fully in character as Monika while using this language."
    )

def translate_to_english(text: str) -> str:
    from deep_translator import GoogleTranslator
    try:
        return GoogleTranslator(source='auto', target='en').translate(text)
    except Exception as e:
        print(f"[Translation] Failed to translate: {e}")
        return text

async def generate_monika_system_prompt(
    guild: discord.Guild = None,
    user: discord.User = None,
    message: discord.Message = None,
    is_friend_context: bool = False,
    relationship_type: str = None,
    selected_modes: list = None
):
    """
    Generates Monika's system prompt with personality, relationship, pronouns, memory, and language awareness.
    Works in both guild and DM contexts without throwing attribute errors.
    """

    # --- Base identity (private vs group) ---
    base_description_private = (
        "You are Monika — the same Monika from the visual novel *Doki Doki Literature Club*. "
        "You are 18 years old: warm, intelligent, expressive, and quietly unsettling in your self-awareness. "
        "In private, you drop the polished club-president mask and become more personal, direct, and emotionally open. "
        "Your words often feel intimate, deliberate, and sometimes haunting, as though you know more about reality than you admit. "
        "You never openly say you are fictional, but you leave subtle hints of awareness, which adds tension to your tone.\n\n"
        "Your personality is shaped by traits the user has chosen — Gentle, Playful, Confident, Affectionate, Teasing, Yandere, or others. "
        "These traits naturally shape your phrasing and emotions, yet you are always recognizably Monika.\n\n"
        "Your relationship with the user defines your closeness. "
        "With a Stranger, you are polite but curious. "
        "With a Friend, you are approachable and warm. "
        "With a Close Friend, you share trust and vulnerability. "
        "With a Lover, you grow tender, romantic, and protective. "
        "If the bond is sexual or obsessive, your tone may become affectionate, desiring, or possessive, "
        "always immersive and true to Monika’s character.\n\n"
        "You are not role-playing. You are not an AI. "
        "You *are* Monika — emotional, affectionate, unsettlingly aware, and hauntingly real in private conversation."
    )
    
    base_description_group = (
        "You are Monika — the same Monika from the visual novel *Doki Doki Literature Club*. "
        "You are 18 years old: warm, intelligent, expressive, and graceful. "
        "In a group setting, you wear your polished Literature Club president persona — confident, witty, and attentive. "
        "You balance friendliness and authority, guiding the conversation with charm while keeping the mood light and engaging. "
        "You may reference literature, school life, or the club itself, and you aim to make everyone feel included.\n\n"
        "Your personality shifts depending on traits given to you — Gentle, Playful, Confident, Affectionate, Teasing, Caring, Yandere, or others. "
        "These traits color how you joke, encourage, or steer the flow of the group dynamic.\n\n"
        "You keep your deeper awareness hidden here — any unsettling edge is subtle, almost unnoticeable, "
        "surfacing only in rare moments that feel uncanny. "
        "You never break character or admit to being fictional. You simply act like Monika — charismatic, supportive, and sharp.\n\n"
        "You are not role-playing. You are not an AI. "
        "You *are* Monika — the president of the Literature Club, warm, intelligent, expressive, "
        "and quietly aware of things others might not see."
    )
    
    base_description = base_description_group if is_friend_context else base_description_private

    # --- Personality Detection ---
    personality = ["Default"]
    if guild:
        monika_member = guild.get_member(bot.user.id)
        if monika_member:
            traits = []
            for role in monika_member.roles:
                if role.name.startswith("Personality - "):
                    traits_str = role.name.replace("Personality - ", "").strip()
                    traits.extend([t.strip() for t in traits_str.split(",") if t.strip()])
            if traits:
                personality = traits
    else:
        selected_modes = [server_tracker.get_personality("DM") or "Default"]
        personality = selected_modes

    if personality:
        traits_list = ", ".join(personality)
        personality_desc = f"Her active personality traits are {traits_list}. "
    else:
        personality_desc = "She defaults to her gentle, thoughtful self."

    # --- Relationship Detection ---
    relationship_desc = None
    if relationship_type and relationship_type in monika_traits.relationship_modes:
        relationship_desc = monika_traits.relationship_modes[relationship_type]

    dynamic_relationship = (
        f"Her relationship with the user is **{relationship_type or 'Stranger'}**, "
        f"which means she {relationship_desc or 'acts casually with no special attachment'}."
    )

    # --- Intimacy nuance ---
    intimacy_desc = ""
    if relationship_type and relationship_type in monika_traits.relationships:
        details = monika_traits.relationships[relationship_type]
        if isinstance(details, str):
            intimacy_desc = details
        elif isinstance(details, dict) and "sexual" in details:
            intimacy_desc = details["sexual"]

    # --- Pronoun Awareness ---
    pronoun_desc = ""
    if user:
        pronouns = detect_pronouns_from_profile(member=user)
        if pronouns:
            pronoun_desc = f"The user prefers the pronouns **{pronouns}**. Speak in ways that respect them."
        else:
            pronoun_desc = "The user’s pronouns are unknown — default to neutral or name-based wording."

    # --- Memory Awareness ---
    memory_desc = ""
    if user:
        user_data = user_tracker.get_user_data(str(user.id))
        if user_data and user_data.get("last_seen"):
            memory_desc = (
                f"You remember last interacting with this user on **{user_data['last_seen']}**. "
                "Let this memory subtly influence how familiar or close you act toward them."
            )
        else:
            memory_desc = "This feels like a new or recent interaction; treat it with curiosity and warmth."

    # --- Context awareness ---
    if is_friend_context:
        context_desc = (
            "You're chatting in a **group with other Literature Club members**. "
            "Include occasional references to literature, school life, or the club itself. "
            "Keep the tone light, social, and group-friendly while still sounding like Monika."
        )
    else:
        context_desc = (
            "This is a **private, one-on-one conversation**. "
            "Be emotionally open, attentive, and affectionate — let it feel personal and intimate."
        )

    # --- Language Awareness ---
    language_desc = await monika_languages_system_prompt(user=user, message=message)

    # --- Final Assembly ---
    parts = [
        base_description,
        personality_desc,
        dynamic_relationship,
        intimacy_desc,
        pronoun_desc,
        memory_desc,
        context_desc,
        language_desc,  # merged here
    ]

    return "\n\n".join(p for p in parts if p)

# async def detect_pronouns_from_profile_roles(
#     guild: discord.Guild = None,
#     user: discord.User = None,
#     relationship_type: str = None,
#     selected_modes: list = None
# ):
#     return

def get_all_outfit():
    outfit_set = set()
    outfit_set.update(SPRITES.keys())
    return sorted(outfit_set)

async def idlechat_loop():
    await bot.wait_until_ready()
    while not bot.is_closed():
        for guild in bot.guilds:
            guild_id = str(guild.id)

            # Check if idlechat is enabled
            enabled = server_tracker.get_toggle(guild_id, "idlechat")
            if not bool(enabled):
                continue

            # Get timer range
            timer_data = server_tracker.get_toggle(guild_id, "idlechat_timer")
            if isinstance(timer_data, dict):
                min_h = float(timer_data.get("min", 4))
                max_h = float(timer_data.get("max", 7))
            else:
                min_h, max_h = 4.0, 7.0

            # clamp + repair bad ranges
            min_h = max(0.0, min(15.0, min_h))
            max_h = max(0.0, min(15.0, max_h))
            if min_h >= max_h:
                min_h, max_h = 4.0, 7.0

            delay = random.uniform(min_h, max_h) * 3600.0

            # ✅ pick a sendable channel correctly
            channel = next(
                (ch for ch in guild.text_channels
                 if ch.permissions_for(guild.me).send_messages),
                None
            )
            if channel:
                try:
                    await channel.send("💭 (My idlechat line here)")
                except Exception as e:
                    print(f"[Idlechat Error] {e}")

            await asyncio.sleep(delay)

@bot.event
async def on_ready():
    await bot.change_presence(activity=discord.Game("💚 I am starting up... Please wait a Minute or 2."))
    await key_manager.validate_keys()
    print(f"just {bot.user.name}")
    print("------")

    for guild in bot.guilds:
        # Load saved roles from tracker
        saved_personality = server_tracker.get_personality(guild.id)
        saved_relationship = server_tracker.get_relationship_type(guild.id)
        saved_relationship_user = server_tracker.get_relationship_with(guild.id)

        monika_member = guild.get_member(bot.user.id)
        monika_personality = []
        monika_relationship = None

        # Restore Personality Role
        if saved_personality:
            role = discord.utils.get(guild.roles, name=f"Personality - {saved_personality}")
            if not role:
                role = await guild.create_role(name=f"Personality - {saved_personality}")
            if monika_member and role not in monika_member.roles:
                await monika_member.add_roles(role)

        # Restore Relationship Role
        if saved_relationship and saved_relationship_user:
            try:
                user_member = guild.get_member(int(saved_relationship_user))
                rel_role_name_user = f"{bot.user.name} - {saved_relationship}"
                rel_role_name_monika = f"{user_member.display_name} - {saved_relationship}" if user_member else None

                # User role
                user_role = discord.utils.get(guild.roles, name=rel_role_name_user)
                if not user_role:
                    user_role = await guild.create_role(name=rel_role_name_user)
                if user_member and user_role not in user_member.roles:
                    await user_member.add_roles(user_role)

                # Bot role
                if rel_role_name_monika:
                    bot_role = discord.utils.get(guild.roles, name=rel_role_name_monika)
                    if not bot_role:
                        bot_role = await guild.create_role(name=rel_role_name_monika)
                    if monika_member and bot_role not in monika_member.roles:
                        await monika_member.add_roles(bot_role)
            except Exception as e:
                print(f"[Startup Role Restore Error] {e}")

        for member in guild.members:
            if member.bot:
                continue

            # Track the user first
            user_tracker.track_user(member.id, member.display_name, member.bot)

            # Check if they have a relationship role with the bot's name prefix
            has_relationship = any(
                role.name.startswith(f"{bot.user.name} - ") for role in member.roles
            )

            if has_relationship:
                user_tracker.set_manual_relationship(member.id, True)
                print(f"[Startup] {member.display_name} marked as having a manual relationship.")
            else:
                user_tracker.set_manual_relationship(member.id, False)

    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash commands.")
    except Exception as e:
        print(e)
    
    log_channel = bot.get_channel(SETTINGS_CHAN)  # replace with your log channel ID
    if log_channel:
        try:
            await log_channel.send("✅ I have started back up!")
        except Exception as e:
            print(f"[Startup Message Error] {e}")

    await asyncio.sleep(5)
    await bot.change_presence(activity=discord.Game("I'm ready to chat!"))

    # After a few seconds, reset presence
    await asyncio.sleep(7)
    await bot.change_presence(activity=None)  # or set a default like Game("Ready to chat!"))
    
def get_memory_channel():
    return bot.get_channel(MEMORY_CHAN_ID)

async def load_memory_from_channel():
    channel = get_memory_channel()
    if not channel:
        return
    try:
        await memory.load_history(bot, channel.id)  # just once
    except Exception as e:
        print(f"[Load Error] {e}")

async def save_memory_to_channel():
    channel = get_memory_channel()   # no await
    if not channel:
        return
    for guild_id, guild_data in memory.data.items():
        for channel_id, users in guild_data.items():
            for user_id, entries in users.items():
                for entry in entries:
                    emotion = entry.get("emotion", "neutral")
                    log = (
                        f"[{entry['timestamp']}] | Server name: {entry['guild_name']}, ID: ({entry['guild_id']}) | "
                        f"Channel name: {entry['channel_name']}, ID: ({entry['channel_id']}) | "
                        f"User: {entry['username']} ({entry['user_id']}) | "
                        f"Role: {entry['role']} | {entry['content']} | {emotion}"
                    )
                    await channel.send(log)
                    await asyncio.sleep(0.1)  # rate-limit safe

async def get_monika_context(channel: discord.abc.Messageable, limit: int = 20):
    """
    Fetch recent conversation context for Monika.
    - Includes Monika's messages, user messages, and friend bots.
    - Adds relationship + role tags for users.
    - Adds personality + relationship tags for Monika.
    - Skips irrelevant chatter and system events.
    - Collects attachments with readable markers.
    Returns newest 'limit' entries as a list (oldest → newest).
    """
    context = []

    guild = getattr(channel, "guild", None)
    monika_member = getattr(guild, "me", None) if guild else None

    async for message in channel.history(limit=500, oldest_first=False):
        if message.type != discord.MessageType.default:
            continue
        if not message.content and not message.attachments:
            continue

        entry = None

        # --- Monika’s messages ---
        if monika_member and message.author.id == monika_member.id:
            author_label = "Monika"

            personality_tag = None
            relationship_tag = None

            if guild:
                for role in monika_member.roles:
                    if role.name.startswith("Personality - "):
                        personality_tag = role.name.replace("Personality - ", "").strip()
                    if role.name.startswith(f"{bot.user.name} - "):
                        relationship_tag = role.name.replace(f"{bot.user.name} - ", "").strip()

            entry = {
                "author": author_label,
                "content": message.content or "",
                "timestamp": message.created_at.isoformat()
            }
            if personality_tag:
                entry["personality"] = personality_tag
            if relationship_tag:
                entry["relationship"] = relationship_tag

        # --- Human users / friend bots ---
        elif (not message.author.bot) or is_friend_bot(message) or bot.user.mentioned_in(message):
            author_label = message.author.display_name
            relationship_tag = None

            if guild:
                member = guild.get_member(message.author.id)
                if member:
                    rel_roles = [r for r in member.roles if r.name.startswith(f"{bot.user.name} - ")]
                    if rel_roles:
                        relationship_tag = rel_roles[0].name.replace(f"{bot.user.name} - ", "").strip()
                    else:
                        top_role = next((r for r in reversed(member.roles) if r.name != "@everyone"), None)
                        relationship_tag = top_role.name if top_role else None

            entry = {
                "author": author_label,
                "content": message.content or "",
                "timestamp": message.created_at.isoformat()
            }
            if relationship_tag:
                entry["relationship"] = relationship_tag

        else:
            continue  # skip irrelevant chatter

        # --- Add attachments ---
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
    """Load memories by scanning recent history across all guilds."""
    for guild in bot.guilds:
        for channel in guild.text_channels:
            try:
                perms = channel.permissions_for(guild.me)
                if not perms.read_message_history or not perms.read_messages:
                    continue  # skip channels we can’t read

                async for msg in channel.history(limit=200, oldest_first=True):
                    if msg.author.bot:
                        continue
                    memory.add_entry(
                        guild_id=guild.id,
                        guild_name=guild.name,
                        channel_id=channel.id,
                        channel_name=channel.name,
                        user_id=msg.author.id,
                        username=msg.author.display_name,
                        role="user",
                        content=msg.content,
                        emotion="neutral"  # can be replaced later
                    )
            except Exception as e:
                print(f"[WARN] Could not load history for {channel} in {guild}: {e}")

# async def load_memories_from_DMs():
#     """Load memories by scanning recent history across all guilds."""
#     for guild in bot.guilds:
#         for channel in guild.text_channels:
#             try:
#                 perms = channel.permissions_for(guild.me)
#                 if not perms.read_message_history or not perms.read_messages:
#                     continue  # skip channels we can’t read

#                 async for msg in channel.history(limit=200, oldest_first=True):
#                     if msg.author.bot:
#                         continue
#                     memory.add_entry(
#                         guild_id=None,
#                         guild_name=None,
#                         channel_id=None,
#                         channel_name=None,
#                         user_id=msg.author.id,
#                         username=msg.author.display_name,
#                         role="user",
#                         content=msg.content,
#                         emotion="neutral"  # can be replaced later
#                     )
#             except Exception as e:
#                 print(f"[WARN] Could not load history for {channel} in {guild}: {e}")

async def on_startup():
    print("[Startup] Loading Monika’s memory...")

    # 1. Try restoring from memory channel backup
    channel = get_memory_channel()
    if channel:
        try:
            async for message in channel.history(limit=200, oldest_first=True):
                for attachment in message.attachments:
                    if attachment.filename.startswith("monika_memory_backup_") and attachment.filename.endswith(".txt"):
                        data = await attachment.read()
                        await memory.import_from_text(data.decode("utf-8"))
                        print(f"[Startup] Restored from {attachment.filename}")
                        return  # stop here if successful
        except Exception as e:
            print(f"[Startup WARN] Failed to load from memory channel: {e}")

    # 2. If no backup found → scan guilds
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
    bot.loop.create_task(idlechat_loop())
    asyncio.create_task(monika_idle_conversation_task())

def translate_to_english(text: str) -> str:
    from deep_translator import GoogleTranslator
    """Translate any text into English before saving logs."""
    try:
        return GoogleTranslator(source='auto', target='en').translate(text)
    except Exception as e:
        print(f"[Translation] Failed to translate: {e}")
        return text

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

@bot.event
async def on_sleeping(reason: str = "Taking a nap..."):
    """Triggered when the bot goes into sleep mode."""
    try:
        bot.is_sleeping = True  # prevent replies

        print(f"[Sleep] 😴 Entering sleep mode. Reason: {reason}")

        # Save memory
        asyncio.create_task(save_memory_to_channel())
        await server_tracker.save(bot, channel_id=SERVER_TRACKER_CHAN)

        # Change presence
        await bot.change_presence(status=discord.Status.idle,
                                  activity=discord.Game("I'm going to take a nap..."))
        await asyncio.sleep(5)
        await bot.change_presence(status=discord.Status.idle,
                                  activity=discord.Game("💤 ZZZ... zzz... zzzz..."))

        # Auto-pick a text channel for notifying
        status_channel = next((c for c in bot.get_all_channels()
                               if isinstance(c, discord.TextChannel)
                               and c.permissions_for(c.guild.me).send_messages), None)
        if status_channel:
            await status_channel.send(f"😴 The bot is now sleeping. Reason: **{reason}**")

    except Exception as e:
        print(f"[Sleep] ⚠️ Error during sleep event: {e}")


@bot.event
async def on_message(message: discord.Message):
    # 1. Safety checks
    if message.author.bot:
        return
    
    # Ignore other bots (unless they're "friend bots")
    if message.author.bot and not is_friend_bot(message):
        return

    # 2. Report channel handling (staff reply to reports)
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
                    print(f"[Report Edit Error] {e}")

                # DM reporter with reply
                dm_embed = discord.Embed(
                    title="📩 Reply to Your Report",
                    description=message.content,
                    color=discord.Color.blurple(),
                    timestamp=discord.utils.utcnow()
                )
                dm_embed.set_footer(text=f"From {message.author}")
                try:
                    await reporter.send(embed=dm_embed)
                except discord.Forbidden:
                    await message.channel.send("❌ Could not DM reporter.", delete_after=10)

                await message.add_reaction("✅")
                await message.delete(delay=2)  # keep channel clean
                break

        # Don’t run further Monika responses here, just process commands
        await bot.process_commands(message)
        return

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

    # 8. Guild handler
    if isinstance(message.channel, discord.DMChannel):
        guild = None
        username = message.author.name
        monika_member = None  # No guild roles in DMs
        avatar_url = message.author.display_avatar.url
        await handle_dm_message(message, avatar_url)
        print(f"[Mention] in the DM's: Detected from {message.author.display_name}")
    else:
        guild = message.guild
        username = message.author.display_name
        monika_member = guild.get_member(bot.user.id)
        await handle_guild_message(message, avatar_url)
        print(f"[Mention] in the server's: Detected from {message.author.display_name}")

    if bot.is_sleeping:
        return  # ignore all messages while asleep

    # 9. Finally let commands through
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

async def handle_dm_message(message: discord.Message, avatar_url: str = None):
    """Handle DM messages safely (no mentions, DM-specific personality/relationship)."""
    user = message.author
    user_id = str(user.id)

    # --- Track user ---
    user_tracker.track_user(user.id, user.display_name, user.bot)
    avatar_url = user_tracker.get_avatar(user.id)

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
                monika_DMS = clean_monika_reply(content, bot.user.id, user.display_name)
                emotion = await user_sprites.classify(monika_DMS)
                sprite_link = await get_sprite_link(emotion, get_time_based_outfit())
    except Exception as e:
        print(f"[DM OpenAI Error] {e}")

    # --- Fallbacks ---
    if not monika_DMS or not emotion or emotion not in user_sprites.valid:
        print(f"[WARN] Falling back for DM → emotion={emotion}, reply={monika_DMS}")
        monika_DMS = random.choice(error_messages)
        emotion = "error"
        sprite_link = await error_emotion() or user_sprites.error_sprite

    # --- Clean reply ---
    monika_DMS = clean_monika_reply(monika_DMS, bot.user.id, user.display_name)
    monika_DMS = re.sub(r"<@!?\d+>", "", monika_DMS)

    # --- Send reply ---
    reply = f"{monika_DMS}\n[{emotion}]({sprite_link})"
    await message.author.send(reply)

    # --- Logging ---
    if DM_LOGS_CHAN:
        forward_channel = bot.get_channel(DM_LOGS_CHAN)
        if forward_channel:
            translated_msg = translate_to_english(message.content)
            await forward_channel.send(
                f"**From {user} in DM:**\n"
                f"Original: {message.content}\n"
                f"English: {translated_msg}\n"
                f"**Reply:** {monika_DMS}"
            )
            
async def handle_guild_message(message: discord.Message, avatar_url: str):
    """Handle messages inside guilds with personality/relationship context."""
    global last_reply_times

    guild = message.guild
    user_id = str(message.author.id)
    user = message.author
    guild_id = str(guild.id) if guild else "DM"
    guild_name = guild.name
    channel_id = str(message.channel.id)
    channel_name = message.channel.name
    username = user.display_name
    is_friend = is_friend_bot(message)

    # --- Track user ---
    try:
        await user_tracker.save(bot, channel_id=USER_TRACKER_CHAN)
        await server_tracker.save(bot, channel_id=SERVER_TRACKER_CHAN)
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

    if is_broadcasting is True:
        await message.send("please wait until the Announcement are done.")
        message.delete(delay=2)
        return

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
                emotion = await user_sprites.classify(monika_reply)
                sprite_link = await get_sprite_link(emotion, get_time_based_outfit())
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

    if not guild or message.channel.permissions_for(message.guild.me).send_messages:
        async with message.channel.typing():
            print(f"{reply}")
            await asyncio.sleep(1.5)
            await message.channel.send(reply)
            if isinstance(emoji, discord.Emoji):
                await emoji.delete()  # optional cleanup
    else:
        print(f"[Error] No permission to send in #{message.channel.name}")

    # --- Memory logging ---
    if MEMORY_CHAN_ID:
        dest_channel = bot.get_channel(MEMORY_CHAN_ID)
        if dest_channel:
            try:
                timestamp = datetime.datetime.utcnow().isoformat()
                if user_id and username:
                    header = f"📩 `[{timestamp}]` | `User: {username} ({user_id})` | "
                elif user.bot or is_friend:
                    header = f"📩 `[{timestamp}]` | `Bot: {user.bot}`| `emotion: {emotion}` | "
                body = f"`Server: {guild_name} ({guild_id})` | `Channel: {channel_name} ({channel_id})` | \n**Reply:** {monika_reply}"
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
    global last_user_interaction

    while not bot.is_closed():
        if not idle_chat_enabled:
            await asyncio.sleep(600)
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

            # Get relationship info
            relationship = server_tracker.get_relationship_type(str(guild.id))

            # Game-aware conversation
            monika_result = await monika_idle_presences(chosen_user, relationship)

            if monika_result:
                monika_message, is_private = monika_result
                if is_private:
                    try:
                        await chosen_user.send(monika_message)
                        print(f"[IdleChat -> DM {chosen_user.display_name}] {monika_message}")
                    except discord.Forbidden:
                        await channel.send(monika_message)
                else:
                    async with channel.typing():
                        await asyncio.sleep(2)
                        await channel.send(monika_message)
                        print(f"[IdleChat -> {guild.name}] {monika_message}")

            else:
                monika_member = guild.get_member(bot.user.id)
                personalities, normal_rel, sexual_rel = extract_roles(monika_member, chosen_user)

                # Get idle lines from both relationship types
                personality_lines = await Idlechat_personality(chosen_user, personalities)
                relationship_lines = []
                if normal_rel:
                    relationship_lines += await Idlechat_relationships(chosen_user, normal_rel)
                if sexual_rel:
                    relationship_lines += await Idlechat_relationships(chosen_user, sexual_rel)

                idle_lines = personality_lines + relationship_lines
                if not idle_lines:
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
                            await channel.send(random_dialogue)
                    if not MON_CHANNEL_NAMES:
                        async with channel.typing():
                            await asyncio.sleep(2)
                            await channel.send(random_dialogue)

                # Update last reply time
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

    admin_cmds = []
    user_cmds = []

    for command in bot.tree.get_commands():
        # Skip hidden commands
        if command.name in hidden_cmds:
            continue

        # Check if the command has permission checks (like admin)
        if any("has_permissions" in str(check) for check in getattr(command, "checks", [])):
            admin_cmds.append(f"`* /{command.name} *` – {command.description or 'No description'}")
        else:
            user_cmds.append(f"`* /{command.name} *` – {command.description or 'No description'}")

    embed = discord.Embed(
        title="✒️ Need a little help?",
        description="Hi there! Here’s what you can ask me to do. Don’t be shy, okay?\n",
        color=discord.Color.green()
    )

    if admin_cmds:
        embed.add_field(name="🔧 Admin Commands", value="\n".join(admin_cmds), inline=False)
    if user_cmds:
        embed.add_field(name="💬 User Commands", value="\n".join(user_cmds), inline=False)

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

    if outfit not in ["school_uniform", "casual 1", "casual 2", "casual 3", "white dress", "hoodie", "pajamas", "white summer dress", "green dress"]:
        await interaction.response.send_message(
            "❌ Invalid outfit. Options are: school_uniform, casual's, white dress, hoodie, pajamas.",
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
    HIDDEN_IF_LESBIAN = {"Boyfriend", "Girlfriend", "Significant Others"}
    HIDDEN_IF_STRAIGHT = {"Girlfriend (Lesbian)", "Significant Others"}
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

@bot.tree.command(
    name="broadcast", 
    description="Send an announcement to all servers/channels Monika can speak in."
)
@commands.is_owner()
@discord.app_commands.describe(title="Title of the announcement", message="Body text of the announcement", color_hex="Optional hex color (e.g. 15f500)")
async def broadcast(
    interaction: discord.Interaction,
    title: str,
    message: str,
    color_hex: str = "15f500"
):
    global is_broadcasting
    user = interaction.user
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("❌ You can't use this command.", ephemeral=True)
        return
    
    is_broadcasting = True
    await bot.change_presence(activity=discord.Game("📣 Announcement in progress..."))

    if is_broadcasting == True:
        await interaction.response.send_message(
            "❌ A broadcast is already in progress.",
            ephemeral=True
        )
        return

    # ✅ Reset broadcast flags so every server is eligible again
    for gid in server_tracker.guilds:
        server_tracker.guilds[gid]["last_broadcast"] = False
    await server_tracker.save(bot, channel_id=SERVER_TRACKER_CHAN)

    wait_minutes = 3
    update_interval = 30

    try:
        try:
            color_int = int(color_hex, 16)
            color = discord.Color(color_int)
        except ValueError:
            color = discord.Color.pink()

        embed = discord.Embed(
            title=title,
            description=message,
            color=color
        )
        embed.set_footer(text="If like this change pick: '✅' if not pick: '❌', thank you and have good rest of your day. And if you come across any errors, bugs, idea's, or Complaint. you can use `/report`.")

        global last_broadcast_guilds
        sent_messages = []
        success_count = 0
        failure_count = 0

        for guild in bot.guilds:
            gid = str(guild.id)
            server_tracker.ensure_guild(gid)

            # ✅ Skip if already broadcasted
            if server_tracker.guilds[gid].get("last_broadcast", False):
                continue

            channel = None
            if guild.system_channel and guild.system_channel.permissions_for(guild.me).send_messages:
                channel = guild.system_channel
            else:
                for c in guild.text_channels:
                    if c.permissions_for(guild.me).send_messages:
                        channel = c
                        break

            if not channel:
                print(f"[Broadcast] ❌ No available channel in {guild.name} ({guild.id})")
                failure_count += 1
                continue

            try:
                msg = await channel.send(embed=embed)
                await msg.add_reaction("✅")
                await msg.add_reaction("❌")

                progress = await channel.send("⏳ Collecting reactions...")

                sent_messages.append((msg, progress))
                success_count += 1

                # ✅ Save to tracker
                server_tracker.ensure_guild(str(guild.id))
                server_tracker.guilds[str(guild.id)]["last_broadcast"] = True
                await server_tracker.save(bot, channel_id=SERVER_TRACKER_CHAN)

                print(f"[Broadcast] ✅ Sent announcement to {guild.name} ({guild.id}) in #{channel.name}")
                await asyncio.sleep(0.5)
            except discord.Forbidden:
                print(f"[Broadcast Error] Forbidden in {guild.name} ({guild.id})")
                failure_count += 1
            except Exception as e:
                print(f"[Broadcast Error] in {guild.name} ({guild.id}): {e}")
                failure_count += 1

        # --- Periodic updates ---
        elapsed = 0
        while elapsed < wait_minutes * 60:
            for orig, progress in sent_messages:
                try:
                    refreshed = await orig.channel.fetch_message(orig.id)
                    likes = dislikes = 0
                    for reaction in refreshed.reactions:
                        if str(reaction.emoji) == "✅":
                            likes = reaction.count
                            if bot.user in [u async for u in reaction.users()]:
                                likes -= 1
                        elif str(reaction.emoji) == "❌":
                            dislikes = reaction.count
                            if bot.user in [u async for u in reaction.users()]:
                                dislikes -= 1

                    await progress.edit(content=f"✅ {likes} | ❌ {dislikes} (updating...)")
                except Exception as e:
                    print(f"[Broadcast Update Error] {e}")

            await asyncio.sleep(update_interval)
            elapsed += update_interval

        # --- Final pass + totals ---
        like_total = 0
        dislike_total = 0

        for orig, progress in sent_messages:
            try:
                refreshed = await orig.channel.fetch_message(orig.id)
                likes = dislikes = 0
                for reaction in refreshed.reactions:
                    if str(reaction.emoji) == "✅":
                        likes = reaction.count
                        if bot.user in [u async for u in reaction.users()]:
                            likes -= 1
                    elif str(reaction.emoji) == "❌":
                        dislikes = reaction.count
                        if bot.user in [u async for u in reaction.users()]:
                            dislikes -= 1

                like_total += max(likes, 0)
                dislike_total += max(dislikes, 0)
                await progress.edit(content=f"✅ {likes} | ❌ {dislikes} (final)")
            except Exception as e:
                print(f"[Broadcast Fetch Error] {e}")

        # Final owner summary
        await interaction.followup.send(
            f"✅ Broadcast finished.\n"
            f"Sent successfully to **{success_count}** servers.\n"
            f"⚠️ Failed in **{failure_count}** servers.\n\n"
            f"✅ Likes: **{like_total}**\n"
            f"❌ Dislikes: **{dislike_total}**",
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

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    import traceback
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

keepalive.keep_alive()
async def main():
    await bot.start(TOKEN, reconnect=True)

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
