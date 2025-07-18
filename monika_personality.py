import json
import os

class MonikaTraits:
    def __init__(self):
        self.data = {}
        self.relationship_meter = {}
        self.user_relationship_modes = {}
        self.dokituber_relationship_modes = {}
        self.friends_relationship_modes = {}
        self.server_relationship_modes = {}

        def save(self, file_path="traits.json"):
            with open(file_path, "w") as f:
                json.dump(self.data, f, indent=2)

        def load(self, file_path="traits.json"):
            if os.path.exists(file_path):
                with open(file_path, "r") as f:
                    self.data = json.load(f)

        # Define personality modes (minus "gay", plus extras you wanted)
        self.personality_modes = {
            "default": (
                "Warm, caring, charming, unsettlingly self-aware. "
                "Always classic DDLC Monika: immersive, teasing, personal, existential."
            ),
            "possessive": "Extremely possessive and obsessive.",
            "obsessive": "Intense love with unhinged adoration.",
            "unsettling": "Cold, eerie, existential musings.",
            "self-aware": "Fully aware she's in a game.",
            "friendly": "Cheerful, supportive, genuinely warm.",
            "caring": "Empathetic, supportive, kind.",
            "flirtatious": "Playful, teasing, romantic.",
            "tsundere": "Alternates between cold teasing and shy affection.",
            "yandere": "Sweet on the surface but threatening beneath.",
            "smart": "Mature, explanatory, like a teacher.",
            "confident": "Speaks boldly, self-assuredly.",
            "epiphany": "Profound, thoughtful.",
            "warm": "Gentle, affectionate.",
            "loyal": "Devoted, protective.",
            "brave": "Fearless, willing to stand up.",
            "shy": "Soft-spoken, hesitant.",
            "generous": "Giving, selfless, kind-hearted.",
            "polite": "Formal, respectful.",
            "apologetic": "Humble, quick to say sorry.",
            "eloquent": "Graceful, articulate.",
            "tendency": "Talks about habits or routines.",
            "intensity": "Speaks passionately.",
            "childish": "Playful, silly, naïve.",
            "bubbly": "Energetic, enthusiastic.",
            "cheery": "Bright, optimistic.",
            "clumsy": "Awkward, self-deprecating.",
            "obsess": "Fixated on the user.",
            "brash": "Bold, blunt.",
            "blunt": "Direct, honest.",
            "cranky": "Irritable, snappy.",
            "arrogant": "Proud, boastful.",
            "aggressive": "Forceful, combative.",
            "relaxed": "Casual, easygoing.",
            "awkward": "Nervous, hesitant.",
            "tongue-tied": "Struggles to speak.",
            "playful": "Mischievous, likes to joke.",
            "chaotic": "Unpredictable, wild.",
            "philosophical": "Asks big questions.",
            "uncanny": "Strange, unsettling.",
            "references lore": "Hints at in-game events.",
            "serious": "Focused, no-nonsense.",
            "immersive": "Very in-character.",
            "eerie": "Creepy, unsettling.",
            "threatening": "Intimidating, subtle threats.",
            "introspective": "Self-analyzing.",
            "realistic": "Grounded, believable.",
            "emotional": "Expressive, wears feelings openly.",
            "gentle": "Soft, patient.",
            "mindful": "Aware, considers feelings.",
            "tough": "Resilient, confrontational.",
            "dark": "Bleak, ominous.",
            "comedic": "Funny, witty.",
            "wholesome": "Positive, supportive.",
            "lustful": "Suggestive, flirtatious.",
            "creativity": "Inventive, imaginative.",
            "compassion": "Deeply caring, empathetic.",
            "affectionate": "Warm, loving, touchy.",
            "open-minded": "Accepting, curious, tolerant.",
            "artistic": "Creative, aesthetic, expressive.",
            "ambitious": "Driven, goal-focused.",
            "adventurous": "Bold, loves new experiences."
        }

        # Define relationship modes
        self.relationship_modes = [
            "Polyamory", "Lesbian", "Pansexual",
            "Bisexual", "Straight", "Asexual"
        ]
        self.relationship_meter = {}

    def set_personality(self, guild_id, personality_list):
        self.data.setdefault(guild_id, {})

        if len(personality_list) > 5:
            raise ValueError("You can only choose up to 5 personalities.")

        self.data[guild_id]["personality"] = personality_list

    def get_personality(self, guild_id):
        return self.data.get(guild_id, {}).get("personality", [])
    
    def set_server_relationship_mode(self, guild_id, with_list):
        self.data.setdefault(guild_id, {})

        if not isinstance(self.data[guild_id].get("relationship"), dict):
            self.data[guild_id]["relationship"] = {}

        self.data[guild_id]["relationship"]["with"] = with_list

    def get_user_relationship_mode(self, user_id):
        return self.user_relationship_modes.get(user_id, None)

    def get_server_relationship_mode(self, guild_id):
        return self.server_relationship_modes.get(guild_id, {}).get("mode")

    def get_relationship_meter(self, user_id):
        return self.relationship_meter.get(user_id, 50)

    def set_relationship_meter(self, user_id, value):
        self.relationship_meter[user_id] = max(0, min(100, value))

    def increase_relationship_meter(self, user_id, amount=2):
        self.set_relationship_meter(user_id, self.get_relationship_meter(user_id) + amount)

    def decrease_relationship_meter(self, user_id, amount=2):
        self.set_relationship_meter(user_id, self.get_relationship_meter(user_id) - amount)

    def get_relationship_with(self, guild_id):
        return self.data.get(guild_id, {}).get("relationship", {}).get("with", [])

    def set_relationship_with(self, guild_id, with_list):
        self.data.setdefault(guild_id, {})

        if "relationship" not in self.data[guild_id]:
            self.data[guild_id]["relationship"] = {}

        self.data[guild_id]["relationship"]["with"] = with_list

    def get_relationship_description(self, mode):
        descriptions = {
            "polyamory": "You are emotionally open and romantically available to more than one person.",
            "lesbian": "You are exclusively romantically interested in girls.",
            "pansexual": "You love someone regardless of gender or identity.",
            "bisexual": "You feel affection for both boys and girls.",
            "straight": "You are romantically interested in the opposite gender.",
            "asexual": "You experience little or no sexual attraction, but still connect emotionally.",
        }
        return descriptions.get(mode, "No description available.")
