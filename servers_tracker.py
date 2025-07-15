import datetime
import json
import os

class GuildTracker:
    def __init__(self, file_path="json/servers.json"):
        self.file_path = file_path
        self.servers = {}  # server_id -> server_info
        self.load()

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
                    self.servers = json.load(f)
                except json.JSONDecodeError:
                    self.servers = {}
        else:
            self.servers = {}

    def export_json(self, filepath):
        with open(filepath, "w") as f:
            json.dump(self.servers, f, indent=2)

    def import_json(self, filepath):
        if os.path.exists(filepath):
            with open(filepath, "r") as f:
                self.servers = json.load(f)
