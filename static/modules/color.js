/**
 * Pure colour maths helpers with no DOM access, making them directly testable under node.
 */

// WCAG contrast helpers (mirrors api/routes.py's _linearize / _relative_luminance /
// _contrast_ratio / _on_primary_for, see lines ~1285-1322). These must stay in
// exact result-parity with the Python implementation -- see
// tests/test_theme_preview_on_primary.py's parity assertion over a shared color
// corpus.
export function linearize(channel) {
    if (channel <= 0.04045) return channel / 12.92;
    return Math.pow((channel + 0.055) / 1.055, 2.4);
}

export function relativeLuminance(hexColor) {
    const hex = hexColor.replace(/^#/, '');
    let r = Number.parseInt(hex.substring(0, 2), 16) / 255;
    let g = Number.parseInt(hex.substring(2, 4), 16) / 255;
    let b = Number.parseInt(hex.substring(4, 6), 16) / 255;
    r = linearize(r);
    g = linearize(g);
    b = linearize(b);
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export function contrastRatio(hexA, hexB) {
    const la = relativeLuminance(hexA);
    const lb = relativeLuminance(hexB);
    const lighter = Math.max(la, lb);
    const darker = Math.min(la, lb);
    return (lighter + 0.05) / (darker + 0.05);
}

const ON_PRIMARY_CANDIDATES = ['#1c1f24', '#ffffff', '#000000'];
const WCAG_AA_MIN = 4.5;

export function onPrimaryFor(brandHex) {
    for (const candidate of ON_PRIMARY_CANDIDATES) {
        if (contrastRatio(candidate, brandHex) >= WCAG_AA_MIN) return candidate;
    }
    return '#ffffff';
}

export function hexToRgba(hex, alpha) {
    const r = Number.parseInt(hex.slice(1, 3), 16);
    const g = Number.parseInt(hex.slice(3, 5), 16);
    const b = Number.parseInt(hex.slice(5, 7), 16);
    return 'rgba(' + r + ', ' + g + ', ' + b + ', ' + alpha + ')';
}
