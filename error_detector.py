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

CHECK_INTERVAL = 30

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

                try:
                    func_src = ast.get_source_segment(source, node)
                except Exception:
                    func_src = source.splitlines()[func_lineno - 1]

                try:
                    compile(func_src, filepath, "exec")
                except Exception as e:
                    results.append(
                        f"❌ {filepath} → `{func_name}` (line {func_lineno}): {e}"
                    )
    except Exception as e:
        results.append(f"[SCAN] ⚠️ Could not scan {filepath}: {e}")
    return results


def scan_code():
    print("[SCAN] Starting full project scan...")
    errors = []
    for root, _, files in os.walk("."):
        for file in files:
            if file.endswith(".py"):
                filepath = os.path.join(root, file)
                errors.extend(scan_functions_in_file(filepath))

    if errors:
        print("\n".join(errors))
    else:
        print("[SCAN] ✅ No issues found.")

    return errors

async def send_scan_results(bot: discord.Client):
    errors = scan_code()
    channel = bot.get_channel(SETTINGS_CHAN)
    if not channel:
        print("[SCAN] ⚠️ Could not find SETTINGS_CHAN.")
        return

    if errors:
        msg = "\n".join(errors)
        if len(msg) > 1900:
            msg = msg[:1900] + "\n... (truncated)"
        await channel.send(f"🚨 Function-level scan problems:\n```{msg}```")
    else:
        await channel.send("✅ Function-level scan complete. No issues found!")

# === Run and monitor the bot process ===
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

            stdout, stderr = await process.communicate()
            status_info["monika_online"] = False

            if stderr:
                err = stderr.decode()
                print(f"[Detector] ⚠️ Runtime Error:\n{err}")
                status_info["error_count"] += 1
                status_info["last_error"] = err

        except Exception as e:
            print(f"[Detector] ❌ Failed to start Monika: {e}")

        await asyncio.sleep(5)

# === Periodic check ===
async def check_monika_status():
    while True:
        if not status_info["monika_online"]:
            print("[Detector] ⚠️ Monika is offline or crashed!")
        await asyncio.sleep(CHECK_INTERVAL)

async def report_error(bot: discord.Client, channel_id: int, error_text: str, severity: str = "Error"):
    """Send errors/warnings as an embed to a channel using the existing bot."""
    if should_ignore(error_text):
        print("⚪ Ignored:", error_text)
        return

    channel = bot.get_channel(channel_id)
    if not channel:
        print("⚠️ Error channel not found.")
        return

    embed = discord.Embed(
        title=f"❌ {severity} Detected",
        description=f"```{error_text[:2000]}```",
        color=0xE74C3C if severity == "Error" else 0xF1C40F,
        timestamp=datetime.datetime.utcnow()
    )
    embed.set_footer(text="Error Monitor Service")

    await channel.send(embed=embed)

# === Startup ===
async def main():
    print("[Detector] Starting error scanner...")

    # 🔎 Full scan before launching Monika
    scan_code()

    # 🚀 Always launch Monika
    await asyncio.gather(
        run_bot_and_watch(),
        check_monika_status()
    )


if __name__ == "__main__":
    asyncio.run(main())
