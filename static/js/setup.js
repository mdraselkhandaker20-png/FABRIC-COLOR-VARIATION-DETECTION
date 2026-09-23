// ── Setup & Calibration page ───────────────────────────────────
function $(id) { return document.getElementById(id); }
let lastBaselineAt = null;
let activeSetupId = null;

function fmt(v, suffix) { return (v === null || v === undefined || v === '') ? '—' : v + (suffix || ''); }

onStatus(s => {
    // Live check list
    const list = $('checkList');
    list.innerHTML = (s.checks || []).map(c => `
        <div class="ck ${c.ok ? 'ok' : 'bad'}">
            <span class="ck-dot"></span>
            <span class="ck-lbl">${esc(c.label)}</span>
            <span class="ck-val">${esc(c.value)}</span>
        </div>`).join('') || '<div class="muted">Waiting for camera…</div>';

    // Camera settings
    const cam = s.camera;
    if (cam) {
        const st = cam.settings || {};
        const locked = cam.settling ? 'locking…' : (st.locked ? 'locked' : 'automatic');
        let extra = '';
        if (st.exposure !== undefined && st.exposure !== null) extra += ` · exposure ${st.exposure}`;
        if (st.wb_temperature) extra += ` · WB ${st.wb_temperature} K`;
        $('camInfo').innerHTML = `<strong>${esc(cam.name)}</strong><br>Exposure &amp; white balance: ${locked}${esc(extra)}`;
    } else {
        $('camInfo').textContent = 'No camera connected.';
    }

    const sb = $('stateBanner');
    if (cam && cam.settling) { sb.textContent = 'Locking exposure and white balance…'; sb.style.display = 'block'; }
    else if (s.baseline) { sb.textContent = 'Measuring baseline — keep everything still… ' + Math.round(s.baseline.progress * 100) + '%'; sb.style.display = 'block'; }
    else sb.style.display = 'none';

    // Baseline progress
    const running = !!s.baseline;
    $('baselineProgress').style.display = running ? 'block' : 'none';
    if (running) $('baselineFill').style.width = Math.round(s.baseline.progress * 100) + '%';
    $('btnBaseline').disabled = running || !!s.test;

    // Baseline result
    const b = s.baseline_result;
    if (b && b.measured_at !== lastBaselineAt) {
        lastBaselineAt = b.measured_at;
        renderBaseline(b);
    }
    $('btnSaveSetup').disabled = !b || running;
    $('saveHint').textContent = !b ? 'Measure the baseline first.'
        : (b.setup_ok ? 'All checks passed — this setup is good for measurements.'
            : (b.mode !== 'measurement' ? 'Measured with the demo camera — saved setups from it are for practice only.'
                : 'Some checks failed — you can still save it as a trial for your records.'));
});

function renderBaseline(b) {
    const c = b.checks;
    const row = (ok, label, val) => `<div class="ck ${ok ? 'ok' : 'bad'}"><span class="ck-dot"></span><span class="ck-lbl">${label}</span><span class="ck-val">${val}</span></div>`;
    $('baselineResult').innerHTML = `
        <div class="br-head ${b.setup_ok ? 'ok' : 'bad'}">
            <span class="ref-chip" style="background:${b.reference_hex}"></span>
            ${b.setup_ok ? 'SETUP OK' : 'SETUP NOT OK'}
            <span class="muted">${b.frames} frames · ${b.duration_s} s · ${esc(b.camera_name)}</span>
        </div>
        ${row(c.camera_locked, 'Exposure/WB locked', c.camera_locked ? 'yes' : 'no')}
        ${row(c.exposure_ok, 'Exposure', b.dark_clip_pct + '% black · ' + b.bright_clip_pct + '% clipped · L* ' + b.mean_L)}
        ${row(c.stable_ok, 'Noise (P95)', 'ΔE00 ' + b.noise_p95_de00 + ' (mean ' + b.noise_mean_de00 + ' ± ' + b.noise_std_de00 + ')')}
        ${row(c.even_ok, 'Uniformity (max)', 'ΔE00 ' + b.uniformity_max_de00)}
        <div class="br-foot">Suggested ΔE00 limit: <strong>${b.suggested_threshold_de00}</strong>
            <span class="muted">(noise mean + 3 SD — smaller differences cannot be told apart from camera noise)</span></div>`;
}

function startBaseline() {
    postJSON('/baseline/start', { duration: parseFloat($('baselineDur').value) || 10 }).then(d => {
        if (!d.ok) toast(d.message, 'err');
    });
}

function relockCamera() {
    postJSON('/camera/relock').then(d => toast(d.ok ? 'Re-locking exposure…' : d.message, d.ok ? '' : 'err'));
}

function saveSetup() {
    postJSON('/setups', {
        name: $('spName').value,
        camera_distance_cm: $('spCamDist').value,
        light_distance_cm: $('spLightDist').value,
        light_angle_deg: $('spAngle').value,
        light_source: $('spLight').value,
        reference_fabric: $('spFabric').value,
        notes: $('spNotes').value,
        activate: true,
    }).then(d => {
        if (!d.ok) { toast(d.message, 'err'); return; }
        toast('Saved "' + d.setup.name + '" and made it the active setup.');
        loadSetups();
    });
}

function loadSetups() {
    fetch('/setups').then(r => r.json()).then(d => {
        activeSetupId = d.active_setup_id;
        const rows = d.setups.map(s => {
            const b = s.baseline || {};
            const active = s.id === activeSetupId;
            return `<tr class="${active ? 'active' : ''}">
                <td><strong>${esc(s.name)}</strong><div class="muted small">${esc(s.created)}</div></td>
                <td>${esc(b.camera_name || '')}${b.mode !== 'measurement' ? ' <span class="tag demo">demo</span>' : ''}</td>
                <td>${fmt(s.camera_distance_cm)}</td>
                <td>${fmt(s.light_distance_cm)}</td>
                <td>${fmt(s.light_angle_deg, '°')}</td>
                <td>${fmt(b.noise_mean_de00)} ± ${fmt(b.noise_std_de00)}</td>
                <td>${fmt(b.uniformity_max_de00)}</td>
                <td>${fmt(b.suggested_threshold_de00)}</td>
                <td>${s.setup_ok ? '<span class="tag ok">OK</span>' : '<span class="tag warn">not OK</span>'}</td>
                <td class="row-actions">
                    ${active ? '<span class="tag active">active</span>' : `<button class="btn-mini" onclick="activateSetup(${s.id})">Use</button>`}
                    <button class="btn-mini del" onclick="deleteSetup(${s.id})" title="Delete">✕</button>
                </td></tr>`;
        }).join('');
        $('setupRows').innerHTML = rows || '<tr><td colspan="10" class="muted">No setups saved yet.</td></tr>';
    });
}

function activateSetup(id) {
    postJSON('/setups/' + id + '/activate').then(() => { toast('Active setup changed.'); loadSetups(); });
}

function deleteSetup(id) {
    if (!confirm('Delete this setup trial?')) return;
    fetch('/setups/' + id, { method: 'DELETE' }).then(() => loadSetups());
}

window.addEventListener('DOMContentLoaded', loadSetups);