// Instantiate Monaco Editor once the DOM loads
require.config({ paths: { 'vs': 'https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.45.0/min/vs' }});

let editor;

require(['vs/editor/editor.main'], function() {
    editor = monaco.editor.create(document.getElementById('editor-container'), {
        value: '[Container]\nImage=docker.io/library/nginx:latest\nNetwork=host\n',
        language: 'ini', /* Systemd files are closest to INI */
        theme: 'vs-dark',
        automaticLayout: true
    });
});

// Hook Monaco into HTMX submission
document.body.addEventListener('htmx:configRequest', function(evt) {
    if (evt.detail.elt.id === "save-btn") {
        evt.detail.parameters['content'] = editor.getValue();
    }
});
