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
* **Phase:** Project Complete! All requirements, testing, RGBAC, UI, and configuration are fulfilled.
* **Current Action:** Finalized deployment documentation (SETUP.MD) with configuration details, app login info, and passwordless sudo setups. Checked off final items in PLAN.MD.
* **Next Steps:** Open to new feature requests, patches, or maintenance tasks.
* **Testing:** E2E, Unit, and Integration tests are all functional and the app meets the design requirements.
