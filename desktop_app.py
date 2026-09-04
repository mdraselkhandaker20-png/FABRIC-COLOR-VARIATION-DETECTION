"""
Desktop launcher for Fabric Color Variation Detection.

Run this file instead of app.py to get a native desktop window
(no browser tab, no address bar) that fills the whole screen —
so the live camera feed and the final report are always fully visible.

    python desktop_app.py

To turn this into a single-click .exe (Windows) later, see the
"Build a standalone .exe" section in README.md.
"""
import threading
import time
import webview
from app import app

HOST = "127.0.0.1"
PORT = 5050


def run_flask():
    app.run(host=HOST, port=PORT, debug=False, threaded=True, use_reloader=False)


if __name__ == "__main__":
    t = threading.Thread(target=run_flask, daemon=True)
    t.start()
    time.sleep(1.0)  # give Flask a moment to bind the port before the window loads it

    window = webview.create_window(
        "Fabric Color Variation Detection",
        f"http://{HOST}:{PORT}/",
        maximized=True,
        min_size=(1100, 700),
    )
    webview.start()