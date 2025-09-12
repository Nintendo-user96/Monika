from flask import Flask
from threading import Thread
import time, requests, logging, os

app = Flask(__name__)

# Track last heartbeat (just for logging now)
last_seen = time.time()

@app.route('/')
def home():
    global last_seen
    last_seen = time.time()
    return "Just Monika - alive"

def run():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

def self_ping(url, delay=60):
    """Ping our own server every `delay` seconds to stay awake."""
    global last_seen
    while True:
        try:
            requests.get(url, timeout=5)
            last_seen = time.time()
            logging.info(f"✅ Self-ping → {url}")
        except Exception as e:
            logging.warning(f"⚠️ Self-ping failed: {e}")
        time.sleep(delay)

def keep_alive():
    # Start Flask server
    t = Thread(target=run, daemon=True)
    t.start()

    # If we know the URL → enable self-ping
    url = os.environ.get("KEEPALIVE_URL")
    if url:
        p = Thread(target=self_ping, args=(url,), daemon=True)
        p.start()
