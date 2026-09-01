/**
 * Modal dismissal handlers for ESC-key and backdrop-click dismissal.
 */

// Wire ESC-key and backdrop-click dismissal onto an already-resolved element.
// Both entry points below (the by-id helper and the htmx auto-setup) share this
// so the two handler pairs cannot drift apart.
export function bindModalDismissal(modal) {
  // Close on ESC key
  const escHandler = function(e) {
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
}

export function setupModalDismissal(modalId) {
  const modal = document.getElementById(modalId);
  if (!modal) return;
  bindModalDismissal(modal);
}

export function initModalDismissal() {
  // Auto-setup for modals added via HTMX
  document.body.addEventListener('htmx:afterSwap', function() {
    const modals = document.querySelectorAll('.modal-overlay:not([data-dismissal-setup])');
    modals.forEach(function(modal) {
      modal.dataset.dismissalSetup = 'true';
      bindModalDismissal(modal);
    });
  });
}

// Dismiss the closest containing modal overlay.
export function dismissModal(el) {
  const modal = el.closest('.modal-overlay');
  if (modal) modal.remove();
}

