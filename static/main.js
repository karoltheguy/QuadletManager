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

// Track which server the user is currently working in.
// The stats chart only renders updates for this server.
// null = show whichever server reports first (auto-set on first update).
window.activeServerId = null;

// Cache the last-seen data per server so we can re-render immediately
// when the user switches servers without waiting for the next 5s poll.
const lastStatsPerServer = {};

// Called from quadlet_tree.html when the user clicks a file button.
window.setActiveServer = function(serverId) {
    serverId = parseInt(serverId, 10);
    if (window.activeServerId === serverId) return;
    window.activeServerId = serverId;
    // Re-render immediately with cached data for this server, if we have it.
    if (lastStatsPerServer[serverId]) {
        updateStats(lastStatsPerServer[serverId]);
    } else {
        // No data yet for this server – show a waiting message.
        var tableEl = document.getElementById('stats-table');
        if (tableEl) {
            tableEl.innerHTML = '<div class="p-3 text-gray-500 italic">Waiting for stats data...</div>';
        }
        if (statsChart) {
            statsChart.data.labels = [];
            statsChart.data.datasets[0].data = [];
            statsChart.data.datasets[1].data = [];
            statsChart.update();
        }
    }
};

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
            // Cache the latest data for this server so we can switch to it instantly.
            lastStatsPerServer[data.server_id] = data;

            // Auto-select the first server that reports in if nothing is selected yet.
            if (window.activeServerId === null) {
                window.activeServerId = data.server_id;
            }

            // Only update the chart for the currently active server.
            if (data.server_id !== window.activeServerId) return;

            // Clear any error state when we successfully receive stats
            var tableEl = document.getElementById('stats-table');
            if (tableEl) tableEl.classList.remove('stats-error');
            updateStats(data);
        } catch (err) {
            console.error('Stats parse error:', err);
        }
    });

    // Stats error events (when podman is unreachable/timed out)
    evtSource.addEventListener('stats_error', function(e) {
        try {
            var data = JSON.parse(e.data);
            var tableEl = document.getElementById('stats-table');
            if (tableEl) {
                tableEl.classList.add('stats-error');
                tableEl.innerHTML = '<div class="p-3 text-red-400">' +
                    '<div class="font-bold mb-1">⚠ Stats unavailable for ' +
                    (data.server_name || 'server') + '</div>' +
                    '<div class="text-xs text-gray-500">' + (data.error || 'Unknown error') + '</div>' +
                    '<div class="text-xs text-gray-600 mt-1">Will retry automatically…</div>' +
                    '</div>';
            }
        } catch (err) {
            console.error('Stats error parse error:', err);
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
    // Wait for the HTML body to be present or just delay SSE slightly if needed
    connectSSE();
});

// ── Real-time Logs WebSocket ─────────────────────────────
let currentLogSocket = null;

window.toggleLogs = function(serverId, unitName, scope) {
    let statusDiv = document.getElementById('systemd-status');
    let btn = document.getElementById('toggle-logs-btn');

    if (currentLogSocket) {
        // Stop current tail
        currentLogSocket.send("STOP");
        currentLogSocket.close();
        currentLogSocket = null;
        
        if (btn) btn.innerText = 'Tail Logs';
        if (btn) btn.classList.replace('bg-orange-700', 'bg-blue-700');
        if (btn) btn.classList.replace('hover:bg-orange-600', 'hover:bg-blue-600');
        
        statusDiv.innerHTML += '\n--- Stopped log stream. Re-fetch status to view current. ---\n';
        return;
    }

    statusDiv.innerHTML = 'Connecting to log stream...\n';
    
    if (btn) btn.innerText = 'Stop Logs';
    if (btn) btn.classList.replace('bg-blue-700', 'bg-orange-700');
    if (btn) btn.classList.replace('hover:bg-blue-600', 'hover:bg-orange-600');

    const wsUrl = (window.location.protocol === 'https:' ? 'wss://' : 'ws://') + window.location.host + '/ws/logs/' + serverId + '/' + unitName + '?scope=' + scope;
    currentLogSocket = new WebSocket(wsUrl);

    currentLogSocket.onmessage = function(event) {
        // Append text (escaping HTML safely if needed, but innerText might be safer except it removes formatting)
        // Journalctl logs are relatively safe but let's just create a text node or use innerHTML with simple escape if we cared. 
        // For now simple append.
        statusDiv.appendChild(document.createTextNode(event.data));
        statusDiv.scrollTop = statusDiv.scrollHeight;
    };

    currentLogSocket.onclose = function(e) {
        if (currentLogSocket) {
            statusDiv.innerHTML += '\n--- Log Stream Disconnected ---\n';
            currentLogSocket = null;
            if (btn) btn.innerText = 'Tail Logs';
            if (btn) btn.classList.replace('bg-orange-700', 'bg-blue-700');
            if (btn) btn.classList.replace('hover:bg-orange-600', 'hover:bg-blue-600');
        }
    };
    
    currentLogSocket.onerror = function(err) {
        console.error('WebSocket Error:', err);
        statusDiv.innerHTML += '\n--- Error connecting to Log Stream ---\n';
    };
};
