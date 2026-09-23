"""
Camera + measurement engine.

One background thread owns the camera. It reads every frame, analyses the
inspection region, runs the colour test / setup baseline, and keeps the latest
frame for the video streams. Web requests never touch the camera directly —
that is what removes the "two VideoCapture objects on one camera" conflicts
of v1.

Camera modes
------------
MEASUREMENT : a camera whose name matches CONFIG["measurement_camera_keywords"]
              (Logitech C270 by default). Exposure + white balance are locked.
              Only these reports count as measurements.
DEMO        : any other camera (e.g. the laptop's built-in one). Everything
              works, but reports are stamped DEMO and are not measurements.
"""
import math
import os
import platform
import threading
import time
from collections import deque
from datetime import datetime

import cv2
import numpy as np

from colorimetry import bgr_to_lab, lab_to_hex, delta_e_2000, delta_e_76, delta_e_cmc

IS_WINDOWS = platform.system() == "Windows"
IS_LINUX = platform.system() == "Linux"
FAKE_CAMERAS = os.environ.get("FCV_FAKE_CAMERA") == "1"   # developer simulator
FAKE_DEFECT = os.environ.get("FCV_FAKE_DEFECT") == "1"    # simulator: periodic shade defect

CONFIG = {
    # Any camera whose name contains one of these (case-insensitive) is the
    # measurement camera. Add your camera's name here if you change hardware.
    "measurement_camera_keywords": ["c270", "logitech"],
    "frame_width": 640,
    "frame_height": 480,
    # Size of the green measuring box, as a fraction of the camera image
    # (0.8 = box covers 80 % of the width and 80 % of the height, centred).
    "roi_fraction": 0.8,

    # Reference colour = median of these frames, after skipping warm-up frames
    "reference_skip_frames": 10,
    "reference_frames": 15,

    # Pass/fail threshold (CIEDE2000). The Setup page measures the system's own
    # noise and suggests a threshold; the test never uses less than this floor.
    "default_threshold_de00": 2.0,
    "min_threshold_de00": 1.0,

    # Readiness checks ("light dots")
    "dark_clip_level": 4,        # pixel counts as black if all channels <= this
    "bright_clip_level": 250,    # pixel counts as clipped if any channel >= this
    "max_dark_clip_pct": 1.0,
    "max_bright_clip_pct": 1.0,
    "uniformity_max_de00": 2.0,  # max ΔE00 between inspection-grid cells
    "stability_max_de00": 1.0,   # 95th pct frame-to-frame ΔE00 over the window
    "stability_window": 30,

    "light_lost_grace_s": 1.5,
    "camera_lost_grace_s": 2.0,
    "exposure_settle_s": 2.0,    # auto-exposure runs this long before locking
    "camera_poll_s": 3.0,        # how often to look for plugged/unplugged cameras

    "pass_pct": 80,
    "excellent_pct": 90,
    "default_light_source": "Bilateral LED panel lighting (5500K daylight-balanced)",
}

CHECK_MESSAGES = {
    "camera": "NO CAMERA",
    "settling": "LOCKING EXPOSURE",
    "dark": "TOO DARK",
    "bright": "OVEREXPOSED",
    "stable": "UNSTABLE",
    "even": "UNEVEN LIGHT",
}


# ─────────────────────────────── camera discovery ───────────────────────────────
def _windows_camera_names():
    """DirectShow device names, in the same order as OpenCV CAP_DSHOW indices."""
    try:
        import comtypes
        try:
            comtypes.CoInitialize()
        except Exception:
            pass
        from pygrabber.dshow_graph import FilterGraph
        return list(FilterGraph().get_input_devices())
    except Exception:
        return None


def _linux_camera_names():
    base = "/sys/class/video4linux"
    if not os.path.isdir(base):
        return None
    cams = []
    for dev in sorted(os.listdir(base), key=lambda d: int(''.join(c for c in d if c.isdigit()) or 0)):
        idx = int(''.join(c for c in dev if c.isdigit()) or 0)
        try:
            with open(os.path.join(base, dev, "name")) as f:
                name = f.read().strip()
            with open(os.path.join(base, dev, "index")) as f:
                if f.read().strip() != "0":   # skip metadata nodes
                    continue
        except OSError:
            continue
        cams.append((idx, name))
    return cams


def classify(name):
    n = (name or "").lower()
    return "measurement" if any(k in n for k in CONFIG["measurement_camera_keywords"]) else "demo"


def list_cameras(skip_index=None):
    """Return [{index, name, kind}]. Never opens the camera currently in use."""
    if FAKE_CAMERAS:
        return [{"index": 0, "name": "Integrated Camera (simulated)", "kind": "demo"},
                {"index": 1, "name": "Logitech HD Webcam C270 (simulated)", "kind": "measurement"}]
    if IS_WINDOWS:
        names = _windows_camera_names()
        if names is not None:
            return [{"index": i, "name": n, "kind": classify(n)} for i, n in enumerate(names)]
    if IS_LINUX:
        found = _linux_camera_names()
        if found is not None:
            return [{"index": i, "name": n, "kind": classify(n)} for i, n in found]
    # Fallback (e.g. macOS / pygrabber missing): probe indices; names unknown.
    cams = []
    for i in range(0, 4):
        if i == skip_index:
            cams.append({"index": i, "name": f"Camera {i}", "kind": "demo" if i == 0 else "measurement"})
            continue
        cap = cv2.VideoCapture(i)
        ok = cap.isOpened()
        cap.release()
        if ok:
            # Without names, assume index 0 = built-in, anything else = external USB
            cams.append({"index": i, "name": f"Camera {i}" + ("" if i == 0 else " (external USB, assumed)"),
                         "kind": "demo" if i == 0 else "measurement"})
    return cams


# ─────────────────────────────── simulator (dev only) ───────────────────────────────
class FakeCapture:
    """Synthetic fabric images so the whole app can be exercised without hardware."""
    def __init__(self, kind):
        self.kind = kind
        self.t0 = time.time()
        self.rng = np.random.default_rng()
        w, h = CONFIG["frame_width"], CONFIG["frame_height"]
        yy, xx = np.mgrid[0:h, 0:w]
        r = np.sqrt(((xx - w / 2) / w) ** 2 + ((yy - h / 2) / h) ** 2)
        strength = 0.12 if kind == "measurement" else 0.5
        self.vignette = (1 - strength * r)[..., None]
        if kind == "demo":
            self.vignette = self.vignette * (0.85 + 0.3 * (xx / w))[..., None]

    def isOpened(self): return True
    def set(self, *a): return True
    def get(self, *a): return 0.0
    def release(self): pass

    def read(self):
        time.sleep(1 / 30)
        t = time.time() - self.t0
        base = np.array([70, 140, 60], dtype=np.float64)      # green fabric (BGR)
        if FAKE_DEFECT and self.kind == "measurement" and 8 < (t % 20) < 11:
            base = base + np.array([0, -12, 18])                # simulated shade defect
        # frame-level jitter (sensor/illumination flicker) + per-pixel noise
        base = base + self.rng.normal(0, 0.35 if self.kind == "measurement" else 1.2, 3)
        noise_sd = 1.5 if self.kind == "measurement" else 4.0
        img = base * self.vignette + self.rng.normal(0, noise_sd, (CONFIG["frame_height"], CONFIG["frame_width"], 3))
        return True, np.clip(img, 0, 255).astype(np.uint8)


# ─────────────────────────────── frame analysis ───────────────────────────────
def roi_rect(w, h):
    f = min(max(float(CONFIG["roi_fraction"]), 0.2), 0.95)
    rw, rh = int(w * f), int(h * f)
    return ((w - rw) // 2, (h - rh) // 2, rw, rh)


def analyze(frame):
    h, w = frame.shape[:2]
    x, y, rw, rh = roi_rect(w, h)
    roi = frame[y:y + rh, x:x + rw]
    dark_pct = float((roi.max(axis=2) <= CONFIG["dark_clip_level"]).mean() * 100)
    bright_pct = float((roi.max(axis=2) >= CONFIG["bright_clip_level"]).mean() * 100)
    small = cv2.resize(roi, (60, 60), interpolation=cv2.INTER_AREA)
    lab = bgr_to_lab(small)
    color = np.median(lab.reshape(-1, 3), axis=0)
    grid = lab.reshape(3, 20, 3, 20, 3).mean(axis=(1, 3))          # 3x3 cells
    grid_de = delta_e_2000(grid[1, 1], grid.reshape(-1, 3))
    return {
        "lab": color,
        "grid": grid,
        "grid_de": grid_de,
        "uniformity": float(grid_de.max()),
        "dark_pct": dark_pct,
        "bright_pct": bright_pct,
        "mean_L": float(lab[..., 0].mean()),
        "rect": (x, y, rw, rh),
    }


def _r(v, n=2):
    return None if v is None else round(float(v), n)


# ─────────────────────────────── engine ───────────────────────────────
class Engine:
    def __init__(self, on_report=None, get_active_setup=None):
        self.lock = threading.RLock()
        self.on_report = on_report                  # callback(report) -> saves it
        self.get_active_setup = get_active_setup    # callback() -> setup dict | None
        self.alive = False

        self.cameras = []
        self.manual_choice = None       # camera name chosen by user, None = auto
        self.pending_open = None        # camera dict to open (set by any thread)
        self.rescan_requested = True
        self.relock_requested = False
        self.last_poll = 0.0

        self.cap = None
        self.cam = None
        self.cam_settings = {}
        self.settle_until = 0.0
        self.frame = None
        self.frame_id = 0
        self.last_frame_t = 0.0
        self.fail_since = None
        self.analysis = None
        self.window = deque(maxlen=CONFIG["stability_window"])
        self.stability = None
        self.checks = []

        self.test = None
        self.last_report = None
        self.baseline = None
        self.baseline_result = None
        self.message = ""
        self.message_t = 0.0

    # ── lifecycle ──
    def start(self):
        if self.alive:
            return
        self.alive = True
        threading.Thread(target=self._loop, daemon=True, name="camera-engine").start()

    def shutdown(self):
        self.alive = False
        time.sleep(0.2)
        with self.lock:
            self._close()

    # ── public API (called from Flask threads) ──
    def request_rescan(self):
        self.rescan_requested = True

    def select_camera(self, name):
        with self.lock:
            if self.test:
                return False, "Stop the running test before switching camera."
            self.manual_choice = None if name in (None, "", "auto") else name
            self.rescan_requested = True
            return True, ""

    def request_relock(self):
        with self.lock:
            if self.test or self.baseline:
                return False, "Wait for the running test/baseline to finish."
            if not self.cap:
                return False, "No camera connected."
            self.relock_requested = True
            return True, ""

    def mode(self):
        return self.cam["kind"] if self.cam else None

    def is_settling(self):
        return time.time() < self.settle_until

    def start_test(self, fabric_name, light_source, duration, threshold, operator=""):
        with self.lock:
            if self.test:
                return False, "A test is already running."
            if self.baseline:
                return False, "Setup baseline is running — wait for it to finish."
            ready, reason = self.ready_for_test()
            if not ready:
                return False, reason
            thr_floor = CONFIG["min_threshold_de00"]
            self.test = {
                "fabric_name": fabric_name,
                "light_source": light_source,
                "operator": operator,
                "duration": duration,
                "threshold": max(thr_floor, float(threshold)),
                "mode": self.cam["kind"],
                "camera_name": self.cam["name"],
                "camera_settings": dict(self.cam_settings),
                "setup": self.get_active_setup() if self.get_active_setup else None,
                "state": "reference",
                "frames_seen": 0,
                "ref_labs": [],
                "ref": None,
                "readings": [],
                "t0": None,
                "start_time": None,
                "bad_since": None,
            }
            self.last_report = None
            return True, ""

    def stop_test(self):
        with self.lock:
            if not self.test:
                return None
            if self.test["state"] == "measuring" and self.test["readings"]:
                return self._finalize("stopped_by_user")
            self.test = None
            return None

    def start_baseline(self, duration=10):
        with self.lock:
            if self.test:
                return False, "Stop the running test first."
            if self.baseline:
                return False, "Baseline already running."
            if not self.cap or self.analysis is None:
                return False, "No camera connected."
            if self.is_settling():
                return False, "Camera is still locking exposure — wait a moment."
            self.baseline = {"t0": time.time(), "duration": float(duration), "labs": [], "grids": [],
                             "dark": [], "bright": [], "L": []}
            self.baseline_result = None
            return True, ""

    # ── readiness ──
    def _compute_checks(self, now):
        a = self.analysis
        cam_ok = self.cap is not None and a is not None and (now - self.last_frame_t) < 1.0
        settling = self.is_settling()
        checks = [{
            "key": "camera", "label": "Camera",
            "ok": cam_ok and not settling,
            "value": ("locking exposure…" if settling else (self.cam["name"] if cam_ok else "not connected")),
            "msg": CHECK_MESSAGES["settling" if (cam_ok and settling) else "camera"],
        }]
        if a is None:
            for k, lbl in (("dark", "Not too dark"), ("bright", "Not overexposed"),
                           ("stable", "Stable"), ("even", "Even light")):
                checks.append({"key": k, "label": lbl, "ok": False, "value": "—", "msg": CHECK_MESSAGES[k]})
            return checks
        checks.append({"key": "dark", "label": "Not too dark",
                       "ok": a["dark_pct"] <= CONFIG["max_dark_clip_pct"],
                       "value": f"{a['dark_pct']:.1f}% black px", "msg": CHECK_MESSAGES["dark"]})
        checks.append({"key": "bright", "label": "Not overexposed",
                       "ok": a["bright_pct"] <= CONFIG["max_bright_clip_pct"],
                       "value": f"{a['bright_pct']:.1f}% clipped px", "msg": CHECK_MESSAGES["bright"]})
        st = self.stability
        checks.append({"key": "stable", "label": "Stable",
                       "ok": st is not None and st <= CONFIG["stability_max_de00"],
                       "value": "measuring…" if st is None else f"ΔE00 {st:.2f}", "msg": CHECK_MESSAGES["stable"]})
        checks.append({"key": "even", "label": "Even light",
                       "ok": a["uniformity"] <= CONFIG["uniformity_max_de00"],
                       "value": f"ΔE00 {a['uniformity']:.2f}", "msg": CHECK_MESSAGES["even"]})
        return checks

    def ready_for_test(self):
        """Measurement mode needs all 5 checks. Demo mode needs camera + exposure."""
        checks = self.checks or []
        if not checks or not self.cam:
            return False, "No camera connected."
        needed = checks if self.cam["kind"] == "measurement" else checks[:3]
        for c in needed:
            if not c["ok"]:
                return False, f"{c['label']}: {c['value']}"
        return True, ""

    # ── main loop ──
    def _loop(self):
        while self.alive:
            now = time.time()
            polling = FAKE_CAMERAS or IS_WINDOWS or IS_LINUX
            if self.rescan_requested or (polling and now - self.last_poll > CONFIG["camera_poll_s"]):
                self.rescan_requested = False
                self.last_poll = now
                self._refresh_and_select()

            if self.pending_open is not None:
                with self.lock:
                    target, self.pending_open = self.pending_open, None
                    self._open(target)

            cap = self.cap
            if cap is None:
                time.sleep(0.2)
                continue

            ok, frame = cap.read()
            now = time.time()
            if not ok or frame is None:
                with self.lock:
                    self.fail_since = self.fail_since or now
                    if now - self.fail_since > CONFIG["camera_lost_grace_s"]:
                        if self.test and self.test["state"] == "measuring" and self.test["readings"]:
                            self._finalize("camera_lost")
                        else:
                            self.test = None
                        self.baseline = None
                        self._flash(f"Camera '{self.cam['name'] if self.cam else ''}' stopped sending frames.")
                        self._close()
                        self.rescan_requested = True
                time.sleep(0.05)
                continue
            self.fail_since = None

            if self.relock_requested:
                self.relock_requested = False
                self._begin_settle()
            if self.settle_until and now >= self.settle_until:
                self.settle_until = 0.0
                with self.lock:
                    self._lock_settings()

            try:
                a = analyze(frame)
            except Exception:
                continue

            with self.lock:
                self.frame = frame
                self.frame_id += 1
                self.last_frame_t = now
                self.analysis = a
                self.window.append(a["lab"])
                if len(self.window) >= 10:
                    labs = np.array(self.window)
                    de = delta_e_2000(labs.mean(axis=0), labs)
                    self.stability = float(np.percentile(de, 95))
                else:
                    self.stability = None
                self.checks = self._compute_checks(now)
                self._step_test(a, now)
                self._step_baseline(a, now)

    # ── camera management ──
    def _refresh_and_select(self):
        try:
            cams = list_cameras(skip_index=self.cam["index"] if self.cam else None)
        except Exception:
            cams = self.cameras
        with self.lock:
            self.cameras = cams
            if self.test or self.baseline:
                return
            target = None
            if self.manual_choice:
                target = next((c for c in cams if c["name"] == self.manual_choice), None)
            if target is None:
                target = next((c for c in cams if c["kind"] == "measurement"), None)
            if target is None and cams:
                target = cams[0]
            cur = self.cam
            if target is None:
                if cur is not None:
                    self._flash(f"'{cur['name']}' disconnected.")
                    self._close()
                return
            if cur is None or cur["name"] != target["name"]:
                if cur is not None:
                    self._flash(f"Switched to {target['name']} ({target['kind'].upper()} mode).")
                self.pending_open = target
            elif cur["index"] != target["index"]:
                cur["index"] = target["index"]   # device order changed; keep open handle

    def _open(self, cam):
        self._close()
        if FAKE_CAMERAS:
            cap = FakeCapture(cam["kind"])
        else:
            backend = cv2.CAP_DSHOW if IS_WINDOWS else (cv2.CAP_V4L2 if IS_LINUX else cv2.CAP_ANY)
            cap = cv2.VideoCapture(cam["index"], backend)
            if not cap.isOpened():
                cap.release()
                cap = cv2.VideoCapture(cam["index"])
        if not cap.isOpened():
            self._flash(f"Could not open '{cam['name']}'.")
            return
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, CONFIG["frame_width"])
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CONFIG["frame_height"])
        cap.set(cv2.CAP_PROP_FPS, 30)
        self.cap = cap
        self.cam = dict(cam)
        self.window.clear()
        self.stability = None
        self.analysis = None
        self.last_frame_t = time.time()
        if cam["kind"] == "measurement":
            self._begin_settle()
        else:
            self.cam_settings = {"locked": False, "note": "Automatic exposure/white balance (demo camera)"}

    def _begin_settle(self):
        """Let auto exposure / WB adapt to the current light, then lock them."""
        cap = self.cap
        if cap is None:
            return
        auto = 0.75 if IS_WINDOWS else 3
        for prop, val in ((cv2.CAP_PROP_AUTO_EXPOSURE, auto), (cv2.CAP_PROP_AUTO_WB, 1)):
            try:
                cap.set(prop, val)
            except Exception:
                pass
        self.cam_settings = {"locked": False, "note": "settling"}
        self.window.clear()
        self.stability = None
        self.settle_until = time.time() + CONFIG["exposure_settle_s"]

    def _lock_settings(self):
        cap = self.cap
        if cap is None:
            return
        manual = 0.25 if IS_WINDOWS else 1
        s = {}

        def get(p):
            try:
                return float(cap.get(p))
            except Exception:
                return None

        exposure, gain, wb = get(cv2.CAP_PROP_EXPOSURE), get(cv2.CAP_PROP_GAIN), get(cv2.CAP_PROP_WB_TEMPERATURE)

        def put(key, prop, val):
            try:
                s[key] = bool(cap.set(prop, val))
            except Exception:
                s[key] = False

        put("auto_exposure_off", cv2.CAP_PROP_AUTO_EXPOSURE, manual)
        if exposure:
            put("exposure_set", cv2.CAP_PROP_EXPOSURE, exposure)
        put("auto_wb_off", cv2.CAP_PROP_AUTO_WB, 0)
        if wb and wb > 0:
            put("wb_set", cv2.CAP_PROP_WB_TEMPERATURE, wb)
        put("autofocus_off", cv2.CAP_PROP_AUTOFOCUS, 0)
        s.update({
            "locked": bool(s.get("auto_exposure_off")),
            "exposure": exposure, "gain": gain, "wb_temperature": wb,
            "locked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
        self.cam_settings = s
        self.window.clear()
        self.stability = None

    def _close(self):
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass
        self.cap = None
        self.cam = None
        self.analysis = None
        self.checks = []
        self.settle_until = 0.0
        self.cam_settings = {}

    def _flash(self, msg):
        self.message = msg
        self.message_t = time.time()

    # ── colour test ──
    def _step_test(self, a, now):
        t = self.test
        if not t:
            return
        t["frames_seen"] += 1
        exposure_bad = (a["dark_pct"] > CONFIG["max_dark_clip_pct"] or
                        a["bright_pct"] > CONFIG["max_bright_clip_pct"])
        if exposure_bad:
            t["bad_since"] = t["bad_since"] or now
            if now - t["bad_since"] > CONFIG["light_lost_grace_s"]:
                if t["state"] == "measuring" and t["readings"]:
                    self._finalize("light_lost")
                else:
                    self.test = None
                    self._flash("Test cancelled: light/exposure went out of range before the reference was set.")
                return
        else:
            t["bad_since"] = None

        if t["state"] == "reference":
            if t["frames_seen"] <= CONFIG["reference_skip_frames"]:
                return
            t["ref_labs"].append(a["lab"])
            if len(t["ref_labs"]) >= CONFIG["reference_frames"]:
                t["ref"] = np.median(np.array(t["ref_labs"]), axis=0)
                t["state"] = "measuring"
                t["t0"] = now
                t["start_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            return

        ref = t["ref"]
        lab = a["lab"]
        de00 = float(delta_e_2000(ref, lab))
        de76 = float(delta_e_76(ref, lab))
        decmc = float(delta_e_cmc(ref, lab))
        status = "same" if de00 <= t["threshold"] else "not_same"
        t["readings"].append({
            "t": round(now - t["t0"], 3),
            "L": round(float(lab[0]), 3), "a": round(float(lab[1]), 3), "b": round(float(lab[2]), 3),
            "de00": round(de00, 3), "de76": round(de76, 3), "decmc": round(decmc, 3),
            "diff": round(de00, 3),
            "status": status,
        })
        if now - t["t0"] >= t["duration"]:
            self._finalize("completed")

    def _finalize(self, reason):
        t = self.test
        self.test = None
        if not t or not t["readings"]:
            return None
        rs = t["readings"]
        total = len(rs)
        same = sum(1 for r in rs if r["status"] == "same")
        de00 = np.array([r["de00"] for r in rs])
        de76 = np.array([r["de76"] for r in rs])
        decmc = np.array([r["decmc"] for r in rs])
        ref = t["ref"]
        report = {
            "id": int(time.time() * 1000),
            "version": 2,
            "fabric_name": t["fabric_name"],
            "light_source": t["light_source"],
            "operator": t["operator"],
            "date": t["start_time"],
            "duration": t["duration"],
            "actual_duration": round(rs[-1]["t"], 2),
            "stop_reason": reason,
            "mode": t["mode"],
            "camera_name": t["camera_name"],
            "camera_settings": t["camera_settings"],
            "setup": t["setup"],
            "total_readings": total,
            "fps": round(total / rs[-1]["t"], 1) if rs[-1]["t"] > 0 else None,
            "same": same,
            "not_same": total - same,
            "pct_good": round(same / total * 100, 1),
            "pct_bad": round((total - same) / total * 100, 1),
            "delta_e_method": "CIEDE2000",
            "delta_e_threshold": t["threshold"],
            "avg_diff": _r(de00.mean(), 3), "std_diff": _r(de00.std(), 3),
            "min_diff": _r(de00.min(), 3), "max_diff": _r(de00.max(), 3),
            "p95_diff": _r(np.percentile(de00, 95), 3),
            "de76_avg": _r(de76.mean(), 3), "de76_max": _r(de76.max(), 3),
            "decmc_avg": _r(decmc.mean(), 3), "decmc_max": _r(decmc.max(), 3),
            "reference_lab": [round(float(v), 3) for v in ref],
            "reference_hex": lab_to_hex(ref),
            "reference_frames": CONFIG["reference_frames"],
            "readings": rs,
        }
        if self.on_report:
            self.on_report(report)
        self.last_report = report
        return report

    # ── setup baseline ──
    def _step_baseline(self, a, now):
        b = self.baseline
        if not b:
            return
        b["labs"].append(a["lab"])
        b["grids"].append(a["grid"])
        b["dark"].append(a["dark_pct"])
        b["bright"].append(a["bright_pct"])
        b["L"].append(a["mean_L"])
        if now - b["t0"] >= b["duration"]:
            self.baseline = None
            self.baseline_result = self._baseline_result(b, now)

    def _baseline_result(self, b, now):
        labs = np.array(b["labs"])
        ref = np.median(labs, axis=0)
        noise = delta_e_2000(ref, labs)
        grid = np.array(b["grids"]).mean(axis=0)
        grid_de = delta_e_2000(grid[1, 1], grid.reshape(-1, 3))
        dark = float(np.mean(b["dark"]))
        bright = float(np.mean(b["bright"]))
        n_mean, n_std = float(noise.mean()), float(noise.std())
        n_p95 = float(np.percentile(noise, 95))
        suggested = max(CONFIG["min_threshold_de00"], math.ceil((n_mean + 3 * n_std) * 10) / 10)
        checks = {
            "camera_locked": bool(self.cam_settings.get("locked")),
            "exposure_ok": dark <= CONFIG["max_dark_clip_pct"] and bright <= CONFIG["max_bright_clip_pct"],
            "stable_ok": n_p95 <= CONFIG["stability_max_de00"],
            "even_ok": float(grid_de.max()) <= CONFIG["uniformity_max_de00"],
        }
        mode = self.cam["kind"] if self.cam else None
        return {
            "measured_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "duration_s": round(now - b["t0"], 1),
            "frames": int(len(labs)),
            "camera_name": self.cam["name"] if self.cam else None,
            "mode": mode,
            "camera_settings": dict(self.cam_settings),
            "reference_lab": [round(float(v), 3) for v in ref],
            "reference_hex": lab_to_hex(ref),
            "mean_L": _r(np.mean(b["L"])),
            "dark_clip_pct": _r(dark), "bright_clip_pct": _r(bright),
            "noise_mean_de00": _r(n_mean, 3), "noise_std_de00": _r(n_std, 3),
            "noise_p95_de00": _r(n_p95, 3), "noise_max_de00": _r(noise.max(), 3),
            "uniformity_max_de00": _r(grid_de.max(), 3), "uniformity_mean_de00": _r(grid_de.mean(), 3),
            "grid_de00": [round(float(v), 2) for v in grid_de],
            "suggested_threshold_de00": suggested,
            "checks": checks,
            "setup_ok": all(checks.values()) and mode == "measurement",
            "limits": {k: CONFIG[k] for k in ("max_dark_clip_pct", "max_bright_clip_pct",
                                              "stability_max_de00", "uniformity_max_de00")},
        }

    # ── snapshots for the web layer ──
    def snapshot(self):
        now = time.time()
        with self.lock:
            a = self.analysis
            t = self.test
            test = None
            if t:
                rs = t["readings"]
                total = len(rs)
                same = sum(1 for r in rs if r["status"] == "same")
                el = (now - t["t0"]) if t["t0"] else 0.0
                test = {
                    "state": t["state"],
                    "fabric_name": t["fabric_name"],
                    "threshold": t["threshold"],
                    "duration": t["duration"],
                    "elapsed": round(el, 1),
                    "remaining": max(0, round(t["duration"] - el)),
                    "reference_progress": min(1.0, max(0, t["frames_seen"] - CONFIG["reference_skip_frames"])
                                              / CONFIG["reference_frames"]),
                    "reference_hex": lab_to_hex(t["ref"]) if t["ref"] is not None else None,
                    "light_bad": t["bad_since"] is not None,
                    "stats": {
                        "total": total, "same": same, "not_same": total - same,
                        "pct_good": round(same / total * 100, 1) if total else 0,
                        "pct_bad": round((total - same) / total * 100, 1) if total else 0,
                    },
                    "history": [{"diff": r["de00"], "status": r["status"]} for r in rs[-90:]],
                    "last": rs[-1] if rs else None,
                }
            lr = self.last_report
            baseline = None
            if self.baseline:
                b = self.baseline
                baseline = {"progress": min(1.0, (now - b["t0"]) / b["duration"]), "frames": len(b["labs"])}
            ready, reason = self.ready_for_test()
            return {
                "camera": ({**self.cam, "settings": self.cam_settings, "settling": self.is_settling()}
                           if self.cam else None),
                "cameras": self.cameras,
                "camera_choice": self.manual_choice or "auto",
                "mode": self.mode(),
                "checks": self.checks,
                "ready": ready,
                "ready_reason": reason,
                "live": None if a is None else {
                    "lab": [round(float(v), 2) for v in a["lab"]],
                    "hex": lab_to_hex(a["lab"]),
                    "uniformity": _r(a["uniformity"]),
                    "grid_de00": [round(float(v), 2) for v in a["grid_de"]],
                    "dark_pct": _r(a["dark_pct"]), "bright_pct": _r(a["bright_pct"]),
                    "mean_L": _r(a["mean_L"]), "stability": _r(self.stability),
                },
                "test": test,
                "last_report": None if lr is None else {k: v for k, v in lr.items() if k != "readings"},
                "baseline": baseline,
                "baseline_result": self.baseline_result,
                "message": self.message if now - self.message_t < 6 else "",
                "limits": {k: CONFIG[k] for k in ("uniformity_max_de00", "stability_max_de00",
                                                  "default_threshold_de00", "min_threshold_de00",
                                                  "pass_pct", "excellent_pct")},
            }

    def stream_frame(self, view):
        """Latest frame with overlays, as JPEG bytes (or None)."""
        with self.lock:
            if self.frame is None or self.cap is None:
                return None, self.frame_id
            frame = self.frame.copy()
            a = self.analysis
            t = self.test
            fid = self.frame_id
            last_status = t["readings"][-1]["status"] if (t and t["readings"]) else None
            state = t["state"] if t else None
        if a is not None:
            x, y, w, h = a["rect"]
            if view == "setup":
                cw, ch = w / 3.0, h / 3.0
                for i in range(3):
                    for j in range(3):
                        de = float(a["grid_de"][i * 3 + j])
                        ok = de <= CONFIG["uniformity_max_de00"]
                        col = (80, 200, 80) if ok else (60, 60, 230)
                        x0, y0 = int(x + j * cw), int(y + i * ch)
                        cv2.rectangle(frame, (x0, y0), (int(x0 + cw), int(y0 + ch)), col, 1)
                        txt = "REF" if (i, j) == (1, 1) else f"{de:.1f}"
                        cv2.putText(frame, txt, (x0 + 5, y0 + 16), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                                    (0, 0, 0), 3, cv2.LINE_AA)
                        cv2.putText(frame, txt, (x0 + 5, y0 + 16), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                                    col, 1, cv2.LINE_AA)
            else:
                col = (0, 255, 100)
                if state == "reference":
                    col = (0, 215, 255)
                elif last_status == "not_same":
                    col = (60, 60, 240)
                cv2.rectangle(frame, (x, y), (x + w, y + h), col, 2)
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        return (buf.tobytes() if ok else None), fid