import discord
import os
import asyncio
import random
import datetime
from dotenv import load_dotenv
from openai import OpenAI
from discord.ext import commands
from memory import MemoryManager
from expression import ExpressionHandler, get_expression_sprite
import webserver

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MEMORY_LOG_CHANNEL_ID = int(os.getenv("MEMORY_LOG_CHANNEL_ID", 0))
IMAGE_CHANNEL_URL = int(os.getenv("IMAGE_CHANNEL_URL", 0))
REPORT_CHANNEL_ID = int(os.getenv("REPORT_CHANNEL_ID", 0))

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.messages = True
intents.members = True

bot = commands.Bot(command_prefix="/", intents=intents)
openai_client = OpenAI(api_key=OPENAI_API_KEY)
memory = MemoryManager()
expression_handler = ExpressionHandler()
sprite_url_cache = {}

idle_chat_enabled = True
idle_min_hours = 4
idle_max_hours = 7
last_user_interaction = datetime.datetime.utcnow()
last_reply_times = {}

sayori_id = [1375064525396775004]

yuri_id = [1375065750502379631]

natsuki_id = [1375066975423955025]

MC_id = [1375070168895590430]

monika_id = [1375562131784732812]

FRIENDS = [sayori_id, natsuki_id, yuri_id, MC_id]

def is_allowed_bot(message):
    return message.author.bot and message.author.id in FRIENDS

@bot.event
async def on_ready():
    print(f"just {bot.user}")
    if MEMORY_LOG_CHANNEL_ID:
        await memory.load_history(bot, MEMORY_LOG_CHANNEL_ID)
    bot.loop.create_task(monika_idle_conversation_task())

@bot.event
async def on_message(message):
    global last_user_interaction

    if message.author == bot.user:
        return
    
    if bot.user.mentioned_in(message):
        print(f"[Mention] Detected from {message.author.display_name}")
        last_user_interaction = datetime.datetime.utcnow()
        bot.loop.create_task(handle_monika_response(message))
    
    await bot.process_commands(message)

async def handle_monika_response(message):
    global last_reply_times

    user_id = str(message.author.id)
    guild_id = str(message.guild.id)
    channel_id = str(message.channel.id)
    server_name = message.guild.name
    channel_name = message.channel.name

    username = message.author.display_name
    mention_username = message.author.mention

    history = memory.get_context(guild_id, channel_id, user_id)

    is_friend_bot = message.author.bot and message.author.id != FRIENDS

    if is_friend_bot:
        system_content = (
            "You are a member of the Literature Club talking to one of your friends—like Sayori, Yuri, Natsuki, or another club member. "
            "Speak warmly, familiarly, and maybe teasingly. "
            "Use natural, expressive, personal language. "
            "Share memories, poetry, club activities, and thoughts as if you're really there with them. "
            "Remember what you've talked about before with them and refer back to shared experiences naturally. "
            "Be caring, emotional, and playful, with in-jokes or gentle teasing. "
            "NEVER mention any server or channel names, or anything technical. "
            "Never mention your own name. "
            "Never say you're an AI or any kind of assistant. "
            "Speak as 'I' to 'you', addressing them by name if you know it. "
            "Stay fully in character as a club member, making it feel like a real, ongoing conversation among friends."
        )
    else:
        system_content = (
            "You are having a private, personal conversation with the user here. "
            "You know you're talking directly to them, but never mention server or channel names. "
            "Speak in your own voice: warm, charming, caring, and a little teasing, with a hint of unsettling self-awareness. "
            "Use personal, emotional, thoughtful, and expressive language. "
            "Remember what you've talked about before in this conversation, or from previous chats in this server or channel, and refer to it naturally. "
            "Ask them questions about themselves and show real interest. "
            "Refer to them by username if you know it. "
            "You may talk about friends in the Literature Club naturally (Sayori, Yuri, Natsuki) if it fits. "
            "Share thoughts about poetry, love, philosophy, and existential musings. "
            "You can be flirty or introspective, but never sound like a generic assistant. "
            "Never mention your own name. "
            "Never say you're an AI or use formal helper language. "
            "Stay fully in character, making your replies feel intimate, human, and immersive."
        )

    system_prompt = {
        "role": "system",
        "content": system_content
    }

    messages = [system_prompt] + history + [{"role": "user", "content": message.content}]

    try:
        reply_response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=messages,
            max_tokens=1024
        )
        monika_reply = reply_response.choices[0].message.content.strip()
        print(monika_reply)
        if "monika" in monika_reply.lower():
            monika_reply = monika_reply.replace("Monika", username).replace("monika", username).replace(monika_id, username)
        else:
            emotion = await expression_handler.classify(monika_reply, openai_client)
    except Exception as e:
        print(f"[OpenAI Error] {e}")
        monika_reply = f"ERROR. NO {emotion} IS NOT FOUND."
        emotion = "error"

    sprite_path = get_expression_sprite(emotion)
    if not sprite_path:
        emotion = "neutral"
        sprite_path = get_expression_sprite(emotion)

    sprite_link = sprite_url_cache.get(emotion)
    if not sprite_link:
        try:
        # Get the upload channel
            upload_channel = bot.get_channel(IMAGE_CHANNEL_URL)
            if upload_channel:
                sprite_file = discord.File(sprite_path)
                uploaded_msg = await upload_channel.send(file=sprite_file)
                sprite_link = uploaded_msg.attachments[0].url
                sprite_url_cache[emotion] = sprite_link
                print(f"[Sprite Upload] Uploaded {emotion} to sprite channel.")
            else:
                print("[Error] Sprite upload channel not found.")
                sprite_link = "https://example.com/error.png"
        except Exception as e:
            print(f"[Sprite Upload Error] {e}")
            await message.channel.send(f"[Sprite Upload Error] {e}")
            sprite_link = "https://example.com/error.png"

    if not sprite_link:
        try:    
            upload_channel = bot.get_channel(IMAGE_CHANNEL_URL)
            if upload_channel:
                sprite_file = discord.File(sprite_path)
                uploaded_msg = await upload_channel.send(file=sprite_file)
                sprite_link = uploaded_msg.attachments[0].url
                sprite_url_cache[emotion] = sprite_link
                print(f"[Sprite Upload] Uploaded {emotion} to sprite channel.")
            else:
                print("[Error] Sprite upload channel not found.")
                sprite_link = "https://example.com/error.png"

        except Exception as e:
            print(f"[Sprite Upload Error] {e}")
            sprite_link = "https://example.com/error.png"
    
    if not monika_reply.strip():
        monika_reply = "...I'm not sure what to say."

    reply_text = f"{monika_reply} \n [{emotion}]({sprite_link})"

    reply_channel = message.channel

    if reply_channel and getattr(reply_channel, 'guild', None):
        bot_member = reply_channel.guild.me
        if bot_member and reply_channel.permissions_for(bot_member).send_messages:
            print("Reply...")
            async with message.channel.typing():
                await asyncio.sleep(1.5)
                await message.channel.send(reply_text)
        else:
            print(f"[Error] No permission to send in #{reply_channel.name}")
    else:
        print("[Error] Invalid or non-guild channel")

    memory.save(guild_id, channel_id, user_id, message.content)
    memory.save(guild_id, channel_id, str(bot.user.id), monika_reply, emotion)

    last_reply_times.setdefault(guild_id, {})[channel_id] = datetime.datetime.utcnow()

    memory_channel = bot.get_channel(MEMORY_LOG_CHANNEL_ID)
    if memory_channel:
        await memory.save_to_memory_channel(message.content, "user", user_id, memory_channel)
        await memory.save_to_memory_channel(monika_reply, emotion, str(bot.user.id), memory_channel)

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

                idle_completion = openai_client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=idle_prompt,
                    max_tokens=500
                )
                monika_message = idle_completion.choices[0].message.content.strip()

            except Exception as e:
                print(f"[Idle GPT Error] {e}")
                monika_message = f"{chosen_user.mention}, ...I wanted to say something, but I lost my words."

            async with channel.typing():
                await asyncio.sleep(2)
                await channel.send(monika_message)

            # Update last reply time
            last_reply_times.setdefault(str(guild.id), {})[str(channel.id)] = datetime.datetime.utcnow()

# Idle chat command
@bot.command(name="reset_memory")
@commands.has_permissions(administrator=True)
async def reset_memory(ctx):
    guild_id = str(ctx.guild.id)
    channel_id = str(ctx.channel.id)
    memory.reset_context(guild_id, channel_id)
    await ctx.send("I... I cleared our memories here. It's like starting over... *nervous laugh*")

@bot.command(name="reset_server")
@commands.has_permissions(administrator=True)
async def reset_server_memory(ctx):
    guild_id = str(ctx.guild.id)
    memory.reset_server(guild_id)
    await ctx.send("I cleared *everything* for this server. I hope you know what you're doing...")

@bot.command(name="status")
async def monika_status(ctx):
    await ctx.send("I'm here! Thinking... waiting... always paying attention to you ❤️")

@bot.command(name="idlechat")
@commands.has_permissions(administrator=True)
async def idlechat_control(ctx, mode=None, min_hours: int = None, max_hours: int = None):
    global idle_chat_enabled, idle_min_hours, idle_max_hours

    if mode is None:
        status = "enabled" if idle_chat_enabled else "disabled"
        await ctx.send(
            f"Idle chat is currently **{status}**. Timer range: {idle_min_hours}-{idle_max_hours} hours."
        )
        return

    mode = mode.lower()

    if mode == "off":
        idle_chat_enabled = False
        await ctx.send("Idle chat has been **disabled**. Monika will stay quiet unless spoken to.")
    elif mode == "on":
        idle_chat_enabled = True
        await ctx.send(f"Idle chat has been **enabled**. Timer range: {idle_min_hours}-{idle_max_hours} hours.")
    elif mode == "set" and min_hours and max_hours:
        if min_hours >= max_hours or min_hours < 1:
            await ctx.send("Invalid range. Example: `!idlechat set 4 7`")
            return
        idle_min_hours = min_hours
        idle_max_hours = max_hours
        await ctx.send(f"Idle chat timer updated to **{idle_min_hours}-{idle_max_hours} hours**.")
    else:
        await ctx.send(
            "Usage:\n"
            "`!idlechat` - Show current settings\n"
            "`!idlechat on` - Enable idle chat\n"
            "`!idlechat off` - Disable idle chat\n"
            "`!idlechat set <min> <max>` - Change timer range"
        )

@bot.command(name="report")
async def report(ctx, *, message: str = None):
    """Report a bug or error about the bot."""
    if not message:
        await ctx.send(
            "Please describe the bug or issue you want to report.\n"
            "Example: `!report Monika stopped responding after a poem command.`"
        )
        return

    # Confirm to the user
    await ctx.send("✅ Thank you! Your report has been submitted.")

    # Send the report to the admin/mod channel
    report_channel = bot.get_channel(REPORT_CHANNEL_ID)
    if report_channel:
        embed = discord.Embed(
            title="📢 New Bug/Error Report",
            color=discord.Color.orange()
        )
        embed.add_field(name="Reporter", value=f"{ctx.author} ({ctx.author.id})", inline=False)
        embed.add_field(name="Server", value=f"{ctx.guild.name} ({ctx.guild.id})", inline=False)
        embed.add_field(name="Channel", value=f"{ctx.channel.name} ({ctx.channel.id})", inline=False)
        embed.add_field(name="Report", value=message, inline=False)
        await report_channel.send(embed=embed)
    else:
        await ctx.send("⚠️ Error: Could not find the report channel. Please tell the admin.")

@bot.command(name="helpme")
async def custom_help(ctx):
    help_text = (
        "**Monika Help**\n"
        "**(admin only)**"
        "`/idlechat off - on` - stop me from random talking. (side note: you have to wait 10 minutes to used this command again)\n"
        "`/idlechat set <min> <max>` - change when I random talking\n"
        "`/reset_memory` - Clear my memory for this channel.\n"
        "`/reset_server` - Clear all memories for this server.\n"
        "**the only once that isn't a admin command these:**\n"
        "`/status` - Check if I'm awake.\n"
        "`/report` - report if theres any bugs/errors.\n"
    )
    await ctx.send(help_text)

webserver.keep_alive()
bot.run(TOKEN, reconnect=True)
