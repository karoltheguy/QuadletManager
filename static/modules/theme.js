/**
 * Owns app theme, UI density, editor theme, theme preview, and chart theming.
 */

import { state } from '@qm/state';
import { onPrimaryFor, hexToRgba } from '@qm/color';

// ── Theme Toggle ─────────────────────────────────────────
// No saved pref → follows OS via CSS @media (prefers-color-scheme).
// First click reads the currently-resolved theme and flips to the
// opposite, then persists to localStorage so the override sticks.
export function toggleTheme() {
    const root = document.documentElement;
    let current = root.dataset.theme;
    if (!current) {
        current = window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
    }
    const next = current === 'light' ? 'dark' : 'light';
    root.dataset.theme = next;
    try {
        localStorage.setItem('qm-theme-override', next);
    } catch {
        // Ignore localStorage restrictions
    }
    applyChartTheme();
    applyEditorTheme();
}

// ── Density Toggle ───────────────────────────────────────
export function toggleDensity(value) {
    const root = document.documentElement;
    if (value === 'compact') {
        root.dataset.density = 'compact';
    } else {
        delete root.dataset.density;
    }
    try {
        localStorage.setItem('qm-density', value);
    } catch {
        // Ignore localStorage restrictions
    }
}

export function initDensityRadio() {
    let stored = 'relaxed';
    try {
        stored = localStorage.getItem('qm-density') || 'relaxed';
    } catch {
        // Ignore localStorage restrictions
    }
    const radio = document.getElementById('density-' + stored);
    if (radio) radio.checked = true;
}

// ── Editor Theme Toggle ──────────────────────────────────
export function toggleEditorTheme(value) {
    try {
        localStorage.setItem('qm-editor-theme', value);
    } catch {
        // Ignore localStorage restrictions
    }
    applyEditorTheme();
}

export function initEditorThemeRadio() {
    let stored = 'follow';
    try {
        stored = localStorage.getItem('qm-editor-theme') || 'follow';
    } catch {
        // Ignore localStorage restrictions
    }
    const radio = document.getElementById('editor-theme-' + stored);
    if (radio) radio.checked = true;
}

// ── Theme Preview ─────────────────────────────────────────

// NOTE: load_active_theme() in api/routes.py only injects --brand-on-primary
// when a saved theme has a custom brand_primary override; the live preview
// below always emits it. This is not a divergence -- onPrimaryFor() reproduces
// the static CSS defaults for both shipped brand colors (#14b8a6 -> #1c1f24,
// #0e7268 -> #ffffff), so emitting it unconditionally here matches what the
// server would compute either way.
export function applyThemePreview(form) {
    const mode = form.dataset.mode;
    let rules = '';
    let brandPrimary = null;
    form.querySelectorAll('input[type="color"][name]').forEach(function(inp) {
        rules += '--' + inp.name.replaceAll('_', '-') + ':' + inp.value + ';';
        if (inp.name === 'brand_primary') brandPrimary = inp.value;
    });
    if (brandPrimary) {
        rules += '--brand-on-primary:' + onPrimaryFor(brandPrimary) + ';';
    }
    const css = ':root[data-theme="' + mode + '"]{' + rules + '}';
    let el = document.getElementById('qm-theme-preview');
    if (!el) {
        el = document.createElement('style');
        el.id = 'qm-theme-preview';
        // Read the CSP nonce from the importmap script tag via the IDL .nonce property.
        // Browsers blank the visible nonce content attribute after parsing, so
        // getAttribute('nonce') returns '' while .nonce retains the value.
        const importmap = document.querySelector('script[type="importmap"]');
        const nonce = importmap ? importmap.nonce : '';
        if (nonce) {
            el.nonce = nonce;
        }
        const anchor = document.getElementById('qm-theme-overrides');
        if (anchor) anchor.after(el);
        else document.head.appendChild(el);
    }
    el.textContent = css;
}

export function clearThemePreview() {
    const el = document.getElementById('qm-theme-preview');
    if (el) el.remove();
}

// Setting .style from JavaScript is not blocked by the Content-Security-Policy;
// only a parsed style= attribute in markup is, which is why this indirection is needed.
export function paintThemeSwatches(root = document) {
    root.querySelectorAll('[data-swatch-color]').forEach(function(el) {
        el.style.backgroundColor = el.dataset.swatchColor;
    });
}

export function setEditorMode(editor, mode) {
  editor.dataset.editingMode = mode;
  editor.querySelectorAll('.color-editor-form').forEach(f => {
    f.classList.toggle('hidden', f.dataset.mode !== mode);
  });
  // Match on data-mode instead of button text so translation or rewording does not break active state.
  editor.querySelectorAll('.seg-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.mode === mode);
  });
}

export function getChartTheme() {
    const s = getComputedStyle(document.documentElement);
    const get = function(v) { return s.getPropertyValue(v).trim(); };
    const brand = get('--brand-primary');
    const border = get('--border-color');
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

export function patchChartOptions(opts, t) {
    opts.scales.y.ticks.color          = t.tickColor;
    opts.scales.y.grid.color           = t.gridColor;
    opts.scales.x.ticks.color          = t.tickColor;
    opts.plugins.legend.labels.color   = t.legendColor;
    opts.plugins.tooltip.backgroundColor = t.tooltipBg;
    opts.plugins.tooltip.titleColor    = t.tooltipTitle;
    opts.plugins.tooltip.bodyColor     = t.tooltipBody;
    opts.plugins.tooltip.borderColor   = t.tooltipBorder;
}

export function applyChartTheme() {
    const t = getChartTheme();
    // Monitor time-series charts build their own per-container datasets, so only
    // the shared axis/legend/tooltip colors need repainting on a theme switch.
    [state.cpuHistoryChart, state.memHistoryChart].forEach(function(chart) {
        if (!chart) return;
        patchChartOptions(chart.options, t);
        chart.update('none');
    });
}

export function applyEditorTheme() {
    if (!window.monaco || !window.editor) return;
    let pref = 'follow';
    try {
        pref = localStorage.getItem('qm-editor-theme') || 'follow';
    } catch {
        pref = 'follow';
    }
    if (pref === 'light') {
        window.monaco.editor.setTheme('vs');
    } else if (pref === 'dark') {
        window.monaco.editor.setTheme('vs-dark');
    } else {
        const resolved = document.documentElement.dataset.theme;
        window.monaco.editor.setTheme(resolved === 'light' ? 'vs' : 'vs-dark');
    }
}
