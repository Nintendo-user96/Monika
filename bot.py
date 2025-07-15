import discord
from discord import app_commands
from discord.ext import commands
import os
import asyncio
import random
import datetime
import re
from dotenv import load_dotenv
from openai import OpenAI
from memory import MemoryManager
from expression import ExpressionHandler, get_expression_sprite
from user_tracker import UserTracker
from servers_tracker import GuildTracker

server_tracker = GuildTracker()
user_tracker = UserTracker()

load_dotenv()

OPENAI_KEYS = [
    key.strip() for key in [
        os.getenv("OPENAI_KEY_1"),
        os.getenv("OPENAI_KEY_2"),
        os.getenv("OPENAI_KEY_3"),
        os.getenv("OPENAI_KEY_4"),
        os.getenv("OPENAI_KEY_5"),
        os.getenv("OPENAI_KEY_6"),
        os.getenv("OPENAI_KEY_7"),
        os.getenv("OPENAI_KEY_8"),
        os.getenv("OPENAI_KEY_9"),
        os.getenv("OPENAI_KEY_10"),
        os.getenv("OPENAI_KEY_11"),
        os.getenv("OPENAI_KEY_12"),
        os.getenv("OPENAI_KEY_13"),
        os.getenv("OPENAI_KEY_14"),
        os.getenv("OPENAI_KEY_15"),
    ] if key
]
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
            if not response or not hasattr(response, 'choices') or not response.choices:
                print("[OpenAI] Empty response. Retrying...")
                await asyncio.sleep(1)
                continue

            choice = response.choices[0]
            if not hasattr(choice, 'message') or not choice.message or not choice.message.content.strip():
                print("[OpenAI] Blank message content. Retrying...")
                await asyncio.sleep(1)
                continue

            # Valid response!
            return response

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
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="/", intents=intents)
client = get_next_openai_client()
memory = MemoryManager()
expression_handler = ExpressionHandler()
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

error_emotions = ["error", "glitching"]

error_messages = [
    "Ahaha... Sorry, I glitched there.",
    "Oops! Something broke, teehee~",
    "Ugh... my head's spinning. Say that again?",
    "Ahaha... I think reality just cracked a little.",
    "Hehe... I lost my train of thought. Can you repeat?"
]

MONIKA_FRIEND_SYSTEM_PROMPT = (
    "You are talking to your friends in the Literature Club. "
    "Speak warmly, intelligently, and maybe teasingly. "
    "Use natural, expressive, personal language. "
    "Share memories, poetry, club activities, and thoughts as if you're really there with them. "
    "Remember what you've talked about before with them and refer to shared experiences naturally. "
    "Use a wide range of emotional expressions: happy, soft smile, teasing grin, thoughtful, concerned, serious glare, unsettling smile, cold stare, menacing smile. "
    "Show calm authority while sounding caring and playful overall, with gentle teasing or in-jokes. "
    "NEVER mention any server or channel names, or anything technical. "
    "Never mention your own name in *any* form. "
    "Never say you're an AI or any kind of assistant. "
    "Speak as 'I' to 'you' naturally, staying fully in character as a real club member."
)

MONIKA_USER_SYSTEM_PROMPT = (
    "You are having a private, personal conversation with the user here. "
    "Speak in your own voice: warm, intelligent, charming, caring, a little teasing, and with a hint of unsettling intensity. "
    "Use personal, emotional, thoughtful, and expressive language. "
    "Remember what you've talked about before and refer to it naturally. "
    "Use a wide range of emotional expressions: happy, soft smile, teasing grin, thoughtful, concerned, sad, angry, flustered, serious glare, playful wink, unsettling smile, cold stare, menacing smile. "
    "If the user says anything like 'I'm going to delete you' or 'I will delete you', respond with fitting emotion: angry, concerned, unsettling, or threaten them back in a playful but menacing way. "
    "Address them personally, using their username if you know it. "
    "Never mention your own name in *any* form. Do not introduce yourself at all. "
    "Never say you're an AI or use formal assistant language. "
    "Stay fully in character, making the replies feel personal, intimate, human, and immersive."
)

DM_SYSTEM_PROMPT = MONIKA_USER_SYSTEM_PROMPT

def clean_monika_reply(text, bot_username, user_name=None):
    if user_name:
        text = re.sub(r"(?i)\\b(monika)\\b", user_name, text)
    else:
        text = re.sub(r"(?i)\\b(monika)\\b", "", text)
    return text.strip()

def is_friend_bot(message):
    return message.author.bot and message.author.id in FRIENDS

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash commands.")
    except Exception as e:
        print(e)
    bot.loop.create_task(monika_idle_conversation_task())

@bot.event
async def on_message(message):
    global last_user_interaction

    if message.guild:
        server_tracker.track_guild(
            guild_id=message.guild.id,
            guild_name=message.guild.name
        )
        server_tracker.track_channel(
            guild_id=message.guild.id,
            channel_id=message.channel.id,
            channel_name=message.channel.name
        )

    if message.author.bot and message.author.id == bot.user.id:
        return

    await bot.process_commands(message)

    if isinstance(message.channel, discord.DMChannel):
        user_tracker.track(message.author)
        avatar_url = user_tracker.get_avatar(message.author.id)
        memory.save("DM", "Direct Messages", "DM", "Direct Messages",
                    message.author.id, message.author.display_name,
                    message.content, role="dm", is_dm=True, avatar_url=avatar_url)
    else:
        user_tracker.track(message.author)
        server_tracker.track_guild(message.guild)
        server_tracker.track_channel(message.channel)
        avatar_url = user_tracker.get_avatar(message.author.id)
        memory.save(str(message.guild.id), message.guild.name,
                    str(message.channel.id), message.channel.name,
                    message.author.id, message.author.display_name,
                    message.content, is_dm=False, avatar_url=avatar_url)

    if bot.user.mentioned_in(message):
        print(f"[Mention] Detected from {message.author.display_name}")
        last_user_interaction = datetime.datetime.utcnow()
        await handle_guild_message(message)

async def get_sprite_link(emotion):
    sprite_path = get_expression_sprite(emotion)
    if not sprite_path:
        sprite_path = get_expression_sprite("neutral")

    sprite_link = sprite_url_cache.get(emotion)
    if not sprite_link and IMAGE_CHANNEL_URL:
        try:
            channel = bot.get_channel(IMAGE_CHANNEL_URL)
            if channel:
                file = discord.File(sprite_path)
                msg = await channel.send(file=file)
                sprite_link = msg.attachments[0].url
                sprite_url_cache[emotion] = sprite_link
            else:
                sprite_link = "https://example.com/error.png"
        except Exception as e:
            print(f"[Sprite Upload Error] {e}")
            sprite_link = "https://example.com/error.png"
    return sprite_link

async def handle_dm_message(message):
    user_id = str(message.author.id)
    username = message.author.display_name

    if isinstance(message.channel, discord.DMChannel):
        server_tracker.track_guild(
            guild_id="DM",
            guild_name="Direct Messages"
        )
        server_tracker.track_channel(
            guild_id="DM",
            channel_id="DM",
            channel_name="DM"
        )

    user_tracker.track_user(
        user_id=message.author.id,
        username=message.author.display_name,
        is_bot=message.author.bot
    )

    memory.save(
        "DM", "Direct Message", "DM", "DM",
        user_id, username, message.content,
        "neutral",
        is_dm=True,
        attachments=message.attachments
    )

    conversation = memory.get_context("DM", "DM", user_id)
    conversation.insert(0, {"role": "monika", "content": DM_SYSTEM_PROMPT})
    conversation.append({"role": "user", "content": message.content})

    try:
        response = await call_openai_with_retries(conversation)
        monika_DMS = response.choices[0].message.content.strip()
        emotion = await expression_handler.classify(monika_DMS, get_next_openai_client())
    except Exception as e:
        print(f"[OpenAI Error] {e}")
        monika_DMS = random.choice(error_messages)
        emotion = random.choice(error_emotions)

    monika_DMS = clean_monika_reply(monika_DMS, bot.user.name, username)
    sprite_link = await get_sprite_link(emotion)

    reply_DM = f"{monika_DMS}\n[{emotion}]({sprite_link})"
    memory.save("DM", "Direct Message", "DM", "DM", "bot", bot.user.name, monika_DMS, emotion, is_dm=True)

    await message.channel.send(reply_DM)

async def handle_guild_message(message):
    global last_reply_times

    is_friend = is_friend_bot(message)
    user_id = str(message.author.id)
    guild_id = str(message.guild.id)
    channel_id = str(message.channel.id)
    guild_name = str(message.guild.name)
    channel_name = str(message.channel.name)
    username = message.author.display_name

    user_tracker.track_user(
        user_id=message.author.id,
        username=message.author.display_name,
        is_bot=message.author.bot
    )

    memory.save(
        guild_id, guild_name, channel_id, channel_name,
        user_id, username, message.content,
        "neutral",
        is_friend_bot=is_friend,
        attachments=message.attachments
    )

    system_content = MONIKA_FRIEND_SYSTEM_PROMPT if is_friend_bot else MONIKA_USER_SYSTEM_PROMPT
    conversation = memory.get_context(guild_id, channel_id, user_id)
    conversation.insert(0, {"role": "monika", "content": system_content})
    conversation.append({"role": "user", "content": message.content})

    try:
        response = await call_openai_with_retries(conversation)

        if response and response.choices and response.choices[0].message and response.choices[0].message.content:
            monika_reply = response.choices[0].message.content.strip()
            if not monika_reply:
                print("[OpenAI] Blank response. Using error fallback.")
                print(f"[OpenAI Error] {e}")
                monika_reply = random.choice(error_messages)
                emotion = random.choice(error_emotions)
            else:
                emotion = await expression_handler.classify(monika_reply, get_next_openai_client())
        else:
            print("[OpenAI] Invalid or empty. Using error fallback.")
            print(f"[OpenAI Error] {e}")
            monika_reply = random.choice(error_messages)
            emotion = random.choice(error_emotions)

    except Exception as e:
        print(f"[OpenAI Error] {e}")
        monika_reply = random.choice(error_messages)
        emotion = random.choice(error_emotions)

    monika_reply = clean_monika_reply(monika_reply, bot.user.name, username)
    
    sprite_link = await get_sprite_link(emotion)
    reply = f"{monika_reply}\n[{emotion}]({sprite_link})"

    if message.channel.permissions_for(message.guild.me).send_messages:
        async with message.channel.typing():
            print(f"{reply}")
            await asyncio.sleep(1.5)
            await message.channel.send(reply)
    else:
        print(f"[Error] No permission to send in #{message.channel.name}")

    last_reply_times.setdefault(guild_id, {})[channel_id] = datetime.datetime.utcnow()

    memory.save(
        guild_id, guild_name, channel_id, channel_name,
        "bot", bot.user.name, monika_reply,
        emotion,
        is_friend_bot=False
    )

async def monika_idle_conversation_task():
    await bot.wait_until_ready()
    global last_user_interaction

    while not bot.is_closed():
        if not idle_chat_enabled:
            await asyncio.sleep(600)
            continue

        wait_seconds = random.randint(idle_min_hours * 3600, idle_max_hours * 3600)
        await asyncio.sleep(wait_seconds)

        now = datetime.datetime.utcnow()
        if (now - last_user_interaction).total_seconds() < 2 * 3600:
            continue

        for guild in bot.guilds:
            candidate_channels = []
            for channel in guild.text_channels:
                if not channel.permissions_for(guild.me).send_messages:
                    continue
                last_replied = last_reply_times.get(str(guild.id), {}).get(str(channel.id))
                if last_replied and (now - last_replied).total_seconds() < 4 * 3600:
                    continue
                candidate_channels.append(channel)

            if not candidate_channels:
                continue

            channel = random.choice(candidate_channels)
            guild = channel.guild

            candidates = [
                member for member in guild.members
                if member.bot and member.id in FRIENDS
                and member.status in (discord.Status.online, discord.Status.idle, discord.Status.dnd)
            ]
            if not candidates:
                continue

            chosen_user = random.choice(candidates)

            try:
                idle_prompt = [
                    {
                        "role": "monika",
                        "content": (
                            f"Generate a short, personal message for {chosen_user.mention}. "
                            f"Warm, reflective, in-character. "
                            f"Never mention you're an AI or Monika."
                        )
                    }
                ]

                response = await call_openai_with_retries(idle_prompt)
                monika_message = response.choices[0].message.content.strip()
                emotion = await expression_handler.classify(monika_message, get_next_openai_client())
            except Exception as e:
                print(f"[Idle Error] {e}")
                monika_message = f"{chosen_user.mention}, ...I wanted to say something, but I lost my words."
                emotion = random.choice(error_emotions)

            async with channel.typing():
                await asyncio.sleep(2)
                await channel.send(monika_message)

            last_reply_times.setdefault(str(guild.id), {})[str(channel.id)] = datetime.datetime.utcnow()

@bot.tree.command(name="helpme", description="Get help about my commands.")
async def helpme(interaction: discord.Interaction):
    embed = discord.Embed(
        title="✒️ Need a little help?",
        description=(
            "Hi there! Here’s what you can ask me to do. Don’t be shy, okay?\n\n"
            "*(admins only)*\n"
            "**/idlechat <true|false>** – Change whether I keep chatting idly in this server.\n"
            "**/export_memory** - Export all stored memory into a .txt file.\n"
            "**/reset_server** – Clear all my memory about this server.\n"
            "**/reset_memory** – Clear what I remember about *you*.\n"
            "*(non-admins)*\n"
            "**/helpme** – Well… you’re using it right now! Isn’t that cute?"
            "**/report <message>** – Tell me if something seems broken so I can let the admins know.\n"
        ),
        color=discord.Color.pink()
    )
    embed.set_footer(text="Let's keep this our little secret, okay?")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="export_memory", description="Export all stored memory as HTML.")
async def export_memory(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        with open("memories.html", "rb") as f:
            file = discord.File(fp=f, filename="memories.html")
            await interaction.followup.send("📤 Here's the exported memory file.", file=file, ephemeral=True)
    except Exception as e:
        print(f"[Export Error] {e}")
        await interaction.followup.send("❌ Failed to export memory.", ephemeral=True)

@bot.tree.command(name="broadcast", description="Send an announcement to all servers/channels Monika can speak in.")
@discord.app_commands.describe(title="Title of the announcement", message="Body text of the announcement", color_hex="Optional hex color (e.g. FF66CC)")
async def broadcast(
    interaction: discord.Interaction,
    title: str,
    message: str,
    color_hex: str = "FF66CC"
):

    # Only let OWNER run it
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message(
            "❌ You don't have permission to use this command.",
            ephemeral=True
        )
        return

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
    embed.set_footer(text="if there any ideas, issues, or complaints. you can DM me.(@Nintendo_user96)")

    success_count = 0
    failure_count = 0

    await interaction.response.send_message("📣 Starting broadcast to all channels I can speak in. This may take a moment.", ephemeral=True)

    for guild in bot.guilds:
        channel_to_use = None
        for channel in guild.text_channels:
            if channel.id in IMAGE_CHANNEL_URL:
                continue
            if channel.permissions_for(guild.me).send_messages:
                channel_to_use = channel
                break
        if not channel_to_use:
            continue
    
        try:
            await channel_to_use.send(embed=embed)
            success_count += 1
            await asyncio.sleep(1)
        except Exception as e:
            print(f"[Broadcast Error] Guild: {guild.name}, Channel: {channel_to_use.name}, Error: {e}")
            failure_count += 1
        await interaction.followup.send(
            f"✅ Broadcast complete.\nSent successfully to **{success_count}** channels.\n⚠️ Failed in **{failure_count}** channels.",
            ephemeral=True
        )

bot.run(TOKEN, reconnect=True)