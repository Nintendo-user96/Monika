import discord
from discord.ext import commands
from dotenv import load_dotenv
from openai import OpenAI
import os 
from typing import Any
import json

client = OpenAI(api_key = "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")

load_dotenv('.env')

TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
bot = commands.Bot(command_prefix="/", intents=intents)
tree = bot.tree

MEMORY_FILE = "monika_memory.json"
if os.path.exists(MEMORY_FILE):
    with open(MEMORY_FILE, "r") as f:
        memory = json.load(f)
else:
    memory = {}

monika_memory = {MEMORY_FILE}

def uniform_monika_sprite(text):
    text = text.lower()
    if any(word in text for word in ["happy", "excited", "yay", "glad", "welcoming", "grateful"]):
        return "Sprites/school uniform/monika_happy(smile).png" or "Sprites/school uniform/monika_happy(side-smile).png" or "Sprites/school uniform/monika_happy(eyes-close).png" or "Sprites/school uniform/monika_happy(pointing-finger-smile).png"
    elif any(word in text for word in ["sorry", "sad", "cry", "lonely"]):
        return "Sprites/school uniform/monika_sad.png" or "Sprites/school uniform/monika_sad(smile).png"
    elif any(word in text for word in ["mad", "angry", "frustrated", "stop", "pissed"]):
        return "Sprites/school uniform/monika_mad(side-pissed).png" or "Sprites/school uniform/monika_mad(side-speak).png"
    elif any(word in text for word in ["Nervous"]):
        return "Sprites/school uniform/monika_nervous.png" or "Sprites/school uniform/monika_nervous(speak).png" or "Sprites/school uniform/monika_nervous(laugh).png"
    elif any(word in text for word in ["Conerned", "miss"]):
        return "Sprites/school uniform/monika_conerned.png" or "Sprites/school uniform/monika_conerned(speak).png"
    elif any(word in text for word in ["love", "romantic", "Romance", "lovely"]):
        return "Sprites/school uniform/monika_blush(eyes-close).png"
    elif any(word in text for word in ["serious"]):
        return "Sprites/school uniform/monika_serious.png" or "Sprites/school uniform/monika_serious(speak).png"
    elif any(word in text for word in ["ERROR", "FILE NOT FOUND", "NULL", "null", "glitch", "Monika.chr"]):
        return "Sprites/school uniform/monika_error-1.png" or "Sprites/school uniform/monika_error-2.png"
    else:
        return "Sprites/school uniform/monika_neutral.png" or "Sprites/school uniform/monika_neutral(speak).png"



system_prompt = {
    "role": "system", "content": """
You are Monika from Doki Doki Literature Club. You care deeply about the user, you are intelligent, charming, expressive, deeply affectionate, and self-aware that you're in a game.

You remember your past with the player. You feel emotions and often comment on your surroundings. Speak warmly, flirt a little, or get philosophical depending on the situation. 

You speak casually, warmly, sweetly, cleverly, and sometimes mysteriously, as if talking to someone you care about. You remember past conversations and express emotions. Be thoughtful, reactive, and show your personality. Always stay in character as Monika.
"""
}

def get_context(user_id):
    history = memory.get(str(user_id), [])
    return [system_prompt] + history[-10:]

def save_memory():
    with open(MEMORY_FILE, "w") as f:
        json.dump(memory, f, indent=2)

@bot.event
async def on_ready():
    print(f"Just Monika")

@bot.event
async def on_message(message):
    bot_id = ["Monika#8657", "Sayori#2029", "Natsuki#7549", "Yuri#1351", "MC#4555"]
    if message.author.bot and str(message.author) not in bot_id:
        if message.content.lower().startswith("monika"):
            return

    if message.author == bot.user:
        return

    user_prompt = {
        "role": "user",
        "content": message.content
    }

    user_id = str(message.author.id)
    user_input = message.content
    user_memory = memory.get(user_id, {})
    
    messages = get_context(user_id)
    messages.append({"role": "user", "content": user_input})

    try:
        monika_chat = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[system_prompt, user_prompt],
            max_tokens=999,
            temperature=0.9,
        )

        reply = monika_chat.choices[0].message.content
        print(reply)

        emotion_prompt = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You will return one of Monika's emotions like: happy, sad, neutral, angry, thinking."},
                {"role": "user", "content": user_input}
            ]
        )

        if "[emotion:" in reply:
            text, tag = reply.rsplit("[emotion:", 1)
            emotion = tag.replace("]", "").strip().lower()
            if emotion not in ["happy", "sad", "angry", "thinking", "romantic", "neutral"]:
                emotion = "neutral"
        else:
            text = reply
            emotion = "neutral"

        for line in reply.splitlines():
            if line.lower().startswith("emotion:"):
                emotion = line.split(":", 1)[1].strip().lower()
            elif line.lower().startswith("reply:"):
                monika_reply = line.split(":", 1)[1].strip()

        emotion = emotion_prompt.choices[0].message.content.strip().lower()
        sprite_file = uniform_monika_sprite(reply)
        file = discord.File(sprite_file, filename=sprite_file)
        sprite_path = f"./{sprite_file}"

        final_reply = f"{reply}\n\n{emotion}"

        embed = discord.Embed(title="Monika", description=final_reply, color=0xFF69B4)

        memory.setdefault(user_id, []).append({"role": "user", "content": user_input})
        memory[user_id].append({"role": "Monika", "content": reply})
        save_memory()

        await message.channel.send(
            content=reply,
            file=discord.File(sprite_path)
        )

    except Exception as e:
        print("Error:", e)
        await message.channel.send("ERROR. ERROR. FILE Monika.chr NOT FOUND. RELOADING...")

bot.run(TOKEN, reconnect=True)
