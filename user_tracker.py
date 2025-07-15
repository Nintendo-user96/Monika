import datetime
import json
import os

class UserTracker:
    def __init__(self, file_path="json/users.json"):
        self.file_path = file_path
        self.users = {}  # user_id -> user_info
        self.load()

    def _now(self):
        return datetime.datetime.utcnow().isoformat()

    def track_user(self, user_id, username, is_bot=False, avatar_url=None):
        user_id = str(user_id)
        now = self._now()

        if user_id not in self.users:
            self.users[user_id] = {
                "user_id": user_id,
                "name": username,
                "is_bot": is_bot,
                "avatar_url": avatar_url,
                "last_seen": now
            }
        else:
            self.users[user_id]["name"] = username
            self.users[user_id]["is_bot"] = is_bot
            self.users[user_id]["avatar_url"] = avatar_url
            self.users[user_id]["last_seen"] = now

        self.save()

    def get_user_info(self, user_id):
        return self.users.get(str(user_id))

    def get_avatar(self, user_id):
        user_info = self.get_user_info(user_id)
        return user_info.get("avatar_url") if user_info else None

    def save(self):
        with open(self.file_path, "w") as f:
            json.dump(self.users, f, indent=2)

    def load(self):
        if os.path.exists(self.file_path):
            with open(self.file_path, "r") as f:
                try:
                    self.users = json.load(f)
                except json.JSONDecodeError:
                    self.users = {}
        else:
            self.users = {}

    def export_json(self, filepath):
        with open(filepath, "w") as f:
            json.dump(self.users, f, indent=2)

    def import_json(self, filepath):
        if os.path.exists(filepath):
            with open(filepath, "r") as f:
                self.users = json.load(f)
