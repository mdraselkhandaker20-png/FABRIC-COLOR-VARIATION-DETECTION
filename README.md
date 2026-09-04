# Fabric Color Variation Detection

A real-time fabric color-consistency inspection system: Python + OpenCV vision
core, Flask web layer, and a native desktop shell (pywebview) so it opens as
its own app window instead of a browser tab.

---

## 🛠 Setup (first time)

### Step 1 — Install Python
Python 3.9+ — https://python.org

### Step 2 — Open the folder in VS Code
```
File → Open Folder → select this project folder
```

### Step 3 — Create + activate a virtual environment
```bash
python -m venv venv
# Windows
venv\Scripts\activate
# Mac/Linux
source venv/bin/activate
```

### Step 4 — Install dependencies
```bash
pip install -r requirements.txt
```

### Step 5 — Plug in the USB inspection camera
Connect **only** the USB camera you'll use for testing (no built-in laptop
camera fighting for index 0). The app always opens camera index `0`, so with
just the USB camera plugged in, that's it — nothing to select in the UI.

---

## ▶ Running it

**As a desktop app (recommended — this is what you asked for):**
```bash
python desktop_app.py
```
This opens a maximized native window with no browser bar. The live feed and
the report always fill the display, however big or small the USB camera's
sensor is — the video is scaled to the window, not the other way round.

**As a regular web app (for debugging in a browser):**
```bash
python app.py
```
Then open **http://127.0.0.1:5000**

---

## 📌 How a test works

1. Enter the **fabric name** (required) and optionally the **light source**
   (e.g. "D65 6500K LED booth") — this gets saved into the report for your
   documentation.
2. Wait for the light badge to show **LIGHT OK** (5/5 green dots).
3. Click **START**.
   - The first ~10 frames lock in the **reference color**.
   - Every frame after that is compared to the reference in **CIE76 ΔE**
     (Delta E) color-difference space, computed in CIE Lab.
   - **Green** = ΔE ≤ 15 (same). **Red** = ΔE > 15 (variation detected).
4. The test **auto-stops and generates the report at 30 seconds** (default;
   editable per test) — no manual STOP needed for a normal run.
5. The report modal shows pass/fail plus % good vs % defect. Click
   **VIEW REPORT** for the full page, or **EXPORT CSV** on that page to get
   a spreadsheet-ready table of every reading (useful for building tables/
   figures for a paper).

---

## 🔧 Adjusting sensitivity

In `app.py`:
```python
DELTA_E_THRESHOLD = 15
```
Lower = more sensitive (flags smaller color shifts). Higher = more tolerant.
AATCC/ISO textile practice commonly treats ΔE ≤ 1–2 as "not visible to the
eye" and ΔE up to ~3–5 as a commercially tight pass/fail line — 15 here is
deliberately loose for a webcam-grade sensor; tighten it once you're on a
locked-exposure USB camera in a proper light box (see below).

---

## 🖥 Build a standalone .exe (optional, Windows)

Once `desktop_app.py` runs correctly with `python desktop_app.py`, you can
package it as a single-click executable so it doesn't need VS Code or a
terminal at all:

```bash
pip install pyinstaller
pyinstaller --noconfirm --onedir --windowed ^
  --add-data "templates;templates" ^
  --add-data "static;static" ^
  --name "FabricColorQC" desktop_app.py
```
(On Mac/Linux replace `;` with `:` in `--add-data`.) The output appears in
`dist/FabricColorQC/`. Copy `reports.json` next to the produced `.exe` so
your saved test history travels with it.

---

## 📁 Project structure

```
├── app.py                  # Flask backend — camera loop, ΔE calc, reports, CSV export
├── desktop_app.py          # Runs app.py in a background thread + opens it in a native window
├── requirements.txt
├── reports.json            # Saved test history (auto-created/updated)
├── templates/
│   ├── base.html           # Sidebar layout (history scrolls independently of the page)
│   ├── check_color.html    # Main test dashboard
│   ├── check_gsm.html      # GSM module (placeholder)
│   └── report.html         # Single test report + CSV export
└── static/
    ├── css/style.css
    └── js/{main.js, color_check.js}
```

---

## 📷 Hardware notes (for repeatable, publishable readings)

See the accompanying chat message for camera + lighting recommendations and
why they matter for CIE76 ΔE measurements to be defensible in a journal
write-up (manual exposure/white-balance lock, D65 lighting, enclosed booth).