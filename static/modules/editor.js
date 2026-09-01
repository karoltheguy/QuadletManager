/* global monaco, require */
/**
 * Monaco editor configuration, validation, and save handling.
 */
import { applyEditorTheme } from '@qm/theme';

// Tracks unsaved edits. main.js's beforeunload handler reads it through
// isEditorDirty(); it was `window._editorDirty` before #468.
let editorDirty = false;

export function isEditorDirty() {
    return editorDirty;
}


// Report a failed validation request in the results pane and throw. Split out
// of validateQuadlet so that function stays under the cognitive-complexity limit.
async function throwValidationRequestError(response) {
    let message = 'Validation request failed with status ' + response.status;
    // A non-JSON body is expected on some error paths, so fall back to the
    // status message rather than letting the parse rejection escape.
    const errorBody = await response.json().catch(function () { return null; });
    if (errorBody && typeof errorBody.error === 'string' && errorBody.error) {
        message = errorBody.error;
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

export function mountEditorPane(targetContainer) {
    // Cancel any pending debounced lint from the previous pane before it can fire
    // against a model we are about to dispose.
    if (window._quadletLintDetach) {
        window._quadletLintDetach();
        window._quadletLintDetach = null;
    }

    // Dispose any previously-running Monaco instance before requesting a new one.
    if (window.editor) {
        var prevModel = window.editor.getModel();
        window.editor.dispose();
        if (prevModel) prevModel.dispose();
        window.editor = null;
    }

    // The caller hands us the container that was in the document when the swap
    // landed, and the file name and content are read off it *synchronously*
    // here, before require fires. Monaco's callback can be delayed past a later
    // swap, and re-reading at that point would write the new pane's file into
    // this editor.
    var fileName = targetContainer ? targetContainer.dataset.fileName : '';
    var fileContent = targetContainer ? targetContainer.dataset.fileContent : '';
    require(['vs/editor/editor.main'], function() {
        if (!window._quadletProvidersRegistered && window.registerQuadletLintProviders) {
            window.registerQuadletLintProviders(monaco, 'ini');
            window._quadletProvidersRegistered = true;
        }

        // Guard: if this container is no longer in the document (i.e. another
        // click happened and HTMX already replaced this pane), skip init.
        if (!document.body.contains(targetContainer)) return;

        var uri = monaco.Uri.file(fileName);
        var old = monaco.editor.getModel(uri);
        if (old) old.dispose();
        var model = monaco.editor.createModel(fileContent, 'ini', uri);

        window.editor = monaco.editor.create(targetContainer, {
            model: model,
            theme: document.documentElement.dataset.theme === 'light' ? 'vs' : 'vs-dark',
            automaticLayout: true
        });
        applyEditorTheme();
        editorDirty = false;
        window.editor.onDidChangeModelContent(function() {
            editorDirty = true;
            var indicator = document.getElementById('unsaved-indicator');
            if (indicator) indicator.removeAttribute('hidden');
        });

        function startQuadletLint() {
            if (!document.body.contains(targetContainer)) return;
            if (window.editor && window.editor.getModel() !== model) return;
            window._quadletLintDetach = window.attachQuadletLint(monaco, model);
        }

        if (window._quadletLintReady) {
            startQuadletLint();
        } else {
            document.addEventListener('quadlet-lint-ready', startQuadletLint, { once: true });
        }
    });
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
        if (target?.id !== 'editor-pane' || !editorDirty) {
            return;
        }
        evt.preventDefault();
        if (confirm('You have unsaved changes in the editor. Discard them?')) {
            evt.detail.issueRequest();
        }
    });

    // The server sets HX-Trigger: quadlet-saved on a successful /api/save response.
    document.body.addEventListener('quadlet-saved', function() {
        editorDirty = false;
        const indicator = document.getElementById('unsaved-indicator');
        if (indicator) indicator.setAttribute('hidden', '');
    });

    // The pane arrives as an htmx swap, so mounting rides on afterSwap
    // rather than an inline script in the partial. Two guards matter: the
    // response also carries out-of-band swaps, so afterSwap fires several
    // times per response, and dashboard.html ships a placeholder
    // #editor-container with no file attributes that must never be mounted.
    document.body.addEventListener('htmx:afterSwap', function() {
        const container = document.getElementById('editor-container');
        if (!container || container.dataset.fileName === undefined) return;
        if (container.dataset.editorMounted) return;
        container.dataset.editorMounted = '1';
        mountEditorPane(container);
    });
}
