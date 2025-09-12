from flask import Flask
from threading import Thread
import time, os, sys, requests, logging

app = Flask(__name__)

# Track last heartbeat
last_seen = time.time()

@app.route('/')
def home():
    global last_seen
    last_seen = time.time()  # refresh heartbeat
    return "Just Monika"

def run():
    app.run(host="0.0.0.0", port=8080)

def watchdog(timeout=180):
    """Restart if no heartbeat within timeout (seconds)."""
    global last_seen
    while True:
        if time.time() - last_seen > timeout:
            logging.error("❌ Watchdog: no heartbeat, restarting...")
            sys.stdout.flush()
            os._exit(1)  # hosting service restarts us
        time.sleep(60)

def self_ping(url, delay=60):
    """Ping our own server every `delay` seconds to feed watchdog."""
    global last_seen
    while True:
        try:
            requests.get(url, timeout=5)
            last_seen = time.time()
            logging.info(f"✅ Self-ping successful → {url}")
        except Exception as e:
            logging.warning(f"⚠️ Self-ping failed: {e}")
        time.sleep(delay)

def keep_alive():
    # Start Flask server
    t = Thread(target=run, daemon=True)
    t.start()

    # Start watchdog
    w = Thread(target=watchdog, daemon=True)
    w.start()

    # If we know the URL → enable self-ping
    url = os.environ.get("KEEPALIVE_URL")
    if url:
        p = Thread(target=self_ping, args=(url,), daemon=True)
        p.start()
