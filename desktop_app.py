"""
Desktop launcher for Fabric Color Variation Detection.

    python desktop_app.py

Starts the Flask server in a background thread and opens it in a native,
maximised window (no browser bar). The camera is released when the window
closes. For a single-click .exe see README.md.
"""
import socket
import threading
import time

import webview

from app import app, engine

HOST = "127.0.0.1"
PORT = 5050


def run_flask():
    app.run(host=HOST, port=PORT, debug=False, threaded=True, use_reloader=False)


def wait_for_port(timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        try:
            with socket.create_connection((HOST, PORT), timeout=0.3):
                return True
        except OSError:
            time.sleep(0.1)
    return False


if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    wait_for_port()
    webview.create_window(
        "Fabric Color Variation Detection",
        f"http://{HOST}:{PORT}/",
        maximized=True,
        min_size=(1100, 700),
    )
    webview.start()
    engine.shutdown()