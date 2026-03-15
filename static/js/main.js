/* SportEquity – main.js
   Global utilities, chart helpers, UI enhancements
*/

// ─── Set today's date on all date inputs that have no value ──────────────────
document.addEventListener('DOMContentLoaded', function () {
    var today = new Date().toISOString().split('T')[0];
    document.querySelectorAll('input[type="date"]').forEach(function (el) {
        if (!el.value) el.value = today;
    });

    // Auto-dismiss Bootstrap alerts after 5 s
    document.querySelectorAll('.alert-dismissible').forEach(function (el) {
        setTimeout(function () {
            var bsAlert = bootstrap.Alert.getOrCreateInstance(el);
            if (bsAlert) bsAlert.close();
        }, 5000);
    });

    // Initialize Bootstrap tooltips
    document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(function (el) {
        new bootstrap.Tooltip(el);
    });

    // Training intensity range → live badge update
    var range = document.getElementById('intensityRange');
    var badge = document.getElementById('intensityValue');
    if (range && badge) {
        range.addEventListener('input', function () {
            badge.textContent = range.value;
            badge.className = 'badge ' + (
                range.value >= 80 ? 'bg-danger' :
                range.value >= 60 ? 'bg-warning text-dark' :
                'bg-success'
            );
        });
        // trigger once on load
        range.dispatchEvent(new Event('input'));
    }
});

// ─── Chart.js global dark-friendly defaults ──────────────────────────────────
if (typeof Chart !== 'undefined') {
    Chart.defaults.font.family = "'Segoe UI', Tahoma, Geneva, Verdana, sans-serif";
    Chart.defaults.font.size   = 12;
    Chart.defaults.plugins.legend.labels.padding = 16;
}

// ─── Utility: create a standard line chart ───────────────────────────────────
function makeLineChart(ctxId, labels, datasets, yMax) {
    var el = document.getElementById(ctxId);
    if (!el) return null;
    return new Chart(el.getContext('2d'), {
        type: 'line',
        data: { labels: labels, datasets: datasets },
        options: {
            responsive: true,
            interaction: { mode: 'index', intersect: false },
            plugins: { legend: { display: datasets.length > 1 } },
            scales: {
                x: { grid: { color: 'rgba(0,0,0,0.05)' } },
                y: {
                    beginAtZero: true,
                    max: yMax || undefined,
                    grid: { color: 'rgba(0,0,0,0.05)' }
                }
            }
        }
    });
}

// ─── Utility: create a standard bar chart ────────────────────────────────────
function makeBarChart(ctxId, labels, datasets) {
    var el = document.getElementById(ctxId);
    if (!el) return null;
    return new Chart(el.getContext('2d'), {
        type: 'bar',
        data: { labels: labels, datasets: datasets },
        options: {
            responsive: true,
            plugins: { legend: { display: datasets.length > 1 } },
            scales: {
                x: { grid: { display: false } },
                y: { beginAtZero: true }
            }
        }
    });
}

// ─── Sport-score ring animation ───────────────────────────────────────────────
function animateScore(el, target) {
    if (!el) return;
    var current = 0;
    var step = target / 40;
    var timer = setInterval(function () {
        current = Math.min(current + step, target);
        el.textContent = Math.round(current);
        if (current >= target) clearInterval(timer);
    }, 25);
}

// ─── Generic API helper ───────────────────────────────────────────────────────
async function apiGet(url) {
    try {
        var res = await fetch(url);
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return await res.json();
    } catch (e) {
        console.error('API error [' + url + ']:', e);
        return null;
    }
}

async function apiPost(url, body) {
    try {
        var res = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });
        return await res.json();
    } catch (e) {
        console.error('API POST error [' + url + ']:', e);
        return null;
    }
}
