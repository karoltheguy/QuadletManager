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
* **Phase:** RBAC logic complete. HTMX UI and testing strategy are also largely complete.
* **Current Action:** Implemented HTTP Basic Auth for strict backend RBAC role enforcement and conditioned HTMX templates based on roles. Seeded default users.
* **Next Steps:** Proceed to finalize any remaining testing strategy items, or any configuration/deployment documentation.
* **Testing:** All units pass test suite seamlessly with RBAC constraints in place.
