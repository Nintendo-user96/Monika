import discord
import datetime

# ===== CONFIG =====
IGNORED_ERRORS = [
    # Discord.py Command Errors
    "CommandNotFound",
    "MissingPermissions",
    "CheckFailure",
    "DisabledCommand",

    # API & Gateway
    "Gateway not responding",
    "ConnectionResetError",
    "Connection closed",
    "Bad Request",
    "Too Many Requests",  # rate limit
    "HTTPException",
    "ClientOSError",

    # Runtime / benign
    "Task was destroyed but it is pending",
    "CancelledError",
    "RuntimeWarning"
]
# ==================

def should_ignore(error_text: str) -> bool:
    """Check if an error should be ignored based on known noise patterns."""
    return any(ignored.lower() in error_text.lower() for ignored in IGNORED_ERRORS)

async def report_error(bot: discord.Client, channel_id: int, error_text: str, severity: str = "Error"):
    """Send errors/warnings as an embed to a channel."""
    if should_ignore(error_text):
        print("⚪ Ignored:", error_text)
        return

    channel = bot.get_channel(channel_id)
    if not channel:
        print("⚠️ Error channel not found.")
        return

    print("❌ Reporting:", error_text)

    embed = discord.Embed(
        title=f"❌ {severity} Detected",
        description=f"```{error_text[:2000]}```",  # truncate to Discord limit
        color=0xE74C3C if severity == "Error" else 0xF1C40F,
        timestamp=datetime.datetime.utcnow()
    )
    embed.set_footer(text="Error Monitor Service")

    await channel.send(embed=embed)