import datetime
import json
import os

class GuildTracker:
    def __init__(self, file_path_1="servers.json", file_path_2="server_personality.json", file_path_3="server_relationship.json"):
        self.file_path = file_path_1
        self.servers = {}
        self.channels = {}
        
        # Personality modes per server
        self.personality_file = file_path_2
        self.personality_modes = {}

        # Relationship modes per server
        self.relationship_file = file_path_3
        self.relationship_modes = {}

        self.load()
        self.load_personality_modes()
        self.load_relationship_modes()

    # ---------------- BASIC SERVER/CHANNEL TRACKING ----------------

    def _now(self):
        return datetime.datetime.utcnow().isoformat()

    def track_server(self, server_id, server_name):
        server_id = str(server_id)
        now = self._now()
        if server_id not in self.servers:
            self.servers[server_id] = {
                "server_id": server_id,
                "name": server_name,
                "channels": {},
                "last_seen": now
            }
        else:
            self.servers[server_id]["name"] = server_name
            self.servers[server_id]["last_seen"] = now
        self.save()

    def track_channel(self, server_id, channel_id, channel_name):
        server_id = str(server_id)
        channel_id = str(channel_id)
        now = self._now()

        if server_id not in self.servers:
            self.track_server(server_id, f"Unnamed Server {server_id}")

        self.servers[server_id]["channels"][channel_id] = {
            "name": channel_name,
            "last_seen": now
        }
        self.save()

    def get_server_info(self, server_id):
        return self.servers.get(str(server_id))

    def save(self):
        with open(self.file_path, "w") as f:
            json.dump(self.servers, f, indent=2)

    def load(self):
        if os.path.exists(self.file_path):
            with open(self.file_path, "r") as f:
                try:
                    data = json.load(f)
                    self.servers = data.get("servers", {})
                    self.channels = data.get("channels", {})
                except json.JSONDecodeError:
                    self.servers = {}
                    self.channels = {}
        else:
            self.servers = {}
            self.channels = {}
        
    # ---------------- PERSONALITY MODE PERSISTENCE ----------------

    def save_personality_modes(self):
        with open(self.personality_file, "w") as f:
            json.dump(
                {k: list(v) for k, v in self.personality_modes.items()},
                f,
                indent=2
            )

    def load_personality_modes(self):
        if os.path.exists(self.personality_file):
            with open(self.personality_file, "r") as f:
                try:
                    data = json.load(f)
                    self.personality_modes = {
                        str(k): set(v) for k, v in data.items()
                    }
                except json.JSONDecodeError:
                    self.personality_modes = {}
        else:
            self.personality_modes = {}

    def set_personality_modes(self, guild_id, modes):
        self.personality_modes[str(guild_id)] = set(modes)
        self.save_personality_modes()

    def get_personality_modes(self, guild_id):
        return self.personality_modes.get(str(guild_id), set())
    
    # ---------------- RELATIONSHIP MODE PERSISTENCE ----------------

    def load_relationship_modes(self):
        if os.path.exists(self.relationship_file):
            with open(self.relationship_file, "r") as f:
                try:
                    data = json.load(f)
                    self.relationship_modes = {
                        str(k): v for k, v in data.items()
                    }
                except json.JSONDecodeError:
                    self.relationship_modes = {}
        else:
            self.relationship_modes = {}

    def save_relationship_modes(self):
        with open(self.relationship_file, "w") as f:
            json.dump(self.relationship_modes, f, indent=2)

    def set_relationship_mode(self, guild_id, mode):
        self.relationship_modes[str(guild_id)] = set(mode)
        self.save_relationship_modes()

    def get_relationship_mode(self, guild_id):
        return self.relationship_modes.get(str(guild_id), set())
    
    # ---------------- JSON PERSISTENCE ----------------

    def export_json(self, filepath):
        with open(filepath, "w") as f:
            json.dump(self.servers, f, indent=2)

    def import_json(self, filepath):
        if os.path.exists(filepath):
            with open(filepath, "r") as f:
                self.servers = json.load(f)
