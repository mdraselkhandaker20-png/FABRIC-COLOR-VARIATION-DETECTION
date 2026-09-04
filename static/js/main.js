function loadHistory() {
    fetch('/reports').then(r => r.json()).then(reports => {
        const list = document.getElementById('historyList');
        if (!list) return;
        if (!reports.length) { list.innerHTML = '<div class="hist-loading">No tests yet</div>'; return; }
        list.innerHTML = reports.map(r => {
            let cls = r.pct_good >= 90 ? 'e' : r.pct_good >= 80 ? 'p' : 'f';
            let lbl = r.pct_good >= 90 ? 'Excellent' : r.pct_good >= 80 ? 'Good' : 'Fail';
            return `<div class="hi">
                <span onclick="window.location='/report/${r.id}'" style="display:block;cursor:pointer;">
                    <div class="hi-name">${r.fabric_name}</div>
                    <div class="hi-date">${(r.date||'').substring(0,16)}</div>
                    <span class="hi-badge ${cls}">${r.pct_good}% ${lbl}</span>
                </span>
                <button class="hi-del" onclick="delReport(${r.id},event)">✕</button>
            </div>`;
        }).join('');
    }).catch(() => {});
}

function delReport(id, e) {
    e.stopPropagation();
    if (!confirm("Delete this report?")) return;
    fetch("/reports/" + id, { method: "DELETE" })
        .then(() => loadHistory());
}

window.addEventListener('DOMContentLoaded', loadHistory);