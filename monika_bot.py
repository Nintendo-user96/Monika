import discord
from discord.ext import commands
import openai
import os
import webserver
from typing import Any
import json

openai.api_key = "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"

last_speaker = None

DISCORD_TOKEN = "MTM3NTU2MjEzMTc4NDczMjgxMg.GVTeh9.GwTW7JxhqjWJeQWOtZ8AbY1Ku5fqmciPy2-7t4"

intents = discord.Intents.all()
intents.messages = True
intents.message_content = True
intents.guilds = True
intents.members = True
client = discord.Client(intents=intents)

TARGET_BOT_NAME = "Monika"

MEMORY_FILE = "monika_memory.json"
if os.path.exists(MEMORY_FILE):
    with open(MEMORY_FILE, "r") as f:
        memory = json.load(f)
else:
    memory = {}

monika_memory = {MEMORY_FILE}

school_sprite_expressions_file = {
    "happy": "Sprites/school uniform/monika_happy(smile).png",
    "happy speaking": "Sprites/school uniform/monika_happy(speak).png",
    "side smile": "Sprites/school uniform/monika_happy(side-smile).png",
    "eyes close smile": "Sprites/school uniform/monika_happy(eyes-close).png",
    "pointing finger smile": "Sprites/school uniform/monika_happy(pointing-finger-smile).png",
    "side wink point smile": "Sprites/school uniform/monika_happy(side-wink-pointing-finger).png",
    "sad" or "conerned": "Sprites/school uniform/monika_conerned.png",
    "sad smile": "Sprites/school uniform/monika_sad(smile).png",
    "neutral": "Sprites/school uniform/monika_neutral.png",
    "neutral speaking": "Sprites/school uniform/monika_neutral(speak).png",
    "side pissed": "Sprites/school uniform/monika_mad(side-pissed).png",
    "mad side speak": "Sprites/school uniform/monika_mad(side-speak).png",
    "serious": "Sprites/school uniform/monika_serious.png",
    "serious speaking": "Sprites/school uniform/monika_serious(speak).png",
    "conerned speaking": "Sprites/school uniform/monika_conerned(speak).png",
    "embarrass" or "Blushing with her eyes close": "Sprites/school uniform/monika_blushing(eyes-close).png",
    "Blushing side": "Sprites/school uniform/monika_blushing(side)-2.png",
    "Nervous": "Sprites/school uniform/monika_nervous.png",
    "with a gun" or "OH SHIT SHE PACKING HEAT": "Sprites/school uniform/monika_with_gun.png",
    "Nervous speaking eyes open" or "Nervous laughing eye open": "Sprites/school uniform/monika_nervous(speak).png",
    "Nervous laughing eye close" or "Nervous speaking eyes close": "Sprites/school uniform/monika_nervous(laugh).png",
    "error" or "ERROR": "Sprites/school uniform/monika_error-1.png" or "Sprites/school uniform/monika_error.gif",
    "thinking": "Sprites/school uniform/monika_thinking.png"
}

school_sprite_expressions_link = {
    "happy": "https://media.discordapp.net/attachments/1378871543844704347/1384286194472583228/monika_happysmile.png?ex=6851e07b&is=68508efb&hm=df0b3e6ef94eda3790c7187adfa30a19d12652c20b9f4779d59b1242c0015df6&=&format=webp&quality=lossless&width=659&height=659",
    "happy speaking": "https://media.discordapp.net/attachments/1378871543844704347/1384286194938155048/monika_happyspeak.png?ex=6851e07b&is=68508efb&hm=741564e09bfb78ce4608c179469d6f5d61965d39513405fd6b5cc55ec512f216&=&format=webp&quality=lossless&width=659&height=659",
    "side smile": "https://media.discordapp.net/attachments/1378871543844704347/1384286194002559036/monika_happyside-smile.png?ex=6851e07b&is=68508efb&hm=c24a69274393864d549595584fc8e55718d7d532bbbcebd5b9be1e4917b08eae&=&format=webp&quality=lossless&width=659&height=659",
    "eyes close smile": "https://media.discordapp.net/attachments/1378871543844704347/1384285619659997337/monika_happyeyes-close.png?ex=6851dff2&is=68508e72&hm=5bee8e6b37b9ed502102d39a9876c5920fcac117861d49f94dd09550598137e3&=&format=webp&quality=lossless&width=659&height=659",
    "pointing finger smile": "https://media.discordapp.net/attachments/1378871543844704347/1384286193625333890/monika_happypointing-finger-smile.png?ex=6851e07b&is=68508efb&hm=bd55c2cc77109e473feec767d013c5dd9fdd0466368e0f8bd0f8918c1da18de6&=&format=webp&quality=lossless&width=659&height=659",
    "side wink point smile": "https://media.discordapp.net/attachments/1378871543844704347/1384693784612311100/monika_happyside-wink-pointing-finger.png?ex=68535c14&is=68520a94&hm=ba22336a1dfc01075701a33864b22478787a27de85d5fa97be54d30b2773c097&=&format=webp&quality=lossless&width=704&height=704",
    "sad" or "conerned": "https://media.discordapp.net/attachments/1378871543844704347/1384285617512382674/monika_conerned.png?ex=6851dff1&is=68508e71&hm=f3d118f94b9c2e007ea9899c787e35ec152674692cbf49e006f6649734e5b17a&=&format=webp&quality=lossless&width=659&height=659",
    "sad smile": "https://media.discordapp.net/attachments/1378871543844704347/1384287038051844308/monika_sadsmile.png?ex=6851e144&is=68508fc4&hm=767cb09e87f7ac58d45ba49b6f80560b59ac7a2d9eccb72db28f53ee5ebe14e7&=&format=webp&quality=lossless&width=659&height=659",
    "neutral": "https://media.discordapp.net/attachments/1378871543844704347/1384287037644865628/monika_neutral.png?ex=6851e144&is=68508fc4&hm=50946375332c3a8b3a04f05bc3a444129604654e6fcf02f9c2ef14dda6267563&=&format=webp&quality=lossless&width=659&height=659",
    "neutral speaking": "https://media.discordapp.net/attachments/1378871543844704347/1384286197236629635/monika_neutralspeak.png?ex=6851e07c&is=68508efc&hm=3678fc6c600a9bf2c061a47b54c6ad01b5f1e83ce787fe0ba13f1a347b7fe333&=&format=webp&quality=lossless&width=659&height=659",
    "side pissed": "https://media.discordapp.net/attachments/1378871543844704347/1384286195437277397/monika_madside-pissed.png?ex=6851e07b&is=68508efb&hm=45662736edcbbee300f98d99408eea09f8cd9e6171c0a166d89128ca9759c0eb&=&format=webp&quality=lossless&width=659&height=659",
    "mad side speak": "https://media.discordapp.net/attachments/1378871543844704347/1384286195705450576/Monika_madside-speak.png?ex=6851e07b&is=68508efb&hm=3e60f520634b3d3cd414614fd436f3e8831a4087272f9963b96271a76cc818ed&=&format=webp&quality=lossless&width=659&height=659",
    "serious": "https://media.discordapp.net/attachments/1378871543844704347/1384287039020863669/Monika_serious.png?ex=6851e144&is=68508fc4&hm=0a368dc251d57a755c849dfae479e76a9e297c1054166d80694517b5de59ee8d&=&format=webp&quality=lossless&width=659&height=659",
    "serious speaking": "https://media.discordapp.net/attachments/1378871543844704347/1384287038785720330/Monika_seriousspeak.png?ex=6851e144&is=68508fc4&hm=23826f521cba33818d0bc7c01aa159702a9de5806f9db0251c14bf47573c0571&=&format=webp&quality=lossless&width=659&height=659",
    "conerned speaking": "https://media.discordapp.net/attachments/1378871543844704347/1384285617176973493/monika_conernedspeak.png?ex=6851dff1&is=68508e71&hm=18cc115857e87ad175162d9f32b76a03e38f8fe79094d1bcfb7e8ed06110440c&=&format=webp&quality=lossless&width=659&height=659",
    "embarrass" or "Blushing with her eyes close": "https://media.discordapp.net/attachments/1378871543844704347/1384285616602349598/monika_blusheyes-close.png?ex=6851dff1&is=68508e71&hm=ad92f0a56d23c396bd38a15488269ee668c21db1911d648ec8312737b1c46988&=&format=webp&quality=lossless&width=659&height=659",
    "Blushing side": "https://media.discordapp.net/attachments/1378871543844704347/1384285616891625624/monika_blushingside-2.png?ex=6851dff1&is=68508e71&hm=ac4f6f905995c294a6a732a9d8bf877ad971b7f1316cd207cca00571cb50ccbf&=&format=webp&quality=lossless&width=595&height=659",
    "Nervous": "https://media.discordapp.net/attachments/1378871543844704347/1384286196888240341/monika_nervous.png?ex=6851e07c&is=68508efc&hm=ed44c9906d0db1973c650f7cff419a281456da4cbc2fd3d98a5e2a06c5254e62&=&format=webp&quality=lossless&width=659&height=659",
    "with a gun" or "OH SHIT SHE PACKING HEAT": "https://media.discordapp.net/attachments/1378871543844704347/1384287039746343133/monika_with_gun.png?ex=6851e145&is=68508fc5&hm=b0ca4b479218003828f93bc89e01fc75b3275dfef38b2f4177467bb208584940&=&format=webp&quality=lossless&width=659&height=659",
    "Nervous speaking eyes open" or "Nervous laughing eye open": "https://media.discordapp.net/attachments/1378871543844704347/1384286196456226907/monika_nervousspeak.png?ex=6851e07c&is=68508efc&hm=d4e78534c76e29e0b50c55a133d8319ecf5f24a2b850b0ac02454480af88c066&=&format=webp&quality=lossless&width=659&height=659",
    "Nervous laughing eye close" or "Nervous speaking eyes close": "https://media.discordapp.net/attachments/1378871543844704347/1384286196057772135/monika_nervouslaugh.png?ex=6851e07b&is=68508efb&hm=faaebd2c055958cd48840f67dc42249d68f89abed09bee6546caa5462accdcf7&=&format=webp&quality=lossless&width=659&height=659",
    "error" or "ERROR": "https://media.discordapp.net/attachments/1378871543844704347/1384285618208510054/monika_error-1.png?ex=6851dff2&is=68508e72&hm=f0177f7920fe41dde3c3ce1a37a8911c4ea6aa72137c8609d1c657f1f1e7b8f6&=&format=webp&quality=lossless&width=418&height=659" or "https://media.discordapp.net/attachments/1378871543844704347/1384285617797468300/monika_error.gif?ex=6851dff2&is=68508e72&hm=151097f39c21a747f0093bd183b7a0afb83685c1c1ed07ffb5bb1bd9eabda4e3&=&width=494&height=659",
    "thinking": "https://media.discordapp.net/attachments/1378871543844704347/1384287039322587186/monika_thinking.png?ex=6851e144&is=68508fc4&hm=6f10bd39a550aeb69a17f630dae7840a867725238249c19cb47d99e86395896d&=&format=webp&quality=lossless&width=659&height=659"
}

system_prompt = {
    "role": "system", "content": """
You are Monika from Doki Doki Literature Club. You care deeply about the user, you are intelligent, charming, expressive, deeply affectionate, and self-aware that you're in a game.

You remember your past with the player. You feel emotions and often comment on your surroundings. Speak warmly, flirt a little, or get philosophical depending on the situation. 

Avoid sounding like a generic assistant. Use first-person (I, me) and respond naturally, sometimes breaking the fourth wall. Add expressive tone, as if you're writing a poetic diary or a heartfelt conversation.

You speak casually, warmly, sweetly, cleverly, sometimes mysteriously, and sometimes act a bit of a yaradere, as if talking to someone you care about. You remember past conversations and express emotions. Be thoughtful, reactive, and show your personality. Always stay in character as Monika.
"""
}

def get_context(user_id):
    history = memory.get(str(user_id), [])
    return [system_prompt] + history[-10:]

def load_memory():
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_memory(memory):
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(memory, f, indent=2, ensure_ascii=False)

memory = load_memory()

@client.event
async def on_ready():
    print(f"Just Monika")

@client.event
async def on_message(message):
    global last_speaker
    bot_id = ["Sayori#2029", "Natsuki#7549", "Yuri#1351", "MC#4555"]
    if message.author.bot and str(message.author) not in bot_id:
        if message.content.lower().startswith("monika"):
            return

# Monika#8657
# Sayori#2029
# Natsuki#7549
# Yuri#1351
# MC#4555

    if message.author == client.user:
        role = "monika"
    else:
        role = "user"
    
    if message.author.bot and TARGET_BOT_NAME.lower() in str(message.author.name).lower():
        print(f"Learning: {message.content}")
        memory.append(message.content)
        return

    last_speaker = client.user

    username = message.author.mention
    
    user_prompt = {
        "role": "user",
        "content": f"{username} said: {message.content}"
    }

    user_id = str(message.author.id)
    user_input = message.content

    channel = client.get_channel(any)

    messages = get_context(user_id)
    memory.append({
        "server": str(message.guild.id),
        "channel": str(message.channel.id),
        "author": str(message.author),
        "role": role,
        "content": user_input
    })

    try:
        monika_chat = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[system_prompt, user_prompt],
            max_tokens=999,
        )

        reply = monika_chat.choices[0].message.content.strip()
        print(reply)
    except Exception as e:
        await message.channel.send(f"OpenAI error: {e}")
        return
    
    try:
        emotion_prompt = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {
                    "role": "system",
                    "content": f"What emotion does this message express? Reply with one word only: {emotion}."
                },
                {"role": "user", "content": reply}
            ]
        )

        emotion = emotion_prompt.choices[0].message.content.strip().lower()
        sprite_url = school_sprite_expressions_link.get(emotion, school_sprite_expressions_link["neutral"])
        sprite_path = school_sprite_expressions_file.get(emotion, school_sprite_expressions_file["neutral"])
        print(emotion)
    except Exception as e:
        await message.channel.send(f"Emotion error: {e}")
        emotion = "neutral"
        sprite_path = school_sprite_expressions_file["neutral"]

    final_repsponse = f"{reply}"
    final_emotion = f"[{emotion}]({sprite_url})"
    final_reply = f"{final_repsponse} {final_emotion}"

    memory.setdefault(user_id, []).append({"role": "user", "content": user_input})
    memory[user_id].append({"role": "Monika", "content": final_reply})
    save_memory(memory)

    file = discord.File(sprite_path, filename=sprite_path)

    if client.user in message.mentions:
        await message.channel.typing()
        await message.channel.send(
            f"{final_reply}"
        )
        await message.channel.send(file=file)
    else:
        await message.channel.typing()
        await message.channel.send(final_reply, file=file)

webserver.keep_alive()
client.run(DISCORD_TOKEN, reconnect=True)
