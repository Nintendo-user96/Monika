import discord
import asyncio
import subprocess
import sys
import py_compile
import traceback
import datetime
import os
import ast
import textwrap

# === CONFIG ===
BOT_FILE = "monika_bot.py"        # main bot file
SETTINGS_CHAN = int(os.getenv("SETTINGS_CHANNEL", "0"))  # channel ID where errors get reported
ERROR_LOG_FILE = "error_log.txt"

CHECK_INTERVAL = 30
SPAM_COOLDOWN = 120

IGNORED_ERRORS = [
    "HTTPException: 429 Too Many Requests",
    "Gateway not connected",
    "Bad Request",
    "Task was destroyed but it is pending",
    "ClientConnectorError",
    "aiohttp.client_exceptions.ClientOSError",
    "discord.errors.GatewayNotFound",
]

# Discord client
intents = discord.Intents.default()
client = discord.Client(intents=intents)

status_info = {
    "last_error": "None",
    "error_count": 0,
    "started": datetime.datetime.utcnow(),
    "monika_online": False,
    "last_sent_error": None,
    "last_sent_time": None,
}

def should_ignore(error_text: str) -> bool:
    """Check if an error should be ignored based on known noise patterns."""
    return any(ignored.lower() in error_text.lower() for ignored in IGNORED_ERRORS)

# === Append error to log file ===
def log_error_to_file(error_msg: str):
    with open(ERROR_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(
            f"[{datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}]\n"
            f"{error_msg}\n"
            f"{'-'*60}\n"
        )


def scan_functions_in_file(filepath):
    results = []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source, filename=filepath)

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func_name = node.name
                func_lineno = node.lineno

                # Try to extract full function source
                try:
                    func_src = ast.get_source_segment(source, node)
                except Exception:
                    # Fallback: just grab the first line
                    func_src = source.splitlines()[func_lineno - 1]

                try:
                    compile(func_src, filepath, "exec")
                except Exception as e:
                    results.append(
                        f"❌ Error in {filepath} → function `{func_name}` "
                        f"(line {func_lineno}): {e}"
                    )
    except Exception as e:
        results.append(f"⚠️ Could not scan {filepath}: {e}")
    return results


def scan_all_functions():
    errors = []
    for root, _, files in os.walk("."):
        for file in files:
            if file.endswith(".py"):
                filepath = os.path.join(root, file)
                errors.extend(scan_functions_in_file(filepath))
    return errors


# === Notify channel with log file (anti-spam) ===
async def notify_error(error_msg: str):
    now = datetime.datetime.utcnow()
    if (
        status_info["last_sent_error"] == error_msg
        and status_info["last_sent_time"]
        and (now - status_info["last_sent_time"]).total_seconds() < SPAM_COOLDOWN
    ):
        print("[Detector] Duplicate error suppressed.")
        return

    log_error_to_file(error_msg)

    await client.wait_until_ready()
    channel = client.get_channel(SETTINGS_CHAN)
    if channel:
        embed = discord.Embed(
            title="🚨 Error Detected",
            description=error_msg[:1000],
            color=discord.Color.red(),
            timestamp=now
        )
        await channel.send(embed=embed)
        if os.path.exists(ERROR_LOG_FILE):
            await channel.send(file=discord.File(ERROR_LOG_FILE))

    status_info["last_error"] = error_msg
    status_info["error_count"] += 1
    status_info["last_sent_error"] = error_msg
    status_info["last_sent_time"] = now


# === Run Monika and monitor ===
async def run_bot_and_watch():
    while True:
        try:
            process = await asyncio.create_subprocess_exec(
                sys.executable, BOT_FILE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            status_info["monika_online"] = True
            print("[Detector] Monika process started.")
            _, stderr = await process.communicate()
            status_info["monika_online"] = False

            if stderr:
                err = stderr.decode()
                if not any(ignored in err for ignored in IGNORED_ERRORS):
                    await notify_error(f"⚠️ Runtime Error:\n{err}")

        except Exception as e:
            await notify_error(f"❌ Detector failed to start Monika:\n{e}")

        await asyncio.sleep(5)


# === Periodic status check ===
async def check_monika_status():
    await client.wait_until_ready()
    while True:
        if not status_info["monika_online"]:
            await notify_error("⚠️ Monika is offline or crashed!")
        await asyncio.sleep(CHECK_INTERVAL)

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

# === Startup ===
async def main():
    print("[Detector] Starting error scanner...")

    # 🔎 Full function-level scan
    errors = scan_all_functions()
    if errors:
        msg = "\n".join(errors)
        await notify_error(f"❌ Function-level scan found problems:\n{msg}")
        print("[Detector] Function scan found problems, but Monika will still launch.")
    else:
        log_error_to_file("✅ Function-level scan complete. No issues found!")
        print("[Detector] Function scan passed. Launching Monika...")

    # 🚀 Always launch Monika
    await asyncio.gather(
        run_bot_and_watch(),
        check_monika_status()
    )


if __name__ == "__main__":
    asyncio.run(main())
