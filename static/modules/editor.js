/* global monaco, require */
/**
 * Monaco editor configuration, validation, and save handling.
 */

// Report a failed validation request in the results pane and throw. Split out
// of validateQuadlet so that function stays under the cognitive-complexity limit.
async function throwValidationRequestError(response) {
    let message = 'Validation request failed with status ' + response.status;
    try {
        const errorBody = await response.json();
        if (errorBody && typeof errorBody.error === 'string' && errorBody.error) {
            message = errorBody.error;
        }
    } catch (e) {
        // response body was not JSON; fall back to the default message
    }
    const resultsEl = document.getElementById('validation-results');
    if (resultsEl) {
        resultsEl.innerHTML = '';
        resultsEl.removeAttribute('hidden');
        const line = document.createElement('div');
        line.className = 'validation-issue validation-issue-error';
        line.textContent = message;
        resultsEl.appendChild(line);
    }
    throw new Error(message);
}

// ── Editor Validation / Save ────────────────────────────────
export async function validateQuadlet() {
    const form = document.getElementById('save-form');
    const serverId = form.querySelector('[name="server_id"]').value;
    const filePath = form.querySelector('[name="file_path"]').value;
    const scope = form.querySelector('[name="scope"]').value;
    const content = window.editor.getValue();

    const body = new FormData();
    body.append('file_path', filePath);
    body.append('scope', scope);
    body.append('content', content);

    const response = await fetch('/api/validate/' + encodeURIComponent(serverId), {
        method: 'POST',
        body: body
    });
    if (!response.ok) {
        await throwValidationRequestError(response);
    }
    const verdict = await response.json();
    const issues = verdict.issues || [];
    const lines = content.split('\n');

    const markers = [];
    issues.forEach(function(issue) {
        if (!issue.key) return;
        for (let i = 0; i < lines.length; i++) {
            const trimmed = lines[i].replace(/^\s+/, '');
            const rest = trimmed.slice(issue.key.length).replace(/^\s+/, '');
            if (trimmed.indexOf(issue.key) === 0 && rest.charAt(0) === '=') {
                markers.push({
                    severity: issue.level === 'error' ? monaco.MarkerSeverity.Error : monaco.MarkerSeverity.Warning,
                    message: issue.message,
                    startLineNumber: i + 1,
                    startColumn: 1,
                    endLineNumber: i + 1,
                    endColumn: lines[i].length + 1
                });
                break;
            }
        }
    });
    monaco.editor.setModelMarkers(window.editor.getModel(), 'quadlet', markers);

    const resultsEl = document.getElementById('validation-results');
    if (resultsEl) {
        resultsEl.innerHTML = '';
        if (verdict.valid && issues.length === 0) {
            resultsEl.setAttribute('hidden', '');
        } else {
            resultsEl.removeAttribute('hidden');
            issues.forEach(function(issue) {
                const line = document.createElement('div');
                line.className = 'validation-issue validation-issue-' + issue.level;
                line.textContent = issue.level + ': ' + issue.message;
                resultsEl.appendChild(line);
            });
            if (verdict.local_only) {
                const note = document.createElement('div');
                note.className = 'validation-note';
                note.textContent = 'local validation only';
                resultsEl.appendChild(note);
            }
        }
    }

    return verdict;
}

export async function saveQuadlet() {
    try {
        const verdict = await validateQuadlet();
        if (!verdict.valid && !confirm('Validation found errors. Save anyway?')) {
            return;
        }
    } catch {
        // validation unavailable — do not block saving
    }

    document.getElementById('hidden-content').value = window.editor.getValue();
    document.getElementById('save-form').dispatchEvent(new Event('submit', {cancelable: true, bubbles: true}));
}

export function initEditor() {
    // ── Monaco Editor Configuration ──────────────────────────
    require.config({ paths: { 'vs': '/static/vendor/monaco/vs' }});

    // Ensure Monaco layout handles window sizing
    window.addEventListener('resize', function() {
        if (window.editor) {
            window.editor.layout();
        }
    });

    // Guard htmx swaps of the editor pane when there are unsaved changes.
    document.body.addEventListener('htmx:confirm', function(evt) {
        const target = evt.detail?.target;
        if (target?.id !== 'editor-pane' || !window._editorDirty) {
            return;
        }
        evt.preventDefault();
        if (confirm('You have unsaved changes in the editor. Discard them?')) {
            evt.detail.issueRequest();
        }
    });

    // The server sets HX-Trigger: quadlet-saved on a successful /api/save response.
    document.body.addEventListener('quadlet-saved', function() {
        window._editorDirty = false;
        const indicator = document.getElementById('unsaved-indicator');
        if (indicator) indicator.setAttribute('hidden', '');
    });
}
