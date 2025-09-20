from flask import Flask
from threading import Thread
import time, requests, os, traceback, random, datetime

app = Flask(__name__)

@app.route('/')
def home():
    try:
        return "Just Monika - alive"
    except BaseException as e:
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{now}] ⚠️ Error inside route ignored: {e}")
        traceback.print_exc()
        return "Alive (error ignored)"

def run():
    """Run Flask server safely in retry loop."""
    def loop():
        while True:
            try:
                port = int(os.environ.get("PORT", 8080))
                app.run(
                    host="0.0.0.0",
                    port=port,
                    debug=False,
                    use_reloader=False
                )
            except BaseException as e:
                now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                print(f"[{now}] ⚠️ Flask crashed, retrying in 5s: {e}")
                traceback.print_exc()
                time.sleep(5)
    Thread(target=loop, daemon=True, name="FlaskThread").start()

def self_check(url, min_delay=30, max_delay=60):
    """Periodically ping server, only print errors."""
    def loop():
        while True:
            try:
                r = requests.get(url, timeout=5)
                if r.status_code != 200:  # only log failures
                    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    print(f"[{now}] ⚠️ Self-check failed: HTTP {r.status_code}")
            except BaseException as e:
                now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                print(f"[{now}] ⚠️ Self-check error ignored: {e}")
                traceback.print_exc()
            delay = random.randint(min_delay, max_delay)
            time.sleep(delay)
    Thread(target=loop, daemon=True, name="SelfCheckThread").start()

def keep_alive():
    """Start keepalive in background threads and return immediately."""
    try:
        run()
        url = os.environ.get("KEEPALIVE_URL")
        if url:
            self_check(url)
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{now}] ✅ Keepalive threads started")
    except BaseException as e:
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{now}] ⚠️ Keepalive setup error ignored: {e}")
        traceback.print_exc()
