from flask import Flask, render_template, Response, jsonify, request
import cv2
import numpy as np
import threading
import time
import json
import os
from datetime import datetime

app = Flask(__name__)

lock = threading.Lock()
is_running = False
color_status = "idle"
reference_color = None
color_history = []
current_brightness = 0
light_level = 0
preview_cam_idx = 0

current_test = {
    "fabric_name": "",
    "start_time": None,
    "readings": [],
    "duration": 30,
    "camera_index": 0,
    "last_report": None,
}

REPORTS_FILE = "reports.json"
BRIGHTNESS_THRESHOLDS = [60, 90, 110, 110, 120]

def load_reports():
    if os.path.exists(REPORTS_FILE):
        with open(REPORTS_FILE, "r") as f:
            return json.load(f)
    return []

def save_report(report):
    reports = load_reports()
    reports.insert(0, report)
    with open(REPORTS_FILE, "w") as f:
        json.dump(reports, f, indent=2)

def get_brightness(frame):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return float(gray.mean())

def get_light_level(brightness):
    level = 0
    for t in BRIGHTNESS_THRESHOLDS:
        if brightness >= t:
            level += 1
        else:
            break
    return level

def get_dominant_color(frame, region):
    x, y, w, h = region
    roi = frame[y:y+h, x:x+w]
    roi_resized = cv2.resize(roi, (50, 50))
    pixels = roi_resized.reshape(-1, 3).astype(np.float32)
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 10, 1.0)
    _, _, centers = cv2.kmeans(pixels, 1, None, criteria, 10, cv2.KMEANS_RANDOM_CENTERS)
    return centers[0].astype(int)

def color_difference(c1, c2):
    c1_lab = cv2.cvtColor(np.uint8([[c1]]), cv2.COLOR_BGR2Lab)[0][0].astype(float)
    c2_lab = cv2.cvtColor(np.uint8([[c2]]), cv2.COLOR_BGR2Lab)[0][0].astype(float)
    return float(np.sqrt(np.sum((c1_lab - c2_lab) ** 2)))

def _finalize_report():
    readings = current_test["readings"]
    if not readings:
        return None
    total = len(readings)
    same = sum(1 for r in readings if r["status"] == "same")
    not_same = total - same
    pct_good = round(same / total * 100, 1)
    pct_bad = round(not_same / total * 100, 1)
    avg_diff = round(sum(r["diff"] for r in readings) / total, 2)
    report = {
        "id": int(time.time()),
        "fabric_name": current_test["fabric_name"],
        "date": current_test["start_time"],
        "duration": current_test["duration"],
        "total_readings": total,
        "same": same,
        "not_same": not_same,
        "pct_good": pct_good,
        "pct_bad": pct_bad,
        "avg_diff": avg_diff,
        "readings": readings,
    }
    save_report(report)
    current_test["last_report"] = report
    return report

def preview_gen(cam_idx=0):
    global current_brightness, light_level
    cap = cv2.VideoCapture(cam_idx)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    while True:
        if is_running:
            time.sleep(0.1)
            continue
        ret, frame = cap.read()
        if not ret:
            time.sleep(0.5)
            continue
        b = get_brightness(frame)
        with lock:
            current_brightness = b
            light_level = get_light_level(b)
        _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
    cap.release()

def generate_frames():
    global is_running, color_status, reference_color, color_history
    global current_test, current_brightness, light_level
    cam_idx = current_test.get("camera_index", 0)
    cap = cv2.VideoCapture(cam_idx)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    frame_count = 0
    ref_set = False
    test_start = None

    while is_running:
        ret, frame = cap.read()
        if not ret:
            break
        h, w = frame.shape[:2]
        region = (w // 4, h // 3, w // 2, h // 3)
        rx, ry, rw, rh = region

        b = get_brightness(frame)
        with lock:
            current_brightness = b
            ll = get_light_level(b)
            light_level = ll

        # light কমে গেলে stop
        if ll < 5 and ref_set:
            with lock:
                is_running = False
                color_status = "idle"
                _finalize_report()
            break

        current_color = get_dominant_color(frame, region)

        with lock:
            if not ref_set and frame_count > 10:
                reference_color = current_color.copy()
                ref_set = True
                test_start = time.time()
                current_test["start_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                current_test["readings"] = []

            if ref_set and reference_color is not None:
                diff = color_difference(reference_color, current_color)
                status = "same" if diff <= 15 else "not_same"
                color_status = status
                reading = {"time": time.time(), "diff": round(diff, 2), "status": status}
                color_history.append(reading)
                if len(color_history) > 60:
                    color_history.pop(0)
                current_test["readings"].append(reading)

                elapsed = time.time() - test_start
                if elapsed >= current_test["duration"]:
                    is_running = False
                    _finalize_report()

        cv2.rectangle(frame, (rx, ry), (rx + rw, ry + rh), (0, 255, 100), 2)
        fabric = current_test.get("fabric_name", "")
        if fabric:
            cv2.putText(frame, f"Fabric: {fabric}", (rx, ry - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 220, 50), 2)
        frame_count += 1
        _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')

    cap.release()

@app.route('/')
def index():
    return render_template('check_color.html')

@app.route('/check_color')
def check_color():
    return render_template('check_color.html')

@app.route('/check_gsm')
def check_gsm():
    return render_template('check_gsm.html')

@app.route('/report/<int:report_id>')
def report_page(report_id):
    reports = load_reports()
    report = next((r for r in reports if r["id"] == report_id), None)
    if not report:
        return "Report not found", 404
    return render_template('report.html', report=report)

@app.route('/preview_feed')
def preview_feed():
    cam_idx = int(request.args.get('cam', 0))
    return Response(preview_gen(cam_idx), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/light_status')
def light_status():
    with lock:
        return jsonify({"brightness": round(current_brightness, 1), "level": light_level})

@app.route('/start', methods=['POST'])
def start():
    global is_running, reference_color, color_history, color_status, current_test
    data = request.get_json() or {}
    with lock:
        ll = light_level
    if ll < 5:
        return jsonify({"status": "light_low", "message": "Light not OK"})
    fabric_name = data.get("fabric_name", "Unknown").strip() or "Unknown"
    duration = int(data.get("duration", 30))
    cam_idx = int(data.get("camera_index", 0))
    with lock:
        if not is_running:
            is_running = True
            reference_color = None
            color_history = []
            color_status = "idle"
            current_test["fabric_name"] = fabric_name
            current_test["duration"] = duration
            current_test["camera_index"] = cam_idx
            current_test["start_time"] = None
            current_test["readings"] = []
            current_test["last_report"] = None
    return jsonify({"status": "started"})

@app.route('/stop', methods=['POST'])
def stop():
    global is_running, color_status
    report = None
    with lock:
        if is_running:
            is_running = False
            color_status = "idle"
            report = _finalize_report()
    return jsonify({"status": "stopped", "report": report})

@app.route('/status')
def status():
    with lock:
        history_copy = list(color_history[-30:])
        current_status = color_status
        is_on = is_running
        fabric = current_test["fabric_name"]
        readings = list(current_test["readings"])
        last_report = current_test.get("last_report")
        b = current_brightness
        ll = light_level
    total = len(readings)
    same = sum(1 for r in readings if r["status"] == "same")
    pct_good = round(same / total * 100, 1) if total else 0
    pct_bad = round(100 - pct_good, 1) if total else 0
    return jsonify({
        "running": is_on,
        "color_status": current_status,
        "fabric_name": fabric,
        "history": history_copy,
        "stats": {
            "total": total,
            "same": same,
            "not_same": total - same,
            "pct_good": pct_good,
            "pct_bad": pct_bad,
        },
        "last_report": last_report,
        "light": {"brightness": round(b, 1), "level": ll},
    })

@app.route('/reports')
def get_reports():
    return jsonify(load_reports())

@app.route('/reports/<int:report_id>', methods=['DELETE'])
def delete_report(report_id):
    reports = load_reports()
    reports = [r for r in reports if r["id"] != report_id]
    with open(REPORTS_FILE, "w") as f:
        json.dump(reports, f, indent=2)
    return jsonify({"status": "deleted"})

if __name__ == '__main__':
    app.run(debug=True, threaded=True)
