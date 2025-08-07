import datetime
import re

class MemoryManager:
    def __init__(self):
        # Structure: guild_id -> channel_id -> user_id -> list of messages
        self.data = {}

    def save(self, guild_id, guild_name, channel_id, channel_name, user_id, username, content, emotion=None, avatar_url=None, role="user"):
        entry = {
            "timestamp": datetime.datetime.utcnow().isoformat(),
            "guild_id": guild_id,
            "guild_name": guild_name,
            "channel_id": channel_id,
            "channel_name": channel_name,
            "user_id": user_id,
            "username": username,
            "content": content,
            "role": role,
            "emotion": emotion or "neutral",
            "avatar_url": avatar_url
        }
        self.data.setdefault(guild_id, {}).setdefault(channel_id, {}).setdefault(user_id, []).append(entry)

    def get_monika_context(self, guild_id: str, channel_id: str, user_id: str, limit=10):
        """Retrieve the last few relevant messages from Monika and a user in the given channel."""
        guild_id = str(guild_id)
        channel_id = str(channel_id)
        user_id = str(user_id)

        if guild_id not in self.data:
            return []

        if channel_id not in self.data[guild_id]:
            return []

        user_messages = self.data[guild_id][channel_id].get(user_id, [])
        bot_messages = self.data[guild_id][channel_id].get("bot", [])

        # Merge and sort by timestamp (assuming timestamp is ISO format)
        all_messages = user_messages + bot_messages
        try:
            sorted_messages = sorted(all_messages, key=lambda x: x.get("timestamp", ""))
        except Exception as e:
            print(f"[Context Sort Error] {e}")
            sorted_messages = all_messages

        return sorted_messages[-limit:]

    async def save_to_memory_channel(self, content, emotion, user_id, username, role, guild_id, guild_name, channel_id, channel_name, memory_channel):
        if not memory_channel:
            print("[Memory] No memory channel provided.")
            return

        safe_content = content.replace("|", "\\|")
        timestamp = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')

        log_message = (
            f"`[{timestamp}]` | `Server name: {guild_name}, ID: ({guild_id})` | "
            f"`Channel name: {channel_name}, ID: ({channel_id})` | "
            f"`User Name: {username}, ID: ({user_id})` | "
            f"`Role: {role}` | `{safe_content}` | `{emotion}`"
        )

        try:
            await memory_channel.send(log_message)
            print(f"[Memory] Logged to channel: {log_message}")
        except Exception as e:
            print(f"[Memory Channel Error] {e}")

    async def load_history(self, client, MEMORY_CHAN_ID):
        log_channel = client.get_channel(MEMORY_CHAN_ID)
        if not log_channel:
            print("[Memory] Log channel not found.")
            return

        print("[Memory] Loading history from log channel...")

        async for msg in log_channel.history(limit=500):
            try:
                if not msg.content or "] |" not in msg.content:
                    continue

                timestamp_part, rest = msg.content.split("] |", 1)
                timestamp = timestamp_part.strip("[")
                parts = [p.strip() for p in rest.split(" | ")]

                if len(parts) < 6:
                    print(f"[Memory Parse Warning] Skipping malformed line: {msg.content}")
                    continue

                guild_info = parts[0].replace("Server name:", "").split(", ID: (")
                guild_name = guild_info[0].strip()
                guild_id = guild_info[1].strip(")")

                channel_info = parts[1].replace("Channel name:", "").split(", ID: (")
                channel_name = channel_info[0].strip()
                channel_id = channel_info[1].strip(")")

                user_info = parts[2].replace("User Name:", "").split(", ID: (")
                username = user_info[0].strip()
                user_id = user_info[1].strip(")")

                role = parts[3].replace("Role:", "").strip()
                content = parts[4].replace("\\|", "|").strip()
                emotion = parts[5].strip()

                self.data \
                    .setdefault(guild_id, {}) \
                    .setdefault(channel_id, {}) \
                    .setdefault(user_id, []) \
                    .append({
                        "guild_id": guild_id,
                        "guild_name": guild_name,
                        "channel_id": channel_id,
                        "channel_name": channel_name,
                        "user_id": user_id,
                        "username": username,
                        "role": role,
                        "content": content,
                        "emotion": emotion,
                        "timestamp": timestamp
                    })

            except Exception as e:
                print(f"[Memory Parse Error] {e}")

        print("[Memory] History load complete.")

    def import_from_text(self, guild_id: str, text: str) -> int:
        """
        Import from an exported .txt memory file.
        Restores chat logs, personality, and relationship.
        Returns number of messages imported.
        """
        lines = text.splitlines()
        imported = 0

        self.data.setdefault(guild_id, {})

        current_channel = "imported"
        self.data[guild_id].setdefault(current_channel, {})
        self.data[guild_id][current_channel].setdefault("manual_import", [])

        section = "memories"  # track which section we're parsing
        personality = []
        relationship = {}

        for line in lines:
            if line.startswith("--- Personality ---"):
                section = "personality"
                continue
            elif line.startswith("--- Relationship ---"):
                section = "relationship"
                continue

            if section == "memories":
                match = re.match(r"\[(.*?)\] (.*?): (.*)", line)
                if match:
                    ts, username, content = match.groups()
                    entry = {
                        "timestamp": ts,
                        "username": username,
                        "content": content,
                        "user_id": "manual_import"
                    }
                    self.data[guild_id][current_channel]["manual_import"].append(entry)
                    imported += 1

            elif section == "personality":
                if line.strip() and not line.startswith("---"):
                    personality = [m.strip() for m in line.split(",") if m.strip()]

            elif section == "relationship":
                if line.startswith("Type:"):
                    relationship_type = line.split(":", 1)[1].strip()
                    relationship["type"] = relationship_type
                if line.startswith("With:"):
                    with_users = line.split(":", 1)[1].strip()
                    if with_users:
                        relationship["with"] = [u.strip() for u in with_users.split(",")]

        # Save into memory
        if personality:
            self.set_personality(guild_id, personality)
        if relationship:
            self.set_relationship(guild_id, relationship_type=relationship.get("type"),
                                            with_list=relationship.get("with", []))

        return imported
