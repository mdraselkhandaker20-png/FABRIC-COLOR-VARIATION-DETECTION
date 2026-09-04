let isRunning = false;
let statusInterval = null;
let timerInterval = null;
let graphData = [];
let testDuration = 30;
let elapsed = 0;
const THRESHOLD = 15;

const canvas = document.getElementById('colorGraph');
const ctx = canvas ? canvas.getContext('2d') : null;

// ── Keep the graph canvas filling its card at native resolution ────
// (the card's height now flexes with the viewport, so this is measured
// live instead of using a fixed CSS height)
function sizeGraphCanvas() {
    if (!canvas || !canvas.parentElement) return;
    const rect = canvas.parentElement.getBoundingClientRect();
    canvas.width = Math.max(50, rect.width - 26);
    canvas.height = Math.max(40, rect.height - 30);
    drawGraph();
}
window.addEventListener('resize', sizeGraphCanvas);

// ── Preview (always on, single USB camera) ─────────────────────
function startPreview() {
    const preview = document.getElementById('previewFeed');
    if (preview) {
        preview.src = '/preview_feed?t=' + Date.now();
        preview.style.display = 'block';
    }
}

// ── Light monitoring ──────────────────────────────────────────
function updateLightUI(level) {
    const ids = ['ld1','ld2','ld3','ld4','ld5'];
    ids.forEach((id, i) => {
        const el = document.getElementById(id);
        if (!el) return;
        if (i >= level) { el.className = 'ld dim'; return; }
        // dot 1,2 = red, dot 3,4 = yellow, dot 5 = green
        if (i < 2) el.className = 'ld red';
        else if (i < 4) el.className = 'ld yel';
        else el.className = 'ld grn';
    });

    const badge = document.getElementById('lightBadge');
    const txt = document.getElementById('lightTxt');
    if (level >= 5) {
        badge.className = 'light-badge ok';
        txt.textContent = 'LIGHT OK';
    } else if (level > 0) {
        badge.className = 'light-badge low';
        txt.textContent = 'LIGHT LOW';
    } else {
        badge.className = 'light-badge checking';
        txt.textContent = 'CHECKING...';
    }
}

// ── Light poll (when not running) ─────────────────────────────
function startLightMonitor() {
    setInterval(() => {
        if (isRunning) return;
        fetch('/light_status').then(r => r.json()).then(d => {
            updateLightUI(d.level);
        }).catch(() => {});
    }, 800);
}

// ── Start ─────────────────────────────────────────────────────
function startDetection() {
    const fabricName = document.getElementById('fabricNameInput').value.trim();
    if (!fabricName) {
        document.getElementById('fabricNameInput').style.borderColor = '#ef4444';
        setTimeout(() => document.getElementById('fabricNameInput').style.borderColor = '', 1500);
        return;
    }
    testDuration = parseInt(document.getElementById('durationInput').value) || 30;
    const lightSource = (document.getElementById('lightSourceInput') || {}).value || '';

    fetch('/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ fabric_name: fabricName, duration: testDuration, light_source: lightSource })
    }).then(r => r.json()).then(d => {
        if (d.status === 'light_low') {
            alert('Light not OK! Please ensure proper lighting before starting.');
            return;
        }

        isRunning = true;
        graphData = [];
        elapsed = 0;

        // preview বন্ধ → video চালু (delay দিয়ে)
        const preview = document.getElementById('previewFeed');
        if (preview) { preview.src = ''; preview.style.display = 'none'; }

        document.getElementById('fabricDisplay').textContent = fabricName;
        document.getElementById('camFabricName').textContent = 'Fabric: ' + fabricName;
        document.getElementById('camScan').style.display = 'block';
        document.getElementById('camTimer').style.display = 'block';
        document.getElementById('camTimer').textContent = testDuration + 's';
        document.getElementById('lightWarn').style.display = 'none';

        document.getElementById('startBindi').className = 'bindi green';
        document.getElementById('stopBindi').className = 'bindi';

        setTimeout(() => {
            document.getElementById('videoFeed').src = '/video_feed?' + Date.now();
            document.getElementById('videoFeed').style.display = 'block';
        }, 800);

        timerInterval = setInterval(() => {
            elapsed++;
            const rem = Math.max(0, testDuration - elapsed);
            document.getElementById('camTimer').textContent = rem + 's';
        }, 1000);

        sizeGraphCanvas();
        statusInterval = setInterval(pollStatus, 400);
    });
}

// ── Stop ──────────────────────────────────────────────────────
function stopDetection() {
    fetch('/stop', { method: 'POST' }).then(r => r.json()).then(d => {
        shutdown();
        if (d.report) showModal(d.report);
    });
}

// ── Refresh ───────────────────────────────────────────────────
function refreshSystem() {
    if (isRunning) {
        fetch('/stop', { method: 'POST' }).then(() => {
            isRunning = false;
            clearInterval(statusInterval);
            clearInterval(timerInterval);
            resetUI();
            startPreview();
        });
    } else {
        resetUI();
        startPreview();
    }
}

function resetUI() {
    document.getElementById('videoFeed').src = '';
    document.getElementById('videoFeed').style.display = 'none';
    document.getElementById('camScan').style.display = 'none';
    document.getElementById('camTimer').style.display = 'none';
    document.getElementById('camFabricName').textContent = '';
    document.getElementById('lightWarn').style.display = 'none';
    document.getElementById('fabricDisplay').textContent = '—';
    document.getElementById('startBindi').className = 'bindi';
    document.getElementById('stopBindi').className = 'bindi red';
    document.getElementById('scGoodPct').textContent = '0%';
    document.getElementById('scBadPct').textContent = '0%';
    document.getElementById('scTotal').textContent = '0';
    document.getElementById('qbarFill').style.width = '0%';
    document.getElementById('qbarVal').textContent = '— %';
    document.getElementById('qbarVal').className = 'qbar-val';
    graphData = [];
    if (ctx && canvas) { ctx.clearRect(0, 0, canvas.width, canvas.height); }
}

function shutdown() {
    isRunning = false;
    clearInterval(statusInterval);
    clearInterval(timerInterval);

    document.getElementById('videoFeed').src = '';
    document.getElementById('videoFeed').style.display = 'none';
    document.getElementById('camScan').style.display = 'none';
    document.getElementById('camTimer').style.display = 'none';
    document.getElementById('camFabricName').textContent = '';
    document.getElementById('lightWarn').style.display = 'none';

    document.getElementById('startBindi').className = 'bindi';
    document.getElementById('stopBindi').className = 'bindi red';

    // delay দিয়ে preview চালু
    setTimeout(() => startPreview(), 800);

    if (typeof loadHistory === 'function') loadHistory();
}

// ── Poll status ───────────────────────────────────────────────
function pollStatus() {
    fetch('/status').then(r => r.json()).then(d => {
        // light warn
        if (d.light !== undefined) {
            updateLightUI(d.light.level);
            if (d.light.level < 5 && isRunning) {
                document.getElementById('lightWarn').style.display = 'block';
            } else {
                document.getElementById('lightWarn').style.display = 'none';
            }
        }

        // stats
        if (d.stats) {
            const g = d.stats.pct_good;
            document.getElementById('scGoodPct').textContent = g + '%';
            document.getElementById('scBadPct').textContent = d.stats.pct_bad + '%';
            document.getElementById('scTotal').textContent = d.stats.total;
            const lbl = g >= 90 ? 'EXCELLENT' : g >= 80 ? 'GOOD' : 'BELOW MIN';
            document.getElementById('scGoodLbl').textContent = lbl;
            const fill = document.getElementById('qbarFill');
            fill.style.width = Math.min(g, 100) + '%';
            fill.className = 'qbar-fill' + (g >= 90 ? ' excellent' : g < 80 ? ' fail' : '');
            const val = document.getElementById('qbarVal');
            val.textContent = g + '% — ' + lbl;
            val.className = 'qbar-val' + (g >= 90 ? ' excellent' : g < 80 ? ' fail' : ' good');
        }

        // graph
        if (d.history && d.history.length) { graphData = d.history; drawGraph(); }

        // auto report
        if (!d.running && isRunning) {
            isRunning = false;
            clearInterval(statusInterval);
            clearInterval(timerInterval);
            setTimeout(() => {
                fetch('/status').then(r => r.json()).then(d2 => {
                    shutdown();
                    if (d2.last_report) showModal(d2.last_report);
                });
            }, 600);
        }
    }).catch(() => {});
}

// ── Modal ─────────────────────────────────────────────────────
function showModal(report) {
    document.getElementById('modalFabric').textContent = report.fabric_name;
    document.getElementById('modalGoodPct').textContent = report.pct_good + '%';
    document.getElementById('modalBadPct').textContent = report.pct_bad + '%';
    const pass = report.pct_good >= 80;
    const v = document.getElementById('modalVerdict');
    v.textContent = pass
        ? (report.pct_good >= 90 ? '★ EXCELLENT — Outstanding color consistency' : '✓ FABRIC PASSED — Color consistency acceptable')
        : '✗ FABRIC FAILED — ' + report.not_same + ' defects found';
    v.className = 'modal-verdict ' + (pass ? 'pass' : 'fail');
    document.getElementById('modalViewBtn').onclick = () => window.location = '/report/' + report.id;
    document.getElementById('modalAgainBtn').onclick = () => { closeModal(); refreshSystem(); };
    document.getElementById('reportModal').style.display = 'flex';
}

function closeModal() {
    document.getElementById('reportModal').style.display = 'none';
}

// ── Graph ─────────────────────────────────────────────────────
function drawGraph() {
    if (!ctx || !canvas) return;
    const w = canvas.width, h = canvas.height;
    ctx.clearRect(0, 0, w, h);
    if (graphData.length < 2) return;
    ctx.fillStyle = '#f8f7f5'; ctx.fillRect(0, 0, w, h);
    const maxDiff = 40;
    const ty = h - (THRESHOLD / maxDiff) * h;
    ctx.strokeStyle = 'rgba(239,68,68,0.35)'; ctx.setLineDash([5,4]); ctx.lineWidth = 1.5;
    ctx.beginPath(); ctx.moveTo(0, ty); ctx.lineTo(w, ty); ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = 'rgba(239,68,68,0.45)'; ctx.font = '9px monospace';
    ctx.fillText('THRESHOLD', w - 76, ty - 3);
    const step = w / (graphData.length - 1);
    ctx.beginPath(); ctx.lineWidth = 2; ctx.strokeStyle = '#2d5a3d'; ctx.lineJoin = 'round';
    graphData.forEach((p, i) => {
        const x = i * step, y = h - (Math.min(p.diff, maxDiff) / maxDiff) * h;
        i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
    ctx.stroke();
    graphData.forEach((p, i) => {
        const x = i * step, y = h - (Math.min(p.diff, maxDiff) / maxDiff) * h;
        ctx.beginPath(); ctx.arc(x, y, 3, 0, Math.PI * 2);
        ctx.fillStyle = p.status === 'same' ? '#22c55e' : '#ef4444'; ctx.fill();
    });
}

// ── Init ──────────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', () => {
    document.getElementById('stopBindi').className = 'bindi red';
    sizeGraphCanvas();
    startPreview();
    startLightMonitor();
});