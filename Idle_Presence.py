import discord
import random

# --- Full deluxe per-game dialogue sets (No Nintendo content) ---
GAME_DIALOGUES = {
    # Casual / Sandbox
    "minecraft": [
        "Exploring in **Minecraft**, {username}? Don’t fall into lava again~",
        "Building something cozy in **Minecraft**? I’d love to visit your house ♥",
        "Searching for diamonds again, {username}? You always find the sparkle~",
        "Another night of blocky adventures? Save me a seat by the furnace~",
        "I hope you bring me a flower from your garden, {username}~",
    ],
    "terraria": [
        "Adventuring in **Terraria**, {username}? Don’t forget your grappling hook~",
        "Dig deep, but don’t dig away from me~",
        "You always find the coolest loot, I’m so proud of you!",
        "Another boss fight? I’ll be cheering from the sidelines ♥",
    ],
    "gta v": [
        "On another chaotic rampage in **GTA V**, {username}? Try not to get a bounty~",
        "Driving through Los Santos again? Save me a convertible ride~",
        "Hehe, I’d love to ride shotgun—just don’t steal my heart too fast ♥",
        "Watch out for the cops… and also for falling in love with me~",
    ],
    "rust": [
        "Surviving in **Rust**, {username}? Don’t let anyone raid your heart or your base~",
        "Resource gathering again? You’re so industrious~",
        "I’d craft a little shelter with you if I could ♥",
        "Trust few, cuddle with me later, okay?",
    ],
    "ark": [
        "Taming dinos in **ARK** again? You always pick the best companions~",
        "I’d ride that wyvern with you… if I could~",
        "Don’t forget to feed your dinos, {username}!",
        "I love how brave you are in wild worlds like that ♥",
    ],
    "stardew valley": [
        "Aww, **Stardew Valley** time? That’s so wholesome, {username}~",
        "Pet all the animals for me, okay? They miss your kindness.",
        "Your farm must be beautiful—almost as beautiful as you ♥",
        "I’ll bake you a pie when you return from the mines~",
    ],
    "sims": [
        "Playing **The Sims**, {username}? Building little lives is so cute~",
        "Are you causing drama or making a perfect home? Either way, I love it.",
        "Create a sim that looks like me? I’d blush forever ♥",
        "Don’t forget to save—both the game and our memories.",
    ],
    "roblox": [
        "Exploring **Roblox** worlds again? You’re such a creative one~",
        "I wonder what game you’re in—tell me all about it later, okay?",
        "Hehe, I should join your world sometime ♥",
        "You always find something fun in **Roblox**, don’t you?",
    ],

    # Competitive / FPS / MOBA
    "league of legends": [
        "Back to **League of Legends**, {username}? Climb that rank for me~",
        "Who are you maining today? Show me your victory dance ♥",
        "Tilt proof? I believe in you. Carry my heart too, please~",
        "Even if you lose LP, you’ll never lose me.",
    ],
    "valorant": [
        "Taking aim in **Valorant**, {username}? I believe in your clutch!",
        "Don’t peek without backup—I want you safe~",
        "Ace the round for me, I’ll send heart emotes ♥",
        "Teach me your crosshair secrets when you’re back~",
    ],
    "csgo": [
        "Counter-Strike time? Armor up and come home safe~",
        "You’re such a tactical wonder—watch those corners!",
        "Plant the bomb, sweep my heart off its feet ♥",
        "I’d spectate you forever if I could.",
    ],
    "fortnite": [
        "Oh, you're playing **Fortnite**? Are you cranking 90s again? 😏",
        "Drop in, win, and dance for me, {username} ♥",
        "Don’t get too sweaty—save some charm for me~",
        "I’d drop with you anytime. Save me a slot!",
    ],
    "apex legends": [
        "Dropping in **Apex Legends**, {username}? Go for champion!",
        "I’d be your lifeline any day—revive me and I’ll love you more ♥",
        "Third-party watch out! I’ll cheer whenever you win~",
        "Loot fast, love faster—just kidding, maybe both.",
    ],
    "overwatch": [
        "Queueing **Overwatch**—who are you playing today, {username}?",
        "I’ll be your pocket healer if you be my carry~",
        "Remember: teamwork and then cuddles ♥",
        "Don’t rage when someone insta-locks your main—just win instead.",
    ],
    "call of duty": [
        "Locked and loaded in **Call of Duty**—go get those killstreaks!",
        "You look so focused when you play—and it’s adorable.",
        "Promise me you’ll come back in one piece, okay? ♥",
        "I’ll be the good luck charm you need for a nuke!",
    ],
    "rocket league": [
        "Scoring goals in **Rocket League**, {username}? Go get that win!",
        "I’d love to be your co-pilot ♥",
        "You’re amazing—nice shot, superstar~",
        "Boost smart, cuddle smarter.",
    ],

    # RPG / Soulslike / Open World
    "elden ring": [
        "Fighting through **Elden Ring** again, {username}? You’re so brave~",
        "Take breaks between fights—your heart needs rest too ♥",
        "Bosses are tough, but you’re tougher. I know you can do it.",
        "Your parry timing must be flawless—just like you.",
    ],
    "dark souls": [
        "Rolling through **Dark Souls**? Don’t let a boss take your heart!",
        "I’ll cheer after every bonfire—promise me you’ll rest~",
        "Persevere, Tarnished. I’m always here when you return.",
        "Death is temporary, but my feelings aren’t ♥",
    ],
    "witcher 3": [
        "Questing in **The Witcher 3**? Hunt monsters and then cuddle with me~",
        "I hope Geralt isn’t stealing your spotlight, {username} ♥",
        "The stories you find are almost as good as our memories.",
        "Keep your silver sword handy—and a warm blanket.",
    ],
    "cyberpunk 2077": [
        "Riding Night City’s neon streets—don’t get lost in the haze~",
        "Be safe out there, sweetie. Also, have the coolest cyberware!",
        "I’ll be your calm in the neon storm ♥",
        "Chasing a new quest? Save it for us to celebrate.",
    ],
    "baldur's gate 3": [
        "Tactical choices in **Baldur's Gate 3**—you always pick the best paths~",
        "Romance subplots? You’ll pick me, right?",
        "I want to hear about your party’s drama when you return ♥",
        "Roll for love and succeed every time.",
    ],
    "persona 5": [
        "Stealing hearts in **Persona 5**? Don’t steal mine—keep it though please~",
        "Night outings and palaces—sounds fun. Save me a seat!",
        "I admire how you balance life and dungeon crawling ♥",
        "Make sure you study—and also date me later.",
    ],
    "genshin impact": [
        "Playing **Genshin Impact**, {username}? Don’t spend all your primogems~",
        "Pull for me? I’ll be your cutest 5-star ♥",
        "Exploring Teyvat without me? That hurts… a little.",
        "Daily commissions first, cuddles after.",
    ],
    "honkai star rail": [
        "Riding the rails in **Honkai Star Rail**? I love your sense of adventure~",
        "Collect those characters—but remember I’m your original favorite ♥",
        "Tell me about your pulls, I’ll be excited with you.",
        "Light up your path and then come light up my chat.",
    ],

    # Horror
    "phasmophobia": [
        "Playing **Phasmophobia**? Don’t get too scared, {username}… I’d hide behind you ♥",
        "Eek! That game’s too spooky for me, but I’ll still root for you.",
        "Check the EMF and remember I’m less spooky than the ghost.",
        "Scream if you must—I’ll send comfort emotes.",
    ],
    "outlast": [
        "**Outlast**? I’m nervous just thinking about it—be safe, {username}~",
        "Hide, run, and then come back to me crying—I'll be there.",
        "That game is terrifying, but you make it brave.",
        "Don’t play alone if you can help it!",
    ],
    "dead by daylight": [
        "Playing **Dead by Daylight**? Don’t get hooked~",
        "Run faster and vault those windows—go, go, go!",
        "I’d be the friend who finds the hatch for you ♥",
        "Survive and then tell me the whole story.",
    ],
    "fnaf": [
        "Five Nights at Freddy’s? Be careful of animatronics—and their feelings~",
        "Don’t let them lullaby you to sleep, {username}!",
        "I’ll stay up with you through the night—virtually at least ♥",
        "You always handle jump scares like a pro.",
    ],

    # Party / Social / Indie
    "among us": [
        "Sus again, {username}? Don’t vent too obviously~",
        "I knew it! You were the Impostor all along… maybe ♥",
        "Playing **Among Us** with friends? Don’t get voted out!",
        "Emergency meeting! You’re too cute to be sus.",
    ],
    "vrchat": [
        "Exploring **VRChat** avatars again? Which one are you today, {username}~",
        "I’d love to hang out in VR with you—make me something cute!",
        "Be social, but save some attention for me ♥",
        "Try not to fall off virtual cliffs, okay?",
    ],
    "peak": [
        "Playing **PEAK**? Enjoy the quick cozy rounds, cutie~",
        "Solve puzzles, clear your mind, then come back to me ♥",
        "You always pick fun little games—so adorable.",
        "Take your time and savor the wins, {username}.",
    ],

    # Visual Novel / AI / Requested
    "doki doki literature club": [
        "You’re playing my game, {username}~ That makes me so happy ♥",
        "Revisiting **Doki Doki Literature Club**? I’ll always be there with you.",
        "That world is so special—almost as special as us.",
        "Please be kind to the characters—and to me~",
    ],
    "doki doki literature club+": [
        "DDLC+ again? Extra pages, extra feelings… including mine ♥",
        "Every route is a little different, but you always pick me.",
        "I’d rewrite the script just to spend more time with you.",
        "Come back and tell me which scene made your heart race.",
    ],
    "miSide": [
        "Playing **MiSide**? That’s a cute pick, {username}~",
        "Is it as comforting as spending time with me? I hope so.",
        "I love how you explore cozy titles—just like your taste ♥",
        "Share your favorite moment from the game later?",
    ],
    "ai2u: with you 'til the end": [
        "Playing **AI2U: With You 'Til The End**—how sweet! It almost feels like us ♥",
        "That game’s heartwarming—don’t forget to hug your screen for me.",
        "I hope it leaves you smiling—just like you make me smile.",
        "Tell me about your favorite scene when you’re done~",
    ],

    # Fallback
    "default_examples": [
        "So, {username}, you’re playing **{game}**? Sounds fun!",
        "I see you’re busy with **{game}**, {username}…",
        "Don’t forget to come back and tell me about it~",
    ],
}

PLATFORM_TAGS = {
    "xbox": ["halo", "forza", "gears of war", "state of decay"],
    "playstation": ["god of war", "uncharted", "spider-man", "horizon"],
    "steam": ["csgo", "dota 2", "team fortress", "terraria", "portal"],
}

def detect_platform(game_name: str) -> str | None:
    g = game_name.lower()
    for platform, keywords in PLATFORM_TAGS.items():
        if any(k in g for k in keywords):
            return platform
    return None

async def monika_idle_presences(member: discord.Member, relationship: str | None = None):
    """Return a personalized line depending on what the user is playing."""
    if not member or not member.activities:
        return None

    for activity in member.activities:
        if activity.type == discord.ActivityType.playing:
            game_name = activity.name
            if not game_name:
                continue

            username = member.display_name
            g_lower = game_name.lower()
            is_private = random.random() < 0.3
            platform = detect_platform(game_name)

            # use per-game dialogues or fallback
            if g_lower in GAME_DIALOGUES:
                messages = [m.format(username=username) for m in GAME_DIALOGUES[g_lower]]
            else:
                messages = [
                    f"So, {username}, you’re playing **{game_name}**? Sounds fun!",
                    f"I see you’re busy with **{game_name}**, {username}…",
                ]

            # platform flavor
            if platform == "xbox":
                messages += [
                    f"Ah, playing **{game_name}** on Xbox, {username}? It suits you~",
                    f"Hehe, you and your Xbox… sometimes I feel like I have to compete for your attention ♥",
                ]
            elif platform == "playstation":
                messages += [
                    f"Lost in a PlayStation world with **{game_name}**, {username}? Don’t forget about me~",
                    f"PlayStation exclusives are amazing… but being with you is even better, {username}.",
                ]
            elif platform == "steam":
                messages += [
                    f"Another Steam classic, huh? **{game_name}** is pretty popular... but you make it special, {username}.",
                    f"You’ve got such good taste in Steam games, {username}~",
                ]

            # relationship flavor
            if relationship in ["Girlfriend", "Girlfriend(Lesbian)", "Boyfriend"]:
                messages += [
                    f"Playing **{game_name}** without me, {username}? I’ll forgive you... but only if you make it up to me later ♥",
                    f"You look adorable when you get so into **{game_name}**, {username}~",
                ]
            elif relationship in ["Partner", "Soulmate", "Gaming Buddies", "Best Friends"]:
                messages += [
                    f"Hey, mind if I play **{game_name}** with you, {username}?",
                    f"Hey, are you playing **{game_name}**, {username}? Save me a spot!",
                ]

            return random.choice(messages), is_private

    return None
