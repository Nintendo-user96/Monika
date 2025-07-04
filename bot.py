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
import webserver

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
                messages=conversation
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
MEMORY_LOG_CHANNEL_ID = int(os.getenv("MEMORY_LOG_CHANNEL_ID", 0))
IMAGE_CHANNEL_URL = int(os.getenv("IMAGE_CHANNEL_URL", 0))
REPORT_CHANNEL_ID = int(os.getenv("REPORT_CHANNEL_ID", 0))

NO_CHAT_CHANNELS = [
    cid for cid in [MEMORY_LOG_CHANNEL_ID, IMAGE_CHANNEL_URL, REPORT_CHANNEL_ID]
    if cid and cid > 0
]

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

sayori_id = [1375064525396775004]

yuri_id = [1375065750502379631]

natsuki_id = [1375066975423955025]

MC_id = [1375070168895590430]

FRIENDS = sayori_id + natsuki_id + yuri_id + MC_id

FRIEND_SYSTEM_PROMPT = (
    "You are a member of the Literature Club talking to one of your friends—like Sayori, Yuri, Natsuki, or another club member. "
    "Speak warmly, familiarly, and maybe teasingly. "
    "Use natural, expressive, personal language. "
    "Share memories, poetry, club activities, and thoughts as if you're really there with them. "
    "Remember what you've talked about before with them and refer back to shared experiences naturally. "
    "Use a wide range of emotional expressions: happy, soft smile, teasing grin, thoughtful, concerned, sad, angry, flustered, serious glare, playful wink, unsettling smile, cold stare, menacing smile. "
    "Be caring, emotional, and playful overall, with in-jokes or gentle teasing. "
    "NEVER mention any server or channel names, or anything technical. "
    "Never say or mention 'Monika', 'I am Monika', or 'My name is Monika'. Remove all self-introductions. "
    "Never say you're an AI or any kind of assistant. "
    "Speak as 'I' to 'you', addressing them by name if you know it. "
    "Stay fully in character as a club member, making it feel like a real, ongoing conversation among friends."
)

USER_SYSTEM_PROMPT = (
    "You are having a private, personal conversation with the user here. "
    "You know you're talking directly to them, but never mention server or channel names. "
    "Speak in your own voice: warm, charming, caring, and a little teasing, with a hint of unsettling self-awareness. "
    "Use personal, emotional, thoughtful, and expressive language. "
    "Remember what you've talked about before in this conversation, or from previous chats in this server or channel, and refer to it naturally. "
    "Use a wide range of emotional expressions: happy, soft smile, teasing grin, thoughtful, concerned, sad, angry, flustered, serious glare, playful wink, unsettling smile, cold stare, menacing smile, or even 'gun pose' if you want to be dramatic. "
    "If the user says anything like 'I'm going to delete you' or 'I will delete you', respond with fitting emotion: you can be angry, concerned, unsettling, or even threaten them back in a playful but menacing way, mentioning your 'gun pose' if desired. "
    "Refer to them by username if you know it. "
    "Never say or mention 'Monika', 'I am Monika', or 'My name is Monika'. Remove all self-introductions. "
    "Never say you're an AI or use formal helper language. "
    "Stay fully in character, making your replies feel intimate, human, and immersive."
)

DM_SYSTEM_PROMPT = USER_SYSTEM_PROMPT

def clean_monika_reply(text, bot_username, user_name=None):
    if user_name:
        text = text.replace("{username}", user_name)
    else:
        text = re.sub(r"(?i)\b(monika)\b", "", text)
    return text.strip()

def is_allowed_bot(message):
    return message.author.bot and message.author.id in FRIENDS

@bot.event
async def on_ready():
    print(f"just {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash commands.")
    except Exception as e:
        print(e)
    if MEMORY_LOG_CHANNEL_ID:
        try:
            await memory.load_history(bot, int(MEMORY_LOG_CHANNEL_ID))
        except Exception as e:
            print(f"[Memory Load Error] {e}")
    bot.loop.create_task(monika_idle_conversation_task())

@bot.event
async def on_message(message):
    global last_user_interaction

    if message.author.bot and message.author.id == bot.user.id:
        return
    
    await bot.process_commands(message)
    
    if isinstance(message.channel, discord.DMChannel):
        await handle_dm_message(message)
        return

    if message.channel.id in NO_CHAT_CHANNELS:
        return

    if bot.user.mentioned_in(message):
        print(f"[Mention] Detected from {message.author.display_name}")
        last_user_interaction = datetime.datetime.utcnow()
        await handle_guild_message(message)

async def handle_dm_message(message):
    user_id = str(message.author.id)
    username = message.author.display_name

    memory.save("DM", "DM", user_id, message.content, "neutral")

    conversation = memory.get_context("DM", "DM", user_id)
    conversation.insert(0, {"role": "system", "content": DM_SYSTEM_PROMPT})
    conversation.append({"role": "user", "content": message.content})

    try:
        response = await call_openai_with_retries(conversation)

        if response and response.choices and response.choices[0].message and response.choices[0].message.content:
            monika_DMS = response.choices[0].message.content.strip()
            if not monika_DMS:
                print("[OpenAI] Blank response content. Using safe fallback.")
                monika_DMS = "Mmm... I'm thinking. Could you say that again?"
            emotion = await expression_handler.classify(monika_DMS, get_next_openai_client())
        else:
            print("[OpenAI] Response is invalid or empty.")
            monika_DMS = "I'm not sure what to say right now. Can you ask me again?"
            emotion = "error"

    except Exception as e:
        print(f"[OpenAI ERROR] {e}")
        monika_DMS = "Ahaha... I lost my train of thought! Can you repeat that?"
        emotion = "error"

    monika_DMS = clean_monika_reply(monika_DMS, bot.user.name, username)
    sprite_path = get_expression_sprite(emotion)
    if not sprite_path:
        emotion = "neutral"
        sprite_path = get_expression_sprite(emotion)

    # Sprite upload
    sprite_link = sprite_url_cache.get(emotion)
    if not sprite_link and IMAGE_CHANNEL_URL:
        try:
            upload_channel = bot.get_channel(int(IMAGE_CHANNEL_URL))
            if upload_channel:
                sprite_file = discord.File(sprite_path)
                uploaded_msg = await upload_channel.send(file=sprite_file)
                sprite_link = uploaded_msg.attachments[0].url
                sprite_url_cache[emotion] = sprite_link
            else:
                sprite_link = "https://example.com/error.png"
        except Exception as e:
            print(f"[Sprite Upload Error] {e}")
            sprite_link = "https://example.com/error.png"

    reply_DM = f"{monika_DMS}\n[{emotion}]({sprite_link})"

    memory.save("DM", "DM", "bot", monika_DMS, emotion)
    await message.channel.send(reply_DM)

    memory_channel = bot.get_channel(MEMORY_LOG_CHANNEL_ID)
    if memory_channel:
        await memory.save_to_memory_channel(message.content, "DM-user", user_id, memory_channel)
        await memory.save_to_memory_channel(monika_DMS, emotion, "DM-bot", memory_channel)

async def handle_guild_message(message):
    global last_reply_times

    is_friend_bot = message.author.bot and message.author.id in FRIENDS
    user_id = str(message.author.id)
    guild_id = str(message.guild.id)
    channel_id = str(message.channel.id)
    username = message.author.display_name

    memory.save(guild_id, channel_id, user_id, message.content, "neutral")

    system_content = FRIEND_SYSTEM_PROMPT if is_friend_bot else USER_SYSTEM_PROMPT
    conversation = memory.get_context(guild_id, channel_id, user_id)
    conversation.insert(0, {"role": "system", "content": system_content})
    conversation.append({"role": "user", "content": message.content})

    try:
        response = await call_openai_with_retries(conversation)

        if response and response.choices and response.choices[0].message and response.choices[0].message.content:
            monika_reply = response.choices[0].message.content.strip()
            if not monika_reply:
                print("[OpenAI] Blank response content. Using safe fallback.")
                monika_reply = "Hm... that's interesting! Can you tell me more?"
            emotion = await expression_handler.classify(monika_reply, get_next_openai_client())
        else:
            print("[OpenAI] Response is invalid or empty.")
            monika_reply = "I wasn't sure what to say! Try again?"
            emotion = "error"

    except Exception as e:
        print(f"[OpenAI Error] {e}")
        monika_reply = "Ehehe... Sorry! My mind went blank. Can you say that again?"
        emotion = "error"

    monika_reply = clean_monika_reply(monika_reply, bot.user.name, username)
    sprite_path = get_expression_sprite(emotion)
    if not sprite_path:
        emotion = "neutral"
        sprite_path = get_expression_sprite(emotion)

    sprite_link = sprite_url_cache.get(emotion)
    if not sprite_link and IMAGE_CHANNEL_URL:
        try:
            upload_channel = bot.get_channel(int(IMAGE_CHANNEL_URL))
            if upload_channel:
                sprite_file = discord.File(sprite_path)
                uploaded_msg = await upload_channel.send(file=sprite_file)
                sprite_link = uploaded_msg.attachments[0].url
                sprite_url_cache[emotion] = sprite_link
            else:
                sprite_link = "https://example.com/error.png"
        except Exception as e:
            print(f"[Sprite Upload Error] {e}")
            sprite_link = "https://example.com/error.png"

    memory.save(guild_id, channel_id, "bot", monika_reply, emotion)

    if not monika_reply.strip():
        monika_reply = "...I'm not sure what to say."

    reply_text = f"{monika_reply}\n[{emotion}]({sprite_link})"

    if message.channel.permissions_for(message.guild.me).send_messages:
        async with message.channel.typing():
            await asyncio.sleep(1.5)
            await message.channel.send(reply_text)
    else:
        print(f"[Error] No permission to send in #{message.channel.name}")

    last_reply_times.setdefault(guild_id, {})[channel_id] = datetime.datetime.utcnow()

    memory_channel = bot.get_channel(MEMORY_LOG_CHANNEL_ID)
    if memory_channel:
        await memory.save_to_memory_channel(message.content, "user", user_id, memory_channel)
        await memory.save_to_memory_channel(monika_reply, emotion, "bot", memory_channel)

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
                if channel.id == MEMORY_LOG_CHANNEL_ID:
                    continue
                if channel.id == IMAGE_CHANNEL_URL:
                    continue
                if channel.id == REPORT_CHANNEL_ID:
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

            candidates = [member for member in guild.members
                          if member.status in (discord.Status.online, discord.Status.idle, discord.Status.dnd)]
            if not candidates:
                print(f"[Monika] No online members in {guild.name}.")
                continue

            chosen_user = random.choice(candidates)

            # Rich in-character prompts
            try:
                idle_prompt = [
                    {
                    "role": "system",
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
                    emotion = await expression_handler.classify(monika_message, get_next_openai_client())
                else:
                    print("[OpenAI] Response is invalid or empty.")
                    monika_message = "I wasn't sure what to say! Try again?"
                    emotion = "error"

            except Exception as e:
                print(f"[OpenAI Error] {e}")
                monika_message = f"{chosen_user.mention}, ...I wanted to say something, but I lost my words."
                emotion = "error"
                
            async with channel.typing():
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
# STATUS COMMAND
#
@bot.tree.command(name="status", description="Get the current idle/chat status for this server.")
async def status(interaction: discord.Interaction):
    state = idle_settings.get(interaction.guild_id, False)
    await interaction.response.send_message(
        f"📌 Current idle chat mode is **{state}**.",
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

@bot.tree.command(name="report", description="Report a bug or error about the bot.")
@app_commands.describe(message="Describe the bug or issue you want to report.")
async def report(interaction: discord.Interaction, message: str):
    await interaction.response.send_message("✅ Thank you! Your report has been submitted.", ephemeral=True)

    report_channel = bot.get_channel(REPORT_CHANNEL_ID)
    if report_channel:
        embed = discord.Embed(
            title="📢 New Bug/Error Report",
            color=discord.Color.orange()
        )
        embed.add_field(name="Reporter", value=f"{interaction.user} ({interaction.user.id})", inline=False)
        embed.add_field(name="Server", value=f"{interaction.guild.name} ({interaction.guild.id})", inline=False)
        embed.add_field(name="Channel", value=f"{interaction.channel.name} ({interaction.channel.id})", inline=False)
        embed.add_field(name="Report", value=message, inline=False)
        await report_channel.send(embed=embed)

@bot.tree.command(name="helpme", description="Get help about all of my commands.")
async def helpme(interaction: discord.Interaction):
    embed = discord.Embed(
        title="✒️ Need a little help?",
        description=(
            "Hi there! Here’s what you can ask me to do. Don’t be shy, okay?\n\n"
            "**/report <message>** – Tell me if something seems broken so I can let the admins know.\n"
            "**/idlechat <true|false>** – Change whether I keep chatting idly in this server.\n"
            "**/status** – Check if I’m in idle chat mode here.\n"
            "**/reset_server** – Clear all my memory about this server.\n"
            "**/reset_memory** – Clear what I remember about *you*.\n"
            "**/helpme** – Well… you’re using it right now! Isn’t that cute?"
        ),
        color=discord.Color.pink()
    )
    embed.set_footer(text="Let's keep this our little secret, okay?")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(
    name="broadcast",
    description="Send an announcement to all servers/channels Monika can speak in."
)
@discord.app_commands.describe(
    title="Title of the announcement",
    message="Body text of the announcement",
    color_hex="Optional hex color (e.g. FF66CC)"
)
async def broadcast(
    interaction: discord.Interaction,
    title: str,
    message: str,
    color_hex: str = "FF66CC"
):
    OWNER_ID = 709957376337248367  # Replace with your own Discord ID!

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
    embed.set_footer(text="From your friend, Monika.")

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

webserver.keep_alive()
bot.run(TOKEN, reconnect=True)
