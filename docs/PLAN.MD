# QuadletManager Development Plan

## Objective
Build a self-hosted, agentless web dashboard to manage Podman Quadlets on multiple remote Linux servers via Systemd.

## 1. Backend Infrastructure & Security
* [x] **SSH Tunneling**: Maintain a connection pool (`asyncssh` or `ssh2-promise`) to 5-10 servers to avoid re-auth overhead per HTMX request.
* [x] **Key Encryption**: Master Key in environment variables. Encrypt/decrypt SSH private keys via AES-256-GCM. Decrypt only in memory during the session lifecycle; never store plaintext.
* [x] **Sudo Execution**: All writes to `/etc/containers/systemd/` and `systemctl daemon-reload` prepended with `sudo`.
* [x] **User Scopes**: Rootless targets `~/.config/containers/systemd/` (no sudo, standard user logic). Rootful targets `/etc/containers/systemd/`.

## 2. Database Schema (SQLite)
* [x] `users`: `id, username, password_hash, role` (viewer/editor)
* [x] `servers`: `id, name, ip_address, ssh_user, ssh_key_id`
* [x] `ssh_keys`: `id, key_name, encrypted_private_key`
* [x] `quadlets`: `id, server_id, file_path, scope, last_known_mtime, last_content_hash`
* [x] `templates`: `id, name, type` (container/volume/network/pod), `content`

## 3. The Synchronization Engine
* [x] **Timestamp Polling**: Run background task every 10s -> `stat -c %Y [file]`. Update DB, fetch content via `cat` if remote is newer.
* [x] **Change Notification**: Push SSE/WebSocket message for "File modified externally" to update UI reactively.
* [x] **Collision Avoidance**: Immediately update DB timestamp on Web UI save to prevent false-positive notifications from our own edits.

## 4. Web UI Features (HTMX + Tailwind)
* **Layout**: Three-Pane Layout.
  - Left (Navigator): Server Tree -> Scope -> Files.
  - Center (Editor): Monaco Editor instance.
  - Right (Inspector): `systemctl status` + process resource graphs.
* **Editor Workflow**: Save triggers `hx-post`. 200 OK triggers HTMX Toast notification and right-panel state refresh.
* **Templates**: "New File" modal to inject container/volume/network/pod boilerplate.

## 5. Monitoring & Logs
* [x] **Real-time Logs**: WebSocket connection, run `sudo journalctl -u [unit] -f -n 100`. Catch WebSocket disconnects/kill signals to kill remote processes cleanly.
* [x] **Resource Stats**: `podman stats --no-stream --format "json"` every 5s, visual chart pushed to UI.

## 6. RBAC Logic
* [x] **Viewer Role**: Read-only tree view, logs, stats.
* [x] **Editor Role**: Full CRUD, start/stop capabilities. Checked strictly on Backend and hidden conditionally in UI templates.

## 7. Testing Strategy
* [x] **Unit Testing (Mocked SSH)**: Pure logic, encryption, permission guards, state alerts without actual SSH connection.
* [x] **Integration Testing (Containerized Lab)**: Docker systemd-enabled container to simulate an actual remote target (verifying file DB persistence and valid `systemctl daemon-reload` responses).
* [x] **End-to-End Testing (HTMX Flows)**: Playwright testing of Monaco UI, Toast injections, template workflows, and SSE reactions.
* [x] **Regression Testing**: Syntax validation of standard Quadlet format edge cases.

## 8. Configuration & Deployment
* [x] **App Config**: Provide `config.yaml` to define Master Key and configuration options.
* [x] **Documentation**: Provide a setup guide (`SETUP.MD`) for remote servers with specifics on sudoers configuration and deployment steps.

## 9. Future Work (Not Required for MVP)
* Maintenance & Hardening
  * Security audit — review for edge cases (input sanitization, SSH key handling, session management)
  * Dependency updates — ensure all packages are up to date
  * Error handling — verify graceful recovery in all failure scenarios (SSH drops, DB corruption, etc.)
* New Features
  * Multi-user sessions — allow concurrent editors with conflict resolution
  * Audit log — track who changed what, and when
  * Backup & restore — snapshot quadlet configs before edits
  * Dark/light theme toggle — if not already implemented
  * Notification preferences — Slack/email alerts on file changes or service failures
  * Quadlet dependency visualization — graph relationship between containers, volumes, networks, and pods
* DevOps & Deployment
  * Containerize QuadletManager itself — ship as a Docker/Podman image for easy deployment
  * CI/CD pipeline — automated testing and deployment on push
  * Helm chart or Compose file — one-command deployment
* Documentation
  * User guide / walkthrough — beyond the setup guide, a full usage tutorial
  * API documentation — auto-generated OpenAPI/Swagger docs from FastAPI