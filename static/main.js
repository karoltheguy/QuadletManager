// ── Monaco Editor Configuration ──────────────────────────
require.config({ paths: { 'vs': 'https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.45.0/min/vs' }});

// Ensure Monaco layout handles window sizing
window.addEventListener('resize', function() {
    if (window.editor) {
        window.editor.layout();
    }
});


// ── Stats Chart ──────────────────────────────────────────
let statsChart = null;

function initStatsChart() {
    const ctx = document.getElementById('stats-chart');
    if (!ctx) return;

    statsChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: [],
            datasets: [
                {
                    label: 'CPU %',
                    data: [],
                    backgroundColor: 'rgba(99, 102, 241, 0.6)',
                    borderColor: 'rgba(99, 102, 241, 1)',
                    borderWidth: 1,
                    borderRadius: 3
                },
                {
                    label: 'Memory %',
                    data: [],
                    backgroundColor: 'rgba(236, 72, 153, 0.6)',
                    borderColor: 'rgba(236, 72, 153, 1)',
                    borderWidth: 1,
                    borderRadius: 3
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,   // Disable for frequent (5s) updates
            scales: {
                y: {
                    beginAtZero: true,
                    max: 100,
                    ticks: {
                        color: '#9ca3af',
                        font: { size: 10 },
                        callback: function(value) { return value + '%'; }
                    },
                    grid: { color: 'rgba(75, 85, 99, 0.3)' }
                },
                x: {
                    ticks: {
                        color: '#9ca3af',
                        font: { size: 10 },
                        maxRotation: 45,
                        minRotation: 0
                    },
                    grid: { display: false }
                }
            },
            plugins: {
                legend: {
                    labels: {
                        color: '#d1d5db',
                        font: { size: 11 },
                        boxWidth: 12,
                        padding: 8
                    }
                },
                tooltip: {
                    backgroundColor: 'rgba(17, 24, 39, 0.9)',
                    titleColor: '#f3f4f6',
                    bodyColor: '#d1d5db',
                    borderColor: 'rgba(75, 85, 99, 0.5)',
                    borderWidth: 1,
                    cornerRadius: 6,
                    padding: 8
                }
            }
        }
    });
}

function parsePercent(val) {
    if (typeof val === 'string') {
        return parseFloat(val.replace('%', '')) || 0;
    }
    return parseFloat(val) || 0;
}

function updateStats(data) {
    const containers = data.containers || [];

    // ── Update Chart ──
    if (statsChart) {
        statsChart.data.labels = containers.map(function(c) { return c.name; });
        statsChart.data.datasets[0].data = containers.map(function(c) { return parsePercent(c.cpu); });
        statsChart.data.datasets[1].data = containers.map(function(c) { return parsePercent(c.mem); });
        statsChart.update();
    }

    // ── Update Stats Table ──
    var tableEl = document.getElementById('stats-table');
    if (!tableEl) return;

    if (containers.length === 0) {
        tableEl.innerHTML = '<div class="p-3 text-gray-500 italic">No containers running on ' +
            (data.server_name || 'server') + '</div>';
        return;
    }

    var html = '<table class="w-full">';
    html += '<thead><tr class="text-gray-500 border-b border-gray-700">';
    html += '<th class="text-left p-2">Container</th>';
    html += '<th class="p-2 text-right">CPU</th>';
    html += '<th class="p-2 text-right">MEM</th>';
    html += '<th class="p-2 text-right">NET I/O</th>';
    html += '<th class="p-2 text-right">PIDs</th>';
    html += '</tr></thead><tbody>';

    containers.forEach(function(c) {
        html += '<tr class="border-b border-gray-800 hover:bg-gray-900">';
        html += '<td class="text-left p-2 text-indigo-400 font-semibold">' + c.name + '</td>';
        html += '<td class="p-2 text-right">' + c.cpu + '</td>';
        html += '<td class="p-2 text-right">' + c.mem + '</td>';
        html += '<td class="p-2 text-right text-gray-400">' + c.net_io + '</td>';
        html += '<td class="p-2 text-right text-gray-400">' + c.pids + '</td>';
        html += '</tr>';
    });

    html += '</tbody></table>';
    html += '<div class="px-2 py-1 text-gray-600 text-right">' + (data.server_name || '') + '</div>';
    tableEl.innerHTML = html;
}


// ── SSE Connection ───────────────────────────────────────
function connectSSE() {
    var evtSource = new EventSource('/api/events');

    // Stats updates (every 5s from stats_engine)
    evtSource.addEventListener('stats_update', function(e) {
        try {
            var data = JSON.parse(e.data);
            updateStats(data);
        } catch (err) {
            console.error('Stats parse error:', err);
        }
    });

    // File change notifications (from sync_engine)
    evtSource.addEventListener('file_changed', function(e) {
        try {
            var data = JSON.parse(e.data);
            var toast = document.getElementById('status-toast');
            if (toast) {
                toast.innerHTML = '<div class="bg-yellow-600 p-2 rounded text-sm font-bold toast-enter">' +
                    '⚠ ' + data.message + ' (' + data.file_path + ')</div>';
                // Auto-dismiss after 8 seconds
                setTimeout(function() {
                    if (toast.querySelector('.toast-enter')) {
                        toast.innerHTML = '';
                    }
                }, 8000);
            }
        } catch (err) {
            console.error('File changed parse error:', err);
        }
    });

    evtSource.onerror = function() {
        console.warn('SSE connection lost, reconnecting in 3s...');
        evtSource.close();
        setTimeout(connectSSE, 3000);
    };
}


// ── Initialize on DOM Ready ──────────────────────────────
document.addEventListener('DOMContentLoaded', function() {
    initStatsChart();
    connectSSE();
});
