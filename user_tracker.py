import discord, os, json
from datetime import datetime

class UserTracker:
    def __init__(self, bot, user_channel_id):
        self.bot = bot
        self.user_channel_id = user_channel_id
        self.data = {}  # user_id: {name, avatar, pronouns, last_seen}
        self.users = {}
        self.last_backup_message = None

    def _now(self):
        return datetime.utcnow().isoformat()
    
    # ✅ Set language
    def set_language(self, user_id: str, lang_code: str):
        if user_id not in self.users:
            self.users[user_id] = {}
        self.users[user_id]["language"] = lang_code

    # ✅ Get language (default = "en")
    def get_language(self, user_id: str) -> str:
        return self.users.get(user_id, {}).get("language", "en")
    
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
                    self.data = json.loads(json_text)
                    self.last_backup_message = message
                    print("[UserTracker] Data loaded from channel.")
                    return
                except Exception as e:
                    print(f"[UserTracker] Failed to load user data: {e}")

    async def save(self, bot, channel_id):
        """Save the current user tracker data to the user channel as JSON."""
        channel = self.bot.get_channel(int(channel_id))
        if not channel:
            print("[UserTracker] User channel not found.")
            return

        formatted = "```json\n" + json.dumps(self.data, indent=2) + "\n```"

        try:
            if self.last_backup_message:
                await self.last_backup_message.edit(content=formatted)
            else:
                self.last_backup_message = await channel.send(formatted)
            print("[UserTracker] Data saved to channel.")
        except Exception as e:
            print(f"[UserTracker] Failed to save user data: {e}")

    def register_user(self, user: discord.User, relationship=None, personality=None, pronouns=None):
        """Register or update a user in memory only if something has changed."""
        user_id = str(user.id)
        existing = self.data.get(user_id, {})

        updated = {
            "name": user.display_name,
            "relationship": relationship or existing.get("relationship"),
            "personality": personality or existing.get("personality"),
            "pronouns": pronouns or existing.get("pronouns"),
            "bot": user.bot,
            "last_seen": datetime.utcnow().isoformat()
        }

        # ✅ Only update if something is different
        if updated != existing:
            self.data[user_id] = updated
            return True  # means changed
        return False  # no change
    
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
        
    def set_pronouns(self, user_id: str, pronouns: str):
        """Save pronouns for a user."""
        if user_id not in self.users:
            self.users[user_id] = {}
        self.users[user_id]["pronouns"] = pronouns

    def get_pronouns(self, user_id: str):
        """Retrieve saved pronouns, or None if unset."""
        return self.users.get(user_id, {}).get("pronouns")
    
    def set_relationship(self, user_id, relationship):
        """
        Set or clear the stored relationship for a user.
        - user_id may be int or str.
        - relationship should be a string (e.g. "Lover") or None to clear.
        Returns True if the stored value changed (useful to decide whether to save).
        """
        uid = str(user_id)

        # ensure runtime entry exists
        prev = self.users.get(uid, {}).get("relationship")
        if uid not in self.users:
            self.users[uid] = {}

        # set runtime relationship
        self.users[uid]["relationship"] = relationship

        # persist to self.data so save() includes it
        self.data.setdefault(uid, {})
        if relationship is None:
            # remove persistent relationship if clearing
            if "relationship" in self.data[uid]:
                del self.data[uid]["relationship"]
        else:
            self.data[uid]["relationship"] = relationship

        return prev != relationship

    def get_relationship(self, user_id: str) -> str:
        """Return stored relationship for a user, or 'Stranger' if none set."""
        user_data = self.users.get(user_id, {})
        return user_data.get("relationship", "Stranger")

    def set_nickname(self, user_id: str, nickname: str):
        if user_id not in self.users:
            self.users[user_id] = {}
        self.users[user_id]["nickname"] = nickname

    def get_nickname(self, user_id: str) -> str:
        return self.users.get(user_id, {}).get("nickname", None)

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
