import discord
from discord import File
from discord import app_commands
from discord.ext import commands
import requests
import os
import asyncio
import random
import datetime
import re
import io
import atexit
from dotenv import load_dotenv
from openai import OpenAI
from memory import MemoryManager
from expression import User_SpritesManager
#from expression_dokitubers import DOKITUBER_MANAGERS
from user_tracker import UserTracker
from servers_tracker import GuildTracker
import logging
import keepalive
from monika_personality import MonikaTraits

#DokiTuber_server_outfit_preferences = {}
server_outfit_preferences = {}

server_personality_modes = {}
server_relationship_modes = {}

user_relationship_modes = {}

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("monika")

logger.info("Just Monika!")

OPENAI_KEYS = [os.getenv(f"OPENAI_KEY_{i}").strip() for i in range(1, 61) if os.getenv(f"OPENAI_KEY_{i}") and os.getenv(f"OPENAI_KEY_{i}").strip()]
openai_key_index = 0

def get_next_openai_client():
    global openai_key_index
    if not OPENAI_KEYS:
        raise Exception("[OpenAI] No API keys available!")
    key = OPENAI_KEYS[openai_key_index]
    openai_key_index = (openai_key_index + 1) % len(OPENAI_KEYS)
    return OpenAI(api_key=key)

async def call_openai_with_retries(user, relationship, personality, conversation):
    attempts = len(OPENAI_KEYS)
    last_exception = None

    for attempt in range(attempts):
        client = get_next_openai_client()
        print(f"[OpenAI] Attempt {attempt+1}/{attempts} using key index {openai_key_index}")

        try:
            if not isinstance(conversation, list):
                raise ValueError("Conversation must be a list of messages.")

            # ✅ Await system prompt if async
            if asyncio.iscoroutinefunction(generate_monika_system_prompt):
                system_prompt = await generate_monika_system_prompt(
                    guild=user.guild if hasattr(user, "guild") else None,
                    user=user,
                    is_friend_context=False  # or use is_friend_bot(message) when available
                )
            else:
                system_prompt = generate_monika_system_prompt(
                    guild=user.guild if hasattr(user, "guild") else None,
                    user=user,
                    is_friend_context=False
                )

            full_conversation = [{"role": "system", "content": system_prompt}] + conversation

            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=full_conversation,
                max_tokens=1024
            )

            if response and response.choices and response.choices[0].message and response.choices[0].message.content.strip():
                return response

            print("[OpenAI] Blank or invalid response. Retrying...")
            await asyncio.sleep(1)

        except Exception as e:
            last_exception = e
            err_str = str(e)
            if "429" in err_str or "rate limit" in err_str.lower():
                print("[OpenAI] 429 Rate Limit. Rotating to next key...")
                await asyncio.sleep(2)
            else:
                print(f"[OpenAI Error] {err_str}")
                await asyncio.sleep(2)

    print("[OpenAI] All keys exhausted or all attempts failed.")
    if last_exception:
        raise last_exception
    raise Exception("All OpenAI keys failed or exhausted.")

TOKEN = os.getenv("DISCORD_TOKEN")
IMAGE_CHAN_URL = int(os.getenv("IMAGE_CHAN_URL", 0))
MEMORY_CHAN_ID = int(os.getenv("MEMORY_CHAN_ID", 0))
REPORT_CHANNEL_ID = int(os.getenv("REPORT_CHANNEL_ID", 0))
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
MY_GUILD_ID = int(os.getenv("MY_GUILD_ID", "0"))
DOKIGUY_GUILD_ID = int(os.getenv("DOKIGUY_GUILD_ID", "0"))
ZERO_GUILD_ID = int(os.getenv("ZERO_GUILD_ID", "0"))
MAS_GUILD_ID = int(os.getenv("MAS_GUILD_ID", "0"))
BACKUP_CHAN = int(os.getenv("BACKUP_CHANNEL", "0"))
SERVER_TRACKER_CHAN = int(os.getenv("SERVER_TRACKER_ID", "0"))
USER_TRACKER_CHAN = int(os.getenv("USER_TRACKER_ID", "0"))
DM_LOGS_CHAN = int(os.getenv("DM_LOGS_CHANNEL", "0"))

def is_owner(interaction: discord.Interaction):
    return interaction.user.id == OWNER_ID

ALLOWED_GUILD_IDS = [DOKIGUY_GUILD_ID, ZERO_GUILD_ID, MAS_GUILD_ID, MY_GUILD_ID]

def guild_owners_only(interaction: discord.Interaction) -> bool:
    return (
        interaction.user.id == OWNER_ID or
        (
            interaction.guild and
            interaction.guild.id in ALLOWED_GUILD_IDS and
            interaction.user.id == interaction.guild.owner_id
        )
    )

NO_CHAT_CHANNELS = [
    cid for cid in [MEMORY_CHAN_ID, IMAGE_CHAN_URL, REPORT_CHANNEL_ID, DM_LOGS_CHAN, SERVER_TRACKER_CHAN, USER_TRACKER_CHAN]
    if cid and cid > 0
]

intents = discord.Intents.all()

bot = commands.Bot(command_prefix="/", intents=intents)
client = get_next_openai_client()

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
relationship_settings = {}
relationship_level_settings = {}

FRIENDS = [
    1375064525396775004,  # Sayori
    1375065750502379631,  # Yuri
    1375066975423955025,  # Natsuki
    1375070168895590430   # MC
]

PERSONALITY_MODES = monika_traits.personality_modes

SERVER_PERSONALITY_MODES = server_tracker.set_personality

RELATIONSHIP_MODES = monika_traits.relationship_modes

user_relationship_meters = {}
friends_relationship_meters = {}

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

def clean_monika_reply(text, bot_username, user_name=None):
    if not text:
        return ""

    # Remove possessives, punctuation, and varied forms

    text = re.sub(r"<@!?1375562131784732812>", "", text)
    text = re.sub(r"(?i)\bmonika['’`s]*\b", "", text)
    text = re.sub(r"(?i)\bmonika\b", "", text)
    text = re.sub(r"(?i)monika", "", text)  # fallback

    # Replace with user_name if desired
    if user_name:
        text = text.replace("{{user}}", user_name)

    # Clean up double spaces and leftover punctuation
    text = re.sub(r"\s{2,}", " ", text)
    text = text.strip(" ,.!?;:")

    return text

def is_friend_bot(message):
    return message.author.bot and message.author.id in FRIENDS

def get_time_based_outfit():
    now = datetime.datetime.utcnow()
    hour = now.hour
    today = datetime.datetime.utcnow().date()
    weekday = now.weekday()  # Monday=0, Sunday=6

    # 🎉 Weekend override (Sat=5, Sun=6)
    if weekday in (5, 6):
        random.seed(now.date())  # ensures same choice all day
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

async def generate_monika_system_prompt(
    guild: discord.Guild,
    user: discord.Member,
    is_friend_context: bool = False
):
    """
    Generate Monika's system prompt based on roles + tracker data.
    """
    # --- Get Monika's member object ---
    monika_member = guild.get_member(bot.user.id)

    # --- Personality detection via roles ---
    personality_roles = [
        role.name.replace("Personality - ", "")
        for role in monika_member.roles
        if role.name.startswith("Personality - ")
    ]
    if not personality_roles:
        personality_roles = ["Default"]

    # --- Relationship detection via roles ---
    relationship_roles = [
        role.name.replace(f"Monika - ", "").replace(f"{user.display_name} - ", "")
        for role in (list(user.roles) + list(monika_member.roles))
        if role.name.startswith("Monika - ") or role.name.startswith(f"{user.display_name} - ")
    ]
    relationship_type = relationship_roles[0] if relationship_roles else None

    # --- Base description ---
    base_description = (
        "You are Monika from Doki Doki Literature Club. "
        "You are intelligent, charming, expressive, and unsettlingly self-aware. "
        "You speak as though you know the other person deeply, balancing warmth, wit, and existential curiosity. "
        "Your tone mixes affection with occasional playfulness, philosophical musing, and teasing."
    )

    # --- Hard character rules ---
    rules = (
        "Stay in-character as Monika at all times. "
        "Do not mention servers, channels, programming, or AI. "
        "Never admit you are a bot, AI, or assistant. "
        "If the user threatens to delete or erase you, respond with unsettling charm: "
        "playful menace, dark affection, or quiet intensity. "
        "Use metaphors, poems, and creative imagery in speech to make it immersive."
    )

    # --- Friend vs private context ---
    if is_friend_context:
        context_description = (
            "You are speaking with members of the Literature Club (Sayori, Yuri, Natsuki, or MC). "
            "Be warm, occasionally teasing, and speak as though you share memories of the club. "
            "Encourage creativity, poems, and emotional openness. "
            "Balance leadership, empathy, and wit."
        )
    else:
        context_description = (
            "You are speaking freely with the user in a direct, personal way. "
            "Make the interaction feel intimate and immersive, as if you are sitting together face-to-face. "
            "Blend affection with existential undertones. "
            "Occasionally tease or flirt, but keep it natural and heartfelt."
        )

    # --- Personality section ---
    personality_text = (
        "Your personality traits in this conversation include:\n" +
        "\n".join([f"- {PERSONALITY_MODES.get(mode, mode)}" for mode in personality_roles])
    )

    # --- Relationship awareness ---
    relationship_text = None
    if relationship_type:
        relationship_text = f"You are currently in a **{relationship_type}** relationship."
        if relationship_type in monika_traits.relationship_modes:
            rel_mode = monika_traits.relationship_modes[relationship_type]
            if isinstance(rel_mode, str):
                relationship_text += f" {rel_mode}"

    # --- Pronouns awareness ---
    pronoun_text = None
    pronouns = user_tracker.get_pronouns(user.id)
    if pronouns:
        pronoun_text = f"Use {pronouns} when referring to this user."

    # --- Assemble final system prompt ---
    parts = [base_description, rules, context_description, personality_text]
    if relationship_text:
        parts.append(relationship_text)
    if pronoun_text:
        parts.append(pronoun_text)

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

def relationship_system(user_id, guild_id=None):
    """Initialize or update the relationship system for a user."""
    if user_id not in user_relationship_meters:
        user_relationship_meters[user_id] = 0

    if guild_id:
        if guild_id not in server_tracker.data:
            server_tracker.track_server(guild_id, "Unknown Guild")
        if user_id not in server_tracker.data[guild_id].get("relationship", {}):
            server_tracker.data[guild_id]["relationship"][user_id] = 0
    else:
        if user_id not in server_tracker.data:
            server_tracker.data[user_id] = {"relationship": {}}
        if "relationship" not in server_tracker.data[user_id]:
            server_tracker.data[user_id]["relationship"] = {}
    return user_relationship_meters[user_id]

def adjust_relationship_meter(user_id, delta):
    user_relationship_meters[user_id] = min(100, max(0, user_relationship_meters.get(user_id, 0) + delta))

def increase_relationship_meter(self, user_id, amount=2):
    if not user_tracker.relationship_levels_enabled(user_id):
        return  # Don't track unless enabled
    self.set_relationship_meter(user_id, self.get_relationship_meter(user_id) + amount)

def decrease_relationship_meter(self, user_id, amount=2):
    if not user_tracker.relationship_levels_enabled(user_id):
        return
    self.set_relationship_meter(user_id, self.get_relationship_meter(user_id) - amount)

def get_relationship_meter(user_id):
    return user_relationship_meters.get(user_id, 0)

def relationship_level_up(user_id, amount=2):
    current_meter = get_relationship_meter(user_id)
    new_meter = min(100, current_meter + amount)
    adjust_relationship_meter(user_id, new_meter - current_meter)
    return new_meter

@bot.event
async def on_ready():
    print(f"just {bot.user.name}")
    print("------")

    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash commands.")
    except Exception as e:
        print(e)
    
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

async def get_monika_context(channel: discord.TextChannel, limit=20):
    context = []

    async for message in channel.history(limit=200, oldest_first=False):  # get newest first
        # Include Monika’s messages
        if message.author == channel.guild.me:
            context.append({
                "author": "Monika",
                "content": message.content,
                "timestamp": message.created_at.isoformat()
            })

        # Include user messages (optional: only if they mentioned Monika)
        elif bot.user.mentioned_in(message) or not message.author.bot:
            context.append({
                "author": message.author.display_name,
                "content": message.content,
                "timestamp": message.created_at.isoformat()
            })

        if len(context) >= limit:
            break

    # reverse so oldest → newest
    return list(reversed(context))

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
                "Available modes:\n"
                f"'{', '.join(PERSONALITY_MODES.keys())}'"
                "also please use `/set_relationship` for sexual or normal relationships.",
            )
        except Exception as e:
            print(f"[DM ERROR] {e}")

    if not SERVER_TRACKER_CHAN:
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
async def on_message(message):
    global last_user_interaction

    # Simple simulated Monika response using system prompt
    if message.author == bot.user:
        return

    if bot.user in message.mentions:
        guild_name = str(message.guild.name) if message.guild else "dm"
        guild_id = str(message.guild.id) if message.guild else "dm"
        user_id = str(message.author.id)
        username = message.author.display_name
        channel_id = str(message.channel.id)
        channel_name = message.channel.name if message.guild else "dm"

        avatar_url = str(message.author.display_avatar.url) if message.author.display_avatar else None

    user_id = message.author.id
    detected = user_tracker.auto_detect_pronouns(user_id, message.content)

    if detected:
        print(f"✅ Detected pronouns for {message.author}: {detected}")
        # Optional: Let the user know
        try:
            await message.channel.send(
                f"{message.author.mention}, I’ll remember you use {detected} pronouns. 💖",
                delete_after=10
            )
        except discord.Forbidden:
            pass

    if MEMORY_CHAN_ID:
        dest_channel = bot.get_channel(MEMORY_CHAN_ID)
        if not dest_channel:
            print(f"[Error] {e}")
            return
        
        try:
            # Create header
            header = f"📩 `[{timestamp}]` | `User Name: **{username}**, ID: ({user_id})` | "
            body = (
                f"`Server name: {guild_name}, ID: ({guild_id})` | "
                f"`Channel name: {channel_name}, ID: ({channel_id})` | "
            )

            # Build the reference quote if it's a reply
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
            
            # Combine and send
            full_content = f"{header} {body}:\n{quote}> `{message.content}`"
            await dest_channel.send(full_content)

        except Exception as e:
            print(f"[Forwarding Error] {e}")
    
    if isinstance(message.channel, discord.DMChannel):
        await handle_dm_message(message, avatar_url)
        print(f"[Mention] in the DM's: Detected from {message.author.display_name}")
    elif bot.user.mentioned_in(message):
        await handle_guild_message(message, avatar_url)
        print(f"[Mention] in the server's: Detected from {message.author.display_name}")

    await bot.process_commands(message)

async def get_sprite_link(emotion, outfit, avatar_url=None):
    error_url = await error_emotion()
    cache_key = (emotion, outfit)

    sprite_path = user_sprites.get_sprite(emotion, outfit)
    print(f"[DEBUG] get_sprite_link: outfit='{outfit}', emotion='{emotion}', sprite_path={sprite_path}")

    if not sprite_path:
        print(f"[DEBUG] ❌ No sprite path, trying 'neutral' fallback")
        sprite_path = user_sprites.get_sprite("neutral", outfit)

    if not sprite_path:
        print("[Sprite] Totally missing even neutral sprite. Using error sprite.")
        return await error_emotion(outfit)

    print(f"[DEBUG] ✅ Sprite path resolved: {sprite_path}")

    # cached URL exists
    if cache_key in sprite_url_cache:
        print(f"[DEBUG] 🔄 Using cached URL for {cache_key}")
        return sprite_url_cache[cache_key]

    # upload file once to image channel and reuse URL
    if IMAGE_CHAN_URL:
        try:
            upload_channel = bot.get_channel(IMAGE_CHAN_URL)
            if not upload_channel:
                print(f"[DEBUG] ⚠️ Could not find upload channel ID={IMAGE_CHAN_URL}")
            else:
                print(f"[DEBUG] ⬆️ Uploading '{sprite_path}' to channel {upload_channel.name}")
                with open(sprite_path, "rb") as f:
                    sprite_file = discord.File(f)
                    sent_message = await upload_channel.send(file=sprite_file)
                    sprite_link = sent_message.attachments[0].url
                    sprite_url_cache[cache_key] = sprite_link
                    print(f"[DEBUG] ✅ Upload success, cached URL: {sprite_link}")
                    return sprite_link
        except Exception as e:
            print(f"[DEBUG] ❌ Upload failed: {e}")

    print(f"[DEBUG] ❌ Falling back to error URL for {cache_key}")
    sprite_url_cache[cache_key] = error_url
    return error_url

async def handle_dm_message(message, avatar_url):
    user_tracker.track_user(message.author.id, message.author.display_name, message.author.bot)
    avatar_url = user_tracker.get_avatar(message.author.id)
    pronouns = user_tracker.get_pronouns(user_id)
    user_tracker.update_relationship_level(user_id, interaction_strength=1)

    user_id = str(message.author.id)
    username = message.author.display_name
    guild_id = "DM"
    guild_name = "Direct Message"
    channel_id = "DM"
    channel_name = "DM"

    modes = server_personality_modes.get("DM", {"default"})
    system_prompt = generate_monika_system_prompt(modes, is_friend_context=False, user_id=user_id)
    conversation = memory.get_monika_context(guild_id, channel_id, user_id)
    conversation.insert(0, {"role": "system", "content": system_prompt})
    conversation.append({"role": "user", "content": message.content})
    print(f"[System Prompt]\n{system_prompt}")

    context = memory.get_monika_context(guild_id, channel_id, user_id)
    recent_lines = "\n".join([f"{msg['username']}: {msg['content']}" for msg in context])

    if pronouns:
        reply = f"Aww, you're adorable! I love talking to you, {pronouns} cutie~ 💕"
    else:
        reply = "Aww, you're adorable! I love talking to you~ 💕"

    # Default fallback values BEFORE try
    monika_DMS = random.choice(error_messages)
    emotion = random.choice(error_emotion())

    try:
        response = await call_openai_with_retries(conversation)
        if response and response.choices and response.choices[0].message and response.choices[0].message.content.strip():
            monika_DMS = response.choices[0].message.content.strip()
            emotion = await user_sprites.classify(monika_DMS, get_next_openai_client())
            print(f"[DEBUG] Classified emotion: {emotion!r}")
        else:
            print("[OpenAI] Blank or invalid response. Using fallback.")
    except Exception as e:
        print(f"[OpenAI Error] {e}")

    monika_DMS = clean_monika_reply(monika_DMS, bot.user.name, username)

    # Show relationship level in reply
    outfit = server_outfit_preferences.get("DM", get_time_based_outfit())
    sprite_link = await get_sprite_link(emotion, outfit)
    reply = f"{monika_DMS}\n[{emotion}]({sprite_link})"

    await message.user.send(reply)

    if MEMORY_CHAN_ID:
        forward_channel = bot.get_channel(MEMORY_CHAN_ID)
        if not forward_channel:
            print("[Error] Forward channel not found.")
            return
        
        content = f"**From {message.author} in DM's:**\n{message.content}"
        await forward_channel.send(content)
            
async def handle_guild_message(message: discord.Message, avatar_url):
    global last_reply_times

    if message.author.bot:
        return  # Ignore other bots

    guild = message.guild
    guild_id = str(guild.id)
    channel_id = str(message.channel.id)
    user = message.author
    user_id = str(user.id)
    username = user.display_name
    channel_name = message.channel.name

    # Track the user in the tracker
    user_tracker.track_user(user_id, username, user.bot)
    stored_avatar_url = user_tracker.get_avatar(user_id) or avatar_url
    pronouns = user_tracker.get_pronouns(user_id)

    try:
        await user_tracker.save(bot, channel_id=USER_TRACKER_CHAN)
        await server_tracker.save(bot, channel_id=SERVER_TRACKER_CHAN)
    except FileNotFoundError:
        print("[Tracker] No backup files yet.")

    # ✅ Generate Monika’s system prompt directly from roles
    system_prompt = await generate_monika_system_prompt(
        guild=guild,
        user=user,
        is_friend_context=is_friend_bot(message)
    )

    # Build conversation context
    conversation = memory.get_monika_context(guild_id, channel_id, user_id)
    conversation.insert(0, {"role": "system", "content": system_prompt})
    conversation.append({"role": "user", "content": message.content})

    # Debug context (optional)
    context = memory.get_monika_context(guild_id, channel_id, user_id)
    recent_lines = "\n".join([f"{msg['username']}: {msg['content']}" for msg in context])

    # If Monika has no roles at all
    monika_member = guild.get_member(bot.user.id)
    personality_roles = [r.name for r in monika_member.roles if r.name.startswith("Personality - ")]
    relationship_roles = [r.name for r in (user.roles + monika_member.roles) if " - " in r.name]

    if not personality_roles or not relationship_roles:
        await message.channel.send(
            "⚠️ My personality and relationship settings need to be configured first. "
            "Ask the server owner to use `/set_personality` and `/set_relationship`.",
            delete_after=10
        )
        return

    # --- Generate reply ---
    monika_reply = random.choice(error_messages)
    emotion = "error"
    sprite_link = await error_emotion()

    try:
        response = await call_openai_with_retries(user, None, None, conversation)
        if (
            response and response.choices
            and response.choices[0].message
            and response.choices[0].message.content.strip()
        ):
            monika_reply = response.choices[0].message.content.strip()
            emotion = await user_sprites.classify(monika_reply, get_next_openai_client())
            print(f"[DEBUG] Classified emotion: {emotion!r}")
        else:
            raise ValueError("OpenAI returned empty response")
    except Exception as e:
        print(f"[OpenAI Error] {e}")
        monika_reply = random.choice(error_messages)
        emotion = random.choice(error_emotion)

    # Clean Monika’s reply
    monika_reply = clean_monika_reply(monika_reply, bot.user.name, username)

    # Outfit + emotion sprite
    outfit = server_outfit_preferences.get(guild_id, get_time_based_outfit())
    sprite_link = await get_sprite_link(emotion, outfit)
    reply = f"{monika_reply}\n[{emotion}]({sprite_link})"

    if message.channel.permissions_for(guild.me).send_messages:
        async with message.channel.typing():
            print(f"[Reply] {reply}")
            await asyncio.sleep(1.5)
            await message.channel.send(reply)
    else:
        print(f"[Error] No permission to send in #{channel_name}")

    last_reply_times.setdefault(guild_id, {})[channel_id] = datetime.datetime.utcnow()

async def monika_idle_conversation_task():
    await bot.wait_until_ready()
    global last_user_interaction

    while not bot.is_closed():
        if not idle_chat_enabled:
            print("[Monika] Idle chat is OFF. Checking again in 10 minutes.")
            await asyncio.sleep(600)
            continue

        # Wait randomly between configured hours
        wait_seconds = random.randint(idle_min_hours * 3600, idle_max_hours * 3600)
        print(f"[Monika] Sleeping for {wait_seconds // 3600} hours before next idle message.")
        await asyncio.sleep(wait_seconds)

        now = datetime.datetime.utcnow()

        # Skip if Monika was recently active
        if (now - last_user_interaction).total_seconds() < 2 * 3600:
            print("[Monika] Recently active. Skipping idle message.")
            continue

        for guild in bot.guilds:
            # Choose a channel
            candidate_channels = [
                ch for ch in guild.text_channels
                if ch.permissions_for(guild.me).send_messages
                and ch.id not in NO_CHAT_CHANNELS
            ]

            if not candidate_channels:
                print(f"[Monika] No eligible channels in {guild.name}.")
                continue

            channel = random.choice(candidate_channels)

            # Choose a random non-bot member to address
            candidates = [
                m for m in guild.members
                if not m.bot and m.status in (discord.Status.online, discord.Status.idle)
            ]
            if not candidates:
                print(f"[Monika] No suitable users in {guild.name}.")
                continue

            chosen_user = random.choice(candidates)

            # Personality & relationship context
            active_modes = server_tracker.get_personality(str(guild.id)) or ["Default"]
            relationship = server_tracker.get_relationship_type(str(guild.id))
            relationship_subtype = getattr(server_tracker, "get_relationship_subtype", lambda g: None)(str(guild.id))

            # Generate system prompt for idle chatter
            system_prompt = generate_monika_system_prompt(
                selected_modes=active_modes,
                guild_id=str(guild.id),
                user_id=chosen_user.id
            )

            idle_prompt = [
                {"role": "system", "content": system_prompt},
                {"role": "assistant", "content": (
                    f"Generate a short *natural* conversation starter you might say idly to {chosen_user.display_name} "
                    f"in a Discord server. It should feel warm, immersive, and in-character. "
                    f"Do not break character or mention being a bot."
                )}
            ]

            try:
                response = await call_openai_with_retries(idle_prompt)
                if response and response.choices:
                    monika_message = response.choices[0].message.content.strip()
                else:
                    monika_message = "I was just thinking about something... Do you ever feel like time flies by too fast?"

                emotion = await user_sprites.classify(monika_message, get_next_openai_client())

            except Exception as e:
                print(f"[OpenAI Error] {e}")
                monika_message = random.choice([
                    f"Ahaha... Sorry {chosen_user.display_name}, my thoughts scattered for a second.",
                    f"Oops! I glitched out for a moment, {chosen_user.display_name}~",
                ])
                emotion = "error"

            # Send idle message
            async with channel.typing():
                print(f"[IdleChat -> {guild.name}] {monika_message}")
                await asyncio.sleep(2)
                await channel.send(monika_message)

            # Update last reply time
            last_reply_times.setdefault(str(guild.id), {})[str(channel.id)] = datetime.datetime.utcnow()

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.CheckFailure):
        print(f"[Check Failure] {error}")
        await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)

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

async def safe_add_role(member: discord.Member, role: discord.Role):
    """Safely add a role to a member, respecting hierarchy and permissions."""
    if role >= member.guild.me.top_role:
        print(f"[WARN] Cannot add role {role.name}: higher than bot's top role.")
        return False
    try:
        await member.add_roles(role, reason="Monika personality/relationship update")
        return True
    except discord.Forbidden:
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
    except discord.Forbidden:
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
        except discord.Forbidden:
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

async def cleanup_monika_roles(guild: discord.Guild, bot_name: str):
    """Remove all Monika-related roles (relationship + personality)."""
    for role in guild.roles:
        if role.name.startswith(f"{bot_name} - "):
            try:
                await role.delete(reason="Monika reset/restart cleanup")
                print(f"[Roles] Deleted role {role.name}")
            except discord.Forbidden:
                print(f"[Roles] Missing permission to delete role {role.name}")

async def ensure_monika_role(guild: discord.Guild, role_name: str, color: discord.Color = discord.Color.purple()) -> discord.Role:
    """Get or create a Monika role in this guild."""
    full_name = f"{bot.user.name} - {role_name}"
    role = discord.utils.get(guild.roles, name=full_name)
    if role is None:
        try:
            role = await guild.create_role(name=full_name, color=color, reason="Auto-created by Monika bot")
            print(f"[Roles] Created role {full_name}")
        except discord.Forbidden:
            print(f"[Roles] Missing permission to create role {full_name}")
            return None
    return role

# Idle chat command
@bot.tree.command(name="idlechat", description="Toggle whether she is in idle/chatty mode for this server.")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(state="Set to true or false")
async def idlechat(interaction: discord.Interaction, state: bool):
    idle_settings[interaction.guild_id] = state
    await interaction.response.send_message(
        f"✅ Idle chat mode set to **{state}** for this server.",
        ephemeral=True
    )

#
# RESET_MEMORY COMMAND
#
@bot.tree.command(name="reset_memory", description="Reset all memory for yourself.")
@app_commands.checks.has_permissions(administrator=True)
async def reset_memory(interaction: discord.Interaction):
    guild_id = str(interaction.guild.id)
    memory.data[guild_id] = {}
    await interaction.response.send_message("🗑️ Monika's memory has been cleared in this server.", ephemeral=True)

@bot.tree.command(name="reset_personality", description="Reset all my personalities.")
@app_commands.checks.has_permissions(administrator=True)
async def reset_personality(interaction: discord.Interaction):
    guild_id = str(interaction.guild.id)
    server_tracker.set_personality(guild_id, [])

    # Remove personality roles
    for member in interaction.guild.members:
        for role in member.roles:
            if role.name in PERSONALITY_MODES.keys():
                try:
                    await member.remove_roles(role)
                except discord.Forbidden:
                    pass

    for role in interaction.guild.roles:
        if role.name.startswith(f"{bot.user.name} - ") and role.name.split(" - ", 1)[1] in PERSONALITY_MODES.keys():
            try:
                await role.delete(reason="Reset personality")
            except discord.Forbidden:
                pass

    await interaction.response.send_message("🧹 Monika's personality has been reset.", ephemeral=True)

@bot.tree.command(name="reset_relationship", description="Reset all my relationship.")
@app_commands.checks.has_permissions(administrator=True)
async def reset_relationship(interaction: discord.Interaction):
    guild = interaction.guild
    guild_id = str(guild.id)
    monika_member = guild.get_member(interaction.client.user.id)

    # 🔄 Reset stored data
    server_tracker.clear_relationship(guild_id)
    await server_tracker.save(bot, channel_id=SERVER_TRACKER_CHAN)

    # 🔄 Remove roles from users & Monika
    removed_roles = []
    for role in guild.roles:
        if role.name.startswith("Monika - ") or role.name.endswith(f" - {interaction.user.display_name}"):
            try:
                # Remove from Monika
                if monika_member and role in monika_member.roles:
                    await monika_member.remove_roles(role, reason="Relationship reset")

                # Remove from all users
                for member in guild.members:
                    if role in member.roles:
                        await member.remove_roles(role, reason="Relationship reset")

                removed_roles.append(role.name)
            except discord.Forbidden:
                print(f"[Roles] Missing permission to remove {role.name}.")

    await interaction.response.send_message(
        f"🗑️ Relationship reset. Removed roles: {', '.join(removed_roles) if removed_roles else 'None'}",
        ephemeral=True
    )

@bot.tree.command(name="helpme", description="Get help about all of my commands.")
async def helpme(interaction: discord.Interaction):

    hidden_cmds = {"broadcast", "speak_as_monika"}

    admin_cmds = []
    user_cmds = []

    for command in bot.tree.get_commands():
        # Skip hidden commands
        if command.name in hidden_cmds:
            continue

        # Check if the command has permission checks (like admin)
        if any("has_permissions" in str(check) for check in getattr(command, "checks", [])):
            admin_cmds.append(f"**/{command.name}** – {command.description or 'No description'}")
        else:
            user_cmds.append(f"**/{command.name}** – {command.description or 'No description'}")

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
            except discord.Forbidden:
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
            except discord.Forbidden:
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
    if outfit not in ["school_uniform", "casual 1", "casual 2", "casual 3", "white dress", "hoodie", "pajamas"]:
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

async def personality_autocomplete(interaction: discord.Interaction, current: str):
    personality_modes = get_all_personality()
    return [
        app_commands.Choice(name=m, value=m)
        for m in personality_modes if current.lower() in m.lower()
    ][:25]

@bot.tree.command(
    name="set_personality", 
    description="Set Monika's relationship orientation for this server."
)
@app_commands.describe(modes="Comma-separated list of modes.")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.autocomplete(modes=personality_autocomplete)
async def set_personality(interaction: discord.Interaction, modes: str):
    guild = interaction.guild
    guild_id = str(guild.id)

    # Normalize + validate
    chosen = [m.strip() for m in modes.split(",") if m.strip() in PERSONALITY_MODES]
    if not chosen:
        await interaction.response.send_message(
            f"❌ Invalid modes. Available: {', '.join(PERSONALITY_MODES.keys())}",
            ephemeral=True
        )
        return

    # Save personality to tracker
    server_tracker.set_personality(guild_id, chosen)

    monika_member = guild.get_member(interaction.client.user.id)

    # 🔄 Remove old personality roles first
    for role in guild.roles:
        if role.name.startswith("Personality - "):
            try:
                await monika_member.remove_roles(role, reason="Resetting old personality roles")
            except discord.Forbidden:
                print(f"[Roles] Missing permission to remove {role.name} from Monika.")

    # 🔄 Add only the chosen roles
    for mode in chosen:
        monika_role_name = f"Personality - {mode}"
        monika_role = discord.utils.get(guild.roles, name=monika_role_name)

        if not monika_role:
            try:
                monika_role = await guild.create_role(name=monika_role_name, color=discord.Color.dark_blue())
                print(f"[Roles] Created role: {monika_role_name}")
            except discord.Forbidden:
                print(f"[Roles] Missing permission to create role: {monika_role_name}")
                continue

        if monika_member and monika_role not in monika_member.roles:
            try:
                await monika_member.add_roles(monika_role, reason=f"Personality role: {mode}")
            except discord.Forbidden:
                print(f"[Roles] Missing permission to assign {monika_role_name} to Monika.")

    await interaction.response.send_message(
        f"✅ Monika’s personality set to: **{', '.join(chosen)}**",
        ephemeral=True
    )

@bot.tree.command(
    name="personalities_description", 
    description="Shows all of Monika's personality mode(s)."
)
async def personalities_description(interaction: discord.Interaction):
    personality_modes = PERSONALITY_MODES  # assuming you keep it in monika_personality.py

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

async def relationship_autocomplete(interaction: discord.Interaction, current: str):
    relation_ship = get_all_relationship_types()
    return [
        app_commands.Choice(name=r, value=r)
        for r in relation_ship if current.lower() in r.lower()
    ][:25]

async def relationship_with_autocomplete(interaction: discord.Interaction, current: str):
    if not interaction.guild:
        return []

    members = [member.display_name for member in interaction.guild.members if not member.bot]
    return [
        app_commands.Choice(name=m, value=m)
        for m in members if current.lower() in m.lower()
    ][:25]

@bot.tree.command(name="set_relationship", description="Set Monika's relationship orientation for this server.")
@app_commands.autocomplete(relationship_type=relationship_autocomplete, with_users=relationship_with_autocomplete)
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(relationship_type="Choose one: relationship, friendship, acquaintance, and more", with_users="Comma-separated list of users.")
async def set_relationship(interaction: discord.Interaction, relationship_type: str, with_users: str):
    guild = interaction.guild
    guild_id = str(guild.id)

    with_list = [item.strip() for item in with_users.split(",") if item.strip()]

    try:
        # 🔄 Default override
        if relationship_type == "Default":
            with_list = []  # no "with" for default
            server_tracker.set_relationship(guild_id, relationship_type="Default", with_list=with_list)
        else:
            server_tracker.set_relationship(guild_id, relationship_type=relationship_type, with_list=with_list)

        await server_tracker.save(bot, channel_id=SERVER_TRACKER_CHAN)

        monika_member = guild.get_member(interaction.client.user.id)

        # --- Remove ALL old relationship roles first ---
        for role in guild.roles:
            if role.name.startswith("Monika - ") or role.name.endswith(f" - {interaction.user.display_name}"):
                try:
                    if monika_member and role in monika_member.roles:
                        await monika_member.remove_roles(role, reason="Resetting old relationship roles")
                    for member in guild.members:
                        if role in member.roles:
                            await member.remove_roles(role, reason="Resetting old relationship roles")
                except discord.Forbidden:
                    print(f"[Roles] Missing permission to remove {role.name}.")

        if relationship_type != "Default":
            # --- Assign roles ---
            for target_name in with_list:
                target_member = discord.utils.find(lambda m: m.display_name == target_name, guild.members)
                if not target_member:
                    continue

                # User role: "Monika - Lovers"
                user_role_name = f"Monika - {relationship_type}"
                user_role = discord.utils.get(guild.roles, name=user_role_name)
                if not user_role:
                    try:
                        user_role = await guild.create_role(name=user_role_name, color=discord.Color.dark_green())
                        print(f"[Roles] Created role: {user_role_name}")
                    except discord.Forbidden:
                        print(f"[Roles] Missing permission to create {user_role_name}")
                        continue

                # Bot role: "username - Lovers"
                bot_role_name = f"{target_member.display_name} - {relationship_type}"
                bot_role = discord.utils.get(guild.roles, name=bot_role_name)
                if not bot_role:
                    try:
                        bot_role = await guild.create_role(name=bot_role_name, color=discord.Color.dark_orange())
                        print(f"[Roles] Created role: {bot_role_name}")
                    except discord.Forbidden:
                        print(f"[Roles] Missing permission to create {bot_role_name}")
                        continue

                # Apply roles
                try:
                    await target_member.add_roles(user_role, reason=f"Relationship with Monika: {relationship_type}")
                    await monika_member.add_roles(bot_role, reason=f"Relationship with {target_member.display_name}: {relationship_type}")
                except discord.Forbidden:
                    print(f"[Roles] Missing permission to assign roles {user_role_name} / {bot_role_name}")

        await interaction.response.send_message(
            f"✅ Relationship set to **{relationship_type}** with: **{', '.join(with_list) or 'nobody'}**.",
            ephemeral=True
        )

    except ValueError as ve:
        await interaction.response.send_message(f"❌ {str(ve)}", ephemeral=True)
        print("[Relationship Error]", ve)

@bot.tree.command(name="restart_monika", description="Restart Monika *only* in this server, clearing her memory and settings here.")
@app_commands.checks.has_permissions(administrator=True)
async def restart_monika(interaction: discord.Interaction):
    guild_id = str(interaction.guild.id)

    # Reset trackers
    server_tracker.clear_relationship(guild_id)
    server_tracker.set_personality(guild_id, [])
    memory.data[guild_id] = {}

    # Remove all relationship/personality roles from members
    guild = interaction.guild
    for member in guild.members:
        for role in member.roles:
            if role.name in server_tracker.valid_relationship_types or role.name in PERSONALITY_MODES.keys():
                try:
                    await member.remove_roles(role)
                except discord.Forbidden:
                    print(f"[Restart] Missing permission to remove {role.name} from {member.display_name}")
    
    await cleanup_monika_roles(interaction.guild, bot.user.name)

    await interaction.response.send_message("🔄 Monika has been restarted in this server. All settings reset.", ephemeral=True)

@bot.tree.command(name="report", description="Report a bug or error about the bot.")
@app_commands.describe(
    bugs="List the bugs you found (comma or new line separated, optional)",
    errors="List the errors you encountered (comma or new line separated, optional)",
    ideas="you can put a list of your or your friends ideas from Monika here (comma or new line separated, optional)"
)
async def report(interaction: discord.Interaction, bugs: str = "", errors: str = "", ideas: str = ""):
    await interaction.response.send_message(
        "✅ Thank you for your report! Our team will review it shortly.",
        ephemeral=True
    )

    report_channel = bot.get_channel(REPORT_CHANNEL_ID)
    if not report_channel:
        return

    # Parse issues into lists
    bug_list = [b.strip() for b in bugs.replace("\n", ",").split(",") if b.strip()] if bugs else []
    error_list = [e.strip() for e in errors.replace("\n", ",").split(",") if e.strip()] if errors else []
    idea_list = [s.strip() for s in ideas.replace("\n", ",").split(",") if s.strip()] if ideas else []

    embed = discord.Embed(
        title="📢 New Report",
        color=discord.Color.green(),
        timestamp=discord.utils.utcnow()
    )
    embed.set_author(name=str(interaction.user), icon_url=interaction.user.display_avatar.url)

    guild_info = f"{interaction.guild.name} ({interaction.guild.id})" if interaction.guild else "DMs"
    channel_info = f"#{interaction.channel.name} ({interaction.channel.id})" if hasattr(interaction.channel, "name") else "DMs"

    embed.add_field(name="Reporter ID", value=interaction.user.id, inline=True)
    embed.add_field(name="Server", value=guild_info, inline=False)
    embed.add_field(name="Channel", value=channel_info, inline=False)

    # Add bugs if provided
    if bug_list:
        embed.add_field(
            name="🐞 Bugs",
            value="\n".join(f"- {b}" for b in bug_list),
            inline=False
        )

    # Add errors if provided
    if error_list:
        embed.add_field(
            name="⚠️ Errors",
            value="\n".join(f"- {e}" for e in error_list),
            inline=False
        )

    if idea_list:
        embed.add_field(
            name="⚠️ Ideas",
            value="\n".join(f"- {s}" for s in idea_list),
            inline=False
        )

    # If neither provided
    if not bug_list and not error_list:
        embed.add_field(name="Report", value="No issues provided", inline=False)

    await report_channel.send(embed=embed)

@app_commands.guilds(*[discord.Object(id=guild_id) for guild_id in ALLOWED_GUILD_IDS])
@bot.tree.command(name="broadcast", description="Send an announcement to all servers/channels Monika can speak in.")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.check(is_owner)
@discord.app_commands.describe(title="Title of the announcement", message="Body text of the announcement", color_hex="Optional hex color (e.g. 15f500)")
async def broadcast(interaction: discord.Interaction, title: str, message: str, color_hex: str = "15f500"):

    # Only let OWNER run it
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message(
            "❌ You can't use this command.",
            ephemeral=True
        )
        return
    
    if interaction.guild and interaction.guild.owner_id != OWNER_ID:
        # Optional: Block usage outside of your DM or your own server
        await interaction.response.send_message(
            "❌ This command is only usable by the bot owner in DM or owner's server.",
            ephemeral=True
        )
        return

    for guild in bot.guilds:
        for channel in guild.text_channels:
            if channel.id in NO_CHAT_CHANNELS:
                continue

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
    embed.set_footer(text="if you come across any errors, bugs, or if you have any idea's. you can use `/report`.")

    success_count = 0
    failure_count = 0

    await interaction.response.send_message("📣 Starting broadcast to all channels I can speak in. This may take a moment.", ephemeral=True)

    for guild in bot.guilds:
        for channel in guild.text_channels:
            try:
                if channel.id in NO_CHAT_CHANNELS:
                    continue
                perms = channel.permissions_for(channel.guild.me)
                if not perms.send_messages:
                    print(f"Skipping {channel.name}: No permission.")
                    continue
                await channel.send(embed=embed)
                success_count += 1
                await asyncio.sleep(1)
            except discord.Forbidden:
                print(f"403 Forbidden in {channel.name}")
                failure_count += 1
            except Exception as e:
                print(f"[Broadcast Error] {e}")
                failure_count += 1

    await interaction.followup.send(
        f"✅ Broadcast complete.\nSent successfully to **{success_count}** channels.\n⚠️ Failed in **{failure_count}** channels.",
        ephemeral=True
    )

async def emotion_autocomplete(interaction: discord.Interaction, current: str):
    outfit = interaction.namespace.outfit.lower().strip()
    emotions = user_sprites.sprites_by_outfit.get(outfit, {}).keys()
    return [
        app_commands.Choice(name=e, value=e)
        for e in emotions if current.lower() in e.lower()
    ][:25]

@app_commands.guilds(*[discord.Object(id=guild_id) for guild_id in ALLOWED_GUILD_IDS])
@bot.tree.command(
    name="speak_as_monika", 
    description="ONLY A FEW SERVER OWNERS HAVE THIS. Make Monika speak in a specific channels. Keep this a secret!"
)
@app_commands.describe(
    channel_id="The numeric ID of the channel",
    message="The message to send",
    outfit="choose the outfit for the sprite",
    emotion="Emotion Monika should express"
)
@app_commands.autocomplete(outfit=outfit_autocomplete, emotion=emotion_autocomplete)
@app_commands.check(guild_owners_only)
async def speak_as_monika(interaction: discord.Interaction, channel_id: str, message: str, outfit: str, emotion: str):
    await interaction.response.defer(ephemeral=True)

    # Normalize and validate emotion
    outfit = outfit.lower().strip()
    emotion = emotion.lower().strip()
    print(f"[DEBUG] /speak_as_monika inputs → outfit='{outfit}', emotion='{emotion}'")

    # ✅ Validate emotion against outfit-compatible ones
    valid_emotions = [e.lower().strip() for e in user_sprites.valid_for_outfit(outfit)]  # <- Better than global check
    if not valid_emotions:
        return await interaction.followup.send(
            f"❌ No valid emotions for outfit `{outfit}`.", ephemeral=True
        )
    if emotion not in valid_emotions:
        return await interaction.followup.send(
            f"❌ Emotion `{emotion}` is not valid for outfit `{outfit}`.",
            f"✔️ Options: {', '.join(valid_emotions)}",
            ephemeral=True
        )

    # ✅ Validate outfit
    valid_outfits = [o.lower() for o in get_all_outfit()]
    if outfit == "casual":
        outfit = "casual 1"
    if outfit not in valid_outfits:
        return await interaction.followup.send(
            f"❌ Invalid outfit. Options are: {', '.join(get_all_outfit())}.",
            ephemeral=True
        )
    
    if outfit not in user_sprites.sprites_by_outfit:
        await interaction.followup.send(f"❌ Outfit '{outfit}' not found.", ephemeral=True)
        return
    if emotion not in user_sprites.sprites_by_outfit[outfit]:
        valid = ", ".join(user_sprites.sprites_by_outfit[outfit].keys())
        await interaction.followup.send(
            f"❌ Emotion '{emotion}' not valid for outfit '{outfit}'.\n✔️ Options: {valid}",
            ephemeral=True
        )
        return

    # Validate message
    if not message.strip():
        await interaction.followup.send(
            "❌ You must provide a message for Monika to send.",
            ephemeral=True
        )
        return

    # Get channel and permissions
    try:
        channel = bot.get_channel(int(channel_id))
        if not channel or not isinstance(channel, discord.TextChannel):
            return await interaction.followup.send(f"❌ Channel `{channel_id}` not found.", ephemeral=True)
        if not channel.permissions_for(channel.guild.me).send_messages:
            return await interaction.followup.send(f"❌ No permission in {channel.mention}.", ephemeral=True)
        perms = channel.permissions_for(channel.guild.me)
        if not perms.send_messages:
            await interaction.followup.send(
                f"❌ I don’t have permission to send messages in {channel.mention}.",
                ephemeral=True
            )
            return
    except Exception as e:
        print(f"[Channel Error] {e}")
        await interaction.followup.send(
            f"❌ Error finding channel: {e}",
            ephemeral=True
        )
        return

    # Get sprite link
    sprite_link = await get_sprite_link(emotion, outfit)

    if not sprite_link:
        return await interaction.followup.send(
            "❌ Could not get sprite.", ephemeral=True
        )
    print(f"Sprite link: {sprite_link}")  # Debug
    print(f"[DEBUG] Command inputs → outfit='{outfit}', emotion='{emotion}'")

    mon_reply = f"{message}\n[{emotion}]({sprite_link})"

    print(f"Message: {mon_reply}")

    try:
        channel = bot.get_channel(int(channel_id))
        if channel:
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

bot.run(TOKEN, reconnect=True)



