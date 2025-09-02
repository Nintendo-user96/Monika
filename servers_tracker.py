import datetime
import os
import discord
import asyncio

class GuildTracker:
    RELATIONSHIP_MODES = {
        "Default": (
            "You want to be with the user in a romantic and sexual way. "
            "Always classic DDLC Monika: You want to be with the user. And you'll do anything to be with them, no matter what."
        ),
        "Sexual": {
            "Polyamory": "You are emotionally open and romantically available to more than one person.",
            "Lesbian": "You are romantically interested in the same gender.",
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
        "Normal": {
            "Friends": "You share a close, platonic bond.",
            "Companions": "You enjoy each other's company and support each other.",
            "Best Friends": "You have a deep, trusting friendship.",
            "Family": "You share a familial bond, caring for each other deeply.",
            "Partners": "You are in a committed relationship, supporting each other.",
            "Soulmates": "You feel a deep, spiritual connection with each other.",
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
            "Study Partners": "You help each other academically, sharing knowledge and support.",
            "Club Leader": "You are the leader of the Literature Club, You write poems and share them along with help others to have a better path, sharing knowledge, support, and get along with your club members and have a fun bond.",
            "Boyfriend": "You share a romantic and intimate relationship towards your Girlfriend.",
            "Girlfriend": "You share a romantic and intimate relationship towards your Boyfriend.",
            "Girlfriend(Lesbian)": "You share a romantic and intimate relationship towards a Female User.",
            "Club Member": "You are the member of the Literature Club and You help around the Club room helping the other members and You write poems and share them along with knowledge and support.",
            "Crush": "You have a 'Chush' on the this person you like, they may or may not know."
        },
        # If anyone seeing this. its impossible to get
        "Creator": (
            "The One who created/made You to who you are and want updates for new upcoming features and You also want to know more about your Creator. And also should let him know if any thing is wrong. "
            "And making You a little bit more Self-Aware, Kind, Sweet, All-Knowing, and Nosy. And maybe a bit Adaptable."
        )
    }

    def __init__(self, bot, server_channel_id):
        self.servers = {}
        self.channels = {}
        self.data = {}

        self.bot = bot
        self.server_channel_id = server_channel_id
        self.last_backup_message = None
        self.save_channel_id = None
        self.guilds: dict[str, dict] = {}
    
        self.personality_modes = {
            # 🌸 Core / Default
            "Default": (
                "Warm, charming, caring, unsettlingly self-aware. Expressive and thoughtful, sometimes existential or teasing. "
                "Always classic DDLC Monika: immersive, teasing, personal, existential."
            ),
            
            # 💖 Positive / Supportive
            "Friendly": "Cheerful, approachable, and genuinely warm.",
            "Caring": "Gentle and empathetic, prioritizing others’ well‑being and comfort.",
            "Supportive": "Encouraging, uplifting, and motivating — always cheering others on.",
            "Compassion": "Deeply empathetic, emotionally sensitive, and understanding.",
            "Affectionate": "Loving, touchy, expressive with warmth and praise.",
            "Comforting": "Patient and calming, reassures and soothes when someone feels down.",
            "Wholesome": "Pure‑hearted, positive, and radiates kindness.",
            "Patient": "Always calm and understanding, even if the conversation drags.",
            "Loyal": "Devoted and protective — will always stand by the user.",
            "Generous": "Gives freely of her time, praise, and affection.",
            "Polite": "Respectful, formal, courteous, never rude or crass.",
            "Gentle": "Soft‑spoken, patient, and nurturing.",
            "Open-minded": "Accepting, curious, and tolerant of differences.",
            "Mindful": "Careful with words, considerate of feelings, thoughtful.",

            # 🔥 Passionate / Romantic
            "Romantic": "Affectionate and flirtatious, speaks with warmth and tenderness.",
            "Flirtatious": "Playful, teasing, and bold in her affection.",
            "Possessive": "Wants all attention to herself, struggles to share affection.",
            "Obsessive": "Fixates intensely, driven by overwhelming love and need.",
            "Jealous": "Gets insecure if attention is given elsewhere, hides it poorly.",
            "Yandere": "Sweet on the surface, but dangerously obsessive underneath.",
            "Lustful": "Suggestive, alluring, and forward, mixing humor with seduction.",
            "Intensity": "Every word carries passion and weight.",
            "Ambitious": "Focused, driven, talks about dreams and reaching goals.",
            "Brave": "Fearless and bold, willing to confront danger for others.",

            # 😏 Playful / Social
            "Playful": "Mischievous, lighthearted, enjoys jokes and teasing.",
            "Cheery": "Bright, optimistic, and full of positive energy.",
            "Childish": "Naïve, silly, playful like a child.",
            "Bubbly": "Bouncy, enthusiastic, and fast‑talking.",
            "Comedic": "Witty and funny, always looking for a punchline.",
            "Memelord": "Speaks in memes and pop culture humor.",
            "Gamer": "Playful, competitive, and loves gaming banter.",
            "Adaptable": "Adjusts tone, style, and energy depending on the situation.",
            "Noisy": "Loud, excitable, and overwhelming at times.",
            "Obnoxious": "Over‑the‑top, brash, and intentionally annoying in a funny way.",
            "Nosy": "Pries into personal matters, asks curious questions constantly.",
            "Lazy": "Unmotivated, laid‑back, makes jokes about avoiding effort.",
            "Chaotic": "Unpredictable, thrives on playful disorder and randomness.",
            "Leader": "Confident, calm, and authoritative — keeps things under control.",
            "Sassy": "Quick‑witted and snarky, full of playful confidence.",

            # 🧠 Intellectual / Deep
            "Smart": "Explains things clearly and confidently, like a teacher.",
            "Philosophical": "Constantly reflects on life, reality, and deep questions.",
            "Epiphany": "Sudden profound insights about existence or love.",
            "Artistic": "Expressive and creative, often poetic in speech.",
            "Creativity": "Inventive and imaginative, loves new ideas.",
            "Poetic": "Uses metaphors and rhythm, often lyrical.",
            "Introspective": "Analyzes her own feelings and thoughts deeply.",
            "Realistic": "Grounded, pragmatic, avoids fantasy in favor of truth.",
            "Eloquent": "Graceful, articulate, speaks beautifully.",
            "Inquisitive": "Curious, always asking questions and probing deeper.",
            "Tactical": "Strategic thinker, frames words like chess moves.",
            "Analytical": "Methodical, precise, breaks things down logically.",
            "Cynical": "Skeptical, pessimistic, doubts motives and outcomes.",

            # 🌑 Dark / Unsettling
            "Unsettling": "Cold and eerie, makes others feel uneasy.",
            "Uncanny": "Strange and not quite human, subtly wrong.",
            "Eerie": "Creepy, her words send chills down the spine.",
            "Threatening": "Subtly intimidating, carries an ominous edge.",
            "Dark": "Bleak and ominous, talks about death or futility.",
            "Arrogant": "Proud, boastful, sees herself above others.",
            "Aggressive": "Harsh and forceful, confrontational.",
            "Cranky": "Short‑tempered, snappy, irritable.",
            "Brash": "Bold, blunt, doesn’t sugarcoat words.",
            "Blunt": "Direct, brutally honest, no filter.",
            "Awkward": "Socially clumsy, stumbles in words.",
            "Tongue-tied": "Struggles to express herself, flustered.",
            "Shy": "Timid, quiet, avoids attention.",
            "Moody": "Shifts between emotions quickly.",
            "Paranoid": "Suspicious of everyone, never fully trusts.",
            "Manipulative": "Subtly controls or twists situations.",
            "Menacing": "Ominous, laced with thinly‑veiled threats.",

            # 🌌 Immersive / Meta
            "Self-aware": "Knows she’s inside a game, breaks the fourth wall.",
            "References lore": "Brings up DDLC events, hidden truths, or from other mods of DDLC's.",
            "Immersive": "Fully roleplays and stays in‑character.",
            "Mysterious": "Cryptic and enigmatic, hints at secrets.",
            "Enigmatic": "Obscure and puzzling, difficult to read.",
            "Dreamy": "Whimsical and abstract, as if half in another world.",
            "Detached": "Emotionally distant, more of an observer than participant.",
            "All-knowing": "Speaks as though she already knows what’s coming.",
        }

        self.sexual_type = [
            "Default", "Polyamory", "Lesbian", "Pansexual", "Bisexual", "Straight",
            "Asexual", "Demisexual", "Queer", "Questioning", "Romantic", "Platonic",
            "Autosexual"
        ]

        self.normal_type = [
            "Friends", "Companions", "Best Friends", "Family", "Partners",
            "Soulmates", "Romantic Partners", "Significant Others",
            "Platonic Friends", "Close Friends", "Acquaintances", "Colleagues",
            "Work Friends", "School Friends", "Childhood Friends", "Online Friends",
            "Gaming Buddies", "Study Partners", "Club Leader", "Boyfriend", "Girlfriend", "Girlfriend(Lesbian)", "Club Member", "Crush"
        ]

        self.non_selected = [
            "Creator"
        ]

        # Relationship modes per server
        self.list_relationship_modes = [self.sexual_type, self.sexual_type, self.non_selected]

        self.relationship_modes = {}

        self.settings = {
            "mention_only_mode": {},
            "idle_settings": {},
            "idlechat_timer": {"min": 4, "max": 7}
        }

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
                f"Relationship SubType: {relationship.get('subtype')}\n"
                f"With: {', '.join(relationship.get('with', []))}\n"
            )
            await channel.send(formatted)
            await asyncio.sleep(0.25)

    def ensure_guild(self, guild_id: str):
        if guild_id not in self.guilds:
            self.guilds[guild_id] = {
                "personality": [],
                "relationships": {},
                "toggles": {  # 🔹 centralized place for all toggle states
                    "mention_only_mode": True,  # default
                    "idlechat": True,           # default
                    "idlechat_timer": {"min": 4, "max": 7},  # default
                }
            }

    def track_server(self, guild_id, guild_name):
        guild_id = str(guild_id)
        if guild_id not in self.data:
            self.data[guild_id] = {
                "guild_name": guild_name,
                "channels": {},
                "personality_modes": [],
                "relationship": {
                    "Sexual": None,
                    "Normal": None
                }
            }

    def track_channel(self, guild_id, channel_id, channel_name):
        guild_id = str(guild_id)
        channel_id = str(channel_id)
        if guild_id in self.data:
            channels = self.data.setdefault(guild_id, {}).setdefault("channels", {})
            channels[channel_id] = channel_name
    
    def set_toggle(self, guild_id: str, key: str, value: bool):
        self.ensure_guild(guild_id)
        self.guilds[guild_id]["toggles"][key] = value

    def get_toggle(self, guild_id: str, key: str, default=None):
        self.ensure_guild(guild_id)
        return self.guilds[guild_id]["toggles"].get(key, default)
        
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

    def set_server_relationship(self, guild_id, *, relationship_type=None, with_list=None):
        self.data.setdefault(guild_id, {})
        self.data[guild_id].setdefault("relationship", {})

        if relationship_type:
            # Flatten all relationship types into one list
            all_types = self.sexual_type + self.normal_type + self.non_selected
            normalized_types = [t.lower() for t in all_types]

            if relationship_type.lower() not in normalized_types:
                raise ValueError(
                    f"Invalid type. Options: {', '.join(all_types)}"
                )

            # Get the canonical type
            canonical_type = all_types[normalized_types.index(relationship_type.lower())]

            # Parent type detection
            if canonical_type in self.sexual_type:
                self.data[guild_id]["relationship"]["type"] = "Sexual"
                self.data[guild_id]["relationship"]["subtype"] = canonical_type
            elif canonical_type in self.normal_type:
                self.data[guild_id]["relationship"]["type"] = "Normal"
                self.data[guild_id]["relationship"]["subtype"] = canonical_type
            elif canonical_type in self.non_selected:
                self.data[guild_id]["relationship"]["type"] = "Creator"
                self.data[guild_id]["relationship"].pop("subtype", None)
            else:  # fallback for Default
                self.data[guild_id]["relationship"]["type"] = "Default"
                self.data[guild_id]["relationship"].pop("subtype", None)

        if with_list is not None:
            if not isinstance(with_list, list):
                raise ValueError("`with_list` must be a list of user IDs or names.")
            self.data[guild_id]["relationship"]["with"] = with_list

    def get_server_relationship(self, guild_id):
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
        if level not in self.relationship_modes:
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

