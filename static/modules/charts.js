/* global Chart */
/**
 * Monitor time-series charts, swatch state management, and chart selection.
 */

import { state, chartColorByName, monitorChartSelection } from '@qm/state';
import { getChartTheme } from '@qm/theme';

// ── Stats Chart ──────────────────────────────────────────
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

// Colors are keyed off container name, not position: the table swatch and
// the chart line have to agree, but the two dataset-building paths visit
// containers in different orders.

// An empty set means every series is visible; a non-empty set is the exact
// set of visible container names. Both history charts share this selection.

// Single source of truth for "is this series/swatch on": both the row
// renderer and the click refresh use it, so the button state and
// `ds.hidden` can never drift apart.
export function chartSwatchIsOn(name) {
    return monitorChartSelection.size === 0 || monitorChartSelection.has(name);
}

// Sets a swatch button's aria-pressed and class from the shared predicate.
// `chart-swatch` is the permanent identity class (styling and test hooks key
// off it regardless of state); `chart-swatch-off` is added alongside it,
// never in place of it, when the series is hidden.
export function applySwatchState(btn, name) {
    const on = chartSwatchIsOn(name);
    btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    btn.className = on ? 'chart-swatch' : 'chart-swatch chart-swatch-off';
}

export function chartColorFor(name) {
    if (chartColorByName.has(name)) {
        return chartColorByName.get(name);
    }
    const color = HISTORY_COLORS[chartColorByName.size % HISTORY_COLORS.length];
    chartColorByName.set(name, color);
    return color;
}

export function applyChartSelection(chart) {
    if (!chart) return;
    chart.data.datasets.forEach(function(ds) {
        ds.hidden = monitorChartSelection.size > 0 && !monitorChartSelection.has(ds.label);
    });
}

// One click on a container's swatch. From all-visible, it isolates that
// container; from a subset it adds or removes; and clicking the only selected
// container clears the selection, so a user is never stranded in a filtered view.
export function toggleChartSelection(name) {
    if (!monitorChartSelection.has(name)) {
        monitorChartSelection.add(name);
    } else if (monitorChartSelection.size >= 2) {
        monitorChartSelection.delete(name);
    } else {
        monitorChartSelection.clear();
    }
    applyChartSelection(state.cpuHistoryChart);
    applyChartSelection(state.memHistoryChart);
    if (state.cpuHistoryChart) state.cpuHistoryChart.update('none');
    if (state.memHistoryChart) state.memHistoryChart.update('none');
    refreshChartSwatches();
}

// Gives the click immediate feedback without waiting for the next stats
// frame to re-render the table.
export function refreshChartSwatches() {
    document.querySelectorAll('#monitoring-stats-table button.chart-swatch').forEach(function(btn) {
        applySwatchState(btn, btn.dataset.container);
    });
}


export function _buildTimeSeriesConfig() {
  const t = getChartTheme();
  return {
    type: 'line',
    data: { labels: [], datasets: [] },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      scales: {
        y: {
          beginAtZero: true,
          suggestedMax: 5,
          ticks: {
            color: t.tickColor,
            font: { size: 10 },
            callback: function(v) { return v + '%'; }
          },
          grid: { color: t.gridColor }
        },
        x: {
          ticks: {
            color: t.tickColor,
            font: { size: 10 },
            maxTicksLimit: 8,
            maxRotation: 0
          },
          grid: { display: false }
        }
      },
      plugins: {
        // The container table is the legend now (issue #256); the canvas
        // legend would just duplicate the chart-swatch buttons.
        legend: { display: false },
        tooltip: {
          backgroundColor: t.tooltipBg,
          titleColor: t.tooltipTitle,
          bodyColor: t.tooltipBody,
          borderColor: t.tooltipBorder,
          borderWidth: 1,
          cornerRadius: 6,
          padding: 8,
          callbacks: {
            label: function(ctx) { return ctx.dataset.label + ': ' + ctx.parsed.y.toFixed(1) + '%'; }
          }
        }
      }
    }
  };
}

export function initCpuChart() {
  const ctx = document.getElementById('cpu-history-chart');
  if (!ctx) return;
  state.cpuHistoryChart = new Chart(ctx, _buildTimeSeriesConfig());
}

export function initMemChart() {
  const ctx = document.getElementById('mem-history-chart');
  if (!ctx) return;
  state.memHistoryChart = new Chart(ctx, _buildTimeSeriesConfig());
}


export function loadMonitorCharts(minutes, btnEl) {
  state._monitorChartMinutes = minutes;

  if (btnEl) {
    document.querySelectorAll('.health-range-btn').forEach(function(b) { b.classList.remove('active'); });
    btnEl.classList.add('active');
  }

  const serverId = state._monitoringServerId;
  if (!serverId) return;

  // Build the URL rather than concatenating into fetch: serverId and minutes
  // reach here from DOM datasets and shared state, so encoding them is what
  // keeps a crafted value from escaping the path segment. openLogSocket in
  // logs.js constructs its WebSocket URL the same way.
  const historyUrl = new URL(
    '/api/health/history/' + encodeURIComponent(serverId),
    window.location.origin
  );
  historyUrl.searchParams.set('minutes', minutes);

  fetch(historyUrl)
    .then(function(r) { return r.json(); })
    .then(function(data) {
      const emptyEl = document.getElementById('monitor-charts-empty');
      const errorEl = document.getElementById('monitor-charts-error');
      if (errorEl) errorEl.classList.add('hidden');

      if (!data || data.length === 0) {
        if (emptyEl) emptyEl.classList.remove('hidden');
        return;
      }
      if (emptyEl) emptyEl.classList.add('hidden');

      if (!state.cpuHistoryChart || !state.memHistoryChart) return;

      // Build unified sorted timestamp labels from all containers
      const tsSet = new Set();
      data.forEach(function(c) { c.history.forEach(function(p) { tsSet.add(p.ts); }); });
      const tsSorted = Array.from(tsSet).sort(function(a, b) { return a - b; });

      const _rangeMinutes = state._monitorChartMinutes;
      const _dayNames = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
      const labels = tsSorted.map(function(ts) {
        const d = new Date(ts * 1000);
        const hh = d.getHours().toString().padStart(2, '0');
        const mm = d.getMinutes().toString().padStart(2, '0');
        const ss = d.getSeconds().toString().padStart(2, '0');
        if (_rangeMinutes <= 60) {
          return hh + ':' + mm + ':' + ss;
        } else if (_rangeMinutes <= 1440) {
          return hh + ':' + mm;
        } else {
          return _dayNames[d.getDay()] + ' ' + hh + ':' + mm;
        }
      });

      // Apply container filter to chart data
      const filteredData = state.monitorContainerFilter
        ? data.filter(function(c) { return (c.container_name || '').toLowerCase().includes(state.monitorContainerFilter); })
        : data;

      const cpuDatasets = filteredData.map(function(c) {
        const byTs = {};
        c.history.forEach(function(p) { Reflect.set(byTs, p.ts, p.cpu !== null ? p.cpu : null); });
        const color = chartColorFor(c.container_name);
        return {
          label: c.container_name,
          data: tsSorted.map(function(ts) {
            const val = Reflect.get(byTs, ts);
            return val !== undefined ? val : null;
          }),
          borderColor: color,
          backgroundColor: color.replace('1)', '0.08)'),
          borderWidth: 1.5,
          pointRadius: 0,
          fill: false,
          spanGaps: false,
        };
      });

      const memDatasets = filteredData.map(function(c) {
        const byTs = {};
        c.history.forEach(function(p) { Reflect.set(byTs, p.ts, p.mem !== null ? p.mem : null); });
        const color = chartColorFor(c.container_name);
        return {
          label: c.container_name,
          data: tsSorted.map(function(ts) {
            const val = Reflect.get(byTs, ts);
            return val !== undefined ? val : null;
          }),
          borderColor: color,
          backgroundColor: color.replace('1)', '0.08)'),
          borderWidth: 1.5,
          pointRadius: 0,
          fill: false,
          spanGaps: false,
        };
      });

      state.cpuHistoryChart.data.labels = labels;
      state.cpuHistoryChart.data.datasets = cpuDatasets;
      applyChartSelection(state.cpuHistoryChart);
      state.cpuHistoryChart.update();

      state.memHistoryChart.data.labels = labels;
      state.memHistoryChart.data.datasets = memDatasets;
      applyChartSelection(state.memHistoryChart);
      state.memHistoryChart.update();
    })
    .catch(function(err) {
      console.error('Monitor chart fetch error:', err);
      const errorEl = document.getElementById('monitor-charts-error');
      if (errorEl) errorEl.classList.remove('hidden');
    });
}
