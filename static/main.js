// ── Monaco Editor Configuration ──────────────────────────
require.config({ paths: { 'vs': 'https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.45.0/min/vs' }});

// Ensure Monaco layout handles window sizing
window.addEventListener('resize', function() {
    if (window.editor) {
        window.editor.layout();
    }
});


// ── Notifications Configuration ──────────────────────────
if ('Notification' in window && Notification.permission !== 'granted' && Notification.permission !== 'denied') {
    Notification.requestPermission();
}

const manualStops = new Set(); // tracks serverId:stem that we intentionally stopped
const pendingStarts = {}; // tracks stems waiting for active status

function sendNotification(title, body) {
    if ('Notification' in window && Notification.permission === 'granted') {
        new Notification(title, { body: body });
    }
}

function checkQuadletStartup(watchId, stem, serverId, unitName, scope) {
    delete pendingStarts[watchId];
    
    var running = runningContainersBySid[serverId] || new Set();
    var isRunning = false;
    running.forEach(function(name) {
        if (name.indexOf(stem) !== -1 || stem.indexOf(name) !== -1) {
            isRunning = true;
        }
    });
    
    if (isRunning) {
        sendNotification('Success', 'Quadlet ' + stem + ' started successfully');
    } else {
        // Fetch status HTML to extract the error message
        var statusUrl = '/api/systemctl/status/' + serverId + '?unit=' + encodeURIComponent(unitName) + '&scope=' + encodeURIComponent(scope);
        fetch(statusUrl)
            .then(function(res) { return res.text(); })
            .then(function(html) {
                var temp = document.createElement('div');
                temp.innerHTML = html;
                var lines = temp.textContent.split('\n');
                var errorMsg = 'Unknown error';
                for (var i = 0; i < lines.length; i++) {
                    var line = lines[i].trim();
                    if (line.indexOf('Failed') !== -1 || line.indexOf('failed with') !== -1 || line.indexOf('error') !== -1) {
                        errorMsg = line;
                        break;
                    }
                }
                sendNotification('Error', 'Quadlet ' + stem + ' failed with error ' + errorMsg);
            })
            .catch(function(err) {
                sendNotification('Error', 'Quadlet ' + stem + ' failed to start');
            });
    }
}

document.body.addEventListener('htmx:beforeRequest', function(evt) {
    var path = evt.detail.pathInfo.requestPath;
    var params = evt.detail.requestConfig.parameters || {};
    var unitName = '';
    var serverId = null;
    var scope = '';
    var action = '';
    
    if (path.indexOf('/api/systemctl/') !== -1) {
        var urlParts = path.split('?');
        serverId = parseInt(urlParts[0].split('/').pop(), 10);
        var searchParams = new URLSearchParams(urlParts[1] || window.location.search);
        unitName = params.unit || searchParams.get('unit') || '';
        scope = params.scope || searchParams.get('scope') || '';
        action = params.action || searchParams.get('action') || '';
    } else if (path.indexOf('/api/save') !== -1) {
        unitName = params.unit_name || '';
        serverId = parseInt(params.server_id, 10);
        scope = params.scope || '';
        action = 'restart'; // saving implies a restart
    }
    
    if (unitName && serverId) {
        var stem = unitName.replace('.service', '').toLowerCase();
        var watchId = serverId + ':' + stem;
        
        if (action === 'stop') {
            manualStops.add(watchId);
        } else if (action === 'start' || action === 'restart') {
            manualStops.delete(watchId);
            if (pendingStarts[watchId]) clearTimeout(pendingStarts[watchId].timer);
            pendingStarts[watchId] = {
                unit: unitName,
                serverId: serverId,
                scope: scope,
                timer: setTimeout(function() {
                    checkQuadletStartup(watchId, stem, serverId, unitName, scope);
                }, 5000)
            };
        }
    }
});


// ── Stats Chart ──────────────────────────────────────────
let statsChart = null;
let monitoringChart = null;
let healthHistoryChart = null;

const HISTORY_COLORS = [
    'rgba(99, 102, 241, 1)',
    'rgba(16, 185, 129, 1)',
    'rgba(236, 72, 153, 1)',
    'rgba(245, 158, 11, 1)',
    'rgba(6, 182, 212, 1)',
    'rgba(239, 68, 68, 1)',
    'rgba(139, 92, 246, 1)',
    'rgba(251, 146, 60, 1)',
];

// Track which server the user is currently working in.
// The stats chart only renders updates for this server.
// null = show whichever server reports first (auto-set on first update).
window.activeServerId = null;

// Cache the last-seen data per server so we can re-render immediately
// when the user switches servers without waiting for the next 5s poll.
const lastStatsPerServer = {};

// Per-server map of currently running container name stems.
// Key: serverId (int), Value: Set<string> of lowercase container name stems.
const runningContainersBySid = {};


// Called from quadlet_tree.html when the user clicks a file button.
window.setActiveServer = function(serverId) {
    serverId = parseInt(serverId, 10);
    if (window.activeServerId === serverId) return;
    window.activeServerId = serverId;
    // Re-render immediately with cached data for this server, if we have it.
    if (lastStatsPerServer[serverId]) {
        updateStats(lastStatsPerServer[serverId]);
        applyStatusDots(serverId);
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

/**
 * Update all status dots for a given server based on the cached
 * runningContainersBySid map.
 *
 * Quadlet filenames like "my-app.container" map to container name stems by
 * stripping the extension. Podman container names are compared
 * case-insensitively — podman often uses the stem directly as the container
 * name, though operators may prefix/suffix it. We do a "contains" check so
 * that "my-app" matches a running container named "systemd-my-app".
 *
 * @param {number} serverId
 */
function applyStatusDots(serverId) {
    var running = runningContainersBySid[serverId] || new Set();
    var serverStats = lastStatsPerServer[serverId];
    var containersByName = {};
    if (serverStats) {
        (serverStats.containers || []).forEach(function(c) {
            containersByName[(c.name || '').toLowerCase()] = c;
        });
    }

    var dots = document.querySelectorAll('.status-dot[data-server-id="' + serverId + '"]');
    dots.forEach(function(dot) {
        var stem = (dot.dataset.unitStem || '').toLowerCase();
        var isRunning = false;
        var matchedContainer = null;
        running.forEach(function(name) {
            if (name.indexOf(stem) !== -1 || stem.indexOf(name) !== -1) {
                isRunning = true;
                if (containersByName[name]) matchedContainer = containersByName[name];
            }
        });
        dot.classList.remove('dot-running', 'dot-stopped', 'dot-failed');
        if (isRunning) {
            dot.classList.add('dot-running');
            dot.title = matchedContainer
                ? 'Running — CPU: ' + matchedContainer.cpu + ' | MEM: ' + matchedContainer.mem
                : 'Running';
        } else {
            dot.classList.add('dot-stopped');
            dot.title = 'Stopped / not running';
        }
    });
}


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
      animation: false, // Disable for frequent (5s) updates
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

function initMonitoringChart() {
  const ctx = document.getElementById('monitoring-chart');
  if (!ctx) return;

  monitoringChart = new Chart(ctx, {
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
          borderRadius: 4
        },
        {
          label: 'Memory %',
          data: [],
          backgroundColor: 'rgba(236, 72, 153, 0.6)',
          borderColor: 'rgba(236, 72, 153, 1)',
          borderWidth: 1,
          borderRadius: 4
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      scales: {
        y: {
          beginAtZero: true,
          max: 100,
          ticks: {
            color: '#9ca3af',
            font: { size: 11 },
            callback: function(value) { return value + '%'; }
          },
          grid: { color: 'rgba(75, 85, 99, 0.3)' }
        },
        x: {
          ticks: {
            color: '#9ca3af',
            font: { size: 11 },
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
            font: { size: 12 },
            boxWidth: 14,
            padding: 10
          }
        },
        tooltip: {
          backgroundColor: 'rgba(17, 24, 39, 0.9)',
          titleColor: '#f3f4f6',
          bodyColor: '#d1d5db',
          borderColor: 'rgba(75, 85, 99, 0.5)',
          borderWidth: 1,
          cornerRadius: 6,
          padding: 10
        }
      }
    }
  });
}

function initHealthHistoryChart() {
  const ctx = document.getElementById('health-history-chart');
  if (!ctx) return;

  healthHistoryChart = new Chart(ctx, {
    type: 'line',
    data: { labels: [], datasets: [] },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      stepped: true,
      scales: {
        y: {
          beginAtZero: true,
          max: 1,
          ticks: {
            color: '#9ca3af',
            font: { size: 10 },
            stepSize: 1,
            callback: function(v) { return v === 1 ? 'Running' : 'Stopped'; }
          },
          grid: { color: 'rgba(75, 85, 99, 0.3)' }
        },
        x: {
          ticks: {
            color: '#9ca3af',
            font: { size: 10 },
            maxTicksLimit: 8,
            maxRotation: 0,
          },
          grid: { display: false }
        }
      },
      plugins: {
        legend: {
          labels: { color: '#d1d5db', font: { size: 11 }, boxWidth: 12, padding: 8 }
        },
        tooltip: {
          backgroundColor: 'rgba(17, 24, 39, 0.9)',
          titleColor: '#f3f4f6',
          bodyColor: '#d1d5db',
          borderColor: 'rgba(75, 85, 99, 0.5)',
          borderWidth: 1,
          cornerRadius: 6,
          padding: 8,
          callbacks: {
            label: function(ctx) {
              return ctx.dataset.label + ': ' + (ctx.parsed.y === 1 ? 'Running' : 'Stopped');
            }
          }
        }
      }
    }
  });
}

window._healthHistoryMinutes = 15;

window.loadHealthHistory = function(minutes, btnEl) {
  window._healthHistoryMinutes = minutes;

  // Update active button style
  if (btnEl) {
    document.querySelectorAll('.health-range-btn').forEach(function(b) { b.classList.remove('active'); });
    btnEl.classList.add('active');
  }

  var serverId = window.activeServerId;
  if (!serverId) return;

  fetch('/api/health/history/' + serverId + '?minutes=' + minutes)
    .then(function(r) { return r.json(); })
    .then(function(data) {
      var emptyEl = document.getElementById('health-history-empty');
      var wrapEl = document.getElementById('health-history-chart-wrap');

      if (!data || data.length === 0) {
        if (emptyEl) emptyEl.style.display = '';
        if (wrapEl) wrapEl.style.display = 'none';
        return;
      }
      if (emptyEl) emptyEl.style.display = 'none';
      if (wrapEl) wrapEl.style.display = '';

      if (!healthHistoryChart) return;

      // Build unified sorted timestamp labels from all containers
      var tsSet = new Set();
      data.forEach(function(c) { c.history.forEach(function(p) { tsSet.add(p.ts); }); });
      var tsSorted = Array.from(tsSet).sort(function(a, b) { return a - b; });

      var labels = tsSorted.map(function(ts) {
        var d = new Date(ts * 1000);
        return d.getHours().toString().padStart(2, '0') + ':' +
               d.getMinutes().toString().padStart(2, '0') + ':' +
               d.getSeconds().toString().padStart(2, '0');
      });

      var datasets = data.map(function(c, i) {
        var byTs = {};
        c.history.forEach(function(p) { byTs[p.ts] = p.is_running; });
        return {
          label: c.container_name,
          data: tsSorted.map(function(ts) { return byTs[ts] !== undefined ? byTs[ts] : null; }),
          borderColor: HISTORY_COLORS[i % HISTORY_COLORS.length],
          backgroundColor: HISTORY_COLORS[i % HISTORY_COLORS.length].replace('1)', '0.15)'),
          borderWidth: 2,
          pointRadius: 0,
          stepped: true,
          fill: true,
          spanGaps: false,
        };
      });

      healthHistoryChart.data.labels = labels;
      healthHistoryChart.data.datasets = datasets;
      healthHistoryChart.update();
    })
    .catch(function(err) { console.error('Health history fetch error:', err); });
};

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

      var oldSet = runningContainersBySid[data.server_id] || new Set();

      // Build / refresh the running-set for this server.
      var runningSet = new Set();
      (data.containers || []).forEach(function(c) {
        runningSet.add((c.name || '').toLowerCase());
      });
      runningContainersBySid[data.server_id] = runningSet;
      
      // Detect spontaneously stopped containers
      oldSet.forEach(function(oldName) {
          if (!runningSet.has(oldName)) {
              var wasManual = false;
              manualStops.forEach(function(manualKey) {
                  var parts = manualKey.split(':');
                  var mServerId = parseInt(parts[0], 10);
                  var mStem = parts[1];
                  if (mServerId === data.server_id && (oldName.indexOf(mStem) !== -1 || mStem.indexOf(oldName) !== -1)) {
                      wasManual = true;
                  }
              });
              if (!wasManual) {
                  sendNotification('Alert', 'Quadlet container ' + oldName + ' stopped or failed unexpectedly');
              }
          }
      });

      // Update status dots for this server regardless of which server
      // is "active" in the inspector – every server's tree is visible.
      applyStatusDots(data.server_id);

      // Auto-select the first server that reports in if nothing is selected yet.
      if (window.activeServerId === null) {
        window.activeServerId = data.server_id;
      }

      // Update server selector with new data
      populateServerSelector();

      // Only update the chart for the currently active server.
      if (data.server_id !== window.activeServerId) return;

      // Clear any error state when we successfully receive stats
      var tableEl = document.getElementById('stats-table');
      if (tableEl) tableEl.classList.remove('stats-error');
      updateStats(data);
      
      // Also update monitoring view if it exists
      updateMonitoringView(data);
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
      // Also show error in monitoring table
      var monitoringTableEl = document.getElementById('monitoring-stats-table');
      if (monitoringTableEl) {
        monitoringTableEl.innerHTML = '<div class="p-4 text-danger">' +
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
  // Trigger resize for monitoring chart
  if (tabId === 'monitoring' && monitoringChart) {
    monitoringChart.resize();
    loadHealthHistory(window._healthHistoryMinutes || 15);
  }
};

// ── Monitoring Server Selector ────────────────────────────
window.selectMonitoringServer = function(serverId) {
  serverId = parseInt(serverId, 10);
  if (window.activeServerId === serverId) return;
  window.activeServerId = serverId;
  
  // Re-render with cached data for this server
  if (lastStatsPerServer[serverId]) {
    updateMonitoringView(lastStatsPerServer[serverId]);
    loadHealthHistory(window._healthHistoryMinutes || 15);
  } else {
    // No data yet – show waiting message
    var tableEl = document.getElementById('monitoring-stats-table');
    if (tableEl) {
      tableEl.innerHTML = '<div class="p-4 text-muted italic">Waiting for stats data...</div>';
    }
    if (monitoringChart) {
      monitoringChart.data.labels = [];
      monitoringChart.data.datasets[0].data = [];
      monitoringChart.data.datasets[1].data = [];
      monitoringChart.update();
    }
  }
};

function updateMonitoringView(data) {
  const containers = data.containers || [];
  
  // Update Monitoring Chart
  if (monitoringChart) {
    monitoringChart.data.labels = containers.map(function(c) { return c.name; });
    monitoringChart.data.datasets[0].data = containers.map(function(c) { return parsePercent(c.cpu); });
    monitoringChart.data.datasets[1].data = containers.map(function(c) { return parsePercent(c.mem); });
    monitoringChart.update();
  }
  
  // Update Monitoring Stats Table
  var tableEl = document.getElementById('monitoring-stats-table');
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

function populateServerSelector() {
  var select = document.getElementById('monitoring-server-select');
  if (!select) return;
  
  // Clear existing options except the placeholder
  select.innerHTML = '<option value="">Select a server...</option>';
  
  // Add servers from the cached stats data
  Object.keys(lastStatsPerServer).forEach(function(serverId) {
    var data = lastStatsPerServer[serverId];
    var option = document.createElement('option');
    option.value = serverId;
    option.textContent = data.server_name || ('Server ' + serverId);
    if (parseInt(serverId) === window.activeServerId) {
      option.selected = true;
    }
    select.appendChild(option);
  });
}

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
                if (statsChart) statsChart.resize();
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
                if (statsChart) statsChart.resize();
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
                if (statsChart) statsChart.resize();
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
                if (statsChart) statsChart.resize();
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
  if (saved.sidebar) document.documentElement.style.setProperty('--sidebar-width', saved.sidebar);
  if (saved.inspector) document.documentElement.style.setProperty('--inspector-width', saved.inspector);
})();

window.switchTab('dashboard');
initStatsChart();
initMonitoringChart();
initHealthHistoryChart();
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
    var monitoringTableEl = document.getElementById('monitoring-stats-table');
    if (monitoringTableEl) {
      monitoringTableEl.innerHTML = '<div class="p-4 text-warning italic">' +
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
