import discord
from datetime import datetime
import os

class UserTracker:
    def __init__(self, bot, user_channel_id):
        self.bot = bot
        self.user_channel_id = user_channel_id
        self.data = {}  # user_id: {name, avatar, pronouns, last_seen}
        self.users = {}
        self.last_backup_message = None

        self.RELATIONSHIP_LEVELS = [
            "Stranger",
            "Friend",
            "Close Friend",
            "Best Friend",
            "Partner",
            "Soulmate"
        ]

    def _now(self):
        return datetime.utcnow().isoformat()
    
    async def load(self):
        """Load the last user data backup from the channel."""
        channel = self.bot.get_channel(self.user_channel_id)
        if not channel:
            print("[UserTracker] User channel not found.")
            return

        async for message in channel.history(limit=50):
            if message.author == self.bot.user and message.content.startswith("```"):
                try:
                    json_text = message.content.strip("```\n").strip("```")
                    self.data = eval(json_text)
                    self.last_backup_message = message
                    print("[UserTracker] Data loaded from channel.")
                    return
                except Exception as e:
                    print(f"[UserTracker] Failed to load user data: {e}")

    async def save(self, bot, channel_id):
        """Save the current user tracker data to the user channel."""
        channel = self.bot.get_channel(int(channel_id))
        if not channel:
            print("[UserTracker] User channel not found.")
            return

        formatted = "```\n"
        for username, user_id, info in self.data.items():
            formatted += f"Username: {info.get('name', username)} (User ID: {user_id})\n"
            for key, value in info.items():
                formatted += f"  {key}: {value}\n"
            formatted += "\n"
        formatted += "```"

        try:
            if self.last_backup_message:
                await self.last_backup_message.edit(content=formatted)
            else:
                self.last_backup_message = await channel.send(formatted)
            print("[UserTracker] Data saved to channel.")
        except Exception as e:
            print(f"[UserTracker] Failed to save user data: {e}")

    def register_user(self, user: discord.User, pronouns=None):
        self.data[str(user.id)] = {
            "name": user.name,
            "avatar": str(user.avatar.url if user.avatar else ""),
            "pronouns": pronouns or "unspecified",
            "last_seen": datetime.utcnow().isoformat()
        }
    
    def set_user(self, user_id, name=None, avatar=None, pronouns=None):
        self.data.setdefault(user_id, {})
        if name:
            self.data[user_id]["name"] = name
        if avatar:
            self.data[user_id]["avatar"] = avatar
        if pronouns:
            self.data[user_id]["pronouns"] = pronouns

    def track_user(self, user_id, name, is_bot=False):
        if user_id not in self.users:
            self.users[user_id] = {
                "name": name,
                "avatar": None,
                "pronouns": None,
                "relationship": None,  # 0 = Stranger
                "has_manual_relationship": False,  # New field
                "is_bot": is_bot
            }
        else:
            self.users[user_id]["name"] = name
            self.users[user_id]["is_bot"] = is_bot

    def set_manual_relationship(self, user_id, value=True):
        if user_id in self.users:
            self.users[user_id]["has_manual_relationship"] = value

    def has_manual_relationship(self, user_id):
        return self.users.get(user_id, {}).get("has_manual_relationship", False)

    def get_user_data(self, user_id):
        return self.data.get(user_id, {})

    def get_avatar(self, user_id):
        user_info = self.get_user_data(user_id)
        return user_info.get("avatar_url") if user_info else None
        
    def set_pronouns(self, user_id, pronouns):
        self.data.setdefault(str(user_id), {})["pronouns"] = pronouns

    def get_pronouns(self, user_id):
        return self.data.get(user_id, {}).get("pronouns")

    def add_relationship_xp(self, user_id: str, amount: int = 1):
        data = self.load()
        if "xp" not in data.get(user_id, {}):
            data[user_id]["xp"] = 0
        data[user_id]["xp"] += amount
        self.save()

    def get_relationship_level(self, user_id: str):
        data = self.load()
        xp = data.get(user_id, {}).get("xp", 0)
        level_index = min(xp // 50, len(self.RELATIONSHIP_LEVELS) - 1)  # 50 XP per level
        return self.RELATIONSHIP_LEVELS[level_index]

    def enable_relationship_levels(self, user_id: int):
        if user_id not in self.data:
            self.data[user_id] = {}
        self.data[user_id]["relationship_levels_enabled"] = True

    def disable_relationship_levels(self, user_id: int):
        if user_id not in self.data:
            self.data[user_id] = {}
        self.data[user_id]["relationship_levels_enabled"] = False

    def relationship_levels_enabled(self, user_id: int) -> bool:
        return self.data.get(user_id, {}).get("relationship_levels_enabled", False)

    async def log_to_channel(self, channel, user_id):
        entry = self.data.get(user_id)
        if not entry: return

        ts = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        log = f"[{ts}] User: {user_id} | Data: {entry}"
        await channel.send(log)

    def update_last_seen(self, user: discord.User):
        if str(user.id) in self.data:
            self.data[str(user.id)]["last_seen"] = datetime.utcnow().isoformat()
        else:
            self.register_user(user)
