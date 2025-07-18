import datetime
import json
import os

class GuildTracker:
    def __init__(self, file_path_1="server.json"):
        self.file_path = file_path_1
        self.servers = {}
        self.channels = {}
    
        self.personality_modes = {}

        # Relationship modes per server
        self.relationship_modes = {}

        self.load()

    # ---------------- BASIC SERVER/CHANNEL TRACKING ----------------

    def _now(self):
        return datetime.datetime.utcnow().isoformat()

    def load(self):
        if os.path.exists(self.file_path):
            with open(self.file_path, "r") as f:
                try:
                    self.data = json.load(f)
                except json.JSONDecodeError:
                    self.data = {}
        else:
            self.data = {}

    def save(self):
        with open(self.file_path, "w") as f:
            json.dump(self.data, f, indent=2)

    def track_server(self, guild_id, guild_name):
        guild_id = str(guild_id)
        if guild_id not in self.data:
            self.data[guild_id] = {
                "guild_name": guild_name,
                "channels": {},
                "personality_modes": [],
                "relationship": None
            }
            self.save()

    def track_channel(self, guild_id, channel_id, channel_name):
        guild_id = str(guild_id)
        channel_id = str(channel_id)
        if guild_id in self.data:
            channels = self.data[guild_id]["channels"]
            channels[channel_id] = channel_name
            self.save()
        
    # ---------------- PERSONALITY MODE PERSISTENCE ----------------

    def set_personality_modes(self, guild_id, modes):
        guild_id = str(guild_id)

        if guild_id not in self.data or self.data[guild_id] is None:
            self.data[guild_id] = {}
        
        self.data[guild_id]["personality"] = list(modes)
        self.save()

    def get_personality_modes(self, guild_id):
        guild_id = str(guild_id)
        return self.data.get(guild_id, {}).get("personality", [])
    
    # ---------------- RELATIONSHIP MODE PERSISTENCE ----------------

    def set_relationship_type(self, guild_id, relationship_type):
        if guild_id not in self.data or self.data[guild_id] is None:
            self.data[guild_id] = {}

        if "relationship" not in self.data[guild_id] or self.data[guild_id]["relationship"] is None:
            self.data[guild_id]["relationship"] = {}

        self.data[guild_id]["relationship"]["type"] = relationship_type
        self.save()

    def get_relationship_type(self, guild_id):
        guild_id = str(guild_id)
        return self.data.get(guild_id, {}).get("relationship", {})

    def set_relationship_with(self, guild_id, with_list):
        if guild_id not in self.data or self.data[guild_id] is None:
            self.data[guild_id] = {}

        if "relationship" not in self.data[guild_id] or self.data[guild_id]["relationship"] is None:
            self.data[guild_id]["relationship"] = {}

        self.data[guild_id]["relationship"]["with"] = with_list
        self.save()

    def get_relationship_with(self, guild_id):
        if guild_id not in self.data:
            return []

        # Fix: ensure "relationship" exists and is a dict
        if not isinstance(self.data[guild_id].get("relationship"), dict):
            self.data[guild_id]["relationship"] = {}

        return self.data[guild_id]["relationship"].setdefault("with", [])
    
    # ---------------- JSON PERSISTENCE ----------------

    def export_json(self, file_path=None):
        if not file_path:
            file_path = self.file_path
        with open(file_path, "w") as f:
            json.dump(self.data, f, indent=2)

    def import_json(self, file_path=None):
        if not file_path:
            file_path = self.file_path
        if os.path.exists(file_path):
            with open(file_path, "r") as f:
                self.data = json.load(f)
            
