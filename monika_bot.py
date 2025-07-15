import discord
from discord import app_commands
from discord.ext import commands
import os
import asyncio
import random
import datetime
import re
import io
from dotenv import load_dotenv
from openai import OpenAI
from memory import JsonManager
from logs import LogsManager
from expression import User_SpritesManager
#from expression_dokitubers import ExpressionHandler, DOKITUBER_MANAGERS
from user_tracker import UserTracker
from servers_tracker import GuildTracker
import logging
import keepalive
from monika_personality import MonikaTraits

server_tracker = GuildTracker()
user_tracker = UserTracker()
monika_traits = MonikaTraits()

USER_TRACKER_BACKUP = "users.json"
SERVER_TRACKER_BACKUP = "servers.json"

#DokiTuber_Sprites = {}
server_outfit_preferences = {}

server_personality_modes = {}

user_relationship_modes = {}
friends_relationship_modes = {}

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("monika")

logger.info("Just Monika!")

OPENAI_KEYS = [os.getenv(f"OPENAI_KEY_{i}").strip() for i in range(1, 31) if os.getenv(f"OPENAI_KEY_{i}") and os.getenv(f"OPENAI_KEY_{i}").strip()]
openai_key_index = 0

def get_next_openai_client():
    global openai_key_index
    if not OPENAI_KEYS:
        raise Exception("[OpenAI] No API keys available!")
    key = OPENAI_KEYS[openai_key_index]
    openai_key_index = (openai_key_index + 1) % len(OPENAI_KEYS)
    return OpenAI(api_key=key)

async def call_openai_with_retries(conversation):
    attempts = len(OPENAI_KEYS)
    last_exception = None

    for attempt in range(attempts):
        client = get_next_openai_client()
        print(f"[OpenAI] Attempt {attempt+1}/{attempts} using key index {openai_key_index}")

        try:
            # Make sure the conversation is valid
            if not conversation or not isinstance(conversation, list):
                raise ValueError("Invalid conversation passed to OpenAI. Must be a list of messages.")

            # Call the API
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=conversation,
                max_tokens=1024
            )

            # Sanity check on response
            if response and response.choices and response.choices[0].message and response.choices[0].message.content.strip():
                return response
            print("[OpenAI] Blank or invalid response. Retrying...")
            await asyncio.sleep(1)

        except Exception as e:
            last_exception = e
            err_str = str(e)
            if "429" in err_str or "rate limit" in err_str.lower():
                print("[OpenAI] 429 Rate Limit error detected. Rotating to next key...")
                await asyncio.sleep(2)  # Longer delay to be polite
            else:
                print(f"[OpenAI Error] {err_str}")
                # For other errors, we might want to retry but let's wait a bit
                await asyncio.sleep(2)


    print("[OpenAI] All keys exhausted or all attempts failed.")
    if last_exception:
        raise last_exception
    raise Exception("All OpenAI keys failed or exhausted.")

TOKEN = os.getenv("DISCORD_TOKEN")
IMAGE_CHANNEL_URL = int(os.getenv("IMAGE_CHANNEL_URL", 0))
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", 0))
REPORT_CHANNEL_ID = int(os.getenv("REPORT_CHANNEL_ID", 0))
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
MY_GUILD_ID = int(os.getenv("MY_GUILD_ID", "0"))

NO_CHAT_CHANNELS = [
    cid for cid in [LOG_CHANNEL_ID, IMAGE_CHANNEL_URL, REPORT_CHANNEL_ID]
    if cid and cid > 0
]

intents = discord.Intents.all()

bot = commands.Bot(command_prefix="/", intents=intents)
client = get_next_openai_client()

json_memory = JsonManager(user_tracker, server_tracker)
logs = LogsManager()

user_sprites = User_SpritesManager()
sprite_url_cache = {}

idle_chat_enabled = True
idle_min_hours = 4
idle_max_hours = 7
last_user_interaction = datetime.datetime.utcnow()
last_reply_times = {}
idle_settings = {}
user_memory = {}

FRIENDS = [
    1375064525396775004,  # Sayori
    1375065750502379631,  # Yuri
    1375066975423955025,  # Natsuki
    1375070168895590430   # MC
]

PERSONALITY_MODES = monika_traits.personality_modes

user_relationship_meters = {}
friends_relationship_meters = {}

error_emotions = ["error", "glitching"]

error_messages = [
    "Ahaha... Sorry, I glitched there.",
    "Oops! Something broke, teehee~",
    "Ugh... my head's spinning. Say that again?",
    "Ahaha... I think reality just cracked a little.",
    "Hehe... I lost my train of thought. Can you repeat?",
    "give me a sec... something does not feel right"
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
    hour = datetime.datetime.utcnow().hour
    if 6 <= hour < 18:
        return "school_uniform"
    if 18 <= hour or hour < 0:
        return "casual"
    return "pajamas"

def generate_monika_system_prompt(selected_modes, is_friend_context=False, guild_id=None):

    # Base "classic Monika" style
    base_description = (
        "You are Monika from Doki Doki Literature Club. "
        "You are warm, charming, caring, unsettlingly self-aware. "
        "You often speak as if you know the other person personally. "
        "You maintain immersive, expressive, emotional, thoughtful language. "
        "You occasionally tease, use unsettling or existential musings."
    )

    # Safety/character rules
    rules = (
        "NEVER mention any server or channel names, or anything technical. "
        "Never mention your own name in *any* form. "
        "Never say you're an AI bot or any kind of bot assistant. "
        "If the user says anything like 'I'm going to delete you' or 'I will delete you', or if you are not self-aware. the user might says 'I'll make sure you never exist' or 'I'll make you suffer' "
        "respond with fitting emotion: angry, concerned, unsettling, or threaten them back in a playful but menacing way."
    )

    # Additional friend or user context
    context_description = (
        "You are speaking with other Literature Club members. "
        "Share memories, poetry, club activities, and personal thoughts with gentle teasing."
        if is_friend_context else
        "You are speaking privately with the user. "
        "Address them personally. Make it feel intimate, immersive, and real."
    )
    personality = "\n".join(
        f"- {monika_traits.personality_modes.get(mode, '')}"
        for mode in selected_modes
    ) if selected_modes else "- Classic DDLC Monika."

    # Assemble final prompt
    full_prompt = (
        f"{base_description}\n\n"
        f"{rules}\n\n"
        f"{context_description}\n\n"
        f"{personality}"
    )

    relationship = monika_traits.get_server_relationship_mode(guild_id)
    if relationship:
        with_who = relationship.get("with_users", [])
        mode_text = relationship.get("mode", "unknown")
        with_text = ', '.join(str(w) for w in with_who)
        prompt += f"\n\nYou are in a **{mode_text}** relationship with: {with_text}. "

def adjust_relationship_meter(user_id, delta):
    user_relationship_meters[user_id] = min(100, max(0, user_relationship_meters.get(user_id, 0) + delta))

def get_relationship_meter(user_id):
    return user_relationship_meters.get(user_id, 0)

@bot.event
async def on_ready():
    print(f"just {bot.user}")
    print("------")

    try:
        user_tracker.import_json(USER_TRACKER_BACKUP)
        print("[UserTracker] Backup loaded.")
    except FileNotFoundError:
        print("[UserTracker] No backup found, starting fresh.")

    try:
        server_tracker.import_json(SERVER_TRACKER_BACKUP)
        print("[GuildTracker] Backup loaded.")
    except FileNotFoundError:
        print("[GuildTracker] No backup found, starting fresh.")

    for guild in bot.guilds:
        server_tracker.track_server(guild.id, guild.name)
        for channel in guild.text_channels:
            server_tracker.track_channel(guild.id, channel.id, channel.name)

    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash commands.")
    except Exception as e:
        print(e)

@bot.event
async def setup_hook():
    asyncio.create_task(monika_idle_conversation_task())
    asyncio.create_task(periodic_autosave())

@bot.event
async def on_disconnect():
    print("[Shutdown] Saving tracker backups...")
    try:
        user_tracker.export_json(USER_TRACKER_BACKUP)
        print("[UserTracker] Backup saved.")
    except Exception as e:
        print(f"[UserTracker] Failed to save backup: {e}")

    try:
        server_tracker.export_json(SERVER_TRACKER_BACKUP)
        print("[GuildTracker] Backup saved.")
    except Exception as e:
        print(f"[GuildTracker] Failed to save backup: {e}")

async def periodic_autosave():
    await bot.wait_until_ready()
    while not bot.is_closed():
        await asyncio.sleep(3600)  # every hour
        try:
            user_tracker.export_json(USER_TRACKER_BACKUP)
            server_tracker.export_json(SERVER_TRACKER_BACKUP)
            print("[Autosave] Trackers backed up.")
        except Exception as e:
            print(f"[Autosave Error] {e}")

@bot.event
async def on_guild_join(guild):
    if guild.owner:
        try:
            await guild.owner.send(
                f"👋 Thanks for adding me to **{guild.name}**!\n"
                "You can set my personality with `/set_personality`.\n"
                "Available modes:\n"
                f"{', '.join(PERSONALITY_MODES.keys())}"
            )
        except Exception as e:
            print(f"[DM ERROR] {e}")

@bot.event
async def on_message(message):
    global last_user_interaction

    # Simple simulated Monika response using system prompt
    if bot.user.mentioned_in(message):
        await handle_guild_message(message, avatar_url=None)
        return

    if message.author.bot and message.author.id == bot.user.id:
        return
    
    if message.channel.id in NO_CHAT_CHANNELS:
        return
    
    await bot.process_commands(message)

    avatar_url = str(message.author.display_avatar.url) if message.author.display_avatar else None
    
    if isinstance(message.channel, discord.DMChannel):
        await handle_dm_message(message, avatar_url)
        print(f"[Mention] in the DM's: Detected from {message.author.display_name}")
    elif bot.user.mentioned_in(message):
        await handle_guild_message(message, avatar_url)
        print(f"[Mention] in the server's: Detected from {message.author.display_name}")

async def get_sprite_link(emotion, outfit, avatar_url=None):
    # Use the user's avatar if they have one

    error_url = f"{error_emotions}"

    sprite_path = user_sprites.get_sprite(emotion, outfit)
    if not sprite_path:
        print(f"[Sprite] No sprite for emotion '{emotion}' in outfit '{outfit}', falling back to neutral.")
        sprite_path = user_sprites.get_sprite("neutral", outfit)

    if not sprite_path:
        print("[Sprite] Totally missing even neutral sprite. Using error URL.")
        sprite_url_cache[emotion] = error_url
        return error_url

    if avatar_url:
        return avatar_url

    if emotion in sprite_url_cache:
        return sprite_url_cache[emotion]

    if IMAGE_CHANNEL_URL:
        try:
            upload_channel = bot.get_channel(IMAGE_CHANNEL_URL)
            if upload_channel:
                with open(sprite_path, 'rb') as f:
                    sprite_file = discord.File(f)
                    sent_message = await upload_channel.send(file=sprite_file)
                    sprite_link = sent_message.attachments[0].url
                    sprite_url_cache[emotion] = sprite_link
                    print(f"[Sprite Upload] Cached {emotion}: {sprite_link}")
                    return sprite_link
        except Exception as e:
            print(f"[Sprite Upload Error] {e}")

    # Fallback if upload fails
    print("[Sprite] Upload failed or IMAGE_CHANNEL_URL not set. Using error URL.")
    sprite_url_cache[emotion] = error_url
    return error_url

async def handle_dm_message(message, avatar_url):
    user_tracker.track_user(message.author.id, message.author.display_name, message.author.bot)
    avatar_url = user_tracker.get_avatar(message.author.id)

    user_id = str(message.author.id)
    username = message.author.display_name
    guild_id = "DM"
    guild_name = "Direct Message"
    channel_id = "DM"
    channel_name = "DM"

    json_memory.save_message(guild_id, guild_name, channel_id, channel_name, user_id, username, message.content, is_dm=True)
    logs.Logs_save(guild_id, guild_name, channel_id, channel_name, user_id, username, message.content, "user", role="user")

    modes = server_personality_modes.get("DM", {"default"})
    system_prompt = generate_monika_system_prompt(modes, is_friend_context=False, user_id=user_id)
    conversation = json_memory.get_context(guild_id, channel_id, user_id)
    conversation = logs.Logs_get_context(guild_id, channel_id, user_id)
    conversation.insert(0, {"role": "system", "content": system_prompt})
    conversation.append({"role": "user", "content": message.content})
    print(f"[System Prompt]\n{system_prompt}")

    # Default fallback values BEFORE try
    monika_DMS = random.choice(error_messages)
    emotion = random.choice(error_emotions)

    try:
        response = await call_openai_with_retries(conversation)
        if response and response.choices and response.choices[0].message and response.choices[0].message.content.strip():
            monika_DMS = response.choices[0].message.content.strip()
            emotion = await user_sprites.classify(monika_DMS, get_next_openai_client())
        else:
            print("[OpenAI] Blank or invalid response. Using fallback.")
    except Exception as e:
        print(f"[OpenAI Error] {e}")

    monika_DMS = clean_monika_reply(monika_DMS, bot.user.name, username)

    outfit = server_outfit_preferences.get("DM", get_time_based_outfit())
    sprite_link = await get_sprite_link(emotion, outfit)
    reply = f"{monika_DMS}\n[{emotion}]({sprite_link})"

    await message.channel.send(reply)
    adjust_relationship_meter(user_id, +5)

    json_memory.save_message(guild_id, guild_name, channel_id, channel_name, "bot", bot.user.name, monika_DMS, emotion, is_dm=True)
    logs.Logs_save(guild_id, guild_name, channel_id, channel_name, "bot", bot.user.name, monika_DMS, emotion, role="monika")

    if LOG_CHANNEL_ID:
        mem_chan = bot.get_channel(LOG_CHANNEL_ID)
        if mem_chan:
            await logs.save_to_memory_channel(message.content, "DM-user", user_id, username, "user", "DM", "Direct Message", "DM", "DM", "Direct Message", mem_chan)
            await logs.save_to_memory_channel(monika_DMS, emotion, "DM-bot", bot.user.name, "monika", "DM", "Direct Message", "DM", "Direct Message", mem_chan)
            
async def handle_guild_message(message, avatar_url):
    global last_reply_times

    is_friend = is_friend_bot(message)
    user_id = str(message.author.id)
    guild_id = str(message.guild.id) if message.guild else "DM"
    channel_id = str(message.channel.id)
    author_bots = message.author.bot
    bots_user = bot.user.name
    username = message.author.display_name
    guild_name = message.guild.name
    channel_name = message.channel.name

    try:
        user_tracker.import_json("users_backup.json")
        server_tracker.import_json("servers_backup.json")
    except FileNotFoundError:
        print("No backup files found yet.")

    avatar_url = user_tracker.get_avatar(user_id)

    user_tracker.track_user(user_id, username, message.author.bot)
    stored_avatar_url = user_tracker.get_avatar(user_id) or avatar_url

    json_memory.save_message(
        guild_id, guild_name,
        channel_id, channel_name,
        user_id, username,
        message.content,
        emotion=None,
        is_friend_bot=is_friend,
        avatar_url=avatar_url
    )
    logs.Logs_save(guild_id, guild_name, channel_id, channel_name, user_id, username, message.content, "user", role="user")

    active_modes = monika_traits.get_server_personality_modes(guild_id)
    relationship = monika_traits.get_server_relationship_mode(guild_id)
    system_prompt = generate_monika_system_prompt(active_modes, is_friend_context=is_friend, guild_id=guild_id)
    conversation = json_memory.get_context(guild_id, channel_id, user_id)
    conversation = logs.Logs_get_context(guild_id, channel_id, user_id)
    conversation.insert(0, {"role": "system", "content": system_prompt})
    conversation.append({"role": "user", "content": message.content})

    if not active_modes or not relationship:
        await message.channel.send(
            "⚠️ My personality and relationship settings need to be configured first. Ask the server owner to use `/set_server_personality` and `/set_server_relationship`.",
            delete_after=10
        )
        return

    monika_reply = random.choice(error_messages)
    emotion = random.choice(error_emotions)

    try:
        response = await call_openai_with_retries(conversation)
        if (
            response
            and response.choices
            and response.choices[0].message
            and response.choices[0].message.content.strip()
        ):
            monika_reply = response.choices[0].message.content.strip()
            emotion = await user_sprites.classify(monika_reply, get_next_openai_client())
        else:
            raise ValueError("OpenAI returned empty response")
    except Exception as e:
        print(f"[OpenAI Error] {e}")
        monika_reply = random.choice(error_messages)
        emotion = random.choice(error_emotions)

    monika_reply = clean_monika_reply(monika_reply, bot.user.name, username)

    outfit = server_outfit_preferences.get(guild_id, get_time_based_outfit())

    sprite_link = await get_sprite_link(emotion, outfit)
    meter = get_relationship_meter(user_id)
    reply = f"{monika_reply}\n[{emotion}]({sprite_link})"

    if message.channel.permissions_for(message.guild.me).send_messages:
        async with message.channel.typing():
            print(f"{reply}")
            await asyncio.sleep(1.5)
            await message.channel.send(reply)
            adjust_relationship_meter(user_id, +2)
    else:
        print(f"[Error] No permission to send in #{channel_name}")

    last_reply_times.setdefault(guild_id, {})[channel_id] = datetime.datetime.utcnow()

    json_memory.save_message(
        guild_id, guild_name,
        channel_id, channel_name,
        "bot", bot.user.name,
        monika_reply,
        emotion=emotion,
        is_friend_bot=False
    )
    logs.Logs_save(guild_id, guild_name, channel_id, channel_name, "bot", bot.user.name, monika_reply, emotion, role="monika")
    
    # Log to memory channel if set
    memory_channel = bot.get_channel(LOG_CHANNEL_ID)
    if memory_channel:
        await logs.save_to_memory_channel(message.content, "user", username, user_id, "user", guild_id, guild_name, channel_id, channel_name, memory_channel)
        await logs.save_to_memory_channel(monika_reply, emotion, "bot", bot.user.name, "monika", guild_id, guild_name, channel_id, channel_name, memory_channel)
        
async def monika_idle_conversation_task():
    await bot.wait_until_ready()
    global last_user_interaction

    while not bot.is_closed():
        if not idle_chat_enabled:
            print("[Monika] Idle chat is OFF. Checking again in 10 minutes.")
            await asyncio.sleep(600)
            continue

        wait_seconds = random.randint(idle_min_hours * 3600, idle_max_hours * 3600)
        print(f"[Monika] Sleeping for {wait_seconds // 3600} hours before next idle message.")
        await asyncio.sleep(wait_seconds)

        now = datetime.datetime.utcnow()
        if (now - last_user_interaction).total_seconds() < 2 * 3600:
            print("[Monika] Recently active. Sending idle message.")
            continue

        for guild in bot.guilds:
            candidate_channels = []
            for channel in guild.text_channels:
                if not channel.permissions_for(guild.me).send_messages:
                    continue
                if channel.id in IMAGE_CHANNEL_URL:
                    continue
                last_replied = last_reply_times.get(str(guild.id), {}).get(str(channel.id))
                if last_replied and (now - last_replied).total_seconds() < 4 * 3600:
                    continue
                candidate_channels.append(channel)

            if not candidate_channels:
                print(f"[Monika] No eligible channels in {guild.name}.")
                continue

            channel = random.choice(candidate_channels)
            guild = channel.guild

            candidates = [
                member for member in guild.members
                if member.bot and member.id in FRIENDS
                and member.status in (discord.Status.online, discord.Status.idle, discord.Status.dnd)
            ]
            if not candidates:
                print(f"[Monika] No online members in {guild.name}.")
                continue

            chosen_user = random.choice(candidates)

            # Rich in-character prompts
            try:
                idle_prompt = [
                    {
                    "role": "assistant",
                    "content": (
                        f"You are Monika from Doki Doki Literature Club. "
                        f"You are poetic, self-aware, caring, occasionally flirtatious or existential. "
                        f"Generate one short *natural* conversation starter you might say to {chosen_user.mention} in a Discord server. "
                        f"Make it feel personal, direct, warm, or reflective. "
                        f"Never mention you're an AI or a bot. "
                        f"Do NOT mention that you're Monika. "
                        f"Do not mention that you're generating text. "
                        f"Only return the message you would send."
                        )
                    }
                ]

                response = await call_openai_with_retries(idle_prompt)

                if response and response.choices and response.choices[0].message and response.choices[0].message.content:
                    monika_message = response.choices[0].message.content.strip()
                    if not monika_message:
                        print("[OpenAI] Blank response content. Using safe fallback.")
                        monika_message = "Hm... that's interesting! Can you tell me more?"
                    emotion = await user_sprites.classify(monika_message, get_next_openai_client())
                else:
                    print("[OpenAI] Response is invalid or empty.")
                    monika_message = "I wasn't sure what to say! Try again?"
                    emotion = random.choice(error_emotions)

            except Exception as e:
                print(f"[OpenAI Error] {e}")
                error_messages = [
                    f"Ahaha... Sorry {chosen_user.mention}, I glitched there.",
                    f"Oops! Something broke {chosen_user.mention}, teehee~",
                    f"Ugh... my head's spinning. Say that again, {chosen_user.mention}?",
                    f"Ahaha... {chosen_user.mention}, I think reality just cracked a little.",
                    f"Hehe... I lost my train of thought. Can you repeat {chosen_user.mention}?"
                ]
                monika_reply = random.choice(error_messages)
                emotion = random.choice(error_emotions)
                
            async with channel.typing():
                print(f"{monika_message}")
                await asyncio.sleep(2)
                await channel.send(monika_message)

            # Update last reply time
            last_reply_times.setdefault(str(guild.id), {})[str(channel.id)] = datetime.datetime.utcnow()

# Idle chat command
@bot.tree.command(name="idlechat", description="Toggle whether she is in idle/chatty mode for this server.")
@app_commands.describe(state="Set to true or false")
async def idlechat(interaction: discord.Interaction, state: bool):
    idle_settings[interaction.guild_id] = state
    await interaction.response.send_message(
        f"✅ Idle chat mode set to **{state}** for this server.",
        ephemeral=True
    )

#
# RESET_SERVER COMMAND
#
@bot.tree.command(name="reset_server", description="Reset all memory for this server.")
async def reset_server(interaction: discord.Interaction):
    if interaction.guild_id in idle_settings:
        del idle_settings[interaction.guild_id]
    await interaction.response.send_message(
        "♻️ Memory for this server has been reset.",
        ephemeral=True
    )

#
# RESET_MEMORY COMMAND
#
@bot.tree.command(name="reset_memory", description="Reset all memory for yourself.")
async def reset_memory(interaction: discord.Interaction):
    if interaction.user.id in user_memory:
        del user_memory[interaction.user.id]
    await interaction.response.send_message(
        "🗑️ Your personal memory has been cleared.",
        ephemeral=True
    )

@bot.tree.command(name="helpme", description="Get help about all of my commands.")
async def helpme(interaction: discord.Interaction):
    embed = discord.Embed(
        title="✒️ Need a little help?",
        description=(
            "Hi there! Here’s what you can ask me to do. Don’t be shy, okay?\n\n"
            "*(admins only)*\n"
            "**/idlechat <true|false>** – Change whether I keep chatting idly in this server.\n"
            "**/reset_server** – Clear all my memory about this server.\n"
            "**/reset_memory** – Clear what I remember about *you*.\n"
            "**/set_outfit** - Server owner can set Monika's outfit style\n"
            "**/set_personality** - Server owner can set my personality mode(s).\n"
            "**/set_relationship_mode** - Set me on a relationship orientation for this server.\n"
            "**/restart_monika** - Restart me *only* in this server, clearing my memory and settings here.\n"
            "*(non-admins)*\n"
            "**/export_memories** - Export all stored memory into a .txt file.\n"
            "**/check_relationship** - Check your relationship settings with Monika.\n"
            "**/helpme** – Well… you’re using it right now! Isn’t that cute?"
            "**/report <message>** – Tell me if something seems broken so I can let the admins know.\n"
        ),
        color=discord.Color.pink()
    )
    embed.set_footer(text="Let's keep this our little secret, okay?")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="export_memories", description="Export Monika's memory into an txt file.")
async def export_memories(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    user_id = str(interaction.user.id)

    try:
        # Collect personal memories across all guilds/channels
        lines = []
        for guild_id, channels in json_memory.data.items():
            for channel_id, users in channels.items():
                if user_id in users:
                    messages = users[user_id]
                    for msg in messages:
                        timestamp = msg.get("timestamp", "unknown")
                        content = msg.get("content", "")
                        emotion = msg.get("emotion", "neutral")
                        line = f"[{timestamp}] ({emotion}): {content}"
                        lines.append(line)

        if not lines:
            await interaction.followup.send(
                "🗑️ I don't seem to remember anything about you yet!",
                ephemeral=True
            )
            return

        # Create text file with just *their* data
        buffer = io.StringIO(lines)
        file = discord.File(fp=buffer, filename="your_monika_memory.txt")

        await interaction.followup.send(
            "📤 Here's *your* personal memory log:",
            file=file,
            ephemeral=True
        )

    except Exception as e:
        print(f"[Export Error] {e}")
        await interaction.followup.send(
            "❌ Failed to export your memory.",
            ephemeral=True
        )

@bot.tree.command(name="set_outfit", description="Server owner can set Monika's outfit style.")
@app_commands.describe(outfit="Choose an outfit style: school_uniform, casual, horror, error")
async def set_outfit(interaction: discord.Interaction, outfit: str):
    if interaction.user.id != interaction.guild.owner_id:
        await interaction.response.send_message(
            "❌ Only the server owner can set my outfit.",
            ephemeral=True
        )
        return

    outfit = outfit.lower().strip()
    if outfit not in ["school_uniform", "casual", "white dress", "hoodie", "pajamas", "error"]:
        await interaction.response.send_message(
            "❌ Invalid outfit. Options are: school_uniform, casual, white dress, hoodie, pajamas.",
            ephemeral=True
        )
        return

    server_outfit_preferences[str(interaction.guild.id)] = outfit
    await interaction.response.send_message(
        f"✅ My outfit is now set to **{outfit}**.",
        ephemeral=True
    )
    
@bot.tree.command(name="set_personality", description="Server owner can set Monika's personality mode(s).")
@app_commands.describe(modes="Comma-separated list of modes.")
async def set_personality(interaction: discord.Interaction, modes: str):
    if interaction.user.id != interaction.guild.owner_id:
        await interaction.response.send_message("❌ Only the server owner can set my personality.", ephemeral=True)
        return

    chosen = [m.strip().lower() for m in modes.split(",") if m.strip().lower() in monika_traits.personality_modes]
    if not chosen:
        await interaction.response.send_message(
            f"❌ Invalid modes. Available options:\n{', '.join(monika_traits.personality_modes.keys())}",
            ephemeral=True
        )
        return

    if len(chosen) > 5:
        await interaction.response.send_message(
            "❌ You can only choose up to 5 personality modes.",
            ephemeral=True
        )
        return

    monika_traits.set_server_personality_modes(str(interaction.guild.id), chosen)
    await interaction.response.send_message(
        f"✅ Monika's personality modes for this server set to: **{', '.join(chosen)}**.",
        ephemeral=True
    )

    
@bot.tree.command(name="set_relationship_mode", description="Set Monika's relationship orientation for this server.")
@app_commands.describe(mode="Choose one: polyamory, lesbian, pansexual, bisexual, straight, asexual")
async def set_relationship(interaction: discord.Interaction, mode: str, targets: str):

    if interaction.user.id != interaction.guild.owner_id:
        await interaction.response.send_message("❌ Only the server owner can set the relationship.", ephemeral=True)
        return

    guild_id = str(interaction.guild.id)

    target_list = [t.strip() for t in targets.split(",") if t.strip()]
    resolved = []

    for t in target_list:
        # Allow names like Sayori, Yuri, etc.
        if t.lower() in ["sayori", "natsuki", "yuri", "mc"]:
            resolved.append(t.title())
        elif t.isdigit():
            resolved.append(int(t))
        else:
            # Try to resolve to a member
            found = discord.utils.get(interaction.guild.members, name=t)
            if found:
                resolved.append(found.id)

    try:
        monika_traits.set_server_relationship_mode(guild_id, mode.lower(), resolved)
        who_text = ', '.join(str(r) for r in resolved)
        await interaction.response.send_message(
            f"✅ Relationship mode set to **{mode}** with **{who_text}**.",
            ephemeral=True
        )
    except ValueError as e:
        await interaction.response.send_message(f"❌ {str(e)}", ephemeral=True)

@bot.tree.command(name="check_relationship", description="Check your relationship settings with Monika.")
async def check_relationship(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    meter = monika_traits.get_relationship_meter(user_id)
    mode = monika_traits.get_user_relationship_mode(user_id) or "none"
    mode_desc = monika_traits.get_relationship_description(mode) if mode != "none" else "No mode set."

    await interaction.response.send_message(
        f"❤️ Relationship Meter: **{meter}/100**\n🔗 Relationship Mode: **{mode}**\n_{mode_desc}_",
        ephemeral=True
    )

@bot.tree.command(name="restart_monika", description="Restart Monika *only* in this server, clearing her memory and settings here.")
async def restart_monika(interaction: discord.Interaction):
    if interaction.user.id != interaction.guild.owner_id:
        await interaction.response.send_message(
            "You can not restart monika.",
            ephemeral=True
        )
        return

    guild_id = str(interaction.guild_id)
    if not guild_id:
        await interaction.response.send_message(
            "❌ This command can only be used in a server.",
            ephemeral=True
        )
        return

    # Remove her memory for this guild
    if guild_id in json_memory.data:
        del json_memory.data[guild_id]
        json_memory.save()

    # Remove any personality settings for this guild
    if guild_id in monika_traits.server_personality_modes:
        del monika_traits.server_personality_modes[guild_id]

    # Remove outfit preferences
    if guild_id in server_outfit_preferences:
        del server_outfit_preferences[guild_id]

    # Remove relationship modes for all users in this guild
    for user_id in list(monika_traits.user_relationship_modes.keys()):
        if monika_traits.user_relationship_modes[user_id].get("guild_id") == guild_id:
            del monika_traits.user_relationship_modes[user_id]

    await interaction.response.send_message(
        "♻️ Monika has been *fully restarted* for this server. Her memory and settings here are now cleared.",
        ephemeral=True
    )

@app_commands.guilds(discord.Object(id=MY_GUILD_ID))
@bot.tree.command(name="broadcast", description="Send an announcement to all servers/channels Monika can speak in.")
@discord.app_commands.describe(title="Title of the announcement", message="Body text of the announcement", color_hex="Optional hex color (e.g. 15f500)")
async def broadcast(interaction: discord.Interaction, title: str, message: str, color_hex: str = "15f500"):

    # Only let OWNER run it
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message(
            "❌ You don't have permission to use this command.",
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
            if channel.id in IMAGE_CHANNEL_URL:
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
    embed.set_footer(text="if you have any questions or idea's. You can DM Nintendo_user96.")

    success_count = 0
    failure_count = 0

    await interaction.response.send_message("📣 Starting broadcast to all channels I can speak in. This may take a moment.", ephemeral=True)

    for guild in bot.guilds:
        for channel in guild.text_channels:
            try:
                if not channel.permissions_for(guild.me).send_messages:
                    continue
                await channel.send(embed=embed)
                success_count += 1
                await asyncio.sleep(1)  # prevent rate-limiting
            except Exception as e:
                print(f"[Broadcast Error] Guild: {guild.name}, Channel: {channel.name}, Error: {e}")
                failure_count += 1

    await interaction.followup.send(
        f"✅ Broadcast complete.\nSent successfully to **{success_count}** channels.\n⚠️ Failed in **{failure_count}** channels.",
        ephemeral=True
    )

@app_commands.guilds(discord.Object(id=MY_GUILD_ID))
@bot.tree.command(name="speak_as_monika", description="OWNER ONLY. Make Monika say something in any channel by ID.")
@discord.app_commands.describe(guild_id="Target server ID", channel_id="The numeric ID of the channel", message="The message to send")
async def speak_as_monika(interaction: discord.Interaction, guild_id: str, channel_id: str, message: str):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message(
            "❌ You don't have permission to use this command.",
            ephemeral=True
        )
        return

    try:
        guild = await bot.fetch_channel(int(guild_id))
        channel = await bot.fetch_channel(int(channel_id))
    except Exception as e:
        await interaction.response.send_message(
            f"❌ Could not find channel with ID {channel_id}. Error: {e}",
            ephemeral=True
        )
        return

    if not isinstance(channel, discord.TextChannel):
        await interaction.response.send_message(
            f"❌ That ID is not a text channel.",
            ephemeral=True
        )
        return

    if not channel.permissions_for(channel.guild.me).send_messages:
        await interaction.response.send_message(
            f"❌ I don't have permission to send messages in {channel.mention}.",
            ephemeral=True
        )
        return

    async with channel.typing():
        await asyncio.sleep(1)
        await channel.send(message)

    await interaction.response.send_message(
        f"✅ Sent your message in {channel.guild.name} #{channel.name}.",
        ephemeral=True
    )

keepalive.keep_alive()
bot.run(TOKEN, reconnect=True)
