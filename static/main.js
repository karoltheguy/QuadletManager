// ── Theme Toggle ─────────────────────────────────────────
// No saved pref → follows OS via CSS @media (prefers-color-scheme).
// First click reads the currently-resolved theme and flips to the
// opposite, then persists to localStorage so the override sticks.
function toggleTheme() {
    var root = document.documentElement;
    var current = root.getAttribute('data-theme');
    if (!current) {
        current = window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
    }
    var next = current === 'light' ? 'dark' : 'light';
    root.setAttribute('data-theme', next);
    try { localStorage.setItem('qm-theme', next); } catch (e) {}
    applyChartTheme();
}

// Mark the clicked quadlet tree button as selected (inset state).
// Called inline from partials/quadlet_tree.html onclick.
function setSelectedQuadletBtn(el) {
    document.querySelectorAll('.quadlet-tree-btn.is-selected')
        .forEach(function (b) { b.classList.remove('is-selected'); });
    if (el) el.classList.add('is-selected');
}

// Re-apply the .is-selected class after htmx swaps the quadlet tree.
// Source of truth is window._selectedContainerStem / _selectedContainerServerId,
// set by selectContainerStem() — the editor pane is the real state, we're
// just re-syncing the sidebar visual to match.
function reapplyQuadletSelection() {
    var stem = window._selectedContainerStem;
    var sid  = window._selectedContainerServerId;
    if (!stem || !sid) return;
    var btn = document.querySelector(
        '.quadlet-tree-btn[data-stem="' + stem + '"][data-server-id="' + sid + '"]'
    );
    if (btn) btn.classList.add('is-selected');
}
document.body.addEventListener('htmx:afterSwap', function (e) {
    // Fire on any swap that could have replaced a tree button. Cheap — a
    // single querySelector with no match is negligible.
    if (e.target && e.target.querySelector && e.target.querySelector('.quadlet-tree-btn')) {
        reapplyQuadletSelection();
    }
});

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

// HTML-escape utility for safe innerHTML insertion of API/user-controlled data.
function escapeHtml(value) {
    if (value === null || value === undefined) return '';
    var map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' };
    return String(value).replace(/[&<>"']/g, function(m) { return map[m]; });
}

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
    'rgba(20, 184, 166, 1)',   // teal  — matches brand-primary
    'rgba(16, 185, 129, 1)',   // emerald
    'rgba(244, 63, 94, 1)',    // rose
    'rgba(245, 158, 11, 1)',   // amber
    'rgba(6, 182, 212, 1)',    // cyan
    'rgba(239, 68, 68, 1)',    // red
    'rgba(168, 85, 247, 1)',   // violet
    'rgba(251, 146, 60, 1)',   // orange
];

function hexToRgba(hex, alpha) {
    var r = parseInt(hex.slice(1, 3), 16);
    var g = parseInt(hex.slice(3, 5), 16);
    var b = parseInt(hex.slice(5, 7), 16);
    return 'rgba(' + r + ', ' + g + ', ' + b + ', ' + alpha + ')';
}

function getChartTheme() {
    var s = getComputedStyle(document.documentElement);
    var get = function(v) { return s.getPropertyValue(v).trim(); };
    var brand = get('--brand-primary');
    var border = get('--border-color');
    return {
        accent:       brand,
        accentBg:     hexToRgba(brand, 0.6),
        secondary:    '#f43f5e',
        secondaryBg:  'rgba(244, 63, 94, 0.6)',
        tickColor:    get('--text-muted'),
        gridColor:    hexToRgba(border, 0.4),
        legendColor:  get('--text-primary'),
        tooltipBg:    get('--bg-base'),
        tooltipTitle: get('--text-primary'),
        tooltipBody:  get('--text-muted'),
        tooltipBorder: hexToRgba(border, 0.6),
    };
}

function patchChartOptions(opts, t) {
    opts.scales.y.ticks.color          = t.tickColor;
    opts.scales.y.grid.color           = t.gridColor;
    opts.scales.x.ticks.color          = t.tickColor;
    opts.plugins.legend.labels.color   = t.legendColor;
    opts.plugins.tooltip.backgroundColor = t.tooltipBg;
    opts.plugins.tooltip.titleColor    = t.tooltipTitle;
    opts.plugins.tooltip.bodyColor     = t.tooltipBody;
    opts.plugins.tooltip.borderColor   = t.tooltipBorder;
}

function applyChartTheme() {
    var t = getChartTheme();
    [statsChart, monitoringChart].forEach(function(chart) {
        if (!chart) return;
        chart.data.datasets[0].backgroundColor = t.accentBg;
        chart.data.datasets[0].borderColor      = t.accent;
        chart.data.datasets[1].backgroundColor  = t.secondaryBg;
        chart.data.datasets[1].borderColor      = t.secondary;
        patchChartOptions(chart.options, t);
        chart.update('none');
    });
    if (healthHistoryChart) {
        patchChartOptions(healthHistoryChart.options, t);
        healthHistoryChart.update('none');
    }
}

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

// Currently selected container stem in the inspector (lowercase).
window._selectedContainerStem = null;
window._selectedContainerServerId = null;

window.selectContainerStem = function(stem, serverId) {
    window._selectedContainerStem = (stem || '').toLowerCase();
    window._selectedContainerServerId = parseInt(serverId, 10);
    updateInspectorStatsCard();
    updateInspectorActivityLog();
};

function updateInspectorStatsCard() {
    var card = document.getElementById('container-stats-card');
    if (!card) return;

    var stem = window._selectedContainerStem;
    var serverId = window._selectedContainerServerId;
    if (!stem || !serverId) {
        card.classList.add('hidden');
        hideTerminalSection();
        return;
    }

    var serverStats = lastStatsPerServer[serverId];
    var running = runningContainersBySid[serverId] || new Set();

    // Find matching container in stats data
    var matched = null;
    if (serverStats) {
        (serverStats.containers || []).forEach(function(c) {
            var cName = (c.name || '').toLowerCase();
            if (cName.indexOf(stem) !== -1 || stem.indexOf(cName) !== -1) {
                matched = c;
            }
        });
    }

    // Check if container is running (even if stats haven't arrived yet)
    var isRunning = false;
    running.forEach(function(name) {
        if (name.indexOf(stem) !== -1 || stem.indexOf(name) !== -1) {
            isRunning = true;
        }
    });

    card.classList.remove('hidden');

    // Show/hide terminal section based on running state
    var terminalSection = document.getElementById('container-terminal-section');
    if (isRunning && terminalSection) {
        terminalSection.classList.remove('hidden');
        // Enable connect button
        var connectBtn = document.getElementById('terminal-connect-btn');
        if (connectBtn) connectBtn.disabled = false;
    } else if (terminalSection) {
        terminalSection.classList.add('hidden');
        disconnectTerminal();
    }

    if (matched) {
        card.innerHTML =
            '<div class="stats-card-title"><span class="status-dot dot-running" style="width:8px;height:8px;"></span>' + escapeHtml(matched.name) + '</div>' +
            '<div class="stats-card-grid">' +
            '<div class="stats-card-item"><span class="stats-card-label">CPU</span><span class="stats-card-value">' + escapeHtml(matched.cpu) + '</span></div>' +
            '<div class="stats-card-item"><span class="stats-card-label">Memory</span><span class="stats-card-value">' + escapeHtml(matched.mem) + '</span></div>' +
            '<div class="stats-card-item"><span class="stats-card-label">Net I/O</span><span class="stats-card-value">' + escapeHtml(matched.net_io) + '</span></div>' +
            '<div class="stats-card-item"><span class="stats-card-label">PIDs</span><span class="stats-card-value">' + escapeHtml(matched.pids) + '</span></div>' +
            '</div>';
    } else if (!isRunning) {
        card.innerHTML =
            '<div class="stats-card-title">' + escapeHtml(stem) + '</div>' +
            '<div class="stats-card-not-running">Container not running</div>';
    } else {
        card.innerHTML =
            '<div class="stats-card-title"><span class="status-dot dot-running" style="width:8px;height:8px;"></span>' + escapeHtml(stem) + '</div>' +
            '<div class="stats-card-not-running">Waiting for stats...</div>';
    }
}

function updateInspectorActivityLog() {
    var activityLog = document.getElementById('container-activity-log');
    if (!activityLog) return;

    var stem = window._selectedContainerStem;
    var serverId = window._selectedContainerServerId;
    if (!stem || !serverId) {
        activityLog.classList.add('hidden');
        return;
    }

    activityLog.classList.remove('hidden');

    // Fetch activity events from the API
    fetch('/api/activity/' + serverId + '?container=' + encodeURIComponent(stem) + '&limit=10')
        .then(function(response) {
            if (!response.ok) throw new Error('Failed to fetch activity');
            return response.json();
        })
        .then(function(data) {
            var listEl = activityLog.querySelector('.activity-list');
            if (!data.events || data.events.length === 0) {
                listEl.innerHTML = '<div class="text-muted italic p-2">No events recorded</div>';
                return;
            }

            var html = '';
            data.events.forEach(function(event) {
                var icon = '';
                switch (event.event_type) {
                    case 'start': icon = '▶'; break;
                    case 'stop': icon = '⏹'; break;
                    case 'restart': icon = '🔄'; break;
                    case 'failure': icon = '⚠'; break;
                    default: icon = '•';
                }

                var relTime = getRelativeTime(event.occurred_at);
                var triggeredBy = event.triggered_by ? ' by ' + event.triggered_by : '';

                html += '<div class="activity-item">' +
                    '<span class="activity-icon">' + icon + '</span>' +
                    '<span class="activity-type">' + escapeHtml(event.event_type) + '</span>' +
                    '<span class="activity-time">' + escapeHtml(relTime) + '</span>' +
                    '<span class="activity-user">' + escapeHtml(triggeredBy) + '</span>' +
                    '</div>';
            });

            listEl.innerHTML = html;
        })
        .catch(function(err) {
            console.error('Error fetching activity:', err);
            var listEl = activityLog.querySelector('.activity-list');
            listEl.innerHTML = '<div class="text-muted italic p-2">Failed to load activity</div>';
        });
}

function getRelativeTime(timestamp) {
    var now = Math.floor(Date.now() / 1000);
    var diff = now - timestamp;

    if (diff < 60) return 'just now';
    if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
    if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
    return Math.floor(diff / 86400) + 'd ago';
}


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


function buildBarChartConfig() {
  var t = getChartTheme();
  return {
    type: 'bar',
    data: {
      labels: [],
      datasets: [
        {
          label: 'CPU %',
          data: [],
          backgroundColor: t.accentBg,
          borderColor: t.accent,
          borderWidth: 1,
          borderRadius: 4
        },
        {
          label: 'Memory %',
          data: [],
          backgroundColor: t.secondaryBg,
          borderColor: t.secondary,
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
            color: t.tickColor,
            font: { size: 11 },
            callback: function(value) { return value + '%'; }
          },
          grid: { color: t.gridColor }
        },
        x: {
          ticks: {
            color: t.tickColor,
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
            color: t.legendColor,
            font: { size: 11 },
            boxWidth: 12,
            padding: 8
          }
        },
        tooltip: {
          backgroundColor: t.tooltipBg,
          titleColor: t.tooltipTitle,
          bodyColor: t.tooltipBody,
          borderColor: t.tooltipBorder,
          borderWidth: 1,
          cornerRadius: 6,
          padding: 8
        }
      }
    }
  };
}

function initStatsChart() {
  const ctx = document.getElementById('stats-chart');
  if (!ctx) return;
  statsChart = new Chart(ctx, buildBarChartConfig());
}

function initMonitoringChart() {
  const ctx = document.getElementById('monitoring-chart');
  if (!ctx) return;
  monitoringChart = new Chart(ctx, buildBarChartConfig());
}

function initHealthHistoryChart() {
  const ctx = document.getElementById('health-history-chart');
  if (!ctx) return;

  var t = getChartTheme();
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
            color: t.tickColor,
            font: { size: 10 },
            stepSize: 1,
            callback: function(v) { return v === 1 ? 'Running' : 'Stopped'; }
          },
          grid: { color: t.gridColor }
        },
        x: {
          ticks: {
            color: t.tickColor,
            font: { size: 10 },
            maxTicksLimit: 8,
            maxRotation: 0,
          },
          grid: { display: false }
        }
      },
      plugins: {
        legend: {
          labels: { color: t.legendColor, font: { size: 11 }, boxWidth: 12, padding: 8 }
        },
        tooltip: {
          backgroundColor: t.tooltipBg,
          titleColor: t.tooltipTitle,
          bodyColor: t.tooltipBody,
          borderColor: t.tooltipBorder,
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

function renderContainerStatsTable(tableElId, data) {
    var tableEl = document.getElementById(tableElId);
    if (!tableEl) return;

    const containers = data.containers || [];

    if (containers.length === 0) {
        tableEl.innerHTML = '<div class="p-4 text-muted italic">No containers running on ' +
            escapeHtml(data.server_name || 'server') + '</div>';
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
        html += '<td class="text-left p-4 text-accent font-semibold">' + escapeHtml(c.name) + '</td>';
        html += '<td class="p-4 text-right">' + escapeHtml(c.cpu) + '</td>';
        html += '<td class="p-4 text-right">' + escapeHtml(c.mem) + '</td>';
        html += '<td class="p-4 text-right text-muted">' + escapeHtml(c.net_io) + '</td>';
        html += '<td class="p-4 text-right text-muted">' + escapeHtml(c.pids) + '</td>';
        html += '</tr>';
    });

    html += '</tbody></table>';
    html += '<div class="p-4 text-muted text-right text-xs">' + escapeHtml(data.server_name || '') + '</div>';
    tableEl.innerHTML = html;
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

    renderContainerStatsTable('stats-table', data);
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

      // Update inspector stats card if this server's container is selected.
      if (data.server_id === window._selectedContainerServerId) {
        updateInspectorStatsCard();
      }

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
  // Restore inspector-expanded class on dashboard tab if persisted
  if (tabId === 'dashboard' && localStorage.getItem('qm-inspector-expanded') === 'true') {
    document.body.classList.add('inspector-expanded');
  }
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

// ── Settings Section Switcher ─────────────────────────────
window.showSettingsSection = function(name) {
  document.querySelectorAll('.settings-group').forEach(function(g) {
    g.style.display = g.dataset.group === name ? 'grid' : 'none';
  });
  document.querySelectorAll('.settings-sidenav-item').forEach(function(btn) {
    btn.classList.toggle('active', btn.dataset.section === name);
  });
};

// ── Inspector Expand / Collapse Toggle ───────────────────
window.toggleInspectorExpand = function() {
  var expanded = document.body.classList.toggle('inspector-expanded');
  localStorage.setItem('qm-inspector-expanded', expanded ? 'true' : 'false');
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

  renderContainerStatsTable('monitoring-stats-table', data);
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

// ── Terminal Session Management ──────────────────────────
window._terminalInstance = null;
window._terminalWs = null;
window._terminalSession = null;
window._fitAddonLoaded = false;

function loadFitAddon(callback) {
    if (window._fitAddonLoaded) {
        callback();
        return;
    }
    var script = document.createElement('script');
    script.src = 'https://cdn.jsdelivr.net/npm/xterm-addon-fit@0.8.0/lib/xterm-addon-fit.umd.min.js';
    script.onload = function() {
        window._fitAddonLoaded = true;
        callback();
    };
    script.onerror = function() {
        console.error('Failed to load FitAddon');
        callback();
    };
    document.head.appendChild(script);
}

function showTerminalSection() {
    var section = document.getElementById('container-terminal-section');
    if (section) section.classList.remove('hidden');
}

function hideTerminalSection() {
    var section = document.getElementById('container-terminal-section');
    if (section) section.classList.add('hidden');
    disconnectTerminal();
}

window.connectTerminal = function() {
    var stem = window._selectedContainerStem;
    var serverId = window._selectedContainerServerId;
    if (!stem || !serverId) {
        console.error('No container selected');
        return;
    }

    var running = runningContainersBySid[serverId] || new Set();
    var isRunning = false;
    var actualContainerName = null;

    // Find the actual container name that matches the stem
    running.forEach(function(name) {
        if (name.indexOf(stem) !== -1 || stem.indexOf(name) !== -1) {
            isRunning = true;
            actualContainerName = name;  // Use the actual container name
        }
    });

    if (!isRunning) {
        alert('Container must be running to open a terminal');
        return;
    }

    // Use the actual container name, fallback to stem if not found
    var containerName = actualContainerName || stem;

    // Get shell selection
    var shellSelect = document.getElementById('terminal-shell-select');
    var shell = shellSelect ? shellSelect.value : 'bash';
    var cmd = shell;

    if (shell === 'custom') {
        var customInput = document.getElementById('terminal-custom-cmd-input');
        cmd = customInput ? customInput.value.trim() : 'bash';
        if (!cmd) {
            alert('Please enter a command');
            return;
        }
    }

    // Close existing connection
    if (window._terminalWs) {
        window._terminalWs.close();
        window._terminalWs = null;
    }

    // Initialize xterm if needed
    if (!window._terminalInstance) {
        var container = document.getElementById('xterm-container');
        if (!container) return;
        window._terminalInstance = new Terminal({ rows: 24, cols: 80 });
        window._terminalInstance.open(container);
    }

    loadFitAddon(function() {
        // Create FitAddon once and reuse it
        if (window.FitAddon && !window._terminalFitAddon) {
            window._terminalFitAddon = new window.FitAddon.FitAddon();
            window._terminalInstance.loadAddon(window._terminalFitAddon);
        }

        // Connect to WebSocket
        var protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        var wsUrl = protocol + '//' + window.location.host + '/ws/exec/' + serverId + '/' + encodeURIComponent(containerName) + '?scope=user&cmd=' + encodeURIComponent(cmd);

        window._terminalWs = new WebSocket(wsUrl);
        window._terminalSession = { serverId: serverId, container: containerName, cmd: cmd };

        window._terminalWs.onopen = function() {
            console.log('Terminal WebSocket connected');
            var connectBtn = document.getElementById('terminal-connect-btn');
            var disconnectBtn = document.getElementById('terminal-disconnect-btn');
            if (connectBtn) connectBtn.classList.add('hidden');
            if (disconnectBtn) disconnectBtn.classList.remove('hidden');

            // Fit terminal to container
            if (window._terminalFitAddon) {
                window._terminalFitAddon.fit();
                var dims = window._terminalFitAddon.proposeDimensions();
                window._terminalWs.send(JSON.stringify({
                    type: 'resize',
                    cols: dims ? dims.cols : 80,
                    rows: dims ? dims.rows : 24
                }));
            }

            // Forward terminal input to WebSocket (dispose previous handler first)
            if (window._terminalDataHandler) {
                window._terminalDataHandler.dispose();
            }
            window._terminalDataHandler = window._terminalInstance.onData(function(data) {
                if (window._terminalWs && window._terminalWs.readyState === WebSocket.OPEN) {
                    window._terminalWs.send(data);
                }
            });

            // Handle window resize
            window._terminalResizeHandler = function() {
                if (window._terminalInstance && window._terminalFitAddon) {
                    window._terminalFitAddon.fit();
                    var dims = window._terminalFitAddon.proposeDimensions();
                    if (window._terminalWs && window._terminalWs.readyState === WebSocket.OPEN) {
                        window._terminalWs.send(JSON.stringify({
                            type: 'resize',
                            cols: dims ? dims.cols : 80,
                            rows: dims ? dims.rows : 24
                        }));
                    }
                }
            };
            window.addEventListener('resize', window._terminalResizeHandler);
        };

        window._terminalWs.onmessage = function(e) {
            if (window._terminalInstance) {
                window._terminalInstance.write(e.data);
            }
        };

        window._terminalWs.onerror = function(err) {
            console.error('Terminal WebSocket error:', err);
            if (window._terminalInstance) {
                window._terminalInstance.write('\r\n\u001b[31mConnection error\u001b[0m\r\n');
            }
        };

        window._terminalWs.onclose = function() {
            console.log('Terminal WebSocket closed');
            var connectBtn = document.getElementById('terminal-connect-btn');
            var disconnectBtn = document.getElementById('terminal-disconnect-btn');
            if (connectBtn) connectBtn.classList.remove('hidden');
            if (disconnectBtn) disconnectBtn.classList.add('hidden');
            if (window._terminalResizeHandler) {
                window.removeEventListener('resize', window._terminalResizeHandler);
            }
        };

        // Show terminal container
        var termContainer = document.getElementById('xterm-container');
        if (termContainer) termContainer.classList.remove('hidden');
    });
};

window.disconnectTerminal = function() {
    if (window._terminalWs) {
        window._terminalWs.close();
        window._terminalWs = null;
    }
    if (window._terminalResizeHandler) {
        window.removeEventListener('resize', window._terminalResizeHandler);
    }
    var connectBtn = document.getElementById('terminal-connect-btn');
    var disconnectBtn = document.getElementById('terminal-disconnect-btn');
    if (connectBtn) connectBtn.classList.remove('hidden');
    if (disconnectBtn) disconnectBtn.classList.add('hidden');
};

// Handle shell selector changes (setup after DOM is ready)
var setupShellSelector = function() {
    var shellSelect = document.getElementById('terminal-shell-select');
    if (shellSelect) {
        shellSelect.addEventListener('change', function() {
            var customRow = document.getElementById('terminal-custom-cmd-row');
            if (this.value === 'custom' && customRow) {
                customRow.classList.remove('hidden');
            } else if (customRow) {
                customRow.classList.add('hidden');
            }
        });
    }
};

// ── Resizable Panel Handles ──────────────────────────────
function initResizableHandles() {
    var SIDEBAR_MIN = 180, SIDEBAR_MAX = 500;
    var INSPECTOR_MIN = 220, INSPECTOR_MAX = 600;
    var SETTINGS_SIDENAV_MIN = 160, SETTINGS_SIDENAV_MAX = 480;

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

    // Settings sidenav handle: controls settings sidebar width
    makeDraggable(
        document.getElementById('settings-sidenav-resize-handle'),
        '--settings-sidenav-width',
        'qm-settings-sidenav-width',
        SETTINGS_SIDENAV_MIN, SETTINGS_SIDENAV_MAX,
        function() {
            var sn = document.querySelector('.settings-sidenav');
            return sn ? sn.getBoundingClientRect().width : 220;
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
  var saved = {
    sidebar: localStorage.getItem('qm-sidebar-width'),
    inspector: localStorage.getItem('qm-inspector-width'),
    settingsSidenav: localStorage.getItem('qm-settings-sidenav-width'),
  };
  if (saved.sidebar) document.documentElement.style.setProperty('--sidebar-width', saved.sidebar);
  if (saved.inspector) document.documentElement.style.setProperty('--inspector-width', saved.inspector);
  if (saved.settingsSidenav) document.documentElement.style.setProperty('--settings-sidenav-width', saved.settingsSidenav);
})();

window.switchTab('dashboard');
initStatsChart();
initMonitoringChart();
initHealthHistoryChart();
setupShellSelector();
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

// ── File Deletion ─────────────────────────────────────────
let _ctxMenu = null;

window.showFileContextMenu = function(event, serverId, path, scope) {
    event.preventDefault();

    if (_ctxMenu) _ctxMenu.remove();

    _ctxMenu = document.createElement('div');
    _ctxMenu.className = 'context-menu';
    _ctxMenu.style.cssText = 'position:fixed;left:' + event.clientX + 'px;top:' + event.clientY + 'px';

    var btn = document.createElement('button');
    btn.className = 'context-menu-item context-menu-danger';
    btn.textContent = 'Delete';
    btn.onclick = function() {
        _ctxMenu.remove();
        _ctxMenu = null;
        window.confirmDeleteFile(serverId, path, scope);
    };
    _ctxMenu.appendChild(btn);
    document.body.appendChild(_ctxMenu);

    setTimeout(function() {
        document.addEventListener('click', function closeMenu() {
            if (_ctxMenu) { _ctxMenu.remove(); _ctxMenu = null; }
            document.removeEventListener('click', closeMenu);
        }, { once: true });
    }, 0);
};

window.confirmDeleteFile = function(serverId, path, scope) {
    var existing = document.getElementById('delete-confirm-modal');
    if (existing) existing.remove();

    var fileName = path.split('/').pop();
    var safeFileName = fileName.replace(/[<>&"]/g, function(c) {
        return {'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;'}[c];
    });

    var modal = document.createElement('div');
    modal.id = 'delete-confirm-modal';
    modal.className = 'modal-overlay';
    modal.innerHTML =
        '<div class="modal-content">' +
        '<h2 class="panel-title mb-4">Delete File</h2>' +
        '<p class="text-sm mb-6">Delete <strong>' + safeFileName + '</strong>? This cannot be undone.</p>' +
        '<div class="flex justify-end space-x-2">' +
        '<button class="btn btn-secondary" onclick="document.getElementById(\'delete-confirm-modal\').remove()">Cancel</button>' +
        '<button class="btn btn-danger" onclick="window.executeDeleteFile(' + serverId + ', ' + JSON.stringify(path) + ', ' + JSON.stringify(scope) + ')">Delete</button>' +
        '</div></div>';
    document.body.appendChild(modal);
  window.setupModalDismissal('delete-confirm-modal');
};

window.executeDeleteFile = async function(serverId, path, scope) {
    document.getElementById('delete-confirm-modal')?.remove();

    var url = '/api/files?server_id=' + encodeURIComponent(serverId) +
              '&path=' + encodeURIComponent(path) +
              '&scope=' + encodeURIComponent(scope);
    var response = await fetch(url, { method: 'DELETE' });
    var html = await response.text();

    var toast = document.getElementById('status-toast');
    if (toast) toast.innerHTML = html;

    if (response.headers.get('HX-Trigger') === 'reload-servers') {
        document.body.dispatchEvent(new Event('reload-servers'));
    }
};

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

// ── Modal Dismissal Handlers ───────────────────────────────
window.setupModalDismissal = function(modalId) {
  var modal = document.getElementById(modalId);
  if (!modal) return;

  // Close on ESC key
  var escHandler = function(e) {
    if (e.key === 'Escape' || e.key === 'Esc') {
      modal.remove();
      document.removeEventListener('keydown', escHandler);
    }
  };
  document.addEventListener('keydown', escHandler);

  // Close on backdrop click (outside modal-content)
  modal.addEventListener('click', function(e) {
    if (e.target === modal) {
      modal.remove();
      document.removeEventListener('keydown', escHandler);
    }
  });
};

// Auto-setup for modals added via HTMX
document.body.addEventListener('htmx:afterSwap', function(e) {
  var modals = document.querySelectorAll('.modal-overlay:not([data-dismissal-setup])');
  modals.forEach(function(modal) {
    modal.setAttribute('data-dismissal-setup', 'true');
    var escHandler = function(e) {
      if (e.key === 'Escape' || e.key === 'Esc') {
        modal.remove();
        document.removeEventListener('keydown', escHandler);
      }
    };
    document.addEventListener('keydown', escHandler);
    modal.addEventListener('click', function(e) {
      if (e.target === modal) {
        modal.remove();
        document.removeEventListener('keydown', escHandler);
      }
    });
  });
});
