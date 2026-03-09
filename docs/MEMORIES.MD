# QuadletManager AI Memories

## Core Directives
* **Goal:** Agentless Web Dashboard for Podman Quadlets via SSH management.
* **Communication Paradigm:** Iterative git commits requested by user to keep a historical log of features added and changes made.
* **Architecture Rules:** Keys unencrypted strictly in memory, HTMX/Tailwind flow on UI.

## Architectural Context
* **Web Interface:** HTMX + TailwindCSS + Monaco Editor snippet injection.
* **Backend:** Python/FastAPI.
* **Database:** SQLite (local file only).
* **Execution Model:** Agentless SSH against remote servers. Rootless/Rootful modes supported based on deployment directory scope.

## Progress & Memory
* **Phase:** Backend infrastructure ready. Implementing systemd control & layout.
* **Current Action:** Setting up `tree_scanner.py` to index remote Quadlets and `systemd_manager.py` to handle systemctl tasks.
* **Next Steps:** Implement daemon-reload handlers and tie file reads/writes to the UI templates.
* **Testing:** 2026-03-08 AI agent successfully updated a file via alternate path, committed, and pushed to Forgejo.
