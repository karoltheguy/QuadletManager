In this project, I need you to create a plan in PLAN.MD which will include the implementation of all the below items.
As I want you to push commits interatively so we can keep a history of features you add and changes you make.
Write yourself memories MEMORIES.MD so we can continue what was started in later time.


Objective: Build a self-hosted, agentless web dashboard to manage Podman Quadlets on multiple remote Linux servers via Systemd.

1. Backend Infrastructure & Security
    SSH Tunneling: Implement a connection manager that uses asyncssh (Python) or ssh2-promise (Node). It must maintain a pool of connections to the 5–10 servers to avoid the overhead of re-authenticating on every HTMX request.
    Key Encryption: * Use a Master Key (stored in an environment variable) to encrypt/decrypt private keys using AES-256-GCM.
        Private keys should never be stored in plain text in the SQLite database.
        Decrypt keys only in memory during the SSH session lifecycle.
    Sudo Execution: All file writes to /etc/containers/systemd/ and systemctl daemon-reload must be prepended with sudo.
    User Scopes:
        Rootless: Target ~/.config/containers/systemd/ (No sudo required).
        Rootful: Target /etc/containers/systemd/ (Sudo required).

2. Database Schema (SQLite)
    users table: id, username, password_hash, role (viewer/editor).
    servers table: id, name, ip_address, ssh_user, ssh_key_id.
    ssh_keys table: id, key_name, encrypted_private_key.
    quadlets table: id, server_id, file_path, scope (global/user), last_known_mtime (integer timestamp), last_content_hash.
    templates table: id, name, type (container/volume/network/pod), content (text).

3. The Synchronization Engine (Agentless)
    Timestamp Polling: A background task must run every 10 seconds.
        Execute: stat -c %Y [file_path].
        If the result is greater than last_known_mtime in the DB, fetch the file content via cat.
    Change Notification: Use HTMX SSE (Server-Sent Events) or a WebSocket to push a "File modified externally" message to the UI.
    Collision Avoidance: When a user saves via the Web UI, the backend must update the last_known_mtime immediately after the write to ensure the poller doesn't flag the UI's own change as an external modification.

4. Web UI Features (HTMX + Tailwind)
    Three-Pane Layout:
        Left (Navigator): A collapsible tree view showing Server -> Scope (Global/User) -> Files.
        Center (Editor): A Monaco Editor instance.
        Right (Inspector): A panel showing systemctl status output and resource graphs.
    The Editor Workflow:
        Save Button: Triggers an hx-post that sends the editor text to the backend.
        Success Feedback: Upon a 200 OK response, HTMX should trigger a "Toast" notification and refresh the status panel on the right.
    Templates: A "New File" modal that allows selecting one of the four Quadlet types, pre-filling the editor with the DB-stored boilerplate.

5. Monitoring & Logs
    Real-time Logs:
        Connect via WebSocket when the "Logs" tab is active.
        Backend command: sudo journalctl -u [unit_name].service -f -n 100.
        The backend must catch the GeneratorExit or WebSocket disconnect signal to kill the journalctl process on the remote host.
    Resource Stats:
        Every 5 seconds, run podman stats --no-stream --format "json".
        Parse the JSON and send it to the UI. Use a small sparkline library (like Chart.js or just CSS bars) to show CPU and Memory usage.

6. RBAC Logic (Permissions)
    View Role:
        Can navigate the file tree.
        Can view logs and stats.
        Cannot save files, delete files, or trigger start/stop/restart actions.
    Editor Role:
        Full access to CRUD operations and service management.
    Visibility Logic: In the HTMX templates, wrap action buttons in conditionals:
    {% if user.role == 'editor' %}<button>Restart</button>{% endif %}

7. Configuration & Deployment
    App Config: A config.yaml to define the Master Key location, session timeouts, and polling frequency.
    Documentation: Provide a setup guide for the remote servers, including the specific sudoers entries required to allow the app to manage systemd units without a password prompt.


Because this app relies heavily on remote system state, your testing strategy must be divided into three distinct layers:

1. Unit Testing (Mocked SSH)
Focus on the "pure" logic of your app without connecting to real servers.
    Method: Use unittest.mock or pytest-mock to simulate the asyncssh or ssh2 responses.
    Test Cases:
        Encryption: Verify that a private key is encrypted before being saved and matches the original after decryption.
        Permission Guard: Test that a viewer role receives a 403 Forbidden when attempting to call the save_file function.
        Timestamp Logic: Provide the "Sync Engine" with a remote timestamp higher than the database timestamp and verify it triggers the "Out of Sync" alert.

2. Integration Testing (Containerized Lab)
Since you can't easily run systemd and podman inside a standard CI/CD runner, use Docker-in-Docker or a specialized Systemd-enabled container as a "Fake Remote Server."
    Method: Spin up a local container running systemd and sshd. Point your app at localhost:[mapped_port].
    Test Cases:
        File CRUD: Does the app successfully write a .container file to /etc/containers/systemd/ inside the test container?
        Daemon Reload: After a save, does systemctl is-active return the expected state?
        Log Streaming: Open a WebSocket and verify that strings printed to the test container's journald appear in the app's output stream.

3. End-to-End (E2E) Testing (HTMX Flows)
Test the "Happy Path" of a user interacting with the UI.
    Method: Use Playwright or Selenium.
    Test Cases:
        The Editor Switch: Click a server in the sidebar -> Verify the Monaco editor loads the correct YAML.
        Template Injection: Click "New from Template" -> Select "Volume" -> Verify the editor content changes to the Volume boilerplate.
        The Polling Alert: Manually touch a file on the "remote" test server and verify the yellow alert banner appears in the browser within 10 seconds without a page refresh.

4. Regression Testing for Quadlet Syntax
Since Quadlets have specific key-value requirements (e.g., [Container], Image=), you should include a validation suite.
    Method: Use a schema validator or a collection of "Known Good" and "Known Bad" Quadlet files.
    Test Cases:
        Verify the app correctly parses a file containing a .pod and its associated .container units.
        Ensure the app doesn't crash if it encounters a malformed unit file on the server.
Note: Each developed features should have unit tests and if possible, integration tests.