# Fabric Color Variation Detection (v2)

Real-time fabric colour-consistency inspection: Python + OpenCV vision core,
Flask web layer, native desktop window (pywebview).

**What changed in v2**
- **Camera is chosen by name.** The Logitech C270 is found automatically
  (Windows DirectShow names via `pygrabber`). Plug it in at any time — the app
  switches to it within ~3 s.
- **Two modes, always visible in the top bar.**
  - 🟢 **MEASUREMENT MODE** — USB C270. Exposure and white balance are locked.
    Only these reports are measurements.
  - 🟡 **DEMO MODE** — any other camera (e.g. the laptop's). Everything works,
    but the screen, the report and the CSV are all stamped **DEMO**.
- **Setup & Calibration page** — find the camera/light distances where all
  five checks are green, measure the system's own noise (baseline), save the
  setup. Every later report quotes the active setup.
- **Correct colour science.** Real CIE L\*a\*b\* (v1 used OpenCV's 8-bit Lab,
  which inflated ΔE ~2.5× on lightness). Primary metric is **CIEDE2000**;
  ΔE76 and **CMC(2:1)** are recorded too. Formulas are verified against
  Sharma et al. (2005) test data — run `python tests/verify_colorimetry.py`.
- **One camera owner.** A single background thread reads the camera; the
  preview and the test share it, so there is no more black-screen / "camera in
  use" conflict when a test starts.
- Reference colour = median of 15 frames (v1 used a single frame).

---

## Setup (first time)

```bash
python -m venv venv
venv\Scripts\activate          # Windows   (Mac/Linux: source venv/bin/activate)
pip install -r requirements.txt
```

## Running

```bash
python desktop_app.py          # native window (recommended)
python app.py                  # browser at http://127.0.0.1:5000 (debugging)
```

No hardware at hand? Run the built-in simulator (two fake cameras):
```bash
set FCV_FAKE_CAMERA=1          # Mac/Linux: export FCV_FAKE_CAMERA=1
set FCV_FAKE_DEFECT=1          # optional: fake shade defect every 20 s
python desktop_app.py
```

---

## Live demo for the supervisor (laptop only)

1. Start the app without the USB camera → top bar shows **DEMO MODE**.
2. Hold a piece of fabric in front of the laptop camera, press **START** —
   the full test, graph, report and CSV work.
3. Plug in the C270 → the app switches to **MEASUREMENT MODE** by itself
   (toast message + green badge). Point out that only these reports count.

In demo mode START needs only camera + exposure checks; the "stable" and
"even light" dots may stay red under room light, and the badge says
`DEMO OK · …`. In measurement mode all five must be green.

## The five readiness checks ("light dots")

| Dot | Passes when |
|---|---|
| Camera | frames arriving and exposure/WB lock finished |
| Not too dark | ≤ 1 % of inspection-area pixels are black |
| Not overexposed | ≤ 1 % of pixels have a clipped channel |
| Stable | 95th percentile frame-to-frame ΔE00 ≤ 1.0 (last 30 frames) |
| Even light | max ΔE00 between the 9 cells of the inspection grid ≤ 2.0 |

Hover the dots to see the live values. Limits are in `CONFIG` in `engine.py`.

---

## Real setup → journal workflow

1. Open **Setup & Calibration** with the C270 connected (MEASUREMENT MODE).
2. Put a **uniformly dyed reference fabric** in the booth.
3. Move camera and LED panels until all five checks are green. The 3×3 grid
   drawn on the video shows ΔE00 of each cell vs. the centre — red cells mean
   uneven light there.
4. Click **MEASURE BASELINE** (10 s). You get: noise (mean ± SD, P95),
   uniformity, exposure, and a **suggested ΔE00 limit** = noise mean + 3 SD.
5. Enter camera→fabric distance, light→fabric distance, light angle, and
   **SAVE SETUP**. It becomes the active setup.
6. Repeat 3–5 at other distances. Every trial is kept →
   **Export all as CSV** gives a table of distance vs. noise vs. uniformity
   for the paper; the best trial is your justified operating point.
7. Run colour tests on **Check Color**. The ΔE00 limit defaults to
   max(2.0, suggested limit). Export each report as CSV (per-reading L\*a\*b\*,
   ΔE00, ΔE76, ΔE CMC(2:1)).

To re-adapt the camera after changing the lights, click **Re-lock exposure &
white balance** on the Setup page.

### Methods paragraph (template — fill in your numbers)

> Images were acquired with a Logitech C270 HD USB webcam (640×480, ~30 fps)
> under bilateral LED panel illumination (5500 K, daylight-balanced) at a
> camera-to-fabric distance of __ cm, light-to-fabric distance of __ cm and
> illumination angle of __°. Auto-exposure and auto white balance were
> disabled after a 2 s adaptation period. Camera RGB values were converted to
> CIE L\*a\*b\* assuming sRGB/D65. For each frame the colour of the central
> inspection region was taken as the per-channel median of L\*a\*b\*; the
> reference colour was the median of 15 consecutive frames. Colour difference
> was computed with CIEDE2000 (k_L = k_C = k_H = 1); ΔE\*ab and ΔE CMC(2:1)
> were also recorded. System repeatability, measured on a uniform reference
> fabric over __ s (n = __ frames), was ΔE00 = __ ± __ (P95 = __);
> illumination uniformity across a 3×3 grid was ≤ __ ΔE00. The pass/fail
> limit was set to ΔE00 = __, above the system noise floor (mean + 3 SD).

**Limitation to state honestly:** the webcam is not colorimetrically
calibrated (sRGB assumption), so absolute L\*a\*b\* values are approximate;
the method is valid for *relative* colour differences under fixed, locked
camera settings. A colour-checker calibration (e.g. X-Rite ColorChecker)
would be the natural next step.

---

## Build a standalone .exe (Windows, optional)

```bash
pyinstaller --noconfirm --onedir --windowed ^
  --add-data "templates;templates" --add-data "static;static" ^
  --hidden-import pygrabber.dshow_graph --collect-submodules comtypes ^
  --name "FabricColorQC" desktop_app.py
```
Output: `dist/FabricColorQC/`. `reports.json`, `setups.json` and
`settings.json` are created next to the `.exe`.

---

## Project structure

```
├── app.py               # Flask routes, report/setup storage, CSV export
├── engine.py            # camera discovery, single camera thread, checks, test + baseline, CONFIG
├── colorimetry.py       # sRGB→CIE Lab, CIEDE2000, CMC(l:c), CIE76
├── desktop_app.py       # native window launcher
├── tests/verify_colorimetry.py
├── reports.json         # test reports (v1 reports are shown as "legacy")
├── setups.json          # saved setup trials (created on first save)
├── settings.json        # active setup (created automatically)
├── templates/           # check_color, setup, report, check_gsm + partials
└── static/              # css/style.css, js/{main,color_check,setup}.js
```

v1 reports stay readable but are labelled **legacy (v1)** — their ΔE values
used the inflated 8-bit Lab scale and should not be mixed with v2 results.