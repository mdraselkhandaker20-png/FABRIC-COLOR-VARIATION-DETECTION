"""
Fabric Color Variation Detection — Flask web layer (v2).

    python app.py            -> http://127.0.0.1:5000  (browser, for debugging)
    python desktop_app.py    -> native desktop window   (recommended)

Camera handling, colour maths and the test logic live in engine.py and
colorimetry.py. This file only stores reports/setup profiles and serves pages.
"""
import csv
import io
import json
import os
import sys
import threading
import time
from datetime import datetime

import cv2
import numpy as np
from flask import Flask, Response, jsonify, render_template, request, send_file

from engine import CONFIG, Engine


# ── paths: work both as a script and as a PyInstaller .exe ──
def _resource_dir():
    return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))


def _data_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


RES_DIR, DATA_DIR = _resource_dir(), _data_dir()
REPORTS_FILE = os.path.join(DATA_DIR, "reports.json")
SETUPS_FILE = os.path.join(DATA_DIR, "setups.json")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")

app = Flask(__name__,
            template_folder=os.path.join(RES_DIR, "templates"),
            static_folder=os.path.join(RES_DIR, "static"))

_file_lock = threading.Lock()


# ── JSON storage ──
def _load(path, default):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return default
    return default


def _save(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def load_reports():
    return _load(REPORTS_FILE, [])


def save_report(report):
    with _file_lock:
        reports = load_reports()
        reports.insert(0, report)
        _save(REPORTS_FILE, reports)


def load_setups():
    return _load(SETUPS_FILE, [])


def load_settings():
    return _load(SETTINGS_FILE, {})


def save_settings(s):
    with _file_lock:
        _save(SETTINGS_FILE, s)


def active_setup():
    sid = load_settings().get("active_setup_id")
    if sid is None:
        return None
    return next((s for s in load_setups() if s["id"] == sid), None)


def report_summary(r):
    return {k: v for k, v in r.items() if k != "readings"}


# ── engine ──
engine = Engine(on_report=save_report, get_active_setup=active_setup)
engine.start()


def _blank_jpeg(text):
    img = np.full((480, 640, 3), 18, np.uint8)
    for i, line in enumerate(text.split("\n")):
        cv2.putText(img, line, (40, 220 + i * 34), cv2.FONT_HERSHEY_SIMPLEX, 0.75,
                    (150, 200, 160), 2, cv2.LINE_AA)
    return cv2.imencode(".jpg", img)[1].tobytes()


NO_CAMERA_JPEG = _blank_jpeg("No camera connected.\nPlug in the USB camera -\nit is picked up automatically.")


# ── pages ──
@app.route("/")
@app.route("/check_color")
def check_color():
    return render_template("check_color.html", config=CONFIG)


@app.route("/setup")
def setup_page():
    return render_template("setup.html", config=CONFIG)


@app.route("/check_gsm")
def check_gsm():
    return render_template("check_gsm.html")


@app.route("/report/<int:report_id>")
def report_page(report_id):
    report = next((r for r in load_reports() if r["id"] == report_id), None)
    if not report:
        return "Report not found", 404
    return render_template("report.html", report=report, config=CONFIG)


# ── live data ──
@app.route("/stream")
def stream():
    view = request.args.get("view", "check")

    def gen():
        last = -1
        while True:
            jpg, fid = engine.stream_frame(view)
            if jpg is None:
                jpg = NO_CAMERA_JPEG
                time.sleep(0.5)
            elif fid == last:
                time.sleep(0.02)
                continue
            last = fid
            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpg + b"\r\n"
            time.sleep(0.04)

    return Response(gen(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/status")
def status():
    s = engine.snapshot()
    setup = active_setup()
    s["active_setup"] = None if not setup else {
        "id": setup["id"], "name": setup["name"],
        "camera_distance_cm": setup.get("camera_distance_cm"),
        "light_distance_cm": setup.get("light_distance_cm"),
        "light_angle_deg": setup.get("light_angle_deg"),
        "light_source": setup.get("light_source"),
        "setup_ok": setup.get("setup_ok"),
        "noise_mean_de00": (setup.get("baseline") or {}).get("noise_mean_de00"),
        "suggested_threshold_de00": (setup.get("baseline") or {}).get("suggested_threshold_de00"),
    }
    return jsonify(s)


@app.route("/cameras/rescan", methods=["POST"])
def cameras_rescan():
    engine.request_rescan()
    return jsonify({"ok": True})


@app.route("/cameras/select", methods=["POST"])
def cameras_select():
    name = (request.get_json(silent=True) or {}).get("name", "auto")
    ok, msg = engine.select_camera(name)
    return jsonify({"ok": ok, "message": msg})


@app.route("/camera/relock", methods=["POST"])
def camera_relock():
    ok, msg = engine.request_relock()
    return jsonify({"ok": ok, "message": msg})


# ── colour test ──
@app.route("/start", methods=["POST"])
def start():
    d = request.get_json(silent=True) or {}
    fabric = (d.get("fabric_name") or "").strip()
    if not fabric:
        return jsonify({"ok": False, "message": "Enter a fabric name first."})
    try:
        duration = max(5, min(600, int(d.get("duration", 30))))
        threshold = float(d.get("threshold") or CONFIG["default_threshold_de00"])
    except (TypeError, ValueError):
        return jsonify({"ok": False, "message": "Duration and threshold must be numbers."})
    ok, msg = engine.start_test(fabric, (d.get("light_source") or "").strip(), duration, threshold,
                                (d.get("operator") or "").strip())
    return jsonify({"ok": ok, "message": msg})


@app.route("/stop", methods=["POST"])
def stop():
    report = engine.stop_test()
    return jsonify({"ok": True, "report": report_summary(report) if report else None})


# ── setup / calibration ──
@app.route("/baseline/start", methods=["POST"])
def baseline_start():
    d = request.get_json(silent=True) or {}
    try:
        dur = max(3, min(60, float(d.get("duration", 10))))
    except (TypeError, ValueError):
        dur = 10
    ok, msg = engine.start_baseline(dur)
    return jsonify({"ok": ok, "message": msg})


def _num(v):
    try:
        return None if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return None


@app.route("/setups", methods=["GET"])
def setups_list():
    return jsonify({"setups": load_setups(), "active_setup_id": load_settings().get("active_setup_id")})


@app.route("/setups", methods=["POST"])
def setups_save():
    d = request.get_json(silent=True) or {}
    baseline = engine.snapshot().get("baseline_result")
    if not baseline:
        return jsonify({"ok": False, "message": "Measure the baseline first."})
    name = (d.get("name") or "").strip() or f"Setup {datetime.now():%Y-%m-%d %H:%M}"
    setup = {
        "id": int(time.time() * 1000),
        "name": name,
        "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "camera_distance_cm": _num(d.get("camera_distance_cm")),
        "light_distance_cm": _num(d.get("light_distance_cm")),
        "light_angle_deg": _num(d.get("light_angle_deg")),
        "light_source": (d.get("light_source") or "").strip(),
        "reference_fabric": (d.get("reference_fabric") or "").strip(),
        "notes": (d.get("notes") or "").strip(),
        "setup_ok": baseline["setup_ok"],
        "baseline": baseline,
    }
    with _file_lock:
        setups = load_setups()
        setups.insert(0, setup)
        _save(SETUPS_FILE, setups)
    if d.get("activate", True):
        s = load_settings()
        s["active_setup_id"] = setup["id"]
        save_settings(s)
    return jsonify({"ok": True, "setup": setup})


@app.route("/setups/<int:sid>/activate", methods=["POST"])
def setups_activate(sid):
    if not any(s["id"] == sid for s in load_setups()):
        return jsonify({"ok": False, "message": "Setup not found."}), 404
    s = load_settings()
    s["active_setup_id"] = sid
    save_settings(s)
    return jsonify({"ok": True})


@app.route("/setups/<int:sid>", methods=["DELETE"])
def setups_delete(sid):
    with _file_lock:
        setups = [s for s in load_setups() if s["id"] != sid]
        _save(SETUPS_FILE, setups)
    s = load_settings()
    if s.get("active_setup_id") == sid:
        s["active_setup_id"] = None
        save_settings(s)
    return jsonify({"ok": True})


SETUP_CSV_COLS = [
    ("Name", lambda s, b: s["name"]), ("Created", lambda s, b: s["created"]),
    ("Camera", lambda s, b: b.get("camera_name")), ("Mode", lambda s, b: b.get("mode")),
    ("Camera-fabric distance (cm)", lambda s, b: s.get("camera_distance_cm")),
    ("Light-fabric distance (cm)", lambda s, b: s.get("light_distance_cm")),
    ("Light angle (deg)", lambda s, b: s.get("light_angle_deg")),
    ("Light source", lambda s, b: s.get("light_source")),
    ("Reference fabric", lambda s, b: s.get("reference_fabric")),
    ("Exposure locked", lambda s, b: (b.get("camera_settings") or {}).get("locked")),
    ("Mean L*", lambda s, b: b.get("mean_L")),
    ("Black px (%)", lambda s, b: b.get("dark_clip_pct")),
    ("Clipped px (%)", lambda s, b: b.get("bright_clip_pct")),
    ("Noise mean dE00", lambda s, b: b.get("noise_mean_de00")),
    ("Noise SD dE00", lambda s, b: b.get("noise_std_de00")),
    ("Noise P95 dE00", lambda s, b: b.get("noise_p95_de00")),
    ("Noise max dE00", lambda s, b: b.get("noise_max_de00")),
    ("Uniformity max dE00", lambda s, b: b.get("uniformity_max_de00")),
    ("Uniformity mean dE00", lambda s, b: b.get("uniformity_mean_de00")),
    ("Suggested threshold dE00", lambda s, b: b.get("suggested_threshold_de00")),
    ("Setup OK", lambda s, b: s.get("setup_ok")),
    ("Frames", lambda s, b: b.get("frames")),
    ("Notes", lambda s, b: s.get("notes")),
]


@app.route("/setups/export.csv")
def setups_export():
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([c[0] for c in SETUP_CSV_COLS])
    for s in load_setups():
        b = s.get("baseline") or {}
        w.writerow([c[1](s, b) for c in SETUP_CSV_COLS])
    mem = io.BytesIO(buf.getvalue().encode("utf-8-sig"))
    return send_file(mem, mimetype="text/csv", as_attachment=True, download_name="setup_trials.csv")


# ── reports ──
@app.route("/reports")
def get_reports():
    return jsonify([report_summary(r) for r in load_reports()])


@app.route("/reports/<int:report_id>", methods=["DELETE"])
def delete_report(report_id):
    with _file_lock:
        reports = [r for r in load_reports() if r["id"] != report_id]
        _save(REPORTS_FILE, reports)
    return jsonify({"status": "deleted"})


@app.route("/report/<int:report_id>/export.csv")
def export_report_csv(report_id):
    r = next((x for x in load_reports() if x["id"] == report_id), None)
    if not r:
        return "Report not found", 404
    setup = r.get("setup") or {}
    base = setup.get("baseline") or {}
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Fabric Color Variation Detection - Test Report"])
    rows = [
        ("Report version", r.get("version", 1)),
        ("Mode", (r.get("mode") or "legacy").upper()),
        ("Fabric name", r.get("fabric_name")),
        ("Light source", r.get("light_source", "")),
        ("Operator", r.get("operator", "")),
        ("Date", r.get("date")),
        ("Camera", r.get("camera_name", "")),
        ("Exposure/WB locked", (r.get("camera_settings") or {}).get("locked", "")),
        ("Setup profile", setup.get("name", "")),
        ("Camera-fabric distance (cm)", setup.get("camera_distance_cm", "")),
        ("Light-fabric distance (cm)", setup.get("light_distance_cm", "")),
        ("Light angle (deg)", setup.get("light_angle_deg", "")),
        ("Setup noise mean dE00", base.get("noise_mean_de00", "")),
        ("Setup uniformity max dE00", base.get("uniformity_max_de00", "")),
        ("Planned duration (s)", r.get("duration")),
        ("Actual duration (s)", r.get("actual_duration", "")),
        ("Stop reason", r.get("stop_reason", "")),
        ("Delta E method", r.get("delta_e_method", "CIE76 (legacy scaled Lab)")),
        ("Delta E threshold", r.get("delta_e_threshold", 15)),
        ("Reference L*a*b*", " ".join(str(v) for v in r.get("reference_lab", []))),
        ("Total readings", r.get("total_readings")),
        ("Same (%)", r.get("pct_good")),
        ("Not same (%)", r.get("pct_bad")),
        ("Mean dE (primary)", r.get("avg_diff")),
        ("SD dE (primary)", r.get("std_diff", "")),
        ("P95 dE (primary)", r.get("p95_diff", "")),
        ("Min dE (primary)", r.get("min_diff", "")),
        ("Max dE (primary)", r.get("max_diff", "")),
        ("Mean dE76", r.get("de76_avg", "")),
        ("Mean dE CMC(2:1)", r.get("decmc_avg", "")),
    ]
    for row in rows:
        w.writerow(row)
    w.writerow([])
    if r.get("version", 1) >= 2:
        w.writerow(["#", "t (s)", "L*", "a*", "b*", "dE00", "dE76", "dE CMC(2:1)", "Status"])
        for i, x in enumerate(r.get("readings", []), 1):
            w.writerow([i, x["t"], x["L"], x["a"], x["b"], x["de00"], x["de76"], x["decmc"], x["status"]])
    else:
        w.writerow(["#", "Timestamp", "Delta E (legacy)", "Status"])
        for i, x in enumerate(r.get("readings", []), 1):
            w.writerow([i, x.get("time"), x.get("diff"), x.get("status")])
    mem = io.BytesIO(buf.getvalue().encode("utf-8-sig"))
    fname = f"report_{r.get('fabric_name', 'fabric')}_{report_id}.csv".replace(" ", "_")
    return send_file(mem, mimetype="text/csv", as_attachment=True, download_name=fname)


if __name__ == "__main__":
    # use_reloader=False: the reloader would start a second engine and fight over the camera
    app.run(debug=True, threaded=True, use_reloader=False)