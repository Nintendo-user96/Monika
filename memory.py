import datetime

class MemoryManager:
    def __init__(self):
        # Nested structure: guild_id -> channel_id -> user_id -> list of messages
        self.data = {}

    def save(self, guild_id, channel_id, user_id, content, emotion="neutral", role=None):
        timestamp = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')

        if role is None:
            role = "assistant" if user_id == "bot" else "user"

        self.data \
            .setdefault(guild_id, {}) \
            .setdefault(channel_id, {}) \
            .setdefault(user_id, []) \
            .append({
                "role": role,
                "content": content,
                "emotion": emotion,
                "timestamp": timestamp
            })

        print(f"[Memory] is Saved")

    async def save_to_memory_channel(self, content, emotion, user_id, memory_channel):
        if not memory_channel:
            print("[Memory] No memory channel provided.")
            return

        timestamp = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        log_message = f"[{timestamp}] UserID: {user_id}: {content} | Emotion: {emotion}"

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

                prefix, rest = msg.content.split("] ", 1)
                if " | Emotion: " in rest:
                    content, emotion = rest.split(" | Emotion: ", 1)
                else:
                    content, emotion = rest, "neutral"

                parts = content.split(": ", 2)
                if len(parts) < 3:
                    continue

                user_id = parts[1].strip()
                text = parts[2].strip()

                guild_id = str(msg.guild.id) if msg.guild else "global"
                channel_id = str(msg.channel.id)

                role = "assistant" if user_id == "bot" else "user"

                self.save(guild_id, channel_id, user_id, text, emotion.strip(), role=role)

            except Exception as e:
                print(f"[Memory Parse Error] {e}")

        print("[Memory] History load complete.")
