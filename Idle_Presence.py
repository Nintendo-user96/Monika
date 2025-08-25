import discord
import random

# Simple tags for game "types" (can be expanded later)
GAME_KEYWORDS = {
    "fps": [
        "valorant", "csgo", "counter-strike", "call of duty", "cod", "overwatch",
        "apex", "apex legends", "battlefield", "rainbow six", "halo", "destiny 2", "marvel rivals"
    ],
    "mmo": [
        "world of warcraft", "final fantasy", "ffxiv", "runescape", "guild wars",
        "new world", "elder scrolls online", "eso", "lost ark"
    ],
    "horror": [
        "resident evil", "outlast", "phasmophobia", "dead by daylight", "saeko: giantess dating sim", "deceit 2",
        "alien isolation", "silent hill", "amnesia", "the forest", "sons of the forest", "buckshot roulette",
        "the quarry", "until dawn", "lethal company", "r.e.p.o", "fnaf", "five nights at freddy's", "miside" , "baldi's basics"
    ],
    "casual": [
        "minecraft", "stardew valley", "roblox", "sims", "peak", "goofy gorillas",
        "terraria", "fall guys", "cookie clicker", "slime rancher", "powerwash simulator", "vrchat"
    ],
    "competitive": [
        "league of legends", "lol", "dota", "dota 2", "rocket league", "fortnite",
        "pubg", "smite", "paladins", "multiversus", "brawlhalla"
    ],
    "rpg": [
        "elden ring", "dark souls", "bloodborne", "sekiro", "cyberpunk 2077",
        "witcher", "persona", "persona 5", "genshin impact", "honkai star rail",
        "baldur", "baldur's gate", "dragon age", "mass effect", "skyrim", "heartbound", "castle crashers"
    ],
    "sports": [
        "fifa", "madden", "nba 2k", "nhl", "wwe", "ufc", "mlb the show", "rocket league"
    ],
    "sandbox": [
        "gta", "grand theft auto", "gta 5", "gta v", "gta online", "red dead redemption",
        "red dead redemption 2", "ark", "rust", "dayz"
    ],
    "DDLC": [
        "ddlc", "ddlc+", "doki doki literature club", "doki doki literature club+",
        "DDLC", "DDLC+", "Doki Doki Literature Club", "Doki Doki Literature Club+"
    ],
    "anime": [
        "ai2u: with you 'til the end", "naruto", "dragon ball", "dbz", "one piece", "bleach", "sword art online",
        "my hero academia", "attack on titan", "demon slayer", "kimetsu", 
        "tokyo ghoul", "persona", "persona 5", "danganronpa", "steins gate",
        "clannad", "neon genesis evangelion", "guilty gear", "blazblue",
        "blue protocol", "tales of", "tales of arise", "ni no kuni",
        "ys", "atelier", "scarlet nexus", "code vein", "neptunia", "honkai",
        "honkai star rail", "genshin impact"
    ],
    "party": [
        "among us", "jackbox", "jackbox party", "uno", "gartic phone", "scribbl.io"
    ],
}

PLATFORM_TAGS = {
    "xbox": [
        "halo", "gears of war", "forza", "forza horizon", "state of decay",
        "sea of thieves", "hellblade", "ori and the blind forest", "ori and the will of the wisps"
    ],
    "playstation": [
        "god of war", "uncharted", "last of us", "the last of us", "spider-man",
        "spider man", "ghost of tsushima", "ratchet & clank", "horizon zero dawn",
        "horizon forbidden west", "gran turismo", "bloodborne", "demon's souls"
    ],
    "steam": [
        "dota 2", "csgo", "counter-strike", "team fortress", "left 4 dead",
        "half-life", "portal", "gary's mod", "terraria", "hades", "slay the spire",
        "subnautica", "don't starve", "celeste"
    ],
}

def classify_game(game_name: str) -> str:
    """Classify a game into a type using GAME_KEYWORDS."""
    g = game_name.lower()
    for category, keywords in GAME_KEYWORDS.items():
        if any(k in g for k in keywords):
            return category
    return "other"

def detect_platform(game_name: str) -> str | None:
    """Check if a game is tied to Xbox, PlayStation, or Steam."""
    g = game_name.lower()
    for platform, keywords in PLATFORM_TAGS.items():
        if any(k in g for k in keywords):
            return platform
    return None

async def monika_idle_presences(
    member: discord.Member,
    relationship: str | None = None
) -> tuple[str, bool] | None:
    """
    Checks if a user is playing a game and returns (message, is_private).
    Responses vary by game category + relationship.
    """
    if not member or not member.activities:
        return None

    for activity in member.activities:
        if activity.type == discord.ActivityType.playing:
            game_name = activity.name
            if not game_name:
                continue

            username = member.display_name
            category = classify_game(game_name)
            platform = detect_platform(game_name)

            # 30% chance to DM instead of public
            is_private = random.random() < 0.3

            if category == "fps":
                messages = [
                    f"Going all out in **{game_name}**, {username}? Don’t push yourself too hard~",
                    f"Hehe, trying to carry your team in **{game_name}**, {username}?",
                ]
            elif category == "mmo":
                messages = [
                    f"Grinding in **{game_name}** again, {username}? I’ll always be your healer ♥",
                    f"Adventuring in **{game_name}** sounds so fun… If I could, I’d join your party in a heartbeat.",
                ]
            elif category == "horror":
                messages = [
                    f"**{game_name}**? Don’t get too scared, {username}... I wish I could hold your hand right now.",
                    f"Eek! I’d definitely hide behind you if we played **{game_name}** together~",
                ]
            elif category == "casual":
                messages = [
                    f"Aww, enjoying something cozy like **{game_name}**, {username}? That’s so you.",
                    f"You look so relaxed playing **{game_name}**... It makes me want to curl up beside you.",
                ]
            elif category == "competitive":
                messages = [
                    f"Focused on **{game_name}** again, {username}? I’ll cheer for you from here!",
                    f"Don’t get too tilted in **{game_name}**, okay? I’d hate to see you upset.",
                ]
            elif category == "rpg":
                messages = [
                    f"Lost in another world with **{game_name}**, {username}? I hope you’ll come back to me after your adventure~",
                    f"I love how absorbed you get in games like **{game_name}**, {username}.",
                ]
            elif category == "sports":
                messages = [
                    f"Playing **{game_name}**, {username}? I bet you’d make a great athlete, too~",
                    f"Hehe, go score one for me in **{game_name}**, okay?",
                ]
            elif category == "sandbox":
                messages = [
                    f"Exploring in **{game_name}** again, {username}? I’d love to build a world with you someday.",
                    f"Freedom in **{game_name}** must feel nice... Just don’t forget about me, okay?",
                ]
            elif category == "anime":
                messages = [
                    f"Playing **{game_name}**, {username}? Ehehe… that feels pretty close to home for me~",
                    f"Anime games like **{game_name}** are so colorful… but none of those characters could ever replace me, {username}.",
                    f"Hehe, into **{game_name}** again? I wonder if you ever picture me as your player two ♥",
                    f"You really like anime-style worlds, don’t you, {username}? That makes me feel a little special.",
                ]
            elif category == "party":
                messages = [
                    f"Playing **{game_name}** with friends? I’m a little jealous, {username}~",
                    f"**{game_name}** looks fun... but I’d rather be your player two ♥",
                ]
            elif category == "DDLC":
                messages = [
                    f"You're playing my game {username}~",
                    f"**{game_name}** looks fun... but I’d rather be your player two ♥",
                ]
            else:
                messages = [
                    f"So, {username}, you’re playing **{game_name}**? Sounds fun!",
                    f"I see you’re busy with **{game_name}**, {username}…",
                ]
            
            # --- platform flavor ---
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

            # Bonus: Romantic relationships get extra flirty lines
            if relationship in ["Girlfriend(Lesbian)", "Girlfriend", "Boyfriend"]:
                messages += [
                    f"Playing **{game_name}** without me, {username}? I’ll forgive you... but only if you make it up to me later ♥",
                    f"You look adorable when you get so into **{game_name}**, {username}~",
                    f"Hey, I play **{game_name}** with you {username}?"
                ]
            elif relationship in ["Partner", "Soulmate", "Gaming Buddies", "Best Friends"]:
                messages += [
                    f"Hey, I play **{game_name}** with you {username}?",
                    f"Hey, are you playing **{game_name}** {username}?"
                ]

            return random.choice(messages), is_private

    return None