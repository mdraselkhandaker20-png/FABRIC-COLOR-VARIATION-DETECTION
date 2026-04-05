# Fabric Color Detection System

A real-time fabric color inspection dashboard using Python Flask + OpenCV.

---

## 🛠 Setup Instructions (VS Code)

### Step 1 — Install Python
Make sure Python 3.9+ is installed: https://python.org

### Step 2 — Open folder in VS Code
```
File → Open Folder → select `fabric-color-detection`
```

### Step 3 — Open Terminal in VS Code
```
Terminal → New Terminal
```

### Step 4 — Create virtual environment
```bash
python -m venv venv
```

### Step 5 — Activate virtual environment
**Windows:**
```bash
venv\Scripts\activate
```
**Mac/Linux:**
```bash
source venv/bin/activate
```

### Step 6 — Install dependencies
```bash
pip install -r requirements.txt
```

### Step 7 — Run the app
```bash
python app.py
```

### Step 8 — Open browser
Go to: **http://127.0.0.1:5000**

---

## 📌 How It Works

1. Click **"Check Color"** in the sidebar → opens the dashboard
2. Click **START** → camera turns on, scanning begins
   - First ~10 frames = **reference color** is captured automatically
   - After that, every frame is compared to the reference
3. **Green LED** = color matches reference (Delta E ≤ 15)
4. **Red LED** = color mismatch detected (Delta E > 15)
5. **Live graph** shows color difference over time
6. Click **STOP** → camera off, LEDs off

---

## 🔧 Adjusting Sensitivity

In `app.py`, find this line:
```python
THRESHOLD = 15  # Delta E threshold
```
- Lower number = more sensitive (detects smaller color changes)
- Higher number = less sensitive

---

## 📁 Project Structure

```
fabric-color-detection/
├── app.py                  # Flask backend (camera + color logic)
├── requirements.txt        # Python packages
├── templates/
│   ├── base.html           # Sidebar layout
│   ├── index.html          # Redirect to check_color
│   ├── check_color.html    # Main dashboard page
│   └── check_gsm.html      # GSM page (placeholder)
└── static/
    ├── css/
    │   └── style.css       # All styles
    └── js/
        ├── main.js         # Shared JS
        └── color_check.js  # Dashboard logic + graph
```
