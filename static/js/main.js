// ── Shared helpers for every page ─────────────────────────────
function esc(s) {
    return String(s === undefined || s === null ? '' : s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function toast(msg, kind) {
    const t = document.getElementById('toast');
    if (!t || !msg) return;
    t.textContent = msg;
    t.className = 'toast show ' + (kind || '');
    clearTimeout(toast._h);
    toast._h = setTimeout(() => { t.className = 'toast'; }, 4200);
}

function postJSON(url, body) {
    return fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body || {})
    }).then(r => r.json());
}

// ── Test history (sidebar) ─────────────────────────────────────
function loadHistory() {
    fetch('/reports').then(r => r.json()).then(reports => {
        const list = document.getElementById('historyList');
        if (!list) return;
        if (!reports.length) { list.innerHTML = '<div class="hist-loading">No tests yet</div>'; return; }
        list.innerHTML = reports.map(r => {
            const cls = r.pct_good >= 90 ? 'e' : r.pct_good >= 80 ? 'p' : 'f';
            const lbl = r.pct_good >= 90 ? 'Excellent' : r.pct_good >= 80 ? 'Good' : 'Fail';
            let tag = '';
            if (!r.version) tag = '<span class="hi-tag legacy">v1</span>';
            else if (r.mode !== 'measurement') tag = '<span class="hi-tag demo">DEMO</span>';
            return `<div class="hi" onclick="window.location='/report/${r.id}'">
                <button class="hi-del" onclick="delReport(${r.id},event)" title="Delete">✕</button>
                <div class="hi-name">${esc(r.fabric_name)}</div>
                <div class="hi-date">${esc((r.date || '').substring(0, 16))}</div>
                <span class="hi-badge ${cls}">${r.pct_good}% ${lbl}</span>${tag}
            </div>`;
        }).join('');
    }).catch(() => {});
}

function delReport(id, e) {
    e.stopPropagation();
    if (!confirm("Delete this report?")) return;
    fetch("/reports/" + id, { method: "DELETE" }).then(() => loadHistory());
}

// ── Live status polling (Check Color + Setup pages) ────────────
const FCV = { status: null, listeners: [], camKey: '', lastMsg: '', offline: false };
function onStatus(fn) { FCV.listeners.push(fn); }

function pollStatus() {
    fetch('/status').then(r => r.json()).then(s => {
        FCV.status = s;
        FCV.offline = false;
        renderModePill(s);
        renderCameraSelect(s);
        renderReadiness(s);
        if (s.message && s.message !== FCV.lastMsg) toast(s.message);
        FCV.lastMsg = s.message;
        FCV.listeners.forEach(fn => { try { fn(s); } catch (err) { console.error(err); } });
    }).catch(() => {
        if (!FCV.offline) toast('Lost connection to the app server.', 'err');
        FCV.offline = true;
    }).finally(() => setTimeout(pollStatus, 350));
}

function renderModePill(s) {
    const pill = document.getElementById('modePill');
    const txt = document.getElementById('modeText');
    if (!pill) return;
    if (!s.camera) {
        pill.className = 'mode-pill none';
        txt.textContent = 'No camera';
    } else if (s.mode === 'measurement') {
        pill.className = 'mode-pill measurement';
        txt.textContent = 'MEASUREMENT MODE · ' + s.camera.name;
    } else {
        pill.className = 'mode-pill demo';
        txt.textContent = 'DEMO MODE · ' + s.camera.name;
    }
    const banner = document.getElementById('demoBanner');
    if (banner) banner.style.display = (s.mode === 'demo') ? 'block' : 'none';
}

function renderCameraSelect(s) {
    const sel = document.getElementById('cameraSelect');
    if (!sel) return;
    const key = JSON.stringify([s.cameras, s.camera_choice, s.camera && s.camera.name]);
    if (key === FCV.camKey || document.activeElement === sel) return;
    FCV.camKey = key;
    const cur = s.camera ? s.camera.name : '';
    let html = `<option value="auto">Auto (prefer USB camera)</option>`;
    (s.cameras || []).forEach(c => {
        const tag = c.kind === 'measurement' ? 'USB' : 'demo';
        html += `<option value="${esc(c.name)}">${esc(c.name)} (${tag})</option>`;
    });
    sel.innerHTML = html;
    sel.value = s.camera_choice || 'auto';
}

function selectCamera(name) {
    postJSON('/cameras/select', { name }).then(d => {
        if (!d.ok) toast(d.message, 'err');
        FCV.camKey = '';
    });
}

function rescanCameras() {
    postJSON('/cameras/rescan').then(() => toast('Looking for cameras…'));
}

function renderReadiness(s) {
    const checks = s.checks || [];
    const byKey = {};
    checks.forEach(c => { byKey[c.key] = c; });
    ['camera', 'dark', 'bright', 'stable', 'even'].forEach(k => {
        const el = document.getElementById('ld_' + k);
        if (!el) return;
        const c = byKey[k];
        el.className = 'ld ' + (!c ? 'dim' : c.ok ? 'grn' : 'red');
        if (c) el.title = c.label + ': ' + c.value;
    });
    const badge = document.getElementById('lightBadge');
    const txt = document.getElementById('lightTxt');
    const group = document.getElementById('readiness');
    if (!badge) return;
    const failing = checks.filter(c => !c.ok);
    const demoOk = s.mode === 'demo' && checks.slice(0, 3).every(c => c.ok);
    if (!checks.length) {
        badge.className = 'light-badge checking'; txt.textContent = 'NO CAMERA';
    } else if (!failing.length) {
        badge.className = 'light-badge ok'; txt.textContent = 'LIGHT OK';
    } else if (demoOk) {
        badge.className = 'light-badge warn'; txt.textContent = 'DEMO OK · ' + failing[0].msg;
    } else {
        badge.className = 'light-badge low'; txt.textContent = failing[0].msg;
    }
    if (group) group.title = checks.map(c => (c.ok ? '✓ ' : '✗ ') + c.label + ' — ' + c.value).join('\n');
}

window.addEventListener('DOMContentLoaded', () => {
    loadHistory();
    const live = document.querySelector('[data-live]');
    if (live) {
        const feed = document.getElementById('liveFeed');
        if (feed) feed.src = '/stream?view=' + live.dataset.live + '&t=' + Date.now();
        pollStatus();
    }
});