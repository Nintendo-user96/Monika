import datetime
import os
import discord
import asyncio

class GuildTracker:
    RELATIONSHIP_MODES = {
        "default": "Classic DDLC Monika — wants to be with the user no matter what.",
        "sexual": {
            "Polyamory": "You are emotionally open and romantically available to more than one person.",
            "Lesbian/Gay": "You are romantically interested in the same gender.",
            "Pansexual": "You are romantically interested in all genders.",
            "Bisexual": "You are romantically interested in more than one gender.",
            "Straight": "You are romantically interested in the opposite gender.",
            "Asexual": "You experience little or no sexual attraction, but still connect emotionally.",
            "Demisexual": "You only experience sexual attraction after forming a strong emotional bond.",
            "Queer": "You embrace a fluid understanding of sexuality.",
            "Questioning": "You are exploring your sexual orientation.",
            "Romantic": "You seek emotional connections without sexual attraction.",
            "Platonic": "You value deep friendships without romantic feelings.",
            "Autosexual": "You are primarily attracted to yourself.",
        },
        "normal": {
            "Friends": "You share a close, platonic bond.",
            "Best Friends": "You have a deep, trusting friendship.",
            "Family": "You share a familial bond, caring for each other deeply.",
            "Partners": "You are in a committed relationship, supporting each other.",
            "Lovers": "You share a romantic and intimate relationship.",
            "Soulmates": "You feel a deep, spiritual connection with each other.",
            "Romantic Partners": "You are in a loving, romantic relationship.",
            "Significant Others": "You are each other's primary romantic partner.",
            "Platonic Friends": "You share a close, non-romantic friendship.",
            "Close Friends": "You have a strong, trusting friendship.",
            "Acquaintances": "You know each other casually, without deep bonds.",
            "Colleagues": "You work together, sharing professional respect.",
            "Work Friends": "You share a friendly relationship at work.",
            "School Friends": "You share a friendship formed in a school setting.",
            "Childhood Friends": "You have known each other since childhood, sharing many memories.",
            "Online Friends": "You share a friendship formed online, often gaming or chatting.",
            "Gaming Buddies": "You enjoy playing games together, sharing a fun bond.",
            "Study Partners": "You help each other academically, sharing knowledge and support."
        }
    }

    def __init__(self, bot, server_channel_id):
        self.servers = {}
        self.channels = {}
        self.data = {}

        self.bot = bot
        self.server_channel_id = server_channel_id
        self.last_backup_message = None
        self.save_channel_id = None
    
        self.personality_modes = {}

        self.valid_relationship_levels = [
            "Stranger", "Acquaintance", "Friend", "Close Friend", "Partner", "Soulmate"
        ]

        self.valid_relationship_types = [
            "default", "Polyamory", "Lesbian/Gay", "Pansexual", "Bisexual", "Straight",
            "Asexual", "Demisexual", "Queer", "Questioning", "Romantic", "Platonic",
            "Autosexual", "Friends", "Companions", "Best Friends", "Family", "Partners",
            "Lovers", "Soulmates", "Romantic Partners", "Significant Others",
            "Platonic Friends", "Close Friends", "Acquaintances", "Colleagues",
            "Work Friends", "School Friends", "Childhood Friends", "Online Friends",
            "Gaming Buddies", "Study Partners"
        ]

        # Relationship modes per server
        self.relationship_modes = {}

    # ---------------- BASIC SERVER/CHANNEL TRACKING ----------------

    def _now(self):
        return datetime.datetime.utcnow().isoformat()

    async def save(self, bot, channel_id):
        channel = bot.get_channel(int(channel_id))
        if not channel:
            print(f"[Error] Could not find channel ID: {channel_id}")
            return

        for guild_id, info in self.data.items():
            personality = info.get("personality", [])
            relationship = info.get("relationship", {})

            formatted = (
                f"[Server ID: {guild_id}]\n"
                f"Personality: {', '.join(personality)}\n"
                f"Relationship Type: {relationship.get('type')}\n"
                f"With: {', '.join(relationship.get('with', []))}\n"
            )
            await channel.send(formatted)
            await asyncio.sleep(0.25)

    def ensure_guild(self, guild_id):
        self.data.setdefault(guild_id, {
            "personality": [],
            "relationship": {"level": "stranger", "with": []}
        })

    def track_server(self, guild_id, guild_name):
        guild_id = str(guild_id)
        if guild_id not in self.data:
            self.data[guild_id] = {
                "guild_name": guild_name,
                "channels": {},
                "personality_modes": [],
                "relationship": None
            }

    def track_channel(self, guild_id, channel_id, channel_name):
        guild_id = str(guild_id)
        channel_id = str(channel_id)
        if guild_id in self.data:
            channels = self.data.setdefault(guild_id, {}).setdefault("channels", {})
            channels[channel_id] = channel_name
        
    # ---------------- PERSONALITY MODE PERSISTENCE ----------------

    def set_personality(self, guild_id, personality_list):
        if not isinstance(personality_list, (list, set, tuple)):
            raise ValueError("Personality must be a list, set, or tuple of traits.")
        
        # Normalize: ensure list of strings with consistent capitalization
        clean_personality = []
        for mode in personality_list:
            if isinstance(mode, str):
                clean_personality.append(mode.capitalize())
            else:
                print(f"[WARN] Ignoring invalid personality entry: {mode} ({type(mode)})")
        
        if len(clean_personality) > 5:
            raise ValueError("Maximum of 5 personality traits allowed.")

        self.data.setdefault(str(guild_id), {})
        self.data[str(guild_id)]["personality"] = clean_personality

    def get_personality(self, guild_id):
        personality = self.data.get(guild_id, {}).get("personality", [])
        if isinstance(personality, str):
            return [personality]
        if isinstance(personality, list):
            return [str(p) for p in personality]  # force strings
        return ["Default"]  # fallback

    # ---------------- SETTING RELATIONSHIP MODE PERSISTENCE ----------------

    def set_relationship(self, guild_id, *, relationship_type=None, with_list=None):
        self.data.setdefault(guild_id, {})
        self.data[guild_id].setdefault("relationship", {})

        if relationship_type:
            normalized_types = [t.lower() for t in self.valid_relationship_types]
            if relationship_type.lower() not in normalized_types:
                raise ValueError(
                    f"Invalid type. Options: {', '.join(self.valid_relationship_types)}"
                )

            # figure out if it’s a parent or subtype
            canonical_type = self.valid_relationship_types[
                normalized_types.index(relationship_type.lower())
            ]

            # parent type detection (sexual, normal, default)
            if canonical_type.lower() in ["sexual", "normal", "default"]:
                self.data[guild_id]["relationship"]["type"] = canonical_type
                self.data[guild_id]["relationship"].pop("subtype", None)
            else:
                # subtype (Pansexual, Best Friends, etc.)
                self.data[guild_id]["relationship"]["subtype"] = canonical_type
                # assign parent depending on category
                if canonical_type in [
                    "Polyamory", "Lesbian/Gay", "Pansexual", "Bisexual", "Straight",
                    "Asexual", "Demisexual", "Queer", "Questioning", "Romantic",
                    "Platonic", "Autosexual"
                ]:
                    self.data[guild_id]["relationship"]["type"] = "sexual"
                else:
                    self.data[guild_id]["relationship"]["type"] = "normal"

        if with_list is not None:
            if not isinstance(with_list, list):
                raise ValueError("`with_list` must be a list of user IDs or names.")
            self.data[guild_id]["relationship"]["with"] = with_list

    def get_relationship(self, guild_id):
        return self.data.get(guild_id, {}).get("relationship", {})

    def normalize_id(self, guild_id):
        if isinstance(guild_id, list) and guild_id:
            return str(guild_id[0])
        return str(guild_id)

    def get_relationship_type(self, guild_id):
        guild_id = self.normalize_id(guild_id)
        return self.data.get(guild_id, {}).get("relationship", {}).get("type")
    
    def get_relationship_subtype(self, guild_id):
        guild_id = self.normalize_id(guild_id)
        return self.data.get(guild_id, {}).get("relationship", {}).get("subtype")
    
    def get_relationship_level(self, guild_id):
        guild_id = self.normalize_id(guild_id)
        return self.get_relationship(guild_id).get("level")

    def get_relationship_with(self, guild_id):
        guild_id = self.normalize_id(guild_id)
        return self.data.get(guild_id, {}).get("relationship", {}).get("with", [])
    
    def add_relationship_with(self, guild_id, user_id):
        self.data.setdefault(guild_id, {}).setdefault("relationship", {}).setdefault("with", [])
        if user_id not in self.data[guild_id]["relationship"]["with"]:
            self.data[guild_id]["relationship"]["with"].append(user_id)

    def remove_relationship_with(self, guild_id, user_id):
        with_list = self.data.get(guild_id, {}).get("relationship", {}).get("with", [])
        if user_id in with_list:
            with_list.remove(user_id)

    def clear_relationship(self, guild_id):
        if guild_id in self.data and "relationship" in self.data[guild_id]:
            self.data[guild_id]["relationship"] = {}

    def auto_set_relationship_level(self, guild_id, level):
        # Called internally, not user-exposed
        if level not in self.valid_relationship_levels:
            return
        self.data.setdefault(guild_id, {}).setdefault("relationship", {})
        self.data[guild_id]["relationship"]["level"] = level

    def get_relationship_level(self, guild_id):
        return self.data.get(guild_id, {}).get("relationship", {}).get("level", "stranger")
    
    def dokituber_relationship(self, user_id, amount=2):
        # Implement the relationship adjustment logic for Dokituber
        self.increase_relationship_meter(user_id, amount)

    def update_relationship_on_interaction(self, user_id, message):
        value = len(message) // 20  # 1 point per ~20 characters
        self.increase_relationship_meter(user_id, value)
    
    # ----------------  PERSISTENCE ----------------

    def set_memory_channel(self, guild_id, channel_id):
        if guild_id not in self.data:
            self.data[guild_id] = {}
        self.data[guild_id]["memory_channel_id"] = channel_id

    def get_memory_channel(self, guild_id):
        return self.data.get(guild_id, {}).get("memory_channel_id")

    async def log_to_channel(self, channel, guild_id):
        entry = self.data.get(guild_id)
        if not entry: return

        ts = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        text = f"[{ts}] Guild: {guild_id} | Personality: {entry.get('personality')} | Relationship: {entry.get('relationship')}"
        await channel.send(text)

    async def load_from_channel(self, bot, channel_id):
        channel = bot.get_channel(int(channel_id))
        if not channel:
            print(f"[Error] Could not find channel ID: {channel_id}")
            return

        async for message in channel.history(limit=100):
            if not message.content.startswith("[Server ID:"):
                continue
            try:
                lines = message.content.splitlines()
                guild_id = lines[0].split(": ")[1].strip("]")
                personality = lines[1].split(": ")[1].split(", ")
                relationship_type = lines[2].split(": ")[1]
                with_users = []
                if len(lines) > 3 and "With:" in lines[3]:
                    parts = lines[3].split(": ", 1)
                    if len(parts) > 1 and parts[1].strip():
                        with_users = [u.strip() for u in parts[1].split(",") if u.strip()]

                self.data[guild_id] = {
                    "personality": personality,
                    "relationship": {
                        "type": relationship_type,
                        "with": with_users
                    }
                }
            except Exception as e:
                print(f"[Parse Error] Could not parse server data: {e}")
