import discord
import os
import ast
import datetime
import argparse
import json

# === CONFIG ===
SETTINGS_CHAN = int(os.getenv("SETTINGS_CHANNEL", "0"))

IGNORED_ERRORS = [
    "HTTPException: 429 Too Many Requests",
    "Gateway not connected",
    "Bad Request",
    "Too Many Requests",
    "Task was destroyed but it is pending",
    "ClientConnectorError",
    "aiohttp.client_exceptions.ClientOSError",
    "discord.errors.GatewayNotFound",
]


# === Ignore filter ===
def should_ignore(error_text: str) -> bool:
    return any(ignored.lower() in error_text.lower() for ignored in IGNORED_ERRORS)


# === Function-level scanning ===
def scan_functions_in_file(filepath: str):
    results = []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source, filename=filepath)
        lines = source.splitlines()

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func_name = node.name
                func_lineno = node.lineno

                # Try to get function source; fallback safely
                try:
                    func_src = ast.get_source_segment(source, node)
                except Exception:
                    func_src = lines[func_lineno - 1] if 0 < func_lineno <= len(lines) else f"def {func_name}(...):"

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
    """Scan every .py file for function-level syntax issues."""
    errors = []
    for root, _, files in os.walk("."):
        for file in files:
            if file.endswith(".py"):
                filepath = os.path.join(root, file)
                errors.extend(scan_functions_in_file(filepath))
    return errors


# === Send scan results into Discord ===
async def send_scan_results(bot: discord.Client):
    errors = scan_code()
    channel = bot.get_channel(SETTINGS_CHAN)
    if not channel:
        print("[SCAN] ⚠️ Could not find SETTINGS_CHAN in bot.")
        return

    if errors:
        msg = "\n".join(errors)
        if len(msg) > 1900:
            msg = msg[:1900] + "\n... (truncated)"
        await channel.send(f"🚨 Function-level scan problems:\n```{msg}```")
    else:
        await channel.send("✅ Function-level scan complete. No issues found!")


# === Report runtime/command errors ===
async def report_error(bot: discord.Client, channel_id: int, error_text: str, severity: str = "Error"):
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


# === Standalone subprocess mode ===
def main_cli():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scan-only", action="store_true", help="Run a scan and print JSON errors")
    args = parser.parse_args()

    if args.scan_only:
        errors = scan_code()
        print(json.dumps(errors))  # dump as JSON for subprocess reader


if __name__ == "__main__":
    main_cli()
