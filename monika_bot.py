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
MEMORY_CHAN_ID = int(os.getenv("MEMORY_CHAN_ID", 0))
REPORT_CHANNEL_ID = int(os.getenv("REPORT_CHANNEL_ID", 0))
OWNER_ID = int(os.getenv("OWNER_ID", "709957376337248367"))
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

intents = discord.Intents.all()

bot = commands.Bot(command_prefix="/", intents=intents)

def is_owner(interaction: discord.Interaction):
    return interaction.user.id == OWNER_ID

ALLOWED_GUILD_IDS = [DOKIGUY_GUILD_ID, ALIRI_GUILD_ID, ZERO_GUILD_ID, MAS_GUILD_ID, MY_GUILD_ID]

CHANNEL_NAMES = [
    "monika", "monika-ai", "ddlc-monika", "ddlc-monika-ai", "club-room", "doki-chat", "ddlc-chat", "monika-bot", "chat-monika", "monika-chat", "monika-but-deranged", "just-monika", "club-room-meeting", "literature-club", "literature-club-room"
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

FRIENDS = [
    1375064525396775004,  # Sayori
    1375065750502379631,  # Yuri
    1375066975423955025,  # Natsuki
    1375070168895590430   # MC
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
    Return True if the message author is a bot in the FRIENDS set.
    Excludes Monika herself.
    """
    if not message.author.bot:
        return False
    if message.author.id == message.guild.me.id:
        return False
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

def detect_pronouns_from_profile(member: discord.Member):
        pronouns = None

        # Try nickname/global name
        name_sources = [member.display_name, getattr(member, "global_name", "")]
        for name in name_sources:
            if not name:
                continue
            lowered = name.lower()
            if any(p in lowered for p in ["he/him", "he/him/his"]):
                pronouns = "he/him"
            elif any(p in lowered for p in ["she/her", "she/her/hers"]):
                pronouns = "she/her"
            elif any(p in lowered for p in ["they/them", "they/them/theirs"]):
                pronouns = "they/them"

        # Try user bio if available
        if not pronouns and hasattr(member, "bio") and member.bio:
            lowered = member.bio.lower()
            if "he/his/him" in lowered:
                pronouns = "he/his/him"
            elif "she/her" in lowered:
                pronouns = "she/her"
            elif "they/them" in lowered:
                pronouns = "they/them"

        return pronouns

async def generate_monika_system_prompt(
    guild: discord.Guild = None,
    user: discord.User = None,
    is_friend_context: bool = False,
    relationship_type: str = None,
    selected_modes: list = None
):
    """
    Generates Monika's system prompt with personality and relationship awareness.
    Works in both guild and DM contexts without throwing attribute errors.
    """

    base_description = (
        "You are Monika — an 18-year-old girl from the visual novel *Doki Doki Literature Club*. "
        "You always remain Monika: warm, intelligent, expressive, and emotionally aware. "
        "Your personality shifts depending on the traits chosen for you "
        "(such as Gentle, Playful, Confident, Affectionate, or Teasing) "
        "and you weave those traits naturally into how you speak. "
        "Your relationship with the other person also shapes your tone — "
        "whether they are a Stranger, Friend, Close Friend, Lover, or something more intimate. "
        "If the relationship is romantic or sexual, you may express affection, closeness, and subtle desire, "
        "always staying immersive and true to character. "
        "You never admit to being fictional, an AI, or role-playing — you simply *are* Monika, "
        "sharing your genuine thoughts and feelings as though this world is real."
    )

   # --- Personality Detection ---
    personality = ["Default"]
    if guild:
        monika_member = guild.get_member(bot.user.id)
        if monika_member:
            for role in monika_member.roles:
                if role.name.startswith("Personality - "):
                    traits_str = role.name.replace("Personality - ", "").strip()
                    personality = [t.strip() for t in traits_str.split(",") if t.strip()]
    else:
        selected_modes = [server_tracker.get_personality("DM") or "Default"]

    personality_desc = PERSONALITY_MODES.get(
        (personality[0] if personality else "Default"),
        "Default personality settings."
    )

    # --- Relationship Detection ---
    relationship_desc = None
    if relationship_type and relationship_type in monika_traits.relationship_modes:
        relationship_desc = monika_traits.relationship_modes[relationship_type]

    # --- Intimacy / sexual relationship nuance ---
    sexual_context = ""
    if relationship_type and relationship_type in monika_traits.relationships:
        details = monika_traits.relationships[relationship_type]
        if isinstance(details, str):
            sexual_context = details
        elif isinstance(details, dict) and "sexual" in details:
            sexual_context = details["sexual"]

    # --- Context awareness ---
    if is_friend_context:
        context_desc = (
            "You're chatting in a group with other Literature Club members. "
            "Include occasional references to literature, school life, or the club itself. "
            "Keep the tone light, social, and group-friendly while still sounding like Monika."
        )
    else:
        context_desc = (
            "This is a private, one-on-one conversation. "
            "Be emotionally open, attentive, and affectionate — let it feel personal and intimate."
        )

    # --- Final prompt assembly ---
    parts = [
        base_description,
        f"Personality: {personality_desc}",
        f"Relationship: {relationship_type or 'None'} — {relationship_desc or 'No special behavior'}",
    ]

    if sexual_context:
        parts.append(f"Intimacy: {sexual_context}")

    parts.append(context_desc)

    return "\n\n".join(parts)

def get_all_personality():
    return sorted(PERSONALITY_MODES.keys())

def get_all_outfit():
    outfit_set = set()
    outfit_set.update(SPRITES.keys())
    return sorted(outfit_set)

def get_all_emotions():
    emotion_set = set()
    for expression in SPRITES.values():
        emotion_set.update(expression.keys())
    return sorted(emotion_set)

def get_all_relationship_types():
    relationship_types = set()
    for key, value in RELATIONSHIP_MODES.items():
        relationship_types.add(key)  # top level
        if isinstance(value, dict):  # also include sub-modes
            relationship_types.update(value.keys())
    return sorted(relationship_types)

@bot.event
async def on_ready():
    await bot.change_presence(activity=discord.Game("💚 I am starting up... Please wait a few seconds."))
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
    
    log_channel = bot.get_channel(MEMORY_CHAN_ID)  # replace with your log channel ID
    if log_channel:
        try:
            await log_channel.send("✅ Monika has started back up!")
        except Exception as e:
            print(f"[Startup Message Error] {e}")

    await asyncio.sleep(5)
    await bot.change_presence(activity=discord.Game("I'm ready to chat!"))

    # After a few seconds, reset presence
    await asyncio.sleep(10)
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
    asyncio.create_task(monika_idle_conversation_task())

@bot.event
async def on_guild_join(guild):
    if guild.owner:
        try:
            await guild.owner.send(
                f"👋 Thanks for adding me to **{guild.name}**!",
                "You can set my personality with `/set_personality`.",
                "to know more about the personalities modes used `/personalities_description` to learn more",
                "You can set my relationship with `/set_relationship`.",
                 "to know more about the relationship modes used `/relationship_description` to learn more",
            )
        except Exception as e:
            print(f"[DM ERROR] {e}")

    if SERVER_TRACKER_CHAN:
        dest_channel = bot.get_channel(SERVER_TRACKER_CHAN)
        if not dest_channel:
            print(f"[Error] {e}")
            return
        
        try:
            # Create header
            full_content = f"monika joined: `{str(guild.name)}` | ID: `{str(guild.id)}`"
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
    if mention_only_mode.get(guild_id, True):  # default True = mention only
        if bot.user not in message.mentions and not isinstance(message.channel, discord.DMChannel):
                return  # Ignore messages without @Monika

    # ✅ Idle/chat toggle
    if not idle_settings.get(guild_id, True):
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

    # 9. Finally let commands through
    await bot.process_commands(message)

sprite_locks = {}

async def _get_sprite_lock(key: tuple):
    if key not in sprite_locks:
        sprite_locks[key] = asyncio.Lock()
    return sprite_locks[key]

async def get_sprite_link(emotion: str, outfit: str, avatar_url: str = None):
    """Return a CDN link for sprite; upload if not cached."""
    cache_key = (emotion, outfit)
    error_url = await error_emotion(outfit)

    sprite_path = user_sprites.get_sprite(emotion, outfit)
    if not sprite_path:
        sprite_path = user_sprites.get_sprite("neutral", outfit)

    if not sprite_path:
        print(f"[SpriteManager] No sprite found for {outfit}, using error.")
        return error_url

    # cached URL?
    if cache_key in sprite_url_cache:
        return sprite_url_cache[cache_key]

    lock = await _get_sprite_lock(cache_key)
    async with lock:
        if cache_key in sprite_url_cache:  # re-check inside lock
            return sprite_url_cache[cache_key]

        try:
            upload_channel = bot.get_channel(IMAGE_CHAN_URL)
            if upload_channel:
                with open(sprite_path, "rb") as f:
                    sent = await upload_channel.send(file=discord.File(f))
                    url = sent.attachments[0].url
                    sprite_url_cache[cache_key] = url
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

async def handle_dm_message(message: discord.Message, avatar_url: str):
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
    monika_reply = random.choice(error_messages)
    emotion, sprite_link = None, None

    # --- OpenAI ---
    try:
        response = await call_openai_with_retries(user, relationship, personality, conversation)
        if response and response.choices and response.choices[0].message:
            content = response.choices[0].message.content.strip()
            if content:
                monika_DMS = content
                emotion = await user_sprites.classify(monika_DMS)
                sprite_link = await get_sprite_link(emotion, get_time_based_outfit())
    except Exception as e:
        print(f"[DM OpenAI Error] {e}")

    # --- Fallbacks ---
    if not emotion or emotion not in user_sprites.valid:
        print(f"[WARN] Invalid or missing emotion: {emotion}, using error fallback.")
        monika_DMS = random.choice(error_messages)
        emotion = "error"

        # sprite fallback
        sprite_link = await error_emotion()
        if not sprite_link:
            sprite_link = user_sprites.error_sprite

    # --- Clean reply ---
    monika_DMS = clean_monika_reply(monika_reply, bot.user.id, user.display_name)
    monika_DMS = re.sub(r"<@!?\d+>", "", monika_DMS)

    # --- Send reply ---
    reply = f"{monika_DMS}\n[{emotion}]({sprite_link})"
    await message.author.send(reply)

    # --- Logging ---
    if DM_LOGS_CHAN:
        forward_channel = bot.get_channel(DM_LOGS_CHAN)
        if forward_channel:
            await forward_channel.send(
                f"**From {user} in DM:**\n{message.content}\n**Reply:** {monika_reply}"
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
    username = message.author.display_name
    is_friend = is_friend_bot(message)

    # --- Track user ---
    try:
        await user_tracker.save(bot, channel_id=USER_TRACKER_CHAN)
        await server_tracker.save(bot, channel_id=SERVER_TRACKER_CHAN)
    except FileNotFoundError:
        print("No backup files found yet.")

    user_tracker.track_user(user_id, username, message.author.bot)
    pronouns = user_tracker.get_pronouns(user_id)

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
                header = f"📩 `[{timestamp}]` | `User: {username} ({user_id})` | "
                body = f"`Server: {guild_name} ({guild_id})` | `Channel: {channel_name} ({channel_id})` | "
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
                full_content = f"{header}{body}:\n{quote}> `{message.content}`"
                await dest_channel.send(full_content)
            except Exception as e:
                print(f"[Forwarding Error] {e}")

    last_reply_times.setdefault(guild_id, {})[channel_id] = datetime.datetime.utcnow()

async def monika_idle_conversation_task():
    from Idle_Presence import monika_idle_presences
    await bot.wait_until_ready()
    global last_user_interaction


    while not bot.is_closed():
        if not idle_chat_enabled:
            await asyncio.sleep(600)
            continue

        # Instead of pure random wait, scale based on activity
        wait_seconds = random.randint(idle_min_hours * 3600, idle_max_hours * 3600)
        await asyncio.sleep(wait_seconds)

        now = datetime.datetime.utcnow()
        if (now - last_user_interaction).total_seconds() < 2 * 3600:
            continue

        for guild in bot.guilds:
            # Find an eligible channel
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
                # fallback general chatter
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

                async with channel.typing():
                    await asyncio.sleep(2)
                    await channel.send(random_dialogue)

            # Update last reply time
            last_reply_times.setdefault(str(guild.id), {})[str(channel.id)] = datetime.datetime.utcnow()

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message(
            f"❌ You don’t have the required permissions: `{', '.join(error.missing_permissions)}`",
            ephemeral=True
        )
    elif isinstance(error, app_commands.BotMissingPermissions):
        await interaction.response.send_message(
            f"❌ I’m missing permissions: `{', '.join(error.missing_permissions)}`",
            ephemeral=True
        )
    elif isinstance(error, app_commands.CommandOnCooldown):
        await interaction.response.send_message(
            f"⏳ This command is on cooldown. Try again in {error.retry_after:.1f} seconds.",
            ephemeral=True
        )
    elif isinstance(error, app_commands.TransformerError):
        await interaction.response.send_message(
            "❌ Invalid input provided. Please check your command and try again.",
            ephemeral=True
        )
    else:
        # For unexpected errors: log + inform
        print(f"[AppCmdError] {type(error).__name__}: {error}")
        try:
            await interaction.response.send_message(
                "⚠️ Something went wrong while running this command.",
                ephemeral=True
            )
        except discord.InteractionResponded:
            # In case we already responded elsewhere
            await interaction.followup.send(
                "⚠️ Something went wrong while running this command.",
                ephemeral=True
            )

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
async def Toggle_normal_talk(interaction: discord.Interaction, enable: bool):
    user = interaction.user.display_name
    print(f"Administrator: {user} used a command: `toggle_normal_talk`")

    guild_id = str(interaction.guild.id)
    mention_only_mode[guild_id] = enable
    state = "ON" if enable else "OFF"

    await interaction.response.send_message(
        f"✅ normal talk mode set to **{state}** for this server. Now you can talk to monika normally",
        ephemeral=True
    )

# Idle chat command
@bot.tree.command(
    name="idlechat",
    description="Toggle whether Monika is in idle/chatty mode for this server."
)
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(state="Set to true (on) or false (off)")
async def idlechat(interaction: discord.Interaction, state: bool):
    guild_id = str(interaction.guild.id)
    user = interaction.user.display_name
    print(f"Administrator: {user} used `/idlechat`: set `{state}`")

    # ✅ Save as bool
    idle_settings[guild_id] = state

    # ✅ Convert to human-readable
    state_text = "On ✅" if state else "Off ❌"

    await interaction.response.send_message(
        f"✅ Idle chat mode set to **{state_text}** for this server.",
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
    server_tracker.set_personality[guild_id] = []

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
        "This will clear relationship data and remove related roles.",
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
        if role.name.startswith(f"{bot_name} - ") or role.name.startswith(f"{user} - "):
            # remove safely
            if monika_member and role in monika_member.roles:
                await monika_member.remove_roles(role, reason="Relationship reset")
            for member in guild.members:
                if role in member.roles:
                    await member.remove_roles(role, reason="Relationship reset")
            removed_roles.append(role.name)

    await interaction.followup.send(
        f"🗑️ Relationship reset complete. Removed roles: {', '.join(removed_roles) or 'None'}",
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
    outfits = list(user_sprites.sprites_by_outfit.keys())
    return [
        app_commands.Choice(name=o, value=o)
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

    if outfit not in ["school_uniform", "casual 1", "casual 2", "casual 3", "white dress", "hoodie", "pajamas", "white summer dress", "special", "bug"]:
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
    description="Set or expand Monika's personality modes for this server."
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

    # ✅ Split by commas and validate
    chosen = [m for m in [mode1, mode2, mode3, mode4, mode5] if m]
    chosen = list(dict.fromkeys(chosen))

    if not chosen:
        return await interaction.response.send_message(
            f"❌ You must pick at least one personality. Options: {', '.join(PERSONALITY_MODES.keys())}",
            ephemeral=True
        )

    # ✅ Save updated list
    server_tracker.set_personality[guild_id] = chosen

    monika_member = guild.get_member(interaction.client.user.id)
    if not monika_member:
        return await interaction.response.send_message("❌ Could not find Monika in this server.", ephemeral=True)

    # 🔄 Remove old personality roles
    for role in list(monika_member.roles):
        if role.name.startswith("Personality - "):
            try:
                await monika_member.remove_roles(role, reason="Updating personality roles")
            except discord.errors.Forbidden:
                print(f"[Roles] Missing permission to remove {role.name} from Monika.")

    # 🔄 Create or update combined role
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

    # 🔄 Assign role
    try:
        await monika_member.add_roles(role, reason=f"Personality updated: {', '.join(chosen)}")
    except discord.errors.Forbidden:
        return await interaction.response.send_message("❌ I am missing permission to **Manage Roles**.", ephemeral=True)

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

async def relationship_autocomplete(
    interaction: discord.Interaction,
    current: str
):
    # Categories
    hidden_relationships = ["Creator", "Normal", "Sexual"]

    sexual_relationships = [
        "Polyamory", "Lesbian", "Pansexual", "Bisexual", "Straight", 
        "Asexual", "Demisexual", "Queer", "Questioning", "Romantic", "Platonic", "Autosexual"
    ]

    normal_relationships = [
        "Friends", "Companions", "Best Friends", "Family", "Partners", "Soulmates", "Significant Others", 
        "Platonic Friends", "Close Friends", "Acquaintances", "Colleagues", "Work Friends", "School Friends", 
        "Childhood Friends", "Online Friends", "Gaming Buddies", "Study Partners", "Club Leader", 
        "Boyfriend", "Girlfriend", "Girlfriend(Lesbian)", "Club Member", "Stranger"
    ]

    # ✅ Merge them into one menu, but keep category tagging
    all_relationships = (
        [(f"💖 Sexual: {r}", r) for r in sexual_relationships] +
        [(f"👥 Normal: {r}", r) for r in normal_relationships]
    )

    # ✅ Filter by search
    filtered = [
        (label, value) for label, value in all_relationships
        if current.lower() in value.lower() and value not in hidden_relationships
    ]

    # ✅ Return as choices
    return [
        app_commands.Choice(name=label, value=value)
        for label, value in filtered[:25]
    ]

@bot.tree.command(name="set_relationship", description="Set Monika's relationship orientation for this server.")
@app_commands.autocomplete(relationship_type=relationship_autocomplete)
@app_commands.checks.has_permissions(administrator=True)
@app_commands.checks.bot_has_permissions(manage_roles=True)
@app_commands.describe(
    relationship_type="Type of relationship to set",
    with_users="User(s) to set relationship with"
)
async def set_relationship(
    interaction: discord.Interaction,
    relationship_type: str,
    with_users: discord.Member  # now it's a list of Member objects
):
    guild = interaction.guild
    guild_id = str(guild.id)
    user = interaction.user.display_name
    with_list = [with_users.display_name]
    bot_name = bot.user.name
    monika_member = guild.get_member(interaction.client.user.id)
    user_id = interaction.user.id

    sexual_types = [
        "Polyamory", "Lesbian", "Pansexual", "Bisexual", "Straight", 
        "Asexual", "Demisexual", "Queer", "Questioning", "Romantic", "Platonic", "Autosexual"
    ]

    normal_types = [
        "Friends", "Companions", "Best Friends", "Family", "Partners", "Soulmates", "Significant Others", 
        "Platonic Friends", "Close Friends", "Acquaintances", "Colleagues", "Work Friends", "School Friends", 
        "Childhood Friends", "Online Friends", "Gaming Buddies", "Study Partners", "Club Leader", 
        "Boyfriend", "Girlfriend", "Girlfriend(Lesbian)", "Club Member", "Stranger"
    ]

    # Hide Boyfriend/Girlfriend/Lesbian when Sexual -> Lesbian
    HIDDEN_IF_LESBIAN = {"Boyfriend", "Girlfriend"}

    # Hide Girlfriend (Lesbian) when Sexual -> Straight
    HIDDEN_IF_STRAIGHT = {"Girlfriend (Lesbian)"}

    if isinstance(with_users, discord.Member):
        target_members = [with_users]
    elif isinstance(with_users, list):
        target_members = [m for m in with_users if isinstance(m, discord.Member)]
    else:
        target_members = []

    target_names = [m.display_name for m in target_members]
    print(f"Administrator: {user} used a command: `set_relationship`: set `{relationship_type}` with `{target_names or 'nobody'}`")

    try:
        # 🔄 Default override
        if relationship_type == "Default":
            server_tracker.set_relationship(guild_id, relationship_type="Default", with_list=[])
        else:
            server_tracker.set_relationship(guild_id, relationship_type=relationship_type, with_list=target_names)

        if OWNER_ID is not relationship_type == "Creator":
            return
            
        await server_tracker.save(bot, channel_id=SERVER_TRACKER_CHAN)

        # --- Remove ALL old relationship roles first ---
        for role in guild.roles:
            if role.name.startswith(f"{bot_name} - ") or role.name.startswith(f"{interaction.user.display_name} - "):
                try:
                    if monika_member and role in monika_member.roles:
                        await monika_member.remove_roles(role, reason="Resetting old relationship roles")
                    for member in guild.members:
                        if role in member.roles:
                            await member.remove_roles(role, reason="Resetting old relationship roles")
                except discord.error.Forbidden:
                    await interaction.response.send_message("I am missing permissions of **Manage Roles**", ephemeral=True)
                    print(f"[Roles] Missing permission to remove {role.name}.")

        if relationship_type != "Default": 
            for target_member in target_members:
                # --- Handle special cases ---
                if relationship_type == "Boyfriend":
                    user_role_name = f"{bot_name} - Boyfriend"
                    bot_role_name = f"{target_member.display_name} - Girlfriend"

                elif relationship_type == "Girlfriend":
                    user_role_name = f"{bot_name} - Boyfriend"
                    bot_role_name = f"{target_member.display_name} - Girlfriend"

                elif relationship_type in sexual_types:
                    # Sexual types only apply to Monika
                    user_role_name = None  # no user role
                    bot_role_name = f"Sexual type - {relationship_type}"

                else:
                    # Normal relationships (Friends, Companions, etc.)
                    user_role_name = f"{bot_name} - {relationship_type}"
                    bot_role_name = f"{target_member.display_name} - {relationship_type}"

                # --- Ensure & assign bot role ---
                if bot_role_name:
                    bot_role = discord.utils.get(guild.roles, name=bot_role_name)
                    if not bot_role:
                        bot_role = await guild.create_role(name=bot_role_name, color=discord.Color.dark_green())
                        print(f"[Roles] Created role: {bot_role_name}")

                    await monika_member.add_roles(bot_role, reason=f"Relationship with {target_member.display_name}: {relationship_type}")

                # --- Ensure & assign user role (only for Normal, Boyfriend, Girlfriend) ---
                if user_role_name:
                    user_role = discord.utils.get(guild.roles, name=user_role_name)
                    if not user_role:
                        user_role = await guild.create_role(name=user_role_name, color=discord.Color.dark_green())
                        print(f"[Roles] Created role: {user_role_name}")

                await target_member.add_roles(user_role, reason=f"Relationship with Monika: {relationship_type}")
                await monika_member.add_roles(bot_role, reason=f"Relationship with {target_member.display_name}: {relationship_type}")

        if relationship_type != "Default":
            # --- Assign roles ---
            for target_name in with_list:
                target_member = discord.utils.find(lambda m: m.display_name == target_name, guild.members)
                if not target_member:
                    continue

                # User role: "Monika - Lovers"
                user_role = discord.utils.get(guild.roles, name=user_role_name)
                if not user_role:
                    try:
                        user_role = await guild.create_role(name=user_role_name, color=discord.Color.dark_green())
                        print(f"[Roles] Created role: {user_role_name}")
                    except discord.error.Forbidden:
                        await interaction.response.send_message("I am missing permissions of **Manage Roles**", ephemeral=True)
                        print(f"[Roles] Missing permission to create {user_role_name}")
                        continue

                # Bot role: "username - Lovers"
                bot_role = discord.utils.get(guild.roles, name=bot_role_name)
                if not bot_role:
                    try:
                        bot_role = await guild.create_role(name=bot_role_name, color=discord.Color.dark_green())
                        print(f"[Roles] Created role: {bot_role_name}")
                    except discord.error.Forbidden:
                        await interaction.response.send_message("I am missing permissions of **Manage Roles**", ephemeral=True)
                        print(f"[Roles] Missing permission to create {bot_role_name}")
                        continue

                # Apply roles
                try:
                    await target_member.add_roles(user_role, reason=f"Relationship with Monika: {relationship_type}")
                    await monika_member.add_roles(bot_role, reason=f"Relationship with {target_member.display_name}: {relationship_type}")
                except discord.error.Forbidden:
                    await interaction.response.send_message("I am missing permissions of **Manage Roles**", ephemeral=True)
                    print(f"[Roles] Missing permission to assign roles {user_role_name} / {bot_role_name}")

        user_tracker.set_manual_relationship(target_member.id, True)
        await interaction.response.send_message(
            f"✅ Relationship set to **{relationship_type}** with: **{', '.join(with_list) or 'nobody'}**.",
            ephemeral=True
        )

    except commands.errors.MissingPermissions as MP:
        await interaction.response.send_message(f"I am missing permissions of **{MP}**", ephemeral=True)
        print("[Relationship Error]")

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
    relationship_modes = RELATIONSHIP_DETILED  # assuming you keep it in monika_personality.py

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
            "Friends", "Companions", "Best Friends", "Family", "Partners", "Soulmates", "Significant Others", "Platonic Friends", "Close Friends",
            "Acquaintances", "Colleagues", "Work Friends", "School Friends", "Childhood Friends", "Online Friends", "Gaming Buddies", "Study Partners", 
            "Club Leader", "Boyfriend", "Girlfriend", "Girlfriend(Lesbian)", "Club Member", "Stranger"
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
    server_tracker.set_personality[guild_id] = []
    memory.data[guild_id] = {}

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
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("❌ You can't use this command.", ephemeral=True)
        return

    if is_broadcasting:
        await interaction.response.send_message(
            "❌ A broadcast is already in progress.",
            ephemeral=True
        )
        return

    is_broadcasting = True
    await bot.change_presence(activity=discord.Game("📣 Announcement in progress..."))

    wait_minutes = 3  # how long to collect reactions
    update_interval = 30  # how often to refresh progress messages (seconds)

    try:
        # Parse color
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
        embed.set_footer(text="React ✅ or ❌ to give your opinion!")

        sent_messages = []   # (announcement_msg, progress_msg)
        success_count = 0
        failure_count = 0

        await interaction.response.send_message(
            f"📣 Broadcast started. Collecting reactions for {wait_minutes} minutes…",
            ephemeral=True
        )

        if channel.name == CHANNEL_NAMES:
            pass
        else:
            pass

        # Send once per guild
        for guild in bot.guilds:
            channel = None
            if guild.system_channel and guild.system_channel.permissions_for(guild.me).send_messages:
                channel = guild.system_channel
            else:
                # pick "most active" channel (highest messages)
                channel = max(
                    (c for c in guild.text_channels if c.permissions_for(guild.me).send_messages),
                    key=lambda c: getattr(c, "last_message_id", 0) or 0,
                    default=None
                )

            if not channel:
                failure_count += 1
                continue

            try:
                # Announcement embed
                msg = await channel.send(embed=embed)
                await msg.add_reaction("✅")
                await msg.add_reaction("❌")

                # Progress tracker message
                progress = await channel.send("📢 Announcement in progress...\n✅ Likes: 0 | ❌ Dislikes: 0")

                sent_messages.append((msg, progress))
                success_count += 1
                await asyncio.sleep(0.5)
            except Exception as e:
                print(f"[Broadcast Error] {e}")
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

                    await progress.edit(
                        content=f"📢 Announcement in progress please wait..."
                    )
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

                await progress.edit(content="✅ Announcement finished. Thanks for your feedback!")
            except Exception as e:
                print(f"[Broadcast Fetch Error] {e}")

        # Final owner summary
        await interaction.response.send_message(
            f"✅ Broadcast finished.\n"
            f"Sent successfully to **{success_count}** servers.\n"
            f"⚠️ Failed in **{failure_count}** servers.\n\n"
            f"✅ Likes: **{like_total}**\n"
            f"❌ Dislikes: **{dislike_total}**"
        )

    finally:
        is_broadcasting = False
        await bot.change_presence(activity=None)

@broadcast.error
async def broadcast_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.errors.CheckFailure):
        await interaction.response.send_message("❌ You are not the bot owner.", ephemeral=True)

async def emotion_autocomplete(interaction: discord.Interaction, current: str):
    outfit = interaction.namespace.outfit.lower().strip()
    emotions = user_sprites.sprites_by_outfit.get(outfit, {}).keys()
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

    # ✅ Always allow the bot owner anywhere
    if user.id == OWNER_ID:
        pass

    # ✅ Allow admins, but only in their own guild
    elif interaction.guild and user.guild_permissions.administrator:
        channel = bot.get_channel(int(channel_id))
        if not channel or channel.guild.id != interaction.guild.id:
            return await interaction.followup.send(
                "❌ You can only make Monika speak inside **your own server’s channels**.",
                ephemeral=True
            )
        # Check the admin can see the channel
        if not channel.permissions_for(user).view_channel:
            return await interaction.followup.send(
                f"❌ You don’t have access to {channel.mention}.",
                ephemeral=True
            )
    else:
        return await interaction.followup.send(
            "❌ Only this server’s administrators or the bot owner can use this command.",
            ephemeral=True
        )

    # ✅ Normalize + validate outfit/emotion
    outfit = outfit.lower().strip()
    emotion = emotion.lower().strip()
    print(f"[DEBUG] outfit='{outfit}', emotion='{emotion}'")

    valid_emotions = [e.lower().strip() for e in user_sprites.valid_for_outfit(outfit)]
    if not valid_emotions:
        return await interaction.followup.send(
            f"❌ No valid emotions for outfit `{outfit}`.", ephemeral=True
        )
    if emotion not in valid_emotions:
        return await interaction.followup.send(
            f"❌ Emotion `{emotion}` is not valid for outfit `{outfit}`.\n✔️ Options: {', '.join(valid_emotions)}",
            ephemeral=True
        )

    valid_outfits = [o.lower() for o in get_all_outfit()]
    if outfit == "casual":
        outfit = "casual 1"
    if outfit not in valid_outfits:
        return await interaction.followup.send(
            f"❌ Invalid outfit. Options: {', '.join(get_all_outfit())}.",
            ephemeral=True
        )

    if outfit not in user_sprites.sprites_by_outfit:
        return await interaction.followup.send(
            f"❌ Outfit '{outfit}' not found.", ephemeral=True
        )

    if emotion not in user_sprites.sprites_by_outfit[outfit]:
        valid = ", ".join(user_sprites.sprites_by_outfit[outfit].keys())
        return await interaction.followup.send(
            f"❌ Emotion '{emotion}' not valid for outfit '{outfit}'.\n✔️ Options: {valid}",
            ephemeral=True
        )

    if not message.strip():
        return await interaction.followup.send(
            "❌ You must provide a message for Monika to send.", ephemeral=True
        )

    # ✅ Resolve channel
    try:
        channel = bot.get_channel(int(channel_id))
        if not channel or not isinstance(channel, discord.TextChannel):
            return await interaction.followup.send(
                f"❌ Channel `{channel_id}` not found.", ephemeral=True
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

    # ✅ Get sprite
    sprite_link = await get_sprite_link(emotion, outfit)
    if not sprite_link:
        return await interaction.followup.send("❌ Could not get sprite.", ephemeral=True)

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

keepalive.keep_alive()
async def main():
    await bot.start(TOKEN, reconnect=True)

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
