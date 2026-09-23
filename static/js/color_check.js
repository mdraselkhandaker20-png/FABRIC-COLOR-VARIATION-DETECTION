// ── Check Color page ───────────────────────────────────────────
let graphData = [];
let graphThreshold = 2.0;
let wasRunning = false;
let lastReportId = null;
let thresholdTouched = false;

const canvas = document.getElementById('colorGraph');
const ctx = canvas ? canvas.getContext('2d') : null;

function $(id) { return document.getElementById(id); }

function sizeGraphCanvas() {
    if (!canvas || !canvas.parentElement) return;
    const rect = canvas.parentElement.getBoundingClientRect();
    canvas.width = Math.max(50, rect.width - 26);
    canvas.height = Math.max(40, rect.height - 30);
    drawGraph();
}
window.addEventListener('resize', sizeGraphCanvas);

function setMsg(text, kind) {
    const m = $('ctrlMsg');
    m.textContent = text || '';
    m.className = 'ctrl-msg ' + (kind || '');
}

// ── Start / stop ───────────────────────────────────────────────
function startDetection() {
    const nameEl = $('fabricNameInput');
    const fabricName = nameEl.value.trim();
    if (!fabricName) {
        nameEl.style.borderColor = '#ef4444';
        nameEl.focus();
        setMsg('Enter a fabric name first.', 'err');
        setTimeout(() => nameEl.style.borderColor = '', 1500);
        return;
    }
    const s = FCV.status;
    if (s && s.mode === 'demo') {
        setMsg('Demo camera — this report will be marked DEMO.', 'warn');
    }
    postJSON('/start', {
        fabric_name: fabricName,
        light_source: $('lightSourceInput').value,
        duration: parseInt($('durationInput').value, 10) || 30,
        threshold: parseFloat($('thresholdInput').value) || 2.0,
    }).then(d => {
        if (!d.ok) { setMsg('Not started — ' + d.message, 'err'); return; }
        if (!(s && s.mode === 'demo')) setMsg('');
        graphData = [];
        drawGraph();
    });
}

function stopDetection() {
    postJSON('/stop').then(d => {
        if (d.report) { lastReportId = d.report.id; showModal(d.report); loadHistory(); }
    });
}

function refreshSystem() {
    const done = () => { resetUI(); setMsg(''); };
    if (FCV.status && FCV.status.test) postJSON('/stop').then(done); else done();
}

function resetUI() {
    $('scGoodPct').textContent = '0%';
    $('scBadPct').textContent = '0%';
    $('scTotal').textContent = '0';
    $('scGoodLbl').textContent = 'GOOD';
    $('qbarFill').style.width = '0%';
    $('qbarVal').textContent = '— %';
    $('qbarVal').className = 'qbar-val';
    graphData = [];
    drawGraph();
}

// ── Live status ────────────────────────────────────────────────
onStatus(s => {
    const lim = s.limits || {};
    // Setup line + default threshold from the active setup profile
    const line = $('setupLine');
    const a = s.active_setup;
    if (a) {
        const bits = [];
        if (a.camera_distance_cm != null) bits.push('camera ' + a.camera_distance_cm + ' cm');
        if (a.light_distance_cm != null) bits.push('light ' + a.light_distance_cm + ' cm');
        if (a.light_angle_deg != null) bits.push(a.light_angle_deg + '°');
        if (a.noise_mean_de00 != null) bits.push('noise ΔE00 ' + a.noise_mean_de00);
        line.innerHTML = `Setup: <strong>${esc(a.name)}</strong> <span class="muted">${esc(bits.join(' · '))}</span>`
            + (a.setup_ok ? '' : ' <span class="tag warn">checks not all passed</span>')
            + ' <a href="/setup">change</a>';
        if (!thresholdTouched && a.suggested_threshold_de00 != null) {
            const t = Math.max(lim.default_threshold_de00 || 2, a.suggested_threshold_de00);
            $('thresholdInput').value = t.toFixed(1);
        }
    } else {
        line.innerHTML = '<span class="sl-empty">No setup profile yet — <a href="/setup">run Setup &amp; Calibration</a> before measuring.</span>';
    }

    // Live colour swatch
    if (s.live) {
        $('swLive').style.background = s.live.hex;
        $('swLiveLbl').textContent = 'Live L* ' + s.live.lab[0].toFixed(1);
    }

    // State banner (camera settling / reference being captured)
    const sb = $('stateBanner');
    const t = s.test;
    if (s.camera && s.camera.settling) {
        sb.textContent = 'Locking exposure and white balance…';
        sb.style.display = 'block';
    } else if (t && t.state === 'reference') {
        sb.textContent = 'Capturing reference colour… ' + Math.round(t.reference_progress * 100) + '%';
        sb.style.display = 'block';
    } else {
        sb.style.display = 'none';
    }

    const running = !!t;
    $('startBindi').className = 'bindi' + (running ? ' green' : '');
    $('stopBindi').className = 'bindi' + (running ? '' : ' red');
    $('camScan').style.display = running ? 'block' : 'none';
    $('camTimer').style.display = running ? 'block' : 'none';
    $('lightWarn').style.display = (t && t.light_bad) ? 'block' : 'none';
    $('camFabricName').textContent = t ? 'Fabric: ' + t.fabric_name : '';
    $('btnStart').disabled = running;
    $('fabricNameInput').disabled = running;
    $('cameraSelect').disabled = running;

    if (t) {
        $('camTimer').textContent = (t.state === 'measuring' ? t.remaining : t.duration) + 's';
        if (t.reference_hex) $('swRef').style.background = t.reference_hex;
        $('swRefWrap').style.display = t.reference_hex ? 'flex' : 'none';
        graphThreshold = t.threshold;
        const st = t.stats;
        if (st.total) {
            const g = st.pct_good;
            const lbl = g >= lim.excellent_pct ? 'EXCELLENT' : g >= lim.pass_pct ? 'GOOD' : 'BELOW MIN';
            $('scGoodPct').textContent = g + '%';
            $('scBadPct').textContent = st.pct_bad + '%';
            $('scTotal').textContent = st.total;
            $('scGoodLbl').textContent = lbl;
            const fill = $('qbarFill');
            fill.style.width = Math.min(g, 100) + '%';
            fill.className = 'qbar-fill' + (g >= lim.excellent_pct ? ' excellent' : g < lim.pass_pct ? ' fail' : '');
            const val = $('qbarVal');
            val.textContent = g + '% — ' + lbl;
            val.className = 'qbar-val' + (g >= lim.excellent_pct ? ' excellent' : g < lim.pass_pct ? ' fail' : ' good');
        }
        graphData = t.history || [];
        drawGraph();
    }

    // Test just finished (auto-stop at the time limit, light lost, camera lost)
    if (wasRunning && !running && s.last_report && s.last_report.id !== lastReportId) {
        lastReportId = s.last_report.id;
        showModal(s.last_report);
        loadHistory();
    } else if (wasRunning && !running && !s.last_report) {
        setMsg('Test cancelled before the reference colour was captured.', 'err');
    }
    wasRunning = running;
});

// ── Modal ──────────────────────────────────────────────────────
const STOP_TEXT = {
    completed: 'Completed', stopped_by_user: 'Stopped manually',
    light_lost: 'Stopped: light went out of range', camera_lost: 'Stopped: camera disconnected',
};
function showModal(r) {
    const lim = (FCV.status && FCV.status.limits) || { pass_pct: 80, excellent_pct: 90 };
    $('modalFabric').textContent = r.fabric_name;
    $('modalGoodPct').textContent = r.pct_good + '%';
    $('modalBadPct').textContent = r.pct_bad + '%';
    const m = $('modalMode');
    m.textContent = (r.mode === 'measurement' ? 'Measurement' : 'DEMO — not a measurement')
        + ' · ' + (STOP_TEXT[r.stop_reason] || r.stop_reason) + ' · mean ΔE00 ' + r.avg_diff;
    m.className = 'modal-mode ' + r.mode;
    const pass = r.pct_good >= lim.pass_pct;
    const v = $('modalVerdict');
    v.textContent = pass
        ? (r.pct_good >= lim.excellent_pct ? '★ EXCELLENT — Outstanding color consistency' : '✓ FABRIC PASSED — Color consistency acceptable')
        : '✗ FABRIC FAILED — ' + r.not_same + ' of ' + r.total_readings + ' readings above the limit';
    v.className = 'modal-verdict ' + (pass ? 'pass' : 'fail');
    $('modalViewBtn').onclick = () => window.location = '/report/' + r.id;
    $('modalAgainBtn').onclick = () => { closeModal(); refreshSystem(); };
    $('reportModal').style.display = 'flex';
}
function closeModal() { $('reportModal').style.display = 'none'; }

// ── Graph ──────────────────────────────────────────────────────
function drawGraph() {
    if (!ctx || !canvas) return;
    const w = canvas.width, h = canvas.height;
    ctx.clearRect(0, 0, w, h);
    if (graphData.length < 2) return;
    ctx.fillStyle = '#f8f7f5'; ctx.fillRect(0, 0, w, h);
    const maxDiff = Math.max(graphThreshold * 2.5, ...graphData.map(p => p.diff)) * 1.1;
    const ty = h - (graphThreshold / maxDiff) * h;
    ctx.strokeStyle = 'rgba(239,68,68,0.35)'; ctx.setLineDash([5, 4]); ctx.lineWidth = 1.5;
    ctx.beginPath(); ctx.moveTo(0, ty); ctx.lineTo(w, ty); ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = 'rgba(239,68,68,0.55)'; ctx.font = '9px monospace';
    ctx.fillText('LIMIT ' + graphThreshold, w - 70, ty - 3);
    const step = w / (graphData.length - 1);
    ctx.beginPath(); ctx.lineWidth = 2; ctx.strokeStyle = '#2d5a3d'; ctx.lineJoin = 'round';
    graphData.forEach((p, i) => {
        const x = i * step, y = h - (p.diff / maxDiff) * h;
        i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
    ctx.stroke();
    graphData.forEach((p, i) => {
        const x = i * step, y = h - (p.diff / maxDiff) * h;
        ctx.beginPath(); ctx.arc(x, y, 2.5, 0, Math.PI * 2);
        ctx.fillStyle = p.status === 'same' ? '#22c55e' : '#ef4444'; ctx.fill();
    });
}

window.addEventListener('DOMContentLoaded', () => {
    sizeGraphCanvas();
    $('thresholdInput').addEventListener('input', () => { thresholdTouched = true; });
});