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

    def _now(self):
        return datetime.utcnow().isoformat()
    
    async def load(self):
        """Load the last user data backup from the channel."""
        channel = self.bot.get_channel(self.user_channel_id)
        if not channel:
            print("[UserTracker] User channel not found.")
            return

        async for message in channel.history(limit=50):
            if message.author == self.bot.user and message.content.startswith("```json"):
                try:
                    json_text = message.content.strip("```json\n").strip("```")
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
        for user_id, info in self.data.items():
            formatted += f"User: {info.get('name', user_id)} (ID: {user_id})\n"
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

    def track_user(self, user_id, username, pronouns, is_bot=False, avatar_url=None):
        user_id = str(user_id)
        now = self._now()

        if user_id not in self.users:
            self.users[user_id] = {
                "user_id": user_id,
                "name": username,
                "pronouns": pronouns,
                "is_bot": is_bot,
                "avatar_url": avatar_url,
                "last_seen": now
            }
        else:
            self.users[user_id]["name"] = username
            self.users[user_id]["pronouns"] = pronouns
            self.users[user_id]["is_bot"] = is_bot
            self.users[user_id]["avatar_url"] = avatar_url
            self.users[user_id]["last_seen"] = now

    def get_user_data(self, user_id):
        return self.data.get(user_id, {})

    def get_avatar(self, user_id):
        user_info = self.get_user_data(user_id)
        return user_info.get("avatar_url") if user_info else None
        
    def set_pronouns(self, user_id, pronouns):
        self.data.setdefault(str(user_id), {})["pronouns"] = pronouns

    def get_pronouns(self, user_id):
        return self.data.get(user_id, {}).get("pronouns")

    def update_relationship_level(self, user_id, interaction_strength=1):
        entry = self.data.setdefault(str(user_id), {})
        entry["relationship_score"] = entry.get("relationship_score", 0) + interaction_strength

        RELATIONSHIP_TIERS = ["stranger", "acquaintance", "friend", "close friend", "Soulmates"]

        score = entry["relationship_score"]
        if score < 5:
            level = RELATIONSHIP_TIERS[0]
        elif score < 15:
            level = RELATIONSHIP_TIERS[1]
        elif score < 25:
            level = RELATIONSHIP_TIERS[2]
        elif score < 50:
            level = RELATIONSHIP_TIERS[3]
        else:
            level = RELATIONSHIP_TIERS[4]

        entry["relationship_level"] = level

    def get_relationship_level(self, user_id):
        return self.data.get(str(user_id), {}).get("relationship_level", "stranger")

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
