import json
import discord
import asyncio
import uuid

# vote_tracker.py
class VoteTracker:
    def __init__(self):
        self.global_vote = {
            "title": None,
            "options": [],
            "votes": {},  # user_id -> choice index
        }
        self.votes = {}

    def set_vote(self, title, options):
        self.global_vote = {
            "title": title,
            "options": options,
            "votes": {},
        }

    def add_vote(self, user_id, choice_index):
        self.global_vote["votes"][str(user_id)] = choice_index

    def get_vote(self):
        return self.global_vote

    def clear_vote(self):
        self.global_vote = {"title": None, "options": [], "votes": {}}

    def get_results(self, guild_id):
        """Count votes per option."""
        vote = self.votes.get(guild_id)
        if not vote:
            return []
        counts = {i: 0 for i in range(1, len(vote["options"]) + 1)}
        for choice in vote["votes"].values():
            counts[choice] += 1
        return counts

    async def save(self, bot, channel_id: int):
        """Safely save all votes (keyed by menu_id) without deleting anything."""
        try:
            channel = bot.get_channel(channel_id)
            if not channel:
                print(f"[VoteTracker] ⚠️ Save failed: Channel {channel_id} not found.")
                return

            serialized = json.dumps(self.votes, indent=2)
            chunks = [serialized[i:i+1900] for i in range(0, len(serialized), 1900)]

            # Use or create pinned save message
            existing = None
            async for msg in channel.history(limit=25):
                if msg.author == bot.user and msg.content.startswith("VOTE_TRACKER_SAVE:"):
                    existing = msg
                    break

            content = f"VOTE_TRACKER_SAVE:\n```json\n{chunks[0]}\n```"
            if existing:
                await existing.edit(content=content)
            else:
                await channel.send(content)

            print("[VoteTracker] ✅ Votes saved safely (no purge).")

        except discord.Forbidden:
            print("[VoteTracker] ⚠️ Missing permission to edit messages or pins.")
        except Exception as e:
            print(f"[VoteTracker Save Error] {e}")

    async def load(self, bot, channel_id: int, menu_id: str | None = None):
        """Load votes safely from storage channel without touching user messages."""
        try:
            channel = bot.get_channel(channel_id)
            if not channel:
                print(f"[VoteTracker] ⚠️ Load failed: Channel {channel_id} not found.")
                return

            async for msg in channel.history(limit=50):
                if msg.author == bot.user and msg.content.startswith("VOTE_TRACKER_SAVE:"):
                    try:
                        json_data = msg.content.split("```json\n")[1].split("\n```")[0]
                        loaded_data = json.loads(json_data)

                        # Detect if it's a global dict or multiple menu IDs
                        if isinstance(loaded_data, dict):
                            self.votes = loaded_data

                            # If menu_id provided, load that one only
                            if menu_id and menu_id in self.votes:
                                self.votes["global"] = self.votes[menu_id]
                                print(f"[VoteTracker] ✅ Loaded vote with ID {menu_id}")
                            else:
                                # Otherwise pick the most recent or fallback
                                if "global" not in self.votes:
                                    if len(self.votes) == 1:
                                        self.votes["global"] = next(iter(self.votes.values()))
                                    else:
                                        latest_key = sorted(self.votes.keys())[-1]
                                        self.votes["global"] = self.votes[latest_key]
                                print(f"[VoteTracker] ✅ Loaded latest/global vote.")
                            return

                    except Exception as e:
                        print(f"[VoteTracker Load Parse Error] {e}")
                        return

            print("[VoteTracker] ⚠️ No saved vote data found.")
        except Exception as e:
            print(f"[VoteTracker Load Error] {e}")
