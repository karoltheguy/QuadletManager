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
            tableEl.innerHTML = '<div class="p-4 text-muted italic">Waiting for stats data...</div>';
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
        tableEl.innerHTML = '<div class="p-4 text-muted italic">No containers running on ' +
            (data.server_name || 'server') + '</div>';
        return;
    }

    var html = '<table class="w-full">';
    html += '<thead><tr class="text-muted border-b">';
    html += '<th class="text-left p-4">Container</th>';
    html += '<th class="p-4 text-right">CPU</th>';
    html += '<th class="p-4 text-right">MEM</th>';
    html += '<th class="p-4 text-right">NET I/O</th>';
    html += '<th class="p-4 text-right">PIDs</th>';
    html += '</tr></thead><tbody>';

    containers.forEach(function(c) {
        html += '<tr class="border-b">';
        html += '<td class="text-left p-4 text-accent font-semibold">' + c.name + '</td>';
        html += '<td class="p-4 text-right">' + c.cpu + '</td>';
        html += '<td class="p-4 text-right">' + c.mem + '</td>';
        html += '<td class="p-4 text-right text-muted">' + c.net_io + '</td>';
        html += '<td class="p-4 text-right text-muted">' + c.pids + '</td>';
        html += '</tr>';
    });

    html += '</tbody></table>';
    html += '<div class="p-4 text-muted text-right text-xs">' + (data.server_name || '') + '</div>';
    tableEl.innerHTML = html;
}


// ── SSE Connection ───────────────────────────────────────
function connectSSE() {
    var evtSource = new EventSource('/api/events');

    // Stats updates (every 5s from stats_engine)
    evtSource.addEventListener('stats_update', function(e) {
        try {
            var data = JSON.parse(e.data);
            // Mark that we have received at least one update
            _statsReceived = true;
            if (_statsWaitTimeout) { clearTimeout(_statsWaitTimeout); _statsWaitTimeout = null; }

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
                tableEl.innerHTML = '<div class="p-4 text-danger">' +
                    '<div class="font-bold mb-1">⚠ Stats unavailable for ' +
                    (data.server_name || 'server') + '</div>' +
                    '<div class="text-xs text-muted">' + (data.error || 'Unknown error') + '</div>' +
                    '<div class="text-xs text-muted mt-1">Will retry automatically…</div>' +
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
                toast.innerHTML = '<div class="toast-msg toast-warning toast-enter">' +
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
// Track whether we've received at least one stats update
let _statsReceived = false;
let _statsWaitTimeout = null;

window.switchTab = function(tabId) {
    document.body.className = 'view-' + tabId;
    document.querySelectorAll('.nav-item').forEach(function(btn) {
        if (btn.innerText.toLowerCase() === tabId) {
            btn.classList.add('active');
        } else {
            btn.classList.remove('active');
        }
    });
    // Trigger resize for Monaco
    if (tabId === 'editor' && window.editor) {
        window.editor.layout();
    }
};

// ── Resizable Panel Handles ──────────────────────────────
function initResizableHandles() {
    var SIDEBAR_MIN = 180, SIDEBAR_MAX = 500;
    var INSPECTOR_MIN = 220, INSPECTOR_MAX = 600;

    function makeDraggable(handleEl, cssVar, storageKey, minPx, maxPx, getInitialPx) {
        if (!handleEl) return;

        handleEl.addEventListener('mousedown', function(e) {
            e.preventDefault();
            var startX = e.clientX;
            var startPx = getInitialPx();

            handleEl.classList.add('dragging');
            document.body.classList.add('is-resizing');

            function onMove(e) {
                var delta = e.clientX - startX;
                var newPx = Math.min(maxPx, Math.max(minPx, startPx + delta));
                document.documentElement.style.setProperty(cssVar, newPx + 'px');
            }

            function onUp() {
                handleEl.classList.remove('dragging');
                document.body.classList.remove('is-resizing');
                document.removeEventListener('mousemove', onMove);
                document.removeEventListener('mouseup', onUp);

                // Persist width to localStorage
                var finalPx = getComputedStyle(document.documentElement)
                    .getPropertyValue(cssVar).trim();
                localStorage.setItem(storageKey, finalPx);

                // Re-layout Monaco if open
                if (window.editor) window.editor.layout();
            }

            document.addEventListener('mousemove', onMove);
            document.addEventListener('mouseup', onUp);
        });
    }

    // Left handle: controls sidebar width
    makeDraggable(
        document.getElementById('resize-handle-left'),
        '--sidebar-width',
        'qm-sidebar-width',
        SIDEBAR_MIN, SIDEBAR_MAX,
        function() {
            var sidebar = document.getElementById('navigator');
            return sidebar ? sidebar.getBoundingClientRect().width : 300;
        }
    );

    // Right handle: controls inspector width (drag left = bigger inspector)
    var rightHandle = document.getElementById('resize-handle-right');
    if (rightHandle) {
        rightHandle.addEventListener('mousedown', function(e) {
            e.preventDefault();
            var startX = e.clientX;
            var inspector = document.getElementById('inspector');
            var startPx = inspector ? inspector.getBoundingClientRect().width : 320;

            rightHandle.classList.add('dragging');
            document.body.classList.add('is-resizing');

            function onMove(e) {
                var delta = startX - e.clientX;   // dragging left widens inspector
                var newPx = Math.min(INSPECTOR_MAX, Math.max(INSPECTOR_MIN, startPx + delta));
                document.documentElement.style.setProperty('--inspector-width', newPx + 'px');
            }

            function onUp() {
                rightHandle.classList.remove('dragging');
                document.body.classList.remove('is-resizing');
                document.removeEventListener('mousemove', onMove);
                document.removeEventListener('mouseup', onUp);
                var finalPx = getComputedStyle(document.documentElement)
                    .getPropertyValue('--inspector-width').trim();
                localStorage.setItem('qm-inspector-width', finalPx);
                if (window.editor) window.editor.layout();
            }

            document.addEventListener('mousemove', onMove);
            document.addEventListener('mouseup', onUp);
        });
    }
}


document.addEventListener('DOMContentLoaded', function() {
    // Restore persisted panel widths before first paint
    (function restorePanelWidths() {
        var saved = { sidebar: localStorage.getItem('qm-sidebar-width'), inspector: localStorage.getItem('qm-inspector-width') };
        if (saved.sidebar)   document.documentElement.style.setProperty('--sidebar-width',   saved.sidebar);
        if (saved.inspector) document.documentElement.style.setProperty('--inspector-width', saved.inspector);
    })();

    window.switchTab('dashboard');
    initStatsChart();
    connectSSE();
    initResizableHandles();

    // If no stats arrive within 15s of page load, update the placeholder
    // so the user isn't left staring at "Waiting for stats data..." forever.
    _statsWaitTimeout = setTimeout(function() {
        if (!_statsReceived) {
            var tableEl = document.getElementById('stats-table');
            if (tableEl) {
                tableEl.innerHTML = '<div class="p-4 text-warning italic">' +
                    'No stats received yet — verify server connectivity.</div>';
            }
        }
    }, 15000);
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
        if (btn) btn.classList.replace('btn-warning', 'btn-primary');
        
        statusDiv.innerHTML += '\n--- Stopped log stream. Re-fetch status to view current. ---\n';
        return;
    }

    statusDiv.innerHTML = 'Connecting to log stream...\n';
    
    if (btn) btn.innerText = 'Stop Logs';
    if (btn) btn.classList.replace('btn-primary', 'btn-warning');

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
            if (btn) btn.classList.replace('btn-warning', 'btn-primary');
        }
    };
    
    currentLogSocket.onerror = function(err) {
        console.error('WebSocket Error:', err);
        statusDiv.innerHTML += '\n--- Error connecting to Log Stream ---\n';
    };
};
