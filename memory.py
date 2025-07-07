import datetime

class MemoryManager:
    def __init__(self):
        # Structure: guild_id -> channel_id -> user_id -> list of messages
        self.data = {}

    def save(self, guild_id, guild_name, channel_id, channel_name, user_id, username, content, emotion="neutral", role=None, is_bot=False):
        timestamp = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')

        if role is None:
            role = "monika" if is_bot or user_id == "bot" else "user"

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

        print(
            f"[Memory] Saved | Server: {guild_name} ({guild_id}) | "
            f"Channel: {channel_name} ({channel_id}) | "
            f"User: {username} ({user_id}) | Role: {role} | Emotion: {emotion}"
        )

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
                messages.append({"role": "bot", "content": bot_messages[i]["content"]})

        print(f"[Memory] Retrieved context: {len(messages)} messages for User={user_id} in Channel={channel_id}")
        return messages

    async def save_to_memory_channel(self, content, emotion, user_id, username, guild_id, guild_name, channel_id, channel_name, role, memory_channel):
        if not memory_channel:
            print("[Memory] No memory channel provided.")
            return

        # Escape pipes in user content so logs can be reliably split later
        safe_content = content.replace("|", "\\|")

        role_str = "monika" if user_id == "bot" else "user"

        timestamp = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        log_message = (
            f"[{timestamp}] Server name: {guild_name}, ID: ({guild_id}) | "
            f"Channel name: {channel_name}, ID: ({channel_id}) | "
            f"User Name: {username}, ID: ({user_id}) | Role: {role} | {safe_content} | {emotion}"
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

                line = msg.content
                if "] " not in line:
                    print(f"[Memory Parse Warning] Skipping malformed line (no timestamp): {line}")
                    continue

                timestamp_part, rest = line.split("] ", 1)
                timestamp = timestamp_part.strip("[")  # e.g. "2025-07-03 12:34:56"

                parts = [p.strip() for p in rest.split(" | ")]
                if len(parts) < 8:
                    print(f"[Memory Parse Warning] Skipping malformed line (too few fields): {line}")
                    continue

                guild_info = parts[0].split("(", 1)
                guild_name = guild_info[0].replace("Server:", "").strip()
                guild_id = guild_info[1].strip(") ")

                channel_info = parts[1].split("(", 1)
                channel_name = channel_info[0].replace("Channel:", "").strip()
                channel_id = channel_info[1].strip(") ")

                user_info = parts[2].split("(", 1)
                username = user_info[0].replace("User:", "").strip()
                user_id = user_info[1].strip(") ")

                role = parts[3].replace("Role:", "").strip()
                content = parts[4].replace("Content:", "").replace("\\|", "|").strip()
                emotion = parts[5].replace("Emotion:", "").strip()
                # Unescape pipes in content
                content = content.replace("\\|", "|")

                role = "monika" if role.lower() == "monika" or user_id == "bot" else "user"

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
