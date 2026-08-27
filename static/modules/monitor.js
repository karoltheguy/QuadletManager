/* global htmx */
/**
 * Monitor pane: server stats rendering, container filtering, and tab activation.
 */

import { state, lastStatsPerServer, monitorChartSelection } from '@qm/state';
import { el } from '@qm/dom';
import { parsePercent, mergeUnitRows, renderContainerStatsTable,
         updateSummaryStrip, updateFilterCount } from '@qm/stats';
import { chartColorFor, applyChartSelection, loadMonitorCharts } from '@qm/charts';

export function showMonitoringEmptyState(emptyEl, contentEl) {
  if (emptyEl) emptyEl.style.display = '';
  if (contentEl) contentEl.style.display = 'none';
  const barEl = document.getElementById('monitor-stat-bar');
  if (barEl) barEl.style.display = 'none';
  state._monitoringServerId = null;
}

export function renderMonitoringServerStats(numId) {
  const cached = Reflect.get(lastStatsPerServer, numId);
  if (cached) {
    updateMonitoringView(cached);
    loadMonitorCharts(state._monitorChartMinutes || 15);
  } else {
    const tableEl = document.getElementById('monitoring-stats-table');
    if (tableEl) {
      tableEl.textContent = '';
      tableEl.appendChild(el('div', { className: 'p-4 text-muted italic' }, 'Waiting for stats data...'));
    }

  }
}

// Re-apply the Monitor's server selection to a freshly swapped option list.
// Gated on the option existing, never on lastStatsPerServer having an entry:
// renderMonitoringServerStats already shows "Waiting for stats data..." for a
// server that has not reported yet.
export function restoreMonitoringServerSelection(select) {
  let target = state._monitoringServerId ? String(state._monitoringServerId) : '';
  if (!target) {
    try {
      target = localStorage.getItem('qm-monitor-server') || '';
    } catch {
      // Ignore localStorage restrictions
    }
  }
  if (!target) return;

  const hasOption = Array.from(select.options).some(function(o) { return o.value === target; });
  if (!hasOption) return;

  select.value = target;

  // Assigning .value fires no change event, and none should be dispatched: on
  // a reload-servers swap of an unchanged selection this only has to restore
  // the visible value, not repaint the pane.
  if (String(state._monitoringServerId) !== target) {
    selectMonitoringServer(target);
  }
}

export function selectMonitoringServer(serverId) {
  try {
    localStorage.setItem('qm-monitor-server', serverId ? String(serverId) : '');
  } catch {
    // Ignore localStorage restrictions
  }
  const numId = Number.parseInt(serverId, 10);
  const emptyEl = document.getElementById('monitoring-empty-state');
  const contentEl = document.getElementById('monitoring-content');

  if (!numId) {
    showMonitoringEmptyState(emptyEl, contentEl);
    return;
  }

  if (emptyEl) emptyEl.style.display = 'none';
  if (contentEl) contentEl.style.display = '';

  state._monitoringServerId = numId;

  renderMonitoringServerStats(numId);
}

// The Monitor's name filter is a lowercase substring match, applied to the
// container list and to the merged row list alike so the table, the charts and
// the glance bar always narrow over the same names.
export function applyMonitorFilter(list) {
  if (!state.monitorContainerFilter) return list;
  return list.filter(function(c) {
    return (c.name || '').toLowerCase().includes(state.monitorContainerFilter);
  });
}

export function updateMonitoringView(data) {
  // Only render when this data is for the server currently selected in the dropdown.
  if (data.server_id !== state._monitoringServerId) return;

  // Apply the active filter to every part of the pane: table, charts and the
  // glance bar all narrow together, so the numbers always describe what is
  // on screen.
  const allContainers = data.containers || [];
  const containers = applyMonitorFilter(allContainers);

  // The table shows one row per unit, including stopped units that have no
  // running container, so it renders merged rows. The charts and summary
  // strip only have real measurements to plot, so they keep using the real
  // containers list; a placeholder row would draw a flat-zero chart series
  // and drag the CPU/MEM totals down to a false 0.0%.
  const allRows = mergeUnitRows(allContainers, data.units);
  const rows = applyMonitorFilter(allRows);

  const paneData = function(list) {
    return { server_id: data.server_id, server_name: data.server_name, containers: list, units: data.units };
  };

  // Render the table, summary strip and filter count before touching the
  // charts: handleStatsUpdate catches a throw from the chart append below,
  // so the data render must not depend on it succeeding or the pane freezes.
  renderContainerStatsTable('monitoring-stats-table', paneData(rows));
  updateSummaryStrip(paneData(containers));
  updateFilterCount(rows.length, allRows.length);

  // Append the latest SSE data point to the live time-series charts.
  if ((state.cpuHistoryChart || state.memHistoryChart) && allContainers.length > 0) {
    const now = new Date();
    const timeLabel = now.getHours().toString().padStart(2, '0') + ':' +
                    now.getMinutes().toString().padStart(2, '0') + ':' +
                    now.getSeconds().toString().padStart(2, '0');
    const windowSec = (state._monitorChartMinutes || 15) * 60;

    const appendToChart = function(chart, valueKey) {
      if (!chart) return;
      // Drop datasets for containers the filter no longer matches; otherwise a
      // series drawn before the filter was typed stays on the canvas with
      // nothing appending to it, since this path never refetches history.
      // Chart.js controllers hold dataset indexes, so when a dataset is
      // removed the chart must re-sync before any push into a surviving
      // dataset, or the stale controller throws on the now-shifted index.
      const visibleNames = {};
      containers.forEach(function(c) { visibleNames[c.name] = true; });
      const datasetCountBeforeFilter = chart.data.datasets.length;
      chart.data.datasets = chart.data.datasets.filter(function(ds) { return visibleNames[ds.label]; });
      if (chart.data.datasets.length !== datasetCountBeforeFilter) {
        chart.update('none');
      }

      // Build a map of current dataset labels for quick lookup
      const datasetByName = {};
      chart.data.datasets.forEach(function(ds) { datasetByName[ds.label] = ds; });

      containers.forEach(function(c) {
        const val = valueKey === 'cpu' ? parsePercent(c.cpu) : parsePercent(c.mem);
        if (datasetByName[c.name]) {
          datasetByName[c.name].data.push(val);
        } else {
          // New container not yet in chart — add a new dataset
          const color = chartColorFor(c.name);
          chart.data.datasets.push({
            label: c.name,
            data: [val],
            borderColor: color,
            backgroundColor: color.replace('1)', '0.08)'),
            borderWidth: 1.5,
            pointRadius: 0,
            fill: false,
            spanGaps: false,
          });
        }
      });

      // Append the shared time label and trim old data outside the window
      chart.data.labels.push(timeLabel);
      // Trim from the front while the window is exceeded
      while (chart.data.labels.length > windowSec / 5 + 10) {
        chart.data.labels.shift();
        chart.data.datasets.forEach(function(ds) { ds.data.shift(); });
      }

      applyChartSelection(chart);
      chart.update('none');
    }

    appendToChart(state.cpuHistoryChart, 'cpu');
    appendToChart(state.memHistoryChart, 'mem');
  }
}

export function applyContainerFilter(value) {
  // The filter decides which containers are available, so a filter change
  // resets which of them are selected, otherwise the user can end up with
  // an empty chart and no visible reason.
  monitorChartSelection.clear();
  state.monitorContainerFilter = (value || '').toLowerCase().trim();
  const serverId = state._monitoringServerId;
  const cached = Reflect.get(lastStatsPerServer, serverId);
  if (serverId && cached) {
    updateMonitoringView(cached);
  }
}

export function handleMonitorTabActivation() {
  if (state.cpuHistoryChart) state.cpuHistoryChart.resize();
  if (state.memHistoryChart) state.memHistoryChart.resize();
  loadMonitorCharts(state._monitorChartMinutes || 15);
  refreshMonitoringServerDropdown();
}

// The select's hx-trigger="load" fires while the Monitor pane is still
// display:none, where HTMX event timing is unreliable (issue #86, same
// workaround as refreshSshKeyDropdown). Refetch when the pane becomes
// visible, but only while the list is still empty: unlike the SSH key
// dropdown, refetching here would replace the options under a live
// selection.
export function refreshMonitoringServerDropdown() {
  const sel = document.getElementById('monitoring-server-select');
  if (sel && sel.options.length <= 1) {
    htmx.ajax('GET', '/api/servers/options', {target: sel, swap: 'innerHTML'});
  }
}
