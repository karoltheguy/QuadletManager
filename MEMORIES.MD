# QuadletManager AI Memories

## Core Directives
* **Goal:** Agentless Web Dashboard for Podman Quadlets via SSH management.
* **Communication Paradigm:** Iterative git commits requested by user to keep a historical log of features added and changes made.
* **Architecture Rules:** Keys unencrypted strictly in memory, HTMX/Tailwind flow on UI.

## Architectural Context
* **Web Interface:** HTMX + TailwindCSS + Monaco Editor snippet injection.
* **Backend:** [TBD based on user input - Python/FastAPI vs Node/Express].
* **Database:** SQLite (local file only).
* **Execution Model:** Agentless SSH against remote servers. Rootless/Rootful modes supported based on deployment directory scope.

## Progress & Memory
* **Phase:** Initial Planning & Definition.
* **Current Action:** Wrote objective logic into PLAN.MD and setup project tasks. Pending decision on the specific backend technology before implementing the database and server logic.
* **Next Steps:** Setup boilerplate project for chosen stack, create SQLite migrations, implement crypto/SSH utility module, and push next atomic commit.
