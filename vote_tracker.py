import json
import discord

class VoteTracker:
    def __init__(self):
        self.votes = {}  # {guild_id: {"options": [...], "votes": {user_id: choice}}}

    def ensure_vote(self, guild_id):
        if guild_id not in self.votes:
            self.votes[guild_id] = {"options": [], "votes": {}}

    def set_vote(self, guild_id, options):
        self.votes[guild_id] = {"options": options, "votes": {}}

    def get_vote(self, guild_id):
        return self.votes.get(guild_id, None)

    def clear_vote(self, guild_id):
        if guild_id in self.votes:
            del self.votes[guild_id]

    async def save(self, bot, channel_id: int):
        """Save votes to the tracker channel as embeds without deleting old messages."""
        channel = bot.get_channel(channel_id)
        if not channel:
            return

        # Instead of deleting old messages, just append new embeds
        for guild_id, data in self.votes.items():
            embed = discord.Embed(
                title=f"🗳️ Vote Data for Guild {guild_id}",
                color=discord.Color.orange()
            )
            embed.add_field(name="Options", value="\n".join(data["options"]), inline=False)

            votes_summary = []
            for user_id, choice in data["votes"].items():
                votes_summary.append(f"<@{user_id}> → Option {choice}")
            if not votes_summary:
                votes_summary = ["No votes yet"]

            embed.add_field(name="Votes", value="\n".join(votes_summary), inline=False)
            embed.set_footer(text=f"Menu ID: {data.get('menu_id', 'N/A')}")

            await channel.send(embed=embed)

    async def load(self, bot, channel_id: int):
        channel = bot.get_channel(channel_id)
        if not channel:
            return
        try:
            async for msg in channel.history(limit=1, oldest_first=False):
                if msg.author == bot.user and msg.content.startswith("```json"):
                    data = msg.content.strip("```json\n").strip("```")
                    self.votes = json.loads(data)
        except Exception as e:
            print(f"[VoteTracker Load Error] {e}")
