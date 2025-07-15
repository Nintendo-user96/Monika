import json
import os
import threading

class JsonManager:
    def __init__(self, user_tracker, server_tracker, file_path="json/memory.json"):
        self.file_path = file_path
        self.lock = threading.RLock()
        self.user_tracker = user_tracker
        self.server_tracker = server_tracker
        self.data = []
        self.load()

    def load(self):
        if os.path.exists(self.file_path):
            with open(self.file_path, "r") as f:
                try:
                    self.data = json.load(f)
                except json.JSONDecodeError:
                    self.data = []
        else:
            self.data = []

    def save(self):
        with open(self.file_path, "w") as f:
            json.dump(self.data, f, indent=2)

    def save_message(
        self,
        guild_id,
        guild_name,
        channel_id,
        channel_name,
        user_id,
        username,
        content,
        emotion=None,
        is_dm=False,
        is_friend_bot=False,
        avatar_url=None
    ):
        with self.lock:
            found_guild = next((g for g in self.data if g["guild_id"] == guild_id), None)
            if not found_guild:
                found_guild = {
                    "guild_id": guild_id,
                    "guild_name": guild_name,
                    "channels": []
                }
                self.data.append(found_guild)
            
            found_channel = next((c for c in found_guild["channels"] if c["channel_id"] == channel_id), None)
            if not found_channel:
                found_channel = {
                    "channel_id": channel_id,
                    "channel_name": channel_name,
                    "messages": []
                }
                found_guild["channels"].append(found_channel)
            
            found_channel["messages"].append({
                "user_id": user_id,
                "username": username,
                "content": content,
                "emotion": emotion,
                "is_dm": is_dm,
                "is_friend_bot": is_friend_bot,
                "avatar_url": avatar_url
            })
            self.save()

    def get_context(self, guild_id, channel_id, user_id, limit=10):
        with self.lock:
            filtered = [
                msg for msg in self.data
                if (msg.get("guild_id") == guild_id and msg.get("channel_id") == channel_id and msg.get("user_id") == user_id)
                or (msg.get("is_dm") and msg.get("user_id") == user_id)
                or (msg.get("user_id") == "bot" and (msg.get("guild_id") == guild_id or msg.get("is_dm")))
            ]
            return filtered[-limit:]

    def export_user_memory(self, user_id):
        with self.lock:
            logs = [
                f"{entry.get('username')}: {entry.get('content')}"
                for entry in self.data
                if entry.get("user_id") == user_id
            ]
            return "\n".join(logs)