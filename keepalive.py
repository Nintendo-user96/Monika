from flask import Flask
from threading import Thread
import time, requests, os, traceback, random, datetime

app = Flask(__name__)

@app.route('/')
def home():
    return "Just Monika - alive"

def run_flask():
    while True:
        try:
            port = int(os.environ.get("PORT", 8080))
            app.run(
                host="0.0.0.0",
                port=port,
                debug=False,         # 🔒 no debug mode
                use_reloader=False   # 🔒 no auto-reloader
            )
        except BaseException as e:
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"[{now}] ⚠️ Flask crashed: {e}")
            traceback.print_exc()
            time.sleep(15)  # wait before restarting

def self_check(url, min_delay=30, max_delay=60):
    while True:
        try:
            r = requests.get(url, timeout=5)
            if r.status_code != 200:
                now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                print(f"[{now}] ⚠️ Self-check failed: HTTP {r.status_code}")
        except BaseException as e:
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"[{now}] ⚠️ Self-check error: {e}")
            traceback.print_exc()
        time.sleep(random.randint(min_delay, max_delay))

def heartbeat(interval=60):
    """Prints a heartbeat every `interval` seconds so you know it's alive."""
    while True:
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{now}] 💓 Keepalive still running")
        time.sleep(interval)

def keep_alive():
    try:
        Thread(target=run_flask, daemon=True, name="FlaskThread").start()
        url = os.environ.get("KEEPALIVE_URL")
        if url:
            Thread(target=self_check, args=(url,), daemon=True, name="SelfCheckThread").start()
        Thread(target=heartbeat, daemon=True, name="HeartbeatThread").start()

        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{now}] ✅ Keepalive started")
    except BaseException as e:
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{now}] ❌ Keepalive setup error: {e}")
        traceback.print_exc()
