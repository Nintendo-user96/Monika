import datetime

class LogsManager:
    def __init__(self):
        # Structure: guild_id -> channel_id -> user_id -> list of messages
        self.data_logs = {}

    def Logs_save(self, guild_id, guild_name, channel_id, channel_name, user_id, username, content, emotion="neutral", role=None):
        timestamp = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')

        if role is None:
            role = "assistant" if is_bot or user_id == "bot" else "user" # type: ignore

        self.data_logs \
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

        print(
            f"[Memory] Saved | Server: {guild_name} ID: ({guild_id}) | "
            f"Channel: {channel_name} ID: ({channel_id}) | "
            f"User: {username} ID: ({user_id}) | Role: {role} | Emotion: {emotion}"
        )

    def Logs_get_context(self, guild_id, channel_id, user_id, limit=10):
        messages = []
        all_channels = self.data_logs.get(guild_id, {})
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

    async def save_to_memory_channel(self, content, emotion, user_id, username, role, guild_id, guild_name, channel_id, channel_name, memory_channel):
        if not memory_channel:
            print("[Memory] No memory channel provided.")
            return

        safe_content = content.replace("|", "\\|")
        timestamp = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')

        # Detect role again if not passed or override

        log_message = (
            f"[Memory] Saved | Server: {guild_name} ID: ({guild_id}) | "
            f"Channel: {channel_name} ID: ({channel_id}) | "
            f"User: {username} ID: ({user_id}) | Role: {role} | Emotion: {emotion}"
        )

        try:
            await memory_channel.send(log_message)
            print(f"[Memory] Logged to channel: {log_message}")
        except Exception as e:
            print(f"[Memory Channel Error] {e}")

    async def load_history(self, client, LOG_CHANNEL_ID):
        log_channel = client.get_channel(LOG_CHANNEL_ID)
        if not log_channel:
            print("[Memory] Log channel not found.")
            return

        print("[Memory] Loading history from log channel...")

        async for msg in log_channel.history(limit=500):
            try:
                if not msg.content:
                    continue

                line = msg.content
                if "] " not in line:
                    print(f"[Memory Parse Warning] Skipping malformed line (no timestamp): {line}")
                    continue

                timestamp_part, rest = line.split("] ", 1)
                timestamp = timestamp_part.strip("[")

                parts = [p.strip() for p in rest.split(" | ")]
                if len(parts) < 6:
                    print(f"[Memory Parse Warning] Skipping malformed line (too few fields): {line}")
                    continue

                guild_part = parts[0].replace("Server name:", "").split(", ID: (")
                guild_name = guild_part[0].strip()
                guild_id = guild_part[1].strip(")")

                channel_part = parts[1].replace("Channel name:", "").split(", ID: (")
                channel_name = channel_part[0].strip()
                channel_id = channel_part[1].strip(")")

                user_part = parts[2].replace("User Name:", "").split(", ID: (")
                username = user_part[0].strip()
                user_id = user_part[1].strip(")")

                role = parts[3].replace("Role:", "").strip()
                content = parts[4].replace("\\|", "|").strip()
                emotion = parts[5].strip()

                role = "assistant" if role.lower() == "assistant" or user_id == "bot" else "user"

                self.data_logs \
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