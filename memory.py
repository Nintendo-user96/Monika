import datetime

class MemoryManager:
    def __init__(self):
        # Nested structure: guild_id -> channel_id -> user_id -> list of messages
        self.data = {}

    def save(self, guild_id, guild_name, channel_id, channel_name, user_id, username, content, emotion="neutral", role=None):
        timestamp = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')

        if role is None:
            role = "assistant" if user_id == "bot" else "user"

        self.data \
            .setdefault(guild_id, {}) \
            .setdefault(channel_id, {}) \
            .setdefault(user_id, []) \
            .setdefault(guild_name, {}) \
            .setdefault(channel_name, {}) \
            .setdefault(username, []) \
            .append({
                "role": role,
                "content": content,
                "emotion": emotion,
                "timestamp": timestamp
            })

        print(f"[Memory] Saved | Server: {guild_name} / ({guild_id}) | Channel: {channel_name} / ({channel_id}) | User: {username} / ({user_id})")

    async def save_to_memory_channel(self, content, emotion, user_id, guild_id, channel_id, memory_channel):
        if not memory_channel:
            print("[Memory] No memory channel provided.")
            return

        timestamp = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        log_message = f"[{timestamp}] UserID: {user_id}: {content} ChannelID: {channel_id}, serverID: {guild_id}| Emotion: {emotion}"

        try:
            await memory_channel.send(log_message)
            print(f"[Memory] Logged to channel: {log_message}")
        except Exception as e:
            print(f"[Memory Channel Error] {e}")

    def get_context(self, guild_id, channel_id, user_id, limit=10):
        messages = []
        all_channels = self.data.get(guild_id, {})
        all_users = all_channels.get(channel_id, {})

        user_messages = all_users.get(user_id, [])[-limit:]
        bot_messages = all_users.get("bot", [])[-limit:]

        max_len = max(len(user_messages), len(bot_messages))
        for i in range(max_len):
            if i < len(user_messages):
                messages.append({"role": "user", "content": user_messages[i]["content"]})
            if i < len(bot_messages):
                messages.append({"role": "assistant", "content": bot_messages[i]["content"]})

        print(f"[Memory] Retrieved context: {len(messages)} messages for User={user_id} in Channel={channel_id}")
        return messages

    async def save_to_memory_channel(self, content, emotion, user_id, username, guild_id, guild_name, channel_id, channel_name, memory_channel):
        if not memory_channel:
            print("[Memory] No memory channel provided.")
            return

        timestamp = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        log_message = (
            f"[{timestamp}] Server: {guild_name} ({guild_id}) | "
            f"Channel: {channel_name} ({channel_id}) | "
            f"User: {username} ({user_id}) | Emotion: {emotion}\n"
            f"Content: {content}"
        )

        try:
            await memory_channel.send(log_message)
            print(f"[Memory] Logged to channel: {log_message}")
        except Exception as e:
            print(f"[Memory Channel Error] {e}")

    async def load_history(self, client, MEMORY_LOG_CHANNEL_ID):
        log_channel = client.get_channel(MEMORY_LOG_CHANNEL_ID)
        if not log_channel:
            print("[Memory] Log channel not found.")
            return

        print("[Memory] Loading history from log channel...")

        async for msg in log_channel.history(limit=500):
            try:
                if not msg.content:
                    continue

                # Parse the log format
                first_line, *rest = msg.content.split("\n")
                if " | Emotion: " not in first_line:
                    continue

                header, emotion_part = first_line.split(" | Emotion: ", 1)
                emotion = emotion_part.strip()
                timestamp_part, server_part, channel_part, user_part = header.split(" | ")

                # Extract fields
                guild_name, guild_id = self._parse_name_and_id(server_part, "Server")
                channel_name, channel_id = self._parse_name_and_id(channel_part, "Channel")
                username, user_id = self._parse_name_and_id(user_part, "User")

                content = "\n".join(rest).replace("Content: ", "", 1).strip()

                role = "assistant" if user_id == "bot" else "user"

                self.save(guild_id, guild_name, channel_id, channel_name, user_id, username, content, emotion, role=role)
                
            except Exception as e:
                print(f"[Memory Parse Error] {e}")

        print("[Memory] History load complete.")
        
    def _parse_name_and_id(self, section, label):
        """ Helper to split 'Label: Name (ID)' into (Name, ID) """
        if f"{label}:" not in section:
            return "Unknown", "unknown"
        try:
            after_label = section.split(f"{label}: ", 1)[1].strip()
            name_part, id_part = after_label.rsplit("(", 1)
            return name_part.strip(), id_part.strip(")")
        except Exception:
            return "Unknown", "unknown"

