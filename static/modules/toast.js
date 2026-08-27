/**
 * Shared toast notification renderer for status messages.
 */

import { el } from '@qm/dom';

export function showToast(message, kind) {
    const toast = document.getElementById('status-toast');
    if (!toast) return;
    toast.textContent = '';
    toast.appendChild(
        el('div', { className: 'toast-msg toast-' + kind + ' toast-enter' }, message)
    );
    // Auto-dismiss after 8 seconds
    setTimeout(function() {
        if (toast.querySelector('.toast-enter')) {
            toast.textContent = '';
        }
    }, 8000);
}
