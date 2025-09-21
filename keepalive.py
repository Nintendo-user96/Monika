from flask import Flask
from threading import Thread
import time, requests, os, traceback, random, datetime, sys, threading

app = Flask(__name__)

@app.route('/')
def home():
    return "Just Monika - alive"

# =========================================================
# 🛡 Absolute global error ignoring
# =========================================================
def ignore_global_exceptions(exc_type, exc_value, exc_traceback):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] ⚠️ Global exception ignored: {exc_value}")
    traceback.print_exception(exc_type, exc_value, exc_traceback)

sys.excepthook = ignore_global_exceptions

def ignore_thread_exceptions(args):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] ⚠️ Thread exception ignored: {args.exc_value}")
    traceback.print_exception(args.exc_type, args.exc_value, args.exc_traceback)

threading.excepthook = ignore_thread_exceptions

# =========================================================
# Worker threads (each restarts on error)
# =========================================================
def run_flask():
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
            print(f"[{now}] ⚠️ Flask crashed but ignored: {e}")
            traceback.print_exc()
            time.sleep(15)

def self_check(url, min_delay=30, max_delay=60):
    while True:
        try:
            r = requests.get(url, timeout=5)
            if r.status_code != 200:
                now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                print(f"[{now}] ⚠️ Self-check failed: HTTP {r.status_code}")
        except BaseException as e:
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"[{now}] ⚠️ Self-check error ignored: {e}")
            traceback.print_exc()
        time.sleep(random.randint(min_delay, max_delay))

def heartbeat(interval=60):
    while True:
        try:
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"[{now}] 💓 Keepalive still running")
        except BaseException as e:
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"[{now}] ⚠️ Heartbeat error ignored: {e}")
            traceback.print_exc()
        time.sleep(interval)

# =========================================================
# Main entry with restart protection
# =========================================================
def keep_alive():
    while True:
        try:
            Thread(target=run_flask, daemon=True, name="FlaskThread").start()
            url = os.environ.get("KEEPALIVE_URL")
            if url:
                Thread(target=self_check, args=(url,), daemon=True, name="SelfCheckThread").start()
            Thread(target=heartbeat, daemon=True, name="HeartbeatThread").start()

            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"[{now}] ✅ Keepalive started")
            break  # success → exit loop
        except BaseException as e:
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"[{now}] ❌ Fatal keepalive setup error ignored: {e}")
            traceback.print_exc()
            time.sleep(10)
